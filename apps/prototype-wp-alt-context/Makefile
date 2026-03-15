.PHONY: help check fix lint typecheck arch test test-watch check-php php-cs php-cs-fix php-test phpstan mcp projection-reset worker-daemon FORCE

help:
	@echo "Available commands:"
	@echo "  make check      - Run all checks (lint, types, arch, tests, PHP)"
	@echo "  make fix        - Auto-fix lint/format then run checks"
	@echo "  make lint       - Run ESLint"
	@echo "  make typecheck  - Run TypeScript checks"
	@echo "  make arch       - Run frontend architecture compliance checks"
	@echo "  make test       - Run frontend tests (vitest run)"
	@echo "  make test-watch - Run frontend tests in watch mode"
	@echo "  make check-php  - Run plugin PHP checks (cs, phpunit, phpstan)"
	@echo "  make php-cs-fix - Auto-fix plugin PHP style violations (PHPCBF)"
	@echo "  make projection-reset - Truncate ACX projection tables (guarded; requires WP_PATH + confirmation)"
	@echo "  make mcp        - Start the MCP server for AI agents (monorepo-wide)"
	@echo "  make lane-*     - Worktree lane commands (forwarded to root Makefile; run 'make help' from repo root for full list)"
	@echo "  make worker-daemon* - Worker daemon controls (run/status/stop/resume/tail) forwarded to root Makefile"

check:
	@npm run check
	@$(MAKE) php-test
	@$(MAKE) check-php

fix:
	@npm run lint:fix
	@npm run format:fix
	@composer cs-fix
	@$(MAKE) check

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

php-cs:
	@composer cs-check

php-cs-fix:
	@composer phpcbf

php-test:
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

# Forward all lane-* targets to root Makefile (single rule, never goes stale)
FORCE:

lane-%: FORCE
	@$(MAKE) -C "$$(git rev-parse --show-toplevel)" $@

worker-daemon: FORCE
	@$(MAKE) -C "$$(git rev-parse --show-toplevel)" $@

worker-daemon-%: FORCE
	@$(MAKE) -C "$$(git rev-parse --show-toplevel)" $@

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
	@if ! command -v wp >/dev/null 2>&1; then \
		echo "wp command not found. Install WP-CLI first."; \
		exit 1; \
	fi
	@_LOCALWP_SOCK="$${LOCALWP_SOCKET:-}"; \
	if [ -z "$$_LOCALWP_SOCK" ]; then \
		_LOCALWP_SOCK="$$(find "$$HOME/Library/Application Support/Local/run" -name "mysqld.sock" -print -quit 2>/dev/null || true)"; \
	fi; \
	_WP_BIN="$$(which wp)"; \
	if [ -n "$$_LOCALWP_SOCK" ] && [ -S "$$_LOCALWP_SOCK" ]; then \
		echo "Using LocalWP MySQL socket: $$_LOCALWP_SOCK"; \
		_SOCK_LINK="/tmp/_acx_mysqld.sock"; \
		ln -sf "$$_LOCALWP_SOCK" "$$_SOCK_LINK"; \
		_run_wp() { php -d "mysqli.default_socket=$$_SOCK_LINK" "$$_WP_BIN" "$$@"; }; \
	else \
		_run_wp() { php "$$_WP_BIN" "$$@"; }; \
	fi; \
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
