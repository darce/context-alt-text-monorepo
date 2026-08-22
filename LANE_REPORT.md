## DEMO-UX-1-D-8 — FIXED

canon rows satisfied:

- NAV-13 — one versioned say/don't-say artifact defines preferred terms, avoided forms, outsider definitions, and a rationale for every choice.
- NAV-14 — replacements follow the shipped Workbench/Roster face → face group → person model instead of the backend taxonomy.
- rg-008 — the checker validates the complete JSON shape, enum mode, required fields, uniqueness, safe paths, form ownership, and baseline references before scanning; malformed config exits 2.

what changed (files + why):

- `docs/workbay/contracts/controlled-vocabulary.json`: controlled-vocabulary SSOT beside the repository's other cross-service contracts. Defines cluster → face group/group faces, embedding → face signature or omission, tenant → this site, provenance → where this came from, and outlier → unmatched face, with definitions and non-expert rationales.
- `scripts/check_controlled_vocabulary.py`: scans static string arguments of WordPress `__()`, `_e()`, `_n()`, and `_x()` calls in PHP and direct `@wordpress/i18n` consumers in JS/TS. It excludes tests, fixtures, generated output, dependencies, comments, and untranslated internal strings. New violations print file:line plus the SSOT suggestion and exit 1.
- `scripts/test_check_controlled_vocabulary.py`: executable banned/clean fixtures, plural/context coverage, baseline discrimination, duplicate allowance consumption, and malformed-config coverage.
- `Makefile`: `check-controlled-vocabulary` is invoked by aggregate `check-all`; checker tests are collected by `test-scripts`.
- Gate mode: `baseline`. The 111 path/message/term fingerprints below account for 115 currently reported term violations and warn without breaking CI. New copy hard-fails. To make every violation hard-fail: rewrite/remove the work order below, empty `known_violations`, and set `gate_mode` to `hard_fail`; load validation rejects hard-fail mode while a baseline remains.

RED output (test-first lanes):

```text
$ python3 -m pytest scripts/test_check_controlled_vocabulary.py -q --tb=short
FFFFF                                                                    [100%]
=================================== FAILURES ===================================
_____ test_banned_translatable_fixture_fails_with_location_and_suggestion ______
scripts/test_check_controlled_vocabulary.py:63: in test_banned_translatable_fixture_fails_with_location_and_suggestion
    assert result.returncode == 1
E   assert 2 == 1
E    + where 2 = CompletedProcess(... stderr="/usr/bin/python3: can't open file '/home/ubuntu/w/dux-vocab/scripts/check_controlled_vocabulary.py': [Errno 2] No such file or directory\n").returncode
_________ test_clean_fixture_and_non_translatable_internal_terms_pass __________
scripts/test_check_controlled_vocabulary.py:82: in test_clean_fixture_and_non_translatable_internal_terms_pass
    assert result.returncode == 0, result.stdout + result.stderr
E   AssertionError: /usr/bin/python3: can't open file '/home/ubuntu/w/dux-vocab/scripts/check_controlled_vocabulary.py': [Errno 2] No such file or directory
__________ test_plural_and_context_translation_arguments_are_scanned ___________
scripts/test_check_controlled_vocabulary.py:98: in test_plural_and_context_translation_arguments_are_scanned
    assert result.returncode == 1
E   assert 2 == 1
________ test_tracked_baseline_violation_warns_but_new_violation_fails _________
scripts/test_check_controlled_vocabulary.py:130: in test_tracked_baseline_violation_warns_but_new_violation_fails
    assert baseline.returncode == 0, baseline.stdout + baseline.stderr
E   AssertionError: /usr/bin/python3: can't open file '/home/ubuntu/w/dux-vocab/scripts/check_controlled_vocabulary.py': [Errno 2] No such file or directory
________________ test_malformed_vocabulary_fails_closed_at_load ________________
scripts/test_check_controlled_vocabulary.py:143: in test_malformed_vocabulary_fails_closed_at_load
    assert "terms[0].rationale" in result.stderr
E   assert 'terms[0].rationale' in "/usr/bin/python3: can't open file '/home/ubuntu/w/dux-vocab/scripts/check_controlled_vocabulary.py': [Errno 2] No such file or directory\n"
=========================== short test summary info ============================
FAILED scripts/test_check_controlled_vocabulary.py::test_banned_translatable_fixture_fails_with_location_and_suggestion
FAILED scripts/test_check_controlled_vocabulary.py::test_clean_fixture_and_non_translatable_internal_terms_pass
FAILED scripts/test_check_controlled_vocabulary.py::test_plural_and_context_translation_arguments_are_scanned
FAILED scripts/test_check_controlled_vocabulary.py::test_tracked_baseline_violation_warns_but_new_violation_fails
FAILED scripts/test_check_controlled_vocabulary.py::test_malformed_vocabulary_fails_closed_at_load
5 failed in 0.22s
```

Discrimination follow-up caught a duplicate-baseline accounting bug before correction:

```text
$ python3 -m pytest scripts/test_check_controlled_vocabulary.py::test_baseline_allowance_is_consumed_across_duplicate_strings -q --tb=short
F                                                                        [100%]
E   assert 0 == 1
1 failed in 0.15s
```

GREEN output:

```text
$ python3 -m pytest scripts/test_check_controlled_vocabulary.py -vv --tb=short
collected 6 items
test_banned_translatable_fixture_fails_with_location_and_suggestion PASSED
test_clean_fixture_and_non_translatable_internal_terms_pass PASSED
test_plural_and_context_translation_arguments_are_scanned PASSED
test_tracked_baseline_violation_warns_but_new_violation_fails PASSED
test_baseline_allowance_is_consumed_across_duplicate_strings PASSED
test_malformed_vocabulary_fails_closed_at_load PASSED
============================== 6 passed in 0.50s ===============================

$ make check-controlled-vocabulary
No new controlled-vocabulary violations (115 known violation(s) remain).
```

Current violation work order (one row per translated string/term; repeated words in one string are counted in the SSOT):

```text
KNOWN apps/prototype-wp-alt-context/js/admin/hooks/clusterAutoRetry.ts:26: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Clustering queued — starting in %ds'
KNOWN apps/prototype-wp-alt-context/js/admin/hooks/clusterAutoRetry.ts:29: don't say 'cluster' (2 occurrences); say 'face group (noun) / group faces (verb)'. String: 'Clustering failed after rate-limit retries. Use Retry clustering to try again.'
KNOWN apps/prototype-wp-alt-context/js/admin/hooks/useJobStateMachineMutations.ts:106: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Clustering failed. Please try again.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:166: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Clusters that have been matched to a person.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:175: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'New clusters waiting for your review and labeling.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/DescribeRunApplyView.tsx:107: don't say 'provenance'; say 'where this came from'. String: '%d could not finish (alt may already be saved; provenance incomplete).'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/DescriptionHistoryPage.tsx:329: don't say 'provenance'; say 'where this came from'. String: 'Review generated alt text, provenance, and human corrections in one workspace.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/RetentionPage.tsx:143: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Export clusters, members, detection metadata, and representative details as portable JSON.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/RetentionPage.tsx:150: don't say 'embedding'; say 'face signature (when essential) / omit the implementation detail (otherwise)'. String: 'Raw embedding vectors are excluded from exports.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/RetentionPage.tsx:164: don't say 'tenant'; say 'this site'. String: 'Purge permanently deletes disposed state or all machine-derived tenant data from the backend.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/RetentionPage.tsx:195: don't say 'tenant'; say 'this site'. String: 'Restore tenant state from a previously exported JSON file. The import validates schema compatibility and records a lifecycle audit event.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/RetentionPage.tsx:200: don't say 'embedding'; say 'face signature (when essential) / omit the implementation detail (otherwise)'. String: 'Raw embedding vectors are not included in exports and will not be restored.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/dashboard/DashboardSyncHealthSection.tsx:72: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Mirror is out of sync with the backend — %1$d stale clusters, %2$d failed sync events.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/dashboard/GuidanceCard.tsx:42: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: '%d person has no assigned clusters.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/dashboard/GuidanceCard.tsx:43: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: '%d persons have no assigned clusters.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/dashboard/OrientationCard.tsx:31: don't say 'embedding'; say 'face signature (when essential) / omit the implementation detail (otherwise)'. String: 'Analyze your library to detect faces and extract mathematical identities (embeddings).'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/dashboard/OrientationCard.tsx:47: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: '2. Cluster Faces'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/dashboard/OrientationCard.tsx:50: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Automatically group similar faces into "Clusters" to review many identities at once.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/dashboard/OrientationCard.tsx:69: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Name your clusters to automatically populate alt text across your entire media library.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/retention/RetentionDialogs.tsx:57: don't say 'tenant'; say 'this site'. String: 'Export tenant data'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/retention/RetentionDialogs.tsx:60: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'This export includes clusters, members, detection metadata, and representative details. Raw embedding vectors are excluded.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/retention/RetentionDialogs.tsx:60: don't say 'embedding'; say 'face signature (when essential) / omit the implementation detail (otherwise)'. String: 'This export includes clusters, members, detection metadata, and representative details. Raw embedding vectors are excluded.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/retention/RetentionDialogs.tsx:141: don't say 'tenant'; say 'this site'. String: 'Purge tenant data'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/retention/RetentionDialogs.tsx:229: don't say 'tenant'; say 'this site'. String: 'Import tenant data'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/retention/useRetentionPageState.ts:17: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Keep embeddings and clustering state until an operator explicitly changes policy.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/retention/useRetentionPageState.ts:17: don't say 'embedding'; say 'face signature (when essential) / omit the implementation detail (otherwise)'. String: 'Keep embeddings and clustering state until an operator explicitly changes policy.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/retention/useRetentionPageState.ts:185: don't say 'tenant'; say 'this site'. String: 'Tenant export downloaded.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/retention/useRetentionPageState.ts:195: don't say 'tenant'; say 'this site'. String: 'Tenant purge completed.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/retention/useRetentionPageState.ts:197: don't say 'tenant'; say 'this site'. String: 'Unable to purge tenant data.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/settings/SettingsForm.tsx:256: don't say 'tenant'; say 'this site'. String: 'Tenant identity'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/settings/SettingsForm.tsx:259: don't say 'tenant'; say 'this site'. String: 'Tenant ID'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/settings/TestConnectionBannerView.tsx:33: don't say 'tenant'; say 'this site'. String: 'Persisted tenant'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/settings/TestConnectionBannerView.tsx:35: don't say 'tenant'; say 'this site'. String: 'API key tenant'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/settings/TestConnectionBannerView.tsx:48: don't say 'tenant'; say 'this site'. String: 'Adopting tenant identity…'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/settings/TestConnectionBannerView.tsx:49: don't say 'tenant'; say 'this site'. String: 'Adopt API key tenant'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/settings/settingsConstants.ts:71: don't say 'tenant'; say 'this site'. String: 'Not paired yet — check the connection to pair this tenant'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/settings/testConnectionBanner.ts:53: don't say 'tenant'; say 'this site'. String: 'Connection successful, but tenant pairing failed.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/settings/testConnectionBanner.ts:105: don't say 'tenant'; say 'this site'. String: 'Tenant mismatch.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/settings/testConnectionBanner.ts:107: don't say 'tenant' (2 occurrences); say 'this site'. String: 'The API key belongs to a different site. Adopt the key’s tenant to pair this site, or confirm the key was issued for this WordPress tenant.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/settings/testConnectionBanner.ts:116: don't say 'tenant'; say 'this site'. String: 'Tenant identity conflict.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/settings/testConnectionBanner.ts:118: don't say 'tenant'; say 'this site'. String: 'The API key is bound to a different tenant than this site. Confirm adoption before re-keying local data.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/AdvancedDrawer.tsx:79: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Job history, clustering, and recovery controls for when a scan needs follow-up.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/DeadLetterPanel.tsx:20: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Cluster label update'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/DeadLetterPanel.tsx:21: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Cluster dismiss'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/DeadLetterPanel.tsx:22: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Cluster undismiss'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/DeadLetterPanel.tsx:24: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Cluster person bind'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/DeadLetterPanel.tsx:25: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Cluster person unbind'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/DeadLetterPanel.tsx:29: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Cluster merge'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/DeadLetterPanel.tsx:30: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Cluster merge revert'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/DeadLetterPanel.tsx:31: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Assign outlier to cluster'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/DeadLetterPanel.tsx:31: don't say 'outlier'; say 'unmatched face'. String: 'Assign outlier to cluster'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/DeadLetterPanel.tsx:32: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Create cluster for identity'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/JobPipelineContext.tsx:127: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Created %d clusters for %d identities.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/JobTimeline.tsx:60: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: '1 cluster created'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/JobTimeline.tsx:61: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: '%d clusters created'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaAnalyzeCta.tsx:76: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Clustering identities…'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/Panels.tsx:311: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Retry clustering'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/Panels.tsx:373: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Clustering faces…'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/Panels.tsx:373: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Cluster the latest job results'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/Panels.tsx:390: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Clusters created: %d'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/Panels.tsx:403: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Clustering progress'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/WorkbenchTwoPaneLayout.tsx:357: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Recognition and cluster controls will appear here. Run recognition when media is ready.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/confirmTabCopy.ts:9: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'What does clustering do?'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/confirmTabCopy.ts:16: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Clustering groups similar faces found during a scan so you can name a whole group at once instead of labeling every photo.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/conflict-inbox/conflictInboxUtils.ts:6: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Curated cluster deleted remotely'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/conflict-inbox/conflictInboxUtils.ts:8: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Member moved to another cluster remotely'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/conflict-inbox/conflictInboxUtils.ts:137: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Restore local curation by re-sending every affected curated cluster and member to the backend? Local data is preserved.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/conflict-inbox/conflictInboxUtils.ts:155: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Accepting the machine version deletes the curated cluster and %d attached member rows still linked to it.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/conflict-inbox/conflictInboxUtils.ts:161: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Accepting the machine version deletes the curated cluster and all member rows still attached to it.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/conflict-inbox/conflictInboxUtils.ts:173: don't say 'cluster' (2 occurrences); say 'face group (noun) / group faces (verb)'. String: 'Accepting the machine version removes the temporary restored cluster, reassigns the listed members back to the machine target cluster, and discards the local revert operation.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/conflict-inbox/conflictInboxUtils.ts:179: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Accepting the machine version resets all curated cluster fields to backend state, including label, person assignment, and dismissal state.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/conflict-inbox/conflictInboxUtils.ts:191: don't say 'cluster' (2 occurrences); say 'face group (noun) / group faces (verb)'. String: 'Accepting the machine version moves this identity back to the backend-selected cluster, removes the locally created cluster, and discards the local topology operation.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/conflict-inbox/conflictInboxUtils.ts:197: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Accepting the machine version restores the member to the backend-selected cluster and discards the local topology operation.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/conflict-inbox/conflictInboxUtils.ts:244: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Accepting the machine version removes this cluster from the local projection.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/conflict-inbox/conflictInboxUtils.ts:257: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Accepting the machine version reassigns the member to the machine cluster and clears curation.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/conflict-inbox/conflictInboxUtils.ts:284: don't say 'cluster' (2 occurrences); say 'face group (noun) / group faces (verb)'. String: 'Accepting the machine version removes the temporary restored cluster and moves the listed members back into the machine target cluster.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/conflict-inbox/conflictInboxUtils.ts:297: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Accepting the machine version resets the cluster to backend state and clears local curation guards.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/conflict-inbox/conflictInboxUtils.ts:314: don't say 'cluster' (2 occurrences); say 'face group (noun) / group faces (verb)'. String: 'Accepting the machine version restores the member to the backend-selected cluster and removes the locally created cluster.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/conflict-inbox/conflictInboxUtils.ts:327: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Accepting the machine version restores the member to the backend-selected cluster and clears local curation on that assignment.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/AnchorSelectionModal.tsx:61: don't say 'cluster' (2 occurrences); say 'face group (noun) / group faces (verb)'. String: 'Choose the face that should keep this cluster label. Other faces will move to a new cluster.'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/DebugMetricsPanel.tsx:120: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Clustering'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useClusterActionMutations.ts:225: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Cannot pin representative: no cluster ID'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useClusterConfirmDialog.ts:74: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'this cluster'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useClusterConfirmDialog.ts:81: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Merge this cluster into existing "%s"?'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useClusterLabelMutations.ts:113: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Cannot merge: no cluster ID'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/phasePresentation.ts:68: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Clustering progress'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/phasePresentation.ts:94: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Clustering %d/%d identities…'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/phasePresentation.ts:95: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Clustering faces…'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/syncVocabulary.ts:53: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Clustering…'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/syncVocabulary.ts:60: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Service connected — no clusters yet'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/syncVocabulary.ts:82: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Clustering complete'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/syncVocabulary.ts:83: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Clustering failed'
KNOWN apps/prototype-wp-alt-context/js/admin/pages/workbench/syncVocabulary.ts:88: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Clustering'
KNOWN apps/prototype-wp-alt-context/src/api/class-api.php:521: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Could not resolve person UUID for cluster assignment.'
KNOWN apps/prototype-wp-alt-context/src/api/class-api.php:572: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Could not update cluster assignment.'
KNOWN apps/prototype-wp-alt-context/src/api/class-api.php:584: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Could not update cluster revision.'
KNOWN apps/prototype-wp-alt-context/src/api/class-api.php:643: don't say 'tenant'; say 'this site'. String: 'Tenant identity is unavailable.'
KNOWN apps/prototype-wp-alt-context/src/api/class-api.php:739: don't say 'tenant'; say 'this site'. String: 'Tenant identity is unavailable.'
KNOWN apps/prototype-wp-alt-context/src/api/class-api.php:802: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Could not sync bound cluster labels.'
KNOWN apps/prototype-wp-alt-context/src/api/class-api.php:862: don't say 'tenant'; say 'this site'. String: 'Tenant identity is unavailable.'
KNOWN apps/prototype-wp-alt-context/src/api/class-api.php:884: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Could not load clusters for person.'
KNOWN apps/prototype-wp-alt-context/src/api/class-api.php:896: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Could not dissociate person from clusters.'
KNOWN apps/prototype-wp-alt-context/src/api/class-api.php:914: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Could not queue cluster unbind replay operation.'
KNOWN apps/prototype-wp-alt-context/src/api/class-api.php:928: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Could not queue cluster label-clear replay operation.'
KNOWN apps/prototype-wp-alt-context/src/api/services/class-cluster-person-bind-service.php:25: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Could not resolve person UUID for cluster assignment.'
KNOWN apps/prototype-wp-alt-context/src/api/services/class-cluster-person-bind-service.php:39: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Could not resolve person UUID for cluster assignment.'
KNOWN apps/prototype-wp-alt-context/src/api/services/class-cluster-person-bind-service.php:112: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Could not update cluster assignment.'
KNOWN apps/prototype-wp-alt-context/src/api/services/class-cluster-person-bind-service.php:123: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Could not update cluster revision.'
KNOWN apps/prototype-wp-alt-context/src/api/services/class-person-resolution-service.php:79: don't say 'tenant'; say 'this site'. String: 'Tenant identity is unavailable.'
KNOWN apps/prototype-wp-alt-context/src/api/services/class-person-resolution-service.php:113: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Could not create person for cluster assignment.'
KNOWN apps/prototype-wp-alt-context/src/api/services/class-person-resolution-service.php:122: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Could not create person for cluster assignment.'
KNOWN apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php:179: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Alt Context cannot repair unlabeled clusters because tenant identity is unavailable. Configure the tenant, then run `wp acx bind-unbound-labels`.'
KNOWN apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php:179: don't say 'tenant' (2 occurrences); say 'this site'. String: 'Alt Context cannot repair unlabeled clusters because tenant identity is unavailable. Configure the tenant, then run `wp acx bind-unbound-labels`.'
KNOWN apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php:181: don't say 'cluster'; say 'face group (noun) / group faces (verb)'. String: 'Alt Context is still repairing unlabeled clusters. If this persists, run `wp acx bind-unbound-labels`.'
KNOWN apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php:282: don't say 'tenant'; say 'this site'. String: 'Tenant identity is unavailable.'
```

residual risk / what a reviewer should attack:

- Static literal extraction intentionally skips dynamically computed translation arguments; review whether the project permits those and add an AST-backed rule if it does.
- Content-based baseline fingerprints tolerate line movement, but the same grandfathered message can move within its existing file. Occurrence counts prevent extra duplicate copies from consuming the same allowance.
- The broad `make test-scripts` integration command currently fails before collection with `ERROR: file or directory not found: scripts/hooks`; that directory is absent from this lane checkout and outside this lane's ownership. Focused checker tests, bytecode compilation, `git diff --check`, and the wired Make target pass.
