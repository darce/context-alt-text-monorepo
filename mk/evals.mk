# =============================================================================
# Eval surface (EVALSURF-1)
# =============================================================================
#
# `/scope` owes every new feature an eval set before the plan exists (canon
# EVAL-01 baselines, EVAL-10 frozen test set). The harness that answers that
# obligation already exists — apps/prototype-description-service/scripts/
# eval_harness/, 30+ modules — but only three of its capabilities had a make
# target (`eval-captions`, `bakeoff-face`, `bakeoff-face-score`, all in the
# root Makefile). Everything else was reachable only by knowing the module
# path, so it was invisible to anyone scoping a feature.
#
# This file adds the missing targets plus one discovery target. It does not
# redefine the three that already exist.
#
# Live vs offline: `eval-captions` and `bakeoff-face` reach the remote OCI
# service. Every target below is artifact -> artifact: no network, no tenant
# writes, no local inference. Inference and full test suites still run
# remotely; these are scorers over already-recorded artifacts.
#
# Contract + env: apps/prototype-description-service/scripts/eval_harness/README.md
# Pinned by: scripts/test_make_eval_targets.py (every module path and flag
# below is asserted against the real argparse surface — rg-006).

.PHONY: eval-list eval-score eval-face-calibrate eval-fusion \
        eval-corpus-inventory eval-strata eval-report test-eval-surface

EVAL_SERVICE := $(ROOT_MAKEFILE_DIR)/apps/prototype-description-service
EVAL_TEST_PYTHON ?= python3

# Keep the eval make-surface contract on the broad scripts gate while running
# it from the service directory so local eval_harness imports win over .pth files.
test-scripts: test-eval-surface
test-eval-surface:
	@cd $(EVAL_SERVICE) && PYTHONPATH=$$PWD $(EVAL_TEST_PYTHON) -m pytest \
		../../scripts/test_make_eval_targets.py -q

## eval-list: enumerate the eval surface (start here when scoping a feature)
eval-list:
	@echo "Eval surface - apps/prototype-description-service/scripts/eval_harness/"
	@echo ""
	@echo "  LIVE (remote OCI inference; needs ACX_EVAL_LIVE=1 + eval-tenant key)"
	@echo "    make eval-captions                                       caption + face run, then score (exit contract 0/1/2/3)"
	@echo "    make bakeoff-face                                        face bake-off candidate walk"
	@echo ""
	@echo "  OFFLINE (artifact -> artifact; no network, no tenant writes)"
	@echo "    make eval-score          RUN_RECORD=<path>               re-score a run record, determinism-checked"
	@echo "    make bakeoff-face-score  FACE_RUN=<path>                 score a recorded face run"
	@echo "    make eval-face-calibrate REPORT=<path> MANIFEST=<path>   threshold calibration (canon CAL-07)"
	@echo "    make eval-fusion                                         staged vs ad-hoc fusion eval"
	@echo "    make eval-report         RUN=<label=path> MANIFEST=<path> OUT=<path>  browser-openable HTML bake-off report"
	@echo ""
	@echo "  CORPUS SELECTION (offline, for building a new eval set)"
	@echo "    make eval-corpus-inventory IMAGES=<dir> OUT=<jsonl>      deterministic no-ML stratification features"
	@echo "    make eval-strata           INVENTORY=<src=path> OUT=<p>  per-stratum operator shortlists"
	@echo ""
	@echo "  Every target takes EVAL_ARGS=\"...\" for pass-through flags."
	@echo ""
	@echo "  Refusal is a correct outcome: a REFUSED metric means the scorer could not"
	@echo "  compute it honestly. Do not bury --allow-refused in a wrapper - consent at"
	@echo "  the call site with EVAL_ARGS='--allow-refused' and say why."
	@echo "  Contract + env: apps/prototype-description-service/scripts/eval_harness/README.md"

## eval-score: offline re-score of a recorded run, with the determinism check on
# RUN_RECORD is relative to apps/prototype-description-service.
# Usage: make eval-score RUN_RECORD=scripts/eval_harness/out/run-<stamp>.json
# Same 0/1/2/3 scorer contract as eval-captions; make collapses nonzero to 2.
eval-score:
	@if [ -z "$(RUN_RECORD)" ]; then \
		echo "error: RUN_RECORD is required (e.g. RUN_RECORD=scripts/eval_harness/out/run-20260820.json)" >&2; \
		exit 2; \
	fi
	@cd $(EVAL_SERVICE) && uv run python -m scripts.eval_harness.cli score \
		--run-record "$(RUN_RECORD)" --check-determinism $(EVAL_ARGS)

## eval-face-calibrate: pick face thresholds from a pinned bake-off report (canon CAL-07)
# Pair-level subject-disjoint K-fold. Writes no settings. OUT optional (default stdout).
# Usage: make eval-face-calibrate REPORT=<face_bakeoff report.json> MANIFEST=<golden.json> [OUT=<path>]
eval-face-calibrate:
	@if [ -z "$(REPORT)" ] || [ -z "$(MANIFEST)" ]; then \
		echo "error: REPORT is required (e.g. REPORT=report.json) and MANIFEST is required (e.g. MANIFEST=golden.json)" >&2; \
		exit 2; \
	fi
	@cd $(EVAL_SERVICE) && uv run python -m scripts.eval_harness.calibrate_face_thresholds \
		--report "$(REPORT)" --manifest "$(MANIFEST)" \
		$(if $(OUT),--out "$(OUT)",) $(EVAL_ARGS)

## eval-fusion: staged vs ad-hoc fusion eval over bakeoff_golden (offline, stubbed adapters)
# Usage: make eval-fusion
#        make eval-fusion EVAL_ARGS="--mode staged --limit 10"
eval-fusion:
	@cd $(EVAL_SERVICE) && uv run python -m scripts.eval_harness.fusion_runner $(EVAL_ARGS)

## eval-report: self-contained HTML bake-off report (one card per image)
# Usage: make eval-report RUN=<label=path> MANIFEST=<path> OUT=<path>.html [EVAL_ARGS="--limit 20 --embed-images"]
eval-report:
	@if [ -z "$(RUN)" ]; then \
		echo "error: RUN is required (e.g. RUN=baseline=scripts/eval_harness/out/run-20260820.json)" >&2; \
		exit 2; \
	fi
	@if [ -z "$(MANIFEST)" ] || [ -z "$(OUT)" ]; then \
		echo "error: MANIFEST and OUT are required" >&2; \
		exit 2; \
	fi
	@cd $(EVAL_SERVICE) && uv run python -m scripts.eval_harness.build_bakeoff_report \
		--run "$(RUN)" --manifest "$(MANIFEST)" --out "$(OUT)" $(EVAL_ARGS)

## eval-corpus-inventory: walk an image dir into deterministic stratification features
# No ML, no network. Resumable: pass EVAL_ARGS="--resume".
# Usage: make eval-corpus-inventory IMAGES=<dir> OUT=<checkpoint.jsonl>
eval-corpus-inventory:
	@if [ -z "$(IMAGES)" ] || [ -z "$(OUT)" ]; then \
		echo "error: IMAGES is required (e.g. IMAGES=corpus/) and OUT is required (e.g. OUT=inventory.json)" >&2; \
		exit 2; \
	fi
	@cd $(EVAL_SERVICE) && uv run python -m scripts.eval_harness.corpus_inventory \
		"$(IMAGES)" --out "$(OUT)" $(EVAL_ARGS)

## eval-strata: bucket a corpus inventory into per-stratum operator shortlists
# INVENTORY takes the runner's repeatable SOURCE=PATH form (e.g. celebs01=inv.jsonl).
# Usage: make eval-strata INVENTORY=celebs01=inv.jsonl OUT=shortlists.json
eval-strata:
	@if [ -z "$(INVENTORY)" ] || [ -z "$(OUT)" ]; then \
		echo "error: INVENTORY is required (e.g. INVENTORY=celebs01=inv.jsonl) and OUT is required (e.g. OUT=shortlists.json)" >&2; \
		exit 2; \
	fi
	@cd $(EVAL_SERVICE) && uv run python -m scripts.eval_harness.strata \
		--inventory "$(INVENTORY)" --out "$(OUT)" $(EVAL_ARGS)
