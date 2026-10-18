# D2-R19-01: boundary test sharding

Date: 2026-09-05. The previous combined suite reached 310 seconds under review contention and exceeded its 300-second deadline. The parity test now discovers every Python unittest ID and registers one Vitest test per ID, with a shared 120-second subprocess deadline and derived 132-second Vitest budget. Discovery uses the existing 55-second short-command deadline and rejects empty or invalid results.

## Verification

All 21 shards passed twice, with two concurrent workers running both repetitions of each shard together. Each subprocess ran `python -m unittest <fully-qualified-test-id>` from this directory, using the runtime-selected Python interpreter. Measurements include process startup. The slowest run was 23.496 seconds, leaving more than five times that duration within the class deadline. These measurements describe this sandbox, not a guarantee for every host.

| RendererBoundaryTests method | Run 1 (s) | Run 2 (s) |
| --- | ---: | ---: |
| test_action_rows_and_duplicate_sections_fail_both_check_paths | 7.314 | 7.309 |
| test_conditional_primary_actions_fail_closed | 0.161 | 0.158 |
| test_declaration_matrix_in_process | 0.226 | 0.228 |
| test_declaration_variants_fail_both_check_paths | 23.496 | 23.478 |
| test_domain_state_rows_fail_both_check_paths | 5.265 | 5.248 |
| test_duplicate_action_states_fail_both_check_paths | 2.596 | 2.616 |
| test_duplicate_retained_contract_cannot_hide_an_unchecked_table | 0.157 | 0.169 |
| test_duplicate_screen_metadata_fails_both_check_paths | 4.557 | 4.493 |
| test_duplicate_screen_states_fail_both_check_paths | 2.647 | 2.603 |
| test_internal_import_error_never_uses_snapshot_fallback | 0.172 | 0.167 |
| test_json_digest_ignores_checkout_line_endings | 0.146 | 0.153 |
| test_markdown_newlines_pass_both_check_paths | 1.181 | 1.175 |
| test_noncanonical_screen_rows_fail_both_check_paths_with_row_text | 5.589 | 5.598 |
| test_only_missing_top_level_canvas_package_permits_fallback | 0.207 | 0.232 |
| test_optional_zone_states_and_empty_extensions_match_both_check_paths | 1.683 | 1.651 |
| test_regeneration_with_omitted_optional_action_fields | 0.686 | 0.680 |
| test_render_restores_source_contract_instead_of_reading_mutated_artifact | 0.148 | 0.150 |
| test_retained_heading_variants_and_zone_rows_fail_both_check_paths | 8.982 | 8.972 |
| test_retained_mutations_cannot_be_blessed_by_normal_regeneration | 0.148 | 0.174 |
| test_retained_table_mutation_fails_both_check_paths | 0.658 | 0.642 |
| test_unrecognized_screen_headings_fail_both_check_paths | 7.866 | 7.851 |

Behavioral regression probe: `node apps/prototype-wp-alt-context/js/admin/__tests__/uxmap-render-parity.fixtures/boundary-sharding-probe.cjs <parity-test-source>`. It executes the registration block with two discovered IDs and verifies separate subprocess invocations, working directories, deadlines, and Vitest budgets. Against the original source it failed with `each discovered mutation needs an independent process: 1 !== 2`; against the changed source it passed.

Full gate attempted from the app directory: `ACX_UXMAP_PYTHON="$(command -v python3)" ./node_modules/.bin/vitest run js/admin/__tests__/uxmap-render-parity.test.ts`. Python resolved to `/usr/bin/python3`. Vitest failed during collection with `Subprocess /usr/bin/python3 failed: spawnSync /usr/bin/python3 EPERM`. No Vitest tests executed. The permitted existing node_modules symlink was used; no dependencies were installed. Direct Python shard results and the Node registration probe do not replace this blocked integration gate.

Local verification commands also included `node /tmp/d2-shard-probe.cjs`, `node /tmp/d2-shard-behavior.cjs /tmp/d2-before.ts` (expected failure), `node /tmp/d2-shard-behavior.cjs apps/prototype-wp-alt-context/js/admin/__tests__/uxmap-render-parity.test.ts`, runtime-selected Python running `/tmp/d2-measure.py`, and `git diff --check`.
