# E21-15 REV1 verdict

Lane `e21-15` on `feature/e21-15`. New commits this session: REV1-03, REV1-08. All other listed findings were already present in the sandbox snapshot; this session verified them with TEST-15 mutations.

Gate (unmasked):
- `./node_modules/.bin/tsc --noEmit -p tsconfig.json` → exit 0
- `./node_modules/.bin/vitest run js/components js/admin/pages/workbench js/admin/pages/roster js/admin/styles` → Test Files 112 passed / Tests 1416 passed, exit 0

## E21-15-REV1-01 (high) — fixed

- Status: fixed (already in snapshot; verified).
- Files: `js/components/ui/faceThumbDisplay.ts:164` (`dedicated && thumbUrl`, not `thumbUrl && (dedicated || crop)`).
- Why: PHP fills `thumb_url` with the full-scene attachment when no `/recognition/face-thumbs/` blob exists. Gating avatar-first on any nonempty URL painted the scene as a face chip.
- TEST-15: restore `if (thumbUrl && (dedicated || crop) && blobStatus !== LOAD_STATUS.error)`.
- RED: `a non-dedicated thumbUrl with croppable media falls through to crop [REV1-01]` — `expected 'avatar' to be 'crop'`. Restored GREEN.

## E21-15-REV1-02 (high) — fixed

- Status: fixed (already in snapshot; verified).
- Files: `faceThumbDisplay.ts` `AVATAR_STATE.uncropped` + `resolveUncroppedSource`; `DurableFaceThumb.tsx` uncropped `<img>` + `--uncropped`; `WorkbenchFindingsPanel.tsx:93` `isCroppableBbox`.
- Why: a usable media/attachment URL with no croppable bbox was announced missing.
- TEST-15: disable the `if (uncroppedSrc)` hop.
- RED: `a nonempty mediaUrl without a croppable bbox is uncropped, not missing [REV1-02]` — `expected 'missing' to be 'uncropped'`. Restored GREEN.

## E21-15-REV1-03 (high) — fixed

- Status: fixed this session (`9fff0a3`).
- Files: `js/components/ui/cropFaceFromImage.ts`, `js/components/ui/__tests__/cropFaceFromImage.test.ts`.
- Why: previous suite only hit the size<=0 early return. Recording `getContext`/`drawImage`/`toDataURL` now pins bbox+padding geometry; thrown crop returns null.
- TEST-15 mutation table (crop-geometry test itself went RED; not collateral-only):

| Mutation | Result | Test | Verbatim |
|---|---|---|---|
| invert `sx`/`sy` in `drawImage` | RED | draws the padded bbox source rectangle and returns the jpeg data URL | `expected { sx: 4, sy: 34, sWidth: 52, …(1) } to deeply equal { sx: 34, sy: 4, sWidth: 52, …(1) }` |
| drop padding (`paddingX/Y = 0`) | RED | draws the padded bbox source rectangle and returns the jpeg data URL | `expected { sx: 40, sy: 10, sWidth: 40, …(1) } to deeply equal { sx: 34, sy: 4, sWidth: 52, …(1) }` |
| skip `ctx.drawImage` | RED | draws the padded bbox source rectangle and returns the jpeg data URL | `expected "vi.fn()" to be called 1 times, but got 0 times` |
| replace body after size guard with `return canvas.toDataURL('image/jpeg', 0.92)` | RED | draws the padded bbox source rectangle and returns the jpeg data URL | `expected "vi.fn()" to be called with arguments: [ '2d' ]` |

Also added `applies FACE_CROP_PADDING_RATIO when paddingRatio is omitted` so default-padding `= 0` is RED, and `returns null when the crop throws`. TS2345 on `mockReturnValueOnce(null)` fixed by typing `FakeContext | null` (no ts-ignore). Restored GREEN (8 passed).

## E21-15-REV1-04 (high) — fixed

- Status: fixed (already in snapshot; verified by gate).
- Files: `ClusterReviewPanel.test.tsx`, `WorkbenchFindingsPanel.test.tsx`, `ClusterPreview.test.tsx` re-pointed at DurableFaceThumb hops (dedicated / crop / uncropped / missing).
- TEST-15: covered by hop-specific assertions (e.g. zero-extent uses `acx-durable-face-thumb__uncropped`, not FaceThumbnail). Gate 1416/1416 includes those three suites.

## E21-15-REV1-05 (medium) — fixed

- Status: fixed (already in snapshot; verified).
- Files: `js/components/ui/useDurableFaceThumb.ts` — reset status during render via key compare; handlers ignore stale keys.
- TEST-15: drop the `liveDedicatedKey` guard in `onBlobError`.
- RED: `ignores a stale blob-error from the previous dedicated key` — `expected 'crop' to be 'avatar'`. Restored GREEN.

## E21-15-REV1-06 (medium) — fixed

- Status: fixed (already in snapshot; verified).
- Files: `useDurableFaceThumb.ts` `cropKeyFor` includes `normalizedBboxKey`.
- TEST-15: drop bbox from `cropKeyFor`.
- RED: `folds the normalized bbox into cropKey [REV1-06]` — expected `...|10,20,40,50`. Restored GREEN.

## E21-15-REV1-07 (medium) — fixed

- Status: fixed (already in snapshot; verified).
- Files: `IdentityThumbnail.tsx:89` branches on `isDedicatedFaceThumbUrl(identity.thumb_url)`.
- TEST-15: `dedicatedThumbUrl = identity.thumb_url ?? null`.
- RED: `does not paint a non-dedicated attachment thumb_url as a face chip [REV1-07]` — `expected <img> to be null`. Restored GREEN.

## E21-15-REV1-08 (medium) — fixed

- Status: fixed this session (`ea771b9`).
- Files: `js/admin/pages/roster/IdentityThumbnail.tsx`, `js/admin/pages/roster/__tests__/IdentityThumbnail.test.tsx`.
- Why: claimed dedicated blob 404 with no fallback was a quiet `aria-hidden` placeholder (unnamed `<a>` in ClusterDrawerPanel). Fallback `<img>` 404 left a broken glyph because `onError` only cleared dedicated thumbs.
- TEST-15: dedicated-only `onError` (do not `setFallbackFailed`).
- RED: `clears a fallback source img that 404s [REV1-08]` — `expected <img …></img> to be null`. Restored GREEN.

## E21-15-REV1-10 (medium) — fixed

- Status: fixed (already in snapshot; verified).
- Files: `DurableFaceThumb.tsx` error span renders visible `Image failed to load` beside `--error`.
- TEST-15: remove the visible fallback-label text.
- RED: `genuine network failure keeps loud --error` — `Unable to find an element with the text: Image failed to load`. Restored GREEN.

## E21-15-REV1-18 (low) — fixed

- Status: fixed (already in snapshot; verified).
- Files: `_durable-face-thumb.scss`, `_avatar.scss` use `--acx-shadow-inset-danger`; chips use `--acx-thumb-size-sm`. Token defined in `_colors.scss`.
- TEST-15: restore `box-shadow: inset 0 0 0 1px var(--acx-color-danger)` in both files.
- RED: `tokenizes durable/avatar error inset shadow and chip min sizes [REV1-18]` — expected source to contain `box-shadow: var(--acx-shadow-inset-danger)`. Restored GREEN.

## Commits

```
ea771b9 fix(e21-15): name roster thumb after blob or fallback 404 (E21-15-REV1-08)
9fff0a3 fix(e21-15): record canvas crop geometry and catch thrown crops (E21-15-REV1-03)
```
