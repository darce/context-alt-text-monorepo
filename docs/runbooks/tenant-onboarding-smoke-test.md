# Tenant onboarding smoke test

Run one WordPress site at a time, in the order below. This procedure checks
the effective endpoint, authentication and tenant isolation, followed by a
separate enrollment and held-out recognition flow. A connection check,
health response, empty gallery, or successful name assignment alone is not a
smoke pass. This is an operator runbook, not evidence that a runtime smoke has
been performed.

Read [tenant key administration](admin-tenant-keys.md) for supported local
administration, [portal development E2E](portal-dev-e2e.md) for the Clerk dev
portal flow, and [production Clerk authentication](clerk-production-auth.md)
for production claims, deploy and certificate requirements. The generic
production API examples in other runbooks use the InsightFace production
stack. The demo (Site 1) uses that same existing generic production API store;
no FIR production store is a dependency of this runbook.

## 1. Ordered targets and stop gates

| Order | WordPress site | Required service and model space | Effective recognition URL | Key environment | Current gate |
| --- | --- | --- | --- | --- | --- |
| 1 | Hosted demo at https://demo.altcontext.com/wp-admin/ | Existing generic production API store, InsightFace 512D; no separate production store dependency | Authenticated effective URL of that API, verified at run time; not pinned in this runbook | prod, existing generic production store only | **PENDING.** Read-only verification of that store (serving image, source identity, ACX_ENV, database host, CLI presence) and the section 1 resource gates before any write. |
| 2 | LocalWP wp-context-alt-text at http://localhost:10010/wp-admin/ | Laptop-only InsightFace 512D evaluation | http://localhost:8000 | local | Start and verify the maintained local service; verify the active plugin release and provider disclosure. |
| 3 | LocalWP fir at http://localhost:10028/wp-admin/ | Existing in-house FIR dev-fir stack, SFace 128D model space | https://fir.dev.api.altcontext.com | dev-fir | Use the measured dev-fir Compose stack and verify its in-container environment and active profile. |

Set each tenant's site URL to the exact origin in this table, without
wp-admin. Give each site/store mapping a fresh tenant UUID and a key issued
from that same store. A key authenticates as its owning tenant; WordPress has
no caller-supplied tenant ID. Do not recycle an existing tenant UUID:
tenant create updates the site URL when that UUID already exists.

### Site 1: demo on the existing generic production API

The demo (Site 1) uses the existing generic production API store:
/opt/acx-backend/prod and container acx-prod-api-1, which run the InsightFace
512D stack. No FIR production store is a dependency of Site 1, and the
fir.api.altcontext.com hostname is not used for any site in this runbook. Its
effective URL is not pinned here; verify it from the deployed routing at run time.

Before any Site 1 write, verify read-only against that existing store: the
Compose project and API service; the deployed image and its source identity;
ACX_ENV and the database host; the database, project and role; the active
profile and model ID (InsightFace 512D); the Clerk verifier settings used by the
portal; and the effective routed target of demo.altcontext.com. Require /ready,
authenticated /health/detailed and all three actual vector columns at the
configured width. Confirm the hostname's TLS and upstream route. The API and
worker must report the same provenance and the same store identity.

Repeat fresh native resource admission immediately before any write, using
current gauges and accepted pending costs. The PGDATA guard requires root use
below 90%; a later below-90% sample alone does not admit provisioning. Heavy
image builds remain on **HOLD** until root use is below 80% and fresh
whole-host admission passes. The most recent parent-supplied reading
(2026-10-12) was above 90% root use, so both gates are on **HOLD**. Do not
weaken either threshold or prune to clear them.

Before any deployment or write, the gates run in this order: source join,
capacity admission, image and source identity, and recovery (a verified backup
and rollback path). The maintained CLI must be present in the serving image, and
its real ACX_ENV and database host must satisfy its supported --env prod
contract.
If any detail is unavailable or differs, stop and ask the stack owner for its
runbook; do not guess an environment selector, directory, service name, store,
command, or successful output.

Only after that read-only gate passes may an operator set the explicit
PROD_API_STACK_DIR variable to the verified existing generic production
directory and use the conditional commands in sections 2 and 3. Leave it unset
while the directory is unverified. FIR_PROD_STACK_DIR is not used by this
runbook. Those commands are not a claim that they have run.

### LocalWP and plugin release gates

The two LocalWP roots are:

| Site | LocalWP root | Site URL |
| --- | --- | --- |
| wp-context-alt-text | /Users/daniel/Development/wp-context-alt-text/app/public | http://localhost:10010 |
| fir | /Volumes/Butter/WP/fir/app/public | http://localhost:10028 |

Both current plugin symlinks point to release 0.0.35-066c3aa13, while the
source declares version 0.0.36. Before testing, inspect the active symlink
resolution and record the exact built/released source commit or artifact
identity. Verify it against the approved plugin release source; a version
string by itself is insufficient. Use a stable release path; do not change
either artifact or point it at an ephemeral worktree.

In each dashboard, record the active plugin release and confirm the effective
recognition URL and source before saving a key. The resolver gives precedence
to ACX_RECOGNITION_URL, then the acx_recognition_base_url filter, then the
saved URL; a rejected higher-priority value fails closed. The local endpoint
requires the supported ACX_RECOGNITION_SOURCE=local source hatch, configured
through its documented constant or filter. The retired source option is not
supported. The CLI's --env local is only a database-host guard; it does not
select an API provider.

The Site 2 InsightFace disclosure is implemented and regression-covered in UI
source 4a65721c8e7cd9d546de4566438f27dadc87da8c, tree
0946596f54e5fc0f28a13158656406b6b9cc7b7d. This source is VERIFIED and LANDED
on local main, which has not been pushed; it is not active in the currently
served plugin. Keep the disclosure **PENDING** until the approved source is
present in a VERIFIED SERVING plugin artifact and the active settings page
visibly identifies InsightFace. The source follows the existing settings UX maps
254/267: pending, dirty, saving, stale and unknown states have no annotation;
current authenticated InsightFace settings show one passive
`Recognition engine: InsightFace` annotation; FIR and AuraFace show none. Do
not add a FIR annotation to the generic settings UI or mark Site 3's UI
disclosure as passed. Verify Site 3's actual backend profile and model evidence
instead.

## 2. Clerk sign-in, invitation and claim

Clerk authenticates the portal user. A tenant API key separately authenticates
the WordPress PHP server to the recognition API. A session JWT or Clerk key
does not provision a tenant or model gallery.

| Mode | Clerk account portal and browser origin | Explicit API verifier |
| --- | --- | --- |
| Development | https://saved-frog-4170.accounts.dev; portal origin http://localhost:5173 | ACX_CLERK_ISSUER=https://saved-frog-4170.clerk.accounts.dev; ACX_CLERK_JWKS_URL=https://saved-frog-4170.clerk.accounts.dev/.well-known/jwks.json; ACX_CLERK_AUDIENCE=altcontext-portal; ACX_CLERK_AUTHORIZED_PARTIES=http://localhost:5173 |
| Production | https://accounts.altcontext.com; deployed portal origin https://app.altcontext.com | Set ACX_CLERK_ISSUER and ACX_CLERK_JWKS_URL from the matching production pk_live_ key's FAPI hostname, using the production Clerk runbook. Set ACX_CLERK_AUDIENCE=altcontext-portal and ACX_CLERK_AUTHORIZED_PARTIES=https://app.altcontext.com. Keep all four values explicit. |

The issuer/JWKS must belong to the same Clerk instance as the browser key.
Audience and authorized parties are distinct exact values; do not use
wildcards or add LocalWP origins unless that origin actually issues the portal
session. The production pk_live_ browser key's ordinary-localhost restriction
is separate from a production tenant API key used server-to-server by the PHP
plugin from LocalWP. Use the dev instance's pk_test_ key only for the
development portal and the production pk_live_ key only on
https://app.altcontext.com. Session templates must include the required
audience and verified primary email claims:

    {
      "aud": "altcontext-portal",
      "email": "{{user.primary_email_address}}",
      "email_verified": "{{user.email_verified}}"
    }

Keep any Clerk secret in the approved backend secret store; this service's
session verification does not require an sk_ key. WordPress receives only its
tenant API key from these credentials.

### Development Clerk sweep

Use the existing development portal and its configured dev identity store.
The invitation CLI supports --env dev, not --env dev-fir. An invitation or
portal key in the dev store is not a Site 3 dev-fir tenant/key. Complete any
dev-fir WordPress key setup separately in section 3, and keep an explicit
site-to-store mapping.

After the dev verifier, session template and authorized party above are
deployed, create a single-use invitation in the matching dev API store:

```sh
cd /opt/acx-backend/dev
docker compose -f docker-compose.env.yml exec -T api sh -c 'test "$ACX_ENV" = dev'
docker compose -f docker-compose.env.yml exec -T api python -m scripts.manage_portal_invitations --env dev create --email <verified-smoke-account-email> --ttl-hours 72
```

In the existing dev portal at http://localhost:5173, sign in, redeem the
one-time token in the existing invitation claim flow, and confirm the signed-in
portal's /portal/me request returns 200. A 401 from an unauthenticated probe
only shows that the route is mounted. If exercising the portal's API-key
screen, use its existing create action and keep that key in the dev store; do
not assume it is the dev-fir WordPress key. The token is displayed once; do not
save it in shell history, logs, screenshots or Git. Start/render the dev
portal against the dev API using the maintained steps in
[portal development E2E](portal-dev-e2e.md).

For a development-instance email-code smoke, Clerk documents reserved
+clerk_test addresses and code 424242; that code flow skips sending email.
Clerk development instances default to test mode. Email-link sign-in still
delivers a message. Development email CNAMEs are not needed.

### Production Clerk sweep

Site 1 is the existing generic production API store. First complete the Site 1
store gate in section 1, including a verified production Clerk verifier and a
serving API image that contains the maintained invitation CLI. The invitation is
issued only in the store that the portal's API upstream is verified to reach.

**Stop before issuing or claiming an invitation** until a read-only preflight
proves that the portal and invitation CLI reach the same intended store.
Inspect the deployed portal's actual browser request construction and targets
for CLAIM, ME and KEY against the live app-host routing and API/database
mapping; trace each to the exact API service and store used by
`PROD_API_STACK_DIR`. This preflight is read-only: do not claim an invitation or
create a key to test it. Do not infer the store from the hostname, a mounted
route, a 401 response or a successful CLI command. In particular,
[`app-portal.sh`](../../scripts/deploy/app-portal.sh) defaults
`APP_UPSTREAM` to `prod-api:8000`, and the supplied production stack at that
upstream is the same existing generic InsightFace store that Site 1 uses.
Verify the deployed upstream itself; do not change or retarget production
configuration in this lane.

Before the invitation command, also verify that the portal is enabled on that
same API; its production Clerk issuer and JWKS URL, session audience
`altcontext-portal`, and authorized application origin agree with the production
Clerk instance and frontend; and the exact browser origin and authorized party
are `https://app.altcontext.com`. The four issuance guards (source, digest,
issuer and store) are listed in
[production Clerk authentication](clerk-production-auth.md#post-launch-signed-in-smoke-check).
If any request-to-store, portal-enable, Clerk or origin mapping is unknown or
differs, stop before invitation issuance and leave the production portal sweep
**PENDING**. A later CLI key fallback cannot make a claim made in another store
a Site 1 claim.

Only after that preflight passes, set the verified directory explicitly:

```sh
if [ -z "$PROD_API_STACK_DIR" ]; then echo "Set PROD_API_STACK_DIR only after verifying the existing generic production stack for Site 1; FIR_PROD_STACK_DIR is not used by this runbook" >&2; exit 1; fi
cd "$PROD_API_STACK_DIR"
docker compose -f docker-compose.env.yml exec -T api sh -c 'test "$ACX_ENV" = prod'
docker compose -f docker-compose.env.yml exec -T api python -m scripts.manage_portal_invitations --env prod create --email <verified-smoke-account-email> --ttl-hours 72
```

The command is conditional on verifying that this exact directory uses the
maintained Compose file/API service, ACX_ENV=prod, matching database, production
verifier and invitation CLI already matched by the preflight. If not, stop.
Sign in at https://app.altcontext.com with a real production account, redeem
the invitation only after the preflight, confirm /portal/me returns 200, and
check the decoded session claims locally: aud is altcontext-portal and azp is
https://app.altcontext.com. Never paste a JWT into a website or commit it.
Production test mode is technically possible but discouraged; use real
production authentication and delivery for this sweep. Copy production email
deliverability targets only from that Clerk instance's Dashboard. If the live
claim or /portal/me request resolves to any other store, stop; keep the
production portal sweep **PENDING** and do not describe that claim as Site 1
onboarding.
Use the portal's existing key-creation flow only when the preflight proved its
KEY request writes to this same Site 1 store. A separately issued WordPress key
can be used only for its verified store and does not repair a claim in another
store. Do not mint two keys for one tenant or present unrelated stores as one
onboarding sweep.

The existing portal flow and the WordPress tenant/model-space setup are
separate checks, and each store has its own sweep. One Clerk user may bind
independently in distinct stores, but those bindings are not one onboarding
sweep. Within one store, provision_customer uses email as its idempotency key
and reuses the tenant; do not promise that repeating the same email creates a
new site tenant. Automation needs explicit per-site/per-stack tenant mappings.
Neither a successful login nor an invitation claim proves a tenant key or
gallery exists.

Official Clerk references: [development instances](https://clerk.com/docs/guides/development/managing-environments),
[test emails and phones](https://clerk.com/docs/guides/development/testing/test-emails-and-phones),
[production keys in local development](https://clerk.com/docs/guides/development/troubleshooting/using-production-keys-in-development),
and [production Clerk authentication](clerk-production-auth.md).

## 3. Create site tenants and keys

Provision only after the target stack, source/model profile, verifier and
effective URL are verified. Use a fresh tenant UUID for each site/store and
the exact site origin from section 1. The CLI prints the raw key once as
api_key=... and writes key_id to stderr. Copy the raw key directly into the
approved secret manager and the matching WordPress API-key setting. Record
only non-secret tenant and key IDs. Never capture the raw value in a
transcript, log, screenshot, ticket or Git file.

### Site 1 — demo on the existing generic production API

These commands require the section 1 gate and a verified PROD_API_STACK_DIR,
which is the existing generic production directory. FIR_PROD_STACK_DIR is not
used here.

```sh
if [ -z "$PROD_API_STACK_DIR" ]; then echo "Set PROD_API_STACK_DIR only after verifying the existing generic production stack for Site 1; FIR_PROD_STACK_DIR is not used by this runbook" >&2; exit 1; fi
cd "$PROD_API_STACK_DIR"
docker compose -f docker-compose.env.yml exec -T api sh -c 'test "$ACX_ENV" = prod'
docker compose -f docker-compose.env.yml exec -T api python -m scripts.manage_api_keys --env prod tenant create --tenant <site-1-tenant-uuid> --site-url https://demo.altcontext.com
docker compose -f docker-compose.env.yml exec -T api python -m scripts.manage_api_keys --env prod create --tenant <site-1-tenant-uuid> --tier STANDARD
docker compose -f docker-compose.env.yml exec -T api python -m scripts.manage_api_keys --env prod list --tenant <site-1-tenant-uuid>
```

Replace placeholders locally. Run only if read-only verification proved this
directory, API service, image, store and environment match the existing generic
production target for the demo. The commands have not been run in this
documentation change.

### Site 2 — local InsightFace

From the maintained service checkout, use the local runner and local admin
console in [tenant key administration](admin-tenant-keys.md):

```sh
cd apps/prototype-description-service
make admin-dev
```

Open http://localhost:8000/admin/ and create a fresh tenant for
http://localhost:10010, then mint its STANDARD key. Confirm the local API's
actual profile is InsightFace and its local database is selected before
issuing. The alternative CLI's --env local validates a local DSN; it does not
switch a provider or authorize a remote store.

### Site 3 — measured dev-fir stack

Run these on the dev-fir service VM, from the measured stack directory. First
verify ACX_ENV inside the API container; the maintained CLI also requires
--env dev-fir and checks that its configured database host matches:

```sh
cd /opt/acx-backend/dev-fir
docker compose -f docker-compose.env.yml exec -T api sh -c 'test "$ACX_ENV" = dev-fir'
docker compose -f docker-compose.env.yml exec -T api python -m scripts.manage_api_keys --env dev-fir tenant create --tenant <site-3-tenant-uuid> --site-url http://localhost:10028
docker compose -f docker-compose.env.yml exec -T api python -m scripts.manage_api_keys --env dev-fir create --tenant <site-3-tenant-uuid> --tier STANDARD
docker compose -f docker-compose.env.yml exec -T api python -m scripts.manage_api_keys --env dev-fir list --tenant <site-3-tenant-uuid>
```

Replace placeholders locally. The CLI's --env values prod, local and dev-fir
are database safety guards, not provider or model selectors. The invitation
CLI does not support --env dev-fir; do not invent that invocation.

### CLI mint/revoke and portal rotation are different contracts

The maintained manage_api_keys CLI has separate tenant create, key create,
list and revoke --key-id operations. CLI/admin create mints an independent
key; it does not perform portal rotation or promise portal grace, replay or
one-primary behavior. For a CLI/admin-managed WordPress key, the supported
replacement sequence is create new key, configure it, verify it, revoke the
old key ID, then prove the old key is denied and the new key still works.
This sequence applies only to those CLI/admin-issued keys.

The portal uses its existing supported rotate operation and its own
one-usable-primary, bounded-grace and idempotency contract. The confirmed
GTMSMOKE-AUTH-01 recovery defect is: create K1, rotate to K2, revoke all,
create K3, then rotation of K3 is rejected because historical K2 remains the
selected replacement. The correction and regression are landed on main as
Auth78c at eac89400e5de70d1ce9313f81296764cee2a2c4b, with 8 native PASS
results and an independent MAX PASS. Serving API image deployment and the
real portal rotation/recovery smoke remain **PENDING**. Do not claim the
portal rotation/recovery sweep passed or substitute CLI create/revoke for
portal rotation. Retest only after the approved source is present in a
VERIFIED SERVING artifact, and require actual runtime outcomes for the full
recovery sequence. Do not invent portal flags, routes or payloads.

## 4. Configure WordPress and prove key isolation

For Sites 2 and 3, start each named LocalWP site in the LocalWP app and confirm
its wp-admin URL opens. Use the existing remote WordPress access path for the
hosted demo. Do not run development and production sweeps concurrently against
one WordPress settings page: finish, capture the redacted evidence, and restore
that instance's intended target/key before switching Clerk mode or site.

For each row:

1. Verify the active plugin build/source revision, provider source, effective
   recognition URL and model/profile evidence. Save only that row's tenant
   API key in the plugin setting. WordPress receives no Clerk JWT, Clerk
   publishable or secret key, admin token, database credential, GPU credential
   or OCI credential.
2. Use the existing Test Connection action, then a harmless authenticated
   action against the intended API. Require /ready, authenticated
   /health/detailed and scoped evidence from the actual store. A bare /health
   200 is static and is not readiness, key proof or a gallery check.
3. In an isolated smoke context, test the correct key, no key, an arbitrary
   invalid key and a key from another stack. Run the no-key check only when no
   ACX_RECOGNITION_API_KEY fallback supplies a deployment key. A valid key
   from another tenant in the same store identifies that tenant; it is not an
   invalid key. Use an existing harmless action to prove it cannot read or
   mutate the target tenant's data. If that isolation check needs an
   undocumented route or selector, leave it PENDING. Restore the correct key
   and reconfirm success after the negative controls.
4. For CLI/admin key replacement, keep the old key active until the
   replacement is configured and verified. Revoke by the old key ID using
   the same verified environment's maintained CLI or admin console, then
   prove the old key is denied and the new one still passes. Never leave a
   revoked key configured in the active site.

For Site 1 (demo) revocation, use only the already verified PROD_API_STACK_DIR
and the same maintained CLI/API service:

```sh
if [ -z "$PROD_API_STACK_DIR" ]; then echo "Set PROD_API_STACK_DIR only after verifying the existing generic production stack for Site 1; FIR_PROD_STACK_DIR is not used by this runbook" >&2; exit 1; fi
cd "$PROD_API_STACK_DIR"
docker compose -f docker-compose.env.yml exec -T api python -m scripts.manage_api_keys --env prod revoke --key-id <old-key-id>
```

For dev-fir, use the measured directory and matching guard:

```sh
cd /opt/acx-backend/dev-fir
docker compose -f docker-compose.env.yml exec -T api sh -c 'test "$ACX_ENV" = dev-fir'
docker compose -f docker-compose.env.yml exec -T api python -m scripts.manage_api_keys --env dev-fir revoke --key-id <old-key-id>
```

For Site 2, revoke through the local admin console that issued the key. Keep
raw keys out of all evidence.

## 5. Enroll one person, then test a different held-out recognition photo

Use private operator-controlled photos that are not committed or included in
screenshots. Upload them through WordPress Media > Add New, then follow the
current Workbench flow. The maintained UI calls its surfaces Workbench,
Review Queue and People. The
current review control says Name this person and Save name. See
[Workbench](../../apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx),
[People](../../apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx),
[person naming](../../apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/PersonCommitControl.tsx)
and its [roster assignment API hook](../../apps/prototype-wp-alt-context/js/admin/pages/roster/hooks/useClusterActions.ts),
plus the closest maintained [scan E2E workflow](../../apps/prototype-wp-alt-context/tests/e2e/evidence/workbench-evidence.spec.ts).

1. Upload one or more enrollment photos through the WordPress Media Library.
   In Workbench, use Scan, select those media rows, and choose Analyze selected
   media. Wait for Scan complete and clustering to finish; use Cluster the
   latest job results only when that current action is offered.
2. In Review Queue, inspect the resulting face group. In Name this person,
   enter the independently verified person's name or choose the exact existing
   People match, then use Save name. Confirm that the person appears in People.
   This is the gallery enrollment step. Record the enrollment media, scan/job,
   face-group and person IDs.
3. Upload a different held-out photograph from a separate capture/session and
   scan it through the same Workbench flow. Do not name, accept, auto-accept,
   or silently enroll this held-out probe. Confirm the system itself surfaces
   the expected named suggestion/recognition. A human accepting or assigning
   the held-out person's name is not automatic recognition evidence. If the
   held-out photo only creates an unnamed group or no expected named
   suggestion, do not mark recognition passed. This recognition result says
   nothing about image description; follow the separate description procedure
   below.
4. Include an independently verified unknown person and a wrong-person
   negative. Confirm that the unknown is not given a known name, the wrong
   identity is not suggested as a correct match, and data from another tenant
   is not visible. Record the resulting scan/job/person IDs and outcomes.

Enrollment/gallery creation and held-out retrieval are separate events. A
health 200, ready response, successful empty scan, empty gallery, or manually
assigned held-out name is not a recognition pass. Do not turn probe auto-enroll
or review acceptance on during quality comparison.

### Separate image-description smoke

Keep this result separate from the CPU face-recognition result above. A face
scan, recognition suggestion, or source test is not evidence that image
description ran. Site 2's local-only InsightFace evaluation is a recognition
target; do not count its CPU face work as a description result.

Pre-demand config and credential checks come first, and they do not require the
GPU endpoint to be live. Verify the target's own server-side configuration and
deployed image: the description adapter is a maintained GPU-backed adapter, its
description worker is deployed, and the endpoint credential is minted and
installed server-side (pre-demand config/credential checks). For the maintained
dev example, [portal-dev-e2e](portal-dev-e2e.md) specifies
`ACX_DESCRIPTION_ADAPTER=gpu_qwen30b`; it requires the GPU endpoint key to be
minted and installed on the GPU host and in the dev environment. Follow
[GPU endpoint key minting](gpu-key-mint.md) and the readiness and durable-run
checks in [GPU demo environment flip](gpu-demo-env-flip.md).

Cold start order: the GPU endpoint is initially STOPPED. Prewarming is not a
prerequisite. The description demand itself causes a post-demand START of the
GPU endpoint. After that post-demand START, the endpoint must be live and
authenticated and report ready before any description request is sent.
Keep the endpoint credential on the server/GPU side; never put it in WordPress,
the browser, or the tenant API key field. For Site 1 and Site 3, prove these
prerequisites for their own API, worker and endpoint before use. The dev
example's `https://dev.api.altcontext.com` and adapter configuration do not
retarget either site. If any target-specific prerequisite or store mapping is
unproven, leave its description result **PENDING**.

After those checks pass, use a separate operator-controlled test attachment
that was not used for recognition enrollment or held-out scoring:

1. In the matching LocalWP site's **Settings > Alt Context**, set Service API
   URL to that site's already verified API and enter its WordPress tenant API
   key, then save to pair the tenant. The Clerk browser key and GPU endpoint
   credential are not WordPress tenant API keys. For the maintained dev setup,
   follow the exact target and prerequisite sequence in
   [portal-dev-e2e](portal-dev-e2e.md); do not substitute its API URL for a
   different site's verified URL. Use the current
   [Workbench UI map](../../apps/prototype-wp-alt-context/docs/ux-maps/workbench-2pane.md)
   for the maintained description-only toggle and Workbench labels; use this
   UI flow without inventing or calling API routes.
2. In **Settings > Alt Context**, record the current recognition-toggle state,
   turn **Identify people in photos** off and save. The Workbench footer should
   disclose that this run describes without identifying people. This keeps
   its description result independent of the face-recognition result.
3. In **Workbench**, select only the test attachment in the media library and
   choose **Describe 1 selected**. Wait for the run to complete, then choose
   **Review drafts** and inspect the item under **Description Runs**. Record
   the non-secret run/media IDs, adapter/model provenance and compute tier.
   **Compute tier: Final (GPU)** is the final GPU result; **Compute tier:
   Provisional (CPU)** is not a GPU description result, and **Compute tier:
   Unknown** or a queued/failed run remains pending. Do not overwrite an
   existing human-authored alt text merely to produce this evidence. Restore
   the recorded **Identify people in photos** state after the description run.

Parent GTMBURST-1 GPU action 61 remains **HOLD** until exact source and image,
live GPU and full-stack proof are available. A description draft from this
procedure or source tests alone cannot clear that hold or establish the
required description PASS.

Capture genuine, redacted backend evidence for each enrollment and retrieval:
actual API image/scan/job/person identifiers; tenant and key IDs; effective
target; active pipeline/profile and authentic model ID; readiness evidence;
and actual database vector typmods for all three columns. Preserve the
enrollment/held-out separation and confirm the enrollment was freshly
extracted from its source pixels by that active model. Store evidence in an
approved private, run-specific location outside Git. Never store raw photos,
keys, JWTs, real account email addresses, database credentials or screenshots
containing them in the repository.

## 6. Model-space and quality boundary

The actual vector columns that must match the selected store's configured
PGVECTOR_DIM are media_identities.embedding,
identity_cluster_representatives.embedding, and
mv_identity_cluster_centroids.centroid. Verify all three actual vector(N)
typmods in the selected database; configuration alone proves no provisioning.
Expected existing spaces are generic InsightFace 512D, FIR SFace 128D, and
AuraFace 512D. InsightFace and AuraFace remain distinct provenance even at
equal width. Each store's three actual columns must show the width for its
active profile: 512 for InsightFace, 128 for SFace and 512 for AuraFace. The
existing generic production store is expected to be InsightFace 512D, but its width is confirmed only from its three actual columns and authenticated active profile.
Require the authentic active profile/model ID, matching actual columns, and
fresh extraction for the enrollment. Never copy or pad vectors or share an
incompatible gallery. Store vectors are never inherited from the InsightFace or SFace stores, and a new store starts without inherited vectors. The measured dev-fir database was 128D; recheck the
selected store and active model before use.

Preserve the generic InsightFace and existing firSFace settings and endpoints.
AuraFace remains a separate candidate at these frozen target labels and exact planned names. Aura names are proposed configuration, not observed resources:

| Frozen target label | DNS name | Planned A record |
| --- | --- | --- |
| dev-auraface | auraface.dev.altcontext.com | 129.213.40.111, TTL 300 |
| staging-auraface | auraface.staging.api.altcontext.com | 129.213.40.111, TTL 300 |
| prod-auraface | auraface.api.altcontext.com | 129.213.40.111, TTL 300 |

Preserve fir.dev.api.altcontext.com, fir.api.altcontext.com,
dev.api.altcontext.com, staging.api.altcontext.com and api.altcontext.com.
Resolution is not service readiness. The 09:10 supplied inventory found
AuraFace DNS resolution but TLS failure, and found TLS failure for fir.api.
At 13:18 UTC, later checks confirmed all three AuraFace A records, while TLS
handshakes failed for all three AuraFace endpoints and production Clerk
(curl HTTP 000, exit 35). DNS resolution does not establish an upstream or
serving readiness. Do not route smoke traffic to an unverified upstream. Do
not add a new public InsightFace
evaluation deployment, change model defaults, or declare a model winner.
The earlier verified gte-base-en-v1.5 FIR 512 result and FIR-23 symmetric
stacks from merge 7928fa are prior evidence, not proof of the live profile of any store named in this runbook. Use them only if fresh authenticated profile/model
evidence confirms that exact contract.

#### Two spare sites for the three frozen Aura targets

| Spare LocalWP site | Site URL | Authorized role | Gate before any AuraFace work |
| --- | --- | --- | --- |
| r | http://localhost:10023 | AuraFace 512D candidate fixture | Back up the site first; install plugin 0.0.36 from a verified artifact; do not wipe existing content |
| vlm | http://localhost:10018 | AuraFace 512D candidate fixture | Back up the site first; install plugin 0.0.36 from a verified artifact; do not wipe existing content |

The two spare sites are the only AuraFace 512D fixtures authorized here for the three frozen Aura targets, and the third Aura target fixture is pending. Do not hijack an original site (the demo, localhost:10010 or localhost:10028) for the pending fixture or for any Aura target. Each spare site must be backed up and have plugin 0.0.36 installed from a verified artifact before any AuraFace work, so that a rollback point exists before the change (Canon RLSE-08). Do not wipe content on either spare site. Which spare site serves which target is recorded in the run record, not assumed here.

#### Proposed AuraFace stack naming (proposed configuration, not observed resources)

Each column uses its exact frozen target label as E. These names are proposed configuration only: none is an observed resource, and none has been created.

| Setting | dev-auraface | staging-auraface | prod-auraface |
| --- | --- | --- | --- |
| Project and unit | acx-dev-auraface | acx-staging-auraface | acx-prod-auraface |
| Stack directory | /opt/acx-backend/dev-auraface | /opt/acx-backend/staging-auraface | /opt/acx-backend/prod-auraface |
| Image tag | dev-auraface | staging-auraface | prod-auraface |
| Network | acx-dev-auraface-net | acx-staging-auraface-net | acx-prod-auraface-net |
| Aliases | dev-auraface-api, dev-auraface-api-next | staging-auraface-api, staging-auraface-api-next | prod-auraface-api, prod-auraface-api-next |
| PGDATA | /opt/acx-backend/data/dev-auraface-pgdata | /opt/acx-backend/data/staging-auraface-pgdata | /opt/acx-backend/data/prod-auraface-pgdata |
| Model root | /opt/acx-backend/data/dev-auraface-models | /opt/acx-backend/data/staging-auraface-models | /opt/acx-backend/data/prod-auraface-models |
| Load directory | /run/acx-write/dev-auraface | /run/acx-write/staging-auraface | /run/acx-write/prod-auraface |
| Blob storage | project-owned acx_blobs | project-owned acx_blobs | project-owned acx_blobs |
| Database | alt_context_dev_auraface | alt_context_staging_auraface | alt_context_prod_auraface |
| Database role | acx_dev_auraface | acx_staging_auraface | acx_prod_auraface |
| ACX_ENV | dev-auraface | staging-auraface | prod-auraface |
| Vector width | PGVECTOR_DIM=512 | PGVECTOR_DIM=512 | PGVECTOR_DIM=512 |
| Face pipeline | RECOGNITION_FACE_PIPELINE_PROFILE=auraface; FACE_PIPELINE_MODELS_DIR and AURAFACE_MODELS_DIR both /data/cache/face_pipeline | same as dev-auraface | same as dev-auraface |
| Secrets and DSN | distinct secret reference and DSN per target | distinct per target | distinct per target |
| Admin | auth enabled; public admin denied | auth enabled; public admin denied | auth enabled; public admin denied; no generic-prod admin overlay |

Before any AuraFace deployment, these preconditions run in order: runtime source join, capacity admission, image and source identity, and recovery (a verified backup and a practiced rollback path). API and worker provenance must agree with the store identity they serve (database, role and ACX_ENV). Each new store starts without vectors. Store vectors are never inherited from the InsightFace or SFace stores.

Functional onboarding and model quality are separate gates. Scorer repair is independent from endpoint work: a scorer fix neither gates nor unblocks endpoint onboarding, and endpoint readiness does not validate a scorer. For a quality
comparison, reuse [FIR-16](../tasks/fir/FIR-16-open-set-head-to-head-task-plan.md)
and the [current FIR dimensions/detectors report](../../benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html).
Use fixed mated and genuinely non-mated source denominators with independent
ground truth. Keep detector, association, alignment and embedding misses in
the end-to-end denominators; compute FNIR from the fixed mated source set and
FPIR from the fixed eligible non-mated source set, never from detector-created
counts or gallery size. Alarms must not dilute the non-mated denominator.
Calibrate each model space on validation data only, freeze settings, then score
a real untouched holdout with no probe enrollment or auto-accept. Pair
identities and sessions and use identity/session-clustered uncertainty. Predeclare
the FPIR operating point, practical margin, critical slices, multiplicity and
power. Do not invent thresholds or margins or claim a win from the report's
253 units.

Keep these existing evaluation rules attached to the comparison: Canon v0.25.6
EMB-01, one embedding space per comparison; IDX-02, rebuild the index when
the embedding contract changes (Foundations of Vector Retrieval, chapter 1);
EVAL-16, upstream failure counts; EVAL-18, use non-mated probes and a score
threshold; EVAL-19, detector alarms must not dilute FPIR (IARPA Janus
Benchmark-C, section 2.3.4); NAME-03, no lying names (The Programmer's Brain,
chapter 9); and GRPH-09, colour conflict graph (Graph Theory Applications,
chapter 8).

## 7. Supplied status, pass criteria and records

Supplied source-status snapshot — **2026-10-11 13:58 UTC**. These source,
test, endpoint and resource facts were supplied for this documentation update;
they are not fresh observations made by the documentation change. Recheck the
actual build and runtime when an operator runs this procedure. This dated
snapshot does not replace those checks.

- **Stack inventory:** the 09:10 inventory contained dev-fir only; it did not
  identify a dedicated FIR production directory or running container.
  Generic /opt/acx-backend/prod and acx-prod-api-1 are InsightFace. Keep the
  existing generic InsightFace, firSFace and exact three AuraFace host
  contracts; production FIR profile/width remains unknown until authenticated
  runtime evidence confirms it.
- **Endpoint and plugin checks:** at 13:18 UTC, all three AuraFace A records
  matched their expected values. TLS handshakes failed for all three AuraFace
  endpoints and production Clerk `/sign-in`: each curl result was HTTP 000,
  exit 35. The development Clerk endpoint returned HTTP 200, curl exit 0;
  `demo.altcontext.com/wp-admin` returned HTTP 301, curl exit 0. These checks
  do not prove an upstream, a complete sign-in/invitation/claim sweep, a
  serving plugin artifact or an end-to-end smoke. LocalWP ports 10010 and
  10028 remained closed (HTTP 000, curl exit 7); their active plugin symlinks
  still named 0.0.35-066c3aa13 while source declares 0.0.36. Curl exit 35 is
  not an HTTP status or a PASS.
- **Auth source and tests:** the GTMSMOKE-AUTH-01 correction and regression
  (Auth78c) are LANDED on main at
  eac89400e5de70d1ce9313f81296764cee2a2c4b, with 8 native PASS results and an
  independent MAX PASS. API deployment and the real live portal
  rotation/recovery smoke remain **PENDING**.
- **UI source and tests:** source 4a65721c8e7cd9d546de4566438f27dadc87da8c,
  tree 0946596f54e5fc0f28a13158656406b6b9cc7b7d, implements the Site 2
  InsightFace disclosure and regression coverage. It is VERIFIED and LANDED
  on local main; main has not been pushed. Independent Sol MAX reviews j1b43
  and j290 both returned PASS with no findings. Native child 4466 reported
  127 tests passing across five Settings-page modules in 23.81 seconds, with
  the full TypeScript check returning 0. Public close is READY and task finish
  is COMPLETE; the UI worktree (UIWT) has been removed and its feature branch
  retired. These source, review and test results do not establish serving or
  runtime PASS.
- **Serving artifact and runtime:** the active plugin remains
  0.0.35-066c3aa13, so the Site 2 disclosure is not active in that artifact.
  API deployment, plugin serving verification, live portal recovery, live
  WordPress smoke, GPU61 and end-to-end/runtime PASS evidence remain
  **PENDING**. Parent GTMBURST-1 GPU action 61 remains **HOLD** pending exact
  source/image, live GPU and full-stack proof. No onboarding keys have been
  issued.
- **Resource admission:** the 09:18 snapshot reported root storage at 93% and
  MemoryMax at 512 MiB. These are historical point-in-time readings; 512 MiB
  is not a static future allocation. The PGDATA guard requires less than 90%
  root use. The latest supplied native reading at 13:12 reported 13,965 MiB
  MemAvailable, 86.90% root use, 8.37 GB cgroup use and 465 PIDs. Fresh
  whole-host admission included full current custody, reported root forecast
  0, and all five retention controls at 0. The former static 13 GiB forecast
  is withdrawn. Use current gauges and accepted pending costs for admission
  immediately before provisioning; this dated snapshot does not admit a
  future operation. The 86.90% sample is below the separate 90% PGDATA
  threshold but above the 80% heavy-build threshold; heavy builds remain
  **HOLD** until root use is below 80% and fresh whole-host admission passes.

- **Parent-supplied snapshot, 2026-10-12 (not fresh observations of this change):** main is at 0d3ff19d with fixture 138 PASS accepted. The invitation CLI is present in the current source tree, but native check 4506 found it absent from all four serving images it checked, and the source anchors recorded for them are stale; serving presence is therefore unproven. The four original WordPress sites have plugin 0.0.36 installed; the r plugin is recorded inactive and is preserved as-is. Root use was above 90% in that reading, so image builds (below 80%) and PGDATA admission (below 90%) are on **HOLD**; thresholds are not weakened and nothing is pruned to clear them. A 300 GiB storage expansion is pending explicit user approval and is not assumed. This snapshot supersedes the 2026-10-11 FIR-production routing wording for the demo. All runtime actions are performed by the parent only; this document performs none.
- **Endpoint and UI history:** source-closed. This documentation change starts no fresh UI iteration. The Canon v0.25.6 rows cited here are pinned and read-only.

Do not claim this runbook or any site runtime PASS from these measurements.
Record recognition and description as separate results. A row can be **PASS**
only when the approved source is present in a VERIFIED SERVING artifact and
actual runtime outcomes establish that its stack and source gates pass;
effective routing, profile/model ID and all three actual vector columns agree;
correct and negative key controls behave as expected; scan/job/person evidence
is complete; and a distinct held-out photo yields the expected automatic
recognition without human naming. The description result needs its own
completed run and target-specific server/worker/GPU proof; a CPU face scan or
source tests cannot satisfy it. Parent GTMBURST-1 GPU action 61 remains
**HOLD** pending exact source/image, live GPU and full-stack proof, so keep the
affected description result **PENDING**. Keep portal rotation recovery
**PENDING** until approved Auth78c source is in a VERIFIED SERVING artifact
and the real portal recovery sequence passes with recorded runtime outcomes.

Keep the durable redacted execution record in an approved private run-specific
location outside Git. Record date/UTC, source and active plugin build identity,
site/store aliases, effective URL, non-secret tenant/key/person/scan/job IDs,
model/profile and vector dimensions, control outcomes, and private receipt
references. The record for this documentation change is: runtime smoke not
run; no onboarding keys issued; no E2E PASS asserted.
