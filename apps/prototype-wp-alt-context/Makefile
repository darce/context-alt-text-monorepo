.PHONY: help check fix format lint lint-fix typecheck arch test test-watch check-php php-cs php-cs-fix php-test phpstan mcp projection-reset localwp-link localwp-verify-activation localwp-mirror-integrity localwp-batch-run-smoke localwp-describe-run-smoke localwp-description-cli-smoke gate-package worker-daemon _js-deps _php-deps FORCE

NPM ?= corepack npm

help:
	@echo "Available commands:"
	@echo "  make check      - Run all checks (lint, types, arch, tests, PHP)"
	@echo "  make fix        - Auto-fix lint/format then run checks"
	@echo "  make format     - Auto-fix lint/format without running checks"
	@echo "  make lint       - Run ESLint"
	@echo "  make typecheck  - Run TypeScript checks"
	@echo "  make arch       - Run frontend architecture compliance checks"
	@echo "  make test       - Run frontend tests (vitest run)"
	@echo "  make test-watch - Run frontend tests in watch mode"
	@echo "  make check-php  - Run plugin PHP checks (cs, phpunit, phpstan)"
	@echo "  make php-cs-fix - Auto-fix plugin PHP style violations (PHPCBF)"
	@echo "  make localwp-link - Symlink plugin into a LocalWP site from a stable checkout (guarded)"
	@echo "  make localwp-verify-activation - Re-run plugin activation cycle (deactivate + activate) through LocalWP WP-CLI; runs lifecycle hooks, not a dry run"
	@echo "  make localwp-mirror-integrity - Run the mirror integrity WP-CLI check through the LocalWP wrapper"
	@echo "  make localwp-batch-run-smoke - Submit a real LocalWP batch scan through the REST API and poll the BatchRun aggregate"
	@echo "  make localwp-describe-run-smoke - Describe one real LocalWP image attachment twice and prove the cache (first miss, repeat hit)"
	@echo "  make localwp-description-cli-smoke - Run WP-CLI description status/generate smoke checks against LocalWP"
	@echo "  make gate-package - Build the reproducible plugin ZIP for release/gate verification"
	@echo "  make projection-reset - Truncate ACX projection tables (guarded; requires WP_PATH + confirmation)"
	@echo "  make mcp        - Start the MCP server for AI agents (monorepo-wide)"
	@echo "  make lane-*     - Worktree lane commands (forwarded to root Makefile; run 'make help' from repo root for full list)"
	@echo "  make worker-daemon* - Worker daemon controls (run/status/stop/resume/tail) forwarded to root Makefile"

check: _js-deps
	@$(NPM) run check
	@$(MAKE) php-test
	@$(MAKE) check-php

# LINTGATE1-NEW-02: `npm run lint:fix` is deliberately NOT part of this target.
# Only 25 eslint violations are autofixable, but they include
# @typescript-eslint/no-unnecessary-type-assertion and
# non-nullable-type-assertion-style, which strip assertions that type inference
# depends on. Applying them collapses those expressions to `any` and detonates
# the no-unsafe-* family: measured 77 -> 6,139 problems via
# `eslint . --fix-dry-run -f json`. Prettier (`format:fix`) is safe -- it never
# edits types. Run `make lint-fix` if you explicitly want the eslint autofixer.
format: _js-deps
	@$(NPM) run format:fix
	@$(MAKE) php-cs-fix

# Opt-in only. See the LINTGATE1-NEW-02 note on `format` before running this:
# it can take the tree from 77 to ~6,139 eslint problems in one invocation.
lint-fix: _js-deps
	@echo "WARNING: eslint --fix strips type assertions and has measured 77 -> 6,139 problems."
	@echo "Review the diff before committing. Ctrl-C within 5s to abort."
	@sleep 5
	@$(NPM) run lint:fix

fix: format check

lint: _js-deps
	@$(NPM) run lint

typecheck: _js-deps
	@$(NPM) run typecheck

arch: _js-deps
	@$(NPM) run arch

test: _js-deps
	@$(NPM) run test -- --run

test-watch: _js-deps
	@$(NPM) run test:watch

check-php: php-cs phpstan
	@echo "✓ PHP checks passed"

# Pre-flight installer: if the plugin's Node dev dependencies are missing,
# install them once so local make targets work in fresh linked worktrees.
_js-deps:
	@if [ ! -x node_modules/.bin/eslint ] || [ ! -x node_modules/.bin/prettier ] || [ ! -x node_modules/.bin/tsc ] || [ ! -x node_modules/.bin/vitest ]; then \
		echo "Plugin Node dev dependencies missing; installing..."; \
		$(NPM) ci --allow-remote=all --no-fund --no-audit; \
	fi

# Pre-flight installer: if the plugin's composer dev dependencies are missing,
# install them once so PHPCS/PHPCBF/PHPUnit are on disk before the target runs.
# Mirrors the existing phpstan guard at line 62 below.
_php-deps:
	@if [ ! -x vendor/bin/phpcbf ] || [ ! -x vendor/bin/phpcs ] || [ ! -x vendor/bin/phpunit ]; then \
		echo "Plugin composer dev dependencies missing; installing..."; \
		composer install --prefer-dist --no-interaction; \
	fi

php-cs: _php-deps
	@composer cs-check

php-cs-fix: _php-deps
	@composer phpcbf

php-test: _php-deps
	@composer test

phpstan:
	@if [ ! -x vendor/bin/phpstan ]; then \
		echo "phpstan is not installed in vendor/bin."; \
		echo "Run 'composer update phpstan/phpstan' when Packagist access is available."; \
		exit 1; \
	fi
	@composer phpstan

mcp:
	@cd ../.. && make mcp-start

localwp-link:
	@bash scripts/localwp/link-plugin.sh \
		--wp-path "$(WP_PATH)" \
		$(if $(PLUGIN_SOURCE),--plugin-source "$(PLUGIN_SOURCE)",) \
		$(if $(filter 1,$(OVERWRITE)),--overwrite,) \
		$(if $(filter 1,$(ALLOW_WORKTREE_SOURCE)),--allow-worktree-source,) \
		$(if $(filter 1,$(DRY_RUN)),--dry-run,)

gate-package:
	@bash scripts/release/package-plugin.sh $(if $(filter 1,$(NO_BUILD)),--no-build,)

# Forward all lane-* targets to root Makefile (single rule, never goes stale)
FORCE:

ORCHESTRATOR_ROOT_CMD = git rev-parse --path-format=absolute --git-common-dir | sed 's,/.git$$,,'
ROOT_MAKEFILE_CMD = "$$($(ORCHESTRATOR_ROOT_CMD))/Makefile"
LANE_WORKTREE_CMD = "$$(git rev-parse --show-toplevel)"

lane-%: FORCE
	@$(MAKE) -f $(ROOT_MAKEFILE_CMD) -C $(LANE_WORKTREE_CMD) $@

worker-daemon: FORCE
	@$(MAKE) -f $(ROOT_MAKEFILE_CMD) -C $(LANE_WORKTREE_CMD) $@

worker-daemon-%: FORCE
	@$(MAKE) -f $(ROOT_MAKEFILE_CMD) -C $(LANE_WORKTREE_CMD) $@

# Destructive helper for local sovereign split-brain recovery after backend reset.
# Usage:
#   make projection-reset WP_PATH="/path/to/wordpress/site" CONFIRM_ACX_PROJECTION_RESET="RESET"
#
# LocalWP socket auto-discovery: When DB_HOST is 'localhost', PHP needs the
# correct mysqli.default_socket to reach LocalWP's MySQL.  This target
# auto-discovers the socket under ~/Library/Application Support/Local/run/
# and passes it via `php -d mysqli.default_socket=...` so WP-CLI connects.
# Override with LOCALWP_SOCKET if auto-discovery picks the wrong site.
projection-reset:
	@if [ -z "$(WP_PATH)" ]; then \
		echo "WP_PATH is required (path to WordPress root containing wp-load.php)."; \
		echo "Example: make projection-reset WP_PATH=\"$$HOME/Local Sites/my-site/app/public\" CONFIRM_ACX_PROJECTION_RESET=\"RESET\""; \
		exit 1; \
	fi
	@if [ "$(CONFIRM_ACX_PROJECTION_RESET)" != "RESET" ]; then \
		echo "Refusing destructive action."; \
		echo "Re-run with CONFIRM_ACX_PROJECTION_RESET=\"RESET\" to confirm."; \
		exit 1; \
	fi
	@if [ ! -f "$(WP_PATH)/wp-load.php" ]; then \
		echo "Invalid WP_PATH: $(WP_PATH) (missing wp-load.php)"; \
		exit 1; \
	fi
	@_LOCALWP_WP="$$(git rev-parse --show-toplevel)/scripts/localwp-wp.sh"; \
	if [ ! -x "$$_LOCALWP_WP" ]; then \
		echo "LocalWP WP-CLI wrapper missing or not executable: $$_LOCALWP_WP"; \
		exit 1; \
	fi; \
	_run_wp() { "$$_LOCALWP_WP" "$$@"; }; \
	SITE_URL_RAW="$$(_run_wp --quiet --skip-plugins --skip-themes --path="$(WP_PATH)" option get siteurl 2>&1 || true)"; \
	if printf '%s\n' "$$SITE_URL_RAW" | grep -qi 'Error establishing a database connection\|Can'"'"'t connect\|Connection refused'; then \
		echo "Database connection failed at $(WP_PATH)."; \
		echo "Start your local WordPress environment (e.g. LocalWP) and try again."; \
		echo "WP-CLI output: $$SITE_URL_RAW"; \
		exit 1; \
	fi; \
	SITE_URL="$$(printf '%s\n' "$$SITE_URL_RAW" | sed '/^Deprecated:/d;/^Warning:/d;/^Notice:/d;/^PHP Deprecated:/d;/^PHP Warning:/d;/^PHP Notice:/d;/^PHP Fatal/d;/^Error:/d' | awk 'NF { print; exit }')"; \
	if [ -z "$$SITE_URL" ]; then \
		echo "Unable to read siteurl from WordPress at $(WP_PATH)."; \
		echo "WP-CLI output: $$SITE_URL_RAW"; \
		exit 1; \
	fi; \
	case "$$SITE_URL" in \
		*localhost*|*127.0.0.1*|*.local*|*.test*) ;; \
		*) \
			if [ "$(ALLOW_NON_LOCAL)" != "1" ]; then \
				echo "Refusing to run against non-local siteurl: $$SITE_URL"; \
				echo "Set ALLOW_NON_LOCAL=1 only if you are intentionally targeting this environment."; \
				exit 1; \
			fi ;; \
	esac; \
	echo "Resetting ACX projection tables on $$SITE_URL..."; \
	_run_wp --path="$(WP_PATH)" acx reset-projection --yes

# Non-destructive helper that reports suspicious mirror rows before the local
# projection is treated as trustworthy.
# Usage:
#   make localwp-mirror-integrity WP_PATH="/path/to/wordpress/site"
#   make localwp-mirror-integrity WP_PATH="/path/to/wordpress/site" THRESHOLD="0.999" LIMIT="50" FORMAT="json"
#   make localwp-mirror-integrity WP_PATH="/path/to/wordpress/site" ATTACHMENT_ID="6624"
localwp-mirror-integrity:
	@if [ -z "$(WP_PATH)" ]; then \
		echo "WP_PATH is required (path to WordPress root containing wp-load.php)."; \
		echo "Example: make localwp-mirror-integrity WP_PATH=\"$$HOME/Development/wp-context-alt-text/app/public\" THRESHOLD=\"0.999\" LIMIT=\"50\" FORMAT=\"table\""; \
		exit 1; \
	fi
	@if [ ! -f "$(WP_PATH)/wp-load.php" ]; then \
		echo "Invalid WP_PATH: $(WP_PATH) (missing wp-load.php)"; \
		exit 1; \
	fi
	@_LOCALWP_WP="$$(git rev-parse --show-toplevel)/scripts/localwp-wp.sh"; \
	if [ ! -x "$$_LOCALWP_WP" ]; then \
		echo "LocalWP WP-CLI wrapper missing or not executable: $$_LOCALWP_WP"; \
		exit 1; \
	fi; \
	ARGS=""; \
	if [ -n "$(ATTACHMENT_ID)" ]; then ARGS="$$ARGS --attachment-id=$(ATTACHMENT_ID)"; fi; \
	if [ -n "$(THRESHOLD)" ]; then ARGS="$$ARGS --threshold=$(THRESHOLD)"; fi; \
	if [ -n "$(LIMIT)" ]; then ARGS="$$ARGS --limit=$(LIMIT)"; fi; \
	if [ -n "$(FORMAT)" ]; then ARGS="$$ARGS --format=$(FORMAT)"; fi; \
	"$$_LOCALWP_WP" --path="$(WP_PATH)" acx mirror-integrity $$ARGS

# Re-run the plugin lifecycle (deactivate + activate) against a LocalWP site
# and optionally gate elapsed time. This is an execution check, not a dry run.
# Usage:
#   make localwp-verify-activation WP_PATH="/path/to/wordpress/site"
#   make localwp-verify-activation WP_PATH="/path/to/wordpress/site" ACTIVATION_BUDGET_SECONDS="10"
localwp-verify-activation:
	@if [ -z "$(WP_PATH)" ]; then \
		echo "WP_PATH is required (path to WordPress root containing wp-load.php)."; \
		echo "Example: make localwp-verify-activation WP_PATH=\"$$HOME/Development/wp-context-alt-text/app/public\" ACTIVATION_BUDGET_SECONDS=\"10\""; \
		exit 1; \
	fi
	@if [ ! -f "$(WP_PATH)/wp-load.php" ]; then \
		echo "Invalid WP_PATH: $(WP_PATH) (missing wp-load.php)"; \
		exit 1; \
	fi
	@_LOCALWP_WP="$$(git rev-parse --show-toplevel)/scripts/localwp-wp.sh"; \
	if [ ! -x "$$_LOCALWP_WP" ]; then \
		echo "LocalWP WP-CLI wrapper missing or not executable: $$_LOCALWP_WP"; \
		exit 1; \
	fi; \
	_run_wp() { "$$_LOCALWP_WP" "$$@"; }; \
	SITE_URL_RAW="$$(_run_wp --quiet --skip-plugins --skip-themes --path="$(WP_PATH)" option get siteurl 2>&1 || true)"; \
	if printf '%s\n' "$$SITE_URL_RAW" | grep -qi 'Error establishing a database connection\|Can'"'"'t connect\|Connection refused'; then \
		echo "Database connection failed at $(WP_PATH)."; \
		echo "Start your local WordPress environment (e.g. LocalWP) and try again."; \
		echo "WP-CLI output: $$SITE_URL_RAW"; \
		exit 1; \
	fi; \
	SITE_URL="$$(printf '%s\n' "$$SITE_URL_RAW" | sed '/^Deprecated:/d;/^Warning:/d;/^Notice:/d;/^PHP Deprecated:/d;/^PHP Warning:/d;/^PHP Notice:/d;/^PHP Fatal/d;/^Error:/d' | awk 'NF { print; exit }')"; \
	if [ -z "$$SITE_URL" ]; then \
		echo "Unable to read siteurl from WordPress at $(WP_PATH)."; \
		echo "WP-CLI output: $$SITE_URL_RAW"; \
		exit 1; \
	fi; \
	case "$$SITE_URL" in \
		*localhost*|*127.0.0.1*|*.local*|*.test*) ;; \
		*) \
			echo "Refusing to run against non-local siteurl: $$SITE_URL"; \
			exit 1; \
			;; \
	esac; \
	DEACTIVATE_OUTPUT="$$(_run_wp --path="$(WP_PATH)" plugin deactivate alt-context 2>&1 || true)"; \
	START_MS="$$(python3 -c 'import time; print(time.time_ns() // 1000000)')"; \
	ACTIVATE_OUTPUT="$$(_run_wp --path="$(WP_PATH)" plugin activate alt-context 2>&1)"; \
	ACTIVATE_STATUS="$$?"; \
	END_MS="$$(python3 -c 'import time; print(time.time_ns() // 1000000)')"; \
	if [ "$$ACTIVATE_STATUS" -ne 0 ]; then \
		echo "Plugin activation failed for $$SITE_URL."; \
		if [ -n "$$DEACTIVATE_OUTPUT" ]; then \
			echo "Deactivate output (suppressed before activate failure):"; \
			echo "$$DEACTIVATE_OUTPUT"; \
		fi; \
		echo "$$ACTIVATE_OUTPUT"; \
		exit "$$ACTIVATE_STATUS"; \
	fi; \
	IS_ACTIVE_OUTPUT="$$(_run_wp --quiet --path="$(WP_PATH)" plugin is-active alt-context 2>&1)"; \
	IS_ACTIVE_STATUS="$$?"; \
	if [ "$$IS_ACTIVE_STATUS" -ne 0 ]; then \
		echo "Plugin is not active after verification for $$SITE_URL."; \
		echo "$$IS_ACTIVE_OUTPUT"; \
		exit "$$IS_ACTIVE_STATUS"; \
	fi; \
	ELAPSED_MS="$$(( END_MS - START_MS ))"; \
	ELAPSED_SECONDS="$$(awk -v ms="$$ELAPSED_MS" 'BEGIN { printf "%.3f", ms / 1000 }')"; \
	if [ -n "$(ACTIVATION_BUDGET_SECONDS)" ]; then \
		BUDGET_MS="$$(python3 -c 'import sys; value = float(sys.argv[1]); sys.exit(1) if value < 0 else print(int(round(value * 1000)))' "$(ACTIVATION_BUDGET_SECONDS)")" || { \
			echo "Invalid ACTIVATION_BUDGET_SECONDS: $(ACTIVATION_BUDGET_SECONDS)"; \
			exit 1; \
		}; \
		if [ "$$ELAPSED_MS" -gt "$$BUDGET_MS" ]; then \
			echo "Plugin activation exceeded budget for $$SITE_URL: $${ELAPSED_SECONDS}s > $(ACTIVATION_BUDGET_SECONDS)s"; \
			exit 1; \
		fi; \
	fi; \
	echo "Plugin activation verified for $$SITE_URL in $${ELAPSED_SECONDS}s"; \
	if [ -n "$(ACTIVATION_BUDGET_SECONDS)" ]; then \
		echo "Activation budget: $(ACTIVATION_BUDGET_SECONDS)s"; \
	fi

# Submit a real LocalWP recognition batch run through the REST surface and
# poll the plugin-owned BatchRun aggregate until it reaches a terminal state.
# Usage:
#   make localwp-batch-run-smoke WP_PATH="/path/to/wordpress/site"
#   make localwp-batch-run-smoke WP_PATH="/path/to/wordpress/site" SMOKE_LIMIT="100" BATCH_SIZE="5"
localwp-batch-run-smoke:
	@if [ -z "$(WP_PATH)" ]; then \
		echo "WP_PATH is required (path to WordPress root containing wp-load.php)."; \
		echo "Example: make localwp-batch-run-smoke WP_PATH=\"$$HOME/Development/wp-context-alt-text/app/public\" SMOKE_LIMIT=\"100\" BATCH_SIZE=\"5\""; \
		exit 1; \
	fi
	@if [ ! -f "$(WP_PATH)/wp-load.php" ]; then \
		echo "Invalid WP_PATH: $(WP_PATH) (missing wp-load.php)"; \
		exit 1; \
	fi
	@_LOCALWP_WP="$$(git rev-parse --show-toplevel)/scripts/localwp-wp.sh"; \
	if [ ! -x "$$_LOCALWP_WP" ]; then \
		echo "LocalWP WP-CLI wrapper missing or not executable: $$_LOCALWP_WP"; \
		exit 1; \
	fi; \
	_run_wp() { "$$_LOCALWP_WP" "$$@"; }; \
	SITE_URL_RAW="$$(_run_wp --quiet --skip-plugins --skip-themes --path="$(WP_PATH)" option get siteurl 2>&1 || true)"; \
	if printf '%s\n' "$$SITE_URL_RAW" | grep -qi 'Error establishing a database connection\|Can'"'"'t connect\|Connection refused'; then \
		echo "Database connection failed at $(WP_PATH)."; \
		echo "Start your local WordPress environment (e.g. LocalWP) and try again."; \
		echo "WP-CLI output: $$SITE_URL_RAW"; \
		exit 1; \
	fi; \
	SITE_URL="$$(printf '%s\n' "$$SITE_URL_RAW" | sed '/^Deprecated:/d;/^Warning:/d;/^Notice:/d;/^PHP Deprecated:/d;/^PHP Warning:/d;/^PHP Notice:/d;/^PHP Fatal/d;/^Error:/d' | awk 'NF { print; exit }')"; \
	if [ -z "$$SITE_URL" ]; then \
		echo "Unable to read siteurl from WordPress at $(WP_PATH)."; \
		echo "WP-CLI output: $$SITE_URL_RAW"; \
		exit 1; \
	fi; \
	case "$$SITE_URL" in \
		*localhost*|*127.0.0.1*|*.local*|*.test*) ;; \
		*) \
			echo "Refusing to run against non-local siteurl: $$SITE_URL"; \
			exit 1; \
			;; \
	esac; \
	CURRENT_SOURCE="$$(_run_wp --quiet --path="$(WP_PATH)" option get acx_recognition_source 2>/dev/null || true)"; \
	CURRENT_SOURCE="$$(printf '%s\n' "$$CURRENT_SOURCE" | sed 's/^[[:space:]]*//;s/[[:space:]]*$$//' | head -n 1)"; \
	if [ "$$CURRENT_SOURCE" != "local" ]; then \
		echo "Switching LocalWP recognition source to local for smoke verification (was: $${CURRENT_SOURCE:-<empty>})."; \
		_run_wp --path="$(WP_PATH)" option update acx_recognition_source local >/dev/null; \
	fi; \
	_run_wp --path="$(WP_PATH)" eval-file "$(CURDIR)/scripts/localwp/batch-run-smoke.php" "$(if $(SMOKE_LIMIT),$(SMOKE_LIMIT),100)" "$(if $(BATCH_SIZE),$(BATCH_SIZE),5)" "$(if $(TIMEOUT_SECONDS),$(TIMEOUT_SECONDS),240)" "$(if $(POLL_INTERVAL_MS),$(POLL_INTERVAL_MS),1000)"

# E19-1 S7: dispatch one real LocalWP image attachment through
# POST /acx/v1/recognition/describe twice and prove the cache by natural
# repeat (first populates, second returns cached=true). Same local-only guard
# block as localwp-batch-run-smoke.
# Usage:
#   make localwp-describe-run-smoke WP_PATH="/path/to/wordpress/site"
#   make localwp-describe-run-smoke WP_PATH="/path/to/wordpress/site" MEDIA_ID="6624"
localwp-describe-run-smoke:
	@if [ -z "$(WP_PATH)" ]; then \
		echo "WP_PATH is required (path to WordPress root containing wp-load.php)."; \
		echo "Example: make localwp-describe-run-smoke WP_PATH=\"$$HOME/Development/wp-context-alt-text/app/public\" MEDIA_ID=\"6624\""; \
		exit 1; \
	fi
	@if [ ! -f "$(WP_PATH)/wp-load.php" ]; then \
		echo "Invalid WP_PATH: $(WP_PATH) (missing wp-load.php)"; \
		exit 1; \
	fi
	@_LOCALWP_WP="$$(git rev-parse --show-toplevel)/scripts/localwp-wp.sh"; \
	if [ ! -x "$$_LOCALWP_WP" ]; then \
		echo "LocalWP WP-CLI wrapper missing or not executable: $$_LOCALWP_WP"; \
		exit 1; \
	fi; \
	_run_wp() { "$$_LOCALWP_WP" "$$@"; }; \
	SITE_URL_RAW="$$(_run_wp --quiet --skip-plugins --skip-themes --path="$(WP_PATH)" option get siteurl 2>&1 || true)"; \
	if printf '%s\n' "$$SITE_URL_RAW" | grep -qi 'Error establishing a database connection\|Can'"'"'t connect\|Connection refused'; then \
		echo "Database connection failed at $(WP_PATH)."; \
		echo "Start your local WordPress environment (e.g. LocalWP) and try again."; \
		echo "WP-CLI output: $$SITE_URL_RAW"; \
		exit 1; \
	fi; \
	SITE_URL="$$(printf '%s\n' "$$SITE_URL_RAW" | sed '/^Deprecated:/d;/^Warning:/d;/^Notice:/d;/^PHP Deprecated:/d;/^PHP Warning:/d;/^PHP Notice:/d;/^PHP Fatal/d;/^Error:/d' | awk 'NF { print; exit }')"; \
	if [ -z "$$SITE_URL" ]; then \
		echo "Unable to read siteurl from WordPress at $(WP_PATH)."; \
		echo "WP-CLI output: $$SITE_URL_RAW"; \
		exit 1; \
	fi; \
	case "$$SITE_URL" in \
		*localhost*|*127.0.0.1*|*.local*|*.test*) ;; \
		*) \
			echo "Refusing to run against non-local siteurl: $$SITE_URL"; \
			exit 1; \
			;; \
	esac; \
	CURRENT_SOURCE="$$(_run_wp --quiet --path="$(WP_PATH)" option get acx_recognition_source 2>/dev/null || true)"; \
	CURRENT_SOURCE="$$(printf '%s\n' "$$CURRENT_SOURCE" | sed 's/^[[:space:]]*//;s/[[:space:]]*$$//' | head -n 1)"; \
	if [ "$$CURRENT_SOURCE" != "local" ]; then \
		echo "Switching LocalWP recognition source to local for smoke verification (was: $${CURRENT_SOURCE:-<empty>})."; \
		_run_wp --path="$(WP_PATH)" option update acx_recognition_source local >/dev/null; \
	fi; \
	_run_wp --path="$(WP_PATH)" eval-file "$(CURDIR)/scripts/localwp/describe-run-smoke.php" "$(if $(MEDIA_ID),$(MEDIA_ID),0)"

# Run the headless description CLI surface against one LocalWP attachment.
# Dry-run is always executed; set WRITE=1 to also write alt text with --force
# only when FORCE=1 is provided.
# Usage:
#   make localwp-description-cli-smoke WP_PATH="/path/to/wordpress/site" MEDIA_ID="6624"
#   make localwp-description-cli-smoke WP_PATH="/path/to/wordpress/site" MEDIA_ID="6624" WRITE=1 FORCE=1
localwp-description-cli-smoke:
	@if [ -z "$(WP_PATH)" ]; then \
		echo "WP_PATH is required (path to WordPress root containing wp-load.php)."; \
		echo "Example: make localwp-description-cli-smoke WP_PATH=\"$$HOME/Development/wp-context-alt-text/app/public\" MEDIA_ID=\"6624\""; \
		exit 1; \
	fi
	@if [ -z "$(MEDIA_ID)" ]; then \
		echo "MEDIA_ID is required for the CLI smoke target."; \
		exit 1; \
	fi
	@if [ ! -f "$(WP_PATH)/wp-load.php" ]; then \
		echo "Invalid WP_PATH: $(WP_PATH) (missing wp-load.php)"; \
		exit 1; \
	fi
	@_LOCALWP_WP="$$(git rev-parse --show-toplevel)/scripts/localwp-wp.sh"; \
	if [ ! -x "$$_LOCALWP_WP" ]; then \
		echo "LocalWP WP-CLI wrapper missing or not executable: $$_LOCALWP_WP"; \
		exit 1; \
	fi; \
	_run_wp() { "$$_LOCALWP_WP" "$$@"; }; \
	SITE_URL_RAW="$$(_run_wp --quiet --skip-plugins --skip-themes --path="$(WP_PATH)" option get siteurl 2>&1 || true)"; \
	if printf '%s\n' "$$SITE_URL_RAW" | grep -qi 'Error establishing a database connection\|Can'"'"'t connect\|Connection refused'; then \
		echo "Database connection failed at $(WP_PATH)."; \
		echo "Start your local WordPress environment (e.g. LocalWP) and try again."; \
		echo "WP-CLI output: $$SITE_URL_RAW"; \
		exit 1; \
	fi; \
	SITE_URL="$$(printf '%s\n' "$$SITE_URL_RAW" | sed '/^Deprecated:/d;/^Warning:/d;/^Notice:/d;/^PHP Deprecated:/d;/^PHP Warning:/d;/^PHP Notice:/d;/^PHP Fatal/d;/^Error:/d' | awk 'NF { print; exit }')"; \
	if [ -z "$$SITE_URL" ]; then \
		echo "Unable to read siteurl from WordPress at $(WP_PATH)."; \
		echo "WP-CLI output: $$SITE_URL_RAW"; \
		exit 1; \
	fi; \
	case "$$SITE_URL" in \
		*localhost*|*127.0.0.1*|*.local*|*.test*) ;; \
		*) \
			echo "Refusing to run against non-local siteurl: $$SITE_URL"; \
			exit 1; \
			;; \
	esac; \
	_run_wp --path="$(WP_PATH)" alt-context describe status --media-id="$(MEDIA_ID)" --format=json; \
	_run_wp --path="$(WP_PATH)" alt-context describe generate --media-id="$(MEDIA_ID)" --format=json; \
	if [ "$(WRITE)" = "1" ]; then \
		FORCE_ARG=""; \
		if [ "$(FORCE)" = "1" ]; then FORCE_ARG="--force"; fi; \
		_run_wp --path="$(WP_PATH)" alt-context describe generate --media-id="$(MEDIA_ID)" --write $$FORCE_ARG --format=json; \
	fi
