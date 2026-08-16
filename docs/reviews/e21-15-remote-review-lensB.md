# E21-15 remote review — test falsifiability lens

Reviewed: 65dbfbd912b531eea682e095a6766be5ad68f013

## Verdict

pass_with_findings

## Findings

### F1 — medium — `WorkbenchFindingsPanel.tsx:186-188`

REV1-15 mutation 4 is real at the collector (`useWorkbenchFindings.test.tsx:398`). `FindingsPreview` never reads `preview.attachmentUrl`. Fallback is `usablePreviewUrl(thumbUrl) ?? usablePreviewUrl(mediaUrl)` (`:186`); empty → `FindingsPreviewMissing` (`:188`). An attachment-only preview that survives the filter still paints “No image”.

Mutation that stays green: leave `collectPreviews` / the attachment filter alone and keep (or restore) this hop. That is the current code. `WorkbenchFindingsPanel.test.tsx:1096-1125` only covers the no-URL missing chip.

Smallest assertion: render the panel with `previews: [{ key, thumbUrl: null, mediaUrl: null, attachmentUrl: ATTACHMENT, bbox: null }]` and expect an `img` (or `DurableFaceThumb`) whose `src` is `ATTACHMENT`, not “No image”.

### F2 — low — `FaceThumbnail.tsx:154`

REV1-13 M1 dropped both `transform` and `transformOrigin: 'top left'`. The new pin (`DurableFaceThumb.test.tsx:204-205`) only matches `translate(...)` and `scale(...)`. `transformOrigin` is the only occurrence in the repo and is never asserted (`FaceThumbnail.test.tsx:54-80` checks `scale(...)` only).

Mutation that stays green: delete `transformOrigin: 'top left'` (origin falls back to center; the bbox no longer fills the frame).

Smallest assertion: `expect(crop.getAttribute('style')).toMatch(/transform-origin:\s*top left/)`.

## Checked and clean

1. All 16 recorded reds match a live assertion the named mutation would break. No fabricated or mis-copied block.
2. REV1-13 M2 covering test (`DurableFaceThumb.test.tsx:168`, `getByAltText('Reference image')`) fails if a zero box is forced into `FaceThumbnail`. REV1-14 M1 (`IdentityThumbnail.test.tsx:126` pending chip needs `attachment_url` in `sourceUrl`). REV1-14 M2 (`:296` — no `setThumbFailed` leaves the dedicated `<img>`). REV1-14 M3 (`:444` / `:1141` — `fallbackSrc = sourceUrl` paints the scene before crop). The PHP note’s `MemberResponseMapperTest` names (`:45`, `:62`) never assert `bbox`; the shared `extract_bbox_pixels` mutation is still caught by `ClusterResponseMapperTest.php:750-751`.
3. One mock-return-only line: `cropFaceFromImage.test.ts:86` (`toBe('data:image/jpeg;base64,crop-record')`) proves the stub ran. Geometry is independently locked at `:101` via a local `expectedSourceRect` oracle, not the mock. No same-source tautology on production values.
4. Canvas / `Image` / `IntersectionObserver` stubs are harnesses (arg spies, construct counts, delayed onload). The `@radix-ui/react-avatar` mock is a pass-through `<img>` that forwards `load`/`error`; it does not invent `data-avatar-state`. IdentityThumbnail `toDataURL` canned URLs discriminate hop (`data:` vs `media_url`), not crop math.
5. `translate(-4.799999999999999px, -19.2px)` is independently derivable from fixture `BBOX {x:10,y:20,width:40,height:50}` and FaceThumbnail default `md=48` (`scale=48/50=0.96`, `tx=4.8-9.6`, `ty=-19.2`). The `4.799999999999999` token is the IEEE remainder — copied from observed `style`, not written as `-4.8`. Still fails if the transform is dropped. Will read as noise on the next geometry change.
6. Highest-value missing assertion is F1 (`WorkbenchFindingsPanel.tsx:186`).
