VERDICT: REVISE
POR: {"file_count":267,"line_count":22855,"md5":"95253c630a3e6e0037ab936ee5cd2592","sample_lines":{"41":"-from recognition.interface_adapters.http.deps.portal_composition import install_portal_composition","173":"         mc_check, cache_dir, model_name = await _model_probe()"}}
## Findings
- H-1 (HIGH): apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useInlineSuggestionBatch.ts:13391 A failed chunk is converted to null and an otherwise successful query returns without a partial-error state. Failure: 201 IDs with one rejected 100-ID chunk and two successful chunks -> React Query resolves with missing matches for that chunk, so the UI presents a clean no-suggestion result. Canon: RLSE-05.
- M-1 (MEDIUM): apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useInlineSuggestionBatch.ts:13384 Chunk requests are launched together with Promise.all and have no concurrency cap. Failure: a large catalogue with N identity IDs -> ceil(N/100) simultaneous GETs with no bound on pending work. Canon: RES-14.
- M-2 (MEDIUM): apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx:12605 useIsMutating counts every mutation in the shared query client, so unrelated work sets the GPU status to run-pending. Failure: an unrelated mutation is pending while the GPU service is idle -> GpuTierStatus suppresses idle lifecycle-reason detail. Canon: RLSE-04.
- L-1 (LOW): apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx:12643 The changed tests do not assert that returned unreadable media IDs render. Failure: the list is removed or stops receiving those IDs -> every changed test stays green while skipped attachments remain undisclosed. Canon: TEST-15.
- L-2 (LOW): apps/prototype-wp-alt-context/js/admin/pages/roster/RosterEntriesTable.tsx:11887 The changed roster tests do not exercise the new representative-quality ordering. Failure: an entry whose top quality conflicts with identity_count regresses to count ranking -> both changed roster tests stay green. Canon: TEST-15.
## Coverage
- `apps/prototype-wp-alt-context/js/admin/pages/roster/RosterEntriesTable.tsx` patch lines 11867-11910: checked representative-quality selection, fallback, and tie ordering.
- `apps/prototype-wp-alt-context/js/admin/pages/roster/__tests__/dw2-gpuflow1re-1.test.tsx` patch lines 11911-12064: skimmed token retention and roster-flow regression; no representative-quality assertion.
- `apps/prototype-wp-alt-context/js/admin/pages/roster/__tests__/dw2-rosterentr-4.test.tsx` patch lines 12065-12173: skimmed retryable undo dismissal and reconciliation behavior.
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/DeadLetterPanel.tsx` patch lines 12174-12316: checked failed-row paging, fetch failure handling, and discard result counts.
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/GpuTierStatus.tsx` patch lines 12317-12484: checked idle lifecycle reason, operation wait details, and accessible description.
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaAltSuggest.tsx` patch lines 12485-12575: checked frozen mark direction across prop changes and busy accessible labels.
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx` patch lines 12576-12664: checked GPU mutation inputs and unreadable-media result rendering.
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/dw2-deadletter-1.test.tsx` patch lines 12665-12819: skimmed later-page eligibility and discard invocation.
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/dw2-mediaaltsu-1.test.tsx` patch lines 12820-12898: skimmed frozen unmark direction and busy label assertions.
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/dw2-syncpresen-1.test.ts` patch lines 12899-12960: skimmed preservation of base actions and badge links under a breach overlay.
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/IdentityClusterItem.tsx` patch lines 12961-13004: checked auto-label prompt and representative/fallback split thumbnails.
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/dw2-clusterlab-1.test.tsx` patch lines 13005-13080: skimmed timeout lookup refusal to rename or create.
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/dw2-identitycl-1.test.tsx` patch lines 13081-13316: skimmed chunking, successful-chunk retention, auto-label prompt, and split thumbnails.
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/clusterLabelLookup.ts` patch lines 13317-13338: checked cancellation classification and fail-closed lookup error.
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useInlineSuggestionBatch.ts` patch lines 13339-13420: checked chunk formation, concurrency, partial failure handling, and cache seeding.
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/utils.ts` patch lines 13421-13442: checked auto-labeled identity selection for suggestion lookup.
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/syncPresentation.ts` patch lines 13443-13459: checked reclaimer overlay retention of base action and badge link.
- `apps/prototype-wp-alt-context/js/components/ui/__tests__/FaceThumbnail.test.tsx` patch lines 13460-13479: skimmed loading-state probe syntax change.
- `apps/prototype-wp-alt-context/package-lock.json` patch lines 13480-13498: skimmed package version consistency.
- `apps/prototype-wp-alt-context/package.json` patch lines 13499-13510: skimmed package version and script metadata.
