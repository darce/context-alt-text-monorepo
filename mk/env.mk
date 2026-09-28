.PHONY: env-render env-examples env-check env-secret-set env-materialize

ENV_PYTHON ?= python3
ENV_SECRET_SERVICE ?= acx-local

env-render:
	@if [ -z "$(strip $(ENV))" ] || [ -z "$(strip $(TARGET))" ]; then \
		echo 'Usage: make env-render ENV=<env> TARGET=<target> [ADOPT=1]' >&2; \
		exit 2; \
	fi
	@$(ENV_PYTHON) $(ROOT_MAKEFILE_DIR)/scripts/env/render_env.py render --root $(ROOT_MAKEFILE_DIR)/config/env --repo-root $(ROOT_MAKEFILE_DIR) --env "$(ENV)" --target "$(TARGET)" $(if $(filter 1,$(ADOPT)),--adopt,)

env-materialize:
	@if [ -z "$(strip $(ENV))" ] || [ -z "$(strip $(TARGET))" ]; then \
		echo 'Usage: make env-materialize ENV=<env> TARGET=<target> [APPLY=1] [ADOPT=1] [CONFIRM=<env>]' >&2; \
		exit 2; \
	fi
	@if [ "$(ADOPT)" = 1 ] && [ "$(APPLY)" != 1 ]; then \
		echo 'ADOPT=1 requires APPLY=1' >&2; exit 2; \
	fi
	@if [ "$(ENV)" = prod ] && [ "$(APPLY)" = 1 ] && [ "$(CONFIRM)" != prod ]; then \
		echo 'Production apply requires CONFIRM=prod' >&2; exit 2; \
	fi
	@bash $(ROOT_MAKEFILE_DIR)/scripts/env/materialize_remote.sh "$(ENV)" "$(TARGET)" $(if $(filter 1,$(APPLY)),--apply,--check) $(if $(filter 1,$(ADOPT)),--adopt,)

env-examples:
	@$(ENV_PYTHON) $(ROOT_MAKEFILE_DIR)/scripts/env/render_env.py render --root $(ROOT_MAKEFILE_DIR)/config/env --repo-root $(ROOT_MAKEFILE_DIR) --all-examples

env-check:
	@$(ENV_PYTHON) $(ROOT_MAKEFILE_DIR)/scripts/env/render_env.py check --root $(ROOT_MAKEFILE_DIR)/config/env --repo-root $(ROOT_MAKEFILE_DIR) --all-examples

env-secret-set:
	@if [ -z "$(strip $(NAME))" ]; then \
		echo 'Usage: make env-secret-set NAME=<name> [ENV_SECRET_SERVICE=<service>]' >&2; \
		exit 2; \
	fi
	@security add-generic-password -U -s "$(ENV_SECRET_SERVICE)" -a "$(NAME)" -w

check-all: env-check
