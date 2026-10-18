# TAUDIT-06 source-parsing test census (Python)

The census covers tests under `apps/prototype-description-service` and `scripts` that read, tokenize, inspect, or AST-parse code-like source (`.py`, `.sh`, `.php`, `.ts`, `.tsx`, `.mk`, `Makefile`, and deployment recipes) and then assert text or syntax. Rows are grouped by test directory. Fixture/output reads and tests that execute the public interface without inspecting code source are omitted.

## `apps/prototype-description-service/recognition/tests/unit`

| ID | path | lines | what it parses | verdict | one-line reason |
|---|---|---:|---|---|---|
| R01 | `apps/prototype-description-service/recognition/tests/unit/test_no_face_extra_strings.py` | 128–144 | Repository files scanned as text for deprecated install-extra strings | convert-to-lint | This is a repository-wide banned-token rule suited to a named lint check. |
| R02 | `apps/prototype-description-service/recognition/tests/unit/test_fir23_embedding_model_read_paths.py` | 317–319 | `001_identity_schema.py` migration source for SQL fragments | rewrite-behavioral | Apply the migration and assert the resulting materialized-view behavior. |
| R03 | `apps/prototype-description-service/recognition/tests/unit/test_representative_selector.py` | 113–119 | `RepresentativeSelector` module source/import lines | convert-to-lint | The downward-only import boundary is a static dependency rule. |
| R04 | `apps/prototype-description-service/recognition/tests/unit/test_job_status_enum_adoption.py` | 44–48, 70–80 | Production Python files for line patterns and hard-coded enum lists | convert-to-lint | Ban legacy status spellings through an explicit source rule. |
| R05 | `apps/prototype-description-service/recognition/tests/unit/test_adapter_surface_inventory.py` | 32, 144–169 | Application `.py` files with text search and AST visitor | convert-to-lint | Adapter reference and call-site allowlists are static architecture rules. |
| R06 | `apps/prototype-description-service/recognition/tests/unit/test_scan_worker_correlation.py` | 193–197 | `scan_worker._main` via `inspect.getsource` | rewrite-behavioral | Invoke the worker entry path with logging configured and assert emitted records. |
| R07 | `apps/prototype-description-service/recognition/tests/unit/test_fir_final_postmerge_observability_contracts.py` | 159–165, 201–206, 461–470, 768–790 | Adapter, runtime factory, and worker Python source; worker `_main` body | rewrite-behavioral | Assert metrics wiring through constructed objects and observable worker startup. |
| R08 | `apps/prototype-description-service/recognition/tests/unit/test_no_raw_secret_reads.py` | 59, 97–102, 136–161 | Production Python tree parsed with AST for environment-secret reads | convert-to-lint | The forbidden secret-read pattern is a static policy best maintained as lint. |
| R09 | `apps/prototype-description-service/recognition/tests/unit/test_fir_release_gates.py` | 138–152, 232, 703–721 | Dockerfile and entrypoint text for install, signal, and stage rules | convert-to-lint | These build and shell source invariants should be named static checks. |
| R10 | `apps/prototype-description-service/recognition/tests/unit/test_fir2_br_postmerge_contracts.py` | 139–151, 176–180 | Migration and settings module source for embedding-dimension literals | rewrite-behavioral | Run the migration/settings path and inspect the resolved schema dimension. |
| R11 | `apps/prototype-description-service/recognition/tests/unit/test_firdv3_auraface_space_contract.py` | 157–165 | `provenance.py` source for preprocessing and historical markers | rewrite-behavioral | Verify imported provenance values and activation behavior without matching source spelling. |
| R12 | `apps/prototype-description-service/recognition/tests/unit/test_merge_candidates.py` | 689–696 | Merge-candidates router `.py` source for thresholds and helper names | rewrite-behavioral | Exercise the public route with candidate scores around each threshold. |
| R13 | `apps/prototype-description-service/recognition/tests/unit/test_auraface_alignment_measurement.py` | 239–243, 404–405, 450–452 | Provenance, generator, and aligner module source | rewrite-behavioral | Assert metadata and alignment results through the imported implementations. |
| R14 | `apps/prototype-description-service/recognition/tests/unit/test_firdv3_s1b_readiness_contract.py` | 1053–1058 | `activation.py` source for forbidden upward imports | convert-to-lint | The infrastructure dependency direction is a static import-boundary rule. |

## `apps/prototype-description-service/recognition/tests/schema`

| ID | path | lines | what it parses | verdict | one-line reason |
|---|---|---:|---|---|---|
| R15 | `apps/prototype-description-service/recognition/tests/schema/test_identity_schema_heal_fakeop.py` | 197–198 | `MIGRATION.ensure_matview` source for operation ordering | rewrite-behavioral | Verify the healed schema and grant state through migration operations. |
| R16 | `apps/prototype-description-service/recognition/tests/schema/test_schema_truth_consistency.py` | 132–137, 348, 433, 472 | Migration and verifier functions via `inspect.getsource` | rewrite-behavioral | Assert agreement by feeding schema fixtures through the migration and verifier APIs. |
| R17 | `apps/prototype-description-service/recognition/tests/schema/test_identity_schema_heal_pg.py` | 387, 480 | A test function and migration function source | rewrite-behavioral | Remove the self-source assertion and prove the refusal/heal result through PostgreSQL fixtures. |

## `apps/prototype-description-service/recognition/tests/api`

| ID | path | lines | what it parses | verdict | one-line reason |
|---|---|---:|---|---|---|
| R20 | `apps/prototype-description-service/recognition/tests/api/test_health_probes.py` | 744–745, 1024 | Dockerfile and entrypoint source text for packaging/probe checks | convert-to-lint | Package and startup declarations are static contracts suited to a focused checker. |
| R21 | `apps/prototype-description-service/recognition/tests/api/test_router_error_boundary_contract.py` | 68–71, 104, 121–159 | Router source parsed for exception handlers and referenced error details | rewrite-behavioral | Send requests through the routers and assert status, payload, and error exposure. |
| R22 | `apps/prototype-description-service/recognition/tests/api/test_retention_api.py` | 892–893 | `TenantExportService.export_tenant_data` source AST | rewrite-behavioral | Assert the returned export payload through the service contract. |
| R23 | `apps/prototype-description-service/recognition/tests/api/test_admin_mount.py` | 187–191 | Admin console module source for mount/wiring text | rewrite-behavioral | Inspect the mounted FastAPI routes and issue a request to the admin surface. |

## `apps/prototype-description-service/recognition/tests/scripts`

| ID | path | lines | what it parses | verdict | one-line reason |
|---|---|---:|---|---|---|
| R18 | `apps/prototype-description-service/recognition/tests/scripts/test_verify_identity_schema.py` | 747–748 | Verifier and migration function source | rewrite-behavioral | Feed schema states to both public collectors and compare their observed results. |
| R24 | `apps/prototype-description-service/recognition/tests/scripts/test_provision_demo.py` | 211–220 | Makefile recipe text for demo provisioning | rewrite-behavioral | Run the target with stub commands and assert the invoked operations. |

## `apps/prototype-description-service/recognition/tests/deploy`

| ID | path | lines | what it parses | verdict | one-line reason |
|---|---|---:|---|---|---|
| R19 | `apps/prototype-description-service/recognition/tests/deploy/test_sync_identity_schema.py` | 147–149 | `sync_identity_schema` module source for `.create_all` | convert-to-lint | Prohibit ORM schema creation with a dedicated static rule. |
| R25 | `apps/prototype-description-service/recognition/tests/deploy/test_cross_slice_contract_gates.py` | 349–383, 734, 1197, 1401 | Deployment shell source, including sliced `do_boot_smoke`, and Makefile recipes | rewrite-behavioral | Drive deployment helpers with fake commands and assert their effects and ordering. |
| R26 | `apps/prototype-description-service/recognition/tests/deploy/test_compose_image_variant_parity.py` | 319–367, 649–663 | Deployment shell function bodies and compose text | rewrite-behavioral | Resolve compose configuration and execute the relevant shell path with stubs. |
| R27 | `apps/prototype-description-service/recognition/tests/deploy/test_vlm_cache_gate.py` | 750–752, 832–835 | Docker entrypoint shell source for cache-gate text | rewrite-behavioral | Run the entrypoint against temporary cache states and assert its decisions. |
| R28 | `apps/prototype-description-service/recognition/tests/deploy/test_runtime_packaging.py` | 55–65, 644–656 | Python entrypoint and logging source AST plus Dockerfile text | convert-to-lint | Packaging allowlists and import rules are static build-policy checks. |
| R29 | `apps/prototype-description-service/recognition/tests/deploy/test_dockerignore_weight_exclusions.py` | 622, 645, 717 | `.dockerignore` and deployment shell source | convert-to-lint | Forbidden image-weight paths and deploy-script exclusions are static policy rules. |
| R30 | `apps/prototype-description-service/recognition/tests/deploy/test_image_coordinate_doc_parity.py` | 67–68, 163 | Dockerfile and OCI README text compared with a sample | convert-to-lint | Keep this as a declarative parity check, implemented by a dedicated source/config checker. |

## `apps/prototype-description-service/scene/tests`

| ID | path | lines | what it parses | verdict | one-line reason |
|---|---|---:|---|---|---|
| R31 | `apps/prototype-description-service/scene/tests/test_eval_harness_pathtext_single_source.py` | 59–64 | Harness `.py` files AST-scanned for duplicate encoder definitions | convert-to-lint | Single-source definitions are a static duplication rule. |
| R32 | `apps/prototype-description-service/scene/tests/test_eval_harness_manifest_printable_paths.py` | 983–989, 1074–1080, 1375–1419 | `manifest.py` AST for operator-visible path formatting | convert-to-lint | The unwrapped-path sink rule belongs in a dedicated AST lint; keep its behavior tests. |
| R33 | `apps/prototype-description-service/scene/tests/test_eval_harness_cli.py` | 5806–5863 | `cli.py` AST for score-gate constant and message wiring | convert-to-lint | Single-source constants and safe error arguments are static source rules. |
| R34 | `apps/prototype-description-service/scene/tests/test_eval_harness_operator_path_census.py` | 73–99 | Harness modules parsed to detect path-bearing expressions sent to operator sinks | convert-to-lint | This is a reusable operator-path lint rather than a behavior test. |
| R35 | `apps/prototype-description-service/scene/tests/test_eval_harness_pilot_draw.py` | 1019–1036, 1092, 1130, 1232–1245, 1802 | Pilot-draw functions and modules via source inspection and AST | rewrite-behavioral | Exercise draw, isolation, and cache invariants through public calls and observable outputs. |
| R36 | `apps/prototype-description-service/scene/tests/test_eval_harness_cli_gate_wire_format.py` | 89, 189–224, 303–312 | CLI source AST for gate-failure wire formatting | convert-to-lint | The rule over error arguments can live in the CLI source lint. |
| R37 | `apps/prototype-description-service/scene/tests/test_eval_harness_cli_stdio.py` | 781–786, 873–879 | Its own test module source, sliced to inspect guard helpers | rewrite-behavioral | Assert pytest collection/marker behavior through the pytest API instead of reading test source. |
| R38 | `apps/prototype-description-service/scene/tests/test_priv1_pseudonymize.py` | 851–855, 927–930, 1052–1055, 1408–1411, 1869–1872, 2429–2446, 3171–3172 | `priv1_pseudonymize.py` function bodies sliced by `source.index` | rewrite-behavioral | Invoke plan/apply/verify commands with temporary data and assert their resulting files and reports. |
| R39 | `apps/prototype-description-service/scene/tests/test_gpu_lifecycle_install_script.py` | 122–124, 369–375 | Installer shell source and ordering of group resolution/unit staging | rewrite-behavioral | Run the installer against fake NSS and filesystem commands and assert the installed units. |
| R40 | `apps/prototype-description-service/scene/tests/test_eval_harness_landmark_cache.py` | 196–202 | `synthetic_occlusion` Python source tokenized for forbidden detector names | convert-to-lint | The source-symbol firewall is a narrow static dependency rule. |
| R41 | `apps/prototype-description-service/scene/tests/test_eval_harness_face_bakeoff.py` | 458–470 | Bench source modules tokenized for forbidden import/name symbols | convert-to-lint | This import firewall should be a static source lint with its mutation fixture retained. |

## `apps/prototype-description-service/scripts`

### `bench/tests`

| ID | path | lines | what it parses | verdict | one-line reason |
|---|---|---:|---|---|---|
| R42 | `apps/prototype-description-service/scripts/bench/tests/test_preflight.py` | 365–375 | Bench `.py` modules AST-scanned for `cv2` imports | convert-to-lint | Keep the no-OpenCV dependency rule as an import lint. |
| R43 | `apps/prototype-description-service/scripts/bench/tests/test_manifest_version_seam.py` | 126–137 | Bench production `.py` files scanned for `present_identities` subtraction patterns | convert-to-lint | This arithmetic ban is a source lint rule. |

### `eval_harness/tests`

| ID | path | lines | what it parses | verdict | one-line reason |
|---|---|---:|---|---|---|
| R44 | `apps/prototype-description-service/scripts/eval_harness/tests/test_r6d3_extract_head_shas.py` | 45–68 | Guard script AST and `main` source for removed helper references | convert-to-lint | The removed-symbol rule should be static; public harvester behavior already has runtime coverage. |
| R45 | `apps/prototype-description-service/scripts/eval_harness/tests/test_eval_captions_operator.py` | 89–100 | Makefile section sliced between target markers | rewrite-behavioral | Run the Make target with fake scorer commands and verify exit/status behavior. |
| R46 | `apps/prototype-description-service/scripts/eval_harness/tests/test_eval_exit_contract.py` | 48–60 | Regen-report module and Makefile source for shared exit constants | rewrite-behavioral | Exercise the wrapper and Make target for each exit class and inspect observed status. |

## `scripts`

| ID | path | lines | what it parses | verdict | one-line reason |
|---|---|---:|---|---|---|
| R47 | `scripts/test_ocirv1_vault_readiness.py` | 797–808 | `ocir-token-rotate.sh` source sliced around guard and compensation text | rewrite-behavioral | Execute rotation against stubbed secrets and assert the guarded compensation behavior. |
| R48 | `scripts/test_remote_gate_guards.py` | 46–48, 58–78, 84–90 | `remote_gate.sh` command block and whole-file strings/regex | rewrite-behavioral | Stub remote commands and exercise preflight, unsafe-host, and private-host paths. |
| R52 | `scripts/test_e15_33_boot_smoke.py` | 21–22, 57–78, 100–181, 238–241 | `recognition-service.sh` with shell-function and heredoc bodies sliced by offsets | rewrite-behavioral | Use the existing fake-SSH harness to assert smoke, rollback, and promotion behavior end to end. |
| R53 | `scripts/test_gpu_burst_smoke.py` | 1535, 2173–2180 | Lifecycle installer shell text and GPU-smoke Python AST imports | convert-to-lint | Retain the no-forbidden-import invariant as an explicit source lint; keep installer execution tests. |
| R54 | `scripts/test_gpu_cost_report.py` | 142–145 | `gpu_cost_report.py` AST import list | convert-to-lint | The dependency allowlist is a static import-boundary rule. |
| R55 | `scripts/test_make_eval_targets.py` | 83–107, 127–128, 198–211 | Make recipes plus invoked module source for required flags | rewrite-behavioral | Use `make -n` and module CLI behavior to verify flags reach the invoked tool. |
| R56 | `scripts/test_mk_orchestrator_module_invocations.py` | 17–29, 49–66 | Orchestrator Makefile fragments for old/new invocation text | rewrite-behavioral | Run the relevant Make targets with stub executables and inspect argv. |
| R57 | `scripts/test_current_task_demotion_surfaces.py` | 54–59 | Handoff Makefile and root Makefile text for overlay inclusion | rewrite-behavioral | Assert effective target behavior through Make’s database/dry-run output. |
| R58 | `scripts/test_e15_28_demo_stack_infra.py` | 60–66, 93–96 | Demo Makefile target and sync shell source strings | rewrite-behavioral | Render compose configuration and run the sync helper with fake Docker commands. |
| R59 | `scripts/test_e15_28_demo_walkthrough_proof.py` | 27–64, 82–90 | TypeScript/TSX sources and Makefile recipe for walkthrough proof | rewrite-behavioral | Run the renderer and E2E target, asserting generated evidence and runtime output. |
| R60 | `scripts/test_e15_28_demo_seed_and_epic.py` | 19–20 | Demo seed-import script text for WP CLI invocations | rewrite-behavioral | Run the importer with a fake `wp` executable and assert imported records. |
| R61 | `scripts/test_php_characterization_gate.py` | 50–58 | Root Makefile target block and CI workflow strings | rewrite-behavioral | Verify the effective `check-all`/`test-scripts` Make graph and CI invocation. |
| R62 | `scripts/test_prod_smoke.py` | 68–71 | Production smoke CLI Python source for tenant-header and option strings | rewrite-behavioral | Mock the HTTP boundary and prove the CLI sends the configured tenant header. |
| R63 | `scripts/test_acx_backend_image_contract.py` | 232, 258, 289–325, 585, 665, 811, 945 | Dockerfile and deployment shell source text for build/deploy ordering | rewrite-behavioral | Build/execute the relevant recipes with stub tools and assert the resulting image/deploy inputs. |
| R64 | `scripts/test_e15_31_admin_deploy_contract.py` | 15–31 | `deploy-env.sh`, systemd unit template, and sync shell source | rewrite-behavioral | Render the unit and run deploy/sync commands with Docker and SSH stubs. |
| R66 | `scripts/test_localwp_batch_run_smoke.py` | 10–22 | Plugin Makefile target body selected by regex | rewrite-behavioral | Run the Make target with a fake WordPress command and verify positional arguments. |

## `scripts/tests`

| ID | path | lines | what it parses | verdict | one-line reason |
|---|---|---:|---|---|---|
| R49 | `scripts/tests/test_remote_agent_origin_guard.py` | 17–30 | `remote_agent.sh` source blocks selected by literal markers | rewrite-behavioral | Exercise the complete guard path with the test venv and controlled import origins. |
| R50 | `scripts/tests/test_plan_baseline_handler_behavior.py` | 119–122 | Handler Python module AST solely to read its module docstring | rewrite-behavioral | Assert the documented fallback through the command’s user-visible help/output. |
| R51 | `scripts/tests/test_wave4_playwright_contract.py` | 20–24 | Its own test module AST to discover a named test | rewrite-behavioral | Query pytest collection metadata for the contract test instead of parsing its source. |
| R65 | `scripts/tests/test_remote_agent_ping_hygiene.py` | 790–812 | Remote-agent shell source and overlay wiring text | rewrite-behavioral | Execute the source and overlay with fake ping/systemctl commands and assert bounded cleanup. |
| R67 | `scripts/tests/test_makefile_startup_cost.py` | 97–101, 443–455 | Makefile logical lines parsed for eager shell assignments | convert-to-lint | This Makefile-specific eager-evaluation parser is itself a lint boundary. |
| R68 | `scripts/tests/test_lane_provisioner_make_wiring.py` | 13–25, 44–55 | Makefile target and recipe text for lane provisioning | rewrite-behavioral | Dry-run/execute the target with stub scripts and assert its argv and failure propagation. |
| R69 | `scripts/tests/test_plan_accept_handler_wiring.py` | 24–48, 61–81, 148–149 | Lifecycle Makefile target/recipe and overlay text | rewrite-behavioral | Run `plan-accept` with stub handlers and inspect the selected handler and arguments. |
| R70 | `scripts/tests/test_ux_map_gate_wiring.py` | 76–104, 123–127 | Makefile target and workflow text for UX-map checks | rewrite-behavioral | Run the Make check target and validate workflow selection through a workflow parser. |

## `scripts/deploy/tests`

| ID | path | lines | what it parses | verdict | one-line reason |
|---|---|---:|---|---|---|
| R71 | `scripts/deploy/tests/test_gpu_lifecycle_deploy_wiring.py` | 1226–1274 | Installer shell source sliced around unit installation and rearm steps | rewrite-behavioral | Run the installer with stub systemd commands and assert service/timer ordering. |
| R72 | `scripts/deploy/tests/test_recognition_deploy.py` | 275–311, 1251–1253 | Deployment shell functions and smoke heredoc sliced with `source.index` | rewrite-behavioral | Exercise the deploy helpers through their CLI with SSH/Docker stubs. |
| R73 | `scripts/deploy/tests/test_sanitize_deploy_diagnostic.py` | 17–19 | `sanitize_deploy_diagnostic()` shell function body | rewrite-behavioral | Feed sensitive and safe diagnostics through the real helper and assert redaction. |
| R74 | `scripts/deploy/tests/test_gpu_release_path.py` | 90–94 | Sync-demo shell source from the `run_gpu_env_preflight` function onward | rewrite-behavioral | Run release with controlled preflight outcomes and assert it stops before promotion. |
| R75 | `scripts/deploy/tests/test_release_receipt.py` | 194–203 | Restart and restore shell function bodies | rewrite-behavioral | Drive the release path with failing stubs and assert recorded compensation effects. |
| R76 | `scripts/deploy/tests/test_recognition_ocir_config.py` | 381–385 | `_ship_selected_env()` shell body | rewrite-behavioral | Invoke deploy selection with environment fixtures and assert the shipped config. |
| R77 | `scripts/deploy/tests/test_verify_classification.py` | 196–205 | Shell helper bodies selected by literal function marker | rewrite-behavioral | Run each verifier case and assert its observable classification and exit code. |
| R78 | `scripts/deploy/tests/test_flip_failure_recovery.py` | 18–25 | Deployment shell function body | rewrite-behavioral | Trigger the failure through the deploy command and assert restored state. |
| R79 | `scripts/deploy/tests/test_deploy_sha_pin.py` | 89–96 | Deployment shell source for commit/SHA pin text | rewrite-behavioral | Run the deployment command with competing refs and assert the selected digest. |
| R80 | `scripts/deploy/tests/test_gpu_lifecycle_install.py` | 92–252 | Lifecycle installer shell source with many substring/regex assertions | rewrite-behavioral | Keep the fake-NSS installer tests and replace static checks with installed-state assertions. |
| R81 | `scripts/deploy/tests/test_gpu_lifecycle_contract_ownership.py` | 72–75, 100, 205 | Installer shell, ownership contract, and Dockerfile source text | convert-to-lint | Contract ownership and image-user rules are static deployment policy. |
| R82 | `scripts/deploy/tests/test_check_gpu_snapshots_shell.py` | 72–80 | Snapshot checker shell source | convert-to-lint | The checker’s shell syntax/pipeline requirements fit a focused script lint. |
| R83 | `scripts/deploy/tests/test_preflight_gpu_env.py` | 1739–1753, 2302, 3027 | Preflight shell files and environment-source script text | rewrite-behavioral | Run preflight with controlled env files and assert resulting diagnostics and state. |
| R84 | `scripts/deploy/tests/test_check_gpu_snapshots_piped.py` | 133–138, 210–215 | Snapshot checker shell source for pipe handling | rewrite-behavioral | Pipe real fixture output through the checker and assert parsed records and status. |
| R85 | `scripts/deploy/tests/test_deploy_env_lease.py` | 615–625 | Deploy shell source for environment lease ordering | rewrite-behavioral | Exercise concurrent lease acquisition through the command and inspect its effects. |
| R86 | `scripts/deploy/tests/test_deploy_snapshot.py` | 230–245, 275–290 | Deployment shell source for snapshot/restore hooks | rewrite-behavioral | Run snapshot and restore paths with fake remote commands and compare state. |
| R87 | `scripts/deploy/tests/test_interrupt_compensation.py` | 119–130 | Deployment shell source for interrupt cleanup | rewrite-behavioral | Send a controlled interrupt during execution and assert cleanup and rollback. |
| R88 | `scripts/deploy/tests/test_check_gpu_snapshot_schema_parity.py` | 17–25 | Snapshot checker shell source for schema-parity text | convert-to-lint | The duplicated shell schema contract can be checked statically or generated from one schema. |

## Summary by verdict

| verdict | files |
|---|---:|
| convert-to-lint | 28 |
| rewrite-behavioral | 60 |
| delete | 0 |
| keep | 0 |
| total | 88 |

No `keep` row was warranted: the identified readers inspect implementation or recipe source, while generated-output drift checks and ordinary fixture/output reads did not parse code source.

## Proposed batches

Each batch below contains at most three files; IDs refer to the tables above.

| batch | files |
|---|---|
| B01 | R01–R03 |
| B02 | R04–R06 |
| B03 | R07–R09 |
| B04 | R10–R12 |
| B05 | R13–R15 |
| B06 | R16–R18 |
| B07 | R19–R21 |
| B08 | R22–R24 |
| B09 | R25–R27 |
| B10 | R28–R30 |
| B11 | R31–R33 |
| B12 | R34–R36 |
| B13 | R37–R39 |
| B14 | R40–R42 |
| B15 | R43–R45 |
| B16 | R46–R48 |
| B17 | R49–R51 |
| B18 | R52–R54 |
| B19 | R55–R57 |
| B20 | R58–R60 |
| B21 | R61–R63 |
| B22 | R64–R66 |
| B23 | R67–R69 |
| B24 | R70–R72 |
| B25 | R73–R75 |
| B26 | R76–R78 |
| B27 | R79–R81 |
| B28 | R82–R84 |
| B29 | R85–R87 |
| B30 | R88 |
