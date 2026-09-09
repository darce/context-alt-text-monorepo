# Tracked lifecycle surface. plan-accept uses the in-repo handler rather than
# the external plugin package.
ACX_LIFECYCLE_HANDLERS ?= scripts/workstate/lifecycle/handlers

.PHONY: plan-accept

plan-accept:
	@ACX_LIFECYCLE_HANDLERS="$(ACX_LIFECYCLE_HANDLERS)" \
		python3 "$(ACX_LIFECYCLE_HANDLERS)/plan_baseline.py" \
			--task "$(TASK)" \
			$(if $(PLAN),--plan "$(PLAN)",)
