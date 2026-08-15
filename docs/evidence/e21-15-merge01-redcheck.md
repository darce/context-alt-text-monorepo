# E21-15 MERGE-01 red-check
## One unavailable-image literal
- Mutation applied: `imageUnavailable: REPRESENTATIVE_IMAGE_UNAVAILABLE` (imported from faceThumbDisplay) -> `imageUnavailable: __('Representative image unavailable', 'alt-context')` with the import removed
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/admin/pages/workbench/identity-clusters/__tests__/representativeVocabulary.source.test.tsx`
- Verdict: FAILED
- Failing assertion: `expect(matches).toHaveLength(1);`
- After restore: PASSED

## hideMissingLabel parity
- Mutation applied: `const hideMissingClass = hideMissingLabel ? \`${baseClass}--hide-missing-label\` : ''; const classes = [baseClass, stateClass, errorClass, hideMissingClass, className, callerUncropped].filter(Boolean).join(' ');` -> `const classes = [baseClass, stateClass, errorClass, className, callerUncropped].filter(Boolean).join(' ');` (prop left declared)
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/components/ui/__tests__/DurableFaceThumb.test.tsx`
- Verdict: FAILED
- Failing assertion: `expect(container.querySelector('.acx-durable-face-thumb--hide-missing-label')).toBeInTheDocument();`
- After restore: PASSED

## REV1-15 mutation 1
- Mutation applied: `identity_attachment_url: suggestion.identity_attachment_url ?? null,` -> deleted
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/admin/api/recognition/__tests__ js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjection.test.ts`
- Verdict: FAILED
- Failing assertion: `expect(suggestion).toHaveProperty('identity_attachment_url', IDENTITY_ATTACHMENT_URL);`
- After restore: PASSED

## REV1-15 mutation 2
- Mutation applied: `attachment_url: normalizeOptionalUrl(representative.attachment_url ?? null),` -> `attachment_url: null,`
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/admin/api/recognition/__tests__ js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjection.test.ts`
- Verdict: FAILED
- Failing assertion: `expect(mapped).toHaveProperty('attachment_url', ATTACHMENT_URL);`
- After restore: PASSED

## REV1-15 mutation 3
- Mutation applied: ENRICHMENT_SOURCE_FIELDS dropped `['identityAttachmentUrl', 'identity_attachment_url']` and `['representativeAttachmentUrl', 'representative_attachment_url']`
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/admin/api/recognition/__tests__ js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjection.test.ts`
- Verdict: FAILED
- Failing assertion: `expect(projected.enrichment).toEqual({ identityAttachmentUrl: ATTACHMENT_ONLY_URL });`
- After restore: PASSED

## REV1-15 mutation 4 — attachment-only preview survives the filter
- Mutation applied: `(preview) => preview.thumbUrl !== null || preview.mediaUrl !== null || preview.attachmentUrl != null` -> `(preview) => preview.thumbUrl !== null || preview.mediaUrl !== null`
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/admin/pages/workbench/identity-clusters/__tests__/useWorkbenchFindings.test.tsx js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjection.test.ts`
- Verdict: FAILED
- Failing assertion: `expect(assignmentModel.previews.map((preview) => preview.key)).toEqual(['assignment-attach-only']);`
- After restore: PASSED

## REV1-12/REV1-03 mutation M1 — swapping drawImage sx/sy inverts the source rect
- Mutation applied: `ctx.drawImage(image, sx, sy, sWidth, sHeight, dx, dy, destWidth, destHeight);` -> `ctx.drawImage(image, sy, sx, sWidth, sHeight, dx, dy, destWidth, destHeight);`
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/components/ui/__tests__/faceThumbDisplay.test.ts js/components/ui/__tests__/cropFaceFromImage.test.ts`
- Verdict: FAILED
- Failing assertion: `expect({ sx, sy, sWidth, sHeight }).toEqual(expected);`
- After restore: PASSED

## REV1-12/REV1-03 mutation M2 — default paddingRatio 0 drops FACE_CROP_PADDING_RATIO
- Mutation applied: `paddingRatio = FACE_CROP_PADDING_RATIO` -> `paddingRatio = 0`
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/components/ui/__tests__/faceThumbDisplay.test.ts js/components/ui/__tests__/cropFaceFromImage.test.ts`
- Verdict: FAILED
- Failing assertion: `expect({ sx, sy, sWidth, sHeight }).toEqual(expected);`
- After restore: PASSED

## REV1-12/REV1-03 mutation M3 — deleting the isCroppableBbox gate returns uncroppable crops
- Mutation applied: `if (!mediaUrl || !isCroppableBbox(source.bbox)) {` -> `if (!mediaUrl) {`
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/components/ui/__tests__/faceThumbDisplay.test.ts js/components/ui/__tests__/cropFaceFromImage.test.ts`
- Verdict: FAILED
- Failing assertion: `expect(resolveFaceThumbCrop({ attachmentUrl: ATTACHMENT_URL })).toBeNull();`
- After restore: PASSED

## REV1-12/REV1-03 mutation M4 — dropping the mediaUrl ternary arm returns null for media-only sources
- Mutation applied: `nonemptyUrl(source.attachmentUrl) ? source.attachmentUrl : nonemptyUrl(source.mediaUrl) ? source.mediaUrl : null` -> `nonemptyUrl(source.attachmentUrl) ? source.attachmentUrl : null`
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/components/ui/__tests__/faceThumbDisplay.test.ts js/components/ui/__tests__/cropFaceFromImage.test.ts`
- Verdict: FAILED
- Failing assertion: `expect(crop).toEqual({ mediaUrl, bbox: BBOX });`
- After restore: PASSED

## REV1-13 mutation M1 — crop is not actually a crop
- Mutation applied: FaceThumbnail img style dropped `transform: translate(...) scale(...)` and `transformOrigin: 'top left'` so the full source image paints unscaled inside `.acx-face-thumbnail`
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/components/ui/__tests__/DurableFaceThumb.test.tsx`
- Verdict: FAILED
- Already covered by existing test: no
- Failing assertion: `expect(crop.getAttribute('style')).toContain('translate(-4.799999999999999px, -19.2px)');`
- After restore: PASSED

## REV1-13 mutation M2 — a degenerate box becomes a crop
- Mutation applied: DurableFaceThumb forced a FaceThumbnail crop whenever `source.bbox` plus attachment/media URL existed, including `{x:0,y:0,width:0,height:0}`, instead of rejecting the zero-extent box
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/components/ui/__tests__/DurableFaceThumb.test.tsx`
- Verdict: FAILED
- Already covered by existing test: yes (`renders a real uncropped img when mediaUrl has no croppable bbox [REV1-02]`)
- Failing assertion: `const image = screen.getByAltText('Reference image');`
- After restore: PASSED

## REV1-13 mutation M3 — the loaded blob is misreported
- Mutation applied: DurableFaceThumb avatar path `data-avatar-state={display.state}` -> `data-avatar-state={display.state === AVATAR_STATE.real ? AVATAR_STATE.fallbackCrop : display.state}`
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/components/ui/__tests__/DurableFaceThumb.test.tsx`
- Verdict: FAILED
- Already covered by existing test: no
- Failing assertion: `expect(container.querySelector('.acx-durable-face-thumb')).toHaveAttribute('data-avatar-state', 'real');`
- After restore: PASSED

## REV1-14 mutation M1 — dropping attachment_url from the source chain loses crop source
- Mutation applied: `const sourceUrl = mediaMeta?.url ?? identity.attachment_url ?? identity.media_url ?? null;` -> `const sourceUrl = mediaMeta?.url ?? identity.media_url ?? null;`
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/admin/pages/roster/__tests__/IdentityThumbnail.test.tsx`
- Verdict: FAILED
- Already covered by existing test: yes (`does not paint a non-dedicated attachment thumb_url as a face chip [REV1-07]`; also `clears a fallback source img that 404s [REV1-08]`; `crops a non-dedicated attachment thumb_url instead of painting the scene [REV1-07]`)
- Failing assertion: `expect(document.querySelector('[data-face-pending="true"]')).not.toBeNull();`
- After restore: PASSED

## REV1-14 mutation M2 — disabling the blob-failure latch never falls through
- Mutation applied: `if (effectiveThumbUrl) { setThumbFailed(true); return; }` -> `if (effectiveThumbUrl) { return; }`
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/admin/pages/roster/__tests__/IdentityThumbnail.test.tsx`
- Verdict: FAILED
- Already covered by existing test: yes (`names a claimed dedicated blob that 404s with no fallback [REV1-08]`; also `names a wrapping link after a claimed blob 404s [REV1-08]`; `clears a fallback source img that 404s [REV1-08]`; `keeps decorative alt="" unnamed after a claimed blob 404 [REV1-08]`)
- Failing assertion: `expect(document.querySelector('img')).toBeNull();`
- After restore: PASSED

## REV1-14 mutation M3 — fallback source is the full scene instead of the crop
- Mutation applied: `const fallbackSrc = needsCanvasCrop ? croppedSrc : sourceUrl;` -> `const fallbackSrc = sourceUrl;`
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/admin/pages/roster/__tests__/IdentityThumbnail.test.tsx`
- Verdict: FAILED
- Already covered by existing test: yes (`keeps placeholder until crop is ready after intersection [S6-BR-02]`; also `does not paint a non-dedicated attachment thumb_url as a face chip [REV1-07]`; `does not construct Image before the host intersects`)
- Failing assertion: `expect(document.querySelector('img')).toBeNull();`
- After restore: PASSED

## REV1-16 — malformed bbox_json must not fabricate a zero box
- Mutation applied: deleted `if ( ! isset( $pixels['x'], $pixels['y'], $pixels['width'], $pixels['height'] ) ) { return null; }` and restored `absint( $pixels[...] ?? 0 )` zero-box fallback
- Command: `cd apps/prototype-wp-alt-context && ./vendor/bin/phpunit --filter ClusterResponseMapperTest`
- Verdict: FAILED
- Failing assertion: `Failed asserting that Array &0 [ 'x' => 1, 'y' => 2, 'width' => 3, 'height' => 0, ] is null.`
- After restore: PASSED
- map_media_identities / map_cluster_detail: added dedicated test `testMapClusterDetailEmitsBboxOnHappyPathAndNullWhenAbsent`; map_media_identities already covered by `testMapMediaIdentitiesGroupsByMediaId` and `testMapMediaIdentitiesFallsBackToClusterRepresentativeMetadata` in MemberResponseMapperTest (method lives on MemberResponseMapper, not ClusterResponseMapper)

## REV4-02 — malformed bbox yields null, not a fabricated box
- Guards added:
```
		if (
			! is_numeric( $pixels['x'] )
			|| ! is_numeric( $pixels['y'] )
			|| ! is_numeric( $pixels['width'] )
			|| ! is_numeric( $pixels['height'] )
		) {
			return null;
		}

		$width  = (int) $pixels['width'];
		$height = (int) $pixels['height'];
		if ( $width <= 0 || $height <= 0 ) {
			return null;
		}
```
- Cases added:
  - `testMapClusterListEmitsNullBboxWhenEdgeIsNonNumeric` (`width` => `'abc'`)
  - `testMapClusterListEmitsNullBboxWhenExtentsAreNegative` (`width` => `-40` and `height` => `-40`)
  - `testMapClusterListEmitsNullBboxWhenWidthIsZero` (`width` => `0`)
  - `testMapClusterListEmitsIntegerBboxWhenPixelsAreNumericAndPositive` (`{x:10,y:20,width:30,height:40}`)
- Mutation applied: deleted the `is_numeric` check and the positive-extent check (`$width <= 0 || $height <= 0`), restoring the bare `absint` block (`'width' => absint( $pixels['width'] )` / `'height' => absint( $pixels['height'] )`)
- Command: `cd apps/prototype-wp-alt-context && ./vendor/bin/phpunit --filter ClusterResponseMapperTest`
- Verdict: FAILED
- Failing assertion: `Failed asserting that Array &0 [ 'x' => 1, 'y' => 2, 'width' => 0, 'height' => 4, ] is null.`
- After restore: PASSED, 33 tests
- Existing assertions updated for old zero-box behaviour: none

## REV4-04 — crop error state is visible, not colour-only
- Change: Avatar error idiom — `AlertTriangle` + `ImageOff` (both `aria-hidden`) plus visible `.acx-face-thumbnail__error-label` text "Face image unavailable" (`aria-hidden` so `role="img"` + aria-label is not announced twice). Tokens: `--acx-gray-200` background, `--acx-color-warning-border` color/label, `--acx-shadow-inset-danger`. Removed the same-token `::before` disc on `.acx-face-thumbnail--error`.
- Test added: yes — FaceThumbnail error-state test asserts `.acx-face-thumbnail__warning-icon`, `.acx-face-thumbnail__broken-icon`, and `.acx-face-thumbnail__error-label` text "Face image unavailable" (not just the aria-label)
- MUT-B verdict: FAILED

## REV4-05 — transform-origin is pinned
- MUT-A (transformOrigin deleted): FAILED
- Failing assertion: expect(crop.getAttribute('style')).toMatch(/transform-origin:\s*top left/);
- After restore: PASSED

## REV4-01/REV4-03 — findings previews paint attachment-only imagery
- Route taken: DurableFaceThumb — FindingsPreview already feeds thumb/attachment/media + bbox into DurableFaceThumb, so attachment-only URLs reuse the durable hop instead of a one-off in-place img
- Missing-chip decision: kept FindingsPreviewMissing — DurableFaceThumb's missing span is a different surface and would change the pinned chip
- MUT-C verdict: FAILED
- Failing assertion: expect(screen.getByRole('img')).toHaveAttribute('src', attachmentUrl)
- After restore: PASSED

## REV4-06 — uncropped hop announces a reference image, not a face crop
- Prop added: uncroppedAlt?: string;
- Assertions restored: :721 `alt: suggested label on a crop is hedged` LEFT — preview has croppable bbox, hop is FaceThumbnail crop, Face image is correct; :745 `alt: suggested label on an uncropped fallback is hedged` RESTORED — bbox is null so hop is uncropped (`acx-durable-face-thumb__uncropped` / `data-avatar-state="uncropped"`), Reference image is required; :986 `alt: cluster suggested_label from buildWorkbenchFindings is hedged` LEFT — representative has croppable bbox, hop is crop, Face image is correct
- MUT-A verdict: FAILED, failing assertion: expect(screen.getByAltText('Reference image, possibly Ada Lovelace')).toBeInTheDocument();
- MUT-B verdict: FAILED, failing assertion: expect(screen.getByAltText('Reference image, possibly Ada Lovelace'))
- After restore: PASSED
- tsc: EXIT 0

## PHP gate — golden refresh and pre-existing phpcs debt
- Fixtures regenerated:
  - `tests/fixtures/clusters-read/get_cluster_detail_local_projection/response.json` — (a) attachment_url (`"attachment_url":null` on sample_identities)
  - `tests/fixtures/clusters-read/get_cluster_members_local_projection/response.json` — (a) attachment_url (`"attachment_url":null` on members)
  - `tests/fixtures/clusters-read/list_clusters_local_projection/response.json` — (a) attachment_url (`"attachment_url":null` on sample_identities)
  - `tests/fixtures/clusters-read/list_clusters_stale_projection_sync/response.json` — (b) null bbox (`"bbox":{"x":0,"y":0,"width":0,"height":0}` → `"bbox":null` on representative_identity)
  - `tests/fixtures/clusters-read/list_clusters_stale_projection_sync_failed/response.json` — (b) null bbox (`"bbox":{"x":0,"y":0,"width":0,"height":0}` → `"bbox":null` on representative_identity)
  - `tests/fixtures/clusters-read/list_top_unlabeled_local_projection/response.json` — (a) attachment_url (`"attachment_url":"http://example.test/media/101.jpg"` on representatives) and (b) null bbox (`"bbox":{"x":0,"y":0,"width":0,"height":0}` → `"bbox":null`)
- Unclassifiable changes: none (no side-effects fixtures, status codes, totals, or limits moved)
- phpunit: EXIT 0, 1757/8496
- phpcs: EXIT 0
- Suppression used: `$tag = '<script ...></script>'; // phpcs:ignore WordPress.WP.EnqueuedResources.NonEnqueuedScript`
- MUT-1 (positive-extent guard deleted) verdict: PASSED — wrong guard. These characterization rows omit `bbox_json`, so `extract_bbox_pixels` returns at the first guard and never reaches `$width <= 0 || $height <= 0`. Not evidence for these goldens.
- MUT-2 (first guard restored to the fabricated zero box, i.e. main's behaviour) verdict: FAILED
- Failing scenarios: list_clusters_stale_projection_sync, list_clusters_stale_projection_sync_failed, list_top_unlabeled_local_projection
- Failing assertion: Failed asserting that two strings are identical. Expected `"bbox":null`; actual `"bbox":{"x":0,"y":0,"width":0,"height":0}`.
- After restore: PASSED, 26 tests
- What the six goldens pin: missing/empty `bbox_json` maps to `null`, not a fabricated `{0,0,0,0}`. The non-numeric and non-positive-extent guards are covered separately by ClusterResponseMapperTest (REV4-02).

## check-php — phpstan could never run on the gate host
- Root cause: no `tmpDir` in phpstan.neon.dist; sys_get_temp_dir()/phpstan on the gate host is owned by `ubuntu` (0755) and the gate runs as `gate` (uid 1002). phpcs failing first masked it.
- Fix: `tmpDir: .phpstan-cache`
- gitignore entry: `.phpstan-cache/`
- phpstan: EXIT 1, errors found:
  - `src/api/services/class-description-history-service.php:337` Call to function is_string() with non-empty-string will always evaluate to true. (`function.alreadyNarrowedType`)
  - `src/api/services/class-description-history-service.php:348` Call to function is_string() with non-empty-string will always evaluate to true. (`function.alreadyNarrowedType`)
- phpcs: EXIT 0
- `git status --short` after the run: clean
