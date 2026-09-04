# WAVEPLAN-1. Wave plan — OCIRV-1 gate → duxw2-nav → GPUUX-1 backend + UI → GPU live procurement → bounded smoke

**Status:** draft for review — no `dispatch_lane_work` / `dispatch_wave` until approved.
**Task ref:** `WAVEPLAN-1` · branch `feature/waveplan-1` · supersedes the "next_actions" of `cont-20260903T175233376245Z-836f3ff6`.
**Backends:** implement + grunt lanes = `codex-remote` / `gpt-5.6-sol` / `reasoning_effort=high`. Reviewers = 1 local (in-process `Agent`) + N remote (`codex-remote`, `grok-remote`, `cursor-remote`). `codex-subagent` bridge is `declared_not_installed` → review-parallel local path is the in-process fallback, recorded as `routing_downgrade` per skill.

## 0. Ground truth (verified 2026-09-03, main @ `f66c5335`)

| Item | State | Consequence |
| --- | --- | --- |
| OCIRV-1 `feature/ocirv-1` @ `c02741c0` | 0 findings, 0 blockers, no review run, last test_result @ `2c764eda` (not HEAD). `git merge-tree main` → **CONFLICT in Makefile** (additive, 0 conflict-marker lines in the tree output — trivial). | Needs main-sync commit + fresh test_result @ new HEAD + review run + slice-complete + `handoff_close_check(enforce=True)`. |
| duxw2 lanes 524/521/520 (step/orient/copy) | `vmgate/feature/duxw2-integration` @ `972767f7` merges `lane/duxw2-{step,orient,copy,vocab}` and is **0 ahead of main** → already landed. Lane rows still `blocked` on `npm test`. | Close rows as landed; do **not** re-dispatch. |
| duxw2-nav lane 519 (`src/admin/class-menu.php` + `MenuTest`) | Never merged into duxw2-integration. Branch + worktree gone. | Re-create from main, `vendor/bin/phpunit --filter MenuTest`, dispatch. Verify absence on main first (`git log main --grep=duxw2-nav`). |
| GPUUX-1 `feature/gpuux-1` @ `4dbf1bec` | 80 behind main; conflicts in `Makefile`, `infra/oci/gpu_lifecycle/reaper.py`, `scripts/deploy/gpu-lifecycle-install.sh`, `uv.lock`. 7 open findings (2 high). Lane 1014 fix3 `blocked`. E1 test list names `gpuStatePresentation.test.ts` which does **not** exist on `feature/gpuux-1-e1` (RED test to be written — correct for TDD). | Main-sync **before** fix3 so fixes land on post-merge code once. |
| GPU live procurement | Path today: UI → PHP → `POST describe-run` → worker `_wait_for_gpu_ready` polls health ≤ `ACX_GPU_WARMUP_TIMEOUT_SECONDS`; separately `describe_load.refresh_load_snapshot_loop` writes `/run/acx/describe-load.json`; `acx-gpu-start.timer` (`OnUnitActiveSec=START_INTERVAL`) polls it; reaper `--mode start` → `oci compute instance action START --wait-for-state RUNNING` → ready probe 30×10s. | Two poll intervals + boot are serial. Design in §6. |

Standing constraints (from continuation gotchas, unchanged): never delete branches; never reap VM lanes with shortened TTL; coordinator never edits peer worktrees (`ocirv-1`, `gpuux-1*`, `febt-1*`, `wbux-6*`) — every edit there is a dispatched lane; never archive `MAINT-stockgauge-ceiling-20260902`; always pass `task_ref=` to orchestrator tools; no `make task-reap --apply`; no raw `ssh gate@…` (use `make check-remote` / `workbay repair --with-remote`); FEBT-1 and WBUX-6 out of scope.

## 1. Nodes

Each node names its **declared inputs** (GRPH-32/33: an edge exists only where a named field moves) and its **owned paths** (GRPH-09: conflict graph = shared files).

| Node | task_ref / lane | Kind · backend | Owned paths (write set) | test_cmd (classifier-admissible) | Reads (in-edges) | Emits |
| --- | --- | --- | --- | --- | --- | --- |
| **A1** ocirv-sync | OCIRV-1 · new lane `ocirv-1-sync` | implement · codex-remote | `Makefile` (merge main into `feature/ocirv-1`, resolve additive block only) | `make test-deploy-contract && python3 -m pytest scripts/test_ocirv1_vault_readiness.py scripts/test_shell_parses_under_system_bash.py -q` | main SHA `f66c5335` | `OCIRV-1.head_sha`, test_result@head |
| **A2** ocirv-review | OCIRV-1 | review · 1 local + 2 remote (`codex-remote`, `grok-remote`) | none (record-only) | — | A1.head_sha, `git diff main...feature/ocirv-1`, semantic packet | findings (target 0 open), review_run |
| **A3** ocirv-gate+merge | OCIRV-1 · coordinator (root worktree) | gate · local | main (merge commit only) | `make close-check` | A2.review_run, A1.test_result | main SHA' (contains OCIRV-1 Makefile block) |
| **B0** duxw2-close-landed | ORCH-UX-UI · lanes 524/521/520 | grunt · coordinator MCP | none | — | `vmgate/feature/duxw2-integration` ⊆ main | lane rows closed, decision |
| **B1** duxw2-nav | ORCH-UX-UI · lane 519 recreated | implement · codex-remote | `apps/prototype-wp-alt-context/src/admin/class-menu.php`, `tests/Unit/MenuTest.php` | `cd apps/prototype-wp-alt-context && vendor/bin/phpunit --testsuite Unit --filter MenuTest` | main SHA | branch `lane/duxw2-nav`, test_result |
| **B2** duxw2-nav review+land | ORCH-UX-UI | review · 1 local + 1 remote → merge | main | `make close-check` | B1 | main |
| **C1** gpuux-sync | GPUUX-1 · new lane `gpuux-1-sync-main` | implement · codex-remote | `Makefile`, `infra/oci/gpu_lifecycle/reaper.py`, `scripts/deploy/gpu-lifecycle-install.sh`, `uv.lock` (conflict resolution only; `uv lock` regen) | `python3 -m pytest infra/oci/gpu_lifecycle/tests -q --tb=short && make test-gpu-snapshot-checker` | **A3.main SHA'** (must absorb OCIRV-1 Makefile block once) | `GPUUX-1.head_sha` |
| **C2** gpuux-fix3 | GPUUX-1 · lane 1014 (re-dispatch) | implement · codex-remote | `Makefile` (deploy-verify rules, `test-scripts`), `infra/oci/gpu_lifecycle/reaper.py` (`_serialized_gpu_state_publish` OSError → loud fail + `gpu_state=unknown`, lock umask), `scripts/deploy/check-gpu-snapshots.sh`, `scripts/deploy/tests/test-check-gpu-snapshots.sh`, `scripts/deploy/tests/test_check_gpu_snapshots_shell.py`, `scripts/deploy/recognition-service.sh` (post-restart checker call, A-07) | `python3 -m pytest infra/oci/gpu_lifecycle/tests scripts/deploy/tests/test_check_gpu_snapshots_shell.py -q --tb=short` | C1.head_sha, findings BR-01..06 + A-07 bodies (from `review_findings(list)`) | findings → `fixed` w/ `verified_commit_sha` |
| **D** gpuux-d-php | GPUUX-1 · lane 993 (switch backend to codex-remote) | implement · codex-remote | `apps/prototype-wp-alt-context/src/api/class-describe-controller.php`, `tests/Unit/DescribeRunControllerTest.php` | `cd apps/prototype-wp-alt-context && vendor/bin/phpunit --testsuite Unit --filter DescribeRunControllerTest` | C1 (contract `packages/shared-contracts/schemas/scene-describe-run.schema.json` `gpu_state` field) | PHP passthrough of `gpu_state` |
| **E1** gpuux-e1-fe | GPUUX-1 · lane 990 | implement · codex-remote | `js/admin/api/describeApi.ts` (`GPU_STATE` as const), `js/admin/copy/syncVocabulary.ts`, `js/admin/pages/workbench/phasePresentation.ts` (`GPU_STATE_PRESENTATION`), `js/admin/pages/workbench/MediaSelection.tsx` (tier chip), `js/admin/hooks/useDescribeRunProgress.ts` (expose `gpuState`), tests incl. **new** `gpuStatePresentation.test.ts` | `cd apps/prototype-wp-alt-context && npx vitest run js/admin/api/__tests__/describeApi.test.ts js/admin/hooks/__tests__/useDescribeRunProgress.test.tsx js/admin/pages/workbench/__tests__/gpuStatePresentation.test.ts js/admin/__tests__/banned-vocabulary.test.tsx` | same contract field as D; ux-map `describe-gpu-tier.uxmap.json` screens 1–4 | `useDescribeRunProgress().gpuState` |
| **E2** gpuux-e2-toasts | GPUUX-1 · new lane `gpuux-1-e2-toasts` | implement · codex-remote | `js/admin/hooks/useGpuStateToasts.ts` (+test), `js/admin/App.tsx` (mount only) | `cd apps/prototype-wp-alt-context && npx vitest run js/admin/hooks/__tests__/useGpuStateToasts.test.tsx` | **E1.gpuState** (named field), ux-map toast policy table | edge-triggered toasts |
| **F** gpuux-review | GPUUX-1 | review · `/wb-review-slice` 1 local + 3 remote + HARM pass | none | — | C2, D, E1, E2 slice packets + semantic packets + codemap blast radius | findings, review_run |
| **G** gpuux-gate+merge+deploy | GPUUX-1 · coordinator | gate · local | main; deploy via `make deploy-verify-dev` (fixed in C2) | `make close-check`; `make check-remote` | F (0 open), fresh test_result @ HEAD | main, deployed backend |
| **H1** gpu-smoke-dry | GPUUX-1 · lane or coordinator | verify | none | `make gpu-burst-smoke` | G | test_result |
| **H2** gpu-smoke-live | operator-gated · coordinator via `make gpu-burst-smoke-live` | verify · runs on acx-backend as ubuntu | none | `ACX_GPU_SMOKE_CONFIRM=RUN ACX_GPU_SMOKE_SERVICE_BASE_URL=… make gpu-burst-smoke-live` (`--max-seconds 1200`, STOP in `finally`) | H1 pass, G deployed | test_result + instance `lifecycle-state: STOPPED` line |
| **P\*** gpu-procurement | new task `GPUPROC-1` (separate approval, §6) | implement · codex-remote | see §6 | see §6 | G (merged gpu_state contract) | — |

## 2. DAG

```
            ┌──────────────────────── W0 ────────────────────────┐
            │  A1 ocirv-sync      B0 duxw2-close     B1 duxw2-nav │
            └───────┬──────────────────┬───────────────────┬─────┘
                    ▼                  │                   ▼
            ┌── W1 ─┴────────┐         │           ┌── W1 ─┴──────┐
            │ A2 ocirv-review│         │           │ B2 nav review │
            └───────┬────────┘         │           └───────┬──────┘
                    ▼                  │                   │
            ┌── W2 ─┴────────┐         │                   │
            │ A3 ocirv-merge │ ← main' │                   │
            └───────┬────────┘         │                   │
                    ▼  (Makefile block)                    │
            ┌── W3 ─┴────────┐                             │
            │ C1 gpuux-sync  │                             │
            └───────┬────────┘                             │
                    ▼  (GPUUX-1.head_sha)                  │
   ┌───────────── W4 ┴──────────────────────────┐          │
   │ C2 fix3 (backend)   D php    E1 fe-states  │          │  ← width 3, disjoint write sets
   └──────┬───────────────┬──────────┬──────────┘          │
          │               │          ▼ (gpuState field)    │
          │               │   ┌── W5 ┴──────┐              │
          │               │   │ E2 toasts   │              │
          │               │   └──────┬──────┘              │
          ▼               ▼          ▼                     ▼
   ┌───────────── W6 ────────────────────────────┐   (B2 lands independently)
   │ F  /wb-review-slice  (S1..S4 + HARM)        │
   └──────────────────────┬──────────────────────┘
                          ▼
   ┌───────────── W7 ────────────────────────────┐
   │ G  close-check → merge → deploy-verify-dev  │
   └──────────────────────┬──────────────────────┘
                          ▼
   ┌───────────── W8 ────────────────────────────┐
   │ H1 smoke-dry ──► H2 smoke-live (STOP in finally) │
   └──────────────────────┬──────────────────────┘
                          ▼
                 P* GPUPROC-1 (§6, separate approval)
```

**Edge justification (GRPH-32):** A3→C1 carries the merged Makefile block (data); C1→{C2,D,E1} carries `GPUUX-1.head_sha` (lanes fork from post-sync tip); E1→E2 carries `useDescribeRunProgress().gpuState`; {C2,D,E1,E2}→F carries slice packets; F→G carries `review_run` + 0-open findings; G→H carries deployed `gpu_state` publisher. A1→A2, B1→B2 are review-of-output edges. **Non-data edges:** C1 after C2 is forbidden (same files, resource exclusivity); B1 ∥ everything (disjoint PHP file). No edge from duxw2 to GPUUX-1 — the duxw2 UI work is already on main.

**Critical path (GRPH-31):** A1 → A2 → A3 → C1 → C2 → F → G → H1 → H2 (9 nodes; C2 is the longest W4 lane). B-chain and D/E1/E2 are off the spine. Makespan floor ≈ 1 codex-remote turn each for A1, C1, C2 (≤3600 s cap) + 2 review rounds + deploy + 1200 s smoke. Width cap = 3 concurrent remote lanes (W4); W0 uses 2 remote lanes (A1, B1) + MCP-only B0.

**Conflict colouring (GRPH-09):** shared files → same colour class must be serial: {A1, A3, C1, C2} all touch `Makefile` → serialised A1<A3<C1<C2. {C1, C2} share `reaper.py`. {E1, E2} disjoint by construction (E2 owns only `useGpuStateToasts.ts` + `App.tsx` mount). WBUX-6 conflicts on `describeApi.ts` with E1 → WBUX-6 stays parked until G lands (out of scope here).

## 3. Wave dispatch spec

| Wave | Lanes (backend) | `dispatch_wave` settings | Gate to next wave |
| --- | --- | --- | --- |
| W0 | A1 `ocirv-1-sync`, B1 `duxw2-nav` (codex-remote gpt-5.6-sol high); B0 = `manage_worktree_lane(close)` ×3 with note "landed via duxw2-integration 972767f7 ⊆ main" | `include_context_packet=true`, `context_targets` = owned paths; `timeout 3600` | both lanes `test_result.passed=true` @ their HEAD |
| W1 | A2 review (1 local Agent + codex-remote + grok-remote reviewers, adversarial template, lenses: release-it ch-5/ch-11 secrets, ddia ch-8, security lexicon `SEC-*` for stdin-only token flow), B2 review (1 local + 1 remote) | reviewer refs `OCIRV-1-REV-r0903<sha7>-A/B/C` — whole-branch fallback (no slice_complete decisions on OCIRV-1; state so in verdict) | 0 open findings; `review_runs(record)` |
| W2 | A3: `record_event(test_result)` already from A1, `close_slice`, `handoff_close_check(enforce=True)`, merge `feature/ocirv-1` → main from root (`--no-ff`), branch retained | local | main' SHA |
| W3 | C1 `gpuux-1-sync-main` (codex-remote): `git merge main` into `feature/gpuux-1`; resolve 4 files; `uv lock`; run test_cmd; **no functional changes** | context packet: `docs/workbay/contracts/gpu-lifecycle.md`, decisions 6449/6456/2266 | test_result @ new head; coordinator diff-audits that only conflict hunks changed |
| W4 | C2 fix3 (lane 1014 re-dispatch), D (lane 993 → codex-remote), E1 (lane 990) — all forked from C1 head | `dispatch_wave` width 3; each lane gets `find_related_prior_work` + `semantic_reinjection_packet(anchor_texts=owned paths)` + codemap `trace_path` for `run_start_cycle`/`_serialized_gpu_state_publish` (C2) and `useDescribeRunProgress` (E1) | each lane: RED test_result → GREEN test_result; C2 additionally `review_findings(update, status=fixed, verified_commit_sha)` for BR-01..06, A-07 |
| W5 | E2 toasts (forked from E1 head) | same packet discipline | GREEN |
| W6 | F `/wb-review-slice`: slice mode S1=C2, S2=D, S3=E1, S4=E2; reviewers_per_slice=1 remote (codex-remote for S1/S2, grok-remote S3, cursor-remote S4) + 1 local HARM-A Agent; lenses per §5 | round `r0903<sha7>` single-probe preflight | 0 open (fix loop bounded to 2 rounds via `/wb-auto-fix`; 3rd round → stop and report) |
| W7 | G: fresh `python3 -m pytest infra/oci/gpu_lifecycle/tests -q` + vitest + phpunit test_results @ HEAD, `close_slice`, `handoff_close_check(enforce=True)`, merge → main, `make deploy-verify-dev`, `make check-remote` | local | deployed; `gpu-state.json` readable on VM (`make check-gpu-snapshots`) |
| W8 | H1 `make gpu-burst-smoke` (dry-run, in-process OCI state machine) → H2 live | H2 needs operator env: `ACX_GPU_SMOKE_CONFIRM=RUN`, `ACX_GPU_SMOKE_SERVICE_BASE_URL`, app-password/api-key env names; `--max-seconds 1200`; STOP issued in `finally`; reaper max-lease is the second backstop (dual control, two keys) | test_result whose `result` includes the post-run `lifecycle-state: STOPPED` line; if not STOPPED → blocker, manual STOP via `workbay repair --with-remote`, no further GPU runs |

Every state change: `record_event(decision)` + `render_handoff(kind='dashboard')`. Every lane dispatch: `offload_preflight` first; refused `test_cmd` is a specification error to fix in the lane, never `bash -c` wrapping (AGT-08).

## 4. Per-lane briefs (what the remote lane receives)

**A1 ocirv-1-sync.** Merge `main` into `feature/ocirv-1`. Only the Makefile additive block conflicts; keep both OCIRV-1 targets and main's. No other edits. Run test_cmd; record test_result. Canon: reversible-commitments (merge commit, no rebase of a reviewed branch).

**B1 duxw2-nav.** Recreate from main: `manage_worktree_lane(upsert, task_ref='ORCH-UX-UI', lane_id=519, worktree_path='…-duxw2-nav', branch='lane/duxw2-nav', backend='codex-remote', model='gpt-5.6-sol', reasoning_effort='high', test_cmd=<phpunit>)`. Objective unchanged from row 519 (admin menu IA change in `class-menu.php`). RED: `MenuTest` asserts new menu order/labels; GREEN: minimal change. Canon: NAV-09 (menu IA), rg-016 autoload parity (`class-*.php` needs `require_once` — verify with `php -r class_exists`).

**C1 gpuux-1-sync-main.** Merge main' into `feature/gpuux-1`. Conflicts: `Makefile` (keep GPUUX-1 gpu targets + main's OCIRV-1 + vmreap targets), `reaper.py` (main gained per-instance lease flock from gpusmoke-1; GPUUX-1 added `_serialized_gpu_state_publish` — both must survive; do not merge the two lock files into one), `gpu-lifecycle-install.sh` (both unit edits), `uv.lock` (regenerate with `uv lock`, do not hand-edit). No behaviour change. Canon: DATA-14 single writer per file stays intact; RES-10 fencing — verify the lease epoch path from main is not dropped.

**C2 gpuux-1-fix3 (lane 1014 re-dispatch).** Closes the 7 open findings; per finding the lane reads the body from `review_findings(list, task_ref='GPUUX-1', status='open')` — bodies are not duplicated here. Design constraints: publish failure must **fail loudly and mark `gpu_state=unknown`** with reason, never silent skip (fail-loudly-succeed-quietly card, RLSE-04, DIAG-07); prerequisite-only `deploy-verify-*` rules must be deleted in favour of `mk/deploy.mk` recipes (delete-over-flag); OCI_HOST default must be the Tailscale name, not the public IP; the shell suite gets a runnable pytest wrapper (`test_check_gpu_snapshots_shell.py` already exists → make it the approved runner, BR-06); mutation-surviving assertion in `test-check-gpu-snapshots.sh` replaced with a real negative case (TEST-15); checker invoked from `recognition-service.sh` post-restart and `make check-gpu-snapshots` (A-07). RED first for each behaviour (tdd skill), then `review_findings(update, status='fixed', verified_commit_sha=<40-char>)`.

**D gpuux-1-d-php.** `class-describe-controller.php` passes `gpu_state` through from the service response unchanged; unknown values → `unknown` (never fabricate, rg-015). Test asserts passthrough + unknown mapping.

**E1 gpuux-1-e1-fe.** `GPU_STATE` as const (sr-007), `GPU_STATE_PRESENTATION` map, tier chip in `BulkDescribeProgress`, `useDescribeRunProgress` exposes `gpuState`. Screens: ux-map Screen 1 (stopped CTA copy), 2 (warming w/ countdown + Cancel + "Use CPU drafts now"), 3 (degraded, `role=status`), 4 (dashboard single-describe). Vocabulary guard: `banned-vocabulary.test.tsx` must stay green. Canon: INT-08 wait+cancel, CARD-09 bounded waiting, HAI-05 provenance of tier, CAL-02 designed unknown.

**E2 gpuux-1-e2-toasts.** `useGpuStateToasts(gpuState)` edge-triggered: `starting→ready` ("GPU ready — remaining items upgrade"), `→degraded` (kept CPU drafts), no toast on `unknown` flicker (debounce one poll). Mounted once in `App.tsx`. Canon: INT-10 (no toast storms), CARD-15.

## 5. Review gate protocol (W1, W6)

- Skill: `review-parallel` (`/wb-review-slice`), adversarial default template, `reviewers_per_slice=1` remote + HARM-A local. Coordinator = this session (Claude Code → in-process `Agent` for local reviewer; remote reviewers via `dispatch_lane_work(lane_kind='review')`).
- Context per reviewer: `semantic_reinjection_packet(anchor_texts=<slice changed_files + rationale>)`; codemap `trace_path` blast radius for touched symbols; prior findings `DEMO-UX-1-GPU-01`, `WBUX-6-REV-r0902rd3-HARM-A-F2`; contract `docs/workbay/contracts/gpu-lifecycle.md`; ux-map JSON.
- Lenses (heuristics canon `~/Development/heuristics-canon-research`): **ddia** ch-8 (RES-10 fencing, clock skew in `written_at`), **release-it** ch-5 (RES-14 handshake, RES-15 breaker, RES-07 reclaim), **latency/perf** (COST-03/05/06, PERF-04 Amdahl on the poll chain), **interaction** (INT-08, INT-10, NAV-09, HAI-05), **security** (stdin-only secrets for OCIRV-1), reasoning cards CARD-06 evidence-before-commitment, CARD-09, designed-unknown, dual-control-two-keys (STOP backstops).
- Verdict decision cites commit SHA; findings only in MCP (never in this plan).

## 6. GPU live procurement from the web UI — design (answer + proposed GPUPROC-1)

**Today's latency chain** (serial): click → `refresh_load_snapshot_loop` interval Δ₁ → `acx-gpu-start.timer` `START_INTERVAL` Δ₂ → OCI START + `--wait-for-state RUNNING` (~60–120 s) → VLM warm (decision 2266) → ready probe (10 s granularity) → worker `_wait_for_gpu_ready`. UI sees a static "~2 min".

**Proposed changes, ordered by leverage/risk:**

| # | Change | Where | Canon | Removes |
| --- | --- | --- | --- | --- |
| P1 | **Intent pre-warm with TTL.** UI sends `POST /describe-run/intent {tier:'gpu', ttl_s:180}` on CTA hover/≥N selection; service writes `prewarm_until` into `describe-load.json`; `JobLoadSnapshot.has_work` includes `prewarm_until > now`. Abandoned intent expires → no cost. | `describe_load.py`, `controller.py`, `reaper.py` (parse), PHP passthrough, `describeApi.ts` | CARD-09, COST-03 (bounded spend), speculative work bounded by TTL | user-decision time from the chain |
| P2 | **Event-driven START.** `acx-gpu-start.path` (systemd `PathChanged=/run/acx/describe-load.json`) triggers `acx-gpu-start.service` in addition to the timer. Single writer unchanged (DATA-14). | `gpu-lifecycle-install.sh` | RES-14 handshaking; DATA-15 causal order | Δ₂ (up to `START_INTERVAL`) |
| P3 | **Calibrated ETA in `gpu-state.json`.** Reaper publishes `starting` immediately on actuation with `started_at`, `expected_ready_at` = p50 of last N boots from lease history; UI countdown reads it (replaces static "~2 min"). Unknown history → omit field, UI shows "warming…" (designed unknown). | `state_snapshot.py`, `reaper.py`, `phasePresentation.ts` | CAL-02, CARD-03, HAI-05 | wrong static estimate |
| P4 | **Fencing epoch + breaker.** Lease `epoch` in `running-since.json`; worker warm-start carries epoch; STOP with stale epoch refused (RES-10). After 3 consecutive START failures → `gpu_state=degraded`, cooldown 10 min, UI CPU-only (RES-15, DIAG-07). | `reaper.py`, `controller.py`, `gpu_remote_adapter.py` | RES-10, RES-15 | START/STOP races, retry storms |
| P5 | **Idle grace sized to session cadence.** `IDLE_SECONDS` from observed inter-batch gaps p90 (COST-05 knee), hard `MAX_LEASE_SECONDS` unchanged; UI shows ≈$ per run from lease history. | install env + ux-map chip | COST-05/06 | cold re-boots inside one session |

GPUPROC-1 waves (proposed, **not** dispatched under this plan): W_a {P1 backend+contract, P2 install unit, P3-UI} (disjoint files) → W_b {P3-backend, P4} (both `reaper.py` → serial or split ownership) → W_c {P5}. Needs its own task plan + `/wb-review-plan` after G lands; the `gpu_state` contract from GPUUX-1 is its input.

**Counter-case:** pre-warm on hover can burn cost on browsing; mitigated by TTL + `has_work` refusing START when snapshot `untrustworthy` (W3-D-04 unchanged) + max-lease. If the demo budget (`DS-2B`) forbids speculative starts, P1 degrades to explicit "Warm GPU" button (still P2/P3 gains).

## 7. GPU smoke — stop guarantee

H2 runs `scripts/gpu_burst_smoke.py` live mode: every OCI/HTTP op has a timeout, `--max-seconds 1200`, STOP issued in `finally`, no password on argv. Backstops: reaper `--max-lease-seconds` forced STOP; post-run coordinator check via `make check-remote` and the smoke's own final `instance get` line recorded in the test_result. Failure to observe `STOPPED` → `record_event(blocker)` and manual STOP before anything else. Batch runs (if any) happen inside the same bounded smoke window; no unattended GPU.

## 8. Risks / rollback

| Risk | Mitigation |
| --- | --- |
| C1 merge silently drops a main-side reaper fix (80 commits) | Coordinator diffs `main...feature/gpuux-1 -- reaper.py` after C1; reviewer S1 lens ddia ch-8; tests from both sides must pass |
| fix3 lane rewrites files outside its write set | `touched_files` check + codemap `detect_changes`; out-of-set edits → finding, lane re-run |
| Remote lane cap 3600 s exceeded on C2 | Split C2 into C2a (Makefile/BR-01/04) and C2b (reaper/BR-02) — same colour class, serial |
| `npx vitest` lacks `gpuStatePresentation.test.ts` at RED | Expected: RED = missing test file fails; lane creates it first (tdd step 2) |
| Review rounds exceed 2 | Stop, record blocker, report; no `enforce=False` |
| GPU not STOPPED after smoke | §7 |

## 9. Reviewer checklist (approve / amend)

1. Order OCIRV-1 → GPUUX-1 sync (Makefile serialisation) — accept?
2. Close duxw2 step/orient/copy lanes as landed (evidence: `vmgate/feature/duxw2-integration` 0 ahead of main) — accept?
3. Backend switch for lane 993 from grok-remote to codex-remote — accept?
4. W4 width 3 concurrent codex-remote lanes — within VM budget?
5. Reviewer mix per slice (codex/grok/cursor remote + 1 local) — accept?
6. §6 GPUPROC-1 scope: approve P1–P5 for a follow-up plan, or trim (e.g. drop hover pre-warm, keep explicit button)?
7. H2 live smoke authorisation: confirm env values will be provided at W8 (not stored in repo).
