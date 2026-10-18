# GPUFLOW-1 spa-suggestion-cards review

Verdict: pass_with_findings

| base | tip | files |
| --- | --- | --- |
| `1f6d97fc712086c027b11ff63189dced6fb7615d` | `604f92c5fd3943c8a32d5760f19f8d9d684e768c` | `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/SuggestionCards.tsx`; `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/SuggestionCards.test.tsx` (the owned fixture path was inspected and unchanged) |

## Review basis

- The authoritative inlined delta changes only the two paths listed above; both are within the lane-owned list. The owned `gpuflow-candidate-preview.json` fixture is an unchanged read-only input.
- `SuggestionCards` renders the shared accessible placeholder when representative media is absent and checks `isCroppableBbox` before `FaceThumbnail`; valid candidate and representative media remain distinct in the added proof.
- The null-representative, invalid-geometry, and representative-only invalid-geometry cases exercise the public card output. The backend normal/replay exclusion is upstream scope and is not duplicated here.
- The declared lane command is `npx vitest run js/admin/pages/workbench/identity-clusters/__tests__/SuggestionCards.test.tsx`. It could not run in this sandbox because the app has no local `node_modules`/Vitest; the required repository gate passed.

## FINDINGS

### GPUFLOW-1-SPASUGGESTIONCARDS-R-02 — low

- **File:line:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/SuggestionCards.tsx:91-93`; `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/SuggestionCards.test.tsx:102-133`
- **Evidence:** Both `FaceCropControl` call sites receive `identityFace`/`representativeFace` objects constructed only after `isCroppableBbox` succeeds at `SuggestionCards.tsx:158-168`. The invalid-geometry test therefore reaches the parent fallback and never invokes the new `FaceCropControl` guard; removing lines 91-93 leaves that test green.
- **Impact:** The added proof does not protect the defensive `FaceCropControl` gate itself ([TEST-15]); a future caller that passes an invalid bbox directly could regress to mounting `FaceThumbnail` without a test detecting it.
- **Fix:** Either remove the redundant private guard and keep one tested gate at face-object construction, or expose a small test seam/directly exercise `FaceCropControl` with invalid geometry while retaining the guard.

## Re-review r2 (6192796d5..aae2980e1)

| finding | verdict | evidence |
| --- | --- | --- |
| CALIBR-M-06 | fixed | `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/SuggestionCards.tsx:249-252` adds `suggestion.enrichment?.representativeMediaId` to the representative `FaceCropControl` target. The added callback assertion at `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/SuggestionCards.test.tsx:364-370` requires the representative media ID, and the fixture supplies it at `gpuflow-candidate-preview.json:12-15`; the missing-ID test also preserves omission when no ID is available. |

### FINDINGS

FINDINGS: []

Verdict: pass
