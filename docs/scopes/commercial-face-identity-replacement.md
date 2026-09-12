# Scope: Commercial Face Identity Replacement (FIR)

**Intake**: 2026-07-15 · task FIR-1 · answers recorded in handoff MCP
**Epic**: [E22 Commercial Face Identity Replacement](../epics/v0.5.0/commercial-face-identity-replacement-epic.md) · task plans in `docs/tasks/fir/`
**Assessment**: [docs/assessments/current/commercial-face-pipeline-replacement-assessment-2026-07-15.md](../assessments/current/commercial-face-pipeline-replacement-assessment-2026-07-15.md)

## Problem

InsightFace buffalo model weights are non-commercial; ACX is a commercial product. Production face identity (detection → embedding → clustering) must move to commercially licensed weights. InsightFace remains **internal-benchmark-only**, hard-separated from production paths (deps, images, DB).

## Intake decisions (recorded)

| Question | Decision |
| --- | --- |
| Accuracy release gate | **No fixed gate yet** — bake-off produces numbers first; gate is then decided and recorded in MCP before switch-over |
| Bench/prod embedding separation | Prod DB stays single-model (128D SFace) + per-row `embedding_model` provenance column; buffalo embeddings live only in eval-harness run artifacts / dedicated eval deployment (pgvector fixed-dim makes a shared column infeasible anyway; zero prod perf cost) |
| GPU scope | **CPU first** (prod is ARM CPU); A10 ONNX-Runtime-CUDA serves the bake-off, production GPU path is a follow-on |
| age/gender metadata | **Dropped** (was inaccurate, never product); possible follow-up after recognition is stable. Pose becomes landmark-derived proxies; quality gains AdaFace/MagFace-style embedding-magnitude signal |

## MVP scope

An ACX-owned face pipeline — YuNet 2026may (MIT) detection + 5 landmarks → five-point affine alignment (OpenCV `FaceRecognizerSF.alignCrop` semantics) → SFace 2021dec (Apache-2.0) 128D embedding → L2 normalize → existing clustering/representative machinery → pgvector cosine retrieval — running on the ARM CPU production path behind the existing `FaceDetectorProtocol`/`EmbeddingGeneratorProtocol` seams, with pinned model hashes + license files shipped in the artifact, buffalo weights removed from production images, and thresholds calibrated from an ACX-domain bake-off.

## Success criteria

1. Production images contain no InsightFace weights; `insightface` dependency only in a `[bench]` extra (today it ships via the `[face]` and `[gpu]` extras).
2. Scan → cluster → curate flow works end-to-end on YuNet+SFace with recalibrated thresholds; unknown-first failure mode until calibration lands — **falsifiable via the new observability surface** (per-scan detection count, assignment-vs-unknown ratio, quality-gate rejections, `embedding_model` in logs/metrics).
3. Bake-off report exists comparing YuNet+SFace vs buffalo_l reference (eval env only) on the extended golden corpus with identification P/R, false-merge/false-split, unknown-rejection, a **throughput/cost leg** (embeddings/sec + sec/image on ARM A1 and A10, cost per 1k images, p95 scan latency vs recorded budget), and per-slice metrics — **the occlusion family split first-class: `masked`, `sunglasses`, `occlusion_other` (each real + synthetic-paired; masks and sunglasses are distinct product-frequency failure modes in user uploads, cheap to split now), plus profile, low-res, blur, similar-people, demographic** — sized per the [FIR-5 slice sizing table](#fir-5-slice-sizing-ci-target-driven).
4. **Gate mechanism (RLSE-02/03)**: the bake-off report *proposes* gate criteria; the **operator** records the gate as an MCP decision; the FIR-6 switch-over slice is blocked until that decision exists, and the switch-over merge cites it. The implementing agent never judges its own gate.
5. Golden parity tests for landmark order, alignment affine, and embedding normalization pass on CPU in CI (`make check-remote` green).
6. Every production embedding row carries `embedding_model` provenance; model files are sha256-verified at image build **and at boot** (extended `check_model_cache`, fail-closed).
7. FIR-2's greenfield verification is recorded: live demo/prod tenants enumerated and operator sign-off on roster wipe / re-scan captured **before** the dimension flip.

## Assumptions

- Greenfield: no data migration; dimension 512→128 flips **both** surfaces together in FIR-6's gated switch-over slice (`EMBEDDING_DIMENSION` in `001_identity_schema.py:14` + `PGVECTOR_DIM` default in `db/settings.py` + all deploy configs); dev/eval exercise 128D earlier via the `PGVECTOR_DIM` env; tenants re-scan. **Assumption to verify, not fact** (AGT-03): FIR-2 enumerates live demo/prod tenants and records operator confirmation that rosters/curation may be wiped before any schema flip; a live tenant with curation worth keeping escalates to the operator.
- Clustering algorithms are dimension-agnostic (cosine on unit vectors) and need calibration only.
- Golden corpus grows via VLM-6 Golden-150 curation (locked at 150; earlier docs say Golden-100); eval tenant pattern from `scripts/eval_harness/` is reused.

## Task decomposition

| Task | Title | Depends on | Core deliverables |
| --- | --- | --- | --- |
| **FIR-2** | Pipeline seam hardening + provenance | — | **Two slices (REF-05)**: (a) seam refactor — model-neutral detection/embedding dataclasses (strip `embedding_512`, age/gender, native pose), centralize embedding-dim in settings (constant only; defaults flip in FIR-6's switch-over), `embedding_model` column + typed model manifest (DOM-05); (b) contract change — drop age/gender columns/exports/API projections **after a consumer audit** (WP plugin + workbench + `stores.py`/`export_service.py` callers; DATA-03). Plus: greenfield verification — enumerate live tenants, record operator wipe/re-scan sign-off |
| **FIR-3** | YuNet+SFace adapters | FIR-2 | OpenCV CPU reference impl (semantic golden); ORT CPU adapters with identical preprocessing; model files pinned by sha256 + license files + source URLs in a provenance manifest; OpenCV 4.12-vs-5 pin decision; golden tests (landmark order, affine, normalization) |
| **FIR-4** | Runtime integration (dark) + license isolation | FIR-3 | scan_worker/inline wiring **behind a face-pipeline profile flag — production default stays on the current pipeline until the FIR-6 switch-over** (RLSE-07); `FacePipelineSettings`; `check_model_cache` extended to sha256-verify at boot (fail-closed) + build-time verification; observability surface (per-scan detection count, assignment/unknown ratio, quality-gate rejections, `embedding_model` in logs/metrics); **no dimension-default change** (dev/eval exercise the 128D pipeline via the `PGVECTOR_DIM` env — keeps every FIR-4 slice mergeable dark, no slice hostage to FIR-6's gate); Docker/deps rework; insightface → `[bench]` extra (out of `[face]`/`[gpu]`); mac install script replacement; repo-wide docs/runbooks sweep for buffalo/insightface references |
| **FIR-5** | Bake-off harness extension | FIR-2 (scaffolding); **FIR-3 for candidate legs** (adapters supply preprocessing-parity YuNet+SFace candidates — duplicating preprocessing in the harness would invalidate the bake-off) | Offline candidate leg (in-process detector+embedder over golden corpus) or env-selected eval-instance profile; false-merge/false-split + cluster-purity + unknown-rejection metrics; **throughput/cost leg + recorded perf budget** (PERF-01/06/07); per-slice rollups with the **occlusion family first-class as three tags — `masked`, `sunglasses`, `occlusion_other`** (real occluders + deterministic synthetic-occlusion paired protocol per tag); slice floors per the [sizing table](#fir-5-slice-sizing-ci-target-driven); demographic slices (Fair-SA); buffalo_l reference leg confined to eval env + run artifacts; corpus hard-slice extension |
| **FIR-6** | Calibration + quality rework + hard-case recovery + switch-over | FIR-4, FIR-5 | Quality signals: landmark pose proxies, sharpness, embedding magnitude (AdaFace/MagFace), **occlusion-severity proxy** (landmark confidence + eye-region patch stats); occlusion-adaptive threshold adjustment via existing `compute_identity_quality().threshold_adjustment` (OACT pattern, 2607.03581 concept); **Hungarian within-photo one-to-one assignment** (2606.23230, `linear_sum_assignment`) — applied after the quality gate, disabled for mirror/collage cases per the mirrors-stratum measurement; representative/medoid aggregation tuning; similarity/unknown/ambiguity-margin calibration on ACX data; bake-off report **proposing** gate criteria; **operator records the gate decision in MCP; switch-over slice is blocked until it exists** — the switch-over slice flips the flag default, flips the dimension defaults (`EMBEDDING_DIMENSION` in `001_identity_schema.py:14` + `PGVECTOR_DIM` in `db/settings.py` + enumerated deploy configs: `.env*`, `docker-compose*.yml`, `infra/oci`, reset scripts), and removes buffalo from prod images |
| FIR-7 (follow-on) | A10 GPU production path | FIR-6 | ORT-CUDA providers, FP16 + threshold recheck, engine caching |
| **FIR-8** | Recognition-profile bench toggle | FIR-5 | Cross-stack bench toggle infrastructure (`scripts/bench/`) enabling profile-selected comparison runs, consumed by FIR-16's open-set leg; see `docs/tasks/fir/FIR-8-recognition-profile-bench-toggle-task-plan.md` |

### FIR-5 slice sizing (CI-target-driven)

Floors are set by interval math, not feel. Assumptions stated: Wilson 95% intervals at worst-case p̂=0.5 (half-widths shrink if measured rates are extreme); paired comparisons use a McNemar-style test at α=0.05, power 0.8, degradation-dominant discordance. **Rule (mirrors VLM-6's locked stance): a slice below its floor reports DIRECTIONAL ONLY and cannot enter the gate decision.** Statistical power for the occlusion family comes from the **synthetic-paired protocol** (twins are generated, not curated — free at any n); real-tagged slices are deliberately small and serve as **ecological-validity checks** (report per-face degradation correlation between synthetic and real occluders; divergence >⅓ demotes the synthetic slice from gating to directional).

| Slice | Source | n floor | Resolution at floor | Gate role |
| --- | --- | --- | --- | --- |
| Headline identification P/R | celebs01 faces within Golden-150 | ≥100 faces | ±10% (Wilson 95%) | **gating** |
| `masked` (synthetic-paired) | generated twins of every roster face | ≥90 pairs | detects Δ≥10 pts paired accuracy drop | **gating** |
| `sunglasses` (synthetic-paired) | same | ≥90 pairs | Δ≥10 pts | **gating** |
| `occlusion_other` (synthetic patch) | same | ≥90 pairs | Δ≥10 pts | **gating** |
| Unknown-rejection (strangers absent from roster) | uploads strangers (plentiful, unpublishable) | ≥43 faces | ±15% | **gating** |
| `masked` (real) | curation-tagged corpus images | ≥15 | ±23% | validity check for synthetic `masked` |
| `sunglasses` (real) | same | ≥15 | ±23% | validity check |
| `occlusion_other` (real) | same | ≥20 | ±20% | validity check |
| `profile`, `low_res`, `blur` | curation tags within Golden-150 | ≥25 each | ±18% | diagnostic (directional) |
| `similar_people` | multi-face photos with ≥2 roster identities | ≥10 photos | n/a (per-photo Hungarian eval) | diagnostic (directional) |

Reference half-widths (Wilson 95%, p̂=0.5): n=15→±22.6% · n=25→±18.2% · n=43→±14.3% · n=96→±9.8% · n=150→±7.9%. Paired floors: Δ≥20 pts→~25 pairs · Δ≥15 pts→~40 · Δ≥10 pts→~90 (conservative under all standard McNemar power readings).

Consequences: the corpus stays locked at 150 (operator labor is the binding constraint) — the real-tag floors above are **selection guidance for the operator's ~112 hard-strata additions**, not a corpus expansion demand; anything that can't fit stays directional. The gate rests on the headline, the three synthetic-paired occlusion slices, and unknown-rejection — all reachable without additional curation labor.

## Coordination with VLM-6 (Golden-150 harness, in flight)

VLM-6 S1/S2 builds most of what FIR-5 needs; FIR must reuse it, not fork it (NAME-02/REF-10: no parallel corpus, no synonym schema fields). Six adjustments, ordered by urgency — items 1–3 are cheapest **during the current S1 curation pass** (operator labor is VLM-6's locked binding constraint; a second tagging pass would double it):

1. **Slice tags = VLM-6's manifest `domain` surface — which needs a concrete schema change.** The landed `Domain` (`scripts/eval_harness/manifest.py:51`, a **single-valued StrEnum**) carries none of the gating tag values. Ask, precisely: extend the enum with `masked`, `sunglasses`, `occlusion_other`, `profile`, `low_res`, `blur`, `similar_people`, `unknown`, and turn the per-entry scalar into a **list** (either `domains: list[Domain]` or an additive `tags` list field — an image is legitimately both `masked` and `low_res`). Canonical names are the ones above: VLM-6's "low-light" stratum maps to `blur`/`low_res` at tagging time. FIR-5 owns the schema edit (`GoldenEntry` + `enrich_entry` persistence) if VLM-6 doesn't take it; the operator-facing part — tagging at curation time — is the non-repeatable piece (a post-pass split costs a second operator pass; see artifact `FIR-1-curation-addendum-tag-vocabulary-20260715`).
2. **Persist ALL curated face boxes** (named + anonymous strangers, `name=None`) per manifest entry — ✅ **LANDED on main**: `FaceBox` + `GoldenEntry.face_boxes` (`scripts/eval_harness/manifest.py`) + `export_identities.py` persistence, regression-tested (VLM-6 decision `claude_vlm6_fir1_face_boxes_enablement` @a2465e01, merged @5017c6d9). Kept here as the record of what FIR's detector leg consumes: box-level detection ground truth, not just `face_count`.
3. **Anti-blind-spot rule in curation instructions**: cluster drafts come from the buffalo-backed service, so faces its detector misses never appear as drafts. Operator must add missed faces during curation (or via XMP region tagging), else FIR inherits buffalo's detection blind spots as the truth ceiling — biasing the bake-off toward the incumbent.
4. **S2 candidate registry stays modality-agnostic**: registry schema + run-record face sections must not be caption-hardcoded ("face legs vacuous by design" was a VLM-2B scope choice, not a schema invariant). FIR-5 registers detector+embedder candidates in-process and reuses the same `fetch_run_record` walker (per-item isolation, rg-007 bounded stall), determinism re-score, and report machinery.
5. **Rules adopted verbatim from VLM-6 locked decisions**: celebs01-only publishability (`is_publishable()` fail-closed — FIR bake-off reports/galleries included); identification P/R scored on celebs01, hard strata on uploads (never published); eval/prod tenant separation — FIR's offline leg touches no tenant at all, and the buffalo_l reference leg runs only in the non-commercial eval environment.
6. **Co-schedule GPU work**: FIR's GPU legs (ORT-CUDA candidates) should ride VLM-6's single S3 A10 window or explicitly book a second window — GPU hosts stay off otherwise. The S2 runner freeze must either include FIR face legs or FIR runs its own driver against the same corpus + manifest.

Sequencing: FIR-5 consumes VLM-6 S1 outputs (curated manifest + roster + face regions + retained full-res originals — also required for FIR's synthetic-occlusion pairs). FIR-5's harness work can start against the 37-entry golden manifest v2 immediately; slice-level occlusion conclusions wait for Golden-150 curation.

**Fallbacks if VLM-6 declines or slips** (ARCH-06 — every ask has a downside plan): asks 1–3 missed in the S1 window → FIR-5 runs a bounded post-pass tagging session (operator, ~1 h, occlusion/profile/blur tags + missed-face additions only); S2 registry stays caption-hardcoded → FIR-5 ships its own thin driver over the same corpus + manifest (accepting the walker duplication cost, recorded as a decision); face boxes not persisted → FIR detection metrics degrade to count-based P/R and the gate proposal must say so explicitly.

## Rollback (RLSE-08)

Written before ship, staged by phase:

- **Pre-switch-over** (FIR-2..FIR-5, pipeline dark): full revert is trivial — the flag never flipped, production never left the current pipeline, dimension defaults never changed (they flip only inside FIR-6's gated switch-over slice). FIR-2's additive provenance column and age/gender drops revert via branch revert + the standard greenfield reset.
- **At switch-over** (FIR-6): the deploy that flips the flag keeps the previous release image tagged; rollback = redeploy previous image + restore `PGVECTOR_DIM`/schema via the standard greenfield reset (embeddings regenerate by re-scan; no data restore needed by design). Buffalo weights may still exist in the *previous* image at this point — lawful because the product is not yet switched commercially; the launch checklist orders weight removal **before** commercial exposure.
- **Post-launch** (buffalo removed, product commercial): the embedder is **roll-forward-only** — reverting to buffalo is license-barred. Degradation path instead of rollback: the face-pipeline flag can disable recognition entirely; scan intake fails closed (existing `UnavailableFaceDetector`/capability-heartbeat machinery), alt-text captioning and the rest of the product continue. Escalation then follows the failed-gate escalation ladder (see Not-Doing; unowned, parked — not FIR-8), not a weight revert.
- **Old-build/new-data compatibility** (DATA-03): a rolled-back build reading a 128D schema (or vice versa) fails loudly at the unit-norm/dimension boundary — acceptable under greenfield reset semantics and stated here so nobody expects dual-read.

## Not-Doing

- Video/track pipeline (companion doc exists; separate future epic).
- age/gender attribute model (follow-up only after recognition is stable).
- Custom model training, dataset licensing, or fine-tuning **in the MVP**.
- Failed-gate escalation ladder (unowned, parked): SFIQA-class learned quality model (2602.07403) → SeetaFace6 audit → licensed InsightFace quote → commercial SDK comparison → (last) occlusion-aware embedder training (synthetic-data SFace / LaCoVL / OccFace as references); YuNet retrain with depth-aware occlusion compositing (2512.11683) only if the bake-off attributes occlusion losses to *detection misses*. Entry: an operator-recorded gate decision with a `fail` verdict on any gating metric/slice. No task number assigned; not FIR-8 (FIR-8 is the recognition-profile bench toggle, a Phase C dependency that must exist before the gate decision — assigning the escalation ladder to FIR-8 would create a dependency cycle).
- HNSW indexes (exact ivfflat/cosine is fine at current roster sizes; add only on measured latency need).
- Commercial SDK or managed-API integration (bake-off comparator at most, behind the failed-gate escalation ladder, unowned/parked).
- Model-registry service or multi-dimension vector query layer (provenance column only — REF-12).
- GPU-class hard-case models in the live path: diffusion super-resolution (2607.05702), GAN-inversion/SAM occlusion segmentation (2602.00635), CLIP-based fusion (2605.19821), LRM 3D reconstruction (2601.12736). S3POT-class segmentation at most as offline GPU curation labeling.
- Detector or embedder retraining in the MVP (Depth-Copy-Paste augmentation and occlusion-aware embedder training live behind the failed-gate escalation ladder, unowned/parked).
- TensorRT / native engine work (post-FIR-7 at earliest).
- Migration/shadow-mode tooling in production (greenfield; shadow comparison lives in the eval harness).

## Re-plan addendum 2026-09-11

Decision #10843 (session `firplan-1-replan-20260911`). No new epic — E22 is revised in place; see the epic's [Status 2026-09-11 Re-plan](../epics/v0.5.0/commercial-face-identity-replacement-epic.md#status-2026-09-11-re-plan).

### What changed

- Headline gate metric is now explicitly **D3 = FNIR at a fixed FPIR** (open-set, non-mated probes, score threshold swept), FPI reported as an integer count, never a rate. The operator ratifies the fixed FPIR operating point; plans name the parameter and the ratification step, never a hard-coded value.
- Corpus locked at **Golden-150 as remediated by FIR-11 R1** (150 − 7 − 3 → 30 entries / 30 probes / 17 identities usable for the paired Nam/Tango non-inferiority check; Product A/B split). FIR-11 rev 7 is the corpus plan of record; new plans consume it, never restate it.
- **No A10 spend and no SCRFD/AdaFace retrain before D-01**, reached only via T-09 → T-14 → D-01. Occlusion work is inference-only (no training) until D-01 says otherwise.
- **`acx-dev-fir` (FIR23-STACK) must exist before any head-to-head**; the head-to-head runs both stacks over public APIs — two embedding spaces require two databases.
- Ledger fact: the FIR-12 open-set harness and the FIR-5 face bake-off are on `main` (FIR-12 merge `d567a341c` 2026-08-22, exemption rule `fa3341409`; FIR-5 merge `c10eac1d8`). No bake-off has been run.
- Withdrawn numbers (never cite as evidence): M-12 0.865/0.321, recall 0.504, 2.73 faces/image, every pre-CVUP-1 (OpenCV 4.x) artifact. "Embedder leads detector" is a hypothesis, not a result, pending FIR-15.

### New task rows (Epic Short ID FIR; titles are canonical)

| Task | Title | Depends on | Core deliverables |
| --- | --- | --- | --- |
| **FIR-13** | Open-set gate contract: face rubric, D3 declaration, T-14 adjudication rule | FIR-12 (merged) | `benchmarks/protocols/face-label-rule.md` (T-09 rubric, frozen, versioned); `gate_contract.py` (`GateContract`, `select_gate_point`, D3 declaration, operating point held `null` pending operator ratification); `union_adjudication.py` (T-14 bound, bootstrap UCL, `DeadZoneVerdict`, all four mandatory conditions) |
| **FIR-14** | OpenCV-5 re-baseline and pre-CVUP-1 artifact withdrawal | FIR-13 | `benchmarks/results/WITHDRAWN.md` withdrawal register; toolchain provenance block on face reports; CV5 re-baseline run on both legs (DIAGNOSTIC tier, corpus not yet remediated); toolchain arm artifact for FIR-11 S5 |
| **FIR-15** | Attribution: alignment-vs-embedder split and oracle occlusion ladder | FIR-13, FIR-14 | T-01 four-arm split harness (`attribution_split.py`) with paired-bootstrap share intervals; oracle-before-predicted occlusion ladder (`occlusion_ladder.py`); D-02 decision packet |
| **FIR-16** | Open-set head-to-head: face_pipeline vs buffalo_l on acx-dev-fir | FIR-13, FIR-14, FIR-11 R1, FIR23-STACK, FIR-8 | Persisted per-face `MediaIdentity.match_score` and `MediaIdentity.match_cluster_id` exported (S1a, greenfield schema edit; pre-gate best centroid, captured before the similarity-threshold filter); open-set leg in the cross-stack bench (`score_open_set`, open-set report section); `propose-gate` CLI + operator decision template; live run on `acx-dev-fir` |
| **FIR-17** | Inference-only occlusion robustness: OACT sign fix (S0), visible-support matching (S1), pose head rescue (S2), branch handoff (S3) | S0 unconditional; S1–S4 depend on FIR-15's D-02 (attribution verdict) | S0 OACT sign fix (`compute_quality_adjustment`, never relax the threshold under occlusion) — runs before D-02 in every branch (EMBEDDER, DETECTOR, INCONCLUSIVE); S1 visible-support (periocular) matching behind a knob (EMBEDDER branch); S2 pose head-region rescue is ADR-only (no knob, no runtime code — deliverable is the ADR plus a named follow-up task); S3 docs-only handoff (DETECTOR/INCONCLUSIVE branches); S4 confirms `masked_cosine`'s single definition (EMBEDDER branch) |

### Dependency edges

- FIR-13 → FIR-14 → FIR-15 → FIR-17 S1–S4 (branch-gated on D-02); FIR-17 S0 is unconditional and lands before D-02, so it does not wait on FIR-15's attribution verdict
- FIR-16 depends on FIR-13, FIR-14, FIR-11 R1, FIR23-STACK, FIR-8
- FIR-6 S4 (calibration on the remediated corpus, including the FIR-17 S0 OACT direction fix) runs **before** the FIR-16 live run
- FIR-6 S5/S6 (final threshold, switch-over) run **after** the FIR-16 gate decision

### New Not-Doing items

- SCRFD/AdaFace retrain of any kind before an operator-recorded D-01 kill/keep decision.
- A10 (GPU) spend of any kind before D-01.
- VLM-6 caption bake-off work — separate program; the only coupling is the shared eval manifest schema.
- Head/torso secondary channel (C4) as an identity claim — association-only if ever built, deferred.
- `PGVECTOR_DIM` flip outside FIR-6 S6 — the dimension default moves only in the gated switch-over slice, never earlier.

### Pointers

- Spec: `docs/specs/fir-open-set-gate-and-occlusion-spec.md` (item prefix `FIRG-001…`)
- Roadmap: `docs/roadmaps/fir-occlusion-robust-recognition-roadmap-2026-09-11.md`
