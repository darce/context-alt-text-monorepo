VERDICT: MERGE
POR: {"file_count": 267, "line_count": 22855, "md5": "95253c630a3e6e0037ab936ee5cd2592", "sample_lines": {"41": "-from recognition.interface_adapters.http.deps.portal_composition import install_portal_composition", "173": "         mc_check, cache_dir, model_name = await _model_probe()"}}
## Findings
- none
## Coverage
`apps/prototype-description-service/scripts/eval_harness/promote_atomic.py` patch lines 9531-9640: basename validation, namespace collision refusal, journal recovery, atomic promotion, and orphan-stage scavenging; changes are formatting/import cleanup.
`apps/prototype-description-service/scripts/eval_harness/provenance_sha.py` patch lines 9641-9685: missing-git classification, executable resolution, and commit verification; changes preserve existing behavior.
`apps/prototype-description-service/scripts/eval_harness/recipe_recovery.py` patch lines 9686-9791: pixel tolerance validation, no-upscale guard, recipe scoring/order, manifest loading, and CLI refusal paths; changes are formatting.
`apps/prototype-description-service/scripts/eval_harness/report.py` patch lines 9792-9843: strict detection scoring receives the same run manifest and `build_reports` forwards it to both scoring paths.
`apps/prototype-description-service/scripts/eval_harness/seed_roster.py` patch lines 9844-9857: missing image resolution error path; formatting only.
`apps/prototype-description-service/scripts/eval_harness/synthetic_occlusion.py` patch lines 9858-9931: pair rollup floors, walk stability, and fail-closed headline probe filtering; changes are formatting/import cleanup.
`apps/prototype-description-service/scripts/eval_harness/tests/test_anti_straddle_delta.py` patch lines 9932-9944: skimmed; only a blank-line addition.
`apps/prototype-description-service/scripts/eval_harness/tests/test_dw2_report_1.py` patch lines 9945-10007: skimmed; invalid ratified IoU threshold must raise the strict detection invariant.
`apps/prototype-description-service/scripts/run_app_portal_evals.py` patch lines 10008-10553: manifest validation, command parsing/execution, JUnit pass accounting, evidence-only artifact checks, per-case and selected-gate enforcement, authorization, dirty-tree status, and emitted evidence.
`apps/prototype-description-service/scripts/validate_fir_dev_runtime.py` patch lines 10554-10582: unexpected validator exception logging and preserved JSON/stderr outcome.
`apps/prototype-description-service/systemd/acx-env.service.template` patch lines 10583-10604: OCI Vault bootstrap hook guidance comment.
