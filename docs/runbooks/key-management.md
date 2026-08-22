# Runbook: API key & tenant management — the three tracks

> **Canonical entry point for all tenant/key work.** Every other doc that
> mentions minting keys (`admin-tenant-keys.md`, the LocalWP development
> runbook, the description-service README, the demo tenant-mint runbook)
> defers to the track definitions here.

## The one rule that prevents every mistake in this domain

**A console or CLI mints keys into the database of the environment it runs
in — nothing else.** The local `/admin` console writes your laptop's
Postgres. The prod `/admin` console (or a CLI exec'd inside the prod
container) writes the prod identity DB. There is no cross-environment
minting: a key minted locally will never authenticate against
`api.altcontext.com`, and vice versa.

If a key is being rejected, the first question is always: *which DB was this
key minted in, and which service is the client actually calling?*

## Which track am I on?

| Question | Track 1 — Hosted service (product path) | Track 2 — Local fast loop (dev path) |
| --- | --- | --- |
| What the plugin calls | `https://api.altcontext.com` (or staging/dev vhosts) | `http://localhost:8000` (local description-service) |
| Who uses it | Real sites, demo, **and any LocalWP install exercising the product path** | Developers iterating on recognition-service code |
| Where tenants/keys live | **Prod identity DB on the OCI VM** | Laptop-local Postgres (throwaway fixtures) |
| How to mint | **`make admin-oci-mint TENANT=<uuid>`** (automated, recommended for scratch/eval/LocalWP), the prod `/admin` console over the tailnet, `make provision-customer EMAIL=<e> ENV=prod` (real customers), or `manage_api_keys --env prod` exec'd in the prod container | `make dev-setup` / `make dev-mint-key`, or the local `admin-dev` console |
| How the plugin selects it | Default — `recognition_source` resolves to `service`; no config needed | **Dev hatch only**: `ACX_RECOGNITION_SOURCE=local` constant/filter (RECOG-1 removed the product toggle) |
| Key install in the plugin | wp-admin **Settings page** (user way, stored as options) or `wp-config.local.php` constants (gate/reproducible way) | Local fixture key via the same two mechanisms |
| Product surface? | Yes | **Never.** Dev convenience only; retirement deferred, kept as a fast iteration loop ([tech-debt entry](../tasks/tech-debt/local-vs-oci-description-service-drift-and-retirement.md)) |

Per-prospect demo instances are Track 3 below. They are deliberately not
scratch Track 1 keys: a demo is a TTL-bound credential bundle with a human
WordPress login and one lifecycle command.

RECOG-1 context: the hosted service is the canonical recognition target. The
local backend was retired from the *product surface* (no Settings toggle) but
deliberately **kept** as a developer fast loop behind the code hatch. Both
tracks are legitimate; they just never share credentials.

---

## Track 1 — Mint a hosted-service key (incl. LocalWP → remote)

A LocalWP install pointing at `api.altcontext.com` is a Track 1 client. Its
tenant and key live in **prod**, so minting happens on the prod console/CLI —
never the local one.

### Tenant UUID discipline

- Mint each WordPress instance its **own fresh UUID** (`uuidgen`).
- **Never reuse `00000000-0000-4000-8000-000000000001` on prod.** That UUID is
  taken twice over: it is the demo site's tenant on prod
  (`demo.altcontext.com`, see the [demo tenant-mint
  runbook](../../infra/oci/demo/tenant-mint-runbook.md)) *and* the default
  local-fixture UUID that `make dev-mint-key` uses in laptop DBs. Reusing it
  for anything else guarantees a collision or a very confusing debugging
  session.

### Fastest: `make admin-oci-mint` (automated, no secret to the laptop)

For a scratch/eval or LocalWP tenant, one command mints the key with no manual tunnel or
token copy:

```sh
cd apps/prototype-description-service
make admin-oci-mint TENANT=<uuid> [SITE_URL=<url>]   # SITE_URL defaults to http://localhost:10018
```

It SSHes to the prod VM and runs the canonical `manage_api_keys --env prod` CLI **inside the
prod `api` container**, so the container's own DB creds do the write — the `/admin` HTTP
route and its `RECOGNITION_ADMIN_TOKEN` are never involved, and no prod secret reaches the
laptop (only the freshly-minted key comes back, printed once). `TENANT`/`SITE_URL` are routed
through the environment and validated (UUID / URL charset) before use, so a pasted value
cannot inject a command over the ssh hop [WEB-02/WEB-16/SEC-01]. It ensures the tenant
(idempotent `tenant create`) then mints the key; paste the printed `api_key=` into the plugin
**Settings**. Host/user override via `OCI_HOST`/`OCI_USER` (default
`acx-backend.tail1a44b8.ts.net` / `ubuntu`). Use the manual `/admin` console below when you
need to browse/list/revoke keys, and `make provision-customer` for a real customer tenant.

### Steps (prod `/admin` console — canonical)

1. Tunnel in (the api container binds loopback-only on the VM):

   ```sh
   ssh -L 8001:127.0.0.1:8000 ubuntu@acx-backend.tail1a44b8.ts.net
   ```

2. Browse `http://localhost:8001/admin/` (trailing slash). Basic auth:
   username anything, password = the **prod** `RECOGNITION_ADMIN_TOKEN` from
   `/opt/acx-backend/prod/secrets/.env` on the VM. (The token in your laptop's
   `apps/prototype-description-service/.env` is the *local* console's token —
   it will be rejected here, by design.)
3. Create the tenant: fresh UUID + the site URL (e.g. `http://localhost:10010`
   for a LocalWP install).
4. Mint the key. **It is shown exactly once** (hash-only storage) — copy it
   immediately.
5. Install it in the plugin (choose one):
   - **Settings page** (user-style, recommended for dev installs): paste the
     service URL and key into wp-admin → Alt Context Settings. Sources report
     `option`. Requires that no `ACX_RECOGNITION_URL` /
     `ACX_RECOGNITION_API_KEY` constants are defined — **constants always
     override options**, and the Settings fields become read-only reporting
     `constant`.
   - **`wp-config.local.php` constants** (gate/release verification): the
     reproducible path documented in the [LocalWP development
     runbook](../../apps/prototype-wp-alt-context/docs/localwp-development-runbook.md#gate-secrets-site-local-config).
6. Verify with the Settings page **Test Connection** button, which probes the
   hosted service with the effective credentials.

CLI fallbacks (run **on the VM**, inside the prod stack): `make
provision-customer EMAIL=<e> ENV=prod` (real customers; idempotent on email,
prints the WP snippet) or `docker compose -f docker-compose.env.yml exec -T api
python -m scripts.manage_api_keys --env prod ...` (see
[admin-tenant-keys.md](admin-tenant-keys.md) for the full ceremony and
[tenant-mint-runbook.md](../../infra/oci/demo/tenant-mint-runbook.md) for the
demo's staged variant).

### Key lifecycle

Rotate/revoke through the same prod console (revoke button; idempotent) or
`manage_api_keys --env prod revoke --key-id <uuid>`. Every create/mint/revoke
writes an `audit_events` row. Prod resets orphan **all** previously minted
keys — after any prod DB reset, expect every Track 1 client (including LocalWP
installs) to need a fresh tenant + key.

---

## Track 2 — Local fast loop (fixtures only)

For iterating on description-service code without touching OCI:

1. `cd apps/prototype-description-service && make dev-setup` (first time) or
   `make dev-mint-key` — bootstraps the local fixture tenant
   (`…0001`, fine *locally*) and prints a fixture key.
   The local `admin-dev` console (`make admin-dev`) is the browser equivalent.
2. Run the service: `make serve` (binds `:8000`).
3. Point the plugin at it via the **dev hatch** in the LocalWP site's
   `wp-config.local.php`:

   ```php
   define('ACX_RECOGNITION_SOURCE', 'local');
   define('ACX_RECOGNITION_LOCAL_URL', 'http://localhost:8000');
   ```

   Remove the defines to fall back to the hosted service. There is no
   Settings toggle for this — that is intentional (RECOG-1).

Everything minted on this track is a **throwaway fixture**: it works only
against the laptop service/DB, is destroyed by `make reset-local`, and must
never be pasted into a plugin install that targets the hosted service.

---

## Track 3 — Demo instances

A demo instance bundles four values under one slug and TTL:

- a fresh tenant UUID, which remains the service's isolation boundary;
- a one-time API key scoped to that tenant and its compute quota;
- a distinct `demo-<slug>` WordPress login with a generated password; and
- a named seed bundle (`default` or `acme`) whose required initial state is
  seeded media present, zero scanned faces, and `people_count == 0`.

The default TTL is 30 days and the default compute quota is 200 units. A
WordPress capability controls what the person can click; it never replaces the
tenant/API-key boundary. The current plugin gates all six admin pages on
`manage_options`, so the generated account must temporarily use the WordPress
administrator role. Do not substitute the CI end-to-end account
(`ACX_E2E_WP_ADMIN_*`) and do not hand that CI identity to a viewer. Moving the
viewer to an `acx_demo_reviewer` role requires changing all menu and route gates
to the intended `acx_operate` capability in the plugin first.

### Provision

Run from the description-service directory:

```sh
make demo-provision LABEL="Acme Gallery" SEED=default
```

`SEED` defaults to `default` when omitted.

The target validates the label and bundle name before the SSH hop, connects to
the prod VM, verifies the WordPress bundle is genuinely pre-scan, runs the
canonical provisioning CLI inside the prod `api` container, and creates the
per-slug account through `wp-cli` inside the demo container. Prod database and
WordPress secrets stay on the VM. The demo URL, API key, WordPress username,
and WordPress password are printed once after both sides succeed.

Provisioning fails before handing out credentials if seeded media is absent,
if scanned faces remain, or if `people_count` is non-zero. This is the same
`SeedBundleContract` enforced by the service and intended for reset tooling;
the state is a release contract, not a convention.

### Expire, rotate, and sweep

```sh
make demo-expire SLUG=<slug> CONFIRM=<same-slug>
make demo-sweep
```

`demo-expire` is the single revoke: it removes the `demo-<slug>` WordPress
principal, marks the demo registry row revoked, and sets the underlying API
key's `revoked_at`. The exact `CONFIRM` value is the deliberate-action gate;
the SSH connection authenticates the critical mutation at the prod boundary.
Removing only the demo registry row is not a revoke because service auth checks
`api_keys.revoked_at`; revoking only the API key is also incomplete because
WordPress authenticates the human independently.

`demo-sweep` applies that same complete lifecycle to every expired instance.
It disables all eligible WordPress users before the canonical sweep commits
the registry and API-key revocations. A failure stops loudly for retry instead
of declaring a still-usable login expired.

Rotation is intentionally composition, not a second mechanism: expire the old
slug with `demo-expire`, then mint a new bundle with `demo-provision`. This
produces a new tenant, API key, slug-derived WordPress identity, and password;
changing `WP_ADMIN_PASSWORD` after WordPress installation does nothing and is
not a rotation path.

---

## Failure signature quick reference

| Symptom | Likely cause |
| --- | --- |
| Prod `/admin` Basic auth rejects your token | You supplied the **local** `.env` token to the **prod** console (tunnel `:8001`). Fetch the prod token from `/opt/acx-backend/prod/secrets/.env` on the VM. |
| Settings "API key rejected", whoami 401/403 | Key minted in a different environment's DB than the service being called — or orphaned by a prod DB reset. Re-mint on the correct track. |
| Pasting a key in Settings has no effect | `ACX_RECOGNITION_API_KEY` (or `_URL`) constant is defined; constants override options. Clear the defines or manage via constants consistently. |
| Local console mints fine but remote calls still 403 | Working as designed — local mints are Track 2 fixtures; the remote service has never heard of them. Mint on Track 1. |
| `tenant create` 409 on prod for `…0001` | That UUID belongs to the demo site on prod. Generate a fresh UUID for your instance. |
| Demo provisioning says the bundle is not pre-scan | The shared WordPress demo still has face/member/person projection state. Run the version-controlled reset path, verify faces and `people_count` are zero, then provision again; never override the guard. |
| Demo API calls fail but the WP login still works | The lifecycle was only partially revoked. Re-run `make demo-expire SLUG=<slug> CONFIRM=<slug>`; do not treat the registry flag alone as expiry. |
