# =============================================================================
# Read-only OCI GPU burst evidence
# =============================================================================
#
# Export a bundle without changing OCI state:
#
#   make gpu-evidence-export \
#     GPU_EVIDENCE_INSTANCE_ID=<instance-ocid> \
#     GPU_EVIDENCE_COMPARTMENT_ID=<compartment-ocid> \
#     GPU_EVIDENCE_SINCE=2026-09-01T00:00:00Z \
#     GPU_EVIDENCE_UNTIL=2026-09-01T01:00:00Z \
#     GPU_EVIDENCE_BUNDLE=docs/evidence/gpu-burst-20260901
#
# Optional export variables:
#   GPU_EVIDENCE_STATE_SNAPSHOT  local path or URL for reaper gpu-state JSON
#   GPU_EVIDENCE_WP_RECEIPTS     local WordPress describe receipts JSON path
#   GPU_EVIDENCE_OCI_BIN         OCI executable (defaults to OCI_BIN or oci)
#
# Check an existing bundle:
#
#   make gpu-evidence-check \
#     GPU_EVIDENCE_BUNDLE=docs/evidence/gpu-burst-20260901 \
#     GPU_EVIDENCE_EXPECTED_STOP_PRINCIPAL=gpu-reaper \
#     GPU_EVIDENCE_MIN_DESCRIPTIONS=1
#
# GPU_EVIDENCE_SINCE and GPU_EVIDENCE_UNTIL are optional for the check target
# when the exporter manifest contains those bounds.  Supplying them again is
# useful when reviewing a narrower window.

GPU_EVIDENCE_EXPORT_SCRIPT ?= $(ROOT_MAKEFILE_DIR)/scripts/deploy/lib/export-gpu-evidence.sh
GPU_EVIDENCE_CHECKER ?= $(ROOT_MAKEFILE_DIR)/scripts/gpu_burst_evidence.py
GPU_EVIDENCE_BUNDLE ?= $(ROOT_MAKEFILE_DIR)/docs/evidence/gpu-burst
GPU_EVIDENCE_INSTANCE_ID ?= $(GPU_INSTANCE_ID)
GPU_EVIDENCE_COMPARTMENT_ID ?= $(GPU_COMPARTMENT_ID)
GPU_EVIDENCE_SINCE ?=
GPU_EVIDENCE_UNTIL ?=
GPU_EVIDENCE_STATE_SNAPSHOT ?=
GPU_EVIDENCE_WP_RECEIPTS ?=
GPU_EVIDENCE_OCI_BIN ?= $(if $(OCI_BIN),$(OCI_BIN),oci)
GPU_EVIDENCE_EXPECTED_STOP_PRINCIPAL ?= gpu-reaper
GPU_EVIDENCE_MIN_DESCRIPTIONS ?= 1
GPU_EVIDENCE_PYTHON ?= python3

# Keep the checker and its contract tests in the root script lint/format
# inputs.  The root Makefile includes this fragment before defining
# `test-scripts`, so the prerequisite below also makes the substantive checker
# suite part of that explicit test target without changing the root file.
OCIRV1_PYTHON_FILES += \
	scripts/gpu_burst_evidence.py \
	scripts/test_gpu_burst_evidence.py \
	scripts/deploy/tests/test_export_gpu_evidence_shell.py

.PHONY: gpu-evidence-tests
test-scripts: gpu-evidence-tests

gpu-evidence-tests:
	@"$(GPU_EVIDENCE_PYTHON)" -m pytest \
		scripts/test_gpu_burst_evidence.py \
		scripts/deploy/tests/test_export_gpu_evidence_shell.py \
		-q -p no:cacheprovider

.PHONY: gpu-evidence-export gpu-evidence-check

gpu-evidence-export:
	@set -eu; \
		test -n "$(GPU_EVIDENCE_INSTANCE_ID)" || { echo "GPU_EVIDENCE_INSTANCE_ID is required" >&2; exit 2; }; \
		test -n "$(GPU_EVIDENCE_COMPARTMENT_ID)" || { echo "GPU_EVIDENCE_COMPARTMENT_ID is required" >&2; exit 2; }; \
		test -n "$(GPU_EVIDENCE_SINCE)" || { echo "GPU_EVIDENCE_SINCE is required" >&2; exit 2; }; \
		test -n "$(GPU_EVIDENCE_UNTIL)" || { echo "GPU_EVIDENCE_UNTIL is required" >&2; exit 2; }; \
		OCI_BIN="$(GPU_EVIDENCE_OCI_BIN)" bash "$(GPU_EVIDENCE_EXPORT_SCRIPT)" \
			--instance-id "$(GPU_EVIDENCE_INSTANCE_ID)" \
			--compartment-id "$(GPU_EVIDENCE_COMPARTMENT_ID)" \
			--since "$(GPU_EVIDENCE_SINCE)" \
			--until "$(GPU_EVIDENCE_UNTIL)" \
			--out "$(GPU_EVIDENCE_BUNDLE)" \
			$(if $(GPU_EVIDENCE_STATE_SNAPSHOT),--state-snapshot "$(GPU_EVIDENCE_STATE_SNAPSHOT)",) \
			$(if $(GPU_EVIDENCE_WP_RECEIPTS),--wp-receipts "$(GPU_EVIDENCE_WP_RECEIPTS)",)

gpu-evidence-check:
	@set -eu; \
		test -d "$(GPU_EVIDENCE_BUNDLE)" || { echo "GPU_EVIDENCE_BUNDLE is not a directory: $(GPU_EVIDENCE_BUNDLE)" >&2; exit 2; }; \
		"$(GPU_EVIDENCE_PYTHON)" "$(GPU_EVIDENCE_CHECKER)" \
			--bundle "$(GPU_EVIDENCE_BUNDLE)" \
			--expected-stop-principal "$(GPU_EVIDENCE_EXPECTED_STOP_PRINCIPAL)" \
			--min-descriptions "$(GPU_EVIDENCE_MIN_DESCRIPTIONS)" \
			$(if $(GPU_EVIDENCE_SINCE),--since "$(GPU_EVIDENCE_SINCE)",) \
			$(if $(GPU_EVIDENCE_UNTIL),--until "$(GPU_EVIDENCE_UNTIL)",)
