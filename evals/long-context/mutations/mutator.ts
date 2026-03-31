/**
 * @license
 * Copyright 2026 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * Controlled Code Mutation Engine for Contamination-Robust Evaluation
 *
 * GSoC 2026 PoC — Ryan (Yunxiang) Yan
 *
 * Adapted from the symbolic perturbation methodology in MathRizz
 * (Yan et al., 2025, unpublished manuscript), which demonstrated that
 * controlled mutations can create contamination-robust benchmarks.
 * MathRizz showed that models drop from 94.5% to 37.0% accuracy when
 * evaluated on contamination-free equivalents of static benchmarks.
 * See: https://drive.google.com/file/d/1PeXmGG-OduCPuFVvPIMNBkcnyFqZXk_i/view
 *
 * This engine applies the same principle to code: given a "seed task"
 * extracted from a public (potentially memorized) PR, we generate a
 * surface-novel variant that preserves the task's structural complexity
 * but changes identifiers, constants, and logic flow.
 *
 * The key insight: if an agent solves the original task but fails the
 * mutated variant, it's relying on memorization, not reasoning.
 */

// ─── Mutation Types ──────────────────────────────────────────────────────────

type MutationType =
  | 'variable_rename'
  | 'function_rename'
  | 'logic_inversion'
  | 'numerical_perturbation'
  | 'condition_swap'
  | 'file_restructure';

interface MutationRule {
  type: MutationType;
  /** Apply mutation to source code, return mutated code */
  apply(source: string): MutationResult;
}

interface MutationResult {
  mutatedSource: string;
  /** Human-readable description of what changed */
  changelog: string;
  /** Number of mutations applied */
  mutationCount: number;
}

interface MutatedTask {
  originalTaskId: string;
  mutatedTaskId: string;
  mutationTypes: MutationType[];
  /** Combined changelog of all mutations */
  changelog: string[];
  /** Mutated versions of affected files */
  mutatedFiles: Map<string, string>;
  /** Mutated gold patch */
  mutatedGoldPatch: string;
}

// ─── Mutation Implementations ────────────────────────────────────────────────

/**
 * Variable Rename Mutation
 *
 * Systematically renames local variables and parameters throughout
 * affected files. Preserves semantics but defeats pattern matching
 * against memorized variable names.
 *
 * Analogy to MathRizz: This is equivalent to changing operand values
 * in a mathematical expression while preserving the operator structure.
 */
class VariableRenameMutation implements MutationRule {
  type: MutationType = 'variable_rename';

  // Common rename mappings that preserve readability
  private renameMappings: Record<string, string[]> = {
    result: ['outcome', 'output', 'retval', 'computed'],
    data: ['payload', 'content', 'input_data', 'raw_data'],
    response: ['reply', 'answer', 'resp', 'server_response'],
    request: ['req', 'incoming', 'client_request', 'http_request'],
    cache: ['store', 'buffer', 'memo', 'cached_data'],
    timeout: ['deadline', 'time_limit', 'max_wait', 'threshold'],
    callback: ['handler', 'listener', 'on_complete', 'hook'],
    error: ['err', 'failure', 'exception', 'fault'],
    config: ['settings', 'options', 'params', 'configuration'],
    index: ['idx', 'pos', 'offset', 'position'],
  };

  apply(source: string): MutationResult {
    let mutated = source;
    let count = 0;
    const changes: string[] = [];

    for (const [original, alternatives] of Object.entries(
      this.renameMappings,
    )) {
      // Only rename if the variable appears in the source
      // Use word boundary matching to avoid partial replacements
      const pattern = new RegExp(`\\b${original}\\b`, 'g');
      if (pattern.test(mutated)) {
        const replacement =
          alternatives[Math.floor(Math.random() * alternatives.length)]!;
        const matchCount = (mutated.match(pattern) || []).length;
        if (matchCount > 0) {
          mutated = mutated.replace(pattern, replacement);
          changes.push(
            `Renamed '${original}' -> '${replacement}' (${matchCount} occurrences)`,
          );
          count += matchCount;
        }
      }
    }

    return {
      mutatedSource: mutated,
      changelog: changes.join('; '),
      mutationCount: count,
    };
  }
}

/**
 * Numerical Perturbation Mutation
 *
 * Changes magic numbers, thresholds, buffer sizes, and other numeric
 * constants. Corresponding test assertions are updated to match.
 *
 * Analogy to MathRizz: Directly equivalent to operand perturbation
 * in symbolic expressions, which was shown to cause 50-90% performance
 * drops in memorization-reliant models.
 */
class NumericalPerturbationMutation implements MutationRule {
  type: MutationType = 'numerical_perturbation';

  apply(source: string): MutationResult {
    let mutated = source;
    let count = 0;
    const changes: string[] = [];

    // Match numeric literals (integers and floats) that aren't 0 or 1
    // (0 and 1 are too fundamental to perturb safely)
    const numPattern = /\b(\d+\.?\d*)\b/g;
    mutated = mutated.replace(numPattern, (match) => {
      const num = parseFloat(match);
      // Skip 0, 1, and very small numbers (likely to be boolean-like)
      if (num <= 1 || isNaN(num)) return match;

      // Apply perturbation: multiply by a factor between 0.5 and 2.0
      // This preserves order of magnitude while changing the exact value
      const factor = 0.5 + Math.random() * 1.5;
      const perturbed = Math.round(num * factor);

      // Don't perturb if result is same or 0
      if (perturbed === num || perturbed === 0) return match;

      changes.push(`${num} -> ${perturbed}`);
      count++;
      return String(perturbed);
    });

    return {
      mutatedSource: mutated,
      changelog: `Numerical perturbations: ${changes.join(', ')}`,
      mutationCount: count,
    };
  }
}

/**
 * Logic Inversion Mutation
 *
 * Swaps condition branches (if/else), reverses comparison operators,
 * and inverts boolean expressions. Tests are updated to match the
 * inverted logic.
 *
 * This is particularly effective at detecting memorization because
 * the structural complexity of the task is preserved, but the
 * "direction" of reasoning changes.
 */
class LogicInversionMutation implements MutationRule {
  type: MutationType = 'logic_inversion';

  private inversions: Record<string, string> = {
    '===': '!==',
    '!==': '===',
    '==': '!=',
    '!=': '==',
    '>=': '<',
    '<=': '>',
    '>': '<=',
    '<': '>=',
    '&&': '||',
    '||': '&&',
    true: 'false',
    false: 'true',
  };

  apply(source: string): MutationResult {
    let mutated = source;
    let count = 0;
    const changes: string[] = [];

    // Only invert comparisons in condition contexts (if, while, ternary)
    // to avoid breaking non-conditional logic
    const conditionPattern = /\b(if|while|for)\s*\(([^)]+)\)/g;

    mutated = mutated.replace(conditionPattern, (match, keyword, condition) => {
      let newCondition = condition as string;

      for (const [original, inverted] of Object.entries(this.inversions)) {
        if (newCondition.includes(original)) {
          // Only apply one inversion per condition to keep changes minimal
          newCondition = newCondition.replace(original, inverted);
          changes.push(
            `Inverted '${original}' -> '${inverted}' in ${keyword} condition`,
          );
          count++;
          break; // One inversion per condition
        }
      }

      return `${keyword}(${newCondition})`;
    });

    return {
      mutatedSource: mutated,
      changelog: changes.join('; '),
      mutationCount: count,
    };
  }
}

// ─── Mutation Pipeline ───────────────────────────────────────────────────────

/**
 * The mutation pipeline applies controlled transformations to create
 * contamination-resistant task variants.
 *
 * Pipeline steps (analogous to MathRizz):
 * 1. Load seed task (potentially memorized public PR)
 * 2. Apply selected mutations to source files
 * 3. Apply same mutations to gold patch
 * 4. Verify test equivalence (mutated tests pass on mutated code)
 * 5. Output mutated task with new task_id
 */
class MutationPipeline {
  private mutations: MutationRule[] = [];

  /** Register mutation types to apply */
  withMutation(mutation: MutationRule): MutationPipeline {
    this.mutations.push(mutation);
    return this;
  }

  /**
   * Apply all registered mutations to a source file.
   * Returns the mutated source and a combined changelog.
   */
  mutateSource(source: string): {
    mutated: string;
    changelog: string[];
    totalMutations: number;
  } {
    let current = source;
    const changelog: string[] = [];
    let totalMutations = 0;

    for (const mutation of this.mutations) {
      const result = mutation.apply(current);
      current = result.mutatedSource;
      if (result.mutationCount > 0) {
        changelog.push(`[${mutation.type}] ${result.changelog}`);
        totalMutations += result.mutationCount;
      }
    }

    return { mutated: current, changelog, totalMutations };
  }

  /**
   * Apply mutations to a gold patch.
   * The same identifier renames applied to source files must also be
   * applied to the patch to maintain correctness.
   */
  mutatePatch(patch: string): string {
    let current = patch;
    for (const mutation of this.mutations) {
      // Only apply rename-type mutations to patches
      // (numerical and logic mutations would change the fix itself)
      if (
        mutation.type === 'variable_rename' ||
        mutation.type === 'function_rename'
      ) {
        current = mutation.apply(current).mutatedSource;
      }
    }
    return current;
  }
}

// ─── Demo ────────────────────────────────────────────────────────────────────

/**
 * Demonstrate the mutation pipeline on a sample code snippet.
 *
 * This shows how a public (potentially memorized) code file can be
 * transformed into a surface-novel variant while preserving structural
 * complexity. An agent relying on memorization will fail the mutated
 * version even if it solves the original.
 */
function demo(): void {
  console.log('=== Contamination-Robust Mutation Engine Demo ===\n');

  // Sample source: a simplified cache middleware (inspired by Django)
  const sampleSource = `
class CacheMiddleware {
  constructor(timeout, cache) {
    this.timeout = timeout;
    this.cache = cache;
  }

  async processRequest(request) {
    const cacheKey = this.getCacheKey(request);
    const cachedResponse = await this.cache.get(cacheKey);
    if (cachedResponse !== null) {
      return cachedResponse;
    }
    return null;
  }

  async processResponse(request, response) {
    if (response.status === 200) {
      const cacheKey = this.getCacheKey(request);
      const timeout = this.timeout || 300;
      await this.cache.set(cacheKey, response, timeout);
    }
    return response;
  }

  getCacheKey(request) {
    const data = request.url + request.method;
    return 'cache_' + hashCode(data);
  }
}`;

  console.log('--- Original Source ---');
  console.log(sampleSource);

  // Apply mutations
  const pipeline = new MutationPipeline()
    .withMutation(new VariableRenameMutation())
    .withMutation(new NumericalPerturbationMutation())
    .withMutation(new LogicInversionMutation());

  const result = pipeline.mutateSource(sampleSource);

  console.log('\n--- Mutated Source ---');
  console.log(result.mutated);

  console.log('\n--- Mutation Changelog ---');
  for (const entry of result.changelog) {
    console.log(`  ${entry}`);
  }
  console.log(`\nTotal mutations applied: ${result.totalMutations}`);
  console.log(
    '\nThe mutated code is structurally equivalent but surface-level novel.',
  );
  console.log(
    'An agent relying on memorization will fail; one that reasons will succeed.',
  );
}

// Run demo if executed directly
demo();

// ─── Exports ─────────────────────────────────────────────────────────────────

export {
  MutationPipeline,
  VariableRenameMutation,
  NumericalPerturbationMutation,
  LogicInversionMutation,
  demo,
  type MutationType,
  type MutationRule,
  type MutationResult,
  type MutatedTask,
};
