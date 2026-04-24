.PHONY: help check fix format lint typecheck arch test test-watch check-php php-cs php-cs-fix php-test phpstan mcp projection-reset localwp-link gate-package worker-daemon _php-deps FORCE

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
	@echo "  make gate-package - Build the reproducible plugin ZIP for release/gate verification"
	@echo "  make projection-reset - Truncate ACX projection tables (guarded; requires WP_PATH + confirmation)"
	@echo "  make mcp        - Start the MCP server for AI agents (monorepo-wide)"
	@echo "  make lane-*     - Worktree lane commands (forwarded to root Makefile; run 'make help' from repo root for full list)"
	@echo "  make worker-daemon* - Worker daemon controls (run/status/stop/resume/tail) forwarded to root Makefile"

check:
	@npm run check
	@$(MAKE) php-test
	@$(MAKE) check-php

format:
	@npm run lint:fix
	@npm run format:fix
	@composer cs-fix

fix: format check

lint:
	@npm run lint

typecheck:
	@npm run typecheck

arch:
	@npm run arch

test:
	@npm run test -- --run

test-watch:
	@npm run test:watch

check-php: php-cs phpstan
	@echo "✓ PHP checks passed"

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
