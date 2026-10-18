# FIRDV implementation entry point

Start with the [LocalWP / FIR 512D implementation guide](../../roadmaps/fir-localwp-512d-implementation-roadmap-2026-09-19.md). It consolidates the intended end state, phase dependencies, corpus additions, operator/human responsibilities and exact next-session kickoff.

| Task | Responsibility |
| --- | --- |
| [FIRDV-1](FIRDV-1-isolated-development-install-task-plan.md) | Initial isolated remote 128D baseline, LocalWP integration and reusable readiness/rollback contracts |
| [FIRDV-2](FIRDV-2-comparative-harness-and-bakeoff-task-plan.md) | Corpus and harness contracts, detector-first scoring, clustering visualizations and self-hosted VLM quality/cost comparison |
| [FIRDV-3](FIRDV-3-embedder-capacity-and-training-feasibility-task-plan.md) | Approved 512D artifact/adapter, controlled comparison, actual 512D LocalWP route in S6 and conditional training feasibility |

First bounded implementation: FIRDV-1 S1 tests-only RED, then a separate implementation dispatch after review. Worker: `codex-remote`, `gpt-5.6-luna`, `max`. Read current repository rules and satisfy the slice's planning/branch review requirements. These are planning artifacts; no site, model result or human annotation is claimed complete.
