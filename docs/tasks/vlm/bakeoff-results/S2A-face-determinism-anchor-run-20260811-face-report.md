# Face Bake-off Eval Report

- schema: `acx-eval/v1` kind: `report` report_kind: `face_bakeoff`
- model_ids: `synthetic-face-anchor` embedding_dims: `[8]` leg: `candidate`
- head_sha: `null`
- fetch manifest_sha256: `19861fede2ec99bc0a7ed8777bca25829bce0fdd65e948e8c0080407e84c18e4`
- score manifest_sha256: `19861fede2ec99bc0a7ed8777bca25829bce0fdd65e948e8c0080407e84c18e4` (matches fetch: True)
- canon_version: `0.11.0` protocol_id: `fir-5-face-bakeoff-v0.11.0`
- zero_box_corpus: False total_gt_boxes: 7
- images: 8/8 scored, 0 failed; matched_faces=6

## Detection

- precision: 0.857 recall: 0.857 (tp=6 fp=1 fn=1)

## Floor-gated slices

- **headline_identification**: status=`UNDER-FLOOR / DIRECTIONAL — awaiting operator demotion` directional=True precision=0.800 (4/5) recall=0.667 (4/6) n_recall_eligible=5/100 frame=`celebs01_named_matched_probes (provenance.source==CELEB); named_matched_probes_pooled_kfold_decisions_plus_missed_gt: precision over accept/confusion; recall denominator = TP + decision-FN + missed_gt (EVAL-16: detector-missed named GT is an identification FN); unmatched_detections disclosed via detection_recall_coupling_flag; error-item media excluded from scoring (listed in failures)`
- **unknown_rejection**: status=`UNDER-FLOOR / DIRECTIONAL — awaiting operator demotion` directional=True rate=1.000 (1/1) n=1/43 frame=`stranger_probes_matched_plus_missed_gt: correct_reject=decision=reject; false_accept=decision=accept; missed_stranger_gt counted as failure in denominator (EVAL-16 / AUDIT-07); caller must pass missed_stranger_gt scoped to the same frame as decisions`
- **clustering**: status=`UNDER-FLOOR / DIRECTIONAL — awaiting operator demotion` directional=True purity=0.800 false_merge=0.500 false_split=0.500 P_same=4 P_diff=6 M=4 frame=`named_matched_faces_pairwise: P_same/P_diff pair floors; M==0 all-singletons guard; single-linkage diagnostic (GRPH-18)`

### Occlusion recovery

- **occlusion.masked**: status=`UNDER-FLOOR / DIRECTIONAL — awaiting operator demotion` directional=True accuracy=1.000 (1/1) n_eligible=1/90
- **occlusion.occlusion_other**: status=`UNDER-FLOOR / DIRECTIONAL — awaiting operator demotion` directional=True accuracy=null (0/0) n_eligible=0/90
- **occlusion.sunglasses**: status=`UNDER-FLOOR / DIRECTIONAL — awaiting operator demotion` directional=True accuracy=null (0/0) n_eligible=0/90

## Gate proposal (excludes DIRECTIONAL)

- role: proposal_only
- release_surface: `proposal_only_not_release`
- canon_version: `0.11.0`
- proposed_slices: []
- excluded_directional: ['clustering', 'headline_identification', 'occlusion.masked', 'occlusion.occlusion_other', 'occlusion.sunglasses', 'unknown_rejection']
- id-recall: 0.667 alongside detection-recall: 0.857 (coupling_flag=True, missed_gt=1, unmatched_det=0) — identification recall is computed only over faces this leg detected and §C-matched (enrolled); weak detection can inflate id-recall on the easy detected subset — report id-recall ALONGSIDE detection-recall
- p95 scan latency: FIR-6-owned; not measured here.
- scope amendments (operator ack required):
  - A10 eval throughput deferred to named follow-up FIR-5a (NOT FIR-7 prod GPU)
  - clustering local floor P_same≥20 ∧ P_diff≥20 and M==0 all-singletons guard
  - p95 full-scan latency deferred to FIR-6 (not measured in FIR-5)
  - synthetic↔real divergence uses Wilson half-width rule (replaces scope >1/3)

## Failures

- none
