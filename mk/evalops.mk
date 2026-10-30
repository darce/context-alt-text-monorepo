# Read-only artifact measurement; no MCP, model, provider or scheduler calls.
# [TEAM-42] Make repeatable guidance executable (The DevOps Handbook, ch. 20),
# Canon v0.26.2. See docs/runbooks/evalops.md for the evidence contracts.
EVALOPS_PYTHON ?= python3
EVALOPS_ARGS ?=
EVALOPS_RELIABILITY ?=
EVALOPS_FAITHFULNESS ?=
EVALOPS_CATEGORY_PROTOCOL ?=

.PHONY: evalops evalops-vm test-evalops
evalops:
	@$(EVALOPS_PYTHON) "$(ROOT_MAKEFILE_DIR)/benchmarks/tools/evalops/run.py" \
		$(if $(EVALOPS_RELIABILITY),--reliability "$(EVALOPS_RELIABILITY)") \
		$(if $(EVALOPS_FAITHFULNESS),--faithfulness "$(EVALOPS_FAITHFULNESS)") \
		$(if $(EVALOPS_CATEGORY_PROTOCOL),--category-protocol "$(EVALOPS_CATEGORY_PROTOCOL)") \
		$(EVALOPS_ARGS)

# Existing remote_gate.sh runs root targets only with WORKDIR=. explicitly.
# Measurement success includes unavailable quality; this target cannot promote.
evalops-vm: evalops

# One interpreter, no app conftest, models, live databases or parallel workers.
test-evalops:
	@LC_ALL=C $(EVALOPS_PYTHON) -m pytest --noconftest \
		"$(ROOT_MAKEFILE_DIR)/benchmarks/tests/test_evalops_runner.py" \
		"$(ROOT_MAKEFILE_DIR)/benchmarks/tests/test_evalops_score_reliability.py" \
		"$(ROOT_MAKEFILE_DIR)/benchmarks/tests/test_evalops_score_faithfulness.py" \
		-q -p no:cacheprovider
