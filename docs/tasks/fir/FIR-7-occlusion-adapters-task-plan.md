# Task Plan — FIR-7. Occlusion-Robustness Adapters for YuNet + SFace

> **Metadata**
>
> - **Date**: 2026-07-23 (v2 — resolves adversarial panel FIR7PR-01..14)
> - **Author**: Claude Fable 5
> - **Owning Epic**: `docs/epics/v0.3.1/self-hosting-epic.md` (E22 face pipeline lineage; FIR series)
> - **Epic Short ID**: FIR
> - **Task ID**: FIR-7
> - **Target Branch**: `feature/fir-7`
> - **Review Coverage Target**: 2
>
> Review counts/finding totals live in the handoff DB, not this file.

---

## FIR-7. Occlusion-Robustness Adapters for YuNet + SFace

## Objective

Close the face pipeline's occlusion-robustness gap — measured on Golden-150 as masked synthetic recovery `a_s` 0.321 / sunglasses 0.226 and 54/84 masked re-detect misses — **with zero clean-face regression, using the cheapest sufficient lever (FM-05)**. This is a *conditional* deliverable: success is the gap closed to target via config levers alone (Slice 0), or one trained adapter, or two, whichever is the least-stateful intervention that clears a **hard, fail-closed re-gate recorded before any training**. Any produced weights are **owned, commercially-clean** (Apache-2.0 base + synthetic/self data + our own code). A Slice-0 config-only close is a valid PASS; producing two adapters is a fallback, not a target.

## Intake (new-feature scope pass)

- **Key Q&A decisions**: `decision #2939` (FIR-7 scope intake).
- **Scope**: cheapest-first. Config/pooling levers (Slice 0) are measured before any training is authorized; the detector fine-tune and the recognizer adapter are conditional slices, dispatched only if a pre-registered descope threshold says levers were insufficient. When both train, the detector is sequenced **before** the recognizer (the recognizer adapter trains on crops produced by the updated detector — FIR7PR-09).
- **Training data**: synthetic / self-only. Golden-150 twin renders on the consented corpus + license-checked synthetic-identity sets. NO research-only datasets (WIDERFace occlusion subset, MFR/RMFRD masked corpora are excluded — they taint commercial use).
- **Success bar**: a pre-registered hard gate (below), not advisory eyeballing. Robustness targets are advisory *numbers*; the pass/fail is the fail-closed non-inferiority + robustness-claim gate.
- **Not-Doing**: (a) no from-scratch FR training on WebFace-scale data; (b) no InsightFace/buffalo weights in the shipped path (non-commercial); (c) no new occlusion strata capture (mirrors gap, real-occlusion n) — this task consumes the existing corpus; (d) no production rollout/switch-over decision — that is FIR-6's gated S6; this task delivers candidate weights + sealed evidence only.

## Problem Statement

The shipped candidate pipeline (YuNet detect + SFace embed, Apache-2.0, 128-D) is occlusion-weak. Golden-150 (v6.1, run `face-run-20260723-074749`) measured, at leg=candidate:

- **Detection recall 0.504** on clean human-verified boxes (186/375 faces missed) — the detector is the dominant failure *even before occlusion*, and 0.504 is the real ceiling on end-to-end identification (FIR7PR-08). An occluded face YuNet never finds never reaches SFace, so recognizer-only work is capped.
- Synthetic occlusion recovery `a_s`: masked 0.321 (54/84 re-detect miss), sunglasses 0.226 (49/84), occlusion_other 0.643 (5/84). Real-occlusion legs sit at floor-limited n.

Two structural traps make the naive framing dangerous, and this v2 plan is built to avoid them:

1. **The eval can measure the renderer, not the model (FIR7PR-01).** Training twins and eval twins are both produced by `synthetic_occlusion.py`. If they share occluder assets and render-parameter distributions, a high synthetic `a_s` proves only that the adapter memorized *our renderer*, not that it generalizes to real masks. Synthetic `a_s` is therefore demoted to a **DIAGNOSTIC** signal; the claim-bearing legs are real-occlusion + an alternate-renderer stress leg.
2. **Objectives isomorphic to the gate metric Goodhart the gate (FIR7PR-02, EVAL-07/-08/-15).** Selecting checkpoints or hyperparameters on the same synthetic score the gate reports turns the gate into a training target. The plan seals a one-shot held-out eval and confines all selection to a train-split synthetic validation stream.

The commercial ceiling reference (InsightFace/buffalo) is non-commercial weights; buying a license or retraining from scratch are both heavier than a targeted, parameter-efficient adaptation of the already-owned Apache stack that we own outright — *if* Slice 0 proves config levers cannot close the gap first.

## Constraints

- **[C-EVAL-DISJOINT] Train/eval renderer disjunction (eval integrity, FIR7PR-01).** Training twins and eval twins MUST draw from **disjoint occluder asset pools and disjoint render-parameter distributions**: separate mask/sunglasses atlases, disjoint placement/scale/rotation/blend/lighting ranges, and separately content-hashed occluder packs (`occluder-pack-train-*` vs `occluder-pack-eval-*`). The generator refuses to emit an eval twin from a train-pack asset (and vice versa); a manifest test asserts pack-hash disjunction. Synthetic `a_s` is a **DIAGNOSTIC-tier** signal only. The **claim-bearing** occlusion legs are the real-occlusion legs plus an **alternate-renderer stress leg** (a second, independently-authored occluder pack the training never saw). Wired into Slice 1 (pack authoring + disjunction test) and the gate (below).
- **[C-GATE] Hard, fail-closed re-gate recorded before training (FIR7PR-06).** Before any Slice-2/3 training runs, a machine-checkable gate specification is committed. It has two tiers:
  - **MUST-pass (fail-closed, every artifact):** clean-face non-inferiority on all floors (per-floor table below), provenance/license audit passing, train/eval leakage checks passing, and — for the recognizer — a frozen-base assertion.
  - **MUST-for-any-robustness-claim:** a **real-occlusion** improvement with reported N and CI, OR an explicit `synthetic-only — NO robustness claim` stamp on the artifact's model card. Synthetic-only artifacts may ship as candidates but carry no robustness language.
  A failure of any MUST-pass condition fails the slice regardless of occlusion gain. No `enforce=False` equivalent — the gate is fail-closed.
- **[C-NONINF] Non-inferiority, not "within noise" (FIR7PR-03, CACE / EVAL-08, AUDIT-11).** Every clean-face floor is gated by a **pre-registered TOST-style non-inferiority test**: baseline value, N, an explicit delta margin, and the rule "the 95% Wilson-score CI lower bound of the adapted metric MUST be ≥ baseline − delta". Trained artifacts run **≥2 seeds**; the reported band is the seed envelope. The phrase "within noise" is **banned** from the plan and reports unless it resolves to this formula. Because Golden-150 draws multiple faces per image (cluster sampling), CIs use the cluster design effect (`n_eff = n/deff`, AUDIT-11), not raw frame count as independent n. See the per-floor non-inferiority table under Verification Strategy.
- **[C-SEALED] Sealed one-shot eval + train-split-only selection (FIR7PR-02, EVAL-07/-08/-10).** The Golden-150 gate eval is **pre-registered and sealed**: run **once per candidate artifact**, never used for checkpoint or hyperparameter selection. All checkpointing, early-stopping, and hyperparameter selection read a **train-split synthetic validation** stream only (identity-disjoint from the eval). A stated multiplicity policy governs the S0/S2/S3/S4 "peeks": each peek is a distinct pre-declared candidate, counted, and the final sealed number is reported exactly once per artifact (no re-seal after a fail).
- **Proprietary-clean provenance (legal gate).** Adapted weights must remain commercially usable: Apache-2.0 base (YuNet/SFace from OpenCV Zoo) + synthetic/self-generated training data + our own training code. Any research-only dataset in the training path voids this and is prohibited. The license allow/denylist is **code constants with fixtures** (FIR7PR-07d), and a passing license audit is a MUST-pass gate condition.
- **PEFT, not full retrain (FM-07).** Prefer frozen-base + small adapter / partial fine-tune over full-weight training. The recognizer adapter MUST freeze the SFace backbone; the detector prefers PEFT / partial-freeze over a full backbone update (FIR7PR-05).
- **CACE — Changing Anything Changes Everything (EVAL-08).** Any weight change ripples through detection → clustering → assignment → thresholds. Every adaptation is gated by a full Golden-150 re-gate under [C-NONINF]; a clean-face regression fails the slice regardless of occlusion gain.
- **[C-REEMBED] Full-corpus re-embed, no mixed space (FIR7PR-11, EMB-01, IDX-02).** Every re-gate **re-embeds the full corpus (gallery + probe)** through the adapted model; clustering, unknown-rejection, and full-corpus-ID floors are computed entirely in-space. A mixed-space assertion in the re-gate rejects any comparison whose two sides carry different `embedding_model`. No adapted-vs-base comparison without a re-embed.
- **PROV-01 / FIR23 lineage.** Each produced model gets a new `embedding_model` (and detector-model) identifier; the recognition read-path already filters on per-row `embedding_model` (merged FIR23-01). Each artifact carries a versioned model card (PROV-02).
- **Training runs in the cloud, not on-prem.** Operator laptop is 8 GB M1 (orchestration only). Rent a single A100/H100 for the campaign under a hard cost/time cap and teardown checklist (FIR7PR-07a). Synthetic identities carry no privacy constraint, so cloud training is clean.
- **Exhaust cheaper levers first (FM-05).** No weight training until Slice 0's config/pooling levers are measured and a pre-registered descope threshold emits a go/no-go `TRAINING_DECISION` artifact (FIR7PR-10); if levers close the gap, later slices are descoped and the task PASSES at Slice 0.
- **Determinism + reproducibility (rg-015, PROV-01).** Training is seeded and logged; produced weights are content-hashed and carry a model card. Eval is the existing Golden-150 harness — do not invent a parallel scorer.

## Workflow Principles

- **Measure against a frozen baseline, on the claim-bearing leg.** Every slice reports the Golden-150 delta vs the frozen v6.1 candidate baseline. Robustness deltas are read from the real-occlusion + alternate-renderer legs (claim-bearing); synthetic `a_s` is reported as DIAGNOSTIC context, never as the success number.
- **Selection and gating are different data.** Selection reads train-split synthetic validation; gating reads the sealed held-out eval once. Never cross the streams (EVAL-07/-10).
- **The eval harness is the source of truth.** Reuse `scripts/eval_harness` (twin renderer, `score-face`, floors, tier logic). The training-data generator is the SAME twin machinery — but with **disjoint train/eval occluder packs and identity split** ([C-EVAL-DISJOINT]).
- **Frozen base for the recognizer is a guard, not a proof.** SFace weights are never updated. This is a *forgetting guard*, but "LQ↑ without HQ↓" is a **measurement obligation** (AdaFace FAIR-NN), not "true by construction" — the adapter sits after the backbone and can still move clean embeddings, so clean preservation is tested per-epoch and at the gate (FIR7PR-04).
- **One legal owner of the data manifest.** A single dataset-provenance manifest declares every training source and its license; nothing enters training that is not in it and license-clean.
- **Cascade honesty (FIR7PR-08/-09, EVAL-16).** Detection failures count as identification errors in at least one reported end-to-end cascade metric. `a_s` is reported on a fixed denominator (faces re-detected by *all* legs) alongside a separate detection-coverage number, so a detector change cannot silently inflate `a_s` by moving its own denominator (EVAL-19).
- **No silent capability inflation.** Candidate weights and their sealed gate evidence ship together; no demo or claim references adapted-model numbers, or quotes a DIRECTIONAL/synthetic cell, without the tier label (FIR7PR-14).

## Terminology

- **Adapter**: a small trainable module (embedding-space residual bottleneck or low-rank conv delta) added to a frozen backbone; trained on the narrow occlusion target while the base is unchanged.
- **Mask-invariant adapter**: recognizer adapter trained so `embed_adapted(occluded)` matches the base clean template of the *same* identity while a margin term keeps *different* identities separated (see Slice 3 loss).
- **Twin**: a synthetic occluded render of a clean base face (mask / sunglasses / other) from a frozen landmark cache; the (clean, occluded) pair is the training and eval unit. **Train twins and eval twins use disjoint occluder packs** ([C-EVAL-DISJOINT]).
- **Occluder pack**: a content-hashed set of occluder assets + a render-parameter distribution. `occluder-pack-train-*` and `occluder-pack-eval-*` are disjoint; the **alternate-renderer** pack is a third, independently-authored pack used only in the claim-bearing stress leg.
- **Re-detect miss**: an occluded twin the detector fails to re-detect after occlusion is applied; the dominant candidate failure mode.
- **`a_s` (fixed-denominator)**: synthetic occlusion recovery accuracy over the **intersection of faces re-detected by all compared legs**, at the entity-disjoint transferred τ (CAL-07). Reported with a separate **detection-coverage** number. **DIAGNOSTIC tier** (FIR7PR-01/-14).
- **Cascade identification metric**: end-to-end accuracy where a face any stage failed to detect/associate counts as an identification error (EVAL-16). The claim-bearing operational number.
- **Evidence tier**: every gate cell is labeled **CONFIRMATORY** (real-occlusion, n ≥ threshold, sealed), **DIRECTIONAL** (real-occlusion n below threshold, or a single-seed peek), or **DIAGNOSTIC** (synthetic / renderer-coupled). Success language may not quote DIRECTIONAL or DIAGNOSTIC cells without the label (FIR7PR-14).
- **Train/eval identity split**: Golden-150 identities are partitioned; occlusion training uses only train-split identities and train-pack occluders, so the sealed eval (built on eval-split identities + eval-pack occluders) never sees a trained identity or a trained occluder as a probe.

## Current State Analysis

- **Works**: YuNet+SFace candidate leg runs end-to-end on Golden-150; twin pipeline generates pairs; `score-face` emits per-tag occlusion `a_s`, re-detect miss, floors, tier logic; per-row `embedding_model` provenance + fail-closed read-path (FIR23-01) already on main.
- **Broken/weak**: detection recall 0.504 (the real ceiling); masked/sunglasses recovery low with detection as the bottleneck; no training/adaptation harness exists (the harness is eval-only); no cloud training runbook; the twin generator currently has **no train/eval occluder-pack disjunction** — this must be built (Slice 1) before any synthetic number is trustworthy.
- **Misleading if untouched**: occlusion caption mining is "text-suggested" (operator overturned 13 in the sweep) — training-data occlusion labels come from the *rendered* twins (ground-truth by construction), NOT caption mining. A synthetic `a_s` read without the DIAGNOSTIC label would overstate real-world robustness (FIR7PR-01/-14).
- **Adjacent**: FIR-6 owns calibration/switch-over (S4-S6, operator-gated). FIR-7 produces candidate weights + sealed evidence that feed FIR-6's decision; it does not itself flip production.

## Target Outcome

The occlusion gap closed to target **with zero clean-face floor regression** (per-floor non-inferiority, [C-NONINF]), achieved by the **cheapest sufficient lever** and proven on a **sealed one-shot Golden-150 re-gate**. The end-state is one of three, all valid PASSes:

1. **Slice-0 close (preferred, cheapest):** config/pooling levers close the gap; the `TRAINING_DECISION` artifact records "no training needed"; no new weights are produced. PASS.
2. **Detector-only:** `yunet-occ` (Apache-clean, PEFT/partial-freeze) closes the dominant re-detect-miss gap; the recognizer stays base. PASS if the cascade metric improves under [C-NONINF] and the recognizer floors are unregressed.
3. **Detector + recognizer:** `yunet-occ` then a frozen-base `sface-occ-adapter`, sequenced (detector first, recognizer trained on updated crops). PASS if both clear their MUST-pass conditions and at least one carries a real-occlusion robustness claim (or an explicit synthetic-only stamp).

Any produced artifact is Apache-clean, content-hashed, carries a schema-valid model card, is integrated behind the existing model-swap seam with a **working, unit-tested rollback to base weights** (RLSE-10), and is stamped with a distinct `embedding_model`/detector id under a mixed-space guard. Final ship decision deferred to FIR-6's gate.

## Context Loading

> Minimum authoritative surfaces for the implementer.

- Rules: `docs/workbay/rules/testing-python.md`, `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/development-workflow.md`.
- Heuristics (v0.12.2 canon + distilled): `~/Development/heuristics-canon/lexicons/ml-systems.md` rows **FM-05/FM-07** (adaptation ladder / PEFT), **EVAL-07** (validation-only selection), **EVAL-08** (CACE slices), **EVAL-10** (sealed test before iteration 0), **EVAL-15** (benchmark contamination), **EVAL-16** (upstream failure counts end-to-end / cascade), **EVAL-17** (evaluate at the production pooling unit), **EVAL-18** (non-mated probes + score threshold), **EVAL-19** (endogenous denominator), **EMB-01** (one space per comparison), **EMB-02/03/04/07/09** (robust template, feature-norm proxy, quality-gated mining, fuse retained, uncertainty-penalized), **CAL-01** (per-stratum threshold), **CAL-07** (entity-disjoint threshold selection), **MLDATA-09** (filter deletes the regime under test), **MLDATA-10** (match training degradation to target stats), **MLDATA-11** (margin objective needs a label-noise path), **MLDATA-19** (measure identity linkage before a synthetic privacy claim), **MLDATA-20** (synthetic-train accuracy does not certify deployment), **AUDIT-11** (cluster design effect / n_eff), **PROV-01/02** (lineage / model card), **DRIFT-01/02/03** (non-stationary, version upstream, refit thresholds with the model), **RLSE-08/10** (rollback written before ship / model is a separately revertible artifact). Distilled: `~/Development/heuristics-canon-research/distilled/ml-systems/{adaface,handbook-face-recognition,hidden-technical-debt-ml,janus-benchmark-c}.md` — AdaFace **FAIR-NN** ("LQ↑ without HQ↓" is a measurement obligation), Handbook §1.3.3 (real-holdout regression), Janus (cascade + pooling-unit eval).
- Harness: `apps/prototype-description-service/scripts/eval_harness/{synthetic_occlusion,face_bakeoff,face_assignment,report,manifest,cli}.py`.
- Runtime seam: `apps/prototype-description-service/recognition/infrastructure/embeddings/face_pipeline_adapter.py`, `.../recognition/application/embedding/manifest.py`, FIR23 read-path (`label_inference.py`, `cluster_repository.py`, `health.py`).
- Corpus + evidence: `benchmarks/manifests/golden150-draft-20260723.json` (+ sidecar), `benchmarks/results/golden150-fir-{v2,final}-20260723/`.
- Handoff: FIR-7 (decision #2939), FIR-5 findings (BUFREV-*, FIR5GL-01 twin-wiring @9b33bca2), FIR-6 state.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `embedding_model` id | recognition backend | per-row model provenance (FIR23-01) | +0..2 new ids (`yunet-occ-*`, `sface-occ-adapter-*`) registered only if produced | yes — mixed-space guard must reject cross-model compares; full-corpus re-embed on switch ([C-REEMBED]) | `test_fir23_embedding_model_read_paths.py` + adapter-model registration + mixed-space-assertion test |
| face pipeline model loader | recognition backend | loads pinned YuNet/SFace ONNX | load adapted ONNX by id; **rollback to base by id, no code release** (RLSE-10) | yes — rollback path names the previous-good artifact (pinned base ids in `manifest.py`); load failure fails readiness (no silent partial load) | boot smoke + health readiness per id; **rollback unit test** |
| eval-harness leg | eval tooling | candidate (YuNet+SFace), buffalo (bench) | +adapted-candidate leg + alternate-renderer stress leg; fixed-denominator `a_s`; tier labels | no (additive; bench-gated pattern from FIR-5) | Golden-150 sealed run with `--leg`/model-id selection; tier-label report lint |
| dataset-provenance manifest | training tooling | none (new) | new manifest + license allow/denylist code constants | yes — schema test rejects research-only sources; fixtures assert allow+deny | provenance-schema test + license-constant fixtures |
| model-card artifact | training tooling | none (new) | new JSON schema + path pattern `benchmarks/models/<id>/model-card.json` | yes — schema test on required fields | model-card schema test |

## Proposed Solution

Cheapest-first, gated by a pre-registered fail-closed re-gate. Five slices, but **only Slice 0 and Slice 1 are unconditional**; Slices 2–4 fire only if Slice 0's `TRAINING_DECISION` artifact authorizes training.

- **Slice 0 (unconditional)** exhausts non-training levers, **stage-separated** (detection levers vs re-detect miss; recognition levers on the already-detected subset only), publishes a fixed sweep table + greedy stacking rule, and emits a go/no-go `TRAINING_DECISION` artifact against a pre-registered descope threshold (FIR7PR-10). If levers close the gap → task PASSES here.
- **Slice 1 (unconditional)** builds the clean occlusion training-data pipeline with **disjoint train/eval occluder packs** ([C-EVAL-DISJOINT]), a legal-provenance manifest, a strict train/eval identity split, and the full leakage matrix + synthetic-identity linkage audit (FIR7PR-13). This slice also commits the **hard gate spec** ([C-GATE]) and the sealed-eval registration ([C-SEALED]) before any training.
- **Slice 2 (conditional)** fine-tunes YuNet on occluded detection with a **multi-task clean-preserving loss** (FIR7PR-05) → `yunet-occ`.
- **Slice 3 (conditional, sequenced after Slice 2)** trains the frozen-base SFace mask-invariant adapter with a **non-degenerate, clean-preserving loss** (FIR7PR-04) on crops produced by `yunet-occ` (FIR7PR-09) → `sface-occ-adapter`.
- **Slice 4 (conditional)** integrates behind the model-swap seam with unit-tested rollback and runs the **sealed** full re-gate, reporting adapter-alone vs detector-alone vs joint under the shipping cascade.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| eval tooling | `scripts/eval_harness/cli.py` | `--leg adapted` / model-id selection for detector+embedder; `--leg alt-renderer` stress leg; sealed-run guard (one-shot per artifact) |
| eval tooling | `scripts/eval_harness/config_levers.py` (new) | Slice 0 lever sweeps, **stage-separated** (detection vs recognition), fixed sweep table, greedy stacking, `TRAINING_DECISION` emitter |
| eval tooling | `scripts/eval_harness/regate.py` (new) | full-corpus re-embed ([C-REEMBED]); per-floor non-inferiority (TOST + Wilson CI + deff); fixed-denominator `a_s`; cascade metric; mixed-space assertion; tier-label report lint |
| training (new) | `scripts/train/occlusion/data_pipeline.py` (new) | (clean, occluded) pair generation with **disjoint train/eval occluder packs**; synthetic-identity ingest; dataset-provenance manifest; leakage matrix + linkage audit |
| training (new) | `scripts/train/occlusion/occluder_packs.py` (new) | authored train/eval/alt-renderer packs; content-hashing; pack-disjunction test |
| training (new) | `scripts/train/occlusion/train_yunet_occ.py` (new) | YuNet detector fine-tune, multi-task `L_occluded + λ·L_clean` + hard-neg mining, seeded, checkpoint on train-split val, model card |
| training (new) | `scripts/train/occlusion/train_sface_adapter.py` (new) | frozen-SFace mask-invariant adapter; clean-anchor + cosine-margin loss; per-epoch collapse/drift diagnostics |
| training (new) | `scripts/train/occlusion/license_policy.py` (new) | allow/denylist code constants + SPDX ids + verification metadata + fixtures |
| training (new) | `scripts/train/occlusion/model_card.py` (new) | model-card schema + writer; `benchmarks/models/<id>/model-card.json` + `weights.onnx` |
| training (new) | `scripts/train/occlusion/README.md` (new) | numbered cloud GPU runbook (rent → dry-run → train → export → download → teardown) |
| runtime | `recognition/application/embedding/manifest.py` | register `yunet-occ-*` / `sface-occ-adapter-*`; pinned previous-good base ids for rollback (RLSE-10) |
| runtime | `recognition/infrastructure/embeddings/face_pipeline_adapter.py` | load adapted ONNX by id; adapter compose; rollback path; load-failure fails readiness |
| docs | `docs/tasks/fir/FIR-7-occlusion-adapters-task-plan.md` | this plan |
| provenance | `benchmarks/manifests/occlusion-training-data-provenance.json` (new) | license audit of every training source |
| gate spec | `benchmarks/gates/fir-7-regate.json` (new) | pre-registered gate spec ([C-GATE]/[C-NONINF]/[C-SEALED]) committed before training |

## Related Files

| File | Note |
| --- | --- |
| `scripts/eval_harness/synthetic_occlusion.py` | twin renderer — reused as training-data generator; enforce train/eval occluder-pack + identity split here |
| `scripts/eval_harness/face_bakeoff.py` | `build_occlusion_twin_pairs` (FIR5GL-01 @9b33bca2) — the pair-generation seam |
| `recognition/application/suggestions/label_inference.py` | FIR23 embedding_model read-path — mixed-space guard consumed by [C-REEMBED] |
| `benchmarks/results/golden150-fir-v2-20260723/` | frozen baseline for all deltas |

## Verification Strategy

- **Deterministic tests**:
  - `cd apps/prototype-description-service && uv run --extra dev pytest scene/tests -k "eval_harness" -q` (harness green; +lever/leg, regate non-inferiority, fixed-denominator `a_s`, cascade, tier-lint tests, mocked training).
  - `uv run --extra dev pytest recognition/tests/unit/test_fir23_embedding_model_read_paths.py` (mixed-space guard + new ids + mixed-space assertion).
  - **Occluder-pack disjunction test** (train/eval/alt packs are hash-disjoint; generator refuses cross-pack emission).
  - **Provenance-schema test** (rejects any research-license source) + **license-policy fixtures** (one research-only source FAILS, one Apache self-generated source PASSES; Vec2Face/DCFace pre-seeded with SPDX id + source URL + verification date + verifier).
  - **Model-card schema test** (required fields: base id+hash, data-manifest hash, seeds, hyperparams, train metrics, gate metrics, license pointer, ONNX hash, git SHA, trainer version; path pattern enforced).
  - **Rollback unit test** (reset to pinned base ids + reload; load failure fails readiness, no silent partial load).
  - **Frozen-base assertion test** (Slice 3: base SFace weights byte-identical before/after adapter train).
- **Runtime-parity / environment checks**:
  - `make check-remote` (full gate) at each integration point.
  - **Sealed** Golden-150 re-gate on the VM per artifact (one-shot): `python -m scripts.eval_harness.regate --artifact <id> --sealed && score-face --check-determinism`. Selection runs read the train-split synthetic validation stream only.
- **Contract/fixture verification**:
  - Boot smoke + health readiness per model id; rollback to base verified fail-closed.
- **Manual verification**:
  - Operator reviews the sealed per-floor non-inferiority table + tier-labeled gate cells per artifact.

### Per-floor non-inferiority table (pre-registered, [C-NONINF])

> Baselines from `golden150-fir-v2-20260723`. `n_eff = n/deff` (AUDIT-11). PASS = adapted metric's 95% Wilson CI lower bound ≥ baseline − delta, on ≥2 seeds for trained artifacts. Tier per cell.

| Floor metric | Baseline | Delta margin | Rule | Tier |
| --- | --- | --- | --- | --- |
| Clean detection recall | 0.504 | 0.02 | Wilson LB ≥ 0.484 | CONFIRMATORY |
| Clean-face full-corpus ID precision | (v2 value) | 0.02 | Wilson LB ≥ base − 0.02 | CONFIRMATORY |
| Clean-face full-corpus ID recall | (v2 value) | 0.02 | Wilson LB ≥ base − 0.02 | CONFIRMATORY |
| Unknown-rejection (non-mated FNIR@fixed-FPIR, EVAL-18) | (v2 value) | 0.03 | Wilson LB within delta | CONFIRMATORY |
| Clustering purity | (v2 value) | 0.02 | Wilson LB within delta | CONFIRMATORY |
| Clustering pairs (BCubed F) | (v2 value) | 0.02 | Wilson LB within delta | CONFIRMATORY |
| Cascade identification accuracy (EVAL-16) | (v2 value) | reported | improvement direction, N+CI | CONFIRMATORY |
| Real-occlusion masked recovery | (v2 value) | reported | improvement, N+CI; DIRECTIONAL if n<threshold | CONFIRMATORY / DIRECTIONAL |
| Alternate-renderer stress `a_s` | (v2 value) | reported | improvement, N+CI | DIRECTIONAL |
| Synthetic masked `a_s` (fixed-denominator) | 0.321 | context only | reported, no claim | DIAGNOSTIC |

## Slice Delivery

### Slice 0: Cheap-lever baseline, stage-separated (no training) — UNCONDITIONAL

**Goal**: Measure every non-training occlusion lever against Golden-150, **separated by pipeline stage**, and emit a pre-registered go/no-go `TRAINING_DECISION` artifact.

Changes:

- `config_levers.py` with a **stage-separated lever ledger**:
  - **Detection levers** (measured against masked re-detect miss / detection recall): YuNet `det_threshold` sweep, input-resolution / tiling, alignment crop-margin (0/20/40% context).
  - **Recognition levers** (measured **only on the already-detected subset**, with an explicit note they cannot recover re-detect misses): template pooling (quality-weighted aggregate, EMB-02/EMB-07), pre-normalization feature-norm quality weighting (EMB-03), uncertainty-penalized similarity (EMB-09).
- A **fixed sweep table** (param → discrete values) committed before running; a **greedy stacking rule** (add the best lever, re-measure, keep if it clears its floor); and an explicit **descope threshold** (e.g. "if stacked levers bring masked re-detect miss ≤ target AND cascade metric improves under [C-NONINF], emit `no-training`").
- Emit `TRAINING_DECISION` artifact (`benchmarks/results/golden150-levers-*/training_decision.json`) that the downstream lanes read as their go/no-go gate.

Proof:

- `benchmarks/results/golden150-levers-*/` delta table: per-lever detection R, masked/sunglasses `a_s` (fixed-denominator, DIAGNOSTIC), re-detect miss, cascade metric, and any clean-floor movement under [C-NONINF]. `TRAINING_DECISION` artifact committed. If it says `no-training`, the task PASSES at Slice 0.

### Slice 1: Clean occlusion training-data pipeline + disjoint packs + gate spec — UNCONDITIONAL

**Goal**: Produce (clean, occluded) same-identity training pairs with proven clean provenance, **disjoint train/eval occluder packs**, a strict train/eval identity split, a full leakage matrix, and the committed hard-gate + sealed-eval specs.

Changes:

- `occluder_packs.py`: author `occluder-pack-train-*`, `occluder-pack-eval-*`, and the independent `occluder-pack-alt-renderer-*`; separate mask/sunglasses atlases; disjoint placement/scale/rotation/blend/lighting ranges; content-hash each; **pack-disjunction test**.
- `data_pipeline.py`: generate training pairs over **train-split identities + train-pack occluders only**; ingest license-checked synthetic-identity faces (Vec2Face/DCFace — license verified via `license_policy.py` before ingest); emit `occlusion-training-data-provenance.json`.
- **Leakage matrix** (written): identities / images / templates / caches / preproc / global-stats — all norm/quality/lever selections fit on the train split only. Checks: (a) no eval-split identity appears in training; (b) **cross-set identity-linkage** between synthetic identities and Golden-150 under base SFace (MLDATA-19) — require weak linkage; (c) **NN-audit** of synthetic ids vs Golden-150 under base SFace; (d) a **real-holdout regression** check (MLDATA-20 / Handbook §1.3.3) — synthetic-train accuracy alone does not certify.
- Commit `benchmarks/gates/fir-7-regate.json` — the pre-registered [C-GATE]/[C-NONINF]/[C-SEALED] spec (floors, deltas, seeds, sealed-once policy, multiplicity policy) — **before** any Slice-2/3 training.

Proof:

- `occlusion-training-data-provenance.json` with a passing license audit; pack-disjunction test green; leakage matrix all-pass (linkage weak, NN-audit clean, real-holdout regression within [C-NONINF]); committed gate spec.

### Slice 2: YuNet detector occlusion fine-tune → `yunet-occ` — CONDITIONAL on `TRAINING_DECISION`

**Goal**: Reduce masked re-detect miss without regressing clean detection recall, using a clean-preserving multi-task objective.

Changes:

- `train_yunet_occ.py`: **multi-task loss `L_det = L_occluded + λ·L_clean`** with **hard-negative mining**; **PEFT / partial-freeze preferred** over a full backbone update (FM-07); a **clean-only validation stream + early stop** (guards catastrophic forgetting, FIR7PR-05); seeded (≥2 seeds), export ONNX, emit schema-valid model card.
- **Training Spec (locked defaults)**: optimizer/LR/schedule/epochs-or-steps/batch/weight-decay/seed(s)/early-stop metric+patience/grad-clip/input resolution; frozen/trainable layer set; `λ` clean weight; abort on divergence/NaN.
- Numbered **cloud GPU runbook** step-through (instance-by-peak-VRAM table, pinned env via Dockerfile + `requirements-train.lock`, data transport path+size+checksum, hard cost/time cap + kill criteria, "hello GPU" dry-run, teardown checklist with verification commands).
- Register `yunet-occ-*` id.

Proof:

- **Sealed** Golden-150 re-gate: clean detection recall non-inferior (Wilson LB ≥ 0.484, [C-NONINF]); report **FP rate + IoU + bootstrap-CI noise bands**, not only re-detect-miss; masked re-detect miss improvement on the claim-bearing legs. Model card + content hash committed to `benchmarks/models/yunet-occ-*/`.

### Slice 3: SFace frozen-base mask-invariant adapter → `sface-occ-adapter` — CONDITIONAL, SEQUENCED after Slice 2

**Goal**: Raise occlusion recovery with the SFace backbone frozen and clean-face embeddings **measurably** preserved, training on crops produced by the updated detector.

Changes:

- **Sequencing (FIR7PR-09)**: freeze `yunet-occ` → regenerate crops through the updated detect/align path → train the adapter on **those** crops (+ box-jitter / crop-margin augmentation). Not a parallel lane with Slice 2 for the coupled path.
- `train_sface_adapter.py`: freeze SFace; **locked adapter architecture** — embedding-space residual MLP `128→r→128`, zero-init residual (identity at start), param budget << backbone; insertion point after the base embedding. **Non-degenerate, clean-preserving loss** (FIR7PR-04):
  - (a) **clean-path anchor**: `||adapted(clean) − base(clean)|| ≈ 0` (identity on clean input);
  - (b) **contrastive / angular-margin term in COSINE space on L2-normalized embeddings**, with base clean templates as class centers (**mandatory, not optional**) — occluded embeddings pulled to their own clean center, pushed from other identities' centers.
  - Loss weights `α` (anchor) / `β` (margin) in the Training Spec.
- **Per-epoch collapse/drift diagnostics**: mean cosine to a frozen clean gallery ≥ 0.99; occluded inter-class separation floor; abort on collapse. "LQ↑ without HQ↓" is verified by measurement (AdaFace FAIR-NN), not asserted.
- Export composed ONNX + adapter module; schema-valid model card. Register `sface-occ-adapter-*` id (distinct `embedding_model`).

Proof:

- **Frozen-base assertion test** (base weights byte-identical). **Sealed** Golden-150 re-gate with **full-corpus re-embed** ([C-REEMBED]): clean-face floors (unknown-rejection, clustering, full-corpus ID) non-inferior under [C-NONINF]; real-occlusion + alternate-renderer recovery improvement (claim-bearing); synthetic `a_s` reported DIAGNOSTIC. Model card + hash committed.

### Slice 4: Runtime integration + rollback + full sealed re-gate — CONDITIONAL

**Goal**: Load produced artifacts behind the model-swap seam with an unit-tested rollback, and produce the final sealed head-to-head under the shipping cascade.

Changes:

- Load adapted ONNX by id in `face_pipeline_adapter.py`; SFace adapter compose; **rollback-to-base path (RLSE-10)**: previous-good = pinned base ids in `manifest.py`, config keys `FACE_DETECTOR_MODEL_ID` / `FACE_EMBEDDER_MODEL_ID`, rollback = reset to base pins + reload, no code release; **load failure fails readiness, no silent partial load**.
- Final **sealed** Golden-150 head-to-head reporting **adapter-alone vs detector-alone vs joint** under the shipping cascade (EVAL-16), with the fixed-denominator `a_s` + detection-coverage split.
- **Failure-mode dispositions (RLSE-08)**: training divergence/NaN/collapse → abort; re-gate fail → quarantine artifact to `benchmarks/rejected/`; partial success → ship detector-only path.

Proof:

- Boot smoke + health readiness green per id; **rollback unit test** green; `make check-remote` green; final tier-labeled delta table in `benchmarks/results/golden150-fir-adapted-*/`; handoff decision records each produced artifact + sealed evidence for FIR-6's gate.

## Lane Decomposition (Multi-Agent)

> Slices 0 and 1 are unconditional. Slices 2–4 fire only if Slice 0's `TRAINING_DECISION` authorizes training. **The detector→recognizer path is sequential, not parallel** (FIR7PR-09): the recognizer adapter trains on crops produced by `yunet-occ`, so `fir7-sface` depends on `fir7-yunet`.

### Lanes

| Lane ID | Owned Paths | Upstream Dependencies | Required Tests |
| --- | --- | --- | --- |
| `fir7-levers` | `scripts/eval_harness/config_levers.py`, `regate.py` | none | `pytest scene/tests -k eval_harness` |
| `fir7-data` | `scripts/train/occlusion/{data_pipeline,occluder_packs,license_policy,model_card}.py`, provenance manifest, gate spec | none | pack-disjunction + provenance-schema + license-fixture + model-card-schema tests |
| `fir7-yunet` | `scripts/train/occlusion/train_yunet_occ.py` | `fir7-data`, `TRAINING_DECISION=go` | sealed Golden-150 detector re-gate |
| `fir7-sface` | `scripts/train/occlusion/train_sface_adapter.py` | **`fir7-yunet`** (crops from updated detector), `TRAINING_DECISION=go` | frozen-base assertion + sealed recognizer re-gate |
| `fir7-integrate` | `recognition/.../face_pipeline_adapter.py`, `manifest.py` | `fir7-yunet`, `fir7-sface` | boot smoke + rollback + `make check-remote` |

### Merge Order

`fir7-levers` (may descope everything downstream) → `fir7-data` → `fir7-yunet` → `fir7-sface` → `fir7-integrate`. The yunet→sface edge is a hard sequencing dependency (coupled detect→embed path), not a parallelizable fork.

### Manifest

```bash
make lane-manifest-init TASK=FIR-7 LANE_IDS='fir7-levers fir7-data fir7-yunet fir7-sface fir7-integrate' TASK_PLAN=docs/tasks/fir/FIR-7-occlusion-adapters-task-plan.md
```

### Orchestration Mode

- **Remote grok lanes (preferred)**: training scripts + data pipeline are well-bounded grunt work; dispatch to grok lanes per the offload recipe, gated by adversarial review (≥1 local + remote grok reviewers).
- **Shell fallback**: repo lane helpers / manual worktrees preserving ownership + evidence.

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the minimum authoritative rules, heuristics (v0.12.2 + distilled), harness, and runtime seam before editing.
- [ ] Recorded the `embedding_model`/detector-id boundary ownership, mixed-space + full-corpus-re-embed expectation, and rollback contract.

### Checklist for Slice 0: Cheap-lever baseline (stage-separated)

- [ ] Lever sweeps implemented as reproducible harness options, separated into detection vs recognition ledgers.
- [ ] Fixed sweep table + greedy stacking rule committed before running.
- [ ] Recognition levers measured only on the already-detected subset with the explicit "cannot recover re-detect misses" note.
- [ ] `TRAINING_DECISION` go/no-go artifact emitted against the pre-registered descope threshold.

### Checklist for Slice 1: Training-data pipeline + disjoint packs + gate spec

- [ ] Train/eval/alt-renderer occluder packs authored, content-hashed, pack-disjunction test green.
- [ ] (clean, occluded) pairs generated over train-split identities + train-pack occluders only.
- [ ] Dataset-provenance manifest with passing license audit (schema test rejects research-only; fixtures assert allow + deny).
- [ ] Leakage matrix all-pass: identity split, cross-set linkage (MLDATA-19) weak, NN-audit clean, real-holdout regression within [C-NONINF] (MLDATA-20).
- [ ] Hard gate spec + sealed-eval + multiplicity policy committed to `benchmarks/gates/fir-7-regate.json` before any training.

### Checklist for Slice 2: YuNet detector fine-tune (conditional)

- [ ] Multi-task `L_occluded + λ·L_clean` + hard-neg mining; PEFT/partial-freeze; clean-only val stream + early stop.
- [ ] Locked Training Spec + numbered cloud GPU runbook (dry-run, cost/time cap, teardown) executable as written.
- [ ] Model card schema-valid + content hash; seeds ≥2.
- [ ] Sealed re-gate: clean detection recall non-inferior; FP rate + IoU + bootstrap-CI bands reported; masked re-detect-miss improvement on claim-bearing legs.

### Checklist for Slice 3: SFace mask-invariant adapter (conditional, sequenced)

- [ ] Trained on crops from frozen `yunet-occ` (+ box-jitter/crop-margin aug).
- [ ] Locked adapter architecture (128→r→128 zero-init residual) + non-degenerate loss (clean anchor + mandatory cosine-margin term).
- [ ] Per-epoch collapse/drift diagnostics (clean cosine ≥ 0.99, inter-class separation floor); frozen-base assertion test green.
- [ ] Sealed re-gate with full-corpus re-embed: clean floors non-inferior; occlusion recovery on claim-bearing legs; synthetic `a_s` DIAGNOSTIC-labeled.

### Checklist for Slice 4: Integration + rollback + sealed re-gate (conditional)

- [ ] Adapted ONNX loads by id; SFace adapter composes; rollback-to-base (no code release) works; load failure fails readiness.
- [ ] Boot smoke + health readiness green per id; rollback unit test green; `make check-remote` green.
- [ ] Final tier-labeled cascade head-to-head (adapter-alone / detector-alone / joint) + failure-mode dispositions wired; handoff decision for FIR-6's gate.

## Review Readiness

- [ ] No boundary-touching change without matching contract/model-id/rollback evidence.
- [ ] Runtime-parity (sealed Golden-150 re-gate + boot smoke) included where unit tests can mask real behavior.
- [ ] Every success statement carries an evidence-tier label; no DIRECTIONAL/DIAGNOSTIC cell quoted as a robustness claim.
- [ ] Handoff decision records each produced artifact, its provenance, its sealed gate delta, and the `TRAINING_DECISION`.

## Stretch Goals

- [ ] Occluded-stranger false-accept slice (FIR5RR-09 / EVAL-18) once stranger-occlusion members are boxed.
- [ ] Body/context embedding for association when the face is undetectable (Apple-style larger recognition area).

## Success Criteria

- [ ] The occlusion gap closed to target with **zero clean-face floor regression** under the pre-registered per-floor non-inferiority table ([C-NONINF]), proven on the **sealed one-shot Golden-150 re-gate** ([C-SEALED]) — achieved by the **cheapest sufficient lever** (a Slice-0 config-only close is a valid PASS).
- [ ] Every clean-face MUST-pass condition ([C-GATE]) holds fail-closed; any robustness claim is backed by a real-occlusion (or alternate-renderer) improvement with N+CI, else stamped `synthetic-only — no robustness claim`.
- [ ] Any produced artifact (`yunet-occ` / `sface-occ-adapter`) is Apache-clean with a passing license audit, a schema-valid model card, a content hash, and — for the recognizer — a passing frozen-base assertion.
- [ ] Any produced artifact is integrated behind the model-swap seam with a verified unit-tested rollback to base (no code release); distinct `embedding_model` ids stamped and mixed-space compares rejected; every re-gate re-embeds the full corpus in-space.
- [ ] All gate cells carry an evidence-tier label (CONFIRMATORY/DIRECTIONAL/DIAGNOSTIC); the report lint tags real-occlusion n<threshold as DIRECTIONAL-only; candidate weights + sealed evidence handed to FIR-6 for the switch-over gate; no production flip in this task.
