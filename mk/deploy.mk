# =============================================================================
# Recognition service deploy targets
# =============================================================================
# Wraps scripts/deploy/recognition-service.sh for the OCI build/push/restart
# pipeline used by the recognition (face clustering / description) service.
#
# All targets honour OCI_HOST/OCI_USER/OCIR_REGISTRY/OCIR_NAMESPACE/IMAGE_NAME
# overrides (see recognition-service.sh for defaults).
#
# REMOTE_BUILD=1 (or env ACX_REMOTE_BUILD=1) routes 'deploy' / 'promote' through
# the OCI VM via SSH+rsync — no local docker daemon required.

DEPLOY_SCRIPT         := $(ROOT_MAKEFILE_DIR)/scripts/deploy/recognition-service.sh
DEPLOY_COMPOSE_SCRIPT := $(ROOT_MAKEFILE_DIR)/scripts/deploy/sync-compose.sh

.PHONY: deploy-help deploy-build deploy-build-remote \
        deploy-dev deploy-staging deploy-prod \
        deploy-promote-staging deploy-promote-prod deploy-rollback-dev \
        deploy-verify deploy-verify-dev deploy-verify-staging deploy-verify-prod \
        deploy-status \
        deploy-compose-dev deploy-compose-staging deploy-compose-prod

deploy-help:
	@echo "Recognition service deploy targets:"
	@echo ""
	@echo "  Build only (no push):"
	@echo "    make deploy-build [TAG=dev]                Local linux/arm64 build (no push)"
	@echo "    make deploy-build-remote [TAG=dev]         Build on the OCI VM (no local docker)"
	@echo ""
	@echo "  Full deploy (build + push + restart + verify):"
	@echo "    make deploy-dev                            Build + push :dev + :SHA, restart acx-dev, verify"
	@echo "    make deploy-dev REMOTE_BUILD=1             Same, built on the VM (recommended; no colima)"
	@echo "    make deploy-staging                        Build + push :staging + :SHA, restart acx-staging, verify"
	@echo "    make deploy-prod CONFIRM=PROMOTE           Build + push :latest + :SHA, restart acx-prod, verify"
	@echo ""
	@echo "  Promote / rollback (retag existing image):"
	@echo "    make deploy-promote-staging                Retag :dev -> :staging, restart, verify"
	@echo "    make deploy-promote-prod CONFIRM=PROMOTE   Retag :staging -> :latest, restart, verify"
	@echo "    make deploy-rollback-dev                   Retag :staging -> :dev (rollback path)"
	@echo ""
	@echo "  Verify / status:"
	@echo "    make deploy-verify ENV=dev                 GET /health and compare commit_sha to local HEAD"
	@echo "    make deploy-verify-dev|staging|prod        Same, fixed env"
	@echo "    make deploy-status                         Snapshot /health for dev, staging, prod"
	@echo ""
	@echo "  Compose-file sync (run when docker-compose.env.yml itself changes):"
	@echo "    make deploy-compose-dev                    Sync compose to acx-dev VM and 'docker compose up -d'"
	@echo "    make deploy-compose-staging                Sync compose to acx-staging VM and 'docker compose up -d'"
	@echo "    make deploy-compose-prod CONFIRM=PROD      Sync compose to acx-prod VM and 'docker compose up -d'"
	@echo ""
	@echo "  Optional overrides: OCI_HOST OCI_USER OCIR_REGISTRY OCIR_NAMESPACE IMAGE_NAME GIT_REF"
	@echo "                      ACX_DEPLOY_PLATFORM ACX_REMOTE_BUILD_DIR ACX_ALLOW_DIRTY"

# Build only (no push). Override the tag with TAG=staging.
deploy-build:
	@"$(DEPLOY_SCRIPT)" build $(TAG)

deploy-build-remote:
	@"$(DEPLOY_SCRIPT)" build-remote $(TAG)

# Full deploy. REMOTE_BUILD=1 routes the build through the VM via rsync+ssh.
deploy-dev:
	@REMOTE_BUILD=$(if $(REMOTE_BUILD),$(REMOTE_BUILD),$(ACX_REMOTE_BUILD)) \
		"$(DEPLOY_SCRIPT)" deploy dev

deploy-staging:
	@REMOTE_BUILD=$(if $(REMOTE_BUILD),$(REMOTE_BUILD),$(ACX_REMOTE_BUILD)) \
		"$(DEPLOY_SCRIPT)" deploy staging

deploy-prod:
	@CONFIRM=$(CONFIRM) \
		REMOTE_BUILD=$(if $(REMOTE_BUILD),$(REMOTE_BUILD),$(ACX_REMOTE_BUILD)) \
		"$(DEPLOY_SCRIPT)" deploy prod

# Retag existing image (no rebuild). Useful for promotions and rollback.
deploy-promote-staging:
	@REMOTE_BUILD=$(if $(REMOTE_BUILD),$(REMOTE_BUILD),$(ACX_REMOTE_BUILD)) \
		"$(DEPLOY_SCRIPT)" promote dev staging

deploy-promote-prod:
	@CONFIRM=$(CONFIRM) \
		REMOTE_BUILD=$(if $(REMOTE_BUILD),$(REMOTE_BUILD),$(ACX_REMOTE_BUILD)) \
		"$(DEPLOY_SCRIPT)" promote staging prod

# Rollback dev to whatever staging is running (handy when a dev push breaks).
deploy-rollback-dev:
	@REMOTE_BUILD=$(if $(REMOTE_BUILD),$(REMOTE_BUILD),$(ACX_REMOTE_BUILD)) \
		"$(DEPLOY_SCRIPT)" promote staging dev

# Verify a deployed environment matches local HEAD.
deploy-verify:
	@"$(DEPLOY_SCRIPT)" verify $(ENV)

deploy-verify-dev:
	@"$(DEPLOY_SCRIPT)" verify dev

deploy-verify-staging:
	@"$(DEPLOY_SCRIPT)" verify staging

deploy-verify-prod:
	@"$(DEPLOY_SCRIPT)" verify prod

# Cross-env health snapshot. Cheap triage tool.
deploy-status:
	@"$(DEPLOY_SCRIPT)" status

# Compose-file sync (independent of image deploy).
deploy-compose-dev:
	@ENV=dev "$(DEPLOY_COMPOSE_SCRIPT)"

deploy-compose-staging:
	@ENV=staging "$(DEPLOY_COMPOSE_SCRIPT)"

deploy-compose-prod:
	@ENV=prod CONFIRM="$(CONFIRM)" "$(DEPLOY_COMPOSE_SCRIPT)"
