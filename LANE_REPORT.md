# Auth lane report — demo credential lifecycle

## DEMO-UX-1-AUTH-01 — FIXED

canon rows satisfied: SEC-01, SEC-04 (service tenant/quota boundary; WordPress-role limitation below), SEC-05, WEB-34.

what changed (files + why):

- `recognition/application/services/demo_provisioning_service.py`: extended the existing tenant/API-key lifecycle with a generated `demo-<slug>` WordPress identity and one-time base58 password. `expire_demo` invokes the WordPress disable seam before setting the registry flag and revoking `api_keys.revoked_at`; `sweep_expired_demos` passes the same seam to every unit. The service-side gateway call occurs while the caller's DB transaction is open, and a failed seed assertion compensates by disabling the just-created login.
- `scripts/provision_demo.py`: prints the WP username/password once with the API key, accepts the service gateway, rolls back rejected seed state, and refuses an unwrapped production invocation that could silently omit the WP lifecycle.
- `scripts/sweep_expired_demos.py`: accepts the same gateway, supports a read-only eligible-slug phase for the remote WP-CLI wrapper, and refuses direct production execution without that wrapper/gateway.
- `Makefile`: added the production `demo-provision`, `demo-expire`, and `demo-sweep` surfaces. All use the extracted `OCI_SSH` hop, validate values before SSH, run the DB CLI in the prod API container, and run WP-CLI in the demo tools container. Provision withholds all generated credentials until the WP account succeeds. Expire requires `CONFIRM=<slug>` and removes the WP login before DB revoke. Sweep removes every eligible WP login before committing the canonical DB sweep.
- `docs/runbooks/key-management.md`: documented the bundled identity, 30-day TTL, quota, one revoke, exact-confirmation gate, CI/demo identity separation, and rotation as expire + provision.
- service and CLI tests: proved per-slug identity uniqueness, explicit WP disable on expire, and WP disable for every swept slug.

RED output (test-first lanes):

```text
============================= test session starts ==============================
collected 0 items / 2 errors

E   ImportError: cannot import name 'SeedBundleStateError' from
E   'recognition.application.services.demo_provisioning_service'
E   ImportError: cannot import name 'WordPressSeedState' from
E   'recognition.application.services.demo_provisioning_service'
!!!!!!!!!!!!!!!!!!! Interrupted: 2 errors during collection !!!!!!!!!!!!!!!!!!!!
============================== 2 errors in 0.43s ===============================
```

GREEN output:

```text
$ uv run --extra dev pytest recognition/tests/service/test_demo_provisioning_service.py recognition/tests/service/test_demo_expiry.py recognition/tests/service/test_demo_quota.py recognition/tests/api/test_demo_router.py recognition/tests/api/test_demo_quota_clustering_routes.py recognition/tests/scripts/test_provision_demo.py
collected 47 items
recognition/tests/service/test_demo_provisioning_service.py .........    [ 19%]
recognition/tests/service/test_demo_expiry.py ....                       [ 27%]
recognition/tests/service/test_demo_quota.py ...................         [ 68%]
recognition/tests/api/test_demo_router.py .......                        [ 82%]
recognition/tests/api/test_demo_quota_clustering_routes.py ....          [ 91%]
recognition/tests/scripts/test_provision_demo.py ....                    [100%]
============================= 47 passed in 10.51s ==============================

$ uv run --extra dev ruff check <owned Python/test paths>
All checks passed!

$ uv run --extra dev mypy recognition/application/services/demo_provisioning_service.py scripts/provision_demo.py scripts/sweep_expired_demos.py
Success: no issues found in 3 source files
```

residual risk / what a reviewer should attack:

- The plugin still gates its six admin pages on `manage_options`, outside this lane's ownership. The safe service-half result therefore creates a distinct administrator identity rather than half-shipping an `acx_demo_reviewer` who can log in but see nothing. Follow-up: change every menu/route gate to `acx_operate`, then switch provisioning to the lesser role. The CI identity is never reused.
- PostgreSQL and MariaDB cannot share an ACID transaction. The injectable service gateway is invoked inside the open Postgres transaction, but the deployable SSH wrapper is a fail-closed ordered saga: create commits DB before WP and compensates DB on WP failure; expire/sweep remove WP first, then commit DB revocation. A host crash can leave an unusable/unrevealed API key active or a WP-disabled demo DB row active, but cannot report DB expiry while its WP login still works. All commands are idempotent/retryable.
- The generated WordPress password crosses stdout exactly once by design. Operator terminal capture remains sensitive and should be treated like the one-time API key.

## DEMO-UX-1-AUTH-02 — FIXED

canon rows satisfied: RLSE-04.

what changed (files + why):

- `demo_provisioning_service.py`: replaced an unstructured name set with exported `SeedBundleContract` definitions. Both current bundles require `WordPressSeedState(faces_count=0, people_count=0)`. `assert_seed_bundle_state` is the single service assertion available to provisioning and reset flows.
- `provision_demo` now fails loudly on stale face/person state and disables the newly created WP user before propagating the failure.
- `demo-provision` verifies that seeded attachments are present and that the WP projection has zero identity members and zero people before minting credentials.
- tests inject a stale bundle (`faces_count=3`, `people_count=1`) and prove provisioning raises rather than proceeding.

RED output (test-first lanes): same collection failure shown under AUTH-01; the test imported the not-yet-implemented seed-state contract and error.

GREEN output: included in the 47-test green run above.

residual risk / what a reviewer should attack:

- Guarantee: a successful production `demo-provision` means seeded WordPress media exists, scanned-face/member count is zero, and the exact frontend source table for `people_count` is empty. Enforcement exists both as the Python seed-bundle contract/service assertion and at the remote WP-CLI boundary before any credential is handed out.
- The current deployment is one shared WordPress demo. If one viewer scans it, a second provision correctly fails rather than silently resetting the first viewer's work. Parallel isolated demos require per-instance WordPress storage, which is outside this lane.

## DEMO-UX-1-AUTH-03 — FIXED

canon rows satisfied: RLSE-11, TEAM-08. `rg-006` was cited by the finding but is not present in the staged `/tmp/canon/*.md` corpus; its stated command-runs-as-written acceptance was still verified.

what changed (files + why):

- `Makefile`: added self-service `demo-provision`, `demo-expire`, and `demo-sweep`; extracted the shared `OCI_SSH` hop used by these and `admin-oci-mint`; added help/phony entries. UUID/URL, label, seed, slug, generated username/password, WP table prefix, numeric IDs/counts, and all remotely returned slugs are allowlist-validated at their relevant trust boundaries.
- `key-management.md`: added canonical Track 3 documentation for tenant + API key + WP user, TTL/quota, pre-scan state, single revoke, sweep, and rotation.

RED output (test-first lanes): NO-TDD finding.

GREEN output:

```text
$ make -n demo-provision LABEL='Acme Gallery' SEED=default
set -e; label="${LABEL:-}"; seed="${SEED:-default}"; ...
ssh ubuntu@acx-backend.tail1a44b8.ts.net "set -e; label='$label'; seed='$seed'; cd /opt/acx-backend/demo; wp='docker compose -f docker-compose.demo.yml run --rm --no-deps wpcli wp'; ... cd /opt/acx-backend/prod; cli='docker compose -f docker-compose.env.yml exec -T api python -m scripts.provision_demo --env prod --wp-managed-by-wrapper'; ..."
echo "→ credentials shown once; install the API key for the matching tenant and hand only the demo-* WP login to the viewer."

$ make -n demo-expire SLUG=3mJr7Ao CONFIRM=3mJr7Ao
set -e; slug="${SLUG:-}"; confirm="${CONFIRM:-}"; ...
ssh ubuntu@acx-backend.tail1a44b8.ts.net "set -e; slug='$slug'; user='demo-$slug'; cd /opt/acx-backend/demo; wp='docker compose -f docker-compose.demo.yml run --rm --no-deps wpcli wp'; ... cd /opt/acx-backend/prod; docker compose -f docker-compose.env.yml exec -T api python -m scripts.provision_demo --env prod --wp-managed-by-wrapper expire --slug \"$slug\""
echo "→ expired $slug (WP login removed; demo registry and API key revoked)."

$ make -n demo-sweep
set -e; ssh ubuntu@acx-backend.tail1a44b8.ts.net "set -e; cd /opt/acx-backend/prod; sweep='docker compose -f docker-compose.env.yml exec -T api python -m scripts.sweep_expired_demos --env prod --wp-managed-by-wrapper'; slugs=$($sweep --list-only); ...; $sweep"
echo "→ demo expiry sweep complete."
```

All three targets exited 0 under `make -n`; the rendered commands include input guards, the shared SSH hop, prod API-container CLI, and demo WP-CLI container.

residual risk / what a reviewer should attack:

- Dry-run proves Make expansion and command construction, not connectivity/remote image freshness. The first live production invocation should be observed for installed image version and compose project naming.
- The long inline remote recipes are reviewable but dense. If another lifecycle operation is added, promote the remote saga to a versioned host-side script rather than extending the inline shell.

## DEMO-UX-1-AUTH-04 — FIXED

canon rows satisfied: SEC-04, SECD-07 (analysis only as directed; route unchanged).

what changed (files + why): no route or response change.

RED output (test-first lanes): analysis-only finding.

GREEN output: the existing demo router tests remain green in the 47-test run above.

residual risk / what a reviewer should attack:

Threat model:

- Reachability: any Internet client can call `GET /x/{slug}`. Likely attackers include blind scanners, distributed botnets, a recipient who forwards a link, anyone receiving a slug via browser history/referrer/log/analytics leakage, and insiders with operational telemetry.
- Asset value by field: `tenant_id` is a stable internal identifier useful for correlation and probing tenant-scoped interfaces; `seed_bundle` fingerprints the configured scenario/prospect; `branding_json` can identify the prospect and expose unreleased/custom campaign data; `expires_at` reveals the useful attack window and business timing; `quota_remaining` is an activity side channel and tells an attacker how much compute can still be consumed. Field combinations make correlation more valuable than any field alone.
- Slug protection: seven base58 characters provide `58^7 = 2,207,984,167,552` possibilities, about 41 bits. A per-IP rate limit makes blind search from one address impractical. It does not protect a leaked slug, and distributed sources weaken the per-IP bound. The slug therefore buys resistance to guessing, not authentication or authorization.
- Principal failure paths: leaked-link replay; distributed enumeration; prospect/tenant correlation through returned metadata; activity/quota surveillance; and using a discovered live window to target quota exhaustion or adjacent tenant-object probes.

Options ranked strictest to least strict:

1. Gate behind the demo WordPress session. Strongest match to the settled workbench-only product: only the authenticated guided user resolves context. Cost: session proof must cross the WP/backend boundary, direct links/pre-login resolution change, and caches/tests must become session-aware.
2. Require the demo WP server-side service credential. The browser calls WordPress, which resolves the slug server-to-server; the credential never reaches the visitor. Cost: add/operate a proxy, scope and rotate a service credential, preserve client IP/rate semantics deliberately, and prevent the proxy becoming a confused deputy.
3. Drop `tenant_id` from the public response. Cheapest compatibility change and removes the most reusable internal identifier. Cost: clients using it need a replacement, while seed/branding/expiry/quota metadata and leaked-slug replay remain public.

Operator decision required; no mechanism was selected in this lane.
