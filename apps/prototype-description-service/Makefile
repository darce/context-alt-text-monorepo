.PHONY: help gate-preflight test test-gpu-lifecycle test-integration lint format check clean install setup typecheck serve stop mcp postgres-start dev-ready dev-setup dev-mint-key logs-tail logs-rotate logs-clean logs-archive worker-daemon db-reset reset admin-dev admin-test admin-open admin-token admin-status admin-down admin-oci-serve admin-oci admin-oci-mint provision-customer FORCE

PYTEST_WORKERS ?= 4

UV := VIRTUAL_ENV= uv
UV_RUN := $(UV) run --locked --extra dev

# Default target
help:
	@echo "Available commands:"
	@echo "  make setup      - Full setup (deps + face detection, platform-aware)"
	@echo "  make install    - Install core dependencies only"
	@echo "  make postgres-start - Start local PostgreSQL via Homebrew (if needed)"
	@echo "  make dev-ready  - Prepare local env for development/testing (no dependency install)"
	@echo "  make dev-setup  - Onboard local env (.env from example if absent, then mint a LOCAL TEST FIXTURE key)"
	@echo "  make dev-mint-key - LOCAL TEST FIXTURES ONLY: bootstrap local tenant + mint a DB API key (not a real tenant)"
	@echo "  make serve      - Start PostgreSQL + development server + scan worker"
	@echo "  make stop       - Stop the development server"
	@echo "  make check      - Run linting, type checking, and tests"
	@echo "  make lint       - Run code linting checks"
	@echo "  make typecheck  - Run type checking with mypy"
	@echo "  make format     - Auto-fix code formatting"
	@echo "  make test       - Run pytest"
	@echo "  make ci         - Format code and run all checks"
	@echo "  make clean      - Remove cache and build files"
	@echo "  make reset      - Drop and recreate the local database (alias: db-reset)"
	@echo "  make mcp        - Start the MCP server for AI agents (monorepo-wide)"
	@echo ""
	@echo "Admin console (local /admin tenant management):"
	@echo "  make admin-dev    - Enable admin env, start service, open /admin, print token"
	@echo "  make admin-test   - Run the /admin JSON smoke harness (tenant/key lifecycle)"
	@echo "  make admin-token  - Print the current admin token"
	@echo "  make admin-open   - Open the /admin console in a browser"
	@echo "  make admin-status - Show service/admin reachability state"
	@echo "  make admin-down   - Stop the local service"
	@echo "  make provision-customer EMAIL=<e> ENV=prod [PLAN=pro] [LABEL=\"Name\"] - Concierge mint real tenant+key (AP-7; ENV=prod required)"
	@echo "  make admin-oci-mint TENANT=<uuid> [SITE_URL=<url>] - Mint a prod tenant key on the VM (no secret leaves the VM); prints the key once"
	@echo "  make lane-*     - Worktree lane commands (forwarded to root Makefile; run 'make help' from repo root for full list)"
	@echo "  make worker-daemon* - Worker daemon controls (run/status/stop/resume/tail) forwarded to root Makefile"
	@echo ""
	@echo "Log Management:"
	@echo "  make logs-tail    - Tail the main recognition log"
	@echo "  make logs-rotate  - Rotate logs (current→.1→.2→...→.10)"
	@echo "  make logs-clean   - Remove rotated logs (keep current)"
	@echo "  make logs-archive - Archive and compress old logs"

# Start MCP server (delegates to root Makefile)
mcp:
	@cd ../.. && make mcp-start

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

# Start local PostgreSQL service (native Homebrew install)
postgres-start:
	@if ! command -v pg_isready >/dev/null 2>&1; then \
		echo "pg_isready not found. Install PostgreSQL tools first." >&2; \
		exit 1; \
	fi
	@DB_HOST="$${PGHOST:-localhost}"; \
	DB_PORT="$${PGPORT:-5432}"; \
	if pg_isready -h "$$DB_HOST" -p "$$DB_PORT" >/dev/null 2>&1; then \
		echo "✓ PostgreSQL already running at $$DB_HOST:$$DB_PORT"; \
	elif command -v brew >/dev/null 2>&1; then \
		echo "Starting PostgreSQL (postgresql@17) via Homebrew..."; \
		brew services start postgresql@17 >/dev/null; \
		for i in 1 2 3 4 5 6 7 8 9 10; do \
			if pg_isready -h "$$DB_HOST" -p "$$DB_PORT" >/dev/null 2>&1; then \
				echo "✓ PostgreSQL is ready at $$DB_HOST:$$DB_PORT"; \
				exit 0; \
			fi; \
			sleep 1; \
		done; \
		echo "PostgreSQL did not become ready at $$DB_HOST:$$DB_PORT." >&2; \
		exit 1; \
	else \
		echo "PostgreSQL is not running and Homebrew is unavailable." >&2; \
		echo "Start PostgreSQL manually, then rerun this command." >&2; \
		exit 1; \
	fi

# Prepare local environment for development/testing (dependencies assumed installed)
dev-ready: postgres-start
	@echo "✓ Local environment ready for development and testing"

# Start development server
serve: dev-ready
	@mkdir -p logs
	@RECOGNITION_ASYNC_ANALYZE_INLINE=0 \
	START_SCAN_WORKER=1 \
	UVICORN_EXTRA_ARGS="--timeout-graceful-shutdown 1" \
	SKIP_INSTALL=1 \
	nohup ./scripts/start_prototype_local.sh start >> logs/prototype-local.log 2>&1 &
	@echo "✓ Backend starting (log: logs/prototype-local.log)"

# Stop development server
stop:
	@./scripts/start_prototype_local.sh stop

# LOCAL TEST FIXTURES ONLY — mints a DB-backed key for the fixed local dev tenant.
# This is NOT a real/production tenant; real tenants are minted against the OCI/prod
# --env prod DB via `make provision-customer ENV=prod`. Prints the raw key once on
# stdout (api_key=...). Override tenant/site if needed:
#   make dev-mint-key DEV_TENANT_ID=<uuid> DEV_SITE_URL=http://localhost:10003
DEV_TENANT_ID ?= 00000000-0000-4000-8000-000000000001
DEV_SITE_URL ?= http://localhost:10003

dev-mint-key:
	@echo "⚠ dev-mint-key: LOCAL TEST FIXTURES ONLY — not a real/production tenant. Real tenants: make provision-customer ENV=prod" >&2
	@echo "Bootstrapping local tenant $(DEV_TENANT_ID) at $(DEV_SITE_URL)..."
	@$(UV_RUN) python -m scripts.manage_api_keys --env local tenant create \
		--tenant $(DEV_TENANT_ID) --site-url $(DEV_SITE_URL)
	@echo "Minting API key (raw secret printed once as api_key=...):"
	@$(UV_RUN) python -m scripts.manage_api_keys --env local create --tenant $(DEV_TENANT_ID)

# One-shot local onboarding: seed .env from the example (never clobber), remind
# which values matter, then mint a LOCAL TEST FIXTURE key. Safe to re-run
# (idempotent .env). LOCAL TEST FIXTURES ONLY — not a real/production tenant.
dev-setup:
	@echo "⚠ dev-setup: LOCAL TEST FIXTURES ONLY — mints a local dev fixture key, not a real/production tenant. Real tenants: make provision-customer ENV=prod" >&2
	@if [ -f .env ]; then \
		echo "✓ .env already present — leaving it unchanged (idempotent)"; \
	elif [ -f .env.example ]; then \
		cp .env.example .env; \
		echo "✓ Created .env from .env.example"; \
	else \
		echo "✗ .env.example missing; cannot seed .env" >&2; \
		exit 1; \
	fi
	@echo ""
	@echo "Values a local dev typically sets (see docs/secrets-inventory.md):"
	@echo "  PGUSER / PGPASSWORD / PGHOST / PGPORT / DB_NAME  — Postgres (defaults suit local Homebrew)"
	@echo "  RECOGNITION_RUNTIME_MODE=development             — keep local (not production)"
	@echo "  RECOGNITION_AUTH_ENABLED=1                       — require bearer keys"
	@echo "  RECOGNITION_ADMIN_*                              — optional; use make admin-dev to enable /admin"
	@echo "  Tenant API keys (LOCAL FIXTURES)                 — mint via make dev-mint-key (DB-only; local fixtures, not real tenants)"
	@echo ""
	@echo "Minting a local tenant API key next (requires Postgres; run make postgres-start / make dev-ready first if needed)..."
	@$(MAKE) dev-mint-key DEV_TENANT_ID="$(DEV_TENANT_ID)" DEV_SITE_URL="$(DEV_SITE_URL)"


# =============================================================================
# Admin console (local /admin tenant management)
# =============================================================================
# Wraps scripts/admin_dev.sh. `admin-dev` enables the env-gated /admin router in
# .env (RECOGNITION_ADMIN_ENABLED + a generated RECOGNITION_ADMIN_TOKEN), starts
# the service, opens the console, and prints the token. `admin-test` exercises
# the JSON admin API end to end.

admin-dev:
	@./scripts/admin_dev.sh up

admin-test:
	@./scripts/admin_dev.sh test

# AP-7: mint a real (non-demo) customer tenant + API key via the shared minter.
# Idempotent on EMAIL. Prints raw key once + WP install snippet.
# ENV must be set explicitly to `prod` — this target refuses to default to the
# local DB so real customers are never minted against a dev database by omission.
# Usage: make provision-customer EMAIL=c@example.com ENV=prod PLAN=pro LABEL="Acme"
provision-customer:
	@if [ -z "$(EMAIL)" ]; then \
		echo "EMAIL is required. Example: make provision-customer EMAIL=customer@example.com ENV=prod PLAN=pro LABEL=\"Acme Co\""; \
		exit 1; \
	fi
	@if [ "$(ENV)" != "prod" ]; then \
		echo "✗ provision-customer mints REAL customer tenants and requires ENV=prod (got ENV='$(ENV)'). Refusing to default to the local DB." >&2; \
		echo "  For local test fixtures use: make dev-mint-key" >&2; \
		exit 1; \
	fi
	@$(UV_RUN) python -m scripts.provision_customer \
		--env "$(ENV)" \
		--email "$(EMAIL)" \
		--plan "$(or $(PLAN),pro)" \
		$(if $(LABEL),--label "$(LABEL)",)

admin-open:
	@./scripts/admin_dev.sh open

admin-token:
	@./scripts/admin_dev.sh token

admin-status:
	@./scripts/admin_dev.sh status

admin-down:
	@./scripts/admin_dev.sh down

# --- OCI /admin over the tailnet (no SSH tunnel) ------------------------------
# The /admin console is 404'd on the public api.altcontext.com vhost by design;
# it is reachable only over the tailnet. `admin-oci-serve` verifies the VM
# loopback backend is up, then publishes it over the tailnet (one-time; requires
# the admin compose overlay layered on the VM and Serve/HTTPS enabled in the
# tailnet console). `admin-oci` preflights the tailnet URL and only opens the
# browser when it is reachable, else prints an actionable diagnostic instead of
# a blank tab. Both honour OCI_HOST and OCI_USER (same env contract as
# scripts/deploy/*).
OCI_HOST ?= acx-backend.tail1a44b8.ts.net
OCI_USER ?= ubuntu

admin-oci-serve:
	@ssh $(OCI_USER)@$(OCI_HOST) '\
		code=$$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://127.0.0.1:8000/admin/ 2>/dev/null); \
		[ -n "$$code" ] || code=000; \
		case "$$code" in \
			000|502|503|504) echo "✗ admin backend on 127.0.0.1:8000 not ready (got $$code). Layer the overlay first: docker compose -f docker-compose.env.yml -f docker-compose.admin.yml up -d" >&2; exit 1 ;; \
			*) echo "✓ admin backend up on 127.0.0.1:8000 (HTTP $$code); publishing over the tailnet ..." ;; \
		esac; \
		sudo tailscale serve --bg --https=443 http://127.0.0.1:8000 && sudo tailscale serve status'

admin-oci:
	@url="https://$(OCI_HOST)/admin/"; \
	code=$$(curl -sS -o /dev/null -w "%{http_code}" --max-time 8 "$$url" 2>/dev/null); \
	[ -n "$$code" ] || code=000; \
	case "$$code" in \
		200|401) echo "Opening $$url (HTTP $$code; auth with RECOGNITION_ADMIN_TOKEN) ..."; \
			open "$$url" 2>/dev/null || xdg-open "$$url" 2>/dev/null || echo "Browse to $$url" ;; \
		502|503|504) echo "✗ $$url -> $$code: tailnet reached but the admin backend is down. Is the admin overlay layered on the VM (docker-compose.admin.yml)?" >&2; exit 1 ;; \
		404) echo "✗ $$url -> 404: reached a vhost that denies /admin. Is 'tailscale serve' pointed at 127.0.0.1:8000? Run 'make admin-oci-serve'." >&2; exit 1 ;; \
		000) echo "✗ $$url unreachable: not on the tailnet, MagicDNS/HTTPS off, or serve not published. Check 'tailscale status' and run 'make admin-oci-serve'." >&2; exit 1 ;; \
		*) echo "✗ $$url -> $$code (unexpected); not opening." >&2; exit 1 ;; \
	esac

# Mint a prod API key for a tenant WITHOUT bringing any secret to the laptop. Runs the
# canonical CLI inside the prod `api` container over the tailnet, so the container's own
# DB creds do the write — the /admin HTTP route (and its RECOGNITION_ADMIN_TOKEN) are not
# involved at all, and the prod token stays in /opt/acx-backend/prod/secrets/.env where it
# belongs [WEB-16: secrets only in a secret store/env; SEC-04: least-privilege; SEC-01: the
# laptop<->VM SSH is a trust boundary — don't cross it with the token]. The raw key prints
# exactly once (api_key=…); copy it into the plugin Settings. Automated form of the
# canonical prod mint in docs/runbooks/key-management.md Track 1.
# Usage: make admin-oci-mint TENANT=<uuid> [SITE_URL=<url>]
# TENANT/SITE_URL reach the shell via the environment (export) and are validated (UUID / URL
# charset) BEFORE use — never textual make-expansion — so an operator-pasted value cannot inject
# a command through the ssh double-hop [WEB-02]. The prod dir and --env are hardcoded so they
# cannot diverge into a wrong-DB mint [MRG-D-02].
export TENANT
export SITE_URL
admin-oci-mint:
	@set -e; \
	tenant="$${TENANT:-}"; site="$${SITE_URL:-http://localhost:10018}"; \
	test -n "$$tenant" || { echo "usage: make admin-oci-mint TENANT=<uuid> [SITE_URL=<url>]" >&2; exit 2; }; \
	printf '%s' "$$tenant" | grep -qiE '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$$' || { echo "✗ TENANT must be a UUID (got '$$tenant')" >&2; exit 2; }; \
	printf '%s' "$$site" | grep -qE '^https?://[A-Za-z0-9:/._-]+$$' || { echo "✗ SITE_URL has invalid characters (allowed: A-Za-z0-9 : / . _ -)" >&2; exit 2; }; \
	echo "→ minting a prod key for tenant $$tenant (site $$site) via $(OCI_HOST) ..."; \
	ssh $(OCI_USER)@$(OCI_HOST) "set -e; cd /opt/acx-backend/prod; mk=\"docker compose -f docker-compose.env.yml exec -T api python -m scripts.manage_api_keys --env prod\"; \$$mk tenant create --tenant \"$$tenant\" --site-url \"$$site\"; \$$mk create --tenant \"$$tenant\""; \
	echo "→ copy the 'api_key=' value above into wp-admin → Alt Context Settings (shown once; unrecoverable)."

# Reset local database (db-reset is an alias)
reset db-reset:
	@ALLOW_DEV_DB_RESET="$${ALLOW_DEV_DB_RESET:-1}" ./scripts/reset_dev_db.sh
	@echo "✓ Local database reset"

# Run all checks and tests (fast lane + serial integration/timing lane)
check: lint typecheck test test-integration
	@echo "✓ All checks passed!"

# Lint only
lint:
	@echo "Running Ruff checks (via the repo-wide lint ratchet)..."
	@# LINTGATE-1: `ruff check .` fails here (93 of the repo's 408 known
	@# violations live under this app), so it could never gate a merge.
	@# The ratchet gates the same rules against a frozen baseline: any new
	@# violation or raised count in these files still fails. See the
	@# `lint-ratchet` target in the root Makefile. Use `ruff check .` directly
	@# for the raw list, or `make lint-ratchet-accept TOOL=ruff` after a fix.
	@python3 ../../scripts/lint_ratchet.py --tool ruff
	@$(UV_RUN) ruff format --check .

# Type check only
typecheck:
	@echo "Running mypy type checks..."
	@$(UV_RUN) mypy .

# Format code
format:
	@echo "Auto-fixing code..."
	@$(UV_RUN) ruff check --fix --unsafe-fixes .
	@$(UV_RUN) ruff format .

# Gate preflight (GATE-BR-01). scripts/remote_gate.sh runs this before any gate
# target and aborts the whole run with 73 if it fails. Its job is to make the
# things the suite would otherwise silently SKIP into hard failures: the
# face_pipeline ONNX weights are gitignored, so a host that never fetched them
# skipped ~45 detector/aligner/embedder/ORT-parity tests and still reported
# EXIT=0. --verify-only is offline (sha256 against the manifest, no download),
# so this is safe to run on every gate invocation.
gate-preflight:
	@$(UV_RUN) python scripts/fetch_face_pipeline_models.py --verify-only

# Fast unit tests (excludes integration/pg/timing markers; parallel when PYTEST_WORKERS>0)
test:
	@echo "Running tests..."
	@$(UV_RUN) pytest $(if $(filter-out 0,$(PYTEST_WORKERS)),-n $(PYTEST_WORKERS),) -m "not integration and not pg and not timing" --durations=25

# Burst-GPU lifecycle controller (GPUW-1). The suite lives at the repo root, but
# the root .venv on the gate host carries no pytest -- only this workdir's does,
# so the remote gate can reach it from here and nowhere else. Its conftest puts
# the repo root on sys.path for exactly this invocation. Without this target the
# cost backstop ships guarded by tests nothing ever collects.
test-gpu-lifecycle:
	@echo "Running gpu-lifecycle tests..."
	@$(UV_RUN) pytest ../../infra/oci/gpu_lifecycle/tests -q --tb=short

# Integration/pg/timing tests (serial — shared DB fixtures; wall-clock-sensitive
# timing tests stay out of the parallel lane so worker contention cannot flake them)
test-integration:
	@echo "Running integration tests..."
	@$(UV_RUN) pytest -m "integration or pg or timing" --durations=25

# Auto-fix and test (for CI; fast lane + serial integration/timing lane)
ci: format typecheck test test-integration

# Install core dependencies only (no face detection)
install:
	@$(UV) sync --locked --extra dev

# Full setup with platform-aware face detection
setup:
	@./scripts/setup.sh

# Clean cache and build artifacts
clean:
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@echo "✓ Cleaned cache files"

# =============================================================================
# Log Management
# =============================================================================

# Tail the main recognition log
logs-tail:
	@tail -f logs/recognition.log

# Rotate logs (shift current to .1, .1 to .2, etc., keep 10 rotations)
# NOTE: WatchedFileHandler in api/logging_config.py auto-detects rotation,
# so no server restart is needed after running this target.
logs-rotate:
	@echo "Rotating logs..."
	@for log in logs/recognition.log logs/scan_worker.log; do \
		if [ -f "$$log" ]; then \
			for i in 9 8 7 6 5 4 3 2 1; do \
				[ -f "$$log.$$i" ] && mv "$$log.$$i" "$$log.$$((i+1))"; \
			done; \
			mv "$$log" "$$log.1"; \
			touch "$$log"; \
			echo "  ✓ Rotated $$log"; \
		fi; \
	done
	@echo "✓ Log rotation complete"

# Remove rotated log files (keep current logs)
logs-clean:
	@echo "Removing rotated logs..."
	@rm -f logs/*.log.[0-9]* 2>/dev/null || true
	@rm -f logs/*_[0-9]*.log 2>/dev/null || true
	@echo "✓ Rotated logs removed"
	@echo "Remaining logs:"
	@ls -lh logs/*.log 2>/dev/null || echo "  (no active logs)"

# Archive old logs to compressed tarball
logs-archive:
	@echo "Archiving logs..."
	@mkdir -p logs/archive
	@ARCHIVE_NAME="logs/archive/logs_$$(date +%Y%m%d_%H%M%S).tar.gz"; \
	if ls logs/*.log.[0-9]* logs/*_[0-9]*.log 1>/dev/null 2>&1; then \
		tar -czf "$$ARCHIVE_NAME" logs/*.log.[0-9]* logs/*_[0-9]*.log 2>/dev/null && \
		rm -f logs/*.log.[0-9]* logs/*_[0-9]*.log && \
		echo "✓ Archived to $$ARCHIVE_NAME"; \
	else \
		echo "No rotated logs to archive"; \
	fi
