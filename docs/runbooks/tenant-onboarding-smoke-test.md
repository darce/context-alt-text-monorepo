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
stack. They do not provision the demo's in-house FIR tenant.

## 1. Ordered targets and stop gates

| Order | WordPress site | Required service and model space | Effective recognition URL | Key environment | Current gate |
| --- | --- | --- | --- | --- | --- |
| 1 | Hosted demo at https://demo.altcontext.com/wp-admin/ | Dedicated in-house FIR production stack | https://fir.api.altcontext.com | prod, only in the verified FIR production store | **PENDING.** No dedicated FIR production directory or running container is present in the supplied inventory. |
| 2 | LocalWP wp-context-alt-text at http://localhost:10010/wp-admin/ | Laptop-only InsightFace evaluation | http://localhost:8000 | local | Start and verify the maintained local service; verify the active plugin release and provider disclosure. |
| 3 | LocalWP fir at http://localhost:10028/wp-admin/ | Existing in-house FIR dev-fir stack | https://fir.dev.api.altcontext.com | dev-fir | Use the measured dev-fir Compose stack and verify its in-container environment and active profile. |

Set each tenant's site URL to the exact origin in this table, without
wp-admin. Give each site/store mapping a fresh tenant UUID and a key issued
from that same store. A key authenticates as its owning tenant; WordPress has
no caller-supplied tenant ID. Do not recycle an existing tenant UUID:
tenant create updates the site URL when that UUID already exists.

### Site 1: production FIR must be identified first

The supplied production API directory, /opt/acx-backend/prod, and container
acx-prod-api-1 are the generic InsightFace stack. There is no dedicated FIR
production directory or running container in the supplied inventory. The
fir.api.altcontext.com target is not evidence that an FIR service is behind
it or ready.

Do not create a Site 1 tenant, invitation, or key in /opt/acx-backend/prod.
Before any such write, obtain and verify the actual dedicated FIR production
stack directory and owner instructions. Read-only verification must establish
the exact Compose project/profile and API service, deployed image identity,
database/project/role and storage, supported environment guard, active
profile and model ID, Clerk verifier settings, and the effective routed target.
Require /ready, authenticated /health/detailed and all three actual vector
columns in that store. Confirm the FIR hostname's TLS and upstream route.
Repeat native resource admission before
provisioning; the supplied root usage is 93% and the PGDATA guard requires
less than 90% used. The maintained CLI must be present in the image and its
real ACX_ENV and database host must satisfy its supported --env prod contract.
If any detail is unavailable or differs, stop and ask the stack owner for its
runbook; do not guess an environment selector, directory, service name, store,
command, or successful output.

Only after that read-only gate passes may an operator set the explicit
FIR_PROD_STACK_DIR variable to the verified directory and use the conditional
commands in sections 2 and 3. Leave it unset while the directory is unknown.
Those commands are not a claim that this stack exists or that they have run.

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

The Site 2 InsightFace disclosure is still pending implementation. Keep it
PENDING until the active settings page visibly identifies InsightFace. Do not
add a FIR annotation to the generic settings UI or mark Site 3's UI disclosure
as passed. Verify Site 3's actual backend profile and model evidence instead.

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

First satisfy the dedicated FIR production gate in section 1, including a
verified production Clerk verifier and a serving API image that contains the
maintained invitation CLI. Do not issue a Site 1 invitation through the
generic InsightFace /opt/acx-backend/prod stack. With the verified directory
set explicitly:

```sh
if [ -z "$FIR_PROD_STACK_DIR" ]; then echo "Set FIR_PROD_STACK_DIR only after verifying the dedicated FIR production stack" >&2; exit 1; fi
cd "$FIR_PROD_STACK_DIR"
docker compose -f docker-compose.env.yml exec -T api sh -c 'test "$ACX_ENV" = prod'
docker compose -f docker-compose.env.yml exec -T api python -m scripts.manage_portal_invitations --env prod create --email <verified-smoke-account-email> --ttl-hours 72
```

The command is conditional on verifying that this exact directory uses the
maintained Compose file/API service, ACX_ENV=prod, matching database, production
verifier and invitation CLI. If not, stop. Sign in at
https://app.altcontext.com with a real production account, redeem the
invitation, confirm /portal/me returns 200, and check the decoded session
claims locally: aud is altcontext-portal and azp is https://app.altcontext.com.
Never paste a JWT into a website or commit it. Production test mode is
technically possible but discouraged; use real production authentication and
delivery for this sweep. Copy production email deliverability targets only
from that Clerk instance's Dashboard. After claim, use the portal's existing
key-creation flow only if read-only verification proves its API writes to the
same dedicated FIR store. Otherwise issue the Site 1 WordPress key with the
verified CLI commands in section 3 and keep the portal key result scoped to
its actual store. Do not mint two keys for one tenant or claim a key from a
different store belongs to Site 1.

The existing portal flow and the WordPress tenant/model-space setup are
separate checks. One Clerk user may bind independently in distinct stores.
Within one store, provision_customer uses email as its idempotency key and
reuses the tenant; do not promise that repeating the same email creates a new
site tenant. Automation needs explicit per-site/per-stack tenant mappings.
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

### Site 1 — dedicated FIR production only

These commands require the section 1 gate and a verified FIR_PROD_STACK_DIR.
The prod examples in other runbooks point at generic InsightFace and must not
be substituted here.

```sh
if [ -z "$FIR_PROD_STACK_DIR" ]; then echo "Set FIR_PROD_STACK_DIR only after verifying the dedicated FIR production stack" >&2; exit 1; fi
cd "$FIR_PROD_STACK_DIR"
docker compose -f docker-compose.env.yml exec -T api sh -c 'test "$ACX_ENV" = prod'
docker compose -f docker-compose.env.yml exec -T api python -m scripts.manage_api_keys --env prod tenant create --tenant <site-1-tenant-uuid> --site-url https://demo.altcontext.com
docker compose -f docker-compose.env.yml exec -T api python -m scripts.manage_api_keys --env prod create --tenant <site-1-tenant-uuid> --tier STANDARD
docker compose -f docker-compose.env.yml exec -T api python -m scripts.manage_api_keys --env prod list --tenant <site-1-tenant-uuid>
```

Replace placeholders locally. Run only if read-only verification proved this
directory, API service, image, store and environment match the dedicated FIR
production target. The commands have not been run in this documentation
change.

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
selected replacement. Regression and fix are pending. Do not claim the portal
rotation/recovery sweep passed or substitute CLI create/revoke for portal
rotation. Retest that recovery sequence only after the fix and regression are
available in the serving artifact. Do not invent portal flags, routes or
payloads.

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

For production revocation, use only the already verified FIR_PROD_STACK_DIR
and the same maintained CLI/API service:

```sh
if [ -z "$FIR_PROD_STACK_DIR" ]; then echo "Set FIR_PROD_STACK_DIR only after verifying the dedicated FIR production stack" >&2; exit 1; fi
cd "$FIR_PROD_STACK_DIR"
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

## 5. Enroll one person, then test a different held-out photo

Use private operator-controlled photos that are not committed or included in
screenshots. Upload them through WordPress Media > Add New, then follow the
current Workbench flow; the
maintained UI calls its surfaces Workbench, Review Queue and People. Its scan
action is Analyze selected media. The current review control says Name this
person and Save name. See [Workbench](../../apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx),
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
   the expected named suggestion/recognition and expected description behavior.
   A human accepting or assigning the held-out person's name is not automatic
   recognition evidence. If the held-out photo only creates an unnamed group
   or no expected named suggestion, do not mark recognition passed.
4. Include an independently verified unknown person and a wrong-person
   negative. Confirm that the unknown is not given a known name, the wrong
   identity is not suggested as a correct match, and data from another tenant
   is not visible. Record the resulting scan/job/person IDs and outcomes.

Enrollment/gallery creation and held-out retrieval are separate events. A
health 200, ready response, successful empty scan, empty gallery, or manually
assigned held-out name is not a recognition pass. Do not turn probe auto-enroll
or review acceptance on during quality comparison.

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
production FIR width is unknown until its active profile is authenticated.
Require the authentic active profile/model ID, matching actual columns, and
fresh extraction for the enrollment. Never copy or pad vectors or share an
incompatible gallery. The measured dev-fir database was 128D; recheck the
selected store and active model before use.

Preserve the generic InsightFace and existing firSFace settings and endpoints.
AuraFace remains a separate candidate at these exact planned names:

| DNS name | Planned A record |
| --- | --- |
| auraface.dev.altcontext.com | 129.213.40.111, TTL 300 |
| auraface.api.altcontext.com | 129.213.40.111, TTL 300 |
| auraface.staging.api.altcontext.com | 129.213.40.111, TTL 300 |

Preserve fir.dev.api.altcontext.com, fir.api.altcontext.com,
dev.api.altcontext.com, staging.api.altcontext.com and api.altcontext.com.
Resolution is not service readiness. The supplied inventory found AuraFace
DNS resolution but TLS failure, and found TLS failure for fir.api. Do not route
smoke traffic to an unverified upstream. Do not add a new public InsightFace
evaluation deployment, change model defaults, or declare a model winner.
The earlier verified gte-base-en-v1.5 FIR 512 result and FIR-23 symmetric
stacks from merge 7928fa are prior evidence, not proof of the live FIR
production profile. Use them only if fresh authenticated profile/model
evidence confirms that exact contract.

Functional onboarding and model quality are separate gates. For a quality
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

The following is the supplied native snapshot for 2026-10-11, not a fresh
runtime observation from this documentation change:

- The 09:10 inventory contained dev-fir only; it did not identify a dedicated
  FIR production directory or running container. Generic /opt/acx-backend/prod
  and acx-prod-api-1 are InsightFace.
- fir.api.altcontext.com TLS failed. The three AuraFace names resolved to
  129.213.40.111 but TLS failed; no AuraFace upstream was confirmed.
- Production Clerk TLS failed; the development Clerk sign-in endpoint returned
  200. This does not prove a complete sign-in, invitation or claim sweep.
- LocalWP ports 10010 and 10028 refused connections. Their plugin symlinks
  still named release 0.0.35-066c3aa13 while source declares 0.0.36.
- Root storage was 93% used at 09:18. The native PGDATA admission guard
  requires less than 90% used. Provisioning is not admitted by this snapshot.
- MemoryMax remained 512 MiB. Preserve the native resource limit and holds.
- The Site 2 InsightFace settings disclosure is pending implementation. No
  onboarding keys or end-to-end recognition PASS are evidenced.

Do not claim this runbook or any site runtime PASS from these measurements.
Mark a row PASS only after its stack and source gates pass; effective routing,
profile/model ID and all three actual vector columns agree; correct and
negative key controls behave as expected; the scan/job/person evidence is
complete; and a distinct held-out photo yields the expected automatic
recognition/description behavior without human naming. Keep portal rotation
recovery PENDING until GTMSMOKE-AUTH-01 is fixed and regression-covered.

Keep the durable redacted execution record in an approved private run-specific
location outside Git. Record date/UTC, source and active plugin build identity,
site/store aliases, effective URL, non-secret tenant/key/person/scan/job IDs,
model/profile and vector dimensions, control outcomes, and private receipt
references. The record for this documentation change is: runtime smoke not
run; no onboarding keys issued; no E2E PASS asserted.
