# Epics

Release-scoped planning documents live here.

## How To Use

- Read the newest release folder first for active planning.
- Treat epic files as multi-slice planning documents, not research notes.
- Move evaluations and comparative analyses to `docs/research/` when they stop being active planning inputs.

## Contents

- [E25 Truthful Service State and a Self-Healing Mirror](v0.5.0/demo-operability-and-mirror-self-healing-epic.md): typed unavailable state on every surface, connection check and breaker visibility, bounded GPU warming, watched outbox reclaimer, non-reused dataset incarnation with atomic mirror cutover, API log hygiene; [task/defect DAG](../scopes/demoheal-parallel-delivery.md) and [contract draft](../scopes/demoheal-operability-contract-draft.md).
- [E24 FIR Development Installation and Comparative Measurement](v0.5.0/fir-development-and-measurement-epic.md): LocalWP with isolated remote FIR, corpus/metric repair, cluster comparisons and self-hosted VLM quality/cost bake-off preparation.
- `v0.1.0/` through `v0.3.1/`: release-line epic sets

## Maintenance Notes

- Each release folder should contain only active or historically important epic plans.
- If a file becomes reference material instead of an executable epic, relocate it to `docs/research/` or `docs/archive/`.
