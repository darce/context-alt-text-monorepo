# E21-15 remote review — correctness and accessibility lens

Reviewed: 89e037cc0ee8cca81a54ffd2c6ce3a53fff9c01c

## Verdict

fail

## Findings

### F1 — high — `WorkbenchFindingsPanel.tsx:157-186`

`useWorkbenchFindings` keeps attachment-only previews (`useWorkbenchFindings.ts:354-356`; test: “keeps a preview whose only imagery is an attachment URL”). `FindingsPreview` never reads `attachmentUrl`. Crop requires `mediaUrl` (`:157-159`). Uncropped fallback is `thumbUrl ?? mediaUrl` (`:186`). Attachment-only + bbox, or attachment-only with no bbox, renders `FindingsPreviewMissing` (“No image”).

Symptom: workbench findings strip shows an empty “No image” chip for a row that has a usable attachment.

Smallest fix: feed `preview` into `DurableFaceThumb` (`thumbUrl`, `attachmentUrl`, `mediaUrl`, `bbox`), or use `usablePreviewUrl(attachmentUrl) ?? usablePreviewUrl(mediaUrl)` for both crop and uncropped hops.

### F2 — medium — `WorkbenchFindingsPanel.tsx:161-170`

Dedicated blob hop is a bare `Avatar` with no error latch and no fall-through. `faceThumbDisplay.ts:205-206` is dedicated-404 → crop; this consumer does not do that.

Symptom: expired `/recognition/face-thumbs/` URL paints Avatar’s error state even when `mediaUrl`/`attachmentUrl` + croppable bbox exist.

Smallest fix: same as F1 — `DurableFaceThumb` already implements the latch + hop.

### F3 — medium — `FaceThumbnail.tsx:108-117` + `_face-thumbnail.scss:41-54`

Terminal crop error is an empty `div` (`aria-label` only). `--error::before` uses the same `--acx-color-data-placeholder` as the background, so there is no visible icon or text (sr-004). `DurableFaceThumb` replaces this with loud copy (`DurableFaceThumb.tsx:74-84`); `FindingsPreview` and other direct `FaceThumbnail` callers do not.

Symptom: a 404 on the crop source is a blank gray square.

Smallest fix: match Avatar — `ImageOff` + visible or `.screen-reader-text` “Image failed to load”.

### F4 — low — `trait-maps-response-fields.php:115-120`

Missing keys / non-JSON / non-object `pixels` correctly return null (`ClusterResponseMapperTest` ~690-788). Present but non-numeric edges still go through `absint` and become `{0,0,0,0}`; negative width/height become a positive croppable box (`absint(-40) === 40`). Roster’s sibling already nulls non-positive extents (`class-roster-entry-projection-repository.php:482-484`).

Symptom: junk numeric strings yield a zero box (client `isCroppableBbox` then skips crop). Sign-flipped extents can crop the wrong region.

Smallest fix: require `is_numeric` on all four edges and `width > 0 && height > 0`; otherwise return null.

## Checked and clean

1. Core hop order holds: dedicated `thumbUrl` (`isDedicatedFaceThumbUrl`) → attachment-then-media + `isCroppableBbox` → uncropped (attachment, media, non-dedicated thumb) → missing. `IdentityThumbnail` is dedicated blob → canvas crop (`isUsableBbox`) → uncropped `sourceUrl` → named error/placeholder. No empty/spinning/wrong-source case on those two paths.
2. Failure latches reset. `useDurableFaceThumb.ts:51-52,93-96` — keyed status; mismatch is `LOAD_STATUS.loading`, not a stale error. `IdentityThumbnail.tsx:91-97` — `thumbFailed` resets on `identity.thumb_url`; `fallbackFailed` resets on `[sourceUrl, cropOwnerId]` (`cropOwnerId` includes `identity_id`).
3. Degenerate geometry is gated on every crop producer in this chain: `isCroppableBbox` / `isUsableBbox` reject non-finite and non-positive extent. `cropFaceFromImage.ts:77-80` clamps a box that is croppable but outside the bitmap. CSS `cropTransformFor` cannot clamp to image bounds (no natural size); callers only reach it after the positive-extent gate.
4. Durable + roster image names hold: real name or “Detected face” / “Reference image” / “Identity from media N”; `alt=""` decorative; missing/error have visible text plus `aria-label`. No filename or UUID leaked. (F3 is the FaceThumbnail-only gap.)
5. Mapper bbox: absent / undecodable / incomplete → null, not a fabricated zero box. (F4 is the remaining `absint` hole.)
6. Display hops use `AVATAR_STATE` / `FACE_THUMB_MODE` / `LOAD_STATUS`. Raw load-status literals remain only inside `FaceThumbnail`’s local `'loading'|'loaded'|'error'` FSM and `Avatar`’s `ImageLoadingStatus` (`'idle'|'loaded'|'error'`) — not scattered avatar-display comparisons.
