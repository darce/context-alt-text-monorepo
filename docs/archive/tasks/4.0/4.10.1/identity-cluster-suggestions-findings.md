# Identity cluster editing observations (v4.10.1)

## 1. Suggestions overlay is empty for new names
- `ClusterEditForm` (`apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterEditForm.tsx:10-113`) only renders suggestions from its `options` array, but `options` is populated solely from `identitySuggestions.matches` in `useClusterSuggestions` (`apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useClusterSuggestions.ts:49-88`). There is no backpressure on the typed label, so new user-defined names never trigger any items that can be filtered into the overlay.
- `findClusterByLabel` (`useClusterSuggestions.ts:91-120`) only runs after the Save button is clicked and pages through `listRecognitionClusters`; the results are never pushed back into the editable dropdown, so the overlay never narrows as the user types.

## 2. Similarity percentages and confirm/reject UI are missing
- The overlay’s buttons only show similarity (`ClusterEditForm.tsx:91-109`) when `option.similarity` exists, yet there are no suggestions with similarity for arbitrary user-defined labels, so the user cannot see dynamic percentages.
- The `window.confirm` flow that previously presented an explicit “merge/assign” confirmation has been replaced with the generic modal around `saveStatus`, so there is no in-line confirm/reject interface that shows the score or lets the user pick a suggestion without exiting edit mode (`apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/IdentityClusterItem.tsx:60-507`).

## 3. Local debug mode lacks representative context
- `DebugMetricsPanel` (`apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/DebugMetricsPanel.tsx:1-73`) only reports face pose/age/gender and the matching similarity; it never reports how many representatives currently cover the cluster or pose data for the current face beyond the summary label.

## 4. Confirmation logs should record representative churn
- Assignment writer helpers like `_is_novel_pose` and `_find_upgradeable_representative` already log pose bucket discoveries and upgrades (`apps/prototype-description-service/recognition/application/persistence/assignment_writer.py:147-214`), but there is no record when a novel pose causes a representative to be created above the configured cap or when a higher-quality face replaces a poor-quality representative in the same bucket. These events are critical for debugging the “new representative face added” requirements and tracking whether better faces supplant older ones.
