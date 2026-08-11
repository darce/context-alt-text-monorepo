# Face Bake-off Eval Report

- schema: `acx-eval/v1` kind: `report` report_kind: `face_bakeoff`
- model_ids: `synthetic-face-anchor` embedding_dims: `[8]` leg: `candidate`
- head_sha: `0000000000000000000000000000000000000000`
- score manifest_sha256: `e7004f3b2355d8c46943acffa3d3ea8c85c068985494962d0c48c5d12e8ccc0e`
- canon_version: `0.11.0` protocol_id: `fir-5-face-bakeoff-v0.11.0`
- zero_box_corpus: False total_gt_boxes: 3
- images: 3/3 scored, 0 failed; matched_faces=3

## Detection

- precision: 1.000 recall: 1.000 (tp=3 fp=0 fn=0)

## Floor-gated slices

- **headline_identification**: status=`UNDER-FLOOR / DIRECTIONAL — awaiting operator demotion` directional=True precision=1.000 (2/2) recall=1.000 (2/2) n_recall_eligible=2/100 frame=`celebs01_named_matched_probes (provenance.source==CELEB); named_matched_probes_pooled_kfold_decisions: precision over accept/confusion; recall over enrolled (≥2 matched faces) only; detection misses excluded from FN (EVAL-16); error-item media excluded from scoring (listed in failures)`
- **unknown_rejection**: status=`UNDER-FLOOR / DIRECTIONAL — awaiting operator demotion` directional=True rate=1.000 (1/1) n=1/43 frame=`stranger_probes_full_corpus_including_unpublishable: correct_reject=decision=reject; false_accept=decision=accept`
- **clustering**: status=`UNDER-FLOOR / DIRECTIONAL — awaiting operator demotion` directional=True purity=1.000 false_merge=0.000 false_split=0.000 P_same=1 P_diff=0 M=1 frame=`named_matched_faces_pairwise: P_same/P_diff pair floors; M==0 all-singletons guard; single-linkage diagnostic (GRPH-18)`

### Occlusion recovery

- **occlusion.masked**: status=`UNDER-FLOOR / DIRECTIONAL — awaiting operator demotion` directional=True accuracy=null (0/0) n_eligible=0/90
- **occlusion.occlusion_other**: status=`UNDER-FLOOR / DIRECTIONAL — awaiting operator demotion` directional=True accuracy=null (0/0) n_eligible=0/90
- **occlusion.sunglasses**: status=`UNDER-FLOOR / DIRECTIONAL — awaiting operator demotion` directional=True accuracy=null (0/0) n_eligible=0/90

## Gate proposal (excludes DIRECTIONAL)

- role: proposal_only
- release_surface: `proposal_only_not_release`
- canon_version: `0.11.0`
- proposed_slices: []
- excluded_directional: ['clustering', 'headline_identification', 'occlusion.masked', 'occlusion.occlusion_other', 'occlusion.sunglasses', 'unknown_rejection']
- id-recall: 1.000 alongside detection-recall: 1.000 (coupling_flag=False, missed_gt=0, unmatched_det=0) — identification recall is computed only over faces this leg detected and §C-matched (enrolled); weak detection can inflate id-recall on the easy detected subset — report id-recall ALONGSIDE detection-recall
- p95 scan latency: FIR-6-owned; not measured here.
- scope amendments (operator ack required):
  - A10 eval throughput deferred to named follow-up FIR-5a (NOT FIR-7 prod GPU)
  - clustering local floor P_same≥20 ∧ P_diff≥20 and M==0 all-singletons guard
  - p95 full-scan latency deferred to FIR-6 (not measured in FIR-5)
  - synthetic↔real divergence uses Wilson half-width rule (replaces scope >1/3)

## Failures

- none
