# GPUFLOW-1 C3 — wrong-match and occlusion calibration

Status: `DIRECTIONAL`; operator capture and sign-off are pending. This is an analysis artifact only. The proposals below are for representative ranking; they are not assignment or suggestion thresholds.

## Decision

- Keep the effective `suggestion_floor` at `0.35` for now. Do not raise it from the single Trudeau/Watson report, and do not enable a quality-adaptive margin until the missing live row and open-set evidence gate are complete. The configured suggestion band is `0.35–0.55`; the rebaseline explicitly says that this band is configuration, not a captured value for the row. [docs/assessments/GPUFLOW-1-rebaseline-20260914.md:86-94]
- Carry these provisional representative-ranking values into C4 only after operator acceptance: `factor_ceiling_occlusion = 0.50` and `factor_floor_sharpness = 10.0`. Both are `DIRECTIONAL`: neither is a percentile or error-rate calibration on the live corpus. [apps/prototype-description-service/recognition/application/settings/clustering.py:72-89] [apps/prototype-description-service/recognition/tests/unit/test_representative_quality_gate.py:68-73,116-138]
- Leave `similarity_threshold`, `suggestion_floor`, `suggestion_ceiling`, and the shared assignment quality path unchanged while C4 wires the representative-only experiment. The frozen GPUFLOW plan requires that separation. [docs/tasks/v0.5.0/GPUFLOW-1-description-service-flow-and-identity-fixes-task-plan.md:387-400]

## Live Trudeau → Watson row

The only defensible numeric statement is that the row has no captured numeric values. The rebaseline records similarity, band, representative identity ID, quality, and occlusion as `NOT CAPTURED`; it records only the configured band (`0.35–0.55`) and the displayed identity/avatar evidence. No similarity, quality, or occlusion value is inferred here. [docs/assessments/GPUFLOW-1-rebaseline-20260914.md:86-98]

The operator must run the following read-only query against the tenant that produced the row. Filter by the actual Trudeau media ID and the suggested `Emma Watson` cluster label; if the UI has a stable suggestion ID, use it as an additional filter. The selected columns cover the suggestion, candidate identity, suggested cluster, selected representative, representative row, and both quality-factor sets.

```sql
SELECT
    s.id AS suggestion_id,
    s.evidence_generation,
    s.created_at,
    s.source,
    s.resolution,
    s.identity_id AS candidate_identity_id,
    s.suggested_cluster_id,
    s.representative_similarity,
    s.avg_member_similarity,
    s.confidence_score,
    c.label AS suggested_label,
    c.representative_identity_id AS cluster_representative_identity_id,
    c.similarity_threshold AS cluster_similarity_threshold,
    candidate.media_id AS candidate_media_id,
    candidate.media_url AS candidate_media_url,
    candidate.bbox_x AS candidate_bbox_x,
    candidate.bbox_y AS candidate_bbox_y,
    candidate.bbox_width AS candidate_bbox_width,
    candidate.bbox_height AS candidate_bbox_height,
    candidate.confidence AS candidate_detection_confidence,
    candidate.embedding_model AS candidate_embedding_model,
    candidate.quality_score AS candidate_quality_score,
    candidate.sharpness AS candidate_sharpness,
    candidate.embedding_norm AS candidate_embedding_norm,
    candidate.occlusion_severity AS candidate_occlusion_severity,
    rep.id AS representative_identity_id,
    rep.media_id AS representative_media_id,
    rep.media_url AS representative_media_url,
    rep.bbox_x AS representative_bbox_x,
    rep.bbox_y AS representative_bbox_y,
    rep.bbox_width AS representative_bbox_width,
    rep.bbox_height AS representative_bbox_height,
    rep.confidence AS representative_detection_confidence,
    rep.embedding_model AS representative_embedding_model,
    rep.quality_score AS representative_quality_score,
    rep.sharpness AS representative_sharpness,
    rep.embedding_norm AS representative_embedding_norm,
    rep.occlusion_severity AS representative_occlusion_severity,
    cr.quality_score AS representative_row_quality,
    cr.diversity_score AS representative_row_diversity,
    cr.is_user_selected AS representative_is_user_selected
FROM identity_suggestions AS s
JOIN media_identities AS candidate ON candidate.id = s.identity_id
JOIN identity_clusters AS c ON c.id = s.suggested_cluster_id
LEFT JOIN media_identities AS rep ON rep.id = c.representative_identity_id
LEFT JOIN identity_cluster_representatives AS cr
       ON cr.cluster_id = c.id AND cr.identity_id = rep.id
WHERE s.tenant_id = :tenant_id
  AND candidate.media_id = :trudeau_media_id
  AND c.label = 'Emma Watson'
ORDER BY s.created_at DESC, s.evidence_generation DESC;
```

The query is grounded in the persisted columns: `identity_suggestions` stores the representative and average-member similarities plus `confidence_score`; `media_identities` stores `sharpness`, `embedding_norm`, `occlusion_severity`, and `quality_score`; clusters and representative rows store the selected representative and representative quality metadata. [apps/prototype-description-service/db/models/constraints.py:33-92] [apps/prototype-description-service/db/models/identity.py:41-70] [apps/prototype-description-service/db/models/identity.py:108-124] [apps/prototype-description-service/db/models/identity.py:244-280]

Capture assignment provenance separately because it is not a reliable join from the suggestion row alone:

```sql
SELECT
    identity_id,
    cluster_id,
    decision,
    similarity,
    reason,
    algorithm,
    job_id,
    metadata_json,
    timestamp
FROM assignment_decisions
WHERE tenant_id = :tenant_id
  AND identity_id = CAST(:candidate_identity_id AS text)
  AND cluster_id = CAST(:suggested_cluster_id AS text)
ORDER BY timestamp DESC;
```

The operator must also attach the effective runtime settings snapshot for the same job: `similarity_threshold`, `suggestion_floor`, `low_confidence_band_width`, `low_confidence_suggestion_floor`, `suggestion_ceiling`, `quality.factor_floor_sharpness`, and `quality.factor_ceiling_occlusion`. The first five are application settings, not columns in the suggestion row. Current defaults are `similarity_threshold=0.55`, `suggestion_floor=0.35`, `low_confidence_band_width=0.05`, optional low-confidence override unset, and `suggestion_ceiling=0.55`; quality-factor defaults are the no-op `factor_floor_sharpness=0.0` and `factor_ceiling_occlusion=1.0`. [apps/prototype-description-service/recognition/application/settings/clustering.py:72-89] [apps/prototype-description-service/recognition/application/settings/clustering.py:226-280]

### What each capture outcome means

| Captured outcome | Meaning for `suggestion_floor` |
|---|---|
| Similarity is below the effective floor but a suggestion was emitted | This is a stale, miswired, or precedence problem. Keep `0.35`; repair the route and capture settings before considering a floor change. [apps/prototype-description-service/recognition/application/settings/clustering.py:226-280] |
| Similarity is in the configured band and the target is wrong while candidate/representative quality is low | The band is doing review routing, but quality should be surfaced or used in a future suggestion-only margin. Keep the fixed floor until per-stratum open-set rates show the recall cost. |
| Similarity is in the band and the target is wrong while both quality sets are high | This is evidence against the current band, but one row cannot set a new floor. Require repeated non-mated and genuine measurements before raising it; report the FNMR/recall tax if it is raised. |
| Similarity is at or above `0.55` | This implicates acceptance/assignment calibration rather than `suggestion_floor`; C3/C4 must not silently change the assignment threshold. [apps/prototype-description-service/recognition/application/settings/clustering.py:226-280] |
| Factors are absent or `NULL` | The current representative multiplier is intentionally neutral for missing factors, so this row cannot calibrate sharpness or occlusion. |

The row must therefore record both similarities, not just a rank-1 label: `representative_similarity` and `avg_member_similarity`. A rank-1 margin is not an admissible acceptance signal under FIR D-08. [apps/prototype-description-service/db/models/constraints.py:53-69] [docs/tasks/fir/FIR-13-open-set-gate-contract-task-plan.md:47-62]

## FIR-11, FIR-7, and FIR-17 quality evidence

### Occlusion distributions and ceilings

| Evidence | Observed distribution | Ceiling/qualification |
|---|---|---|
| FIR-11 corrected post-celebrity corpus | `143` entries, `160` named probes, and `49` identities; strata are `profile=50`, `low_res=26`, `blur=26`, `occlusion_other=17`, `sunglasses=13`, and `masked=5`. The full frame is `150` entries, `167` named probes, and `54` identities. | These are tagged-entry/subject-proxy counts, not `occlusion_severity` quantiles; FIR-11 explicitly says the masked and sunglasses counts are subject proxies. The largest listed occlusion-related stratum is `17`, and the smallest is `5`. [docs/tasks/fir/FIR-11-gate-corpus-remediation-and-fir-rebaseline-task-plan.md:104,119] |
| FIR-11 v3 hand-tag inventory | Of `150` reviewed entries, `96` are tagged and `54` are untagged; tags are `profile=50`, `blur=28`, `low_res=26`, `occlusion_other=19`, `sunglasses=13`, `masked=5`, and `similar_people=0`. | The `masked=5` and `sunglasses=13` cells are too small for a stable error-rate ceiling. FIR-11 gives Wilson half-widths of `±11.9pp` for a clean `n=56` cell and `±31.4pp` for a masked `n=5` cell at observed `p≈0.70`. [docs/tasks/fir/FIR-11-gate-corpus-remediation-and-fir-rebaseline-task-plan.md:195,216] |
| FIR-7 synthetic occlusion diagnostic | Pre-CVUP synthetic `a_s` is `0.321` (`27/84`) for masked, `0.226` for sunglasses, and `0.643` (`5/84`) for `occlusion_other`; masked re-detect misses are `54/84`, and the sunglasses re-detect miss count is `49/84`. | These values are internal-gap/diagnostic figures, not production ceilings: FIR-7 marks them pre-CVUP and inadmissible for external claims. [docs/tasks/fir/FIR-7-occlusion-adapters-task-plan.md:103-110] [docs/tasks/fir/FIR-7-occlusion-adapters-task-plan.md:315-330] |
| FIR-17 runtime proxy | `compute_occlusion_severity` is still a scalar from canonical eye patches. The planned region-visibility signal has `5` texture-only face regions, each in `[0,1]`; it has no occlusion oracle or per-landmark confidence. | The numeric proxy range is bounded by `0` and `1`, but `1.0` is only the saturation ceiling of the proxy, not “fully occluded” ground truth. [docs/tasks/fir/FIR-17-inference-only-occlusion-robustness-task-plan.md:43,60-70,76-77] [docs/specs/fir-open-set-gate-and-occlusion-spec.md:382] |

The eye-patch limitation matters for a microphone or open mouth: the production proxy samples the two eye patches and compares their variance and edge activity with the whole crop; it does not inspect the mouth or lower-face region. A microphone crossing the mouth, an open mouth, or lower-face obstruction can therefore leave the eye signal high and produce a low severity even when the face is operationally occluded. Noise or low contrast in an eye patch can also produce the opposite error. This is why the eye-patch value is a weak proxy, not a microphone/open-mouth detector. [apps/prototype-description-service/recognition/infrastructure/embeddings/face_quality_factors.py:82-105] [docs/tasks/fir/FIR-6-calibration-quality-switchover-task-plan.md:96-98]

### Sharpness distribution and ceiling

The requested FIR-11/FIR-7/FIR-17 evidence does not publish a numeric sharpness distribution, percentile, or corpus ceiling. The metric is defined as variance of the Laplacian on an aligned `112×112` crop; higher values mean sharper imagery, but no FIR stratum supplies enough observed values to choose a percentile or error-rate operating point. [docs/tasks/fir/FIR-6-calibration-quality-switchover-task-plan.md:96] [apps/prototype-description-service/recognition/infrastructure/embeddings/face_quality_factors.py:47-61]

Consequently, the only defensible sharpness ceiling statement is that the raw score has no evidence-backed ceiling in this corpus. `10.0` below is a test-scale starting point, not a measured corpus quantile. [apps/prototype-description-service/recognition/tests/unit/test_representative_quality_gate.py:68-73,116-138] The occlusion count ceilings above and the proxy’s numeric saturation at `1.0` must not be confused with calibrated factor thresholds. [apps/prototype-description-service/recognition/infrastructure/embeddings/face_quality_factors.py:82-105] [docs/tasks/fir/FIR-17-inference-only-occlusion-robustness-task-plan.md:69-70]

## Current knobs and representative scoring

The clustering settings expose quality floors as enrollment/application settings, but their defaults are deliberately inert: `factor_floor_sharpness=0.0` and `factor_ceiling_occlusion=1.0`. The settings validate the sharpness floor as non-negative and the occlusion ceiling in `[0,1]`. [apps/prototype-description-service/recognition/application/settings/clustering.py:72-89]

The suggestion/assignment knobs are separate: `similarity_threshold=0.55`, `suggestion_floor=0.35`, a `0.05` low-confidence band width, and `suggestion_ceiling=0.55`; the low-confidence floor can be explicitly overridden but is unset by default. [apps/prototype-description-service/recognition/application/settings/clustering.py:226-280]

Representative selection bridges the three quality factors from settings. Missing factors never fail the gate, no-op floors yield a multiplier of `1.0`, and active factors are combined with equal weights of one third. Sharpness and embedding norm are scaled against twice their configured floors; occlusion severity contributes `1 - severity/ceiling`, clamped to `[0,1]`. [apps/prototype-description-service/recognition/application/persistence/representative_selector.py:39-75] [apps/prototype-description-service/recognition/application/persistence/representative_selector.py:74-108] [apps/prototype-description-service/recognition/application/persistence/representative_selector.py:130-156]

That implementation has an important boundary for C4: the existing `passes_enrollment_floors` function can reject an identity when active factors are used, while the C3 proposal is intentionally representative-ranking only. C4 must not route these values into candidate assignment, suggestion admission, or shared `quality.py`; it must preserve the current assignment thresholds. [apps/prototype-description-service/recognition/application/persistence/representative_selector.py:74-108] [docs/tasks/v0.5.0/GPUFLOW-1-description-service-flow-and-identity-fixes-task-plan.md:387-400]

## Representative-only proposal

| Factor | Proposed value for C4 ranking | Evidence row | Expected precision/recall cost | Confidence |
|---|---:|---|---|---|
| `factor_ceiling_occlusion` | `0.50` | The factor is a severity proxy bounded in `[0,1]`; FIR-7’s stale synthetic diagnostics include `masked a_s=0.321`, `sunglasses=0.226`, and `occlusion_other=0.643`, while the current no-op ceiling is `1.0`. [apps/prototype-description-service/recognition/infrastructure/embeddings/face_quality_factors.py:82-105] [docs/tasks/fir/FIR-7-occlusion-adapters-task-plan.md:103-110] [apps/prototype-description-service/recognition/application/settings/clustering.py:84-89] | Downweights high eye-patch severity in representative ranking, expected to improve representative precision and reduce wrong-avatar exposure. It can reduce representative recall/coverage when every available view is above the ceiling; assignment recall must be unchanged if C4 keeps this rank-only. No percentage cost is estimable from the underpowered `masked=5` and `sunglasses=13` strata. [docs/tasks/fir/FIR-11-gate-corpus-remediation-and-fir-rebaseline-task-plan.md:195,216] | `DIRECTIONAL` |
| `factor_floor_sharpness` | `10.0` raw variance-of-Laplacian units | FIR defines sharpness as Laplacian variance on an aligned `112×112` crop, with no FIR-11/FIR-7/FIR-17 numeric distribution. The existing active-floor test contract uses `10.0` and distinguishes a `5.0` low-sharpness value from a `50.0` passing value; that is implementation-scale evidence only. [docs/tasks/fir/FIR-6-calibration-quality-switchover-task-plan.md:96] [apps/prototype-description-service/recognition/infrastructure/embeddings/face_quality_factors.py:47-61] [apps/prototype-description-service/recognition/tests/unit/test_representative_quality_gate.py:68-73,116-138] | Downweights blurrier views in representative ranking, expected to improve representative precision and reduce unstable avatar selection. It can reduce representative recall/coverage if the corpus has few sharp views; no assignment FNMR cost is allowed from a rank-only change, and no percentage cost is estimable without the missing sharpness distribution. [apps/prototype-description-service/recognition/application/persistence/representative_selector.py:139-156] | `DIRECTIONAL` |

The values are proposal-only until the operator captures the live row and C4 measures the trade-off on subject-disjoint, out-of-fold evidence. FIR requires a dark/no-op posture for unvalidated floors and a representative multiplier that is neutral when factors are missing or no-op. [docs/tasks/fir/FIR-6-calibration-quality-switchover-task-plan.md:50-59,86,128-130]

## `suggestion_floor` recommendation and evidence gate

Recommendation: **KEEP `suggestion_floor=0.35` now; do not raise it and do not activate a quality-adaptive margin yet.** The current floor is below the `0.55` similarity/ceiling boundary, with a `0.05` low-confidence width; these are configuration values, not evidence that Trudeau→Watson was valid or invalid. [apps/prototype-description-service/recognition/application/settings/clustering.py:226-280] [docs/assessments/GPUFLOW-1-rebaseline-20260914.md:86-94]

The eventual preferred experiment is a quality-adaptive, suggestion-only margin informed by validated PFE/MLS-style quality signals and embedding norm, as the GPUFLOW plan describes. The local corpus specification says AdaFace’s pre-L2 feature norm is a recommended quality proxy but is not currently available after normalization, so this remains future work rather than a numeric C3 setting. [docs/tasks/v0.5.0/GPUFLOW-1-description-service-flow-and-identity-fixes-task-plan.md:534] [docs/specs/fr-corpus-acquisition-spec.md:194-198]

Before any floor change, require all of the following:

- quality-stratified genuine/impostor FMR and FNMR, so a global change is justified per CAL-01;
- non-mated FNIR at a fixed FPIR and an explicit score threshold, with FPI kept as an integer; rank-1/CMC or a rank-1 margin is not an acceptance gate under FIR D-08; [docs/assessments/current/gpu-burst-pipeline-status-and-fir-insightface-replacement-2026-09-11.md:122] [docs/tasks/fir/FIR-13-open-set-gate-contract-task-plan.md:47,62]
- the FNMR/recall tax across every quality stratum if a global floor is raised, per CAL-05; and
- no demographic-conditioned threshold or margin, per CAL-06. A score must not be called a calibrated probability without calibration evidence, per CAL-03.

These gates are consistent with FIR’s explicit warning that no declared acceptance threshold exists yet and that rank-1 margin is inadmissible. [docs/tasks/v0.5.0/GPUFLOW-1-description-service-flow-and-identity-fixes-task-plan.md:50-51]

## Operator acceptance before C4

The operator must check each item before `svc-rep-settings` or `svc-rep-quality` starts:

- [ ] Run the read-only queries above and attach the Trudeau→Watson row, including `representative_similarity`, `avg_member_similarity`, effective threshold snapshot, candidate and representative IDs, sharpness, embedding norm, occlusion severity, quality score, detection confidence, embedding model, bbox, and assignment-decision provenance.
- [ ] Confirm that `NOT CAPTURED` remains `NOT CAPTURED` until the query returns values; do not substitute the configured `0.35–0.55` band for a row score. [docs/assessments/GPUFLOW-1-rebaseline-20260914.md:86-94]
- [ ] Accept `factor_ceiling_occlusion=0.50` and `factor_floor_sharpness=10.0` as `DIRECTIONAL`, representative-ranking-only values; keep assignment thresholds unchanged. [apps/prototype-description-service/recognition/application/settings/clustering.py:72-89] [docs/tasks/v0.5.0/GPUFLOW-1-description-service-flow-and-identity-fixes-task-plan.md:387-400]
- [ ] Record the quality-stratified open-set/genuine evidence gate, including fixed-FPIR FNIR, integer FPI, and FNMR tax before approving any floor change.
- [ ] Confirm CAL-01, CAL-03, CAL-05, and CAL-06 handling, and require TEST-15 mutation/red-proof coverage in C4 so an active-factor regression can actually fail a test.
- [ ] Record operator name, timestamp, and decision/sign-off. Until this checkbox is complete, C4 dispatch remains held under REBASE-M-03.

```json
{
  "handoff_action": "merge_ready",
  "summary": "C3 calibration report is ready with a pending Trudeau/Watson operator capture.",
  "details": "Proposed representative-only values are factor_ceiling_occlusion=0.50 and factor_floor_sharpness=10.0, both DIRECTIONAL because the real corpus has no calibrated factor distributions [apps/prototype-description-service/recognition/application/settings/clustering.py:72-89; apps/prototype-description-service/recognition/tests/unit/test_representative_quality_gate.py:68-73,116-138]. Keep suggestion_floor=0.35 for now [apps/prototype-description-service/recognition/application/settings/clustering.py:226-280]. Pending operator capture must return representative_similarity, avg_member_similarity, effective threshold values, candidate and representative IDs, quality factors, and assignment provenance before C4 dispatch [docs/assessments/GPUFLOW-1-rebaseline-20260914.md:86-98].",
  "tests_run": [
    "/home/gate/grok-sandbox/feature-gpuflow-1-calibration-69af87ac/.venv/bin/python -m pytest scripts/tests/test_composer_lock_tracked.py -q -p no:cacheprovider",
    "git diff --check"
  ],
  "blockers": [
    "REBASE-M-03: Trudeau/Watson numeric row capture and operator sign-off are pending before C4 dispatch."
  ]
}
```
