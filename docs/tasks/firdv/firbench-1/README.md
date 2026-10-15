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
   - States are `StrEnum` members imported from `firbench_contract` [sr-007, repo rule]. No magic status strings.
   - Validation raises the named `FirBenchError` subclasses from `firbench_contract`. Never use `assert` for validation [sr-006, repo rule].
   - No module-level τ, FPIR, δ, α, floor or seed constants. Every binding value comes from the decision manifest [rg-009, repo rule].
   - Determinism (FLOW-18): RNG seeded from the manifest, sorted iteration, no wall-clock reads in semantic outputs.
   - numpy and scipy are available. Any other dependency is a blocker unless W2 inventory confirms it.
6. **One space per comparison.** Never compare vectors from different legs (EMB-01). A leg's identity includes its model-manifest fingerprint and OpenCV/ORT versions.
7. **Privacy.**
   - Tests use synthetic vectors, synthetic identities (`id-0001`) and numpy-generated images only.
   - No real names, no real images, no file from `benchmarks/private/` in a test, fixture or commit.
   - The unseal ledger (`benchmarks/private/firbench/unseal-ledger.jsonl`) is local-only: never committed, never copied into a brief or report.
   - Any output that can hold pixels goes through `firbench_contract.require_private_output_path`.
   - InsightFace is a judge-side reference leg only.
8. **Final report.** List the files changed, the RED evidence (failing test names and reason), the GREEN evidence (pass counts), ruff and mypy status (lint findings never block), and open questions.

## Shared names (fixed by S0; other lanes import, never redefine)

Module `scripts.eval_harness.firbench_contract`:

| Name | Kind | Members / fields |
| --- | --- | --- |
| `Admissibility` | StrEnum | `diagnostic`, `development`, `confirmatory` |
| `VerdictState` | StrEnum | `superior`, `non_inferior`, `inconclusive`, `guardrail_vetoed`, `unratified` |
| `InconclusiveReason` | StrEnum | `primary_fpir_unresolvable`, `required_guardrail_unscored`, `margin_unreachable_mde_gt_delta`, `non_confirmatory_frame`. Set only with `inconclusive`. |
| `FaceOutcome` | StrEnum | mated faces: `missed`, `unaligned`, `wrong_identity`, `rejected`, `correct`. Non-mated source units: `false_accept`, `correct_reject`. |
| `BoundarySemantics` | StrEnum | `legacy_v1` (non-mated accept iff score > τ, mated iff score ≥ τ), `v2` (accept iff score ≥ τ for both) |
| `Arm` | StrEnum | `native`, `gt_crop_redetect` (renamed from `oracle_box`), `cached_yunet_landmark_replay` (renamed from `ref_landmarks`) |
| `ArmStatus` | StrEnum | `available`; `unavailable` (no cached landmark for the face; never a fallback); `unavailable_fused` (insightface, both arms) |
| `LedgerStage` | StrEnum | `missed`, `detected`, `unaligned`, `embedded`. Separable legs write `missed`, `unaligned` or `embedded`. The fused leg writes `missed`, `detected` or `embedded`, never `unaligned`. |
| `LegKind` | StrEnum | `sface`, `auraface`, `insightface`, `canary` |
| `LegId` | frozen dataclass | `kind`, `arm`, `space_fingerprint`, `opencv_version`, `ort_version`; `.key()` gives a stable string |
| `FrameSpec` | frozen dataclass | `frame_id`, `admissibility`, `sealed`, `source_sha256`, `exhaustive` |
| `DecisionManifest` | frozen dataclass | see S0 |
| `UnsealToken` | frozen dataclass | `frame_id`, `frame_sha256`, `decision_sha256`, `run_id`, `code_sha`, `scorer_sha`, `consumed_at` (null until the first sealed read); see S0 Build 7 |
| `require_private_output_path(path, *, repo_root)` | function | raises `NonPrivateOutputError` unless the path resolves under `benchmarks/private/` |

**Non-mated source unit.** The only unit of the FPIR denominator, of FPI, and of the calibration pool. A unit is either (a) a non-mated GT face, or (b) one background unit per frame image, which holds the native-arm detections of that image that overlap no GT face. A no-face image has only its background unit. Units come from the exhaustive frame and are fixed before any run, so detector output never adds or removes one. A unit counts once in FPI when it emits any false accept. Non-mated source units are the only denominator in every fraction, interval and resolvability rule. `N_units` is the count of units in a pool.

**Error raise conditions.** Every error is a `FirBenchError` subclass in `firbench_contract`.

| Error | Raised when |
| --- | --- |
| `UnratifiedDecisionError` | a verdict is requested on a decision that is unratified or unsealed, or whose seal hash does not match |
| `SealedFrameReadError` | a sealed input is read without an unspent `UnsealToken` for that frame, decision and run (`require_frame_read_allowed`), or a verdict is requested on a sealed frame with an unsealed manifest |
| `CrossSpaceComparisonError` | a vector operation spans two `space_fingerprint` values |
| `RuntimeMismatchError` | the OpenCV or ORT version differs within one leg kind, or a cache key does not match its file |
| `CalibrationLeakError` | a calibration fit uses a probe, or any top-k gallery identity, from a test fold |
| `NonPrivateOutputError` | an image-bearing or run output path resolves outside `benchmarks/private/` |
| `ProjectionLeakError` | projection coordinates are passed to a metric |
| `LinkageMetricError` | Ward, median or centroid linkage is requested on cosine distance |
| `CanaryInSealedRunError` | a canary leg is requested on a sealed frame |
| `CanaryConfigError` | a canary declares fewer than two identities, or the permutation leaves a selected label fixed |
| `FrameContractError` | a frame loader finds a missing or malformed key, or an `unresolved` face is requested as non-mated |
| `TauInfeasibleError` | the calibration pool is empty |
| `UndeclaredH2LegError` | `results` lack the H2 leg named in the sealed manifest, or carry results for another in-house leg as H2 |

`require_private_output_path` and the error names above are the only shared error surface. Lanes must not define a second error for the same condition.

Per-search record passed from S2 to S3 (`firbench_legs.FaceSearchRecord`): `face_id`, `image_id`, `psu_id`, `identity_id` (None for non-mated), `fold`, `cell` (query occluder, enrolled occluder), `unit_id`, `stage_reached` (`LedgerStage`), `top_k` (tuple of `(identity_id, score)` in the leg's own space), `gallery_sha256` (hash of the gallery searched), `leg_key`. For a non-mated GT face, `unit_id` is its `face_id`. For a native-arm detection that overlaps no GT face, `unit_id` is `background:<image_id>`, `face_id` is `det:<image_id>:<index>` and `identity_id` is None. Mated GT-face records have `unit_id` None.

## Run artifacts layout (the CLI writes; semantic files immutable once written)

```
<run_dir>/                              private by default: benchmarks/private/firbench/runs/<run_id>/
  manifest.json                         experiment_manifest.build_experiment_manifest output + firbench block (decision sha, frame spec, leg keys, seeds, unseal token id when sealed)
  ledger/                               outcome_ledger rows, one per expected GT face per leg and arm; no background rows
  legs/<leg_key>/cache.npz              embeddings + detections, keyed by LegId.key() and image sha
  legs/<leg_key>/searches.jsonl         FaceSearchRecord rows, including background-unit records (native arm)
  scores.json                           S3 semantic output only (curves, τ, intervals, verdict, guardrails, cells, waterfall); byte-identical on rerun
  timings.json                          attempt and timing receipt; non-replayable, written once, excluded from byte identity
  clusters.json                         S4 output
  report/index.html                     S5 output (+ .json, .csv)
benchmarks/private/firbench/unseal-ledger.jsonl       append-only UnsealToken rows; outside every run dir; local-only
benchmarks/private/firbench/spent/<frame_id>.spent    O_EXCL marker; a frame's sealed read happens once
```

## Reaper rule

The coordinator prints a reaper command only for lanes whose `result.json` is terminal and whose work has landed. Never print a loop over in-flight lanes.
