# FIRBENCH-1 · D-p0-gt ground-truth qualification (2026-10-15)

**Status: NOT QUALIFIED as independent exhaustive ground truth.** This is a bounded qualification of the inspected scope only. It is a proposal and evidence artifact. It is not implementation, not acceptance, not a ratification or amendment of the v6 record, and not an input to any outcome run.

Scope limits, stated once:

- Absence of evidence below is bounded to the inspected paths and external context files listed in §2. It is not a VM-wide or global absence claim.
- No image was opened, hashed, transferred, or inferred from. The laptop corpus figures are an availability observation only (§2.3).
- No human labeling, observation, or QC was simulated. No human contextual observation was performed here (MEAS-29 gap, §8).
- No seed, threshold, bootstrap count, replicate count, or margin was tuned. No winner is named. No numeric default is asserted from canon.
- Private alias maps were not read. No human names, pseudonym roster entries, private paths, or private IDs are reproduced in this file.

## 1. Result

| Question | Result |
| --- | --- |
| Is any frame qualified as independent exhaustive GT? | **No.** No candidate frame has an exhaustive, detector-independent human audit record covering every face, including missed, unnamed, and unresolved faces. |
| Are the GT boxes detector-independent? | **No.** Every box in the golden-150 draft is either detector geometry (369) or a manual operator box (6). The 1,763 detector-only corpus boxes are not GT. |
| Are the named identity labels reusable? | **As dated historical operator labels only.** They are not independently verified, and the three candidate frames share one workbench lineage. |
| Are the unnamed/stranger faces verified as true negatives? | **Not established.** 208 golden-150 boxes are unnamed; no per-box verification record exists. |
| Is annotator independence established? | **No.** One operator role is recorded. No second reader, inter-rater record, or QC record was found. |
| Is capture-occasion / PSU independence established? | **No.** Session identifiers are absent from the tracked manifests. The sanitized laptop snapshot reports unresolved sessions. |
| Is any v6 failure changed by this report? | **No.** The failed v6 gates (H2 boundary, clear_mask cell power) are untouched. Independent116/2000=.058 does not replace the failed row. |

## 2. Inspected inputs

### 2.1 Tracked paths (this checkout, commit `41cee52`)

Hashes are SHA-256 of the working-tree bytes at inspection time. Git blob IDs are listed where relevant.

| Path | Role | SHA-256 |
| --- | --- | --- |
| `benchmarks/manifests/golden150-draft-20260723.json` | golden-150 draft manifest, `manifest_version` 2, 150 entries (git blob `e9b2263e6d2ee4b5dba9850c72da78dd9a37be4d`) | `0dc89a1d0378630522a16080a176c1533357419fcfbe704a7c2bfc487580ac54` |
| `benchmarks/manifests/golden150-draft-20260723.sidecar.json` | golden-150 sidecar: build notes, clamp log, counts, per-media operator blocks | `2f3e04ffcdb5ff1b0ed9bdceefd001dac818304daf2bc34d19c9c189263421a3` |
| `benchmarks/manifests/golden150-selection-v1.json` | golden-150 selection, names `corpus-manifest-v3.json` | `50ad031d4dca14dcf2aaaab7633c5ec16732826ffb73211566fe0760aad06924` |
| `benchmarks/manifests/fir12-selection-v1.json` | FIR-12 selection, 640 entries (git blob `f2c6c0f912cc254e824dd9761148a2d21bc393b4`) | `26738d63d88fec632981f7229803898ba34a9356d8232ed5c6301d27293aa49f` |
| `benchmarks/manifests/corpus-manifest-v3.json` | corpus manifest v3, named by the golden-150 selection | `154eb2b735f947e5ce670886bb848fc2749aad5e952a448a4f1b75f3125abe7e` |
| `benchmarks/manifests/corpus-manifest-v3r-20260814.json` | corpus manifest v3r, 646 entries, the catalog-resolved manifest | `2d9d5ba3e04bcfa7ea29f960b2fdc05431bdae7993bd22042a5369ceee7d9bff` |
| `benchmarks/manifests/corpus-catalog-v1.json` | catalog, logical ID `corpus646-originals` | `b7ad36bef33f1553848080a4083b50af78b6a99ba5f21b65fc1d20e604155281` |
| `docs/tasks/firdv/firbench-1/inventory.md` | W2 inventory §0–§10 | `fcfc28d7290794fc5199b77aa44cfeeff156cafcb1cc9b271d81abb320fd150e` |
| `benchmarks/reports/firbench-1-simulation-v6-20261015.md` | v6 projection (failed numerical acceptance) | `e1e2e101488db662da69d23719ef3dbc192b3b1dcfca2bec59787ca82e9cbc14` |
| `docs/tasks/firdv/FIRBENCH-1-fir-benchmark-tool-task-plan.md` | task plan | `c643832c4185e4c346a9ab0712ed1283591222bf7196c0eeb507b1f4b380a0b1` |
| `docs/tasks/firdv/firbench-1/S9-acceptance.md` | S9 acceptance, pre-outcome clauses | `d796718c121bd0a16f1e88b2203ad2a3929efd82b1a5e29bf80c2d7da503931e` |
| `apps/prototype-description-service/scripts/eval_harness/firbench_selftest.py` | source anchors only (§10) | `d4a9f18d9baba4a75a3fa3e6822dc7121847ebaa22d063899262bb0c02901c67` |
| `apps/prototype-description-service/scripts/eval_harness/firbench_score.py` | source anchors only (§10) | `8c0dfd6f49d3c0d50edb296ba47f247b73aa04efae380258cf1368458af785de` |

Not tracked and not present in this checkout: the golden-150 candidate file, the inventory file, the operator-boxes file, and the operator-corrections file. The sidecar `build_notes` names all four with laptop-absolute paths, which are not reproduced here. They were looked up by name in the tracked tree and in the top level of the external context directory (subdirectories not searched). None was found. The lineage from golden-150 boxes back to these inputs is therefore not walkable in this checkout (GRPH-14, §8).

### 2.2 External read-only context (basenames; not tracked)

| Basename | Role | SHA-256 |
| --- | --- | --- |
| `full-mc-acceptance-receipt.json` | canonical receipt, 15 case hashes | `0362ff0f1c79ec47d13f65c00e8643cccc737305e06895329367a2769cfb393d` |
| `full-mc-review-context.json` | committed-producer review context | `da7251446d3a5b96b5623c48620593fa195304cd87f8337f2ccd9890dad58c27` |
| `resume-c-private-counts.json` | sanitized laptop count snapshot (counts only) | `f6a6af6db4166cbf3aacc314157e4ea0ebc86f33491e848e1a95ff910d4b18a7` |
| `margin-and-design-effect-before-the-run.md` | supplemental CARD-27 | `186c94c2b0ba88897cebea26c39752d6f0e87bbab8bff3ec1fa9aace79f85aad` |
| `canon-0.26.2/meta/release-manifest.json` | canon release (`heuristics-canon/release@5`, version `0.26.2`, date 2026-10-14, 1889 rules, 20 principles) | not hashed |
| `canon-0.26.2/lexicons/epistemics.md`, `ml-systems.md`, `graph-theory.md` | rule rows (locators in §9) | not hashed |

### 2.3 Availability observation (not qualification)

- The sanitized laptop snapshot reports 646 records: 591 personal and 55 editorial, 588 unique personal content, 231 known dependency components, largest component 79, 3 exact duplicate groups, `unresolved_sessions: true`, and `first_annotation_wave_unique: 263`. It states that it is "not an exhaustive frame or human QC."
- The inventory (§2 and §10 flag 6) records, as a dated laptop observation, 643 of 646 `sha256_source` matches, 0 mismatches, and 3 absent. The VM probes in §2 did not locate the corpus.
- Availability is not qualification. Image contents were not used.

## 3. Annotation-mode provenance (recorded, not upgraded)

| Label source (as recorded) | Where recorded | What it is | Upgrade to GT? |
| --- | --- | --- | --- |
| `workbench` named boxes | corpus v3r `named_boxes` (584 faces; sourced from the tracked `corpus646-interleave-manifest-20260716.json`); fir12 `face_boxes` (578 boxes, all named) | Operator workbench clusters | No. Named faces only. Not exhaustive. |
| `detector` boxes | golden-150 `face_boxes` (369); corpus v3r `detected_boxes` (1,763 across 605 entries) | YuNet detector geometry at score threshold 0.3 | **No.** Detector output is not GT, and no per-box verification record exists. |
| `operator` boxes | golden-150 `face_boxes` (6) | Manual operator boxes for detector misses | Historical operator marks. Not exhaustive. |
| `operator_hand` slice tags | corpus v3r `slice_tags_source` (150 entries) | Operator hand tags, a 150-entry subset | Historical operator tags. Not qualified for per-cell claims. |
| `slice_tags_derived` (profile) | corpus v3r `derived_tags` (255) | Shortlist from a calibrated threshold on detector geometry; the manifest says it is "a SHORTLIST, not ground truth" | No. |
| VLM captions and strata | golden-150 captions; fir12 `stratum` and `caption_tags` | VLM-derived | No. The fir12 `ground_truth_caveat` says so explicitly. |
| `roster_only` | Not found as a label in any inspected manifest (grep) | Identity roster membership appears as `present_identities` and roster entries | Not applicable. Nothing was upgraded. |

Golden-150 operator records (sidecar `media`, 150 of 150 entries carry an `operator` block): 47 notes; 9 identity annotations; confirmation kinds include `occlusion_sweep_confirmed` (31), `not_occlusion` (14), `nsfw_cleared` (7), `detector_miss` (5), and `stranger_only_verified` (1). The confirmation families are flag and stratum confirmations. They are not a per-face exhaustive checklist. Some notes describe face-level review on single images, and the sidecar's automated twin-eligibility checks are recorded in the same notes. Only the operator role is recorded as the annotator. The draft manifest's `annotator_id` value (`pre-program-operator`) appears in two nested places. No entry-level `annotator_id` or `annotation_batch` field is populated.

Reconciliation not closed in the record: the sidecar carries 8 `detector_miss` informational flags, 5 `detection`-family confirmations, and 6 operator-source boxes. The three numbers are not reconciled to one another.

## 4. Coverage and counts (dated observations)

| Artifact | Count | Notes |
| --- | --- | --- |
| Golden-150 draft entries | 150 | 145 with at least 1 face; 5 with `face_count` 0 |
| Golden-150 face boxes | 375 | 167 named + 208 unnamed = 375; 369 detector + 6 operator = 375 |
| Golden-150 sidecar `provenance_celeb` / `provenance_operator` | 7 / 137 | 144 stamped; 6 entries have no `provenance` block |
| Golden-150 selection `size` / realized | 150 | Gallery keys: 60; probe-only identities: 7 (external gallery) |
| fir12 entries | 640 | Of 646 manifest entries; 640 recovered at pinned SHA-256; 3 declared unrecoverable |
| fir12 `face_count` 0 | 115 | `face_count` equals the number of named boxes; absence of unnamed faces is not established |
| fir12 boxes | 578 | All named; `face_count` = `len(face_boxes)` for every entry |
| Corpus v3r entries | 646 | 591 personal + 55 celebs; 116 unlabeled (`unlabeled_*`) |
| Corpus v3r identities | 130 | 4 are secondary-only |
| Corpus v3r `named_face_count` total | 584 | |
| Corpus v3r `detected_face_count` total | 1,763 | Over 605 entries with detected faces |
| Corpus v3r `no_faces` flags | 38 | Status flag, not an absence proof |
| Exhaustive-marker grep (`exhaust`, case-insensitive) | 0 | In v3r, v3, and the golden-150 draft (inventory §4). The gate-contract `t14_exhaustive_subset_count` is null. |

Arithmetic checks (static, this lane): 167 + 208 = 375; 369 + 6 = 375; 591 + 55 = 646; 588 = 591 − 3 personal duplicates; 643 unique content = 646 − 3; 578 = 488×1 + 27×2 + 8×3 + 1×4 + 1×8 (fir12 face-count distribution); 640 = 115 + 488 + 27 + 8 + 1 + 1 (fir12 entries).

## 5. Duplicate and identity coverage

All corpus/selection counts in this section are dated report or gate observations (2026-10-15), not fresh manifest verification. The corpus manifests are intentionally unavailable in this minimal review bundle. Only aggregate counts, field names, paths and artifact hashes are reproduced.

- **Exact duplicates (dated report observation).** Corpus v3r records 3 duplicate groups, with 6 entries carrying `duplicate_of`; the earlier laptop snapshot also reports 3 groups. FIR-12 records the same three collapsed pairs, with 0, 1 and 2 faces respectively. No source IDs or retained/dropped mappings are reproduced, and neither manifests nor image bytes were rechecked here.
- **Golden-150 and FIR-12 internal (dated report observation).** Neither selection records duplicate SHA-256 values internally. That says nothing about cross-selection source independence.
- **Cross-selection overlap — FB1-GT-GATE-03 sustained as a documentary correction.** The dated gate's join on `/entries/*/media_id` reports **150 distinct golden entries sharing recorded source IDs with FIR-12**, not merely 64 overlapping entries. For those 150 sources, **64 golden mirror hashes equal the FIR-12 original hashes; 86 differ** (64 + 86 = 150). The corpus v3r metadata maps all 150 golden hashes to `sha256` (downscaled mirror) and all 150 corresponding FIR-12 hashes to `sha256_source` (original). The sidecar declares the mirror to be max-1280. Thus the 64 equal representation hashes are a subset of the 150-source overlap; the other 86 are shared sources represented in different declared hash spaces. No unexplained hash-space coincidence remains in the recorded metadata.
- **Disconfirmation against the named v3 producer.** The same dated gate reports that the actual v3 manifest named by the golden selection matches all 150 golden mirror hashes and all 640 FIR-12 original hashes by recorded source ID. The overlap conclusion does not require substituting v3r for v3. This is attribution to the gate, not a join rerun here.
- **Independence limit.** The 150 shared source entries and common workbench lineage preclude treating these selections as independent samples. Metadata reconciliation does not verify actual image bytes, capture occasions, annotator independence, or an exhaustive human audit. The earlier §8 item 8 request for hash-space reconciliation is resolved at the dated metadata level by the gate evidence below; any image-byte or capture-independence verification remains unperformed. [GRPH-14] Record provenance as a walkable lineage graph (Building Knowledge Graphs, ch. 8 + Mental Models, ch. 8); [EXP-23] Pseudoreplication check (Statistics Done Wrong, ch. 3).
- **Identities and unlabeled entries (dated report observations).** Corpus v3r records 130 identities, including 4 secondary-only; the golden roster records 54 items and its selection 60 gallery and 7 probe-only identities. The 116 unresolved corpus entries are not verified nonmated GT. No person-level deduplication or independence analysis was performed here.

Original producer pins for the dated gate's membership/hash-space reconciliation (SHA-256; these missing files were **not** rehashed):

| Producer path | Fields / recorded evidence | Original SHA-256 |
| --- | --- | --- |
| `benchmarks/manifests/golden150-draft-20260723.json` | `/entries`: 150 distinct source IDs, mirror `sha256` | `0dc89a1d0378630522a16080a176c1533357419fcfbe704a7c2bfc487580ac54` |
| `benchmarks/manifests/fir12-selection-v1.json` | `/entries`: all 150 source IDs present; 64 equal and 86 differing `sha256` values | `26738d63d88fec632981f7229803898ba34a9356d8232ed5c6301d27293aa49f` |
| `benchmarks/manifests/corpus-manifest-v3r-20260814.json` | `/sha256_space`, `/sha256_source_space`, `/entries`: mirror/original mapping for the 150 sources | `2d9d5ba3e04bcfa7ea29f960b2fdc05431bdae7993bd22042a5369ceee7d9bff` |
| `benchmarks/manifests/golden150-draft-20260723.sidecar.json` | `/build_notes/sha256_provenance`: downscaled max-1280 mirror | `2f3e04ffcdb5ff1b0ed9bdceefd001dac818304daf2bc34d19c9c189263421a3` |
| `benchmarks/manifests/corpus-manifest-v3.json` | `/sha256_space`, `/sha256_source_space`, `/entries`: 150 golden mirror and 640 FIR-12 original matches | `154eb2b735f947e5ce670886bb848fc2749aad5e952a448a4f1b75f3125abe7e` |

Attribution chain: this correction → `benchmarks/review-context/resume-c-gt-gate.json`, finding `FB1-GT-GATE-03` (gate SHA-256 `0fb0772c77d3102cc324b5779c0959521d4a7aeaa6c7d70b37e4dab2a7ace83a`) → the original producer pins above. The gate file's bytes were verified here; its historical manifest joins were not independently repeated. **Independent exhaustive GT remains NOT QUALIFIED.**

## 6. Field-by-field eligibility for the current qualified frame

**Second-dispatch scope (2026-10-15):** no frame is qualified. The corpus counts and searches in this table and the unchanged sections are dated author/gate attributions, not current corpus verification. The current checkout is an allowlisted orphan review bundle with no parent history; it is not the original full tree. [Safe source map](../review-context/safe-source-map.json) records original per-file pins under source `870710fd073d9c0937e01e25e69921a3fcc95e59`. Current reads verified the unchanged task-plan, S7, QC-report, occasion-report, `fir_occ_labels.py` and `firbench_runtime.py` bytes against those pins. Excluded corpus manifests and real records were not read or reverified; original commit continuity is unverified. Only §§6 and 8 are corrected here; earlier inspection/check statements elsewhere remain historical attributions.

Verdicts: **Not eligible** (fails a qualification requirement); **Not established** (no record either way in the inspected scope); **Historical only** (reusable as a dated record with its stated scope, not as qualified GT).

| # | Field | Artifact(s) | Annotation mode | Independent exhaustive audit covers it? | Verdict for qualified frame | Reusable historically |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Frame membership, golden-150 | golden-150 draft, selection | Curated quotas | No | **Not eligible** as an exhaustive frame. Selection names corpus v3, not v3r (inventory §10 flag 7). | Yes: the 150-entry curated set and its quotas |
| 2 | Frame membership, corpus | corpus v3r (646), catalog | Spine: image tree | Spine only; no per-image audit record | **Not eligible** as a qualified frame. Spine presence is not an audit. | Yes: the 646-entry inventory and its counts |
| 3 | Face box geometry, golden-150 (375) | golden-150 draft, sidecar | 369 detector + 6 operator | No: no per-box verification; detector-bound | **Not eligible** | 6 operator boxes as operator marks |
| 4 | Face box geometry, corpus detected (1,763) | corpus v3r `detected_boxes` | YuNet detector | No | **Not eligible** (detector output) | Detector candidate pool only |
| 5 | Named identity per named box (167 golden; 584 corpus; 578 fir12) | three artifacts | Workbench / operator names | Partially; single operator role; no second reader | **Historical only**: dated operator labels, not independently verified | Yes, with lineage note (shared source) |
| 6 | Unnamed / stranger faces (208 golden) | golden-150 sidecar and draft | Detector box, no name | No per-box verification | **Not established** | None |
| 7 | Missed faces (detector miss) | sidecar flags (8), confirmations (5), operator boxes (6) | Operator notes | No exhaustive sweep recorded; counts unreconciled | **Not eligible** | Operator-added boxes for the reconciled subset |
| 8 | Zero-face images (5 golden; 115 fir12; 38 corpus `no_faces`) | three artifacts | Status / `face_count` 0 | fir12 `face_count` 0 means no named box, not no face | **Not eligible** as absence evidence | Status flag |
| 9 | Unlabeled identity (116 corpus) | corpus v3r | Unassigned | No | **Not established**; cannot enter a nonmated pool | Count only |
| 10 | Slice / stratum tags | golden-150 operator tags (150); fir12 strata (VLM); corpus derived profile (255) | Operator hand / VLM / shortlist | Operator tags: no second reader | Operator tags **Historical only**; fir12 strata and derived profile **Not eligible** as GT | Operator tags, per-image |
| 11 | Captions | golden-150 captions; fir12 caption tags | VLM | Not GT | **Not eligible** | Not applicable |
| 12 | Duplicate accounting | corpus v3r, fir12, laptop snapshot | Hash | Not an audit | **Historical only**: 3 exact groups accounted | Yes |
| 13 | Annotator identity and independence | golden-150 draft and sidecar | Single operator role | No second reader; no inter-rater record | **Not established** | None |
| 14 | QC of label production | Real S7 queue, independent gold, export and acceptance/repair closure not supplied here | Independent-gold and blind-repeat qualification under frozen project policy (§8 items 1–2) | QC alone does not establish exhaustive coverage | **HOLD_QC**: measured support/outcomes and qualified acceptance missing; see [QC component §§4–7](./firbench-1-qc-observation-qualification-20261015.md#4-field-requirements-matrix) | None; declared floors are policy, not results |
| 15 | Capture-occasion / PSU independence | corpus v3r (no session IDs); inventory §4 | Components by identity and duplicate edges | Not established | **Not established**: 231 components; largest 79 | Component counts (inventory §4; laptop snapshot) |
| 16 | Consent and publication, personal | corpus v3r `consent` | Operator-held consent, off-repo | Not reviewed in this lane | **Not verified** in scope (no publication claim) | None |
| 17 | Licence and publication, celebs | corpus v3r `consent`; golden-150 `provenance` | Editorial fixture; not consented | Not applicable | **Not eligible** for publication; the sidecar lists `publishable` as unset (fail-closed) | Research-only use as recorded |
| 18 | Image availability | catalog; inventory §2; laptop snapshot | — | Not GT | Availability only: VM not found in probed paths; laptop 643/646 (dated) | Availability note |
| 19 | Lineage walk, golden-150 box → operator inputs | sidecar `build_notes` | — | — | **Not walkable** in this checkout (§2.1) | — |
| 20 | Detector parameters | corpus v3r `detector` (YuNet, threshold 0.3, NMS 0.3, top-k 5000) | — | — | Recorded; detector recall below threshold is not measured here | Recorded parameters |
| 21 | Actual human observation of measurement production | Applicable private `fir-occ-observation/v1` record not supplied | Bounded human observation, not generated narrative (§8 item 9) | Does not establish exhaustiveness by itself | **HOLD_OBSERVATION**: recording absence documents this hold only; see [QC component R12–R15](./firbench-1-qc-observation-qualification-20261015.md#4-field-requirements-matrix) | None |
| 22 | AE-5 real canary | Declaration, private roster/gallery binding and measured effects not supplied | Real diagnostic canary | GT report cannot qualify it | **HOLD_AE5**; [occasion component §6](./firbench-1-occasion-preflight-20261015.md#6-real-ae-5--ae-6--ae-12-preflight-matrix), §8 handoff below | Historical roster count only |
| 23 | AE-6 legacy replay / changed-item v2 evidence | Raw per-probe provenance and replay receipts not supplied | Real replay with pinned source/model/gallery/template lineage | GT or availability counts cannot establish parity | **HOLD_AE6**; [occasion component §7](./firbench-1-occasion-preflight-20261015.md#7-historical-real-parity-candidates-ae-6), §8 handoff below | Attributed 204/207 report value only |
| 24 | AE-12 source/template, identity, ledger, timing, budget and admission bindings | Real diagnostic receipts and qualifying rerun not supplied; original decision manifest unavailable in this bundle | Real 20-image three-leg diagnostic, followed by preregistered warm-budget rerun | GT report cannot qualify it | **HOLD_AE12** and **HOLD_ADMISSION**; [occasion component §§8–9](./firbench-1-occasion-preflight-20261015.md#8-tracer-identity-and-budget-approvals), §8 handoff below | None |

`HOLD_*` labels are typed documentary handoff states proposed in this report, not implemented API enums or new exception strings. Missing or mismatched evidence leaves the corresponding real use held. The QC component owns QC/observation details; the occasion component owns occasion and AE-5/6/12 preflight details. A downstream real-preflight join must consume both components' actual evidence and bound receipts (§8), rather than infer readiness from this GT table. These holds do not block independent synthetic method work.

## 7. Reusable historical evidence versus current qualified frame

- **Reusable as historical evidence (with the stated scope):** the dated counts in §4; the 150-entry operator tags and operator-marked boxes for those entries; the named-identity labels as dated operator labels; the three exact duplicate groups; the inventory's negative findings (§6 rows 1–20).
- **Not the current qualified frame:** no candidate frame. The three candidates (golden-150, fir12, corpus v3r) share one workbench lineage (corpus646-interleave, tracked). Their GT is not independent of each other.
- **Not a substitute for qualification:** software checks (146 S9, 69 catalog, 197 report, as recorded by the v6 record) and the synthetic reader result (6/6) do not establish real GT, QC, or AE-12 evidence (v6 §8–§9).
- **v6 gates unchanged:** the v6 failures (H2 boundary 126/2000 = .063 > .060; clear_mask cell 1113/2000 = .5565 < .77) stand. The global power .837 does not prove cell power. Independent 116/2000 = .058 cannot replace the failed row.

## 8. Missing factual artifacts and actions (bounded)

These are requirements for a later authorized real preflight, not evidence produced by this correction. An absence entry documents a hold; it never satisfies the missing requirement. No human labeling, observation, real-data eval, inference or Monte Carlo is performed here. Full component contracts remain in the linked QC and occasion reports; this section supplies the GT-facing handoff.

1. **Independent exhaustive audit, separate from tier-a QC:** audit every image and every face (including unnamed, partial, profile, occluded and tiny faces), with a missed-face sweep independent of detector output. Record reviewer role, date, protocol and second-reader scope/results. Require separate exhaustive tier-b verification and source admission before an exhaustive-frame claim. A qualified tier-a annotation remains non-exhaustive; gold accuracy, repeat agreement and observation never upgrade it.
2. **Frozen protocol and qualified S7 QC closure (`HOLD_QC`):** define face/minimum-size rules, partial/profile/occluded and unresolved-identity treatment, instructions, rubric/rule version, disagreement rule, run scope and support policy before answers/outcomes. Supply the real queue, independently SME-authored non-caption gold (random, batch-matched and hard items), blind repeats, export, acceptance/adjudication and any repair/validation records, linked by hashes to that declaration and candidate. Preserve original exports, pre-adjudication decisions, failures, undefined metrics and QC results immutably. A correction is a separately versioned candidate linked to its prior export; it requires fresh independently authored/blinded validation or qualified SME resolution under the existing S7 contract, never recycled support or worker deletion to improve agreement.

   **Existing project policy, not canon defaults, guarantees or measured results:** `gold_share = 0.10`, `repeat_fraction = 0.10`; per-field repeat agreement ≥ 0.90 and defined Cohen kappa ≥ 0.80; per-annotator independent-gold accuracy ≥ 0.90; ≥ 20 gold decisions per annotator and ≥ 20 repeat decisions per evaluated field across the declared run. Report each annotator/field's support, measured outcomes and disposition. `support_not_accrued` is neither pass nor fail and refuses import; undefined kappa stays null with `kappa_undefined` and requires qualified SME disposition, never conversion to a passing number or a support waiver. Below-floor, uncertain and eval-critical cases follow S7 repair/SME routing. Agreement alone is not truth ([HITL-03], [HITL-05]). Evidence: [task-plan Label QC, lines 97–109](../../docs/tasks/firdv/FIRBENCH-1-fir-benchmark-tool-task-plan.md), [S7 Build 1–4](../../docs/tasks/firdv/firbench-1/S7-label-queue.md#build), and [QC component §§4–7](./firbench-1-qc-observation-qualification-20261015.md#4-field-requirements-matrix). The importer validates supplied `queue.qc`, not equality to these project floors; pre-data policy review and hash binding remain necessary.
3. **Per-box verification:** for any proposed GT pool, verify/reject candidate boxes and record missed faces. The earlier report attributes 375 golden-150 boxes and detector-only corpus candidates; those counts are not newly verified here and are not a reason to omit unrepresented faces.
4. **Detector-miss reconciliation:** resolve the attributed 8 flags, 5 detection confirmations and 6 operator boxes without changing their historical record.
5. **Occasion/PSU provenance:** supply and independently check capture-occasion/session and duplicate/sibling records. The attributed 231 identity-connectivity components are not a verified occasion partition. Declare independent units, deff/ICC and n_eff separately for mated queries and non-mated source units; QC decision support and image availability are not independent-unit evidence ([AUDIT-11], [EXP-23]). See [occasion component §§2–5](./firbench-1-occasion-preflight-20261015.md#2-metadata-inventory-what-exists-for-capture-occasions).
6. **Frame decision:** resolve the attributed corpus-v3/v3r selection mismatch; bind the governing source and exhaustive audit by hash.
7. **Lineage:** privately pin the four attributed build inputs (candidates, inventory, operator boxes, operator corrections), or retain the explicit missing status. A filename or report citation does not close the source-to-producer walk ([GRPH-14], [PROV-01]).
8. **Hash-space reconciliation:** resolve the attributed 64 shared SHA-256 values, including original versus downscaled hash spaces; no current comparison is claimed.
9. **Actual bounded human observation (`HOLD_OBSERVATION`):** a person must observe a sampled production/adjudication process in context and ask operators how values, exceptions and outliers arise ([MEAS-29]). Keep observer/date, sampled production scope and method, operator accounts, exceptions, limits (what the sample does and does not establish), observed context and applicability to the current candidate/queue/run. Compare rule, instructions, operators, collection workflow, adjudication workflow and tool behavior; uncertain or materially out-of-scope reuse requires new observation. Record authenticity and applicability review privately. An absence entry, model-authored account, matching version, schema-valid file or reference string is not the actual observation required before real tier-a analysis. The [QC component R12–R15 and C4](./firbench-1-qc-observation-qualification-20261015.md#6-minimal-missing-record-contract-proposal) owns acquisition details.
10. **Publication records:** retain required consent/licence review before any publication claim; this correction publishes no images or identity records.
11. **Private local corpus check:** a later authorized operator checks originals and catalog binding on the laptop. Availability receipts remain distinct from exhaustive GT, QC and observation qualification. No private source or alias material is inspected here.
12. **Sidecar decision:** resolve the historically open box-source mapping (iptc or mwg) against privately held inputs.

### Component handoff and bounded real-preflight holds

**FB1-GT-GATE-02: sustained.** The old agreement-only request omitted the existing independent-gold/repeat acceptance policy, and its absence wording did not distinguish a documentary hold from actual observation. Items 1–2 and 9 repair that handoff without claiming records exist.

**FB1-GT-GATE-04: sustained for missing handoff; scope limited by component ownership.** The original GT register omitted the AE obligations. The stronger interpretation that this report must duplicate or qualify every component is unsupported: [occasion §6](./firbench-1-occasion-preflight-20261015.md#6-real-ae-5--ae-6--ae-12-preflight-matrix) already defines AE-5/6/12, §§7–9 specify parity/binding/budget inputs, and [QC §§4–7](./firbench-1-qc-observation-qualification-20261015.md#4-field-requirements-matrix) owns QC/observation. Those are contracts and dated findings, not supplied real evidence. A later downstream join owns full combined real-preflight acceptance, consuming actual bound artifacts rather than document readiness claims ([GRPH-32]).

| Typed real hold | Component producer/owner and required handoff | Available evidence and limit |
| --- | --- | --- |
| `HOLD_AE5` | Occasion/canary producer: privately bind the Golden-150 diagnostic frame and 54-entry draft roster/gallery; declare the five-identity AuraFace canary set, seed and derangement before outcomes. Supply measured FNIR/false-name effects and paired CI. Canary legs remain diagnostic and are refused in sealed runs. | Task-plan AE-5, line 451, and occasion §6 specify this; actual declaration, bindings and measured run receipt are missing here. No roster entries are exported. |
| `HOLD_AE6` | Legacy replay producer: raw historical per-probe source for the 207 probes, code/model/preprocessing and gallery/template pins, exact `legacy_v1` replay counts and itemwise `v2` changes. | Task-plan AE-6, line 452, and occasion §7 attribute 204/207 to historical reports. That scalar and its duplicate report are not current replay evidence; raw provenance/replay and changed-item receipts are missing here. |
| `HOLD_AE12` | Occasion/runtime producer and downstream S3 join: approve and privately bind the 20-image diagnostic selection/identity scope, all three legs, `query_source` → `frame.source_sha256`, `gallery_templates` → `gallery_lineage.templates_sha256`, `query_images`, and enrollment/fold/gallery membership. Retain template/media/image bindings privately. Supply every-GT-face exactly-one-state ledger check, actual cold/warm `timings.json` receipts, then the warm budget preregistered from the diagnostic measurement before W5 budgets and a passing warm rerun. | Task-plan AE-12, line 458, and occasion §§6, 8–9 define this; real source/template/identity, ledger, timings, approved budget and rerun receipts are missing here. Fixtures and availability counts supply none of them. |
| `HOLD_ADMISSION` | Downstream real-preflight join: requalify the private S7 closure, check actual observation applicability, independent exhaustive source, occasion/PSU and runtime bindings, and applicable decision ratification/seal/admission state. Record a bound aggregate receipt per requirement; refuse missing/mismatched inputs. Diagnostic canary permission is not sealed confirmatory admission. | Gate 04 attributes null source/template/exhaustive, G4 p95, ratification and seal fields to original `fir-bench-decision-v1.json` (reported SHA-256 `7b89a3504d23b82c2a33e6fda1d52df2d181ec7d6bbfc9a5a24995c5f5ca5e2e`). That manifest is unavailable in this bundle; its bytes/nulls are not currently verified. No replacement real admission/seal receipt is supplied. |

Current software evidence is bounded static validation of the exact pinned readers: `fir_occ_labels.py:685–761,1050–1145,1181–1250,1356–1392` computes QC, checks acceptance/repair and observation bindings, and refuses synthetic rows for real analysis. `_require_observation` explicitly cannot prove human attestations. `firbench_runtime.py:150–177,281–315` consumes `label_evidence` with `export_path`, `queue_path`, `gold_path`, requalifies before conversion and checks source/template hashes and exhaustive admission; tier-a golden rows must use the qualified population-source route. These readers validate records and bindings; they do not establish that gold is correct, a person observed production, or a frame is actually exhaustive. No readers or tests were executed in this correction. The reported 166 software tests and synthetic reader 6/6 establish no real human GT/QC/observation, capture, budget or seal evidence.

**Privacy and sequence:** raw decisions, roster/gallery identities (including pseudonyms), aliases, mappings, observation accounts and row-level records remain private local evidence on the operator’s laptop. Portable reports contain only aggregate counts, artifact hashes and aggregate qualification/hold receipts; private read-closure bundles stay private. The report-level join above is a requirement, not a new implemented schema. Least privilege ([SEC-04], instruction scope; lexicon body unavailable in the partial mirror) limits this correction to allowlisted prose/code/schema. Freeze each experiment's method, selection, margins, harm directions, α allocation and acceptance gates before its outcomes ([EXP-12], [EXP-22], CARD-27); adopt a prospective method only after its gates pass, never calibrate then retroactively freeze that experiment. CARD-27 selects no interval formula or project thresholds. Real-preflight holds do not create dependencies for independent synthetic method work. All previous failed trials remain failed, including v6 H2 .063 > .060 and clear_mask .5565 < .77; seeds and receipts are unchanged, and this prose confers no numerical acceptance.

## 9. Canon rules applied (release 0.26.2; mirror read-only)

Each row cites the stable ID and its locator in the pinned mirror. The rows are applied as stated; no numeric default is asserted from canon.

| Rule | Locator | Applied to |
| --- | --- | --- |
| EXP-09 | `lexicons/epistemics.md:326` | Fixed analysis timing; no selection after seeing labels |
| EXP-12 | `lexicons/epistemics.md:329` | Power and practical significance must be pre-declared; no power claim is made here |
| EXP-13 | `lexicons/epistemics.md:330` | No null calibration (A/A) for the GT pipeline was found; none is claimed |
| EXP-19 | `lexicons/epistemics.md:336` | Not applied: this lane makes no paired contrast |
| EXP-22 | `lexicons/epistemics.md:339` | The golden-150 GT box set is conditioned on detector output. If detection is the measured response, the selection and the confirmation must be split |
| EXP-23 | `lexicons/epistemics.md:340` | N must be the independent unit; repeated faces and frames within sessions are not i.i.d. |
| MEAS-29 | `lexicons/epistemics.md:294` | No human contextual observation of label production was found (§8 item 9) |
| AUDIT-07 | `lexicons/ml-systems.md:327` | A rate claim over "all images" requires a named sampling frame and coverage inventory |
| AUDIT-11 | `lexicons/ml-systems.md:331` | Cluster design effect; n_eff = n/deff. deff is not computed here |
| EVAL-19 | `lexicons/ml-systems.md:274` | Do not normalise false positives by the non-mated search proportion when detector false alarms can add searches |
| GRPH-14 | `lexicons/graph-theory.md:117` | Walkable lineage from artifact to inputs; broken at the untracked inputs (§2.1) |
| PROV-01 | `lexicons/ml-systems.md:446` | Every derived output names its inputs (cross-reference for GRPH-14) |
| CARD-27 (supplement) | `canon-supplement/margin-and-design-effect-before-the-run.md` | Pre-run seal of margin, method class, harm direction, α split, and n_eff before any outcome. It does not select an interval formula or prescribe project numbers. |

## 10. Structural code admission and prior-art limits

**FB1-GT-GATE-01 sustained.** The earlier inference that no code admission gate exists was unsupported and is withdrawn. The §4 zero-marker result is only a dated case-insensitive search for `exhaust` in the v3r, v3 and golden draft input manifests. It cannot establish absence of checks in code, and was not rerun on those intentionally unavailable manifests here.

The following bounded code paths were read in the current allowlisted bundle. Their exact bytes match the original per-file pins in `benchmarks/review-context/safe-source-map.json` and the gate evidence. All paths below are relative to `apps/prototype-description-service/scripts/eval_harness/`.

| Code anchor | Structural check actually read | Verified original/current SHA-256 |
| --- | --- | --- |
| `firbench_score.py:844-856`, `decide` | Calls `fc.require_verdict_allowed(manifest, frame=frame)`; handles `UnratifiedDecisionError` as unratified. The exhaustive-frame refusal is a separate contract error. | `8c0dfd6f49d3c0d50edb296ba47f247b73aa04efae380258cf1368458af785de` |
| `firbench_contract.py:948-968`, `require_verdict_allowed` | Checks ratification, seal/hash, unresolved sealable fields and equality to the sealed frame registry; refuses `frame.exhaustive is not True`. | `346846e2456f44005a50a397a5217e1488821b2093c4cc3d249edd9d796a134a` |
| `firbench_score_io.py:110-117`, `_inventory` | Validates frame interchange; compares persisted admissibility, seal state, source hash and exhaustiveness to the decision; refuses `spec.exhaustive is not True`. | `ca45c0bce0edf4b3571e3f27a55dfa78b6ae434d02d95ad64ec1ebcfa157b2bf` |
| `firbench_runtime.py:150-177,281-315`, `_qualified_source` / `_prepare_run` | Requires exhaustive frame and source/template hash bindings; golden inputs need document-level `annotation_mode == "exhaustive"`. Real tier-a population rows require linked S7 `export_path`/`queue_path`/`gold_path`, conversion/requalification calls and matching annotation/source fields; tier-a golden rows are refused in favor of that population evidence route. | `116785c13e5e8070cf0693650ea01b327241064dd4940b5b90975a2374db39e1` |

These are structural admission checks, not proof that the human acts attested by input fields occurred. The runtime passes named evidence fields to S7 readers; no real evidence bundle was opened or executed here. A true `exhaustive` scalar, a valid schema or a matching hash cannot independently establish a detector-independent, exhaustive human audit, real QC, contextual observation or capture-occasion independence. **Independent exhaustive GT remains NOT QUALIFIED.** The distinction preserves lineage [GRPH-14] Record provenance as a walkable lineage graph (Building Knowledge Graphs, ch. 8 + Mental Models, ch. 8) and names actual data movement [GRPH-32] An edge exists only where data moves (bootstrap); it does not invent a human-evidence producer behind a software check. [MEAS-29] Observe measurement production (Seeing with Fresh Eyes: Meaning, Space, Data, Truth, ch. 4) remains an unfulfilled real-evidence requirement.

- **Prior-art packet (dated context only):** FIR-12 findings 9862/9784/9786 on GT-name normalisation/missed mates; MAINT-FIR-DETECTION decision 12793; FIR-8 paired contrast; FIR-13 finding 13997 on mixed-empty resamples; and the supplied gte-base-en-v1.5/reinjection context. None was retrieved or qualified as new GT evidence here. The earlier S9 line-244 attribution and inventory §5 arithmetic characterization remain dated report context, not freshly verified assertions in this dispatch.
- **Prospective experiment boundary:** freeze the experiment before outcomes; adopt only after gates pass. No calibration-to-freeze cycle or outcome-based selection is authorized by this correction. [EXP-12] Power and practical significance (Trustworthy Online Controlled Experiments, ch. 2); [EXP-22] No circular analysis (Statistics Done Wrong, ch. 6); CARD-27. The card does not choose an interval formula or project gates. No H2 method proposal is implemented by this document.
- **Failed trials unchanged:** original v6 H2 126/2000 = .063 > .060 and clear_mask cell 1113/2000 = .5565 < .77 remain **FAILED**, with their seeds and receipts unchanged. Neither 166 software tests nor synthetic reader 6/6 supplies real human GT, QC, observation, capture, budget or seal evidence. No numerical acceptance follows from this prose. Shared-source counts cannot become independent N or a measured n_eff/deff [EXP-23] Pseudoreplication check (Statistics Done Wrong, ch. 3); [AUDIT-11] Account for cluster design effect (Sampling: Design and Analysis, ch. 5).

## 11. Static checks run in this lane

This section records only checks performed in this second dispatch (2026-10-15); it replaces the earlier blanket claim that every §2 input was rehashed. §2's historical checkout, corpus and external-input observations are not current verification of the minimal bundle.

- Read the subject report, the safe source map and the supplied GT gate. Inspected only the four known code paths/ranges in §10 for admission behavior. No codemap tool is available in this dispatch; the supplied exact-production-search result of 0 and scripts/docs/benchmarks coverage gap are context, not absence evidence. Bounded known-path reads were justified by the gate's exact anchors.
- Ran `sha256sum` on the four §10 code files, `safe-source-map.json` (`c47d154dd30da476830c2685de507b4d15ff2945a7cdbc8a77091c5c9b07b021`) and `resume-c-gt-gate.json` (pin in §5). Compared all four code digests and the gate digest to the source map's original per-file pins; all matched. The starting report bytes also matched its original pin `aaa8b6095c6ee70652b7a352cabed45b7b3bd56925af50bd79958a82af0c17e1`.
- Distinguished provenance: this dispatch began at local orphan commit `3d10689b17102d98e08dc18d57cfdc03ebe7b136`. User-supplied SOURCE `685c0757d425cf6c3649a6258705908106d98df6`, source-map `source_commit` `870710fd073d9c0937e01e25e69921a3fcc95e59` / `source_tree` `e24f827b1a818c821bfbdd776c02dd82ecd1786c`, and the gate's historical `source_tree` `13af3443ec6d4a08a15d7eed9991354d809207a6` are provenance labels, not verified local ancestors or claims of current full-tree equality. No parent history was consulted.
- Read the triggered EXP-12/22/23, AUDIT-11, MEAS-29 and GRPH-14/32 rows and relevant principles in the read-only canon 0.26.2 mirror, plus full CARD-27 supplement. Rehashed the three lexicons, `PRINCIPLES.md` and supplement and compared them with `meta/release-manifest.json`; all five matched. The release-manifest SHA-256 is `46636aa71f2e2e0c413b6ccff1cae4959543026c6ee7e4abde2bc7f30645a260`. The mirror is partial: the security lexicon and release-listed measurement-integrity/least-privilege cards are absent, so their full text was not verified. Least-privilege scope follows the explicit user constraint and available principle; no missing canon text is invented.
- Checked only the new overlap arithmetic (64 + 86 = 150), code anchors against the read ranges, section ownership by byte comparison, and `git diff --check` before staging/commit. No broader revalidation of §4/§6 arithmetic is claimed.

No corpus manifests, images, private identities/maps, legacy repositories or foreign processes were read. No missing file was rehashed; no manifest join, real inference, Monte Carlo, human labeling, QC, observation, capture check or budget/seal validation was performed. No product, test or fixture changed; no tests were added or run. Missing real evidence remains a qualification hold, not a blocker to this bounded document correction.

## 12. Lane outcome

- **Qualified frame:** none.
- **Reusable historical evidence:** §4, §3 (operator-tag and named-label scope), §5, §6 rows marked Historical only.
- **Blocked on:** the records listed in §8. They are factual artifacts that do not exist in the inspected scope.
- **Not done here:** no pixel inspection, no human labeling, no observation, no QC, no outcome run, no tuning, no push, no merge.
