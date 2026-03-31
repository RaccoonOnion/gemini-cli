#!/usr/bin/env python3
"""
Task Extraction Pipeline for Long-Context Coding Evaluation

GSoC 2026 PoC — Ryan (Yunxiang) Yan

Mines merged pull requests from curated repositories to extract
engineering tasks that require long-context, multi-file reasoning.

Implements Phase 2 of the proposal:
- PR mining with multi-file filters
- Tier 1 validation (dependency analysis via file co-change)
- Task difficulty categorization (L1/L2/L3)

Usage:
    python extract_tasks.py [--repos django/django expressjs/express] [--limit 5]
"""

import json
import subprocess
import sys
import os
import argparse
from dataclasses import dataclass


@dataclass
class CandidateTask:
    repo: str
    pr_number: int
    title: str
    files_changed: int
    additions: int
    deletions: int
    labels: list[str]
    merged_at: str
    # Extracted data
    changed_files: list[str] = None
    modules_touched: set[str] = None
    has_tests: bool = False
    difficulty: str = "L1"
    # Validation
    passes_tier1: bool = False
    rejection_reason: str = ""

    def __post_init__(self):
        if self.changed_files is None:
            self.changed_files = []
        if self.modules_touched is None:
            self.modules_touched = set()


def run_gh(args: list[str], fallback: str = "[]") -> str:
    """Run a gh CLI command and return stdout."""
    try:
        result = subprocess.run(
            ["gh"] + args,
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return fallback
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return fallback


def fetch_merged_prs(repo: str, limit: int = 20) -> list[dict]:
    """Fetch recently merged PRs that touch multiple files."""
    raw = run_gh([
        "api", f"repos/{repo}/pulls",
        "--method", "GET",
        "-f", "state=closed",
        "-f", "sort=updated",
        "-f", "direction=desc",
        "-f", f"per_page={limit}",
        "--jq", (
            '[.[] | select(.merged_at != null) | '
            '{number: .number, title: .title, '
            'labels: [.labels[].name], '
            'merged_at: .merged_at}]'
        ),
    ])
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def fetch_pr_files(repo: str, pr_number: int) -> list[dict]:
    """Fetch the list of files changed in a PR."""
    raw = run_gh([
        "api", f"repos/{repo}/pulls/{pr_number}/files",
        "--jq", (
            '[.[] | {filename: .filename, status: .status, '
            'additions: .additions, deletions: .deletions, '
            'changes: .changes}]'
        ),
    ])
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def extract_module(filepath: str) -> str:
    """Extract the top-level module/directory from a file path."""
    parts = filepath.split("/")
    if len(parts) >= 2:
        return parts[0] + "/" + parts[1] if len(parts) > 2 else parts[0]
    return parts[0]


def is_mechanical_change(title: str, files: list[dict]) -> bool:
    """Filter out purely mechanical changes (formatting, deps, renames)."""
    mechanical_keywords = [
        "bump", "update dependency", "formatting", "lint",
        "typo", "readme", "changelog", "version", "ci:",
        "chore:", "docs:", "style:", "deprecat",
        "rename", "revert", ".editorconfig",
    ]
    title_lower = title.lower()
    if any(kw in title_lower for kw in mechanical_keywords):
        return True

    # Check if all files are docs/configs
    non_code_extensions = {
        ".md", ".txt", ".yml", ".yaml", ".toml", ".cfg",
        ".ini", ".json", ".lock", ".gitignore", ".editorconfig",
    }
    code_files = [
        f for f in files
        if not any(f["filename"].endswith(ext) for ext in non_code_extensions)
    ]
    if len(code_files) == 0:
        return True

    return False


def has_test_changes(files: list[dict]) -> bool:
    """Check if the PR includes test file changes."""
    test_patterns = ["test", "spec", "__tests__", "_test.", ".test.", "tests/"]
    return any(
        any(p in f["filename"].lower() for p in test_patterns)
        for f in files
    )


def categorize_difficulty(
    files_changed: int, modules: set[str], has_tests: bool
) -> str:
    """
    Categorize task difficulty:
    L1: Cross-file bug fix (2-3 files, 1-2 modules)
    L2: Multi-module feature (4+ files, 2+ modules)
    L3: Architectural refactor (6+ files, 3+ modules)
    """
    n_modules = len(modules)
    if files_changed >= 6 and n_modules >= 3:
        return "L3"
    elif files_changed >= 4 and n_modules >= 2:
        return "L2"
    elif files_changed >= 2:
        return "L1"
    return "L1"


def tier1_validate(files: list[dict]) -> bool:
    """
    Tier 1 Validation: Dependency analysis via file co-change heuristic.

    A task passes Tier 1 if:
    - It touches files in >= 2 different modules/directories
    - At least one source file AND one test file are changed
    - The changes aren't purely additive (there are deletions too)

    Full implementation would use tree-sitter for import/call graph analysis.
    This PoC uses co-change heuristics as a proxy.
    """
    modules = set()
    has_source = False
    has_test = False
    has_deletions = False

    for f in files:
        module = extract_module(f["filename"])
        modules.add(module)

        if f.get("deletions", 0) > 0:
            has_deletions = True

        fname_lower = f["filename"].lower()
        if any(t in fname_lower for t in ["test", "spec", "__tests__"]):
            has_test = True
        else:
            has_source = True

    return len(modules) >= 2 and has_source and has_test and has_deletions


def generate_task_json(task: CandidateTask, task_index: int) -> dict:
    """Generate a task JSON following the schema."""
    repo_short = task.repo.split("/")[-1]
    task_id = f"{repo_short}-{task_index:03d}"

    return {
        "task_id": task_id,
        "repository": {
            "name": task.repo,
            "commit_sha": "TODO_PIN_COMMIT",
            "languages": [detect_language(task.changed_files)],
            "loc": 0,
            "setup_commands": []
        },
        "problem": {
            "description": task.title,
            "source_pr": f"https://github.com/{task.repo}/pull/{task.pr_number}",
            "difficulty": task.difficulty,
            "category": categorize_from_title(task.title),
            "task_type": "cross_module" if len(task.modules_touched) >= 2 else "single_language",
            "required_context_files": task.changed_files[:10],
            "estimated_context_tokens": estimate_tokens(task.additions + task.deletions),
            "anti_shortcut_tags": detect_anti_shortcut_tags(task),
        },
        "ground_truth": {
            "gold_patch": f"TODO: extract from PR #{task.pr_number}",
            "test_files": [
                f for f in task.changed_files
                if any(t in f.lower() for t in ["test", "spec"])
            ],
            "verification_command": "TODO",
            "gold_quality_metrics": {
                "patch_locality_score": 0.0,
                "duplication_delta": 0,
                "complexity_delta": 0,
                "import_delta": 0
            }
        },
        "contamination": {
            "has_mutated_variant": False,
            "seed_pr_public": True
        },
        "metadata": {
            "long_context_tier": 1,
            "files_touched": len(task.changed_files),
            "modules_touched": len(task.modules_touched),
            "languages_touched": 1,
            "reasoning_chain_length": max(2, len(task.modules_touched)),
            "extracted_by": "pr_mining",
            "human_validated": False,
        }
    }


def detect_language(files: list[str]) -> str:
    """Detect primary language from file extensions."""
    ext_map = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".go": "go", ".rs": "rust", ".java": "java",
        ".c": "c", ".cpp": "cpp", ".h": "c",
    }
    counts: dict[str, int] = {}
    for f in files:
        ext = os.path.splitext(f)[1]
        lang = ext_map.get(ext, "unknown")
        counts[lang] = counts.get(lang, 0) + 1
    return max(counts, key=counts.get) if counts else "unknown"


def categorize_from_title(title: str) -> str:
    """Categorize task type from PR title."""
    t = title.lower()
    if any(w in t for w in ["fix", "bug", "crash", "error", "issue"]):
        return "bug_fix"
    elif any(w in t for w in ["feat", "add", "implement", "support"]):
        return "feature"
    elif any(w in t for w in ["refactor", "clean", "restructure", "move"]):
        return "refactor"
    elif any(w in t for w in ["perf", "optim", "speed", "fast"]):
        return "performance"
    elif any(w in t for w in ["secur", "vuln", "cve", "auth"]):
        return "security"
    return "bug_fix"


def estimate_tokens(total_lines: int) -> int:
    """Rough estimate: 1 line ≈ 10 tokens for context files."""
    return total_lines * 10


def detect_anti_shortcut_tags(task: CandidateTask) -> list[str]:
    """Detect anti-shortcut properties from task metadata."""
    tags = []
    if len(task.modules_touched) >= 3:
        tags.append("multi_solution")
    # Check for files with similar names across modules (retrieval trap potential)
    basenames = [os.path.basename(f) for f in task.changed_files]
    if len(basenames) != len(set(basenames)):
        tags.append("retrieval_trap")
    return tags


def main():
    parser = argparse.ArgumentParser(description="Extract tasks from curated repos")
    parser.add_argument("--repos", nargs="+", default=None, help="Repos to scan")
    parser.add_argument("--limit", type=int, default=10, help="PRs to fetch per repo")
    parser.add_argument("--output-dir", type=str, default=None)
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = args.output_dir or os.path.join(script_dir, "..", "tasks")
    os.makedirs(output_dir, exist_ok=True)

    # Default: scan a diverse subset
    repos = args.repos or [
        "django/django",
        "expressjs/express",
        "kubernetes/kubernetes",
        "rust-lang/rust",
        "microsoft/TypeScript",
        "redis/redis",
    ]

    print("=== Long-Context Eval: Task Extraction Pipeline ===\n")

    all_tasks: list[dict] = []
    task_counter = 1

    for repo in repos:
        print(f"--- {repo} ---")
        print(f"  Fetching merged PRs (limit={args.limit})...")

        prs = fetch_merged_prs(repo, limit=args.limit)
        print(f"  Found {len(prs)} merged PRs")

        extracted = 0
        for pr in prs:
            pr_num = pr["number"]
            title = pr["title"]

            sys.stdout.write(f"  PR #{pr_num}: {title[:60]}... ")
            sys.stdout.flush()

            # Fetch file details
            files = fetch_pr_files(repo, pr_num)

            if not files or len(files) < 3:
                print(f"SKIP (only {len(files)} files)")
                continue

            if is_mechanical_change(title, files):
                print("SKIP (mechanical)")
                continue

            # Build candidate
            candidate = CandidateTask(
                repo=repo,
                pr_number=pr_num,
                title=title,
                files_changed=len(files),
                additions=sum(f.get("additions", 0) for f in files),
                deletions=sum(f.get("deletions", 0) for f in files),
                labels=pr.get("labels", []),
                merged_at=pr.get("merged_at", ""),
                changed_files=[f["filename"] for f in files],
                modules_touched=set(extract_module(f["filename"]) for f in files),
                has_tests=has_test_changes(files),
            )

            # Tier 1 validation
            candidate.passes_tier1 = tier1_validate(files)
            if not candidate.passes_tier1:
                print("SKIP (fails Tier 1)")
                continue

            # Categorize difficulty
            candidate.difficulty = categorize_difficulty(
                len(files), candidate.modules_touched, candidate.has_tests
            )

            # Generate task JSON
            task_json = generate_task_json(candidate, task_counter)
            task_counter += 1
            extracted += 1

            # Write task file
            task_path = os.path.join(output_dir, f"{task_json['task_id']}.json")
            with open(task_path, "w") as f:
                json.dump(task_json, f, indent=2)

            all_tasks.append(task_json)
            print(f"EXTRACTED [{candidate.difficulty}] ({len(files)} files, {len(candidate.modules_touched)} modules)")

        print(f"  Extracted {extracted} tasks from {repo}\n")

    # Summary
    print("=== Extraction Summary ===")
    print(f"Total tasks extracted: {len(all_tasks)}")

    diff_dist = {"L1": 0, "L2": 0, "L3": 0}
    cat_dist: dict[str, int] = {}
    for t in all_tasks:
        d = t["problem"]["difficulty"]
        diff_dist[d] = diff_dist.get(d, 0) + 1
        c = t["problem"]["category"]
        cat_dist[c] = cat_dist.get(c, 0) + 1

    print(f"Difficulty: L1={diff_dist['L1']}, L2={diff_dist['L2']}, L3={diff_dist['L3']}")
    print(f"Categories: {', '.join(f'{k}={v}' for k, v in cat_dist.items())}")
    print(f"\nTasks written to: {output_dir}/")


if __name__ == "__main__":
    main()
