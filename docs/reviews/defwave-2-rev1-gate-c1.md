VERDICT: REVISE
POR: {"file_count":267,"line_count":22855,"md5":"95253c630a3e6e0037ab936ee5cd2592","sample_lines":{"41":"-from recognition.interface_adapters.http.deps.portal_composition import install_portal_composition","173":"         mc_check, cache_dir, model_name = await _model_probe()"}}
## Findings
- M-1 (MEDIUM): apps/prototype-wp-alt-context/js/admin/hooks/usePersonMerge.ts:11507 The per-scope undo key has no release-wide expiry sweep. Failure: merging, navigating away before the 24-hour timer, then repeating leaves each expired key in localStorage because its ephemeral scope is never read again; enough merges can exhaust browser storage. Canon: RES-07.
## Coverage
- `apps/prototype-wp-alt-context/alt-context.php` patch lines 10605-10617: plugin version metadata.
- `apps/prototype-wp-alt-context/js/admin/__tests__/uxmap-render-parity.fixtures/boundary-sharding-probe.cjs` patch lines 10618-10627: fixture import additions.
- `apps/prototype-wp-alt-context/js/admin/__tests__/uxmap-render-parity.fixtures/generate-declaration-emphasis.mjs` patch lines 10628-10639: fixture URL import.
- `apps/prototype-wp-alt-context/js/admin/api/generated/__tests__/dw2-rosterentr-1.test.ts` patch lines 10640-10700: representative quality selection and identity-count fallback assertions.
- `apps/prototype-wp-alt-context/js/admin/api/generated/roster-entry.ts` patch lines 10701-10732: representative identity projection fields and cluster metadata.
- `apps/prototype-wp-alt-context/js/admin/api/recognition/__tests__/dw2-clusterres-1.test.ts` patch lines 10733-10792: persisted cluster export-field response assertion.
- `apps/prototype-wp-alt-context/js/admin/api/recognition/identityQueriesApi.ts` patch lines 10793-10805: suggestion batch-size constant.
- `apps/prototype-wp-alt-context/js/admin/api/recognition/types/cluster.ts` patch lines 10806-10835: optional cluster projection fields.
- `apps/prototype-wp-alt-context/js/admin/guidedPrototype/dw2-livedescri-1.test.ts` patch lines 10836-10979: first-poll deadline, duplicate submit, transient poll, and stranded-run assertions.
- `apps/prototype-wp-alt-context/js/admin/guidedPrototype/liveDescription.ts` patch lines 10980-11016: first poll disclosure recalculates the deadline before clock advancement.
- `apps/prototype-wp-alt-context/js/admin/guidedPrototype/useGuidedLiveDescription.ts` patch lines 11017-11113: duplicate request guard and stranded accepted-run cleanup.
- `apps/prototype-wp-alt-context/js/admin/hooks/__tests__/dw2-usebulkdes-1.test.tsx` patch lines 11114-11299: unreadable media exposure and recovery notice wiring assertions.
- `apps/prototype-wp-alt-context/js/admin/hooks/useBulkDescribe.ts` patch lines 11300-11353: successful submit exposes unreadable media ids.
- `apps/prototype-wp-alt-context/js/admin/hooks/useDescribeRunProgress.ts` patch lines 11354-11439: bounded transient poll classification and escalation threshold.
- `apps/prototype-wp-alt-context/js/admin/hooks/usePersonMerge.ts` patch lines 11440-11568: scoped token persistence, expiry handling, and undo invalidation; see M-1.
- `apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx` patch lines 11569-11582: `s` search parameter disables the default workspace route.
- `apps/prototype-wp-alt-context/js/admin/pages/__tests__/dw2-rosterpage-1.test.tsx` patch lines 11583-11687: active catalogue search assertion.
- `apps/prototype-wp-alt-context/js/admin/pages/roster/RosterEntriesSection.tsx` patch lines 11688-11866: retained undo flow, retryable-error dismissal gate, and token-expiry UI.
