# Continuation prompt — tenant-pairing recovery + ops session (2026-07-12, post plan-PASS)

> Durable, tracked on main (predecessor `~/Development/context-alt-text-NEXT_SESSION_PROMPT.md`
> covers the DS-2B/GTM track — read both; they are parallel agents' states).

## Status coming in (DONE — do NOT redo)

- main @ fecb02ca: vendored canon refreshed (`docs/reference/engineering-heuristics-canon.md`)
  + **NEW** `docs/reference/security-heuristics-canon.md` (SEC-01..10 moved upstream out of
  engineering.md into `lexicons/security.md`; also web/PHP/WordPress/Postgres rules, many
  `Src=bootstrap` → tier S/J, not settled Blockers).
- **MAINT-tenant-pairing-recovery-20260711**: plan authored → /plan-analyze (4 findings) →
  rewrite → /planning-review (1 finding) → verdict **pass_with_findings** (decision #1933,
  runs 332/333). Plan: `docs/tasks/maint/MAINT-tenant-pairing-recovery-20260711-task-plan.md`
  @ feb8c619 on `feature/maint-tenant-pairing-recovery-20260711`
  (worktree `context-alt-text-monorepo-maint-tenant-pairing-recovery-20260711`).
  PA-01..04 + PR-01 all `resolved_on_branch`. **Open by design: MAINT-TPR-01..03** — they ARE
  the implementation work.
- **LocalWP fixed + on latest**: plugin symlinked (`wp-content/plugins/alt-context` →
  `apps/prototype-wp-alt-context`), Vite assets rebuilt, tenant pinned
  `acx_recognition_tenant_id=00000000-0000-7000-8000-000000000000` (ops/root tenant, site_url
  api.altcontext.com) + `acx_recognition_tenant_paired=1` directly in wp_options; key
  `...QWFc` + that tenant → prod `/health/detailed` 200. Cleaner later: mint a key for the
  localhost-derived tenant `c0ce73dc-1c66-56a4-ae32-6eb966810988`.
- **Fresh plugin ZIP** `dist/alt-context-0.0.4.zip` (old one was Jun 13; 86 plugin commits
  since — WBUX-3/4, E20 history UI). `make deploy-demo` still blocked: VM
  `/opt/acx-backend/demo/secrets/.env` missing (populate from `infra/oci/demo/.env.example`).
- **Prod schema drift LIVE**: `tenants.naming_agreement_enabled` absent on prod Postgres →
  `whoami` 500s, `manage_api_keys tenant list` crashes. Diagnosis + durable fix = the plan's D3.
- E21 UX epic (docs/epics/v0.4.1) still unimplemented: E21-3 (Confirm tab), E21-5 (unified
  review queue), E21-9 (person-first roster) are the top visitor-facing gaps; E15-17 s3–4 partial.

## The plan to implement (3 slices, offload-ready)

1. **Slice 1 (service)**: `require_auth_key_only` in
   `recognition/interface_adapters/http/deps/auth.py` (skip the `:198-208` tenant-compare);
   wire BOTH usages in `routers/tenant.py` (router deps + param). Extend
   `recognition/tests/api/test_tenant_whoami.py` red-first.
2. **Slice 2 (plugin)**: `class-settings-controller.php::test_connection` — on
   `TENANT_MISMATCH` run `attempt_tenant_pairing()`, then exactly ONE re-probe; banner confirm
   action in `testConnectionBanner.ts` + `SettingsPage.test.tsx`.
3. **Slice 3 (infra)**: boot schema-parity probe in `api/main.py` (beside
   `validate_oci_vault_boot`, :143-146) + `scripts/converge_schema.py` (ORM metadata vs
   information_schema, additive-only ALTERs, abort on non-additive) hooked into
   `scripts/deploy/recognition-service.sh`; runbook + one-time prod remediation (operator).

TEST_CMDs: `cd apps/prototype-description-service && uv run pytest -q -k "whoami or auth"` ·
plugin `composer test:unit` + `npm test`.

## Orchestration & lane offloading (what worked / directives)

- **Operator directive (standing)**: grok `/offload` for grunt/mechanical slices; codemap MCP
  for code searches (never grep sweeps). Memory: `feedback_grok_offload_codemap_searches`.
- Offload driver: MCP dispatch tools drop actor attribution — drive via
  `WORKBAY_HANDOFF_DEFAULT_AGENT=<agent> WORKBAY_GROK_MODEL=grok-4.5
  ~/.local/share/uv/tools/mcp-workbay-orchestrator/bin/python`, `configure_runtime` pinned to
  ROOT, `dispatch_lane_work` + `run_offload_pass(timeout_seconds=..., max_review_cycles=2)`
  via Bash run_in_background (900s exec cap). `needs_guidance`+`failed_stage=review` is a known
  false-negative — judge on `commit_landed` + own test run. Briefs need verified file:line
  anchors, scoped TEST_CMD with known baseline, out-of-scope list, NO Co-Authored-By.
- Lane manifests: `config/lane-orchestration/<task>.json` — `make lane-manifest-init` scaffolds;
  **workbay bug: deleted scaffolds regenerate themselves within seconds** (observed with
  DS-2B.json). Don't fight it; tracked manifests are the clean state.
- Subagent fan-out (Explore agents) worked well for repo-wide status audits (frontend-plan
  audit + deploy-mechanism scout ran parallel, ~2 min each).

## Codemap index regeneration

- Refresh at session start and before any dispatch/code search:
  `mcp__codebase-graph-mcp__index_repository(repo_path=<ROOT>, mode='full'|'moderate')`;
  per-worktree indexes exist separately (list_projects shows them). Offload freshness gate keys
  off the ROOT project name.
- `search_code(pattern=..., project='Users-daniel-Development-context-alt-text-monorepo')` —
  `pattern` + `project` both REQUIRED. It found the real whoami route (`routers/tenant.py`)
  when the finding had guessed admin.py — codemap-first caught an invented anchor ([AGT-02]).

## Branch-lifecycle abstractions (exact recipes)

- Ad-hoc main work: `make maint-start TASK=MAINT-<slug>-<YYYYMMDD> OBJECTIVE="..."` (TASK=,
  not SLUG=). Planning docs are hook-BLOCKED on main → `git worktree add
  ../context-alt-text-monorepo-<task-id> -b feature/<task-id>` then re-target:
  `mcp-workbay-handoff set --task-ref <ref> --target-branch feature/<...>
  --target-worktree-path <abs path> --expected-revision <rev>` (**expected-revision required
  on update**; fetch via `get_handoff_state(sections='identity')`).
- **Finding resolver preconditions** (all three, learned hard): (1) clean ROOT worktree
  (untracked files count), (2) workspace HEAD must be same-or-DESCENDANT of the finding's
  recorded commit — findings recorded on main while working a branch ⇒ merge main INTO the
  feature branch first, (3) resolving from a descendant requires `resolution_notes` (≤500
  chars). `update(status=fixed)` is hook-blocked; `resolve` is the only close path.
- `record_event` decision: required `session` + `decision` + `decision_id`; actor
  `model_label` must be the CANONICAL label (`Claude Opus 4.8`, not `Opus 4.8`).
- `review_findings` batch_record: `session` + per-finding `file_path`/`description` (not
  file/summary). `review_runs` record: `review_run_id` + `subject_path` required.
- `update` on findings ignores `file_path`/`description` edits (only status-ish fields) —
  correct wrong anchors via a NEW finding + resolve, as done with TPR-03/PA-01.

## Heuristics canon usage

- Source of truth: github.com/darce/heuristics-canon (PRIVATE — `gh api`, never WebFetch):
  `gh api repos/darce/heuristics-canon/contents/lexicons/<name>.md --jq .content | base64 -d`.
  Lexicons: engineering, security (NEW), business-marketing, accessibility, design-aesthetics,
  writing. Vendored copies: `docs/reference/*-heuristics-canon.md`. The gitignored
  `docs/workbay/rules/engineering-heuristics.md` is also synced to canon now.
- Method that works: pull relevant lexicons FIRST, cite IDs in plan/findings, verify each row
  ID exists before citing; planning-review then re-verifies anchors line-exactly.

## Ops access + env facts

- VM SSH: **tailscale only** — `ssh ubuntu@acx-backend` (100.115.186.109); public 22 closed.
  Agent auto-mode blocks prod SSH/reads — operator runs those commands (`! ssh ...`).
- Prod DB spelunking: compose service is `postgres` (not `db`);
  `docker compose -f docker-compose.env.yml exec -T postgres psql -U $POSTGRES_USER -d $POSTGRES_DB`.
  API keys stored sha256-hex in `api_keys.api_key_hash`; match a local raw key by hashing it.
- LocalWP: site `~/Development/wp-context-alt-text/app/public`, DB via
  `php -d mysqli.default_socket=$(scripts/localwp-runtime.sh socket)` mysqli root/root/local
  (wp-cli DB_HOST=localhost quirk makes wp-cli unreliable; direct mysqli works).

## Direction (priority order)

1. Implement MAINT-tenant-pairing-recovery Slices 1–3 (plan PASS; offload Slices 1+3 grunt
   parts via grok recipe; Slice 2 PHP/TS likely inline). Gate + merge per pre-merge rules.
2. Prod remediation (operator): run converge on prod once Slice 3 lands; verify whoami 200.
3. Demo secrets: populate `/opt/acx-backend/demo/secrets/.env` (operator) → `make deploy-demo`
   (fresh ZIP already in dist/) → `make demo-walkthrough-proof`.
4. E21 UX epic: draft task plans for E21-3 / E21-5 / E21-9 (no plans exist; epic "planned").
5. Coordinate with parallel DS-2B/GTM agent state (`~/Development/context-alt-text-NEXT_SESSION_PROMPT.md`).

## Kickoff

1. `make context` (standalone, ROOT). 2. Re-index codemap (ROOT + live worktrees).
3. Resume `MAINT-tenant-pairing-recovery-20260711` from its worktree; dispatch Slice 1.
