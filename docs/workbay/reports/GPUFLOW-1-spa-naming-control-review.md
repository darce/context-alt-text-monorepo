FINDINGS: [{"id":"GPUFLOW-1-SPANAMINGCONTROL-R-01","severity":"medium","file_path":"apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/buildNamingOptions.ts","line":298,"summary":"The C1 preview proof tests an unconsumed selector instead of the production renderer.","evidence":"selectGroupPreviewSource is declared at buildNamingOptions.ts:298-305 and appears only in its new unit test; IdentityClusterItem renders ClusterPreview at IdentityClusterItem.tsx:395-399, whose independent fallback remains at ClusterPreview.tsx:27-32. The delta removes the direct ClusterPreview fixture/assertions from NameFaceControl.test.tsx:17-73 and the lane command does not run ClusterPreview.test.tsx."},{"id":"GPUFLOW-1-SPANAMINGCONTROL-R-02","severity":"medium","file_path":"apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/NameFaceControl.test.tsx","line":608,"summary":"The replacement mount test drops the closed-state aria-activedescendant assertion.","evidence":"The delta deletes the prior assertion that a focused closed combobox has no aria-activedescendant (.review/CHANGE.diff:17-30) and replaces it with listbox/option absence only. The component still exposes aria-activedescendant from NameFaceControl.tsx:502-504, while the remaining tests assert it only after opening at NameFaceControl.test.tsx:128-138."}]
Verdict: pass_with_findings

# GPUFLOW-1 spa-naming-control review

| base | tip | files |
| --- | --- | --- |
| `1f6d97fc712086c027b11ff63189dced6fb7615d` | `1c03364082ee612db5c3de422f2851ed0c646416` | `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/NameFaceControl.test.tsx`; `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/buildNamingOptions.test.ts`; `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/buildNamingOptions.ts` |

The supplied delta changes exactly three paths, all within the lane-owned list. `NameFaceControl` is already initialized closed in the reviewed tree and the new tests cover autofocus, typing, ArrowDown, and Escape intent. The existing read-only `ClusterPreview` consumer currently selects a complete `representative_face` URL/bbox pair, falls back to the first member, and renders the explicit unavailable-image avatar when neither source is usable. The added fixture covers complete, absent, incomplete, and missing-source selector cases. However, the selector is not wired into that renderer, and the replacement mount test drops one closed-state accessibility assertion. These are proof-integrity gaps under [TEST-15] and the repository's no-fabrication boundary [rg-015].

The repository lock check passed. The declared Vitest command could not be trusted in this sandbox because there is no local `node_modules/.bin/vitest`; the bounded `npx --no-install` attempt timed out with exit 124. The delta itself does not skip the command.

## FINDINGS

### GPUFLOW-1-SPANAMINGCONTROL-R-01 — medium

- **File:line:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/buildNamingOptions.ts:298-305`; `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/buildNamingOptions.test.ts:251-255`
- **Evidence:** `selectGroupPreviewSource` is declared and tested, but `rg` finds no production import/call. The only production route is `IdentityClusterItem.tsx:395-399` → `ClusterPreview.tsx:27-32`, which independently repeats the source selection. The delta removes the direct `ClusterPreview` fixture/assertions from `NameFaceControl.test.tsx` and the lane Vitest row does not execute `ClusterPreview.test.tsx`.
- **Impact:** The new green test can remain green while the actual group preview drifts or stops applying the required representative → first-member → placeholder chain; duplicate policy can diverge across the UI boundary. This violates the green-can-go-red discipline [TEST-15].
- **Fix:** Restore a real `ClusterPreview` render assertion in the owned C1 proof (or have the owning lane add its component test to the executed command), and either wire this selector into the renderer through the correct ownership lane or remove the unconsumed export so one source-selection policy is tested.

### GPUFLOW-1-SPANAMINGCONTROL-R-02 — medium

- **File:line:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/NameFaceControl.test.tsx:608-615`
- **Evidence:** The delta deletes the previous `not.toHaveAttribute('aria-activedescendant')` assertion while adding listbox/option absence checks. `NameFaceControl.tsx:502-504` still derives and emits this attribute, and the remaining assertions at `NameFaceControl.test.tsx:128-138` cover only the open state.
- **Impact:** A regression that leaves a stale active descendant on a focused closed combobox can pass the lane's new mount test, weakening the APG closed-state contract and the required C1 proof.
- **Fix:** Keep the new listbox/option assertions and restore an explicit `expect(input).not.toHaveAttribute('aria-activedescendant')` assertion for the closed mount state.

## Re-review r2 (1c0336408..b879db1f1)

| finding | verdict | evidence |
| --- | --- | --- |
| `GPUFLOW-1-SPANAMINGCONTROL-R-01` | fixed | The fix removes the unconsumed `selectGroupPreviewSource` implementation and its selector-only unit test from `buildNamingOptions.ts` and `buildNamingOptions.test.ts` (`.review/CHANGE.diff:326-399`), then renders the production `ClusterPreview` directly with the fixture cases and asserts the selected URL/bbox or placeholder (`.review/CHANGE.diff:162-230`). |
| `GPUFLOW-1-SPANAMINGCONTROL-R-02` | fixed | The closed-on-mount test now explicitly asserts that the focused combobox has no `aria-activedescendant` (`.review/CHANGE.diff:197-205`), alongside the closed listbox/option assertions. |

### FINDINGS

FINDINGS: []

Verdict: pass
