# Offload Brief — AP-7: Concierge Sell-and-Provision Fast-Path

> **Purpose:** the *first* offload lane. Ships in week 1, unblocks revenue, and **does not depend on AP-1/AP-2** — it wraps the *existing* recognition `/admin` minter (`manage_api_keys`), the same path the demo uses. Plan enforcement is manual (concierge), so no billing stack is required.
> **Backend:** `grok-cli` · **Effort:** high · **Token budget:** set per your governor (suggest a bounded single-pass cap).
> **Task branch:** create via branch-lifecycle first (see the parent message for commands); offload runs inside that feature-branch worktree.

---

## Objective (end-state contract)

Give the operator a one-command way to convert a paying concierge customer into a live, authenticated tenant, plus a runbook for the surrounding manual sale.

**Deliverables:**
1. **`make provision-customer EMAIL=<e> [PLAN=pro] [LABEL="<name>"]`** — mints a **real** (non-demo) tenant + API key via the existing `/admin` `manage_api_keys` mechanism (no demo expiry/quota; labeled as a customer), and prints: the API key **once**, the tenant id, and a copy-paste WP install snippet (API URL + key). Idempotent on `EMAIL` (re-running does not create a second tenant for the same email; it reports the existing one).
2. **Runbook** `docs/gtm/runbooks/concierge-sale.md` — the manual sale loop around the command: (a) create a Polar one-time or subscription **payment link** for the agreed plan/price; (b) send it with the personalized pitch (reference plan §10 Move 1); (c) on Polar payment confirmation, run `make provision-customer`; (d) email the key + install steps (manual send now; Resend automates later in AP-6); (e) record the customer in the `leads`/tracking sheet.
3. **No new source-of-truth for keys** — reuse the recognition minter; do **not** stand up a parallel key store (`[ARCH-02]`). The raw key is shown once and never persisted in plaintext.

**Explicitly out of scope (do not build):** Clerk signup, the business DB, the dashboard, automated billing webhooks, plan *enforcement*. Those are AP-1..AP-5. AP-7 is the manual bridge that works *today*.

## Scoped TEST_CMD

```
# Against a local/staging recognition stack with the /admin minter available:
make provision-customer EMAIL=concierge-test@example.com PLAN=pro LABEL="Test Co"
```
**Assertions (encode as a pytest or a scripted check):**
- exit 0; a tenant exists for that email with `plan`/label recorded by the minter;
- the printed API key **authorizes a real recognition call** (passes `require_auth` in `apps/prototype-description-service/.../http/deps/auth.py`) — i.e. an authed request to a scan/analyze endpoint returns non-401;
- re-running the same command with the same `EMAIL` does **not** mint a second tenant (idempotency) and reports the existing tenant id;
- the key is printed exactly once and is not found in plaintext in any persisted file/log.

## Known-red baseline

- `make provision-customer` does not exist → target-not-found (red).
- No customer-provisioning path distinct from `provision-demo` (which sets expiry/quota) → the "non-demo, no-expiry" assertion fails (red).
- Runbook file absent (red).

## Notes for the lane

- Model the target on the existing `provision-demo` shape (§5 of the plan) minus the `demo_instances` slug/expiry/quota; label the key as customer-scoped.
- Polar account creation + payment-link generation are **operator-manual** (external SaaS UI) — the runbook documents them; the lane does not automate Polar.
- Keep the command output copy-paste-friendly for the operator to drop into an email until AP-6 (Resend) automates it.

---

## Ready-to-run `/offload` invocation (from inside a monorepo session)

```
/offload \
  --agent grok-cli \
  --effort high \
  --token-budget <N> \
  "AP-7 concierge sell-and-provision fast-path. End-state: `make provision-customer \
   EMAIL=<e> [PLAN=pro] [LABEL]` mints a real (non-demo) tenant+key via the existing \
   /admin manage_api_keys mechanism, prints key once + tenant id + WP install snippet, \
   idempotent on EMAIL; plus runbook docs/gtm/runbooks/concierge-sale.md. Reuse the \
   recognition minter — no new key store. TEST_CMD: make provision-customer \
   EMAIL=concierge-test@example.com PLAN=pro asserts the key passes require_auth and \
   re-run does not duplicate the tenant. Known-red: target undefined today. \
   Out of scope: Clerk, business DB, dashboard, billing webhooks, plan enforcement."
```
> Replace `<N>` with your per-lane token budget. Present the handoff diff to the branch-review gate before merge (no auto-merge).
