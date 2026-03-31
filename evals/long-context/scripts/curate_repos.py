#!/usr/bin/env python3
"""
Repository Curation Pipeline for Long-Context Coding Evaluation

GSoC 2026 PoC — Ryan (Yunxiang) Yan

Scans GitHub for large, actively maintained, architecturally complex
repositories across 6+ languages. Scores each repository on a rubric
and outputs manifests for the evaluation dataset.

Usage:
    python curate_repos.py [--min-repos 30] [--output-dir ../manifests]
"""

import json
import subprocess
import sys
import os
import argparse
from dataclasses import dataclass, field, asdict
from typing import Optional

# ─── Configuration ────────────────────────────────────────────────────────────

# Seed repositories: well-known large repos across 6+ languages
# These are pre-selected candidates that meet our criteria
SEED_REPOS = {
    "python": [
        "django/django",
        "pallets/flask",
        "tiangolo/fastapi",
        "psf/requests",
        "scikit-learn/scikit-learn",
        "pandas-dev/pandas",
        "pytorch/pytorch",
        "huggingface/transformers",
        "ansible/ansible",
        "celery/celery",
    ],
    "typescript": [
        "microsoft/TypeScript",
        "microsoft/vscode",
        "vercel/next.js",
        "vitejs/vite",
        "prisma/prisma",
        "grafana/grafana",
        "n8n-io/n8n",
        "supabase/supabase",
    ],
    "javascript": [
        "expressjs/express",
        "webpack/webpack",
        "facebook/react",
        "nodejs/node",
        "mrdoob/three.js",
        "socketio/socket.io",
    ],
    "go": [
        "kubernetes/kubernetes",
        "golang/go",
        "docker/cli",
        "hashicorp/terraform",
        "prometheus/prometheus",
        "etcd-io/etcd",
    ],
    "rust": [
        "rust-lang/rust",
        "denoland/deno",
        "tauri-apps/tauri",
        "tokio-rs/tokio",
        "astral-sh/ruff",
    ],
    "c_cpp": [
        "redis/redis",
        "sqlite/sqlite",
        "nginx/nginx",
        "curl/curl",
        "postgres/postgres",
    ],
    "java": [
        "spring-projects/spring-boot",
        "elastic/elasticsearch",
        "apache/kafka",
        "google/guava",
        "ReactiveX/RxJava",
    ],
}


@dataclass
class RepoScore:
    name: str
    language: str
    loc: int = 0
    stars: int = 0
    recent_commits: int = 0
    has_tests: bool = False
    has_ci: bool = False
    license: str = ""
    default_branch: str = "main"
    description: str = ""
    # Scoring
    loc_score: int = 0           # 0-5: based on LOC thresholds
    maintenance_score: int = 0   # 0-5: based on recent commit activity
    complexity_score: int = 0    # 0-5: heuristic from repo structure
    test_score: int = 0          # 0-5: test infrastructure quality
    total_score: int = 0
    # Rejection
    rejected: bool = False
    rejection_reason: str = ""


def run_gh(args: list[str], fallback: str = "{}") -> str:
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


def fetch_repo_info(repo: str) -> dict:
    """Fetch repository metadata via GitHub API."""
    raw = run_gh([
        "api", f"repos/{repo}",
        "--jq", json.dumps({
            "stars": ".stargazers_count",
            "license": ".license.spdx_id // \"unknown\"",
            "description": ".description // \"\"",
            "default_branch": ".default_branch",
            "language": ".language // \"unknown\"",
            "size": ".size",
            "archived": ".archived",
            "fork": ".fork",
        }).replace('"', '"')
    ])
    # gh --jq with object syntax doesn't work well, use individual queries
    info = {}
    for key, jq in [
        ("stars", ".stargazers_count"),
        ("license", '.license.spdx_id // "unknown"'),
        ("description", '.description // ""'),
        ("default_branch", ".default_branch"),
        ("language", '.language // "unknown"'),
        ("size", ".size"),
        ("archived", ".archived"),
        ("fork", ".fork"),
    ]:
        val = run_gh(["api", f"repos/{repo}", "--jq", jq], "")
        info[key] = val
    return info


def fetch_recent_commits(repo: str, branch: str = "main") -> int:
    """Count commits in the last 90 days."""
    from datetime import datetime, timedelta
    since = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%dT00:00:00Z")
    raw = run_gh([
        "api", f"repos/{repo}/commits",
        "-X", "GET",
        "--jq", "length",
        "-f", f"since={since}",
        "-f", f"sha={branch}",
        "-f", "per_page=100",
    ], "0")
    try:
        return int(raw)
    except ValueError:
        return 0


def check_test_infrastructure(repo: str) -> tuple[bool, bool]:
    """Check if repo has test directory and CI config."""
    # Check for common test directories
    tree_raw = run_gh([
        "api", f"repos/{repo}/git/trees/HEAD",
        "--jq", '[.tree[].path] | join(",")',
    ], "")

    paths = tree_raw.split(",") if tree_raw else []
    path_lower = [p.lower() for p in paths]

    has_tests = any(
        t in path_lower
        for t in ["tests", "test", "spec", "__tests__", "testing"]
    )
    has_ci = any(
        c in path_lower
        for c in [".github", ".circleci", ".travis.yml", "jenkinsfile", ".gitlab-ci.yml"]
    )

    return has_tests, has_ci


def score_repo(repo: RepoScore) -> RepoScore:
    """Apply the scoring rubric to a repository."""
    # LOC score (estimated from repo size in KB; rough: 1KB ≈ 25 LOC)
    estimated_loc = repo.loc * 25
    if estimated_loc >= 500_000:
        repo.loc_score = 5
    elif estimated_loc >= 200_000:
        repo.loc_score = 4
    elif estimated_loc >= 100_000:
        repo.loc_score = 3
    elif estimated_loc >= 50_000:
        repo.loc_score = 2
    else:
        repo.loc_score = 1
        repo.rejected = True
        repo.rejection_reason = f"Too small: ~{estimated_loc} estimated LOC"

    # Maintenance score
    if repo.recent_commits >= 100:
        repo.maintenance_score = 5
    elif repo.recent_commits >= 50:
        repo.maintenance_score = 4
    elif repo.recent_commits >= 20:
        repo.maintenance_score = 3
    elif repo.recent_commits >= 5:
        repo.maintenance_score = 2
    else:
        repo.maintenance_score = 1

    # Test infrastructure score
    if repo.has_tests and repo.has_ci:
        repo.test_score = 5
    elif repo.has_tests:
        repo.test_score = 3
    elif repo.has_ci:
        repo.test_score = 2
    else:
        repo.test_score = 1

    # Complexity score (heuristic: larger + more stars + tests = more complex)
    complexity = 0
    if repo.loc_score >= 4:
        complexity += 2
    if repo.stars > 10000:
        complexity += 1
    if repo.has_tests:
        complexity += 1
    if repo.has_ci:
        complexity += 1
    repo.complexity_score = min(5, complexity)

    repo.total_score = (
        repo.loc_score +
        repo.maintenance_score +
        repo.test_score +
        repo.complexity_score
    )

    return repo


def generate_manifest(repo: RepoScore) -> dict:
    """Generate a repository manifest JSON."""
    return {
        "repository": repo.name,
        "description": repo.description,
        "languages": [repo.language],
        "estimated_loc": repo.loc * 25,
        "architecture": {
            "type": "monolith",
            "key_modules": [],
            "test_directory": "tests/",
            "dependency_graph_notes": "TODO: fill during community bonding"
        },
        "setup": {
            "commands": [],
            "test_command": "",
            "estimated_setup_time_seconds": 60
        },
        "selection_scores": {
            "loc_score": repo.loc_score,
            "maintenance_activity": repo.maintenance_score,
            "architectural_complexity": repo.complexity_score,
            "test_infrastructure": repo.test_score,
            "total": repo.total_score,
        }
    }


def main():
    parser = argparse.ArgumentParser(description="Curate repositories for long-context eval")
    parser.add_argument("--min-repos", type=int, default=30, help="Minimum repos to select")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory for manifests")
    parser.add_argument("--fast", action="store_true", help="Skip API calls, use seed list only with minimal checks")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = args.output_dir or os.path.join(script_dir, "..", "manifests")
    os.makedirs(output_dir, exist_ok=True)

    all_repos: list[RepoScore] = []
    total_candidates = sum(len(v) for v in SEED_REPOS.values())

    print(f"=== Long-Context Eval: Repository Curation Pipeline ===")
    print(f"Scanning {total_candidates} candidate repositories across {len(SEED_REPOS)} languages\n")

    for language, repos in SEED_REPOS.items():
        print(f"--- {language.upper()} ({len(repos)} candidates) ---")
        for repo_name in repos:
            sys.stdout.write(f"  {repo_name}... ")
            sys.stdout.flush()

            entry = RepoScore(name=repo_name, language=language)

            if args.fast:
                # Fast mode: minimal API calls
                info = fetch_repo_info(repo_name)
                entry.stars = int(info.get("stars", "0") or "0")
                entry.loc = int(info.get("size", "0") or "0")
                entry.description = info.get("description", "")[:100]
                entry.default_branch = info.get("default_branch", "main")
                entry.has_tests = True  # Assume true for well-known repos
                entry.has_ci = True
                archived = info.get("archived", "false")
                if archived == "true":
                    entry.rejected = True
                    entry.rejection_reason = "Archived"
            else:
                # Full mode: comprehensive checks
                info = fetch_repo_info(repo_name)
                entry.stars = int(info.get("stars", "0") or "0")
                entry.loc = int(info.get("size", "0") or "0")
                entry.description = info.get("description", "")[:100]
                entry.default_branch = info.get("default_branch", "main")

                archived = info.get("archived", "false")
                if archived == "true":
                    entry.rejected = True
                    entry.rejection_reason = "Archived"
                    print(f"SKIP (archived)")
                    all_repos.append(entry)
                    continue

                entry.recent_commits = fetch_recent_commits(
                    repo_name, entry.default_branch
                )
                entry.has_tests, entry.has_ci = check_test_infrastructure(repo_name)

            entry = score_repo(entry)

            status = "SKIP" if entry.rejected else f"score={entry.total_score}"
            print(f"{status} (LOC~{entry.loc*25:,}, stars={entry.stars:,})")

            all_repos.append(entry)

    # Filter and rank
    accepted = [r for r in all_repos if not r.rejected]
    accepted.sort(key=lambda r: r.total_score, reverse=True)

    # Language distribution
    lang_counts: dict[str, int] = {}
    for r in accepted:
        lang_counts[r.language] = lang_counts.get(r.language, 0) + 1

    print(f"\n=== Results ===")
    print(f"Total candidates scanned: {len(all_repos)}")
    print(f"Accepted: {len(accepted)}")
    print(f"Rejected: {len(all_repos) - len(accepted)}")
    print(f"Languages: {len(lang_counts)} ({', '.join(f'{k}:{v}' for k, v in sorted(lang_counts.items()))})")

    # Write manifests for top repos
    selected = accepted[:max(args.min_repos, len(accepted))]

    print(f"\n=== Top {len(selected)} Selected Repositories ===")
    print(f"{'#':<4} {'Repository':<40} {'Language':<12} {'Score':<6} {'LOC (est)':<12} {'Stars':<10}")
    print("-" * 84)

    for i, repo in enumerate(selected, 1):
        print(f"{i:<4} {repo.name:<40} {repo.language:<12} {repo.total_score:<6} {repo.loc*25:>10,} {repo.stars:>9,}")

        # Write manifest
        safe_name = repo.name.replace("/", "_")
        manifest = generate_manifest(repo)
        manifest_path = os.path.join(output_dir, f"{safe_name}.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

    # Update registry
    registry_path = os.path.join(script_dir, "..", "registry.json")
    registry = {
        "dataset_version": "0.2.0-poc",
        "description": "Long-Context & Complex Reasoning Coding Evaluation Dataset (PoC)",
        "author": "Ryan (Yunxiang) Yan <ryan.yunxiang.yan@gmail.com>",
        "gsoc_issue": "https://github.com/google-gemini/gemini-cli/issues/23316",
        "repositories": [
            {
                "name": r.name,
                "manifest": f"manifests/{r.name.replace('/', '_')}.json",
                "languages": [r.language],
                "score": r.total_score,
            }
            for r in selected
        ],
        "tasks": [],  # To be populated by task extraction
        "statistics": {
            "total_repositories": len(selected),
            "languages": list(lang_counts.keys()),
            "language_distribution": lang_counts,
            "score_distribution": {
                ">=18": len([r for r in selected if r.total_score >= 18]),
                "15-17": len([r for r in selected if 15 <= r.total_score < 18]),
                "12-14": len([r for r in selected if 12 <= r.total_score < 18]),
                "<12": len([r for r in selected if r.total_score < 12]),
            }
        }
    }

    with open(registry_path, "w") as f:
        json.dump(registry, f, indent=2)

    print(f"\nManifests written to: {output_dir}/")
    print(f"Registry updated: {registry_path}")
    print(f"\nNext step: run extract_tasks.py to mine PRs from selected repositories")


if __name__ == "__main__":
    main()
