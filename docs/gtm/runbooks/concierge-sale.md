# Concierge sale runbook (AP-7)

Manual sell-and-provision loop for the first paying customers. **No self-serve signup, no billing webhooks, no dashboard** — those land in AP-1..AP-5. This runbook is the week-1 revenue path.

## Prerequisites

- Recognition stack reachable with the `/admin` minter DB (local, staging, or prod).
- Operator shell in the monorepo with DSN configured for the target env.
- Polar account (operator-manual SaaS UI) — this lane does **not** automate Polar.
- Lead/tracking sheet (Notion/Airtable/`leads`) for post-sale records.

## End-to-end loop

### 1. Create a Polar payment link

In the Polar dashboard, create a **one-time** or **subscription** payment link for the agreed plan/price (typically Pro). Copy the checkout URL.

Do not hardcode product IDs in the repo; treat Polar as operator-owned external config.

### 2. Personalized pitch (Move 1)

Send a soft CTA with the payment link. Positioning: plan §10 Move 1 — private demo or direct offer to the warm tribe (galleries, event orgs, publishers, photographers, membership sites). Goal is paid intent, not a calendar book.

### 3. On Polar payment confirmation → provision

From the monorepo root (against the env that serves the customer):

```bash
# Local/dev (default ENV=local):
make provision-customer EMAIL=customer@example.com PLAN=pro LABEL="Acme Gallery"

# Staging/prod (must match DSN host; use ENV=prod inside the API container):
make provision-customer EMAIL=customer@example.com PLAN=pro LABEL="Acme Gallery" ENV=prod
```

**What the command does**

- Mints a **real** (non-demo) tenant + API key via the existing recognition minter (`mint_api_key` / same store as `manage_api_keys`).
- No demo expiry, no demo quota slug.
- Records `email`, `plan`, and optional `label` (display name) on the tenant row.
- Prints once:
  - `tenant_id`
  - `api_key` (**only on first mint** — copy it now; it is not recoverable)
  - WordPress install snippet (`ACX_RECOGNITION_URL`, `ACX_RECOGNITION_API_KEY`, `ACX_RECOGNITION_TENANT_ID`, `ACX_RECOGNITION_SOURCE`)

**Idempotency:** re-running with the same `EMAIL` reports `status=existing` and does **not** mint a second tenant or key. The raw key is **not** re-printed.

**Secrets:** the raw key is never written to a persisted log or sidecar file by this command. Do not paste it into tickets or commit it.

### 4. Email key + install steps

Manually email the customer:

1. The WordPress install snippet from the command output.
2. Plugin install/activate notes (see plugin packaging docs).
3. Support contact.

Automated Resend delivery is **AP-6** — not this lane.

### 5. Record the lead

In the tracking sheet / `leads` surface, record:

| Field | Value |
| --- | --- |
| Email | same as `EMAIL` |
| Label / org | `LABEL` |
| Plan | `PLAN` |
| Tenant id | printed `tenant_id` |
| Polar payment | link/id + paid date |
| Key status | minted (never store the raw key) |

## Plan values

| `PLAN` | Key rate-limit tier |
| --- | --- |
| `free` | `STANDARD` |
| `pro` (default) | `PRO` |
| `enterprise` | `ENTERPRISE` |

Plan *enforcement* beyond tier is out of scope (AP-3..AP-5). Concierge operators honor commercial terms manually.

## API URL in the snippet

Override the printed recognition base URL with:

```bash
export ACX_RECOGNITION_URL=https://api.altcontext.com   # or staging URL
make provision-customer EMAIL=...
```

Default when unset: `https://api.altcontext.com`.

## Failure modes

| Symptom | Check |
| --- | --- |
| `make: *** No rule to make target 'provision-customer'` | Pull latest `feature/ap-7` / main after merge |
| `error: env=local but DSN host ... is not a local host` | Wrong `--env` for the DSN; use `ENV=prod` against remote |
| `error: invalid email` | Pass a normal `user@domain` address |
| `status=existing` but customer lost the key | Mint a **new** key with `python -m scripts.manage_api_keys --env … create --tenant <uuid> --tier PRO` (does not delete the old key; revoke the old one if rotating) |

## Out of scope (do not invent here)

- Clerk signup, business DB, customer dashboard
- Automated Polar webhooks → plan flips
- Parallel key stores or plaintext key archives (`[ARCH-02]`)

## Related

- Offload brief: [`docs/gtm/offload-brief-ap7-concierge.md`](../offload-brief-ap7-concierge.md)
- Launch plan: [`docs/gtm/altcontext-productization-launch-plan.md`](../altcontext-productization-launch-plan.md) §5 / §10 Move 1 / §14 AP-7
- Minter CLI: `apps/prototype-description-service/scripts/manage_api_keys.py`
- Customer fields ADR: [`docs/adrs/ADR-012-customer-tenant-management-crm-ready-admin.md`](../../adrs/ADR-012-customer-tenant-management-crm-ready-admin.md)
