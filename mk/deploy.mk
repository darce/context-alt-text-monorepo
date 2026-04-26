# =============================================================================
# Recognition service deploy targets
# =============================================================================
# Wraps scripts/deploy/recognition-service.sh for the OCI build/push/restart
# pipeline used in MAINT-workbench-multipart-404-investigation-20260426.
#
# All targets honour OCI_HOST/OCI_USER/OCIR_REGISTRY/OCIR_NAMESPACE/IMAGE_NAME
# overrides (see recognition-service.sh for defaults).

DEPLOY_SCRIPT := $(ROOT_MAKEFILE_DIR)/scripts/deploy/recognition-service.sh

.PHONY: deploy-help deploy-dev deploy-staging deploy-prod \
        deploy-promote-staging deploy-promote-prod deploy-status

deploy-help:
	@echo "Recognition service deploy targets:"
	@echo "  make deploy-dev                Build HEAD on OCI host, push :dev, restart acx-dev"
	@echo "  make deploy-staging            Build HEAD on OCI host, push :staging, restart acx-staging"
	@echo "  make deploy-prod CONFIRM=PROD  Build HEAD on OCI host, push :latest, restart acx-prod"
	@echo "  make deploy-promote-staging    Retag :dev -> :staging, restart acx-staging"
	@echo "  make deploy-promote-prod CONFIRM=PROD  Retag :staging -> :latest, restart acx-prod"
	@echo "  make deploy-status             Show current sha at each environment's /health"
	@echo ""
	@echo "Optional overrides: OCI_HOST OCI_USER OCIR_REGISTRY OCIR_NAMESPACE IMAGE_NAME GIT_REF"

deploy-dev:
	@ENV=dev MODE=build "$(DEPLOY_SCRIPT)"

deploy-staging:
	@ENV=staging MODE=build "$(DEPLOY_SCRIPT)"

deploy-prod:
	@ENV=prod MODE=build CONFIRM="$(CONFIRM)" "$(DEPLOY_SCRIPT)"

deploy-promote-staging:
	@ENV=staging MODE=promote SOURCE_TAG=dev "$(DEPLOY_SCRIPT)"

deploy-promote-prod:
	@ENV=prod MODE=promote SOURCE_TAG=staging CONFIRM="$(CONFIRM)" "$(DEPLOY_SCRIPT)"

deploy-status:
	@for env in dev staging prod; do \
		case $$env in \
		  dev)     url=https://dev.api.altcontext.com/health ;; \
		  staging) url=https://staging.api.altcontext.com/health ;; \
		  prod)    url=https://api.altcontext.com/health ;; \
		esac; \
		printf "%-8s %s\n" "$$env" "$$(curl -fsS --max-time 5 $$url 2>/dev/null || echo 'unreachable')"; \
	done
