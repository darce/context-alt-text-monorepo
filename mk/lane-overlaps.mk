# =============================================================================
# Live lane manifest owned-path overlap check
# =============================================================================

.PHONY: lane-overlaps-check lane-overlaps-tests

LANE_OVERLAPS_MANIFEST_DIR ?= $(ROOT_MAKEFILE_DIR)/config/lane-orchestration
LANE_OVERLAPS_STATUS_JSON ?=
LANE_STATUS_JSON ?= $(LANE_OVERLAPS_STATUS_JSON)

lane-overlaps-check:
	@set -eu; \
	 lane_root="$$(git rev-parse --show-toplevel)"; \
	 manifest_dir="$(LANE_OVERLAPS_MANIFEST_DIR)"; \
	 if [ -x "$$lane_root/.venv/bin/python" ]; then \
	  resolved_python="$$lane_root/.venv/bin/python"; \
	 else \
	  resolved_python="$$(command -v python3)" || { echo 'python3 is unavailable' >&2; exit 1; }; \
	 fi; \
	 set -- "$$resolved_python" "$$lane_root/scripts/check_lane_manifest_overlaps.py" \
	  --manifest-dir "$$manifest_dir"; \
	 if [ ! -d "$$manifest_dir" ] || [ -z "$$(find "$$manifest_dir" -maxdepth 1 -type f -name '*.json' -print -quit)" ]; then \
	  "$$@"; \
	  exit 0; \
	 fi; \
	 status_json="$(LANE_STATUS_JSON)"; \
	 if [ -z "$$status_json" ]; then \
	  status_json="$$(mktemp "$${TMPDIR:-/tmp}/lane-overlaps-status.XXXXXX")"; \
	  trap 'rm -f "$$status_json"' EXIT HUP INT TERM; \
	  if ! $(MCP_CMD) $(MCP_STATE_ARGS) lane-list --status all --limit 200 >"$$status_json"; then \
	    echo "Lane status export unavailable; overlap check cannot determine live lanes." >&2; \
	    exit 1; \
	  fi; \
	 fi; \
	 set -- "$$@" --lane-status-json "$$status_json"; \
	 "$$@"

lane-overlaps-tests:
	@set -eu; \
	 lane_root="$$(git rev-parse --show-toplevel)"; \
	 if [ -x "$$lane_root/.venv/bin/python" ]; then \
	  resolved_python="$$lane_root/.venv/bin/python"; \
	 else \
	  resolved_python="$$(command -v python3)" || { echo 'python3 is unavailable' >&2; exit 1; }; \
	 fi; \
	 "$$resolved_python" -m pytest "$$lane_root/scripts/test_check_lane_manifest_overlaps.py" -q -p no:cacheprovider

test-scripts: lane-overlaps-tests
check-all: lane-overlaps-check
