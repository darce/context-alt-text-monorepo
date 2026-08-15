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
