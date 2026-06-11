# LocalWP Playwright Evidence

This runbook is the operator path for the E15 Playwright harness. Scripts, config, and Makefile targets ship in `apps/prototype-wp-alt-context` and the repo-root Makefile.

## Prerequisites

- LocalWP site is running.
- WordPress admin is available at `http://localhost:10010/wp-admin/`.
- LocalWP language is English (the auth bootstrap uses the stable `#wp-submit` button id, but selectors elsewhere may assume English admin chrome).
- The Alt Context plugin is activated in that LocalWP site.
- App dependencies are installed under `apps/prototype-wp-alt-context`, or available from the common git worktree's `node_modules` through the shared Playwright launcher.
- Use the package-manager-pinned npm through Corepack if the shell npm is older than `11.14.1`.
- Chromium is installed for Playwright: `npm run e2e:install` (or `make localwp-e2e-install` from the repo root).

## Credentials Setup

From `apps/prototype-wp-alt-context`:

```bash
cp .env.local.example .env.local
```

Then edit `.env.local` and set:

```text
ACX_E2E_WP_ADMIN_USER=...
ACX_E2E_WP_ADMIN_PASS=...
# Optional: override when LocalWP is not at the default site root:
# WP_BASE_URL=http://localhost:10010
```

`.env.local` stays on the operator workstation only. Do not paste credentials into committed files, shell history notes, or task plans.

## Auth Bootstrap

From `apps/prototype-wp-alt-context`:

```bash
npm run e2e:auth
```

Or from the repo root:

```bash
make localwp-e2e-auth
```

Behavior:

- If both env vars are set, the bootstrap logs in non-interactively and writes shared auth state.
- If either env var is missing, the harness opens a headed browser and pauses so the operator can complete the login interactively.
- Successful bootstrap writes `tests/e2e/.auth/storageState.json`.

## Evidence Capture Recipes

Use `ACX_PLAYWRIGHT_TASK_REF` so the artifact bundle lands under the right task directory.

The committed v1 evidence spec captures the ACX Dashboard. Workbench avatar/progress, LocalWP to OCI scan proof, and public-demo proof can use the same storage-state and artifact convention, but those richer captures still need either a headed operator flow or a task-specific evidence spec before they become fully repeatable.

### No-secret harness checks

These checks prove the Playwright harness is installed and discoverable without using WordPress credentials:

```bash
corepack npm install
corepack npm run e2e:install
ACX_PLAYWRIGHT_TASK_REF=E15-6 corepack npm run e2e:list
```

If package fetching is blocked by local policy, the launcher now falls back to the common git worktree's `apps/prototype-wp-alt-context/node_modules` when that sibling install already exists. If neither local nor common-worktree dependencies exist, stop there and record the blocker; do not relax the package engine or dependency rules.

An unauthenticated reachability screenshot can be captured when LocalWP is running:

```bash
mkdir -p local/playwright/E15-6/cli
ACX_PLAYWRIGHT_TASK_REF=E15-6 bash scripts/playwright-cli.sh screenshot --full-page http://localhost:10010/wp-admin/ local/playwright/E15-6/cli/wp-admin-entry.png
```

That screenshot proves the browser can reach WordPress admin. It does not prove plugin activation, auth, backend connectivity, or scan success.

### E15-3a LocalWP to OCI roundtrip

- Bootstrap auth once.
- Run the headed evidence project with `ACX_PLAYWRIGHT_TASK_REF=E15-3a`.
- Use the committed dashboard evidence spec for admin/plugin reachability and artifact-shape proof.
- Capture Workbench scan screenshots or traces with a headed operator flow until an E15-3a-specific evidence spec exists.
- Keep OCI backend logs, correlation IDs, CORS/rate-limit evidence, fallback timeout proof, and redacted run-log entries in the E15-3a operator run log.

### E15-22 Workbench avatar and progress proof

- Bootstrap auth once.
- Run the headed evidence project with `ACX_PLAYWRIGHT_TASK_REF=E15-22`.
- The committed `tests/e2e/evidence/workbench-evidence.spec.ts` opens Workbench with `status=missing`, captures any **existing** naming-queue avatars/review drawer first, then runs a scan only when cluster evidence is still missing. Service mode is opt-in via `ACX_E2E_ENSURE_SERVICE_MODE=1`; the spec probes `/acx/v1/settings/test` and restores the prior option-owned source when the probe is not `connected`.
- Optional env overrides in `.env.local`: `ACX_E2E_ENSURE_SERVICE_MODE=1`, `ACX_E2E_RECOGNITION_URL` (default `https://api.altcontext.com`), `ACX_E2E_RECOGNITION_API_KEY` (only when the stored key is missing).
- Each run writes `evidence-manifest.json` beside the PNGs listing which captures succeeded.

### E15-5 live-demo roundtrip placeholder

- Use the same LocalWP harness shape with `ACX_PLAYWRIGHT_TASK_REF=E15-5` until public-demo auth exists.
- Treat this as a LocalWP rehearsal path, not a substitute for the later public-demo storage-state work.
- Public-demo browser proof starts only after the live site URL, credentials/storage state, and backend connection exist.

## Operator Work That Remains

- LocalWP must be running with the packaged plugin activated; Playwright does not install or configure the site.
- Admin credentials stay in `.env.local` or the interactive browser prompt; do not send them through agent chat or command history.
- OCI deployment, gate-key placement, backend logs, request IDs, CORS/rate-limit checks, and fallback timeout evidence remain shell/operator proof.
- Seeded-media selection and proof-bundle curation remain operator-owned until v2 seed/reset helpers exist.
- E15-5a operational hygiene has no useful browser surface; use shell/operator evidence.

## Artifact Redaction Rules

Before copying anything out of `local/playwright/<task-ref>/`:

- Remove screenshots or traces that reveal secrets, tokens, or typed credentials.
- Prefer cropped screenshots that show the proof surface only.
- Keep raw local artifacts in the gitignored task-scoped directory; export redacted copies elsewhere only when needed for a proof bundle.

## Notes

- The command names in this runbook are contractual and wired in `package.json` plus the root `Makefile`.
- New smoke specs should reuse the same auth/bootstrap conventions documented here rather than inventing a second path.
- The absorbed tech-debt durable smoke work stays out of this runbook until the v2 envelope starts shipping.
