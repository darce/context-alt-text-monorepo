# =============================================================================
# Live lane manifest owned-path overlap check
# =============================================================================

.PHONY: lane-overlaps-check lane-overlaps-tests

LANE_OVERLAPS_MANIFEST_DIR ?= $(ROOT_MAKEFILE_DIR)/config/lane-orchestration
LANE_OVERLAPS_STATUS_JSON ?=
LANE_STATUS_JSON ?= $(LANE_OVERLAPS_STATUS_JSON)
LANE_OVERLAPS_PAGE_SIZE ?= 200

lane-overlaps-check:
	@set -eu; \
	 lane_root="$$(git rev-parse --show-toplevel)"; \
	 manifest_dir="$(LANE_OVERLAPS_MANIFEST_DIR)"; \
	 if [ -x "$$lane_root/.venv/bin/python" ]; then \
	  resolved_python="$$lane_root/.venv/bin/python"; \
	 else \
	  resolved_python="$$(command -v python3)" || { echo 'python3 is unavailable' >&2; exit 1; }; \
	 fi; \
	 checker_script="$$lane_root/scripts/check_lane_manifest_overlaps.py"; \
	 set -- "$$resolved_python" "$$checker_script" --manifest-dir "$$manifest_dir"; \
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
	  "$$@"; \
	  exit 0; \
	 fi; \
	 status_json="$(LANE_STATUS_JSON)"; \
	 if [ -z "$$status_json" ]; then \
	  status_dir="$$(mktemp -d "$${TMPDIR:-/tmp}/lane-overlaps-status.XXXXXX")"; \
	  status_json="$$status_dir/status.json"; \
	  trap 'rm -rf "$$status_dir"' EXIT HUP INT TERM; \
	  page_size="$(LANE_OVERLAPS_PAGE_SIZE)"; \
	  case "$$page_size" in \
	   ''|*[!0-9]*|0) echo "LANE_OVERLAPS_PAGE_SIZE must be a positive integer." >&2; exit 2 ;; \
	  esac; \
	  offset=0; \
	  total=-1; \
	  while :; do \
	   page_path="$$status_dir/page-$$offset.json"; \
	   if ! $(MCP_CMD) $(MCP_STATE_ARGS) lane-list --status all --limit "$$page_size" --offset "$$offset" >"$$page_path"; then \
	    echo "Lane status export unavailable; overlap check cannot determine live lanes." >&2; \
	    exit 1; \
	   fi; \
	   if ! page_meta="$$("$$resolved_python" -c 'import json, pathlib, sys; document = json.loads(pathlib.Path(sys.argv[1]).read_text()); payload = document.get("data") if isinstance(document.get("data"), dict) else document; rows = payload.get("lanes") if isinstance(payload, dict) else None; total = payload.get("total_matching") if isinstance(payload, dict) else None; returned = payload.get("returned") if isinstance(payload, dict) else None; has_more = payload.get("has_more") if isinstance(payload, dict) else None; assert isinstance(rows, list), "status export page has no lanes list"; assert type(total) is int and total >= 0, "status export page has no total_matching integer"; assert type(returned) is int and returned == len(rows), "status export page returned count is inconsistent"; assert type(has_more) is bool, "status export page has_more is not boolean"; assert all(isinstance(row, dict) and all(isinstance(row.get(key), str) and row.get(key).strip() for key in ("task_ref", "lane_id", "status")) for row in rows), "status export page contains an invalid lane row"; print(total, returned, int(has_more))' "$$page_path")"; then \
	    echo "Lane status export page is invalid or incomplete: $$page_path" >&2; \
	    exit 1; \
	   fi; \
	   set -- $$page_meta; \
	   if [ "$$#" -ne 3 ]; then echo "Lane status export page metadata is invalid." >&2; exit 1; fi; \
	   page_total="$$1"; page_returned="$$2"; page_has_more="$$3"; \
	   if [ "$$total" -lt 0 ]; then total="$$page_total"; \
	   elif [ "$$page_total" -ne "$$total" ]; then \
	    echo "Lane status export changed total_matching during pagination." >&2; exit 1; \
	   fi; \
	   next_offset=$$((offset + page_returned)); \
	   expected_more=0; \
	   if [ "$$next_offset" -lt "$$total" ]; then expected_more=1; fi; \
	   if [ "$$page_has_more" -ne "$$expected_more" ]; then \
	    echo "Lane status export pagination metadata is incomplete." >&2; exit 1; \
	   fi; \
	   if [ "$$expected_more" -eq 0 ]; then break; fi; \
	   if [ "$$page_returned" -le 0 ]; then echo "Lane status export pagination made no progress." >&2; exit 1; fi; \
	   offset="$$next_offset"; \
	  done; \
	  if ! "$$resolved_python" -c 'import json, pathlib, sys; directory = pathlib.Path(sys.argv[1]); output = pathlib.Path(sys.argv[2]); rows = []; [rows.extend((lambda document: (document.get("data") if isinstance(document.get("data"), dict) else document)["lanes"])(json.loads(path.read_text()))) for path in sorted(directory.glob("page-*.json"))]; output.write_text(json.dumps({"lanes": rows}) + "\n")' "$$status_dir" "$$status_json"; then \
	   echo "Lane status export could not be assembled." >&2; \
	   exit 1; \
	  fi; \
	 fi; \
	 set -- "$$resolved_python" "$$checker_script" --manifest-dir "$$manifest_dir"; \
	 if [ -n "$$status_json" ]; then set -- "$$@" --lane-status-json "$$status_json"; fi; \
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
