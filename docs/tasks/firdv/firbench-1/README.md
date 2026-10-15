# FIRBENCH-1 Lane Briefs

Self-contained briefs for remote implementation lanes. Read in this order: this README, your brief, then the sections of the [task plan](../FIRBENCH-1-fir-benchmark-tool-task-plan.md) and [scope](../FIRBENCH-1-scope.md) that your brief names. Canon citations are Canon v0.26.2 row IDs.

## Dispatch order

| Wave | Brief | Model / tier | Depends on |
| --- | --- | --- | --- |
| W2 | [W2-inventory.md](W2-inventory.md) | gpt-6-luna max, fast | plan v3 |
| W2 | [W2-uxmap.md](W2-uxmap.md) | gpt-6.1-sol xhigh, standard | plan v3 |
| W3 A | [S0-contract.md](S0-contract.md) | gpt-6.1-sol xhigh, standard | W2 inventory |
| W3 B | [S1-frames.md](S1-frames.md) | gpt-6.1-sol xhigh, standard | S0 |
| W3 B | [S2-legs.md](S2-legs.md) | gpt-6.1-sol xhigh, standard | S0 |
| W3 B | [S3-score.md](S3-score.md) | gpt-6.1-sol xhigh, standard | S0 |
| W3 B | [S6a-cli-run-score.md](S6a-cli-run-score.md) | gpt-6.1-sol xhigh, standard | S0 (imports S1–S3 by contract name) |
| W3 B | [S7-label-queue.md](S7-label-queue.md) | gpt-6.1-sol xhigh, standard | S0 |
| Gate | AE-12 tracer run (coordinator, VM) | — | batch B merged |
| W3 C | [S4-clusters.md](S4-clusters.md) | gpt-6.1-sol xhigh, standard | S0, S1 |
| W3 C | [S5-report.md](S5-report.md) | gpt-6.1-sol xhigh, standard | S0–S3, W2 ux-map |
| W3 C | [S6b-cli-report-compare-unseal.md](S6b-cli-report-compare-unseal.md) | gpt-6.1-sol xhigh, standard | S6a, S5 contract |
| W3 C | [S9-acceptance.md](S9-acceptance.md) | gpt-6.1-sol xhigh, standard | S0–S3 |

Batch B lanes run in parallel and must not edit each other's files. When a lane needs a symbol another batch-B lane owns, it codes against the names fixed in S0 and in this README, and its tests use fakes.

## Rules for every lane

1. **Owned paths only.** Edit only the files your brief lists. Anything else is a blocker: stop and report it.
2. **Commit on your lane branch.** A RED commit (tests only, failing for the stated reason), then a GREEN commit. Do not push, merge or rebase.
3. **Test command** (on the VM): `uv run --directory apps/prototype-description-service --locked --extra dev pytest scene/tests/<your test file> -q`. Tests import as `from scripts.eval_harness import <module>`.
4. **Bounded reads.** Never `cat` a large file. `report.py` is 5,982 lines and `face_metrics.py` 1,747: use `grep -n` and `sed -n 'a,bp'` ranges.
5. **Python rules.**
   - `from __future__ import annotations`; frozen dataclasses for records.
   - States are `StrEnum` members imported from `firbench_contract` [sr-007]. No magic status strings.
   - Validation raises the named `FirBenchError` subclasses from `firbench_contract`. Never use `assert` for validation [sr-006].
   - No module-level τ, FPIR, δ, α, floor or seed constants. Every binding value comes from the decision manifest [rg-009].
   - Determinism (FLOW-18): RNG seeded from the manifest, sorted iteration, no wall-clock reads in outputs.
   - numpy and scipy are available. Any other dependency is a blocker unless W2 inventory confirms it.
6. **One space per comparison.** Never compare vectors from different legs (EMB-01). A leg's identity includes its model-manifest fingerprint and OpenCV/ORT versions.
7. **Privacy.**
   - Tests use synthetic vectors, synthetic identities (`id-0001`) and numpy-generated images only.
   - No real names, no real images, no file from `benchmarks/private/` in a test, fixture or commit.
   - Any output that can hold pixels goes through `firbench_contract.require_private_output_path`.
   - InsightFace is a judge-side reference leg only.
8. **Final report.** List the files changed, the RED evidence (failing test names and reason), the GREEN evidence (pass counts), ruff and mypy status (lint findings never block), and open questions.

## Shared names (fixed by S0; other lanes import, never redefine)

Module `scripts.eval_harness.firbench_contract`:

| Name | Kind | Members / fields |
| --- | --- | --- |
| `Admissibility` | StrEnum | `diagnostic`, `development`, `confirmatory` |
| `VerdictState` | StrEnum | `superior`, `non_inferior`, `inconclusive`, `guardrail_vetoed`, `unratified` |
| `FaceOutcome` | StrEnum | mated faces: `missed`, `unaligned`, `wrong_identity`, `rejected`, `correct`. Non-mated faces: `false_accept`, `correct_reject`. |
| `BoundarySemantics` | StrEnum | `legacy_v1` (non-mated accept iff score > τ, mated iff score ≥ τ), `v2` (accept iff score ≥ τ for both) |
| `Arm` | StrEnum | `native`, `oracle_box`, `ref_landmarks` |
| `LegKind` | StrEnum | `sface`, `auraface`, `insightface`, `canary` |
| `LegId` | frozen dataclass | `kind`, `arm`, `space_fingerprint`, `opencv_version`, `ort_version`; `.key()` gives a stable string |
| `FrameSpec` | frozen dataclass | `frame_id`, `admissibility`, `sealed`, `source_sha256`, `exhaustive` |
| `DecisionManifest` | frozen dataclass | see S0 |
| Errors | `FirBenchError` subclasses | `UnratifiedDecisionError`, `SealedFrameReadError`, `CrossSpaceComparisonError`, `RuntimeMismatchError`, `CalibrationLeakError`, `NonPrivateOutputError`, `ProjectionLeakError`, `LinkageMetricError`, `CanaryInSealedRunError`, `FrameContractError` |
| `require_private_output_path(path, *, repo_root)` | function | raises `NonPrivateOutputError` unless the path resolves under `benchmarks/private/` |

Per-face record passed from S2 to S3 (`firbench_legs.FaceSearchRecord`): `face_id`, `image_id`, `psu_id`, `identity_id` (None for non-mated), `fold`, `cell` (query occluder, enrolled occluder), `stage_reached` (`FaceOutcome` up to embedding), `top_k` (tuple of `(identity_id, score)` in the leg's own space), `leg_key`.

## Run artifacts layout (the CLI writes; everything immutable once written)

```
<run_dir>/                       private by default: benchmarks/private/firbench/runs/<run_id>/
  manifest.json                  experiment_manifest.build_experiment_manifest output + firbench block
  ledger/                        outcome_ledger rows, one per expected GT face per leg
  legs/<leg_key>/cache.npz       embeddings + detections, keyed by LegId.key() and image sha
  legs/<leg_key>/searches.jsonl  FaceSearchRecord rows
  scores.json                    S3 output (curves, τ, intervals, verdict, guardrails, cells, waterfall)
  clusters.json                  S4 output
  report/index.html              S5 output (+ .json, .csv)
```

## Reaper rule

The coordinator prints a reaper command only for lanes whose `result.json` is terminal and whose work has landed. Never print a loop over in-flight lanes.
