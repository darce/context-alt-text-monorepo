# =============================================================================
# Live lane manifest owned-path overlap check
# =============================================================================

.PHONY: lane-overlaps-check

LANE_OVERLAPS_MANIFEST_DIR ?= $(ROOT_MAKEFILE_DIR)/config/lane-orchestration
LANE_OVERLAPS_STATUS_JSON ?=
LANE_STATUS_JSON ?= $(LANE_OVERLAPS_STATUS_JSON)

lane-overlaps-check:
	@set -eu; \
	 lane_root="$(ROOT_MAKEFILE_DIR)"; \
	 if [ -x "$$lane_root/.venv/bin/python" ]; then \
	 	resolved_python="$$lane_root/.venv/bin/python"; \
	 else \
	 	resolved_python="$$(command -v python3)" || { echo 'python3 is unavailable' >&2; exit 1; }; \
	 fi; \
	 set -- "$$resolved_python" "$$lane_root/scripts/check_lane_manifest_overlaps.py" \
	 	--manifest-dir "$(LANE_OVERLAPS_MANIFEST_DIR)"; \
	 if [ -n "$(LANE_STATUS_JSON)" ]; then \
	 	set -- "$$@" --lane-status-json "$(LANE_STATUS_JSON)"; \
	 fi; \
	 "$$@"

check-all: lane-overlaps-check
