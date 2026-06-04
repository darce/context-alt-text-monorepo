# LocalWP Playwright Evidence

This runbook is the operator path for the E15 Playwright harness. Slice 1 defines the workflow and file conventions here; Slice 2 adds the actual scripts and config.

## Prerequisites

- LocalWP site is running.
- WordPress admin is available at `http://localhost:10010/wp-admin/`.
- The Alt Context plugin is activated in that LocalWP site.
- App dependencies are installed under `apps/prototype-wp-alt-context`.
- Chromium is installed for Playwright via the planned `npm run e2e:install` command.

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

Expected Slice 2 command:

```bash
npm run e2e:auth
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

## Notes For Slice 2 And Later

- The command names in this runbook are contractual now even though the actual scripts land in Slice 2.
- The first smoke spec in Slice 3 should reuse the same auth/bootstrap conventions documented here instead of inventing a second path.
- The absorbed tech-debt durable smoke work stays out of this runbook until the v2 envelope starts shipping.