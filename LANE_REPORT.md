## DEMO-UX-1-UXB-01 — FIXED
canon rows satisfied: A11Y-02
what changed (files + why): `ClusterLabelingPanel.tsx` now derives every member image alternative from its position in the comparison set and source media item ID; `ClusterLabelingPanel.test.tsx` proves two distinct evidence images do not share an accessible name and updates the branch-specific expectations.
RED output (test-first lanes):
```text
FAIL ClusterLabelingPanel > A11Y-02: gives distinct member faces distinct accessible names for comparison
AssertionError: expected 'Face to label' not to be 'Face to label'
Test Files  1 failed (1)
Tests  1 failed | 57 skipped (58)
```
GREEN output:
```text
Test Files  3 passed (3)
Tests  186 passed (186)
```
residual risk / what a reviewer should attack: The members API exposes a media item ID but no media title, so the alternative uses the stable source media ID plus position. Verify whether a future API can provide the human-readable attachment title without falling back to a filename.

## DEMO-UX-1-UXC-01 — FIXED
canon rows satisfied: HAI-15
what changed (files + why): `ReviewQueue.tsx` now renders a blind independent-name input first, stores the committed judgment in card state, withholds the model name/confidence/disclosure and disables selection until commit, then reveals the proposal for reconciliation. The card is keyed so judgment state cannot bleed into another queue item. `ReviewQueue.test.tsx` asserts the model name is absent from both document and input before the action and present/prefilled only afterward; related queue tests now follow the blind-review order.
RED output (test-first lanes):
```text
FAIL ReviewQueue > HAI-15: withholds the suggested name and prefill until an independent judgment is committed
TestingLibraryElementError: Unable to find role="textbox" and name "Independent name judgment"
Test Files  1 failed (1)
Tests  1 failed | 111 skipped (112)
```
GREEN output:
```text
Test Files  3 passed (3)
Tests  186 passed (186)
```
residual risk / what a reviewer should attack: The independent judgment is retained in UI state for reconciliation but is not yet a separate server-side audit record; review persistence requirements should be checked before treating it as durable provenance.

## DEMO-UX-1-UXC-02 — FIXED
canon rows satisfied: HAI-17
what changed (files + why): `SuggestionCards.tsx` makes the undisclosed reference count explicit and disables Yes while a multi-face identity has an available Review details expansion that has not been opened. Opening details records the expansion and enables approval. `SuggestionCards.test.tsx` covers the disabled-before-expanded and enabled-after-expanded sequence.
RED output (test-first lanes):
```text
FAIL SuggestionCard > HAI-17: requires expansion of all stored references before approval
Error: expect(element).toBeDisabled()
Received element is not disabled
Test Files  1 failed (1)
Tests  1 failed | 15 skipped (16)
```
GREEN output:
```text
Test Files  3 passed (3)
Tests  186 passed (186)
```
residual risk / what a reviewer should attack: Approval is gated when the expansion callback exists; callers without a details surface are not deadlocked. Verify the production parent keeps or restores the reviewed state as expected when its details panel changes surfaces.

## Verification
```text
npx tsc --noEmit --pretty false
npx vitest run js/admin/pages/workbench/identity-clusters/__tests__/ClusterLabelingPanel.test.tsx js/admin/pages/workbench/identity-clusters/__tests__/SuggestionCards.test.tsx js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx --reporter=dot

Test Files  3 passed (3)
Tests  186 passed (186)
Duration  17.07s
```
