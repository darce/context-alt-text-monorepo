# Read-only artifact measurement; no MCP, model, provider or scheduler calls.
# [TEAM-42] Make repeatable guidance executable (The DevOps Handbook, ch. 20),
# Canon v0.26.2. See docs/runbooks/evalops.md for the evidence contracts.
EVALOPS_PYTHON ?= python3
EVALOPS_ARGS ?=

.PHONY: evalops
evalops:
	@$(EVALOPS_PYTHON) "$(ROOT_MAKEFILE_DIR)/benchmarks/tools/evalops/run.py" $(EVALOPS_ARGS)
