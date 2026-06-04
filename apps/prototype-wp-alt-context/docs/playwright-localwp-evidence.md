# LocalWP Playwright Evidence

This runbook is the operator path for the E15 Playwright harness. Scripts, config, and Makefile targets ship in `apps/prototype-wp-alt-context` and the repo-root Makefile.

## Prerequisites

- LocalWP site is running.
- WordPress admin is available at `http://localhost:10010/wp-admin/`.
- LocalWP language is English (the auth bootstrap uses the stable `#wp-submit` button id, but selectors elsewhere may assume English admin chrome).
- The Alt Context plugin is activated in that LocalWP site.
- App dependencies are installed under `apps/prototype-wp-alt-context`.
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

### E15-3a LocalWP to OCI roundtrip

- Bootstrap auth once.
- Run the headed evidence project with `ACX_PLAYWRIGHT_TASK_REF=E15-3a`.
- Capture the LocalWP action, backend-connected response, and any screenshots or trace files needed for the roundtrip proof bundle.

### E15-22 Workbench avatar and progress proof

- Bootstrap auth once.
- Run the headed evidence project with `ACX_PLAYWRIGHT_TASK_REF=E15-22`.
- Capture the Workbench surfaces that show truthful avatar/progress rendering for the accepted demo scenario.

### E15-5 live-demo roundtrip placeholder

- Use the same LocalWP harness shape with `ACX_PLAYWRIGHT_TASK_REF=E15-5` until public-demo auth exists.
- Treat this as a LocalWP rehearsal path, not a substitute for the later public-demo storage-state work.

## Artifact Redaction Rules

Before copying anything out of `local/playwright/<task-ref>/`:

- Remove screenshots or traces that reveal secrets, tokens, or typed credentials.
- Prefer cropped screenshots that show the proof surface only.
- Keep raw local artifacts in the gitignored task-scoped directory; export redacted copies elsewhere only when needed for a proof bundle.

## Notes

- The command names in this runbook are contractual and wired in `package.json` plus the root `Makefile`.
- New smoke specs should reuse the same auth/bootstrap conventions documented here rather than inventing a second path.
- The absorbed tech-debt durable smoke work stays out of this runbook until the v2 envelope starts shipping.