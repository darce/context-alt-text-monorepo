# Issue a least-privilege API account for the hosted demo's CI smoke.
# Usage: make issue-demo-ci-account LABEL="ACX CI" ADMIN_USER=acx-demo-admin

.PHONY: issue-demo-ci-account
issue-demo-ci-account:
	@if [ -z "$(LABEL)" ]; then echo "error: LABEL is required (e.g. LABEL=\"ACX CI\")" >&2; exit 2; fi
	@if [ -z "$(ADMIN_USER)" ]; then echo "error: ADMIN_USER is required (demo wp-admin username to keep distinct)" >&2; exit 2; fi
	@cd apps/prototype-description-service && uv run python -m scripts.provision_demo \
		--env "$(DEMO_ENV)" provision --label "$(LABEL)" --seed "$(SEED)" \
		--account ci --admin-user "$(ADMIN_USER)"
