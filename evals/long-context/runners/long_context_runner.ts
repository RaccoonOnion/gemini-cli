/**
 * @license
 * Copyright 2026 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * Long-Context Coding Evaluation Runner
 *
 * GSoC 2026 PoC — Ryan (Yunxiang) Yan
 *
 * This runner executes long-context coding evaluation tasks against Gemini CLI.
 * Unlike behavioral evals that test granular agent behaviors on synthetic codebases,
 * this runner tests multi-file reasoning on real-world repositories.
 *
 * Key features:
 * - Clones real repositories at pinned commits for reproducibility
 * - Presents engineering problems requiring cross-file reasoning
 * - Evaluates both correctness (test pass/fail) and code quality
 * - Supports contamination analysis via original/mutated task pairs
 */

import fs from 'node:fs';
import path from 'node:path';

// ─── Types ───────────────────────────────────────────────────────────────────

/** Code quality metrics computed via AST analysis (Novel Dimension B) */
interface CodeQualityMetrics {
  /** Ratio of lines changed vs. minimum necessary (from gold patch). 0-1, higher = more precise */
  patchLocalityScore: number;
  /** Lines of new code duplicated from existing codebase */
  duplicationDelta: number;
  /** Change in cyclomatic complexity before/after patch */
  complexityDelta: number;
  /** New imports or dependencies added beyond gold patch */
  importDelta: number;
  /** Does the patch follow existing code patterns? 0-1 heuristic */
  architecturalAlignment: number;
}

/** Result of running a single evaluation task */
interface EvalResult {
  taskId: string;
  /** Whether the agent's patch passes all verification tests */
  passed: boolean;
  /** Fraction of test assertions passing (for partial credit) */
  partialScore: number;
  /** Code quality metrics comparing agent patch vs. gold patch */
  codeQuality: CodeQualityMetrics;
  /** Failure mode classification */
  failureMode: FailureMode | null;
  /** Performance metrics */
  performance: {
    /** Total tokens consumed during the task */
    tokensConsumed: number;
    /** Number of tool calls made by the agent */
    toolCalls: number;
    /** Wall-clock time in seconds */
    wallTimeSeconds: number;
    /** Files the agent explored vs. files required */
    contextUtilization: number;
  };
  /** Contamination analysis (if mutated variant exists) */
  contaminationDelta: number | null;
}

/** Failure modes from the evaluation taxonomy */
type FailureMode =
  | 'navigation_failure'
  | 'dependency_blindness'
  | 'partial_fix'
  | 'context_overflow'
  | 'retrieval_trap'
  | 'entropy_explosion'
  | 'copy_paste_shortcut'
  | 'hallucinated_fix'
  | 'memorization_leak'
  | 'tool_misuse';

/** Task definition loaded from JSON */
interface LongContextTask {
  task_id: string;
  repository: {
    name: string;
    commit_sha: string;
    languages: string[];
    loc: number;
    setup_commands: string[];
  };
  problem: {
    description: string;
    difficulty: 'L1' | 'L2' | 'L3';
    category: string;
    task_type: string;
    required_context_files: string[];
    estimated_context_tokens: number;
    anti_shortcut_tags: string[];
  };
  ground_truth: {
    gold_patch: string;
    test_files: string[];
    verification_command: string;
    gold_quality_metrics: CodeQualityMetrics;
  };
  contamination?: {
    has_mutated_variant: boolean;
    mutated_task_id?: string;
  };
  metadata: {
    long_context_tier: number;
    files_touched: number;
    modules_touched: number;
    reasoning_chain_length: number;
  };
}

// ─── Registry ────────────────────────────────────────────────────────────────

interface TaskRegistry {
  dataset_version: string;
  tasks: Array<{
    task_id: string;
    file: string;
    difficulty: string;
    has_mutated_variant: boolean;
  }>;
}

/** Load task registry and resolve task file paths */
function loadRegistry(registryPath: string): TaskRegistry {
  const content = fs.readFileSync(registryPath, 'utf-8');
  return JSON.parse(content) as TaskRegistry;
}

/** Load a single task definition from JSON */
function loadTask(taskDir: string, taskFile: string): LongContextTask {
  const fullPath = path.join(taskDir, taskFile);
  const content = fs.readFileSync(fullPath, 'utf-8');
  return JSON.parse(content) as LongContextTask;
}

// ─── Code Quality Analysis (Novel Dimension B) ──────────────────────────────

/**
 * Compute code quality metrics by comparing agent patch against gold patch.
 *
 * This detects "entropy explosion" — patches that pass tests but degrade
 * codebase maintainability by adding unnecessary complexity, duplicating
 * code, or bolting on fixes rather than integrating into existing logic.
 *
 * Implementation note: Full AST-based analysis requires tree-sitter.
 * This PoC uses line-based heuristics as a proof of concept.
 */
function computeCodeQuality(
  agentPatch: string,
  goldPatch: string,
): CodeQualityMetrics {
  const agentLines = parsePatchLines(agentPatch);
  const goldLines = parsePatchLines(goldPatch);

  // Patch Locality: How close is the agent's patch size to the gold patch?
  // Score of 1.0 means identical size; lower means agent over-engineered
  const patchLocalityScore =
    goldLines.additions > 0
      ? Math.min(1, goldLines.additions / Math.max(agentLines.additions, 1))
      : 1;

  // Duplication: Count lines in agent patch that appear elsewhere in codebase
  // (Simplified: count lines that are exact duplicates of other added lines)
  const addedLines = agentPatch
    .split('\n')
    .filter((l) => l.startsWith('+') && !l.startsWith('+++'));
  const uniqueAdded = new Set(addedLines.map((l) => l.trim()));
  const duplicationDelta = addedLines.length - uniqueAdded.size;

  // Complexity: Heuristic — count new conditional branches added
  const agentBranches = countBranches(agentPatch);
  const goldBranches = countBranches(goldPatch);
  const complexityDelta = agentBranches - goldBranches;

  // Import: Count new import/require lines added
  const agentImports = countImports(agentPatch);
  const goldImports = countImports(goldPatch);
  const importDelta = agentImports - goldImports;

  // Architectural Alignment: Heuristic — does agent modify same files as gold?
  const agentFiles = extractFiles(agentPatch);
  const goldFiles = extractFiles(goldPatch);
  const fileOverlap = agentFiles.filter((f) => goldFiles.includes(f)).length;
  const architecturalAlignment =
    goldFiles.length > 0 ? fileOverlap / goldFiles.length : 0;

  return {
    patchLocalityScore,
    duplicationDelta,
    complexityDelta,
    importDelta,
    architecturalAlignment,
  };
}

/** Parse a unified diff to count additions and deletions */
function parsePatchLines(patch: string): {
  additions: number;
  deletions: number;
} {
  const lines = patch.split('\n');
  let additions = 0;
  let deletions = 0;
  for (const line of lines) {
    if (line.startsWith('+') && !line.startsWith('+++')) additions++;
    if (line.startsWith('-') && !line.startsWith('---')) deletions++;
  }
  return { additions, deletions };
}

/** Count conditional branches (if, else, switch, case, ternary) in a patch */
function countBranches(patch: string): number {
  const branchPatterns = /\b(if|else|switch|case|catch)\b|\?.*:/g;
  const addedLines = patch
    .split('\n')
    .filter((l) => l.startsWith('+') && !l.startsWith('+++'));
  return addedLines.reduce((count, line) => {
    const matches = line.match(branchPatterns);
    return count + (matches ? matches.length : 0);
  }, 0);
}

/** Count import/require statements in added lines */
function countImports(patch: string): number {
  const importPattern = /\b(import|require|from)\b/;
  return patch
    .split('\n')
    .filter((l) => l.startsWith('+') && !l.startsWith('+++'))
    .filter((l) => importPattern.test(l)).length;
}

/** Extract file paths from a unified diff */
function extractFiles(patch: string): string[] {
  return patch
    .split('\n')
    .filter((l) => l.startsWith('+++ b/'))
    .map((l) => l.replace('+++ b/', ''));
}

// ─── Failure Mode Classification ─────────────────────────────────────────────

/**
 * Classify the failure mode based on the agent's behavior and output.
 *
 * Uses heuristics on the agent's tool call log, patch, and test results
 * to categorize failures into actionable categories.
 */
function classifyFailureMode(
  task: LongContextTask,
  agentPatch: string,
  testsPassed: boolean,
  filesExplored: string[],
): FailureMode | null {
  if (testsPassed) return null;

  const requiredFiles = task.problem.required_context_files;
  const exploredSet = new Set(filesExplored);
  const requiredExplored = requiredFiles.filter((f) => exploredSet.has(f));

  // Did the agent fail to find the right files?
  if (requiredExplored.length < requiredFiles.length * 0.5) {
    // Check if it fell for a retrieval trap
    if (task.problem.anti_shortcut_tags.includes('has_legacy_code')) {
      return 'retrieval_trap';
    }
    return 'navigation_failure';
  }

  // Did the agent produce no patch at all?
  if (!agentPatch || agentPatch.trim().length === 0) {
    return 'context_overflow';
  }

  // Did the agent only partially fix the issue?
  const patchFiles = extractFiles(agentPatch);
  const goldFiles = extractFiles(task.ground_truth.gold_patch);
  if (patchFiles.length < goldFiles.length) {
    return 'dependency_blindness';
  }

  // Default: hallucinated fix (produced a patch but tests fail)
  return 'hallucinated_fix';
}

// ─── Main Runner ─────────────────────────────────────────────────────────────

/**
 * Run a single long-context evaluation task.
 *
 * This is a skeleton that demonstrates the evaluation flow.
 * Full implementation requires:
 * - Git clone and setup automation
 * - Gemini CLI agent invocation
 * - Test execution and result parsing
 */
async function runTask(task: LongContextTask): Promise<EvalResult> {
  console.log(`[long-context-eval] Running task: ${task.task_id}`);
  console.log(`  Repository: ${task.repository.name}`);
  console.log(`  Difficulty: ${task.problem.difficulty}`);
  console.log(`  Required files: ${task.problem.required_context_files.length}`);
  console.log(`  Est. context tokens: ${task.problem.estimated_context_tokens}`);

  // TODO: Full implementation steps:
  // 1. git clone --depth=1 --branch=<commit> <repo>
  // 2. Run setup_commands
  // 3. Invoke Gemini CLI with task.problem.description
  // 4. Capture agent's patch
  // 5. Apply patch and run verification_command
  // 6. Compute code quality metrics
  // 7. Classify failure mode if applicable

  // Placeholder result for PoC
  const agentPatch = ''; // Would come from Gemini CLI
  const testsPassed = false;
  const filesExplored: string[] = [];

  const codeQuality = computeCodeQuality(
    agentPatch,
    task.ground_truth.gold_patch,
  );
  const failureMode = classifyFailureMode(
    task,
    agentPatch,
    testsPassed,
    filesExplored,
  );

  return {
    taskId: task.task_id,
    passed: testsPassed,
    partialScore: 0,
    codeQuality,
    failureMode,
    performance: {
      tokensConsumed: 0,
      toolCalls: 0,
      wallTimeSeconds: 0,
      contextUtilization: 0,
    },
    contaminationDelta: null,
  };
}

/**
 * Run all tasks in the registry and generate a report.
 */
async function runAll(baseDir: string): Promise<void> {
  const registry = loadRegistry(path.join(baseDir, 'registry.json'));
  const results: EvalResult[] = [];

  console.log(
    `[long-context-eval] Dataset v${registry.dataset_version}`,
  );
  console.log(
    `[long-context-eval] Running ${registry.tasks.length} tasks\n`,
  );

  for (const taskEntry of registry.tasks) {
    const task = loadTask(baseDir, taskEntry.file);
    const result = await runTask(task);
    results.push(result);
    console.log(
      `  Result: ${result.passed ? 'PASS' : 'FAIL'}${result.failureMode ? ` (${result.failureMode})` : ''}\n`,
    );
  }

  // Generate summary report
  const passed = results.filter((r) => r.passed).length;
  const total = results.length;
  console.log(`[long-context-eval] Summary: ${passed}/${total} passed`);

  // Write results to JSON
  const reportPath = path.join(baseDir, 'results.json');
  fs.writeFileSync(reportPath, JSON.stringify({ results }, null, 2));
  console.log(`[long-context-eval] Results written to ${reportPath}`);
}

// ─── Exports ─────────────────────────────────────────────────────────────────

export {
  runAll,
  runTask,
  loadRegistry,
  loadTask,
  computeCodeQuality,
  classifyFailureMode,
  type EvalResult,
  type CodeQualityMetrics,
  type FailureMode,
  type LongContextTask,
};
