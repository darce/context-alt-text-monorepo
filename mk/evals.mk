# EVAL-01 zero-rule baseline arm (L6-baseline).
# This branch does not include the L4 eval surface; Makefile include of this
# file is out of this lane's allowlist. The target is still the contract
# `make eval-zero-rule-baseline` once included. Direct invocation:
#   make -f mk/evals.mk eval-zero-rule-baseline
#
# Rule: context-pack echo (title + caption + description). No VLM, no pixels.
# Split: scene/tests/seed/golden.json as L3 left it (20 held-out images).

ROOT_MAKEFILE_DIR ?= $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
EVAL_SERVICE := $(ROOT_MAKEFILE_DIR)/apps/prototype-description-service
EVAL_PYTHON ?= python3

.PHONY: eval-zero-rule-baseline
eval-zero-rule-baseline:
	@cd $(EVAL_SERVICE) && PYTHONPATH=$$PWD $(EVAL_PYTHON) -m scripts.eval_harness.zero_rule_baseline $(EVAL_ARGS)
