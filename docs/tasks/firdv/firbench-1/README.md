# FIRBENCH-1 Lane Briefs

Self-contained briefs for remote implementation lanes. Read in this order: this README, your brief, then the sections of the [task plan](../FIRBENCH-1-fir-benchmark-tool-task-plan.md) and [scope](../FIRBENCH-1-scope.md) that your brief names. Canon citations are Canon v0.26.2 row IDs.

## Delegated decisions (MCP 16732–16736, 16756, 16773, 16777)

These decisions are the dispatch supplement for the FIRBENCH-1 briefs. Until the task plan's next revision, they override the operator-pending, default and signature statements in the briefs and in the plan's open questions wherever the two differ. They are reversible project policy. They are not human observation, real hashes, exhaustive ground truth or ratification. Canon v0.26.2 is the rule authority.

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

**Protocol values (project policy, not canon):**

| Value | Setting | MCP |
| --- | --- | --- |
| Folds | `k` = 5, identity-disjoint rotating folds over whole PSUs; `fold_protocol.seed` = 2406466110 | 16733 |
| Gallery | `gallery_lineage.split_seed` = 2468935812; `templates_sha256` unresolved | 16733 |
| Interval | paired cluster percentile bootstrap; `interval.n_boot` = 10000; `interval.seed` = 2429382368 | 16733 |
| Label queue | sampling seed 336880394 (S7) | 16733 |
| Planning ICC | `planning_icc` = 0.10, a declared design assumption and not an observed ICC; S3 reports sensitivity at 0.05, 0.10 and 0.20 | 16733 |
| Power | required manifest `p_d` = 0.15 (design discordance, not observed) and `power` = 0.80 (scope § Power) | 16756 |
| Eligibility | `min_n_independent` = 50 distinct frame PSUs before FPIR or any interval; `cell_floor_n_independent` = 30 PSUs per pair cell, kept separate | 16733, 16736 |

Each seed is the first 32 bits, big-endian, of SHA-256 over `FIRBENCH-1/v1/<purpose>`, with purposes `folds`, `gallery`, `bootstrap` and `label_queue`, declared before outcomes. The four values above were recomputed for this revision and match.

**Project policy.** Every numeric default in these briefs is declared project policy, not a value Canon v0.26.2 prescribes. AE-2 to AE-4 coverage and power validate the defaults before any real gating.

**Still unresolved.** Real frame and template hashes (`gallery_lineage.templates_sha256`, each frame's `source_sha256`), ratification, seal, human observation (MEAS-29 evidence), exhaustive ground truth and any admissible nonmated count. Seal refuses absent inputs. A passed floor is not proof of adequacy.

## Dispatch order

**Current routing (all implementation waves).** First implementation/grunt work uses Haiku 5.5 xhigh remotely. Corrections after merge-gate defects use Sol 6.1 high, standard tier, remotely (`codex-remote gpt-6.1-sol`). This second documentation dispatch uses the latter route. All edits and checks run on the VM. This routing supersedes older model headers in individual briefs.

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

**Partial freeze (MCP 16777).** S1, S2 and S7 may consume the accepted S0 contract now. S3 and S6a wait for the focused per-leg score schema correction in the independent S0 lane. Use the accepted producer and schema for wire fields; the earlier singleton-score schema is not the corrected consumer contract. This prose lane does not redefine that schema.

Two ordering rules sit outside the Depends column. S5 reads the frozen `clusters-v1` and `scores-v1` schemas and must not start before S4 merges. `mk/evals.mk` is edited serially in this order: S6a, then S6b, then S9. No lane runs in parallel with another lane on that file.

## Rules for every lane

1. **Owned paths only.** Edit only the files your brief lists. Anything else is a blocker: stop and report it.
2. **Commit on your lane branch.** For code, a RED commit (tests only, failing for the stated reason), then a GREEN commit. Prose-only changes add no tests; verify references and whitespace. Do not push, merge or rebase.
3. **Test command** (on the VM): `env -u ACX_EVAL_BENCH OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 uv run --exact --directory apps/prototype-description-service --locked --extra dev pytest scene/tests/<your test file> -q --basetemp=/tmp/firbench-1-<lane>-<dispatch>-pytest` (use an isolated basetemp unique to the dispatch so pytest cannot clean another task's directories). Run the package formatter before lint, scoped to owned code paths. Tests import as `from scripts.eval_harness import <module>`.
4. **Bounded reads.** Never `cat` a large file. `report.py` is 5,982 lines and `face_metrics.py` 1,747: use `grep -n` and `sed -n 'a,bp'` ranges.
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
| `IdentityStatus` | StrEnum | `named`, `unknown`, `unresolved`. Set on every GT face. A named face is non-mated only when its identity is held out in the fold. An `unknown` face is non-mated only on an exhaustive frame. An `unresolved` face is never non-mated (S1 Build 7). |
| `SamplingArm` | StrEnum | `probability` (inverse-probability weighted), `challenge` (enriched). Set on every image unit and search record. The two arms are reported separately and never pooled. Not the pipeline `Arm`. |
| `FoldRole` | StrEnum | `fit` (calibration fold), `test` (held-out fold). Set by the rotation (S1 Build 8). |
| `AlignmentMode` | StrEnum | `separable` (the leg runs its own five-point alignment), `fused_internal` (insightface; alignment happens inside one call). |
| `LegKind` | StrEnum | `sface`, `auraface`, `insightface`, `canary` |
| `LegId` | frozen dataclass | `kind`, `arm`, `space_fingerprint`, `opencv_version`, `ort_version`; `.key()` gives a stable string |
| `FrameSpec` | frozen dataclass | `frame_id`, `admissibility`, `sealed`, `source_sha256`, `exhaustive` |
| `DecisionManifest` | frozen dataclass | see S0 (includes `min_n_independent`, `cell_floor_n_independent`, `p_d`, `power` and the delegated values; MCP 16733, 16736, 16756) |
| `UnsealToken` | frozen dataclass | `frame_id`, `frame_sha256`, `decision_sha256`, `run_id`, `code_sha`, `scorer_sha`, `consumed_at` (null until the first sealed read); see S0 Build 7 |
| `require_frame_read_allowed(frame, token, *, decision_sha256, run_id, code_sha, scorer_sha, repo_root, consumed_at) -> UnsealToken` | function | returns the consumed token with caller-supplied actual-attempt `consumed_at` from the separate non-replayable receipt boundary after atomic spending and ledger append; never substitutes an old seal time; raises `SealedFrameReadError` unless the token is unspent and bound to the frame and the explicit runtime keywords; S0 Build 7 (MCP 16756, 16773; current S0 producer signature) |
| `require_private_output_path(path, *, repo_root)` | function | raises `NonPrivateOutputError` unless the path resolves under `benchmarks/private/` |
| Interchange schemas | JSON Schema documents, draft 2020-12 | `frame-v1`, `face-search-record-v1`, `scores-v1`, `clusters-v1`, `comparison-v1`. Each carries `schema_version: 1`. Frozen by S0 Build 9. `validate_interchange(name, payload)` checks them with a stdlib checker (no new dependency) and raises `FrameContractError`. |
| Entry-point signatures | functions | Exact signatures in S0 Build 10. Batch-B lanes code against them unchanged. Before batch B, MCP 16736 fixes `run_frame` (`created_at`); MCP 16756 fixes `build_nonmated_pool` and the explicit frame-read runtime context. Preserve S0's required `consumed_at` keyword and `UnsealToken` return. |
| `reference_threshold_cluster(vectors, *, similarity_threshold)` | function | `firbench_clusters`. The one reference clustering function. S4 uses it for every partition metric and the dendrogram; S5 displays its labels and never recomputes them. The production loader `prepare_cluster_caches` is not used. |

**Non-mated source unit.** The only unit of the FPIR denominator, of FPI, and of the calibration pool. A unit is either (a) a non-mated GT face, or (b) one background unit per frame image, which holds the native-arm detections of that image that overlap no GT face. A no-face image has only its background unit. Units come from the exhaustive frame and are fixed before any run, so detector output never adds or removes one. Each frame image has exactly one background unit (MCP 16735). A duplicate detection that overlaps an already represented GT face creates no unit, and its extra above-threshold names count only as spurious names (EVAL-19). `build_nonmated_pool` refuses `exhaustive=false` (MCP 16756). A unit counts once in FPI when it emits any false accept. Non-mated source units are the only denominator in every fraction, interval and resolvability rule. `N_units` is the count of units in a pool.

**Error raise conditions.** Every error is a `FirBenchError` subclass in `firbench_contract`.

| Error | Raised when |
| --- | --- |
| `UnratifiedDecisionError` | a verdict is requested on a decision that is unratified or unsealed, or whose seal hash does not match |
| `SealedFrameReadError` | a sealed input is read without an unspent `UnsealToken` bound to that frame, decision, run, code and scorer through the explicit keywords of `require_frame_read_allowed`, or a verdict is requested on a sealed frame with an unsealed manifest |
| `CrossSpaceComparisonError` | a vector operation spans two `space_fingerprint` values |
| `RuntimeMismatchError` | the OpenCV or ORT version differs within one leg kind, or a cache key does not match its file |
| `CalibrationLeakError` | a calibration fit uses a probe, or any top-k gallery identity, from a test fold |
| `NonPrivateOutputError` | an image-bearing or run output path resolves outside `benchmarks/private/` |
| `ProjectionLeakError` | projection coordinates are passed to a metric |
| `LinkageMetricError` | Ward, median or centroid linkage is requested on cosine distance |
| `CanaryInSealedRunError` | a canary leg is requested on a sealed frame |
| `CanaryConfigError` | a canary declares fewer than two identities, or the permutation leaves a selected label fixed |
| `FrameContractError` | a frame loader finds a missing or malformed key, an `unresolved` face is requested as non-mated, an interchange payload fails its schema, `build_nonmated_pool` gets `exhaustive=false` or malformed component or fold coverage (MCP 16756), or a run timestamp is invalid, no `created_at` source exists, or an explicit literal mismatches the selected derived instant (MCP 16736, 16773; S0 Build 10) |
| `TauInfeasibleError` | the calibration pool is empty |
| `UndeclaredH2LegError` | `results` lack the H2 leg named in the sealed manifest, or carry results for another in-house leg as H2 |

`require_private_output_path` and the error names above are the only shared error surface. Lanes must not define a second error for the same condition.

Per-search record passed from S2 to S3 (`firbench_legs.FaceSearchRecord`, one `searches.jsonl` row, schema `face-search-record-v1`):

| Field | Type | Rule |
| --- | --- | --- |
| `face_id`, `image_id`, `psu_id` | string | `psu_id` from S1 Build 3 |
| `identity_id` | string or null | null for non-mated |
| `identity_status` | `IdentityStatus` | from the GT face |
| `fold`, `fold_role` | int, `FoldRole` | the face's fold and its role in the rotation |
| `cell` | pair | query occluder, enrolled occluder |
| `unit_id` | string or null | rules below |
| `sampling_arm` | `SamplingArm` | from the image unit |
| `inclusion_probability` | float or null | from the image unit; null on the challenge arm; the IPW weight is its reciprocal |
| `cohort` | object or null | `sex`, `age_band`, `origin`, each a string or null; null for background units |
| `leg_key`, `arm` | string, `Arm` | one row per (face, leg, arm) |
| `arm_availability` | `ArmStatus` | `available` unless the arm could not run |
| `alignment_mode` | `AlignmentMode` | `fused_internal` on the insightface leg |
| `stage_reached` | `SearchStage` or null | null only when `arm_availability = unavailable_fused` |
| `top_k` | tuple of `(identity_id, score)` | in the leg's own space; empty when the arm did not run |
| `gallery_sha256` | string | gallery snapshot id: the sha256 of the enrolled gallery searched |
| `timing_receipt_ref` | string or null | key of this face's row in `timings.json` |

For a non-mated GT face, `unit_id` is its `face_id`. For a native-arm detection that overlaps no GT face, `unit_id` is `background:<image_id>`, `face_id` is `det:<image_id>:<index>` and `identity_id` is None. Mated GT-face records and duplicate detections over a mated face have `unit_id` None.

## Run artifacts layout (the CLI writes; semantic files immutable once written)

```
<run_dir>/                              private by default: benchmarks/private/firbench/runs/<run_id>/
  manifest.json                         experiment_manifest.build_experiment_manifest output + firbench block (decision sha, frame spec, leg keys, seeds, unseal token id when sealed, `created_at`; MCP 16736)
  ledger/                               outcome_ledger rows, one per expected GT face per leg and arm; no background rows
  legs/<leg_key>/cache.npz              embeddings + detections, keyed by LegId.key() and image sha
  legs/<leg_key>/searches.jsonl         FaceSearchRecord rows, including background-unit records (native arm)
  scores.json                           S3 assessment (curves, τ, intervals, verdict, guardrails, cells, waterfall); includes timing receipt SHA and p95 veto state
  timings.json                          attempt and timing receipt; non-replayable, written once; pin identical receipt for full scores/report replay
  clusters.json                         S4 output
  report/index.html                     S5 output (+ .json, .csv); decisions transitively depend on the timing receipt through scores.json
benchmarks/private/firbench/unseal-ledger.jsonl       append-only UnsealToken rows; outside every run dir; local-only
benchmarks/private/firbench/spent/<frame_id>.spent    O_EXCL marker; a frame's sealed read happens once
```

**Replay boundary (FLOW-18; MCP 16773, 16777).** Semantic `created_at` selects seal time, else ratification time, else an explicit literal; only an explicit override must match the selected derived instant (S0 Build 10). Actual `consumed_at` stays in the non-replayable attempt/private unseal-ledger boundary. `scores.json` includes the timing receipt SHA and p95 veto state, so report decisions transitively depend on that receipt. Whole scores/report bytes replay only with all assessment inputs pinned, including one identical `timings.json`. Fresh physical timings are new assessment inputs and may change the real veto, scores and report. Across cold runs, compare pure searches and recognition ledgers; keep attempt receipts separate. For AE-7 full replay, create explicit verification snapshots with one fixed receipt and otherwise identical semantic inputs, leaving every original receipt intact. Also verify that a changed receipt can change the real veto and dependent report decision in an otherwise eligible fixture. Never mask or normalize actual veto/hash fields, overwrite original receipts, or reread a spent sealed frame for replay. Verification snapshots require no new CLI argument. This applies FLOW-18, **Make report recomputation deterministic or mark it non-replayable** (*Designing Data-Intensive Applications*, ch. 10), to pinned assessment inputs.

## Reaper rule

The coordinator prints a reaper command only for lanes whose `result.json` is terminal and whose work has landed. Never print a loop over in-flight lanes.

## Canon rows and cards cited

Inline IDs in these briefs name the rows below. The rule name (the bold text at the start of the Rule cell) and the source are copied from the pinned Canon v0.26.2 rows, with the Source cell as printed. `sr-NNN` and `rg-NNN` are not canon IDs. They are repo rules in the repository's `CLAUDE.md` (Short Rules and the `rg` list), and the briefs write them as `repo rule in CLAUDE.md`.

| ID | Rule | Source |
| --- | --- | --- |
| EMB-01 | One embedding space per comparison | Foundations of Vector Retrieval, ch. 1 |
| FLOW-18 | Make report recomputation deterministic or mark it non-replayable | Designing Data-Intensive Applications, ch. 10 |
| GRPH-33 | A node without a contract cannot be parallelised | practice label |
| EXP-12 | Power and practical significance | Trustworthy Online Controlled Experiments, ch. 2 |
| EXP-22 | No circular analysis (double-dipping) | Statistics Done Wrong, ch. 6 |
| EXP-23 | Pseudoreplication check | Statistics Done Wrong, ch. 3 |
| EXP-30 | Disclose specification spread | Seeing with Fresh Eyes: Meaning, Space, Data, Truth, ch. 4 |
| CAL-04 | Calibrate the threshold on matched non-mates | NIST FRVT Part 3 Demographic Effects |
| CAL-07 | Select face thresholds on identity-disjoint folds | Video-to-Video Face Recognition for Low-Quality Surveillance Data, ch. 6 |
| AUDIT-11 | Account for cluster design effect | Sampling: Design and Analysis, ch. 5 |
| EVAL-07 | Validation-only selection | Designing Machine Learning Systems |
| EVAL-16 | Upstream failure counts against the end-to-end metric | IARPA Janus Benchmark-C, § 2.3.4 |
| EVAL-18 | Non-mated probes and a score threshold, not rank | IARPA Janus Benchmark-C, § 2.3.4 |
| EVAL-19 | Do not let detector alarms dilute FPIR | IARPA Janus Benchmark-C, § 2.3.4 |
| WRIT-81 | Keep decision-changing limits in summary prose | tufte-beautiful-evidence § cognitive-style-of-powerpoint |
| HITL-03 | Gold-embedded annotator QC | Human-in-the-Loop ML |
| HITL-05 | Agreement is a diagnostic, not the truth | Human-in-the-Loop ML |
| HITL-07 | SME adjudication escalation | Human-in-the-Loop ML |
| MLDATA-03 | Resolve label multiplicity in writing | Designing Machine Learning Systems |
| MEAS-29 | Observe measurement production | Seeing with Fresh Eyes: Meaning, Space, Data, Truth, ch. 4 |
| VIZ-41 | Reveal the image-selection pool | Visual Explanations, ch. 1 |
| INT-21 | Specify interaction states | Microinteractions, ch. 3 |
| INT-24 | Specify loop exits | Microinteractions, ch. 5 |
| INT-25 | Map the handoffs | Microinteractions, ch. 6 |
| FORM-11 | Constrain before error | Microinteractions, ch. 3 |

**Cards and mirror coverage.** `CARD-03` (designed-unknown) has its body in the mirror. The exact `CARD-27` body was supplied separately at `/home/gate/firbench-1-context/canon-supplement/margin-and-design-effect-before-the-run.md`; SHA-256 `186c94c2b0ba88897cebea26c39752d6f0e87bbab8bff3ec1fa9aace79f85aad` matches the v0.26.2 release manifest. Its pre-run margin, method, harm-direction, α-allocation and design-effect requirements were checked for this revision. Computed detectable MDE remains distinct from the predeclared practical margin/SESOI (S3 Build 6). The mirror remains partial: 7 of 12 lexicon files and 4 of 33 manifest cards; the separate CARD-27 body resolves that card's coverage gap for this dispatch. Every row above is in one of the 7 files. `CARD-29` is not cited in these briefs. `IDX-02` (S2) and `MEAS-29` (S5, S7) sit outside the files this lane owns. The S5 use of `MEAS-29` for number-to-JSON traceability does not match that row, and the S5 owner should decide it.
