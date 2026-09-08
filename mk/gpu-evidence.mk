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
GPU_EVIDENCE_SINCE ?=
GPU_EVIDENCE_UNTIL ?=
GPU_EVIDENCE_STATE_SNAPSHOT ?=
GPU_EVIDENCE_WP_RECEIPTS ?=
GPU_EVIDENCE_EXPECTED_STOP_PRINCIPAL ?= gpu-reaper
GPU_EVIDENCE_MIN_DESCRIPTIONS ?= 1
GPU_EVIDENCE_PYTHON ?= python3

# Keep operator-provided values from being interpreted by GNU Make before they
# reach the shell.  File-defined defaults still need normal Make expansion,
# while command-line and environment values must be read with `value` so a
# payload such as `$(touch marker)` is rejected instead of disappearing during
# expansion.  Every accepted value is then passed as one single-quoted shell
# argument; embedded single quotes are represented by the usual `\'` splice.
#
# GPU_EVIDENCE_INSTANCE_ID / COMPARTMENT_ID / OCI_BIN fall back to the operator
# names GPU_INSTANCE_ID / GPU_COMPARTMENT_ID / OCI_BIN.  Resolve the *name*
# that actually supplied the value before validating or expanding it; an
# eagerly assigned `?= $(GPU_INSTANCE_ID)` alias is FILE origin and would
# expand an environment payload under `make -n`.  `oci` is the literal
# default only when neither OCI name is set.
GPU_EVIDENCE_SINGLE_QUOTE := '
gpu_evidence_value = $(if $(filter command% environment%,$(origin $(1))),$(value $(1)),$($(1)))
gpu_evidence_shell_quote = $(GPU_EVIDENCE_SINGLE_QUOTE)$(subst $(GPU_EVIDENCE_SINGLE_QUOTE),$(GPU_EVIDENCE_SINGLE_QUOTE)\$(GPU_EVIDENCE_SINGLE_QUOTE)$(GPU_EVIDENCE_SINGLE_QUOTE),$(1))$(GPU_EVIDENCE_SINGLE_QUOTE)
gpu_evidence_validate = $(if $(findstring $$,$(call gpu_evidence_value,$(1))),$(error unsafe GPU evidence value for $(1): dollar signs are not accepted),)
gpu_evidence_alias = $(if $(filter undefined,$(origin $(1))),$(2),$(1))
gpu_evidence_instance_id_name = $(call gpu_evidence_alias,GPU_EVIDENCE_INSTANCE_ID,GPU_INSTANCE_ID)
gpu_evidence_compartment_id_name = $(call gpu_evidence_alias,GPU_EVIDENCE_COMPARTMENT_ID,GPU_COMPARTMENT_ID)
gpu_evidence_oci_bin_name = $(call gpu_evidence_alias,GPU_EVIDENCE_OCI_BIN,OCI_BIN)

# Keep the checker and its contract tests in the root script lint/format
# inputs.  The root Makefile explicitly collects the substantive checker suite
# in `test-scripts`; the standalone target below remains available for focused
# GPU evidence verification.
OCIRV1_PYTHON_FILES += \
	scripts/gpu_burst_evidence.py \
	scripts/test_gpu_burst_evidence.py \
	scripts/deploy/tests/test_export_gpu_evidence_shell.py

.PHONY: gpu-evidence-tests

gpu-evidence-tests:
	$(call gpu_evidence_validate,GPU_EVIDENCE_PYTHON)
	@$(call gpu_evidence_shell_quote,$(call gpu_evidence_value,GPU_EVIDENCE_PYTHON)) -m pytest \
		scripts/test_gpu_burst_evidence.py \
		-q -p no:cacheprovider

.PHONY: gpu-evidence-export gpu-evidence-check

gpu-evidence-export:
	$(call gpu_evidence_validate,$(gpu_evidence_instance_id_name))
	$(call gpu_evidence_validate,$(gpu_evidence_compartment_id_name))
	$(call gpu_evidence_validate,$(gpu_evidence_oci_bin_name))
	$(foreach variable,GPU_EVIDENCE_SINCE GPU_EVIDENCE_UNTIL GPU_EVIDENCE_BUNDLE GPU_EVIDENCE_STATE_SNAPSHOT GPU_EVIDENCE_WP_RECEIPTS GPU_EVIDENCE_EXPORT_SCRIPT,$(call gpu_evidence_validate,$(variable)))
	@set -eu; \
		test -n $(call gpu_evidence_shell_quote,$(call gpu_evidence_value,$(gpu_evidence_instance_id_name))) || { echo "GPU_EVIDENCE_INSTANCE_ID is required" >&2; exit 2; }; \
		test -n $(call gpu_evidence_shell_quote,$(call gpu_evidence_value,$(gpu_evidence_compartment_id_name))) || { echo "GPU_EVIDENCE_COMPARTMENT_ID is required" >&2; exit 2; }; \
		test -n $(call gpu_evidence_shell_quote,$(call gpu_evidence_value,GPU_EVIDENCE_SINCE)) || { echo "GPU_EVIDENCE_SINCE is required" >&2; exit 2; }; \
		test -n $(call gpu_evidence_shell_quote,$(call gpu_evidence_value,GPU_EVIDENCE_UNTIL)) || { echo "GPU_EVIDENCE_UNTIL is required" >&2; exit 2; }; \
		OCI_BIN=$(call gpu_evidence_shell_quote,$(or $(call gpu_evidence_value,$(gpu_evidence_oci_bin_name)),oci)) bash $(call gpu_evidence_shell_quote,$(call gpu_evidence_value,GPU_EVIDENCE_EXPORT_SCRIPT)) \
			--instance-id $(call gpu_evidence_shell_quote,$(call gpu_evidence_value,$(gpu_evidence_instance_id_name))) \
			--compartment-id $(call gpu_evidence_shell_quote,$(call gpu_evidence_value,$(gpu_evidence_compartment_id_name))) \
			--since $(call gpu_evidence_shell_quote,$(call gpu_evidence_value,GPU_EVIDENCE_SINCE)) \
			--until $(call gpu_evidence_shell_quote,$(call gpu_evidence_value,GPU_EVIDENCE_UNTIL)) \
			--out $(call gpu_evidence_shell_quote,$(call gpu_evidence_value,GPU_EVIDENCE_BUNDLE)) \
			$(if $(call gpu_evidence_value,GPU_EVIDENCE_STATE_SNAPSHOT),--state-snapshot $(call gpu_evidence_shell_quote,$(call gpu_evidence_value,GPU_EVIDENCE_STATE_SNAPSHOT)),) \
			$(if $(call gpu_evidence_value,GPU_EVIDENCE_WP_RECEIPTS),--wp-receipts $(call gpu_evidence_shell_quote,$(call gpu_evidence_value,GPU_EVIDENCE_WP_RECEIPTS)),)

gpu-evidence-check:
	$(foreach variable,GPU_EVIDENCE_BUNDLE GPU_EVIDENCE_PYTHON GPU_EVIDENCE_CHECKER GPU_EVIDENCE_EXPECTED_STOP_PRINCIPAL GPU_EVIDENCE_MIN_DESCRIPTIONS GPU_EVIDENCE_SINCE GPU_EVIDENCE_UNTIL,$(call gpu_evidence_validate,$(variable)))
	@set -eu; \
		test -d $(call gpu_evidence_shell_quote,$(call gpu_evidence_value,GPU_EVIDENCE_BUNDLE)) || { printf '%s %s\n' 'GPU_EVIDENCE_BUNDLE is not a directory:' $(call gpu_evidence_shell_quote,$(call gpu_evidence_value,GPU_EVIDENCE_BUNDLE)) >&2; exit 2; }; \
		$(call gpu_evidence_shell_quote,$(call gpu_evidence_value,GPU_EVIDENCE_PYTHON)) $(call gpu_evidence_shell_quote,$(call gpu_evidence_value,GPU_EVIDENCE_CHECKER)) \
			--bundle $(call gpu_evidence_shell_quote,$(call gpu_evidence_value,GPU_EVIDENCE_BUNDLE)) \
			--expected-stop-principal $(call gpu_evidence_shell_quote,$(call gpu_evidence_value,GPU_EVIDENCE_EXPECTED_STOP_PRINCIPAL)) \
			--min-descriptions $(call gpu_evidence_shell_quote,$(call gpu_evidence_value,GPU_EVIDENCE_MIN_DESCRIPTIONS)) \
			$(if $(call gpu_evidence_value,GPU_EVIDENCE_SINCE),--since $(call gpu_evidence_shell_quote,$(call gpu_evidence_value,GPU_EVIDENCE_SINCE)),) \
			$(if $(call gpu_evidence_value,GPU_EVIDENCE_UNTIL),--until $(call gpu_evidence_shell_quote,$(call gpu_evidence_value,GPU_EVIDENCE_UNTIL)),)
