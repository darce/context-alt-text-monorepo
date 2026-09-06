# =============================================================================
# Live lane manifest owned-path overlap check
# =============================================================================

.PHONY: lane-overlaps-check lane-overlaps-tests

LANE_OVERLAPS_MANIFEST_DIR ?= $(ROOT_MAKEFILE_DIR)/config/lane-orchestration
LANE_OVERLAPS_STATUS_JSON ?=
LANE_STATUS_JSON ?= $(LANE_OVERLAPS_STATUS_JSON)
LANE_OVERLAPS_PAGE_SIZE ?= 200
LANE_OVERLAPS_EXPORTER ?=

# Linked worktrees do not carry their own .venv, so fall back to the main
# worktree's interpreter before bare python3.
define LANE_OVERLAPS_RESOLVE_PYTHON
	 lane_root="$$(git rev-parse --show-toplevel)"; \
	 lane_git_common="$$(git rev-parse --git-common-dir)"; \
	 case "$$lane_git_common" in \
	  /*) ;; \
	  *) lane_git_common="$$lane_root/$$lane_git_common" ;; \
	 esac; \
	 lane_main_root="$$(dirname "$$lane_git_common")"; \
	 resolved_python=''; \
	 for lane_python in "$$lane_root/.venv/bin/python" "$$lane_main_root/.venv/bin/python"; do \
	  if [ -x "$$lane_python" ]; then resolved_python="$$lane_python"; break; fi; \
	 done; \
	 if [ -z "$$resolved_python" ]; then \
	  resolved_python="$$(command -v python3)" || { echo 'python3 is unavailable' >&2; exit 1; }; \
	 fi
endef

lane-overlaps-check:
	@set -eu; \
	 $(LANE_OVERLAPS_RESOLVE_PYTHON); \
	 manifest_dir="$(LANE_OVERLAPS_MANIFEST_DIR)"; \
	 checker_script="$$lane_root/scripts/check_lane_manifest_overlaps.py"; \
	 exporter_script="$(LANE_OVERLAPS_EXPORTER)"; \
	 [ -n "$$exporter_script" ] || exporter_script="$$lane_root/scripts/export_lane_status.py"; \
	 if [ -e "$$manifest_dir" ] && [ ! -d "$$manifest_dir" ]; then \
	  echo "Lane manifest path is not a directory: $$manifest_dir" >&2; \
	  exit 2; \
	 fi; \
	 manifest_found=0; \
	 if [ -d "$$manifest_dir" ]; then \
	  for manifest_path in "$$manifest_dir"/*.json; do \
	   if [ -f "$$manifest_path" ]; then manifest_found=1; break; fi; \
	  done; \
	 fi; \
	 if [ "$$manifest_found" -eq 0 ]; then \
	  "$$resolved_python" "$$checker_script" --manifest-dir "$$manifest_dir"; \
	  exit 0; \
	 fi; \
	 status_json="$(LANE_STATUS_JSON)"; \
	 if [ -z "$$status_json" ]; then \
	  page_size="$(LANE_OVERLAPS_PAGE_SIZE)"; \
	  case "$$page_size" in \
	   ''|*[!0-9]*|0) echo "LANE_OVERLAPS_PAGE_SIZE must be a positive integer." >&2; exit 2 ;; \
	  esac; \
	  status_dir="$$(mktemp -d "$${TMPDIR:-/tmp}/lane-overlaps-status.XXXXXX")"; \
	  status_json="$$status_dir/status.json"; \
	  trap 'rm -rf "$$status_dir"' EXIT HUP INT TERM; \
	  if ! "$$resolved_python" "$$exporter_script" \
	    --manifest-dir "$$manifest_dir" --workspace-root "$$lane_main_root" \
	    --page-size "$$page_size" --output "$$status_json"; then \
	   echo "Lane status export unavailable; skipping the overlap check." >&2; \
	   echo "Manifests carry no lifecycle status, so without the live export every" >&2; \
	   echo "long-closed lane would be reported as an overlap." >&2; \
	   exit 0; \
	  fi; \
	 fi; \
	 "$$resolved_python" "$$checker_script" --manifest-dir "$$manifest_dir" \
	  --lane-status-json "$$status_json"

lane-overlaps-tests:
	@set -eu; \
	 $(LANE_OVERLAPS_RESOLVE_PYTHON); \
	 "$$resolved_python" -m pytest \
	  "$$lane_root/scripts/test_check_lane_manifest_overlaps.py" \
	  "$$lane_root/scripts/test_export_lane_status.py" -q -p no:cacheprovider

test-scripts: lane-overlaps-tests
check-all: lane-overlaps-check
