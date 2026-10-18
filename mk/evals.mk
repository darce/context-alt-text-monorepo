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
# `eval-captions` reaches the configured service. `bakeoff-face` runs local
# inference. Artifact scorers make no service/API calls; uv may bootstrap
# dependencies when the environment is not already prepared.
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
	@echo ""
	@echo "  LOCAL INFERENCE (needs GOLDEN_IMAGES_DIR and local YuNet/SFace models)"
	@echo "    make bakeoff-face                                        writes a face run and prunes older outputs"
	@echo ""
	@echo "  OFFLINE (artifact -> artifact; no network, no tenant writes)"
	@echo "    make eval-score          RUN_RECORD=<path>               re-score a run record, determinism-checked"
	@echo "    make bakeoff-face-score  FACE_RUN=<path>                 score a recorded face run"
	@echo "    make eval-face-calibrate REPORT=<path> MANIFEST=<path>   threshold calibration (canon CAL-07)"
	@echo "    make eval-fusion                                         staged vs ad-hoc; writes ignored harness outputs even on refusal"
	@echo "    make eval-report         RUN=<label=path> MANIFEST=<path> OUT=<path>  browser-openable HTML bake-off report"
	@echo ""
	@echo "  CORPUS SELECTION (offline, for building a new eval set)"
	@echo "    make eval-corpus-inventory IMAGES=<dir> OUT=<jsonl>      deterministic no-ML stratification features"
	@echo "    make eval-strata           INVENTORY=<src=path> OUT=<p>  per-stratum operator shortlists"
	@echo ""
	@echo "  BASELINE (offline; EVAL-01 zero-rule arm)"
	@echo "    make eval-zero-rule-baseline                             context-pack echo, no VLM: the floor a model must beat"
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

# =============================================================================
# EVAL-01 zero-rule baseline arm (L6-baseline)
# =============================================================================
#
# Rule: context-pack echo (title + caption + description). No VLM, no pixels.
# Split: scene/tests/seed/held_out_golden.json (frozen held-out reported half).
# EVAL_SERVICE and ROOT_MAKEFILE_DIR are defined above / by the root Makefile.

EVAL_PYTHON ?= python3

.PHONY: eval-zero-rule-baseline
eval-zero-rule-baseline:
	@cd $(EVAL_SERVICE) && PYTHONPATH=$$PWD $(EVAL_PYTHON) -m scripts.eval_harness.zero_rule_baseline $(EVAL_ARGS)

# =============================================================================
# FIRBENCH-1 S6a · one immutable run, then its score (AE-12 tracer entry point)
# =============================================================================
#
# RUN_DIR must resolve under benchmarks/private/ (require_private_output_path); a
# relative RUN_DIR resolves from the repository root. FIR_BENCH_DECISION defaults to the
# committed decision manifest. fir-bench-run needs the bench extra and ACX_EVAL_BENCH=1
# for the insightface leg. fir-bench-score reads files only: dev extra, no eval flag.

FIR_BENCH_DECISION ?= benchmarks/manifests/fir-bench-decision-v1.json
FIR_BENCH_LEGS ?= sface,auraface,insightface
FIR_BENCH_ARMS ?= native

.PHONY: fir-bench-run fir-bench-score fir-bench-report fir-bench-compare fir-bench-unseal

## fir-bench-run: create one immutable FIRBENCH-1 run directory (scoring is a separate step)
# Usage: make fir-bench-run FRAME=<frame_id> RUN_DIR=benchmarks/private/firbench/runs/<run_id>
#        [LEGS=sface,auraface,insightface] [ARMS=native] [SUBSET=N SUBSET_SEED=S] [CREATED_AT=<ISO 8601 with offset>]
fir-bench-run:
	@if [ -z "$(FRAME)" ] || [ -z "$(RUN_DIR)" ]; then \
		echo "error: FRAME and RUN_DIR are required (e.g. FRAME=golden150-v1 RUN_DIR=benchmarks/private/firbench/runs/run-0001)" >&2; \
		exit 2; \
	fi
	@ACX_EVAL_BENCH=1 uv run --directory "$(EVAL_SERVICE)" --locked --extra dev --extra bench \
		python -m scripts.eval_harness.firbench_cli run \
		--frame "$(FRAME)" \
		--decision "$(abspath $(FIR_BENCH_DECISION))" \
		--legs "$(or $(LEGS),$(FIR_BENCH_LEGS))" \
		--arms "$(or $(ARMS),$(FIR_BENCH_ARMS))" \
		$(if $(SUBSET),--subset "$(SUBSET)" --subset-seed "$(SUBSET_SEED)",) \
		$(if $(CREATED_AT),--created-at "$(CREATED_AT)",) \
		--out "$(abspath $(RUN_DIR))"

## fir-bench-score: write scores.json for an existing run (reads files; never rewrites timings.json)
# Usage: make fir-bench-score RUN_DIR=benchmarks/private/firbench/runs/<run_id>
fir-bench-score:
	@if [ -z "$(RUN_DIR)" ]; then \
		echo "error: RUN_DIR is required (e.g. RUN_DIR=benchmarks/private/firbench/runs/run-0001)" >&2; \
		exit 2; \
	fi
	@env -u ACX_EVAL_BENCH uv run --exact --directory "$(EVAL_SERVICE)" --locked --extra dev \
		python -m scripts.eval_harness.firbench_cli score "$(abspath $(RUN_DIR))"

## fir-bench-report: render the private S5 report into <run_dir>/report/ (no eval flag)
# Usage: make fir-bench-report RUN_DIR=benchmarks/private/firbench/runs/<run_id>
fir-bench-report:
	@if [ -z "$(RUN_DIR)" ]; then \
		echo "error: RUN_DIR is required (e.g. RUN_DIR=benchmarks/private/firbench/runs/run-0001)" >&2; \
		exit 2; \
	fi
	@uv run --directory "$(EVAL_SERVICE)" --locked --extra dev \
		python -m scripts.eval_harness.firbench_cli report "$(abspath $(RUN_DIR))"

## fir-bench-compare: compare two scored runs; OUT must lie under benchmarks/private/
# Usage: make fir-bench-compare RUN_A=<run dir> RUN_B=<run dir> OUT=<private dir> [TREATMENT=<field>]
fir-bench-compare:
	@if [ -z "$(RUN_A)" ] || [ -z "$(RUN_B)" ] || [ -z "$(OUT)" ]; then \
		echo "error: RUN_A, RUN_B and OUT are required" >&2; \
		exit 2; \
	fi
	@uv run --directory "$(EVAL_SERVICE)" --locked --extra dev \
		python -m scripts.eval_harness.firbench_cli compare \
		"$(abspath $(RUN_A))" "$(abspath $(RUN_B))" --out "$(abspath $(OUT))" \
		$(if $(TREATMENT),--treatment "$(TREATMENT)",)

## fir-bench-unseal: append one unspent unseal token; the ledger stays local under benchmarks/private/
# Usage: make fir-bench-unseal FRAME=<sealed frame_id> RUN_ID=<run_id> [FIR_BENCH_DECISION=<decision.json>]
fir-bench-unseal:
	@if [ -z "$(FRAME)" ] || [ -z "$(RUN_ID)" ]; then \
		echo "error: FRAME and RUN_ID are required" >&2; \
		exit 2; \
	fi
	@uv run --directory "$(EVAL_SERVICE)" --locked --extra dev \
		python -m scripts.eval_harness.firbench_cli unseal \
		--decision "$(abspath $(FIR_BENCH_DECISION))" --frame "$(FRAME)" --run-id "$(RUN_ID)"

# =============================================================================
# FIRBENCH-1 S9 · simulated acceptance: AE-2b, AE-3, AE-4 and the H2/MDE/floor/stage rows
# =============================================================================
#
# Synthetic only. The simulator writes acceptance.json under benchmarks/private/ and never changes the real
# decision, fixture or run inputs. full_acceptance_evidence is true only when every suite ran at R=2000 with the
# manifest n_boot; AE-10 and real-data AE-5/6/12 evidence stay pending until supplied and verified. Dev profile
# only (no bench extra, no InsightFace), ACX_EVAL_BENCH unset, single-process pytest.

FIR_BENCH_SIM_PARAMS ?= apps/prototype-description-service/scene/tests/fixtures/firbench_sim_v1.json
FIR_BENCH_ACCEPTANCE_OUT ?= benchmarks/private/firbench/acceptance
FIR_BENCH_ACCEPTANCE_SUITES ?= null,selection,coverage,power,noninferiority,mde,floor,stage
# Service-relative, because pytest runs from EVAL_SERVICE. AE-1 known answers, AE-6 legacy parity,
# AE-7 replay, AE-8 cache, AE-9 refusals.
FIR_BENCH_AE_FIXTURE_TESTS ?= scene/tests/test_eval_harness_firbench_contract.py \
	scene/tests/test_eval_harness_firbench_score.py \
	scene/tests/test_eval_harness_firbench_clusters.py \
	scene/tests/test_eval_harness_firbench_face_outcomes.py \
	scene/tests/test_eval_harness_firbench_score_calibration.py \
	scene/tests/test_eval_harness_firbench_frames_partition.py \
	scene/tests/test_eval_harness_firbench_cache_runtime.py \
	scene/tests/test_eval_harness_firbench_compare_compatibility.py \
	scene/tests/test_eval_harness_firbench_compare_seals.py \
	scene/tests/test_eval_harness_firbench_cli_integration.py \
	scene/tests/test_eval_harness_firbench_report_binding.py \
	scene/tests/test_eval_harness_firbench_score_timing_semantics.py

.PHONY: fir-bench-acceptance

## fir-bench-acceptance: simulated AE-2b/AE-3/AE-4 suites, then the AE-1 and AE-6..AE-9 fixture modules
# Usage: make fir-bench-acceptance [FIR_BENCH_ACCEPTANCE_REPLICATES=<int>] [FIR_BENCH_ACCEPTANCE_SEED=<int>] [FIR_BENCH_ACCEPTANCE_OUT=<private dir>]
#        Unset, the replicates and seed come from the fixture (R=2000) and the master seed inside the CLI.
fir-bench-acceptance:
	@env -u ACX_EVAL_BENCH uv run --exact --directory "$(EVAL_SERVICE)" --locked --extra dev \
		python -m scripts.eval_harness.firbench_selftest \
		--params "$(abspath $(FIR_BENCH_SIM_PARAMS))" \
		--decision "$(abspath $(FIR_BENCH_DECISION))" \
		--out "$(abspath $(FIR_BENCH_ACCEPTANCE_OUT))" \
		--suites "$(FIR_BENCH_ACCEPTANCE_SUITES)" \
		$(if $(FIR_BENCH_ACCEPTANCE_REPLICATES),--replicates "$(FIR_BENCH_ACCEPTANCE_REPLICATES)",) \
		$(if $(FIR_BENCH_ACCEPTANCE_SEED),--seed "$(FIR_BENCH_ACCEPTANCE_SEED)",)
	@env -u ACX_EVAL_BENCH uv run --exact --directory "$(EVAL_SERVICE)" --locked --extra dev \
		python -m pytest $(FIR_BENCH_AE_FIXTURE_TESTS) -n0 -q --tb=short -p no:cacheprovider
