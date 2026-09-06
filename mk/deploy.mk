# =============================================================================
# Recognition service deploy targets
# =============================================================================
# Wraps scripts/deploy/recognition-service.sh for the OCI build/push/restart
# pipeline used by the recognition (face clustering / description) service.
#
# All targets honour OCI_HOST/OCI_USER/OCIR_REGISTRY/OCIR_NAMESPACE/IMAGE_NAME
# overrides (see recognition-service.sh for defaults).
#
# Build location: 'deploy' / 'promote' / 'rollback' targets default to remote
# build on the OCI VM via SSH+rsync — no local docker daemon required. To
# build locally instead (e.g. while iterating with colima/Docker Desktop),
# pass REMOTE_BUILD=0 or export ACX_REMOTE_BUILD=0.

DEPLOY_SCRIPT         := $(ROOT_MAKEFILE_DIR)/scripts/deploy/recognition-service.sh
DEPLOY_COMPOSE_SCRIPT := $(ROOT_MAKEFILE_DIR)/scripts/deploy/sync-compose.sh
DEPLOY_DEMO_SCRIPT    := $(ROOT_MAKEFILE_DIR)/scripts/deploy/sync-demo.sh
DB_RESET_REMOTE_SCRIPT := $(ROOT_MAKEFILE_DIR)/scripts/deploy/db-reset-remote.sh
DEMO_WALKTHROUGH_APP  := $(ROOT_MAKEFILE_DIR)/apps/prototype-wp-alt-context

.PHONY: deploy-help deploy-build deploy-build-remote \
        deploy-dev deploy-dev-fir deploy-staging deploy-prod deploy-demo \
        deploy-promote-staging deploy-promote-prod deploy-rollback-dev \
        deploy-rollback-dev-fir \
        deploy-verify deploy-verify-dev deploy-verify-staging deploy-verify-prod \
        deploy-status deploy-clear-image-repo \
        deploy-compose-dev deploy-compose-staging deploy-compose-prod \
        reset-remote db-reset-remote demo-walkthrough-proof walkthrough-first-visitor

deploy-help:
	@echo "Recognition service deploy targets:"
	@echo ""
	@echo "  Build only (no push):"
	@echo "    make deploy-build [TAG=dev]                Local linux/arm64 build (no push)"
	@echo "    make deploy-build-remote [TAG=dev]         Build on the OCI VM (no local docker)"
	@echo ""
	@echo "  Full deploy (build + push + restart + verify) — remote build by default:"
	@echo "    make deploy-dev                            Remote build on VM, push :dev + :SHA, restart acx-dev, verify"
	@echo "    make deploy-dev REMOTE_BUILD=0             Same, built locally (requires colima / Docker Desktop)"
	@echo "    make deploy-dev-fir                        Same image (:dev tag), restart acx-dev-fir (isolated FIR stack), verify"
	@echo "    make deploy-staging                        Remote build on VM, push :staging + :SHA, restart acx-staging, verify"
	@echo "    make deploy-prod CONFIRM=PROMOTE           Remote build on VM, push :latest + :SHA, restart acx-prod, verify"
	@echo "    ACX_BUILD_TARGET=runtime-vlm make deploy-dev REMOTE_BUILD=0   Local VLM image build+deploy (never remote)"
	@echo "  VLM notes (rg-006): remote build of *vlm* targets is refused (refuse_remote_vlm_build)."
	@echo "    Required: REMOTE_BUILD=0, ACX_BUILD_TARGET=runtime-vlm, seed weights into \$$ACX_MODELS_PATH/huggingface_cache"
	@echo "    on the VM first. Compose selects the -vlm repo via sticky ACX_IMAGE_REPO shipped by the deploy script."
	@echo "    Free-space floor (REMOTE_BUILD_MIN_FREE_GB) still applies on the VM pull/smoke path for VLM."
	@echo ""
	@echo "  Promote / rollback (retag existing image — remote ssh by default):"
	@echo "    make deploy-promote-staging                Retag :dev -> :staging, restart, verify"
	@echo "    make deploy-promote-prod CONFIRM=PROMOTE   Retag :staging -> :latest, restart, verify"
	@echo "    make deploy-rollback-dev                   Retag :staging -> :dev (rollback path; also affects dev-fir — shared :dev tag)"
	@echo "    make deploy-rollback-dev-fir               Refuses: FIR-only rollback impossible (shared :dev tag)"
	@echo ""
	@echo "  Verify / status / sticky-repo reset:"
	@echo "    make deploy-verify ENV=dev                 GET /health and compare commit_sha to local HEAD (dev|dev-fir|staging|prod)"
	@echo "    make deploy-verify-dev|staging|prod        Same, fixed env (reads remote ACX_IMAGE_REPO for VLM)"
	@echo "    make deploy-status                         Snapshot /health for dev, dev-fir, staging, prod"
	@echo "    make deploy-clear-image-repo ENV=dev       Remove sticky ACX_IMAGE_REPO from remote .env (→ recognition default)"
	@echo "    make deploy-clear-image-repo ENV=prod CONFIRM=PROMOTE   Same for prod (CONFIRM required)"
	@echo ""
	@echo "  Destructive remote reset (stops unit, clears env Postgres state, restarts, verifies /ready):"
	@echo "    ACX_RESET_SITE_URL is REQUIRED — the WordPress site URL the plugin will hit."
	@echo "    The bootstrap derives the per-site tenant UUID from it (TenantIdentity)."
	@echo "    make reset-remote ENV=dev CONFIRM_REMOTE_RESET=RESET ACX_RESET_SITE_URL=http://localhost:10010             Reset OCI dev (LocalWP origin)"
	@echo "    make reset-remote ENV=staging CONFIRM_REMOTE_RESET=RESET ACX_RESET_SITE_URL=https://staging.altcontext.com     Reset OCI staging"
	@echo "    make reset-remote ENV=prod CONFIRM_REMOTE_RESET=RESET ACX_RESET_SITE_URL=https://altcontext.com CONFIRM=PROMOTE Reset OCI prod"
	@echo "    make reset-remote ENV=dev CONFIRM_REMOTE_RESET=RESET ACX_RESET_SITE_URL=http://localhost:10010 ACX_RESET_DRY_RUN=1   Print plan only"
	@echo ""
	@echo "  Schema-only remote DB reset (greenfield 001 drift; DROP SCHEMA public CASCADE; no prod path):"
	@echo "    make db-reset-remote ENV=dev CONFIRM=RESET              Drop/recreate public schema on OCI dev, restart api, poll /health"
	@echo "    make db-reset-remote ENV=dev-fir CONFIRM=RESET          Same for the isolated FIR stack (acx-dev-fir)"
	@echo "    make db-reset-remote ENV=staging CONFIRM=RESET          Same for OCI staging"
	@echo "    make db-reset-remote ENV=dev CONFIRM=RESET DRY_RUN=1    Print remote commands only (no SSH)"
	@echo ""
	@echo "  Compose-file sync (run when docker-compose.env.yml itself changes):"
	@echo "    make deploy-compose-dev                    Sync compose to acx-dev VM and 'docker compose up -d'"
	@echo "    make deploy-compose-staging                Sync compose to acx-staging VM and 'docker compose up -d'"
	@echo "    make deploy-compose-prod CONFIRM=PROD      Sync compose to acx-prod VM and 'docker compose up -d'"
	@echo ""
	@echo "  Demo WordPress stack (compose + Caddy edge; recreates Caddy to join acx-demo-net):"
	@echo "    make deploy-demo                           Sync demo stack + bootstrap + Caddy config"
	@echo "    ACX_DEMO_GPU_PREFLIGHT=1 make deploy-demo  Fail closed on GPU/reaper env drift before stack up"
	@echo "    ACX_DEMO_DESCRIBE_CHUNK=10 ACX_DEMO_DESCRIBE_MAX=100 make deploy-demo  Bound first describe burst"
	@echo "    PLUGIN_ZIP=dist/alt-context-x.y.z.zip make deploy-demo   Pin plugin artifact explicitly"
	@echo ""
	@echo "  Demo walkthrough proof (Playwright evidence — screenshots + smoke-log fragment):"
	@echo "    First-time setup: (cd apps/prototype-wp-alt-context && npm ci && npm run e2e:install)"
	@echo "    make demo-walkthrough-proof                Drive demo.altcontext.com walkthrough; emit evidence"
	@echo "    WP_BASE_URL=http://localhost:10010 ACX_E2E_REQUIRE_CONSTANT_PROVENANCE=0 ACX_E2E_REQUIRE_SERVICE_TARGET=0 make demo-walkthrough-proof   LocalWP (no wp-config constants / dev hatch)"
	@echo "    Requires ACX_E2E_WP_ADMIN_USER / ACX_E2E_WP_ADMIN_PASS for non-interactive auth."
	@echo ""
	@echo "  First-visitor walkthrough (E21-13, roadmap §Phase-3 Gate — timings manifest + fragment):"
	@echo "    make walkthrough-first-visitor             Scan → review → first named person on demo.altcontext.com"
	@echo "    WP_BASE_URL=http://localhost:10010 make walkthrough-first-visitor               LocalWP origin override"
	@echo "    Requires ACX_E2E_WP_ADMIN_USER / ACX_E2E_WP_ADMIN_PASS for non-interactive auth."
	@echo ""
	@echo "  Optional overrides: OCI_HOST OCI_USER OCIR_REGISTRY OCIR_NAMESPACE IMAGE_NAME GIT_REF"
	@echo "                      ACX_DEPLOY_PLATFORM ACX_REMOTE_BUILD_DIR ACX_ALLOW_DIRTY"
	@echo "                      REMOTE_BUILD (default 1; set 0 for local), ACX_REMOTE_BUILD (env equivalent)"
	@echo "                      ACX_BUILD_TARGET (e.g. runtime-vlm; charset [A-Za-z0-9_.-]+ only)"
	@echo "                      ACX_IMAGE_VARIANT (recognition|vlm; vlm requires *vlm* build target)"
	@echo "                      ACX_VERIFY_OPTIONAL=1 ACX_VERIFY_ATTEMPTS ACX_VERIFY_SLEEP ACX_BOOT_SMOKE"

# Build only (no push). Override the tag with TAG=staging.
# ACX_BUILD_TARGET / ACX_IMAGE_VARIANT are passed through the environment.
deploy-build:
	@"$(DEPLOY_SCRIPT)" build $(TAG)

deploy-build-remote:
	@"$(DEPLOY_SCRIPT)" build-remote $(TAG)

# Default-remote selector. Pass REMOTE_BUILD=0 (or ACX_REMOTE_BUILD=0) to build locally.
# Precedence: explicit REMOTE_BUILD > exported ACX_REMOTE_BUILD > default 1 (remote).
RB_DEFAULT := $(if $(REMOTE_BUILD),$(REMOTE_BUILD),$(if $(ACX_REMOTE_BUILD),$(ACX_REMOTE_BUILD),1))

# Full deploy. Remote build on the OCI VM by default.
deploy-dev:
	@REMOTE_BUILD=$(RB_DEFAULT) \
		"$(DEPLOY_SCRIPT)" deploy dev

deploy-dev-fir:
	@REMOTE_BUILD=$(RB_DEFAULT) \
		"$(DEPLOY_SCRIPT)" deploy dev-fir

deploy-staging:
	@REMOTE_BUILD=$(RB_DEFAULT) \
		"$(DEPLOY_SCRIPT)" deploy staging

deploy-prod:
	@CONFIRM=$(CONFIRM) \
		REMOTE_BUILD=$(RB_DEFAULT) \
		"$(DEPLOY_SCRIPT)" deploy prod

# Retag existing image (no rebuild). Useful for promotions and rollback.
deploy-promote-staging:
	@REMOTE_BUILD=$(RB_DEFAULT) \
		"$(DEPLOY_SCRIPT)" promote dev staging

deploy-promote-prod:
	@CONFIRM=$(CONFIRM) \
		REMOTE_BUILD=$(RB_DEFAULT) \
		"$(DEPLOY_SCRIPT)" promote staging prod

# Rollback dev to whatever staging is running (handy when a dev push breaks).
deploy-rollback-dev:
	@REMOTE_BUILD=$(RB_DEFAULT) \
		"$(DEPLOY_SCRIPT)" promote staging dev

# FIR-only rollback is impossible by design: dev-fir shares the :dev image tag
# with acx-dev (env_to_tag maps both to "dev"), so retagging for dev-fir would
# also roll back acx-dev on its next restart. Fail closed and name the real
# lever instead of silently mutating the shared tag (gate r0811864a A-04/B-01).
deploy-rollback-dev-fir:
	@echo "deploy-rollback-dev-fir: refused. dev-fir shares the :dev image tag with acx-dev;" >&2
	@echo "a FIR-only image rollback does not exist. To roll back the shared :dev image for" >&2
	@echo "BOTH stacks, run 'make deploy-rollback-dev' and restart acx-dev-fir afterwards." >&2
	@exit 2

# Verify a deployed environment matches local HEAD.
# Reads remote ACX_IMAGE_REPO when present so VLM deploys verify without re-exporting
# ACX_BUILD_TARGET. Bounded retries via ACX_VERIFY_ATTEMPTS / ACX_VERIFY_SLEEP.
deploy-verify: GPU_SNAPSHOT_ENV := $(ENV)
deploy-verify: check-gpu-snapshots-live
	@"$(DEPLOY_SCRIPT)" verify $(ENV)

deploy-verify-dev: GPU_SNAPSHOT_ENV := dev
deploy-verify-dev: check-gpu-snapshots-live
	@"$(DEPLOY_SCRIPT)" verify dev

deploy-verify-staging: GPU_SNAPSHOT_ENV := staging
deploy-verify-staging: check-gpu-snapshots-live
	@"$(DEPLOY_SCRIPT)" verify staging

deploy-verify-prod: GPU_SNAPSHOT_ENV := prod
deploy-verify-prod: check-gpu-snapshots-live
	@"$(DEPLOY_SCRIPT)" verify prod

# Cross-env health snapshot. Cheap triage tool.
deploy-status:
	@"$(DEPLOY_SCRIPT)" status

# D9 / S2-A-10: remove sticky ACX_IMAGE_REPO from remote .env (compose → recognition default).
# Prod requires CONFIRM=PROMOTE — same lever as deploy-prod / reset-remote — because a
# mistyped ENV=prod is latent (no restart) and only bites at the next unattended unit restart.
deploy-clear-image-repo:
	@if [ -z "$(ENV)" ]; then \
		echo "deploy-clear-image-repo: ENV is required (dev|staging|prod)" >&2; \
		exit 2; \
	fi
	@if [ "$(ENV)" = "prod" ] && [ "$(CONFIRM)" != "PROMOTE" ]; then \
		echo "deploy-clear-image-repo: ENV=prod requires CONFIRM=PROMOTE (sticky-repo clear is latent until next unit restart)" >&2; \
		exit 2; \
	fi
	@"$(DEPLOY_SCRIPT)" clear-image-repo $(ENV)

# Destructive remote reset. Requires explicit ENV=<dev|staging|prod> and confirmation
# levers (CONFIRM_REMOTE_RESET=RESET; CONFIRM=PROMOTE additionally for prod). Pass
# ACX_RESET_DRY_RUN=1 to print the plan without mutating any remote state.
reset-remote:
	@if [ -z "$(ENV)" ]; then \
		echo "reset-remote: ENV is required (dev|staging|prod)" >&2; \
		exit 2; \
	fi
	@CONFIRM_REMOTE_RESET="$(CONFIRM_REMOTE_RESET)" \
		CONFIRM="$(CONFIRM)" \
		ACX_RESET_DRY_RUN="$(ACX_RESET_DRY_RUN)" \
		"$(DEPLOY_SCRIPT)" reset $(ENV)

# Schema-only remote DB reset (dev|staging). Greenfield recovery when 001 is
# edited in place and long-lived remote volumes fail migration. No prod path.
# CONFIRM=RESET required; DRY_RUN=1 / --dry-run prints plan without SSH.
db-reset-remote:
	@if [ -z "$(ENV)" ]; then \
		echo "db-reset-remote: ENV is required (dev|dev-fir|staging)" >&2; \
		exit 2; \
	fi
	@ENV="$(ENV)" CONFIRM="$(CONFIRM)" DRY_RUN="$(DRY_RUN)" \
		"$(DB_RESET_REMOTE_SCRIPT)"

# Compose-file sync (independent of image deploy).
deploy-compose-dev:
	@ENV=dev "$(DEPLOY_COMPOSE_SCRIPT)"

deploy-compose-staging:
	@ENV=staging "$(DEPLOY_COMPOSE_SCRIPT)"

deploy-compose-prod:
	@ENV=prod CONFIRM="$(CONFIRM)" "$(DEPLOY_COMPOSE_SCRIPT)"

deploy-demo:
	@ACX_DEMO_GPU_PREFLIGHT="$(ACX_DEMO_GPU_PREFLIGHT)" \
		ACX_DEMO_DESCRIBE_CHUNK="$(ACX_DEMO_DESCRIBE_CHUNK)" \
		ACX_DEMO_DESCRIBE_MAX="$(ACX_DEMO_DESCRIBE_MAX)" \
		"$(DEPLOY_DEMO_SCRIPT)"

# Demo walkthrough proof: runs the Playwright `evidence` project's demo-walkthrough
# spec against WP_BASE_URL (default https://demo.altcontext.com), emitting screenshots,
# an evidence manifest, and a paste-ready smoke-log fragment under the task-scoped
# local/playwright/<task-ref>/evidence/ artifact dir. Auth bootstraps from
# ACX_E2E_WP_ADMIN_USER/ACX_E2E_WP_ADMIN_PASS (interactive page.pause() otherwise).
# First-visitor walkthrough (E21-13, roadmap §Phase-3 Gate): scripted scan → review →
# first-named-person against WP_BASE_URL with per-step timings; emits
# walkthrough-manifest.json (time_to_first_named_person_ms) + a paste-ready fragment.
# The unaided human observation follows the same script; this is its instrumented run.
walkthrough-first-visitor: WP_BASE_URL ?= https://demo.altcontext.com
walkthrough-first-visitor: ACX_PLAYWRIGHT_TASK_REF ?= E21-13
walkthrough-first-visitor:
	@cd "$(DEMO_WALKTHROUGH_APP)" && \
		if [ ! -d node_modules ]; then \
			echo "walkthrough-first-visitor: dependencies missing. First run: (cd apps/prototype-wp-alt-context && npm ci && npm run e2e:install)" >&2; \
			exit 2; \
		fi
	@cd "$(DEMO_WALKTHROUGH_APP)" && npm run e2e:install >/dev/null
	@cd "$(DEMO_WALKTHROUGH_APP)" && \
		WP_BASE_URL="$(WP_BASE_URL)" \
		ACX_PLAYWRIGHT_TASK_REF="$(ACX_PLAYWRIGHT_TASK_REF)" \
		ACX_DEPLOY_COMMIT_SHA="$${ACX_DEPLOY_COMMIT_SHA:-$$(git rev-parse HEAD 2>/dev/null || true)}" \
		bash scripts/playwright-cli.sh test --project=evidence tests/e2e/evidence/first-visitor-walkthrough.spec.ts
	@echo "==> First-visitor walkthrough artifacts under:"
	@echo "    $(DEMO_WALKTHROUGH_APP)/local/playwright/$(ACX_PLAYWRIGHT_TASK_REF)/evidence/"
	@echo "    find $(DEMO_WALKTHROUGH_APP)/local/playwright/$(ACX_PLAYWRIGHT_TASK_REF)/evidence -name first-visitor-walkthrough-fragment.md"

demo-walkthrough-proof: WP_BASE_URL ?= https://demo.altcontext.com
demo-walkthrough-proof: ACX_PLAYWRIGHT_TASK_REF ?= E15-28
demo-walkthrough-proof:
	@cd "$(DEMO_WALKTHROUGH_APP)" && \
		if [ ! -d node_modules ]; then \
			echo "demo-walkthrough-proof: dependencies missing. First run: (cd apps/prototype-wp-alt-context && npm ci && npm run e2e:install)" >&2; \
			exit 2; \
		fi
	@cd "$(DEMO_WALKTHROUGH_APP)" && npm run e2e:install >/dev/null
	@cd "$(DEMO_WALKTHROUGH_APP)" && \
		WP_BASE_URL="$(WP_BASE_URL)" \
		ACX_PLAYWRIGHT_TASK_REF="$(ACX_PLAYWRIGHT_TASK_REF)" \
		ACX_DEPLOY_COMMIT_SHA="$${ACX_DEPLOY_COMMIT_SHA:-$$(git rev-parse HEAD 2>/dev/null || true)}" \
		bash scripts/playwright-cli.sh test --project=evidence tests/e2e/evidence/demo-walkthrough.spec.ts
	@echo "==> Demo walkthrough proof artifacts under:"
	@echo "    $(DEMO_WALKTHROUGH_APP)/local/playwright/$(ACX_PLAYWRIGHT_TASK_REF)/evidence/"
	@echo "    Smoke-log fragment (Playwright nests it in a per-test subdir) — locate with:"
	@echo "    find $(DEMO_WALKTHROUGH_APP)/local/playwright/$(ACX_PLAYWRIGHT_TASK_REF)/evidence -name demo-walkthrough-smoke-log-fragment.md"
