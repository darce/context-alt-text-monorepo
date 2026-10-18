# Alt Context LocalWP Development Runbook

This runbook separates two workflows that were previously easy to blur
together:

1. **Active development in LocalWP** — use a symlink, but only from a stable,
   non-ephemeral checkout.
2. **Release/gate verification** — use the packaged ZIP artifact so the tested
   plugin build is explicit and reproducible.

The guardrail exists because task worktrees are temporary by design. A LocalWP
plugin symlink that points at `context-alt-text-monorepo-<task>` can disappear
as soon as the task is archived or the worktree is pruned.

For this repo's LocalWP install, the canonical site/admin base is:

- Site URL: `http://localhost:10010/`
- Admin URL: `http://localhost:10010/wp-admin/`
- Workbench route: `http://localhost:10010/wp-admin/admin.php?page=alt-context-workbench`

Do not confuse LocalWP (`:10010`) with the local description-service dev backend (`http://localhost:8000` from `apps/prototype-description-service`). Browser proof and Workbench scans always use `:10010`.

`wp-context-alt-text.local` was never the correct address for this setup.

## Recommended Layout

Keep one stable checkout dedicated to LocalWP plugin iteration. Example:

```text
~/Development/context-alt-text-monorepo-localwp/
```

Inside that checkout, the plugin source path is:

```text
~/Development/context-alt-text-monorepo-localwp/apps/prototype-wp-alt-context
```

Do **not** point LocalWP directly at a task worktree such as:

```text
~/Development/context-alt-text-monorepo-e15-3a/apps/prototype-wp-alt-context
```

## Active Development: Stable Symlink Install

Use the guarded helper from the plugin app directory:

```bash
cd apps/prototype-wp-alt-context
make localwp-link \
  WP_PATH="$HOME/Development/wp-context-alt-text/app/public" \
  PLUGIN_SOURCE="$HOME/Development/context-alt-text-monorepo-localwp/apps/prototype-wp-alt-context"
```

What it does:

- creates or refreshes `wp-content/plugins/alt-context`
- refuses linked git worktree sources by default
- refuses to overwrite an existing target unless `OVERWRITE=1` is passed
- moves the prior target aside to a timestamped backup before replacing it

Helpful variants:

```bash
# Preview only
make localwp-link \
  WP_PATH="$HOME/Development/wp-context-alt-text/app/public" \
  PLUGIN_SOURCE="$HOME/Development/context-alt-text-monorepo-localwp/apps/prototype-wp-alt-context" \
  DRY_RUN=1

# Replace an existing plugin dir/symlink
make localwp-link \
  WP_PATH="$HOME/Development/wp-context-alt-text/app/public" \
  PLUGIN_SOURCE="$HOME/Development/context-alt-text-monorepo-localwp/apps/prototype-wp-alt-context" \
  OVERWRITE=1
```

If you intentionally want to point LocalWP at a linked worktree, the helper
forces an explicit opt-in:

```bash
make localwp-link \
  WP_PATH="$HOME/Development/wp-context-alt-text/app/public" \
  PLUGIN_SOURCE="/path/to/some/worktree/apps/prototype-wp-alt-context" \
  ALLOW_WORKTREE_SOURCE=1
```

That opt-in is for exceptional debugging only, not the normal workflow.

## Gate / Evidence Workflow: Packaged ZIP

For `E15-3a` and any other reproducible verification pass, use the packaged
artifact instead of a symlinked plugin install:

```bash
cd apps/prototype-wp-alt-context
make gate-package
```

This produces:

- `dist/alt-context-<version>.zip`
- `dist/alt-context-<version>.zip.sha256`

Then install it in WordPress admin:

1. Plugins -> Add New Plugin -> Upload Plugin
2. Upload `dist/alt-context-<version>.zip`
3. Activate `Alt Context`

Use the ZIP path for:

- `E15-3a` LocalWP -> OCI gate evidence
- release candidates
- rollbackable manual smoke runs
- any case where you need to know exactly what artifact was tested

## Recognition Credentials: Two Ways To Manage, One Place To Mint

> **Canonical key/tenant guidance:**
> [docs/runbooks/key-management.md](../../../docs/runbooks/key-management.md).
> A LocalWP install pointing at `https://api.altcontext.com` is a **Track 1**
> client: its tenant + key are minted on the **prod** `/admin` console (or the
> VM-side CLI) — never on the local `admin-dev` console, whose keys are
> laptop-only fixtures.

The plugin accepts credentials from two tiers, and **constants always beat
options**:

1. **Settings page (user-style)** — paste the service URL and API key into
   wp-admin → Alt Context Settings; stored as WP options, sources report
   `option`. This only works while no `ACX_RECOGNITION_URL` /
   `ACX_RECOGNITION_API_KEY` constants are defined — if they are, the Settings
   fields are overridden and report `constant`.
2. **`wp-config.local.php` constants (gate-style)** — the reproducible path
   below, preferred for release/gate verification because the credential
   survives plugin reinstalls and stays out of the DB.

Pick one tier per install and stay on it; a half-and-half config (URL from a
constant, key from an option) is legal but confusing to debug.

## Gate Secrets: Site-Local Config

For `E15-3a`, keep the production-scoped LocalWP gate key out of:

- the plugin checkout
- plugin `.env` / `.env.local`
- the committed repo
- ad hoc Settings-page pastes as the long-term source of truth

Use a LocalWP site-local config include instead. The goal is simple:

- the tested plugin artifact is the ZIP
- the secret lives with the LocalWP site, not with the plugin source tree
- reinstalling the plugin does not lose the gate configuration

### Minimal `wp-config.local.php` Pattern

Create an untracked file next to the LocalWP site's `wp-config.php`:

```php
<?php
declare(strict_types=1);

define('ACX_RECOGNITION_URL', 'https://api.altcontext.com');
define('ACX_RECOGNITION_API_KEY', '<raw production key>');
```

> **The `<?php` opening tag is load-bearing.** A tag-less file passes
> `php -l` (it lints as plain text) but `require` will echo its contents as
> raw output instead of executing the `define()`s — the constants silently
> never exist and the text leaks into the page before headers. If Settings
> reports `url_source=default` despite this file existing, check the tag
> first.

Then load it from `wp-config.php` using a defensive include:

```php
$acx_local_config = __DIR__ . '/wp-config.local.php';
if (file_exists($acx_local_config)) {
	require_once $acx_local_config;
}
```

Recommended placement:

- add the include above the `/* That's all, stop editing! Happy publishing. */` line
- keep `wp-config.local.php` untracked and operator-managed
- set both URL and key together so the gate uses one immutable config surface

Why this pattern:

- the plugin resolves constants before WordPress options
- the ZIP-installed plugin no longer depends on source-checkout `.env.local`
- the Settings screen will truthfully report `url_source=constant` and `key_source=constant`

### Dev Recognition Hatch: Opt Back Into The Local Backend

Hosted **service** is the canonical recognition target and the default. `local`
is retired from the product surface — there is no Settings toggle. A developer
who needs to point the plugin at a local description-service backend
(`http://localhost:8000` from `apps/prototype-description-service`) opts in via a
**dev-only code hatch** in `wp-config.local.php` (next to the LocalWP site's
`wp-config.php`, untracked):

```php
<?php
declare(strict_types=1);

// Dev-only hatch: force the retired local recognition backend. Never a
// product/Settings feature — remove these defines to return to hosted service.
define('ACX_RECOGNITION_SOURCE', 'local');
define('ACX_RECOGNITION_LOCAL_URL', 'http://localhost:8000');
```

Load it from `wp-config.php` with the same defensive include shown above. The
plugin resolves the `ACX_RECOGNITION_SOURCE` constant (or the
`acx_recognition_source` filter) before any option, so this flips the effective
target to the local URL chain. Remove the defines to fall back to the default
hosted service. This is strictly a local developer convenience — never ship it
or expose it as a Settings option.

The local backend needs its own **local fixture** key (`make dev-mint-key` /
`make dev-setup` in `apps/prototype-description-service`) — hosted-service
keys do not work against it, and its fixture keys do not work against the
hosted service. This is Track 2 in
[key-management.md](../../../docs/runbooks/key-management.md#track-2--local-fast-loop-fixtures-only);
the assessment that kept the local service alive as a fast dev loop is
[recorded in the tech-debt registry](../../../docs/tasks/tech-debt/local-vs-oci-description-service-drift-and-retirement.md).

### What Not To Use For The Gate

Do not store the production-scoped LocalWP gate key in:

- `apps/prototype-wp-alt-context/.env.local`
- a symlinked plugin checkout
- a committed file in this repo

WordPress options are acceptable as a temporary emergency override, but they are
not the durable source of truth for `E15-3a`.

## Rotate / Verify / Revoke

Keys for a LocalWP install that targets `https://api.altcontext.com` live in
the **prod identity DB** and are minted/revoked there — canonically via the
prod `/admin` console over the tailnet, with the VM-side CLI as fallback. Full
flow, tunnel command, and token location:
[key-management.md § Track 1](../../../docs/runbooks/key-management.md#track-1--mint-a-hosted-service-key-incl-localwp--remote).

Running `python -m scripts.manage_api_keys` from the laptop **cannot** mint
Track 1 keys: `--env` is mandatory, `--env prod` refuses local DSNs, and the
prod Postgres is only reachable inside the VM's docker network. The local
CLI/console mints laptop-only fixtures (Track 2).

> **Prod DB resets orphan every existing key.** If the plugin suddenly gets
> 401/403 with a key that used to work, re-mint before debugging anything
> else.

### 1. Create A Fresh Gate Key

First, ask the LocalWP helper which tenant UUID the plugin currently pairs
with (repo root):

```bash
bash scripts/localwp-gate-status.sh --wp-path "$HOME/Development/wp-context-alt-text/app/public"
```

If this install has no tenant yet on prod, generate a **fresh** UUID
(`uuidgen`) — never reuse `00000000-0000-4000-8000-000000000001`, which is the
demo site's prod tenant *and* the local-fixture default (see
[key-management.md § Tenant UUID discipline](../../../docs/runbooks/key-management.md#tenant-uuid-discipline)).

Mint on the prod `/admin` console (create tenant → mint key), or via the
VM-side CLI:

```bash
ssh ubuntu@acx-backend.tail1a44b8.ts.net
cd /opt/acx-backend/prod
docker compose -f docker-compose.env.yml exec -T api \
  python -m scripts.manage_api_keys --env prod tenant create \
  --tenant <fresh-uuid> --site-url http://localhost:10010
docker compose -f docker-compose.env.yml exec -T api \
  python -m scripts.manage_api_keys --env prod create --tenant <fresh-uuid>
```

Capture:

- raw key from stdout (shown exactly once)
- `key_id=...` from stderr

Immediately compute a fingerprint for the run log:

```bash
printf '%s' '<raw key>' | shasum -a 256 | awk '{print substr($1,1,12)}'
```

Record only that 12-char fingerprint in `E15-3a-localwp-oci-run-log.md`.

### 2. Install The Key In `wp-config.local.php`

Update the LocalWP site-local file:

```php
<?php
declare(strict_types=1);

define('ACX_RECOGNITION_URL', 'https://api.altcontext.com');
define('ACX_RECOGNITION_API_KEY', '<raw production key>');
```

If the key already exists there, replace it in place. Do not keep multiple
historical keys in the file.

### 3. Verify The Plugin Is Reading Constants

From the `E15-3a` worktree:

```bash
bash scripts/localwp-gate-status.sh \
  --wp-path="$HOME/Development/wp-context-alt-text/app/public"
```

Quick-check expectations from that JSON:

- `plugin.status` is `Active`
- `settings.url_source` is `constant`
- `settings.key_source` is `constant`
- `effective_key.fingerprint` matches the fingerprint recorded in the run log

If you need the raw REST payloads separately, the lower-level checks are:

```bash
bash scripts/localwp-wp.sh \
  --path="$HOME/Development/wp-context-alt-text/app/public" \
  eval 'wp_set_current_user(1); $request = new WP_REST_Request("GET", "/acx/v1/settings"); $response = rest_do_request($request); echo wp_json_encode($response->get_data(), JSON_PRETTY_PRINT);'
```

Expected shape:

```json
{
  "url": "https://api.altcontext.com",
  "url_source": "constant",
  "api_key_set": true,
  "key_source": "constant"
}
```

### 4. Verify `/settings/test`

Run the authenticated probe:

```bash
bash scripts/localwp-gate-status.sh \
  --wp-path="$HOME/Development/wp-context-alt-text/app/public"
```

The same helper prints the current `/settings/test` payload under `probe`.

For the direct probe call only:

```bash
bash scripts/localwp-wp.sh \
  --path="$HOME/Development/wp-context-alt-text/app/public" \
  eval 'wp_set_current_user(1); $request = new WP_REST_Request("POST", "/acx/v1/settings/test"); $response = rest_do_request($request); echo wp_json_encode($response->get_data(), JSON_PRETTY_PRINT);'
```

Expected result for Slice 1:

- `outcome: "connected"`
- backend-side correlation evidence captured separately from OCI stdout

If the probe returns `invalid_key`, `expired`, `revoked`, or
`invalid authorization scheme`, stop and rotate again rather than falling back
to plugin options.

### 5. Revoke The Previous Key

Once the new key is verified and the run log fingerprint is updated, revoke the
old key — on the prod `/admin` console (revoke button, idempotent) or the
VM-side CLI:

```bash
ssh ubuntu@acx-backend.tail1a44b8.ts.net
cd /opt/acx-backend/prod
docker compose -f docker-compose.env.yml exec -T api \
  python -m scripts.manage_api_keys --env prod revoke --key-id <old-key-uuid>
```

Record in the run log:

- revoked key id
- revocation timestamp
- newly active fingerprint

### 6. Re-Verify After Revocation

Repeat the two LocalWP checks:

```bash
bash scripts/localwp-wp.sh --path="$HOME/Development/wp-context-alt-text/app/public" option get siteurl

bash scripts/localwp-wp.sh \
  --path="$HOME/Development/wp-context-alt-text/app/public" \
  eval 'wp_set_current_user(1); $request = new WP_REST_Request("POST", "/acx/v1/settings/test"); $response = rest_do_request($request); echo wp_json_encode($response->get_data(), JSON_PRETTY_PRINT);'
```

This confirms the LocalWP site is using the intended current key and did not
silently fall back to a stale option or source-tree override.

## Why The Split Matters

The WordPress literature in
[`literature/extracted/wp/wp-plugin-literature-digest.md`](/Users/daniel/Development/context-alt-text-monorepo/literature/extracted/wp/wp-plugin-literature-digest.md)
supports both halves of this setup:

- LocalWP symlinks are a useful development convenience.
- Production-grade plugins should bundle assets inside the plugin directory and
  ship as explicit release artifacts.

That means:

- **Symlink** for fast local iteration.
- **ZIP** for stable verification and release-like workflows.

## Quick Policy

- Never use a task worktree symlink as the only LocalWP install path.
- Never use a symlinked plugin install as the canonical `E15-3a` gate artifact.
- If a LocalWP site matters beyond one branch session, make its plugin source
  path stable first.
- For `E15-3a`, keep the production-scoped key in `wp-config.local.php`, not in
  the plugin checkout.
