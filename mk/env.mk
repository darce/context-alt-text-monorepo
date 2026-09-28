.PHONY: env-render env-examples env-check env-secret-set

SERVICE ?= acx-local

env-render:
	@if [ -z "$(strip $(ENV))" ] || [ -z "$(strip $(TARGET))" ]; then \
		echo 'Usage: make env-render ENV=<env> TARGET=<target> [ADOPT=1]' >&2; \
		exit 2; \
	fi
	@python3 $(ROOT_MAKEFILE_DIR)/scripts/env/render_env.py render --root $(ROOT_MAKEFILE_DIR)/config/env --repo-root $(ROOT_MAKEFILE_DIR) --env "$(ENV)" --target "$(TARGET)" $(if $(filter 1,$(ADOPT)),--adopt,)

env-examples:
	@python3 $(ROOT_MAKEFILE_DIR)/scripts/env/render_env.py render --root $(ROOT_MAKEFILE_DIR)/config/env --repo-root $(ROOT_MAKEFILE_DIR) --all-examples

env-check:
	@python3 $(ROOT_MAKEFILE_DIR)/scripts/env/render_env.py check --root $(ROOT_MAKEFILE_DIR)/config/env --repo-root $(ROOT_MAKEFILE_DIR) --all-examples

env-secret-set:
	@if [ -z "$(strip $(NAME))" ]; then \
		echo 'Usage: make env-secret-set NAME=<name> [SERVICE=<service>]' >&2; \
		exit 2; \
	fi
	@security add-generic-password -U -s "$(SERVICE)" -a "$(NAME)" -w

check-all: env-check
