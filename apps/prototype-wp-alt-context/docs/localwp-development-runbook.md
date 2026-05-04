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

### What Not To Use For The Gate

Do not store the production-scoped LocalWP gate key in:

- `apps/prototype-wp-alt-context/.env.local`
- a symlinked plugin checkout
- a committed file in this repo

WordPress options are acceptable as a temporary emergency override, but they are
not the durable source of truth for `E15-3a`.

## Rotate / Verify / Revoke

The backend key lifecycle CLI is:

```bash
cd apps/prototype-description-service
python -m scripts.manage_api_keys create --tenant <tenant-uuid>
python -m scripts.manage_api_keys revoke --key-id <key-uuid>
```

The `create` command prints the raw key to stdout once and the `key_id` to
stderr. Treat stdout as secret material and do not paste it into repo files or
the run log.

### 1. Create A Fresh Gate Key

First, ask the LocalWP helper for the canonical tenant UUID used by the plugin:

```bash
cd /Users/daniel/Development/context-alt-text-monorepo-e15-3a
bash scripts/localwp-gate-status.sh --wp-path "$HOME/Development/wp-context-alt-text/app/public"
```

Copy `tenant_uuid` from that JSON and use it in the create command. This avoids
hand-deriving the UUID and guarantees the CLI key is issued for the same tenant
identity the plugin sends in `X-Tenant-ID`.

From the monorepo:

```bash
cd /Users/daniel/Development/context-alt-text-monorepo-e15-3a/apps/prototype-description-service
python -m scripts.manage_api_keys create --tenant <tenant-uuid>
```

Capture:

- raw key from stdout
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
old key:

```bash
cd /Users/daniel/Development/context-alt-text-monorepo-e15-3a/apps/prototype-description-service
python -m scripts.manage_api_keys revoke --key-id <old-key-uuid>
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
