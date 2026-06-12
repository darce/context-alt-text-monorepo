# Demo tenant + API key minting (explicit UUID)

The demo site must use an **explicit** tenant UUID — never URL-derived/JIT identity.
Use `tenant create --tenant <explicit-uuid>` with `--site-url https://demo.altcontext.com`;
do not rely on URL-only minting that derives the UUID from `site_url`.

## Prerequisites

- Demo stack secrets populated at `/opt/acx-backend/demo/secrets/.env`
- Staged rollout: mint against **staging** first, then repeat for prod at launch

## 1. Choose an explicit tenant UUID

Generate once and reuse everywhere (plugin constant, DB row, key binding):

```text
00000000-0000-4000-8000-demo00000001
```

Record it in `secrets/.env` as `ACX_RECOGNITION_TENANT_ID` and embed the same value
inside `WORDPRESS_CONFIG_EXTRA`.

## 2. Create the tenant row (staging first)

On the VM, against the **staging** API stack:

```bash
cd /opt/acx-backend/staging
docker compose -f docker-compose.env.yml exec -T api \
  python -m scripts.manage_api_keys --env staging tenant create \
  --tenant 00000000-0000-4000-8000-demo00000001 \
  --site-url https://demo.altcontext.com
```

Repeat against prod only after the staging walkthrough passes:

```bash
cd /opt/acx-backend/prod
docker compose -f docker-compose.env.yml exec -T api \
  python -m scripts.manage_api_keys --env prod tenant create \
  --tenant 00000000-0000-4000-8000-demo00000001 \
  --site-url https://demo.altcontext.com
```

## 3. Mint the API key

```bash
cd /opt/acx-backend/staging   # or prod after launch cutover
docker compose -f docker-compose.env.yml exec -T api \
  python -m scripts.manage_api_keys --env staging create \
  --tenant 00000000-0000-4000-8000-demo00000001
```

Copy the emitted raw key into `ACX_RECOGNITION_API_KEY` / `WORDPRESS_CONFIG_EXTRA` in
demo secrets only — never commit it.

## 4. CORS allowlist (staging first)

Append the demo origin to `RECOGNITION_ALLOWED_ORIGINS` in the target env's
`secrets/.env` (comma-separated, no trailing slash):

```text
RECOGNITION_ALLOWED_ORIGINS=...,https://demo.altcontext.com
```

Restart that env's stack per `infra/oci/README.md` deploy workflow.

## 5. Pairing proof

After bootstrap:

- Plugin settings show constant-provenance (read-only) URL/key/tenant fields
- `/settings/test` (settings probe) passes against the configured API
- `TenantIdentity::is_auto_derived_identity()` is **false** for the demo tenant

## Launch cutover

When staging walkthrough is green, update demo secrets to:

- `ACX_RECOGNITION_URL=https://api.altcontext.com`
- prod-minted API key + the same explicit tenant UUID

Re-run `bootstrap-wp.sh` only if constants changed materially; otherwise update
`secrets/.env` and `docker compose -f docker-compose.demo.yml up -d wordpress`.
