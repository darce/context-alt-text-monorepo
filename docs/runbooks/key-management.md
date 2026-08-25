# Runbook: API key & tenant management — the two tracks

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

## Demo WordPress admin rotation (AUTH-01)

The demo wp-admin password in `/opt/acx-backend/demo/secrets/.env`
(`WP_ADMIN_PASSWORD`, chmod 600) is the source of truth on **every**
`bootstrap-wp.sh` run, not only the first `wp core install`. Changing the
secret and re-running bootstrap (or dispatching `deploy-demo`) is how you
revoke the previous password. A silent no-op after a secret change is a
failed rotation.

Two independent keys (store write ≠ apply):

1. **Key 1 — secret store.** On an authorized operator machine, generate a
   new password. Never commit it (WEB-16). Patch `WP_ADMIN_PASSWORD` in
   `secrets/.env` on the VM (mode 600). Do not paste the value into chat,
   tickets, or a prompt template (SEC-06).
2. **Key 2 — apply.** Re-run `bootstrap-wp.sh` on the VM, or dispatch the
   demo deploy workflow so bootstrap runs. Bootstrap calls
   `wp user check-password`; matching secret is a no-op. On mismatch it
   runs `wp user update --user_pass=...` and re-checks. Update or verify
   failure exits 2 with `ERROR: failed to rotate WordPress credential`
   (or the did-not-converge variant). Do not treat a green deploy as
   rotation proof unless that apply step ran.

Do **not** reuse the rotated admin password as the CI smoke login. CI is a
separate identity (AUTH-03).

---

## Demo credential issuance (AUTH-03)

Three identities. Compromising one must not yield the others
(least-privilege-blast-radius). High-impact rotation still takes two keys
(secret-store write, then apply — dual-control-two-keys).

| Identity | Where it lives | Who uses it | Privilege |
| --- | --- | --- | --- |
| Demo wp-admin / viewer | `WP_ADMIN_*` in `/opt/acx-backend/demo/secrets/.env` | Human operator | WordPress administrator |
| Demo CI WP user | `WP_CI_*` in the same secrets file; GitHub Environment secrets `ACX_E2E_WP_CI_USER` / `ACX_E2E_WP_CI_PASS` | `deploy-demo.yml` smoke only | Custom role `acx_ci` (subscriber clone + `manage_options` + `upload_files`) |
| Prospect / CI API key | description-service identity DB | Plugin → hosted service | Viewer quota 200; CI quota 20 |

Never commit these values (WEB-16). Never put them in a prompt template or
RAG store (SEC-06).

### WordPress CI account

`bootstrap-wp.sh` creates/converges `WP_CI_USER` on every run. It must differ
from `WP_ADMIN_USER`. GitHub Actions maps `ACX_E2E_WP_CI_*` onto Playwright's
`ACX_E2E_WP_ADMIN_*` env names (harness unchanged). `ACX_E2E_WP_CI_USER` **must
equal** the VM `WP_CI_USER` — the denylist (`acx-demo-admin` / `admin`,
case-insensitive) is a safety net, not the identity contract. Empty
`ACX_E2E_WP_CI_PASS` is refused. Rotate `WP_CI_PASSWORD` the same two-key way as
admin (patch secrets/.env, then bootstrap/deploy). Do not copy the admin
password into `ACX_E2E_WP_CI_PASS`.

### API keys

Prospect viewer (existing DS-3 path):

```sh
make provision-demo LABEL="Acme Gallery" SEED=default
```

CI-scoped key (reduced recognition quota; label must differ from the demo
wp-admin username):

```sh
make issue-demo-ci-account LABEL="ACX CI" ADMIN_USER=acx-demo-admin
```

Both print `api_key=` once on stdout and never store the raw key. `ENV`
selects the DB (`local` default; `prod` for hosted).

---

## Failure signature quick reference

| Symptom | Likely cause |
| --- | --- |
| Prod `/admin` Basic auth rejects your token | You supplied the **local** `.env` token to the **prod** console (tunnel `:8001`). Fetch the prod token from `/opt/acx-backend/prod/secrets/.env` on the VM. |
| Settings "API key rejected", whoami 401/403 | Key minted in a different environment's DB than the service being called — or orphaned by a prod DB reset. Re-mint on the correct track. |
| Pasting a key in Settings has no effect | `ACX_RECOGNITION_API_KEY` (or `_URL`) constant is defined; constants override options. Clear the defines or manage via constants consistently. |
| Local console mints fine but remote calls still 403 | Working as designed — local mints are Track 2 fixtures; the remote service has never heard of them. Mint on Track 1. |
| `tenant create` 409 on prod for `…0001` | That UUID belongs to the demo site on prod. Generate a fresh UUID for your instance. |
| Bootstrap `ERROR: failed to rotate WordPress credential` | `wp user update` failed after `WP_ADMIN_PASSWORD` changed. Check wp-cli/DB reachability; do not revert the secret to "make bootstrap green" — that re-issues the revoked password. |
| Changed `WP_ADMIN_PASSWORD` but old login still works | Apply step (key 2) did not run, or bootstrap is an old copy without AUTH-01 converge. Re-run current `bootstrap-wp.sh`. |
