# UXW2-6 slices 1–2 report

Lane: lightbox overlay + group naming. Slice 3 (group accept of close matches) is **not** in this checkout.

Commits (by subject only):

- `feat(workbench): UXW2-6 lightbox shows all faces with a ? chip on the reviewed face`
- `feat(workbench): UXW2-6 name inside the box applies to the review group`
- `fix(fe): UXW2-6 load shared overlay styles before other Sass rules`

## What changed

### Slice 1 — every detected face boxed; "?" on the reviewed face

| File | Why |
| --- | --- |
| `js/components/ui/faceGeometry.ts` | `containFit` (letter/pillar-box math FaceLightbox already did inline) + `isPositiveMediaId` so overlay wrapper and fallback bbox share one helper. |
| `js/components/ui/FaceOverlayLayer.tsx` | Optional `reviewFaceId`. That face is pulled out of curated/uncurated lists and rendered as a keyboard-operable "?" chip with accname "Face under review" / "Face under review: {name}". Glyph + accent colour (not colour alone). |
| `js/components/ui/FaceLightbox.tsx` | Optional `identities`, `activeFaceId`, `mediaId`, `onReviewFaceActivate`, `reviewNaming`. Overlay inside `.acx-review-card-lightbox__frame` sized by `containFit`. Empty/absent identities keep the single-bbox fallback. Fetches `media-identities` only while `open && mediaId > 0` and identities were not passed; query options copy AttachmentFacesApp (`retry:false`, no window/reconnect refetch, `staleTime: Infinity`, **no** `refetchInterval`). Loading/error statuses; failed fetch still shows the photo + single highlight. |
| `js/admin/pages/workbench/identity-clusters/SuggestionCards.tsx` | `FaceOriginalTarget` gains optional `mediaId` / `identityId` / `clusterId` / `runSize`. Candidate crop passes `enrichment.identityMediaId` + `suggestion.identityId` only when the media id is positive. |
| `js/admin/pages/workbench/identity-clusters/ReviewQueue.tsx` | Lightbox receives `mediaId` + `activeFaceId` from the open target. |
| `js/admin/styles/components/_face-overlay.scss` | Shared overlay CSS (was attachment-edit-only) plus review-chip tokens. |
| `js/admin/styles/components/index.scss` | `@use './face-overlay'`. |
| `js/attachment-edit/attachment-edit.scss` | `@use` the shared overlay (must sit with the other `@use`s). |
| `js/admin/styles/components/_review-queue.scss` | Overlay wrapper, status, naming, truncation classes. Token-only. |

Existing callers (`PersonWorkspacePanel`, `ReviewCardLightbox` shim, merge cards) still pass only `mediaUrl`/`bbox`/`label` and keep the single-bbox path.

### Slice 2 — naming in the box applies to the review group

| File | Why |
| --- | --- |
| `js/admin/pages/workbench/identity-clusters/reviewQueueDriver.ts` | `REVIEW_GROUP_NAME_CAP = 25` + `reviewGroupNameScope(runSize)` from the ASSIGNMENT run already carried on queue items. |
| `js/admin/pages/workbench/identity-clusters/LightboxNameFace.tsx` | Anchored `NameFaceControl`. Exact roster match → `{clusterId, rosterEntryId}`; novel name → `{clusterId, newEntryName}`. Same reserved-label gate as the card. Visible truncation when `runSize > 25`. |
| `js/admin/pages/workbench/identity-clusters/ReviewQueue.tsx` | "?" → mount naming inside the dialog. ASSIGNMENT open-original attaches `clusterId` + `runSize`. Commit is **one** `schedulePersonCommit` (no second write path). Success announces via the existing polite live region and closes the dialog. Cancel returns focus to the "?" chip. |

## RED-first evidence

### Slice 1 (before production existed)

Ran the new tests against current HEAD: **12 failed / 59 passed**.

| Test | Assertion that failed |
| --- | --- |
| `containFit` letterbox / pillarbox / unusable | `containFit` / `isPositiveMediaId` not exported |
| `FaceOverlayLayer` "?" chip | `Unable to find role="button" name "Face under review"` |
| `FaceOverlayLayer` named review | `Unable to find ... "Face under review: Pat Rivera"` |
| `FaceLightbox` overlay | `Unable to find [data-testid="acx-face-overlay-layer"]` |
| `FaceLightbox` fetch while open | timed out waiting for the review chip (no query) |
| `FaceLightbox` fetch error | `Unable to find role="status"` |
| `FaceLightbox` loading | `Unable to find role="status"` |
| `SuggestionCard` candidate original | `onOpenOriginal` payload lacked `mediaId` / `identityId` |

Existing bbox / shim / closed-dialog tests stayed green (fallback path).

### Slice 2 (before production existed)

| Test | Assertion that failed |
| --- | --- |
| `LightboxNameFace.test.tsx` collect | `Failed to resolve import "../LightboxNameFace"` |
| `reviewGroupNameScope` cap | `REVIEW_GROUP_NAME_CAP` undefined; `reviewGroupNameScope is not a function` |
| ReviewQueue "names the reviewed face…" | no "?" chip / no naming surface / no `commitClusterToRosterEntry` from lightbox |
| ReviewQueue "surfaces truncation…" | `Unable to find text "Naming the first 25 faces in this group. 1 more were not included."` |

## Mutate-and-restore proofs

Each line was broken, the named test went RED, then the file was restored.

| Proof name | Production line broken | Test that went RED |
| --- | --- | --- |
| `containFit-min-to-max` | `Math.min` → `Math.max` in `containFit` | `pillarboxes a tall image` (`scale: 1` expected, got `4`) |
| `review-chip-glyph` | `"?"` → `"•"` in the review chip | `renders a keyboard-operable ? chip` (`toHaveTextContent('?')`) |
| `shouldFetch-open-gate` | dropped `open &&` from `shouldFetch` | `does not fetch media identities while closed` (`toHaveBeenCalled` with `[42]`) |
| `LOAD_FAILED-copy` | `'Could not load other faces.'` → `'Could not load faces.'` | `keeps the photo and single-face highlight` (status text) |
| `SuggestionCards-skip-mediaId` | `if (false && isPositiveMediaId(mediaId))` | `passes identity media id and face id` |
| `REVIEW_GROUP_NAME_CAP-25-to-10` | cap `25` → `10` | `caps at 25 and reports how many were omitted` (`included: 25` vs `10`) |
| `LightboxNameFace-hide-truncation` | `{false && scope.truncated` | `shows an explicit truncation signal` |
| `LightboxNameFace-roster-as-create` | roster branch commits `newEntryName` | `binds an exact roster match` (wanted `rosterEntryId: 7`) |
| `ReviewQueue-runSize-forced-1` | `runSize: currentItem.runSize` → `runSize: 1` | `surfaces truncation when the same-group run is larger than 25` |

## Final gates

From `apps/prototype-wp-alt-context`:

| Gate | Result |
| --- | --- |
| `./node_modules/.bin/vitest run` | exit **0** — **225** files, **2619** tests (baseline 224 / 2592; +1 file, +27 tests) |
| `npm run typecheck` | exit **0** — 0 errors |
| `./vendor/bin/phpunit` | exit **0** — **1942** tests, **9558** assertions (unchanged) |

No pre-existing test was deleted or weakened. The SuggestionCard "omits mediaId" case was tightened to still require `identityId` (always on the suggestion) while asserting `mediaId` is absent.

## Gaps (do not understate)

1. **25-cap vs cluster write.** `schedulePersonCommit` / `commitClusterToRosterEntry` names the **whole cluster**. The UI caps presentation at 25 and says N were not included. The backend still labels every member of that cluster. Omitting 15 faces would need a new API and would split one atomic write ([rg-002]). Slice 3 owns per-id bulk accept, not this path.
2. **Slice 3 not implemented** (out of scope).
3. **Handoff MCP / Python API** (`workbay_handoff_mcp`) is not importable in this clone; `make context` has no target. No `record_event` was written. This markdown file is the reviewer channel.
4. **Candidate crop only** gets `mediaId`/`identityId`. Representative crop stays on today's single-bbox payload (reviewed face is not on that photo).
5. **Radix dialog warning** `Missing Description or aria-describedby={undefined}` appears in jsdom when QueryClient wraps the lightbox. Dialog still has `DialogDescription` + `aria-describedby`; Close/Esc/focus trap work. Not a product blank-dialog.
6. **`.lane/`** is untracked and was not committed.
7. Overlay CSS 24px hit-target literals were **moved**, not newly introduced (A11Y-14 floor already in attachment-edit). New review-chip sizes use `--acx-space-24` / tokens.
