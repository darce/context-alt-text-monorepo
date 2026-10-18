VERDICT: MERGE
POR: {"file_count":267,"line_count":22855,"md5":"95253c630a3e6e0037ab936ee5cd2592","sample_lines":{"41":"-from recognition.interface_adapters.http.deps.portal_composition import install_portal_composition","173":"         mc_check, cache_dir, model_name = await _model_probe()"}}
## Findings
- L-1 (LOW): infra/oci/demo/tests/verify-clustering-seed.sh:16360 The provenance-row counter omits uppercase JPEG and PNG suffixes after guided selection began preserving source casing. Failure: a supported `source.JPG` becomes `slug_1.JPG`, but the row counter excludes that row and the otherwise valid seed bundle fails verification. Canon: TEST-15.
- L-2 (LOW): scripts/tests/test_remote_agent_origin_guard.py:22643 The origin-guard helpers now return hard-coded fragments instead of extracting them from the production script. Failure: removing or changing the production guard can leave these tests green because their assertions still exercise only the copied strings. Canon: TEST-15.
## Coverage
- `infra/oci/demo/lib/describe-gate.sh`, seed README, manifest, import and selector patch lines 16021-16129: trusted profile identity validation, local CPU readiness, WebP selection and extension preservation.
- `infra/oci/demo/tests/test_dw2_describega_1.py` and `verify-clustering-seed.sh` patch lines 16130-16374: readiness and seed image/count checks.
- `infra/oci/gpu_lifecycle/intent.py` and `reaper.py` patch lines 16375-16533: intent parsing formatting and operator-stop handling for transitional instance states.
- `infra/oci/gpu_lifecycle/tests/test_dw2_reaper_1.py`, `test_intent.py` and `test_intent_controller.py` patch lines 16534-16875: operator-stop fallback and intent regression coverage.
- `mk/deploy.mk` and shared-contract schemas patch lines 16876-17060: deploy guidance and recognition/readiness schema contracts.
- `scripts/check_lane_report_shas.py` patch lines 17061-17182: SHA scanner formatting-only changes.
- `scripts/deploy/enable-public-guide.sh` patch lines 17183-17244: local host URL restriction before WP execution.
- `scripts/deploy/gpu-lifecycle-install.sh` patch lines 17245-17271: API container group verification before lifecycle publication.
- `scripts/deploy/lib/export-gpu-evidence.sh` patch lines 17272-17427: bounded OCI Audit capture, explicit page limit and incomplete-capture rejection.
- `scripts/deploy/sync-demo.sh` patch lines 19224-19286: WebP sync and in-place Caddyfile rollback and validation.
- `scripts/guard_codemap_first.py` patch lines 22118-22326: bounded Git lookup, payload cwd, brace globs, shell comments and search flag parsing.
- `scripts/test_dw2_guardcodem_1.py`, `test_vlm3_oci_gpu_infra.py`, and `scripts/tests` patch lines 22327-22797: guard regression tests and skimmed test-only changes.
- `scripts/workstate/provision_lane_worktree.py` and `scripts/worktree_reap.py` patch lines 22798-22855: formatting changes and pinned lane-list call compatibility.
