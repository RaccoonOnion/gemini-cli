# Long-Context & Complex Reasoning Coding Evaluation

**GSoC 2026 Proof of Concept** — Ryan (Yunxiang) Yan

This directory contains a proof-of-concept for the Long-Context & Complex Reasoning
Coding Evaluation Dataset proposed for Google Summer of Code 2026.

## Overview

Unlike the existing behavioral evals in `evals/` which test granular agent behaviors
on small, synthetic codebases, long-context evals test the agent's ability to:

1. **Navigate massive real-world repositories** (100K+ LOC)
2. **Reason across multiple files and modules** to resolve complex engineering problems
3. **Produce maintainable code** (not just test-passing patches)
4. **Reason genuinely** rather than relying on memorized training data

## Structure

```
long-context/
├── README.md                 # This file
├── schema.json               # JSON Schema for task definitions
├── registry.json             # Index of all tasks with metadata
├── tasks/                    # Individual task definitions
│   ├── django-001.json       # Cross-module cache race condition fix
│   └── express-001.json      # Multi-file middleware error handling
├── manifests/                # Repository setup configurations
│   ├── django.json
│   └── express.json
├── mutations/                # Controlled mutation for contamination robustness
│   └── mutator.ts            # Code mutation engine (Novel Dimension C)
└── runners/
    └── long_context_runner.ts # Evaluation runner with code quality metrics
```

## Novel Dimensions

This evaluation framework goes beyond standard task extraction with three novel
dimensions informed by published research:

### A. Anti-Shortcut Task Design
Tasks are curated to defeat naive retrieval-based agents. Each task includes
`anti_shortcut_tags` indicating specific traps (legacy code, overloaded methods,
cross-language boundaries).

### B. Code Quality Metrics ("Entropy Explosion" Detection)
Beyond pass/fail, we measure code quality: patch locality, duplication, cyclomatic
complexity delta, and architectural alignment. This detects agents that pass tests
but degrade codebase maintainability.

### C. Contamination-Robust Mutation
Adapted from MathRizz (Yan et al., 2025), controlled code mutations (variable
renaming, logic inversion, file restructuring) create surface-novel task variants
that preserve structural complexity. Performance delta between original and mutated
variants directly quantifies memorization vs. reasoning.

## References

- Yan et al. (2025a). Cascaded Information Disclosure for Generalized Evaluation
  of Problem Solving Capabilities. IJCNLP-AACL 2025.
- Yan et al. (2025b). MathRizz: Contamination-Robust Interactive Math Word Problem
  Sampling with RAG and Problem Rewriting. Georgia Institute of Technology.
