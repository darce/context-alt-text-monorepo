# FIRBENCH-1 Lane Briefs

Self-contained briefs for remote implementation lanes. Read in this order: this README, your brief, then the sections of the [task plan](../FIRBENCH-1-fir-benchmark-tool-task-plan.md) and [scope](../FIRBENCH-1-scope.md) that your brief names. Canon citations are Canon v0.26.2 row IDs.

## Delegated decisions (MCP 16732–16736, 16756, 16763, 16773, 16777, 16810, 16848, 16855, 16856)

These decisions are the dispatch supplement for the FIRBENCH-1 briefs. Read them with the [v5 delegated choices](../FIRBENCH-1-fir-benchmark-tool-task-plan.md#delegated-choices-and-frozen-seams-revision-v5). Later runtime clarifications below override stale operator-pending, default and signature statements wherever they differ. They are reversible project policy. They are not human observation, real hashes, exhaustive ground truth or ratification. Canon v0.26.2 is the rule authority.

| MCP | Decision | Where it lands |
| --- | --- | --- |
| 16732 | Canon-first delegation for reversible protocol and UI choices. It is not evidence of observation or of real-data properties. | This README; [S5-report.md](S5-report.md); [S7-label-queue.md](S7-label-queue.md); [W2-uxmap.md](W2-uxmap.md) |
| 16733 | Protocol v1 defaults: k=5 identity-disjoint folds, seeds, bootstrap count, planning ICC, eligibility floors | [S0](S0-contract.md) Builds 2 and 8; [S1](S1-frames.md); [S3](S3-score.md) Builds 5, 6 and 10 |
| 16734 | Label QC v1 defaults: gold and repeat shares, agreement floors, support floors | [S0](S0-contract.md) Build 11; [S7](S7-label-queue.md) |
| 16735 | One background unit per frame image; duplicate detections create no unit; UI annotation and state policy (VIZ-41, INT-21, INT-24, INT-25, FORM-11) | Non-mated source unit below; [S3](S3-score.md) Build 2; [S5-report.md](S5-report.md); [W2-uxmap.md](W2-uxmap.md) |
| 16736 | Contract-freeze delta: `min_n_independent` and `insufficient_independent_psus`, QC support floors, the deterministic `created_at` seam, exact-count and Fraction oracles | [S0](S0-contract.md) Builds 1, 2, 8, 10 and the S7-owned Build 11 cross-reference; [S3](S3-score.md) RED tests |
| 16756 | Explicit frozen inputs: required manifest `p_d` (with `power`), `build_nonmated_pool` keywords and explicit frame-read runtime context; the current S0 producer also requires `consumed_at` and returns `UnsealToken` | [S0](S0-contract.md) Builds 2, 7, 8 and 10; [S3](S3-score.md) Build 6 |
| 16773 | Timestamp priority: seal, else ratification, else explicit literal; only the explicit override must match the selected derived instant. Actual `consumed_at` comes from the separate non-replayable attempt receipt. | [S0](S0-contract.md) Builds 7 and 10; run artifacts below |
| 16777 | Full scores/report replay pins one identical timing receipt; fresh physical timings are new assessment inputs that may change the real veto. AE-7 preserves original receipts and uses explicit verification snapshots. | Run artifacts below; [S3](S3-score.md) Build 10 and verification |
| 16810 | Gallery and rotation protocol. Enrolled gallery membership is a separate axis from the query fit and test folds. The primary run has one preregistered test fold, `fold_protocol.seed % fold_protocol.k`, and the other folds pool as fit. Other rotations are unsealed diagnostics only, with no pooled confirmatory CV and no repeated private read. Membership is declared per run before outcomes. `frame-v1` and `FoldProtocol` are unchanged; the expanded `scores-v1` wire still has `schema_version: 1`. | This README (run artifacts, shared names, error conditions); [S0](S0-contract.md) Builds 2, 7 and 10; [S1](S1-frames.md) Builds 1, 6, 7 and 8; [S3](S3-score.md) `calibrate_tau` and Build 10 scores IO (implemented producer interfaces) |
| 16848, 16855 | Bind private query and separate enrollment inputs at runtime, verify hashes and disjoint media, freeze every leg/fold registry before query outcomes, and enforce driver-owned once-only authorization. No new CLI flags or operator choices. | Runtime binding and gallery membership below; [S0](S0-contract.md) Builds 7 and 10; [S1](S1-frames.md) runtime handoff |
| 16856 | Fixed exhaustive-GT p95 exposure conserves all native work, including empty-image work, in the scored primary-test probability scope. | Timing exposure below |

**Protocol values (project policy, not canon):**

| Value | Setting | MCP |
| --- | --- | --- |
| Folds | `k` = 5, identity-disjoint rotating folds over whole PSUs; `fold_protocol.seed` = 2406466110. Primary test fold = `seed % k` = 0, derived by the run driver with no manifest field; the other four folds pool as fit | 16733, 16810 |
| Gallery | `gallery_lineage.split_seed` = 2468935812; `templates_sha256` unresolved | 16733 |
| Gallery membership | Declared per run in `manifest.firbench.gallery_membership` before outcomes. A separate axis from the fold roles: a fold does not imply enrollment, and enrollment does not imply a fold. An explicit `frozenset()` is a declared empty gallery | 16810 |
| Interval | paired cluster percentile bootstrap; `interval.n_boot` = 10000; `interval.seed` = 2429382368 | 16733 |
| Label queue | sampling seed 336880394 (S7) | 16733 |
| Planning ICC | `planning_icc` = 0.10, a declared design assumption and not an observed ICC; S3 reports sensitivity at 0.05, 0.10 and 0.20 | 16733 |
| Power | required manifest `p_d` = 0.15 (design discordance, not observed) and `power` = 0.80 (scope § Power) | 16756 |
| Eligibility | `min_n_independent` = 50 distinct frame PSUs before FPIR or any interval; `cell_floor_n_independent` = 30 PSUs per pair cell, kept separate | 16733, 16736 |

Each seed is the first 32 bits, big-endian, of SHA-256 over `FIRBENCH-1/v1/<purpose>`, with purposes `folds`, `gallery`, `bootstrap` and `label_queue`, declared before outcomes. The four values above were recomputed for this revision and match.

**Project policy.** Every numeric default in these briefs is declared project policy, not a value Canon v0.26.2 prescribes. AE-2 to AE-4 coverage and power validate the defaults before any real gating.

**Implemented software.** The CLI's lazy `_load_collaborators()` calls `firbench_runtime.default_collaborators()`. The adapter prepares the bound frame, complete gallery registry and optional S7 evidence bundle before query outcomes. The driver authorizes sealed reads before preparation and persists declarations/evidence before invoking the prepared runner. Score IO conserves empty-image timing costs; the CLI implements score, materialize-before-render, provenance-checked comparison and once-only unseal. The source locators and exact contracts are below. These are source-inspection findings, not real-run evidence.

**Prior measured software evidence.** Supplied receipts record CLI/comparison 518 checks, report 178 checks with actual Chrome light/dark inspection, and an earlier joined label-evidence suite of 284 checks. These scopes overlap; do not add the counts or present them as checks from this documentation revision. Synthetic/fixture checks and browser rendering do not establish genuine human conduct, independent exhaustive GT or real-data acceptance.

**Verified asset evidence.** The supplied `live-asset-locations.json` audit records all three primary native assets fully rehashed at `/opt/acx-backend/data/dev-models/face_pipeline/{glintr100.onnx,face_recognition_sface_2021dec.onnx,face_detection_yunet_2026may.onnx}`, with sizes and pinned SHA-256s matching provenance. This supersedes only W2's bounded not-found results for those assets. It establishes neither the offline InsightFace bundle nor corpus/GT/observation availability or live-container bindings. AuraFace output still follows the runtime's explicit normalization contract.

**Unresolved real evidence.** Real query/template bindings and hashes, actual per-leg gallery hashes and enrollment inventory, detector-independent exhaustive GT, admissible source-unit counts, genuine MEAS-29 observation/QC, AE-12 tracer evidence, ratification, seal and real budgets remain unestablished. Template-only identity folds use a declared complete map or deterministic pre-outcome seed binding; known identities retain canonical S1 PSU folds. A passed floor proves no adequacy. The S9 pre-outcome contract is project policy; current S9 implementation/acceptance is not accepted evidence. No numerical pass rule changes here.

## Dispatch order

| Wave | Brief | Depends on |
| --- | --- | --- |
| W2 | [W2-inventory.md](W2-inventory.md) | plan v3 |
| W2 | [W2-uxmap.md](W2-uxmap.md) | plan v3 |
| W3 A | [S0-contract.md](S0-contract.md) | W2 inventory |
| W3 B | [S1-frames.md](S1-frames.md) | S0 |
| W3 B | [S2-legs.md](S2-legs.md) | S0 |
| W3 B | [S3-score.md](S3-score.md) | S0 |
| W3 B | [S6a-cli-run-score.md](S6a-cli-run-score.md) | S0 (imports S1–S3 by contract name) |
| W3 B | [S7-label-queue.md](S7-label-queue.md) | S0 |
| Gate | AE-12 tracer run (coordinator, VM) | batch B merged |
| W3 C | [S4-clusters.md](S4-clusters.md) | S0, S1, S2 |
| W3 C | [S5-report.md](S5-report.md) | S0–S4, W2 ux-map (starts after S4 merges) |
| W3 C | [S6b-cli-report-compare-unseal.md](S6b-cli-report-compare-unseal.md) | S6a merged, S5 contract (merges before S9) |
| W3 C | [S9-acceptance.md](S9-acceptance.md) | S0–S3, S6b (starts after S6b merges) |

Batch B lanes run in parallel and must not edit each other's files. When a lane needs a symbol another batch-B lane owns, it codes against the names fixed in S0 and in this README, and its tests use fakes.

**Consumer boundary.** Consumers follow the actual producers and version-1 schemas, including the expanded score fields below. Missing private inputs remain named input-availability refusals; they do not imply a missing runtime adapter.

Two ordering rules sit outside the Depends column. S5 reads the frozen `clusters-v1` and `scores-v1` schemas and must not start before S4 merges. `mk/evals.mk` is edited serially in this order: S6a, then S6b, then S9. No lane runs in parallel with another lane on that file.

## Rules for every lane

1. **Owned paths only.** Edit only the files your brief lists. Anything else is a blocker: stop and report it.
2. **Commit on your lane branch.** For code, a RED commit (tests only, failing for the stated reason), then a GREEN commit. Prose-only changes add no tests; verify references and whitespace. Do not push, merge or rebase.
3. **Test command** (on the VM): `env -u ACX_EVAL_BENCH OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 uv run --exact --directory apps/prototype-description-service --locked --extra dev pytest scene/tests/<your test file> -q --basetemp=/tmp/firbench-1-<lane>-<dispatch>-pytest` (use an isolated basetemp unique to the dispatch so pytest cannot clean another task's directories). Run the package formatter before lint, scoped to owned code paths. Tests import as `from scripts.eval_harness import <module>`.
4. **Bounded reads.** Never `cat` a large file. `report.py` is 5,982 lines and `face_metrics.py` 1,747: use `rg -n` and `sed -n 'a,bp'` ranges.
5. **Python rules.**
   - `from __future__ import annotations`; frozen dataclasses for records.
   - States are `StrEnum` members imported from `firbench_contract` [sr-007, repo rule in CLAUDE.md]. No magic status strings.
   - Validation raises the named `FirBenchError` subclasses from `firbench_contract`. Never use `assert` for validation [sr-006, repo rule in CLAUDE.md].
   - No module-level τ, FPIR, δ, α, floor or seed constants. Every binding value comes from the decision manifest [rg-009, repo rule in CLAUDE.md].
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
9. **Clean-environment test.** Each code lane adds one integration test that runs its module end to end on fakes, under `--extra dev` only: no `bench` extra and no `ACX_EVAL_BENCH`. Only the VM smoke named in a brief uses the bench extra. The final report records the environment, the extra and the flag used.

## Shared names (fixed by S0; other lanes import, never redefine)

Module `scripts.eval_harness.firbench_contract`:

| Name | Kind | Members / fields |
| --- | --- | --- |
| `Admissibility` | StrEnum | `diagnostic`, `development`, `confirmatory` |
| `VerdictState` | StrEnum | `superior`, `non_inferior`, `inconclusive`, `guardrail_vetoed`, `unratified` |
| `InconclusiveReason` | StrEnum | `primary_fpir_unresolvable`, `required_guardrail_unscored`, `margin_unreachable_mde_gt_delta`, `non_confirmatory_frame`, `insufficient_independent_psus` (MCP 16736). Set only with `inconclusive`. |
| `FaceOutcome` | StrEnum | Final outcome, set only by S3 `finish_outcomes`; never a stage. Mated faces: `missed`, `unaligned`, `wrong_identity`, `rejected`, `correct` (a fused-leg `detected` stage finishes as `missed`). Non-mated source units: `false_accept`, `correct_reject`. |
| `BoundarySemantics` | StrEnum | `legacy_v1` (non-mated accept iff score > τ, mated iff score ≥ τ), `v2` (accept iff score ≥ τ for both) |
| `Arm` | StrEnum | `native`, `gt_crop_redetect` (renamed from `oracle_box`), `cached_yunet_landmark_replay` (renamed from `ref_landmarks`) |
| `ArmStatus` | StrEnum | Written to `arm_availability`. `available`; `unavailable` (no cached landmark for the face; never a fallback); `unavailable_fused` (insightface, both attribution arms). `unavailable` also sets `stage_reached = unavailable`; `unavailable_fused` sets `stage_reached = null`. |
| `SearchStage` | StrEnum | `missed`, `detected`, `unaligned`, `embedded`, `unavailable`. Furthest stage a GT face reached in one (leg, arm) row. Separable legs write `missed`, `unaligned` or `embedded`. The fused leg writes `missed`, `detected` or `embedded`, never `unaligned`; `detected` means the detector fired and no embedding was made. `unavailable` is written only on an attribution row whose arm has no cached landmark. Fused attribution rows have stage null. |
| `IdentityStatus` | StrEnum | `named`, `unknown`, `unresolved`. Set on every GT face. A named face is non-mated for a fold's pool only when its identity is in that fold and absent from the declared enrolled gallery (MCP 16810). An `unknown` face is non-mated only on an exhaustive frame. An `unresolved` face is never non-mated (S1 Build 7). |
| `SamplingArm` | StrEnum | `probability` (inverse-probability weighted), `challenge` (enriched). Set on every image unit and search record. The two arms are reported separately and never pooled. Not the pipeline `Arm`. |
| `FoldRole` | StrEnum | `fit` (pooled calibration folds), `test` (the one held-out fold). Set per rotation by S1 Build 8. The primary run's test fold is `fold_protocol.seed % fold_protocol.k`; other rotations are unsealed diagnostics only (MCP 16810). |
| `AlignmentMode` | StrEnum | `separable` (the leg runs its own five-point alignment), `fused_internal` (insightface; alignment happens inside one call). |
| `LegKind` | StrEnum | `sface`, `auraface`, `insightface`, `canary` |
| `LegId` | frozen dataclass | `kind`, `arm`, `space_fingerprint`, `opencv_version`, `ort_version`; `.key()` gives a stable string |
| `FrameSpec` | frozen dataclass | `frame_id`, `admissibility`, `sealed`, `source_sha256`, `exhaustive` |
| `DecisionManifest` | frozen dataclass | see S0 (includes `min_n_independent`, `cell_floor_n_independent`, `p_d`, `power` and the delegated values; MCP 16733, 16736, 16756) |
| `UnsealToken` | frozen dataclass | `frame_id`, `frame_sha256`, `decision_sha256`, `run_id`, `code_sha`, `scorer_sha`, `consumed_at` (null until the first sealed read); see S0 Build 7 |
| `require_frame_read_allowed(frame, token, *, decision_sha256, run_id, code_sha, scorer_sha, repo_root, consumed_at) -> UnsealToken` | function | returns the consumed token with caller-supplied actual-attempt `consumed_at` from the separate non-replayable receipt boundary after atomic spending and ledger append; never substitutes an old seal time; raises `SealedFrameReadError` unless the token is unspent and bound to the frame and the explicit runtime keywords; S0 Build 7 (MCP 16756, 16773; current S0 producer signature) |
| `require_private_output_path(path, *, repo_root)` | function | raises `NonPrivateOutputError` unless the path resolves under `benchmarks/private/` |
| Interchange schemas | JSON Schema documents, draft 2020-12 | `frame-v1`, `face-search-record-v1`, `scores-v1`, `clusters-v1`, `comparison-v1`. Each carries `schema_version: 1`. Frozen by S0 Build 9 and subsequent accepted score-wire corrections. MCP 16810 adds no `frame-v1` or `FoldProtocol` field; `scores-v1` does gain the fields listed above without a version bump. `validate_interchange(name, payload)` checks them with a stdlib checker (no new dependency) and raises `FrameContractError`. |
| Entry-point signatures | functions | Exact signatures in S0 Build 10. Batch-B lanes code against them unchanged. Before batch B, MCP 16736 fixes `run_frame` (`created_at`); MCP 16756 fixes `build_nonmated_pool` and the explicit frame-read runtime context. Preserve S0's required `consumed_at` keyword and `UnsealToken` return. MCP 16810 adds the required `enrolled_identity_ids` keyword to `build_nonmated_pool` and `build_frame`, the optional `identity_folds` to `calibrate_tau`, and the `firbench_score_io.score_run` row. |
| `reference_threshold_cluster(vectors, *, similarity_threshold)` | function | `firbench_clusters`. The one reference clustering function. S4 uses it for every partition metric and the dendrogram; S5 displays its labels and never recomputes them. The production loader `prepare_cluster_caches` is not used. |

**Non-mated source unit.** The only unit of the FPIR denominator, of FPI, and of the calibration pool. A unit is either (a) a non-mated GT face, or (b) one background unit per frame image, which holds the native-arm detections of that image that overlap no GT face. A non-mated GT face is a named face whose identity is in the pool's fold and absent from the declared enrolled gallery, or an `unknown` face on an exhaustive frame in that fold (MCP 16810). A no-face image has only its background unit. Units come from the exhaustive frame, the declared enrollment and the fixed PSU map, and are fixed before any run, so detector output never adds or removes one. Detections only score units; they never build the inventory (MCP 16810). Each frame image has exactly one background unit (MCP 16735). A duplicate detection that overlaps an already represented GT face creates no unit, and its extra above-threshold names count only as spurious names (EVAL-19). `build_nonmated_pool` refuses `exhaustive=false` (MCP 16756), and refuses an omitted, `None` or malformed `enrolled_identity_ids` (MCP 16810). A unit counts once in FPI when it emits any false accept. Non-mated source units are the only denominator in every fraction, interval and resolvability rule. `N_units` is the count of units in a pool.

**Error raise conditions.** Every error is a `FirBenchError` subclass in `firbench_contract`.

| Error | Raised when |
| --- | --- |
| `UnratifiedDecisionError` | a verdict is requested on a decision that is unratified or unsealed, or whose seal hash does not match |
| `SealedFrameReadError` | a sealed input is read without an unspent `UnsealToken` bound to that frame, decision, run, code and scorer through the explicit keywords of `require_frame_read_allowed`, or a verdict is requested on a sealed frame with an unsealed manifest |
| `CrossSpaceComparisonError` | a vector operation spans two `space_fingerprint` values |
| `RuntimeMismatchError` | the OpenCV or ORT version differs within one leg kind, or a cache key does not match its file |
| `CalibrationLeakError` | a calibration fit uses a probe, or any top-k gallery identity, from a test fold; or a top-k identity has no fold in `identity_folds`, or its fold contradicts the frame's identity fold (fails closed; MCP 16810) |
| `NonPrivateOutputError` | an image-bearing or run output path resolves outside `benchmarks/private/` |
| `ProjectionLeakError` | projection coordinates are passed to a metric |
| `LinkageMetricError` | Ward, median or centroid linkage is requested on cosine distance |
| `CanaryInSealedRunError` | a canary leg is requested on a sealed frame |
| `CanaryConfigError` | a canary declares fewer than two identities, or the permutation leaves a selected label fixed |
| `FrameContractError` | a frame loader finds a missing or malformed key, an `unresolved` face is requested as non-mated, an interchange payload fails its schema, `build_nonmated_pool` gets `exhaustive=false` or malformed component or fold coverage (MCP 16756), or a run timestamp is invalid, no `created_at` source exists, or an explicit literal mismatches the selected derived instant; or `enrolled_identity_ids` is `None` or not a `frozenset` of strings (MCP 16736, 16773, 16810; S0 Build 10) |
| `TauInfeasibleError` | the calibration pool is empty |
| `UndeclaredH2LegError` | `results` lack the H2 leg named in the sealed manifest, or carry results for another in-house leg as H2 |

`require_private_output_path` and the error names above are the only shared error surface. Lanes must not define a second error for the same condition.

Per-search record passed from S2 to S3 (`firbench_legs.FaceSearchRecord`, one `searches.jsonl` row, schema `face-search-record-v1`):

| Field | Type | Rule |
| --- | --- | --- |
| `face_id`, `image_id`, `psu_id` | string | `psu_id` from S1 Build 3 |
| `identity_id` | string or null | GT identity only for mated records; null for non-mated records, including named G2/nonenrolled queries. Never inferred from a prediction. |
| `identity_status` | `IdentityStatus` | from the GT face |
| `fold`, `fold_role` | int, `FoldRole` | the face's fold and its role in the rotation |
| `cell` | pair | `(query occluder, enrolled occluder)`. Each occluder is the sorted `+`-joined set (`glasses+mask`); `[]` is `clear` and `null` is `unknown`. The enrolled occluder comes only from `enrolled_occluders` in the membership record, and is `unknown` when that field is absent. It is never taken from a predicted identity (MCP 16810). |
| `unit_id` | string or null | rules below |
| `sampling_arm` | `SamplingArm` | from the image unit |
| `inclusion_probability` | float or null | from the image unit; null on the challenge arm; the IPW weight is its reciprocal |
| `cohort` | object or null | `sex`, `age_band`, `origin`, each a string or null; null for background units |
| `leg_key`, `arm` | string, `Arm` | one row per (face, leg, arm) |
| `arm_availability` | `ArmStatus` | `available` unless the arm could not run |
| `alignment_mode` | `AlignmentMode` | `fused_internal` on the insightface leg |
| `stage_reached` | `SearchStage` or null | null only when `arm_availability = unavailable_fused` |
| `top_k` | tuple of `(identity_id, score)` | in the leg's own space; empty when the arm did not run |
| `gallery_sha256` | string | gallery snapshot id: the sha256 of the enrolled gallery this leg searched. It is per leg, because vector spaces differ, and matches that leg's membership row (MCP 16810) |
| `timing_receipt_ref` | string or null | key of this face's row in `timings.json` |

For a non-mated GT face, `unit_id` is its `face_id`. For a native-arm detection that overlaps no GT face, `unit_id` is `background:<image_id>`, `face_id` is `det:<image_id>:<index>` and `identity_id` is None. Mated GT-face records and duplicate detections over a mated face have `unit_id` None.

<a id="run-artifacts-layout-the-cli-writes-semantic-files-immutable-once-written"></a>

## Run artifacts layout

Declarations, searches, ledgers, evidence and timing receipts are immutable. Scores are validated derived output published atomically; reports and clusters consume pinned run evidence.

```
<run_dir>/                              private by default: benchmarks/private/firbench/runs/<run_id>/
  manifest.json                         CLI-owned schema_version: 1 + firbench block (decision/frame/legs/seeds, gallery registry/basis, created_at, optional label_evidence and consumed-token ref)
  frame.json                            validated frame-v1 payload; exact frame_json(frame) + newline bytes, written before query outcomes
  label-evidence/benchmarks/private/... optional exact S7 proof closure; descriptor in manifest.firbench.label_evidence
  attempt-failure.json                  retained query-outcome failure receipt when the prepared runner raises
  ledger/<leg_key>.jsonl                sorted JSON lines, one per expected GT face per leg and arm; no background rows
  legs/<leg_key>/cache.npz              embeddings + detections, keyed by LegId.key() and image sha
  legs/<leg_key>/searches.jsonl         FaceSearchRecord rows, including background-unit records (native arm)
  scores.json                           validated S3 assessment + face_outcomes for every GT leg/arm row; native summaries, joint gaps and receipt-bound guardrails
  timings.json                          attempt and timing receipt; non-replayable, written once; pin identical receipt for full scores/report replay
  clusters.json                         S4 output
  report/index.html                     S5 output (+ .json, .csv); decisions transitively depend on the timing receipt through scores.json
benchmarks/private/firbench/unseal-ledger.jsonl       append-only UnsealToken rows; outside every run dir; local-only
benchmarks/private/firbench/spent/<frame_id>.spent    O_EXCL marker; a frame's sealed read happens once
```

**Gallery membership (MCP 16810, 16848, 16855).** `manifest.firbench.gallery_membership` has one row for EVERY declared `leg_key` and every query `fold`, including attribution keys. Required fields: `leg_key`, `fold`, `gallery_sha256`, `enrolled_identity_ids` (sorted, possibly empty), and `identity_folds` (the full persisted identity → fold map); optional `enrolled_occluders` maps enrolled identities to occluder sets (`null` unknown, `[]` clear). For each query fold use only that fold's identity-eligible template roster, the actual `gallery_split.build_disjoint_galleries(templates_by_subject=..., seed=...)` with the manifest split seed, and fixed G1 enrollment direction. G2 and other nonenrolled query identities are non-mated. Native legs share membership per fold; attribution rows share that native membership. Every leg retains its own vector space and gallery hash. `frame.gallery_sha256_by_fold` uses a declared primary native leg's hashes; persist which leg supplies that basis. A fold alone never implies enrollment. Persist and validate full `frame.json` and this registry BEFORE query outcomes. Scoring refuses missing or incomplete membership; an explicit empty gallery is valid.

**Runtime input binding (MCP 16848/16855; implemented).** The adapter reads `benchmarks/private/firbench/inputs/<frame_id>.json` with no new CLI flag. The exact `firbench-inputs/v1` fields are `schema`, `query_source`, `gallery_templates`, `query_images`; optional fields are `identity_folds`, `crop_margin` (default 0.0) and `label_evidence`. `query_source` has `kind`, `path`, `sha256`; kind is `population_draft` or `golden_manifest`. `gallery_templates` has `path`, `sha256`. Each `query_images[image_id]` has `path`, `media_ids` and must cover exactly the full source image inventory. Paths are repository-relative under `benchmarks/private/`. Source/template document bytes must match both binding hashes and `FrameSpec.source_sha256` / `GalleryLineage.templates_sha256`. Each image/template asset is hash-checked before decode. Overlapping query/enrollment paths, hashes or media IDs refuse; queries are never dropped to repair overlap.

The separate `firbench-templates/v1` document has exactly `schema`, `templates`. Its nonempty rows have exactly `template_id`, `identity_id`, `media_ids`, `path`, `sha256`, `box` (pixel xywh), `occluders` (`null` unknown, `[]` clear). IDs are pseudonyms; GT/template boxes must fit their bound images. Template embeddings require exactly one spatially matched observation. There is no sample fallback, inferred identity or download. `_Adapter._prepare_run` binds canonical query folds and any template-only folds before splitting each eligible roster into fixed G1 enrollment; it publishes the full map for every leg/fold, including attribution arms.

The DRIVER calls S0 once-only authorization before private binding/source/GT/template/pixel reads. Default settings/model identity preparation uses no query data. Query pixels are decoded once into attempt RAM; scoring never reopens them. Preparation may compute enrollment vectors but no query scores. `_qualified_source` uses actual S7 `load_label_export`, `load_queue`, `to_face_instances`, `require_real_analysis_rows` before S1 conversion, and matches tier-a source geometry, image SHA, identity status and annotation one-to-one. Tier-a golden rows refuse in favor of a qualified population source. When `label_evidence` is supplied, S7 freezes its genuine read closure into exact bytes bound to SHA-256 of UTF-8 `frame_json(prepared_frame) + '\n'`. The driver validates the bundle, writes each support file exclusively, then frame/manifest declarations, all before calling `prepared.run_legs`. `PreparedRun.label_evidence` is optional and last (default `None`); older injected seams still work.

Static refusals known before protected reads spend/write no new run artifacts. Evidence checks requiring protected source/GT happen after S0 consumption; refusal is a failed attempt and never refunds a token. A prepared query failure retains declaration/evidence bytes plus `attempt-failure.json`; it publishes no successful search/ledger/timing output. Core and IO scorer sources share one ordered `scorer_sha256()` digest. Cache publication follows complete computation/validation as described below.

**Timing exposure (MCP 16856; implemented).** `firbench_score_io.timing_exposure(receipt, records, inventory, key)` uses native primary-test probability scope. `N_GT` is the independently fixed exhaustive GT-face count. For each image i with `m_i > 0`, each GT face receives `image_total_i / m_i + sum(empty_GT_image_totals) / N_GT`. Exactly `N_GT` samples conserve all native image/record work in that scope, including empty-image work; extra detections create no bins. If `N_GT = 0`, timing is unscored. The function computes the linear 95th percentile in `ms/GT_face` from `timing_receipt_ms`; incomplete, duplicate or unattributed receipt costs fail closed. Numeric milliseconds remain in RAM/the receipt; semantic p95 output carries metric/state, receipt digest and support metadata, with numeric timing value/limit null. This establishes the producer algorithm, not measured real p95 or a budget pass.

## Runtime and consumer contracts

Source locators below refer to the implemented producers under `apps/prototype-description-service/scripts/eval_harness/`.

| Producer | Contract |
| --- | --- |
| [firbench_cli.py](../../../../apps/prototype-description-service/scripts/eval_harness/firbench_cli.py) | `_load_collaborators`, `run_frame(*, frame_id, decision_path, legs, arms, subset, subset_seed, out_dir, repo_root, created_at=None) -> Path`; `score_run(run_dir, *, repo_root) -> Path`; `report_run(run_dir, *, include_crops, repo_root) -> Path`; `compare_runs(run_a, run_b, *, out_dir, treatment, repo_root) -> Path`; `unseal_frame(*, decision_path, frame_id, run_id, repo_root) -> str` |
| [firbench_runtime.py](../../../../apps/prototype-description-service/scripts/eval_harness/firbench_runtime.py) | `InputBinding`, `TemplateRow`, `_qualified_source`, `_Adapter._prepare_run`, `PreparedRun`, `default_collaborators`, `scorer_sha256` own runtime binding and declaration preparation |
| [firbench_score_io.py](../../../../apps/prototype-description-service/scripts/eval_harness/firbench_score_io.py) | `score_run(run_dir, *, decision, pair_scores=None) -> dict`; `_registry`, `_records`, `_face_outcomes`, `timing_exposure` own persisted evidence validation/assembly |
| [firbench_cluster_io.py](../../../../apps/prototype-description-service/scripts/eval_harness/firbench_cluster_io.py) | `materialize_clusters(run_dir, *, config=None, prior_run_dir=None) -> Path`, with `DiagnosticConfig` for optional configuration; validates actual inputs before accepting an existing canonical `clusters.json`, refuses conflicting bytes |
| [firbench_report.py](../../../../apps/prototype-description-service/scripts/eval_harness/firbench_report.py) | `render_report(run_dir, *, out_dir, include_crops=False) -> Path`; `_binding_scopes`, `_binding_label_evidence`, `_binding_qualification` consume declared scope and qualified evidence |
| [fir_occ_labels.py](../../../../apps/prototype-description-service/scripts/eval_harness/fir_occ_labels.py) | `freeze_label_evidence(export_path, queue_path, gold_path, *, repo_root, frame_sha256) -> LabelEvidenceBundle`; `requalify_label_evidence(run_dir, descriptor, *, frame_sha256) -> tuple[dict, ...]`; both read-only |

**Calibration and score wire (MCP 16868).** IO binds the supplied decision object to the raw decision file SHA and the actual run's containing repository, with private containment. One native leg/space/probability arm calibrates against fixed source units from pooled fit folds; each fit fold may have its own gallery SHA. The full identity map includes unused held-out names; missing, inconsistent or test-fold probe/hit provenance refuses. `scores-v1` still has `schema_version: 1` but has expanded fields: `joint_gaps`, `decision_path`, cell `data_origin`/`n_identities`/`n_eff`/`interval`, per-leg `pair_fmr`, typed guardrail evidence and `face_outcomes`. Follow the actual [scores-v1 schema](../../../../apps/prototype-description-service/scripts/eval_harness/firbench_schemas/scores-v1.json); a stable version number does not mean unchanged fields.

**Native summaries and all declared arms.** `scores.legs` contains native summaries only. IO validates searches against the full GT inventory for every declared leg/arm; `face_outcomes` exposes these GT rows with fold, sampling arm, stage, availability, mated status and explicit outcome/reason. Attribution outcomes use the matching native space's frozen τ. Fit, unresolved, unavailable or uncalibrated rows keep null outcomes with reasons; detector-only records stay in raw searches/background accounting. `joint_gaps` compares available attribution/native outcomes without replacing native inference. Probability and challenge data remain separate. The report consumes these classifications and every declared search scope; missing required searches refuse. Legacy scores without `face_outcomes` have unavailable classifications, not invented outcomes. One unresolved row does not withhold other eligible scored rows.

**Leg cache (MCP 16869).** S2's `ArmResult.cached_observations` (default empty tuple) records actual executions; the runtime accumulates them across folds. It validates all query results and packs/validates all caches before publishing any cache. `firbench_legs.pack_cache_observations` emits `metadata_json` (scalar Unicode: `format='firbench-cache/v1'`, `leg_key`, sorted `rows`) and finite 2-D `float32` `vectors`; `LegCache` also binds its stored leg key. Rows contain `record_id`, `image_id`, `image_sha256`, `gt_face_id`, `stage`, `arm_availability`, `bbox_px`, `landmarks_px`, `detector_score`, `embedding_index`. Indexes cover actual embeddings uniquely; absent embeddings stay null. Independent readers validate types, shapes, geometry, duplicates, exact leg and image-SHA/GT bindings. They never reconstruct vectors from top-k or rerun models. Missing cache/no embedded GT/missing prior chaining evidence is named unavailable; malformed evidence refuses.

**Frozen S7 proof replay.** `manifest.firbench.label_evidence` has exactly `schema='firbench-label-evidence/v1'`, `frame_sha256`, `export_path`, `queue_path`, `gold_path`, sorted `files=[{path, sha256}]`. Run-relative paths preserve `label-evidence/<original repo-relative private path>` and exact bytes/link topology. Only actual S7 support edges are frozen: queue-relative `observation_ref` and `acceptance_path`, plus acceptance `prior_export`, `validation_queue`, `validation_gold`, `validation_export` and their required supports. No images, models, alias maps or directory copying. Absolute/escaping/symlink/ambiguous/cyclic unsupported links and malformed JSON refuse. Report requalification uses only enumerated run-local bytes with the raw `frame.json` SHA, requires the exact closure, and calls actual S7 readers/qualification; original source files need not remain available. Tier-a display requires one-to-one canonical image ID + frame image SHA + box + identity status + normalized Frame annotation match. Missing/unsupported qualification stays withheld with a reason; no reference string, cached boolean or synthetic helper creates genuine human evidence.

**Score publication.** CLI `score_run` validates before atomically replacing `scores.json`; same-decision re-scoring is implemented. This is a derived assessment publication, while source declarations/searches/ledger/evidence and original timing receipts stay immutable. Full byte replay still requires all assessment inputs pinned, as below.

**Replay boundary (FLOW-18; MCP 16773, 16777).** Semantic `created_at` selects seal time, else ratification time, else an explicit literal; only an explicit override must match the selected derived instant (S0 Build 10). Actual `consumed_at` stays in the non-replayable attempt/private unseal-ledger boundary. `scores.json` includes the timing receipt SHA and p95 veto state, so report decisions transitively depend on that receipt. Whole scores/report bytes replay only with all assessment inputs pinned, including one identical `timings.json`. Fresh physical timings are new assessment inputs and may change the real veto, scores and report. Across cold runs, compare pure searches and recognition ledgers; keep attempt receipts separate. For AE-7 full replay, create explicit verification snapshots with one fixed receipt and otherwise identical semantic inputs, leaving every original receipt intact. Also verify that a changed receipt can change the real veto and dependent report decision in an otherwise eligible fixture. Never mask or normalize actual veto/hash fields, overwrite original receipts, or reread a spent sealed frame for replay. Verification snapshots require no new CLI argument. This applies FLOW-18, **Make report recomputation deterministic or mark it non-replayable** (*Designing Data-Intensive Applications*, ch. 10), to pinned assessment inputs.

## Canon rows and cards cited

Inline IDs in these briefs name the rows below. Rule names and source labels follow the pinned Canon v0.26.2 rows. Canon locators resolve under the read-only mirror `/home/gate/firbench-1-context/canon-0.26.2`; `bootstrap` is an unsourced practice label in `SOURCES.md#src-bootstrap`. `sr-NNN` and `rg-NNN` are not canon IDs. They are repo rules in the repository's `CLAUDE.md` (Short Rules and the `rg` list), and the briefs write them as `repo rule in CLAUDE.md`.

| ID | Rule | Source | Canon locator |
| --- | --- | --- | --- |
| EMB-01 | One embedding space per comparison | Foundations of Vector Retrieval, ch. 1 | `lexicons/ml-systems.md#emb-01` |
| FLOW-18 | Make report recomputation deterministic or mark it non-replayable | Designing Data-Intensive Applications, ch. 10 | `lexicons/engineering.md#flow-18` |
| GRPH-33 | A node without a contract cannot be parallelised | bootstrap (unsourced practice label) | `lexicons/graph-theory.md#grph-33` |
| EXP-12 | Power and practical significance | Trustworthy Online Controlled Experiments, ch. 2 | `lexicons/epistemics.md#exp-12` |
| EXP-22 | No circular analysis (double-dipping) | Statistics Done Wrong, ch. 6 | `lexicons/epistemics.md#exp-22` |
| EXP-23 | Pseudoreplication check | Statistics Done Wrong, ch. 3 | `lexicons/epistemics.md#exp-23` |
| EXP-30 | Disclose specification spread | Seeing with Fresh Eyes: Meaning, Space, Data, Truth, ch. 4 | `lexicons/epistemics.md#exp-30` |
| CAL-04 | Calibrate the threshold on matched non-mates | NIST FRVT Part 3 Demographic Effects | `lexicons/ml-systems.md#cal-04` |
| CAL-07 | Select face thresholds on identity-disjoint folds | Video-to-Video Face Recognition for Low-Quality Surveillance Data, ch. 6 | `lexicons/ml-systems.md#cal-07` |
| AUDIT-11 | Account for cluster design effect | Sampling: Design and Analysis, ch. 5 | `lexicons/ml-systems.md#audit-11` |
| EVAL-07 | Validation-only selection | Designing Machine Learning Systems | `lexicons/ml-systems.md#eval-07` |
| EVAL-16 | Upstream failure counts against the end-to-end metric | IARPA Janus Benchmark-C, § 2.3.4 | `lexicons/ml-systems.md#eval-16` |
| EVAL-18 | Non-mated probes and a score threshold, not rank | IARPA Janus Benchmark-C, § 2.3.4 | `lexicons/ml-systems.md#eval-18` |
| EVAL-19 | Do not let detector alarms dilute FPIR | IARPA Janus Benchmark-C, § 2.3.4 | `lexicons/ml-systems.md#eval-19` |
| WRIT-81 | Keep decision-changing limits in summary prose | tufte-beautiful-evidence § cognitive-style-of-powerpoint | `lexicons/writing.md#writ-81` |
| HITL-03 | Gold-embedded annotator QC | Human-in-the-Loop ML | `lexicons/ml-systems.md#hitl-03` |
| HITL-05 | Agreement is a diagnostic, not the truth | Human-in-the-Loop ML | `lexicons/ml-systems.md#hitl-05` |
| HITL-07 | SME adjudication escalation | Human-in-the-Loop ML | `lexicons/ml-systems.md#hitl-07` |
| MLDATA-03 | Resolve label multiplicity in writing | Designing Machine Learning Systems | `lexicons/ml-systems.md#mldata-03` |
| MEAS-29 | Observe measurement production | Seeing with Fresh Eyes: Meaning, Space, Data, Truth, ch. 4 | `lexicons/epistemics.md#meas-29` |
| VIZ-41 | Reveal the image-selection pool | Visual Explanations, ch. 1 | `lexicons/interaction-ux.md#viz-41` |
| INT-21 | Specify interaction states | Microinteractions, ch. 3 | `lexicons/interaction-ux.md#int-21` |
| INT-24 | Specify loop exits | Microinteractions, ch. 5 | `lexicons/interaction-ux.md#int-24` |
| INT-25 | Map the handoffs | Microinteractions, ch. 6 | `lexicons/interaction-ux.md#int-25` |
| FORM-11 | Constrain before error | Microinteractions, ch. 3 | `lexicons/interaction-ux.md#form-11` |

**Cards and mirror coverage.** `CARD-03`, **Designed unknown** (`reasoning/designed-unknown.md`), requires explicit unknown/insufficient-evidence states rather than forced certainty. `CARD-27`, **Seal the margin and size the floor from design-effect n_eff** (canonical locator `reasoning/margin-and-design-effect-before-the-run.md`), is supplied at `/home/gate/firbench-1-context/canon-supplement/margin-and-design-effect-before-the-run.md`; SHA-256 `186c94c2b0ba88897cebea26c39752d6f0e87bbab8bff3ec1fa9aace79f85aad` matches the v0.26.2 release manifest. It requires pre-run margin, method, harm direction, α allocation and design-effect sizing. Computed detectable MDE remains distinct from the predeclared practical margin/SESOI (S3 Build 6). These requirements establish policy, not real-data adequacy or a synthetic pass of absent evidence. All cited rows are available in the partial mirror (7 of 12 lexicons, 4 of 33 cards); the exact supplement supplies CARD-27. MEAS-29 owns bounded contextual observation of real label production; it does not own number-to-JSON traceability or the pre-sealed margin/design-effect gate.
