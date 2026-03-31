# Long-Context & Complex Reasoning Coding Evaluation

**GSoC 2026 Proof of Concept** |
[Proposal (PDF)](https://drive.google.com/file/d/1kJTKaUHn05as4saNb-v33WKGFK1uhn8T/view?usp=sharing)
| [Issue #23316](https://github.com/google-gemini/gemini-cli/issues/23316) |
Ryan (Yunxiang) Yan

## What Is This?

A proof-of-concept evaluation framework for testing whether Gemini CLI can solve
real-world, multi-file engineering problems that require reasoning across large
codebases (100K+ LOC). Unlike existing behavioral evals that test granular agent
behaviors on small synthetic codebases, this framework tests:

1. **Long-context reasoning** across multiple files and modules
2. **Code quality** — not just "does it pass tests?" but "is the fix
   maintainable?"
3. **Genuine reasoning** vs. memorization, via contamination-robust mutations

## What's Included

```
long-context/
├── README.md                        # You are here
├── schema.json                      # JSON Schema for task definitions
├── registry.json                    # Index of 45 curated repos + 11 tasks
│
├── manifests/                       # Repository setup configs (45 repos)
│   ├── django_django.json           #   Python: Django, FastAPI, PyTorch, ...
│   ├── microsoft_TypeScript.json    #   TypeScript: TS, VSCode, Next.js, ...
│   ├── kubernetes_kubernetes.json   #   Go: K8s, Terraform, Prometheus, ...
│   ├── redis_redis.json             #   C/C++: Redis, curl, Postgres, ...
│   ├── rust-lang_rust.json          #   Rust: rustc, Deno, Tauri, Ruff
│   ├── spring-projects_spring-boot.json  # Java: Spring Boot, Elasticsearch, ...
│   └── ... (45 total across 7 languages)
│
├── tasks/                           # Extracted evaluation tasks (11 tasks)
│   ├── django-001.json              #   L2: Cache middleware race condition
│   ├── express-001.json             #   L2: Async error handling in sub-routers
│   ├── kubernetes-001.json          #   L2: Component metrics promotion
│   ├── kubernetes-002.json          #   L2: Pod-level resource managers
│   ├── redis-007.json               #   L2: Stream ID missing from lifecycle ops
│   ├── rust-003.json                #   L3: Rollup of 9 pull requests
│   └── ... (9 auto-extracted + 2 hand-crafted)
│
├── runners/
│   └── long_context_runner.ts       # Eval runner with code quality metrics
│
├── mutations/
│   └── mutator.ts                   # Contamination-robust mutation engine
│
└── scripts/
    ├── curate_repos.py              # Repository curation pipeline
    └── extract_tasks.py             # PR mining + task extraction pipeline
```

## Quick Start

### Run the mutation engine demo

Shows how controlled code mutation creates contamination-resistant task variants
(adapted from
[MathRizz](https://drive.google.com/file/d/1PeXmGG-OduCPuFVvPIMNBkcnyFqZXk_i/view?usp=sharing),
unpublished manuscript):

```bash
npx tsx evals/long-context/mutations/mutator.ts
```

This takes a sample cache middleware, applies variable renaming (`cache` ->
`store`), numerical perturbation (`200` -> `183`), and logic inversion (`!==` ->
`===`), and outputs the mutated code alongside a changelog.

### Run the repository curation pipeline

Scans 45 candidate repos across 7 languages via GitHub API and scores them:

```bash
python3 evals/long-context/scripts/curate_repos.py --fast
```

Outputs scored manifests to `manifests/` and updates `registry.json`.

### Run the task extraction pipeline

Mines merged PRs from curated repos and extracts multi-file tasks:

```bash
# Extract from default repos (Django, Express, K8s, Rust, TypeScript, Redis)
python3 evals/long-context/scripts/extract_tasks.py --limit 15

# Extract from specific repos
python3 evals/long-context/scripts/extract_tasks.py --repos django/django redis/redis --limit 20
```

Tasks pass through:

- **Pre-filter**: >= 3 files changed, not mechanical, has test changes
- **Tier 1 validation**: cross-module dependency, source + test files changed
- **Difficulty categorization**: L1 (cross-file), L2 (multi-module), L3
  (architectural)

### Inspect the dataset

```bash
# View the registry
cat evals/long-context/registry.json | python3 -m json.tool | head -30

# View a sample task
cat evals/long-context/tasks/redis-007.json | python3 -m json.tool

# Count tasks by difficulty
grep -r '"difficulty"' evals/long-context/tasks/ | sort | uniq -c
```

## Three Novel Dimensions

### A. Anti-Shortcut Task Design

Tasks are curated to defeat naive retrieval-based agents. Each task includes
`anti_shortcut_tags` indicating specific traps (legacy code paths, overloaded
methods, cross-language boundaries).

### B. Code Quality Metrics ("Entropy Explosion" Detection)

Beyond pass/fail, we measure code quality: patch locality, duplication,
cyclomatic complexity delta, and architectural alignment. This detects agents
that pass tests but degrade codebase maintainability. Initially scoped to
**Python and TypeScript** with heuristic fallback for other languages.

### C. Contamination-Robust Mutation

Adapted from
[MathRizz](https://drive.google.com/file/d/1PeXmGG-OduCPuFVvPIMNBkcnyFqZXk_i/view?usp=sharing)
(Yan et al., 2025, unpublished manuscript), controlled code mutations (variable
renaming, logic inversion, numerical perturbation) create surface-novel task
variants that preserve structural complexity. Performance delta between original
and mutated variants directly quantifies memorization vs. reasoning.

## Dataset Statistics (PoC)

| Metric                  | Value                                                     |
| ----------------------- | --------------------------------------------------------- |
| Curated repositories    | 45                                                        |
| Languages covered       | 7 (Python, TypeScript, JavaScript, Go, Rust, C/C++, Java) |
| Extracted tasks         | 11 (2 hand-crafted + 9 auto-extracted)                    |
| Difficulty distribution | L1: 1, L2: 8, L3: 2                                       |
| Source repos for tasks  | Kubernetes, Rust compiler, Redis, Django, Express         |

## References

- Yan, Y., Sawada, T., & Goyal, K. (2025). Cascaded Information Disclosure for
  Generalized Evaluation of Problem Solving Capabilities. IJCNLP-AACL 2025.
  [ACL Anthology](https://aclanthology.org/2025.ijcnlp-long.171/)
- Yan, Y., Zhai, Z., Deng, B., & Yang, Q. (2025). MathRizz: Contamination-Robust
  Interactive Math Word Problem Sampling with RAG and Problem Rewriting. Georgia
  Institute of Technology. Unpublished manuscript.
  [Manuscript](https://drive.google.com/file/d/1PeXmGG-OduCPuFVvPIMNBkcnyFqZXk_i/view?usp=sharing)
