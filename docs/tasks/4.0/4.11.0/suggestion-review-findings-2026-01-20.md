# Suggestion Review Findings (2026-01-20)

## Scope
- Reviewed suggestion UI context, pending suggestion payloads, and clustering behavior.
- Sources: `apps/prototype-description-service/logs/scan_worker.log`, `apps/prototype-description-service/logs/recognition.log`, Apple recognition paper.

## Findings
1. Two-avatar context is missing
   - Suggestion cards need both the candidate face and the target cluster representative.
   - Minimum data: `identity_media_url` + `identity_bbox` and `representative_media_url` + `representative_bbox`.
   - `cluster_label` and `cluster_identity_count` are enough for text context; `media_id` is optional for linking.

2. Payload shape
   - Pending suggestions always include the optional media + bbox fields needed for avatars.
   - The endpoint stays paged to keep responses bounded.

3. 57% match meaning
   - `scan_worker.log` shows entries like `similarity 57.32% within suggestion band` and `similarity 60.27% below suggestion floor`.
   - This is a similarity score (representative or avg-member similarity) expressed as a percent, not a probability of correctness.

4. Clustering recall is low
   - RepresentativeDiscovery threshold is 0.85 with best_sim values around 0.64-0.75 (`scan_worker.log` lines ~44, ~275, ~630).
   - Suggestions are frequently skipped for unlabeled clusters (`scan_worker.log` lines ~153, ~190, ~1184).
   - `recognition.log` shows many manual renames/assigns with similarity=0.0000, indicating the system is not clustering expected faces.

5. Precision vs recall in Apple paper
   - The first pass is tuned for high precision and yields many small clusters (paper lines ~111).
   - The second pass (HAC) increases recall significantly (paper lines ~147).

6. Assign vs merge wording
   - Assign identity: move a single identity into a cluster (singleton -> cluster).
   - Merge identity: merge two clusters (all members), with label/anchor selection.
   - Current copy should reflect that difference to avoid confusion.

7. Rename vs new cluster UX
   - Best default: "Yes" assigns to the existing cluster; "No" should keep the identity separate and offer a quick label input to create a new cluster.
   - Avoid auto-creating a new cluster name on reject without user input.

## Recommendations
- Lower representative threshold or widen suggestion band to reduce false negatives.
- Allow suggestions for unlabeled clusters once a small number of confirmations exist, or gate by cluster size instead of label.
- Add inline label editing on suggestion cards to turn rejections into labeled clusters without modal switching.
- Track accept/reject rates per similarity band to tune thresholds.
