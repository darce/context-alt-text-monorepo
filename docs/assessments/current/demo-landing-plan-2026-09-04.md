# Repository landing plan: browser-triggered burst GPU demo

Date: 2026-09-04. Status: evidence-grounded draft; not a merge or deployment approval.
Target: demo.altcontext.com can describe a curated image from the web UI, start the GPU on demand, return a real GPU result, and stop paid GPU compute after the burst.

## Current state and evidence boundaries

- Root main: `b2437345851066c8d3d14177e914fc4d48182a24`. Live `git ls-remote origin refs/heads/main` returned `6d68eea0437b883aa7e21a67e4ba003f664789ab`: local main is two commits ahead. Publishing main is a deployment boundary because deploy-recognition has a push trigger.
- Census: 17 worktrees including root, 26 local branches including main, 93 locally known remote-tracking refs; 36 remote-tracking refs are not ancestors of main. Complete paths, SHAs, ancestry counts, and dirt are in [the inventory](demo-landing-inventory-2026-09-04.json). Other remotes were not fetched; their refs are historical evidence, not proof of current remote state.
- All 16 linked worktrees were clean at observation. Root has existing changes to `.codex/config.toml`, `.mcp.json`, `apps/prototype-description-service/Caddyfile`, and an untracked supertab research document. The Caddy change adds an unrelated download redirect. Preserve and assign these independently of demo release work.
- HTTPS HEAD on demo.altcontext.com returned 200 at 21:50 UTC. This proves reachability only. No image request, cloud mutation, or live GPU smoke was performed. Deployed image identity, effective adapter configuration, timer health, and current OCI power state remain unverified.
- Semantic retrieval succeeded: `embeddings_mode=verified`, `semantic_degrade_reason=null`, model `gte-base-en-v1.5`; both related-prior-work and DEMOLAND semantic reinjection were consumed. Historical semantic hits are leads, not current defects.
- Codemap project `Users-daniel-Development-context-alt-text-monorepo` responds: 60,518 nodes / 222,746 edges, full index generation 2026-09-04T20:53:34Z. Named application/lifecycle anchors below have matching coverage metadata. `scripts/deploy/` is excluded, so installer/workflow configuration was read directly. The duplicate shorter project name has an older graph; do not interchange them. Recheck branch-specific coverage when examining new lane changes.
- Doctor reported handoff and codemap probe timeouts, even though direct MCP and subsequent CLI reads worked. It also reported memory pressure (heavy dispatch refused), projection backlog, and stale findings. Treat this as a CLI/probe and evidence-integrity issue, not proof that embeddings or all graph access are down. Use explicit task refs; no broad task reaping.
- GPUUX-1, OCIRV-1, WBUX-6, FEBT-1/G1, FEBT-2, LINTGATE-1 and WAVEPLAN-1 were already integrated/closed according to current handoff history. Verify Git before reopening any old packet instruction. GPUSMOKE code is present on main, but its old plan's unchecked boxes do not establish current live proof.

## Existing flow to preserve

```text
Browser -> WP describe controller -> backend describe run -> durable queued work
  -> describe_load.load_snapshot / dump_load_snapshot
  -> host start timer -> reaper.run_start_cycle -> OCI START
  -> describe_run_worker._wait_for_gpu_ready -> GPU inference -> result/provenance
  -> drained load -> host reap timer -> reaper.run_reap_cycle -> OCI STOP
  -> read_gpu_state -> WP response -> UI state/toasts
```

Verified anchors:

- `apps/prototype-wp-alt-context/src/api/class-describe-controller.php:DescribeController`: existing admin describe boundary; preserve its permissions.
- `apps/prototype-description-service/scene/application/describe_load.py:load_snapshot` (line 153): single queued/running counts plus separate `batch_in_progress`; do not mistake exclusion of bulk items from the two counters for exclusion of bulk work.
- `apps/prototype-description-service/scene/application/describe_run_worker.py:_wait_for_gpu_ready` (line 149): bounded health polling with cancellation and remaining-deadline enforcement.
- `infra/oci/gpu_lifecycle/reaper.py:run_start_cycle` (line 1379), `run_reap_cycle` (line 1174): existing actuators and state publication. Codemap trace confirms start-cycle calls into the controller path and snapshot writers.
- `apps/prototype-description-service/scene/application/gpu_state.py:read_gpu_state` (line 97), `apps/prototype-wp-alt-context/js/admin/hooks/useGpuStateToasts.ts`: existing state readers/UI surface.
- `scripts/deploy/gpu-lifecycle-install.sh`: current explicit installer; defaults are start every 30s, reap every 2min, idle 300s, max lease 3600s. These are configured defaults, not measured stopping guarantees.
- `scripts/gpu_burst_smoke.py`, root `Makefile:gpu-burst-smoke` and `gpu-burst-smoke-live`: reuse existing proof machinery. Current live Make target has a 1200-second budget and authenticated WP parameters; it is not an anonymous browser test.

## Landing sequence

### 1. Establish trustworthy intake and preserve every work product

1. Refresh census and lane receipts before acting: DEMOLAND and FIXWAVE were dispatched already. Their local branches had no new returned implementation commits at observation. Do not duplicate dispatch merely because a local tip has not advanced.
2. Recover existing remote result artifacts and terminal statuses. Missing `off_box_self_verify` or `no_findings_block` is unknown evidence, never green. Decision 8009 already rescued three review panels; reuse that work.
3. Fix or work around the upstream worker exit-status/evidence-capture defect with an explicit pinned-SHA verification route. D5-RR-01 lives in the WorkBay engine, not this repo's wrappers. A tested independent verification receipt can unblock intake; do not wait indefinitely on upstream or bypass exit checks.
4. Address the actual formatting regressions separately from rejected D1. Reproduce the reported 302-vs-296 ratchet state on the current candidate; format only proven regressions and lower the baseline only if measured. Do not merge the regex collector or increase allowances.
5. Reconcile pending projection events before accepting lifecycle close receipts. Preserve stale rows until their branch, task, and evidence are reconciled; never bulk-close active tasks to resolve root ambiguity.
6. Prepare branch-preservation refs/bundles and a disposition ledger before any later teardown. This planning session deletes nothing. Older packets include explicit branch-retention constraints; use preservation plus lifecycle closure, with deletion only where current authorization is clear.

Exit: reproducible intake checks, terminal lane outcomes, captured source SHAs, root edits accounted for, no lost untracked/report work.

### 2. Integrate the demo lanes and gate repairs together

Use a dedicated integration candidate based on current main. Preserve lane ownership while workers are active. Stage merges serially, then test the combined SHA before publishing main.

| Order | Branch/worktree group | Action and exit condition |
| --- | --- | --- |
| A | `feature/demoland-1-g6` | Complete/review adapter/env preflight and flip runbook. Validate effective config across WP, API, worker, lifecycle reader/writer paths, not just template text. Required secrets are checked without echoing values. |
| B | `feature/demoland-1-g3` | Complete/review deploy-installed start/reap timers and verified enable/active state. Verify installed service invocations, credentials, instance scope, snapshot directories, and reaper execution. Provisioning must not create uncontrolled demand or start a GPU without queued work. |
| C | `feature/fixwave-1-d5` (contains original D5) | Close residual shell/SSH exit masking with behavioral failure injection. Integrate with G3 because both touch deployment-gate expectations. Remove the temporary strict xfail for G3 when G3 lands; combined release gate must have no ownership-based exception. Split unrelated artifact-cache work into a reviewable commit if retained. |
| D | `feature/defwave-1-d3-leak`, `feature/defwave-1-d4-errcodes` | Independently review and capture actual passing tests on each candidate. Handoff blockers 349/348 currently report absent self-verification. D3 is the error-boundary leak lane; D4 is typed UI error handling. Reconcile their error contract with the public route. |
| E | `feature/fixwave-1-d2` (contains original D2) | Restore unique UX-map content, generated render parity, typed domain-state mapping, and a mutation test that detects semantic drift. Resolve both D2-RR and D2-AR findings; green substring tests are insufficient. |
| F | `feature/demoland-1-g1` | Complete/review curated public image selection, explicit Describe action, durable run status/results, and paid-work admission limits. Reuse the admin pipeline internally without weakening admin authorization. Ship disabled until deployment checks pass. |

The existing DEMOLAND manifest orders G6 -> G3 -> G1. The combined sequence adds gate and error-contract prerequisites. G3 and D5 both name `scripts/test_deploy_workflow_gate.py` in their work descriptions: assign final conflict resolution explicitly even if manifest ownership lists look disjoint.

Before accepting G1, settle these contracts:

- A public nonce is not a spending quota or run-ownership token. Verify actual logged-out WordPress nonce behavior, cache handling, and access to run status/results. Use opaque, scoped run handles and prevent lookup of unrelated runs.
- Rate limits, daily budget and one-public-run concurrency must hold atomically under simultaneous requests and retries, not only sequential mocks. Define trusted client-IP handling, duplicate-submit idempotency, release on error/cancel, and lease expiry after a process crash.
- The brief's 120-second hard polling stop is shorter than the backend's 480-second default warm-up budget. Choose one documented end-to-end deadline covering start delay, readiness, inference and delivery. A UI timeout must retain a resumable run handle and must not silently leave paid work running.
- Public output needs explicit queued/starting/warming/ready/result/degraded/error states, accessible status updates, and honest GPU provenance. Never count a seeded caption or CPU draft as successful GPU completion.
- Confirm the public JS build/enqueue path, controller autoload, curated attachment deployment, and page creation are part of the deploy artifact. PHP unit tests alone cannot prove the browser has the JS or route.

Exit: all required fixes integrated, open findings dispositioned against current code, and deploy configuration tied to a single tested candidate SHA.

### 3. Prove the stop invariant before enabling public demand

The start timer and reaper must ship as one operational unit. A max-lease check inside a dead reaper does not bound charges.

Required behavior and evidence:

1. No demand: GPU remains STOPPED; merely viewing or polling the page cannot enqueue work or start it.
2. One accepted request: one durable run and bounded start attempt; readiness is verified before final GPU inference. A second simultaneous request respects the public concurrency limit.
3. Active work: no accidental idle stop while any environment has queued/in-flight/batch work; state files are fresh, readable, and aggregated over the configured deployment registry.
4. Completion/cancel/error: demand drains, automatic reaper issues STOP, then OCI reports STOPPED for the exact managed instance. Do not accept a successful STOP API response as the terminal-state proof.
5. Stop failure, stale load, stale lock holder, worker restart and reaper/service failure: bounded recovery and visible operator alert. Provide an independent cloud-side or separately hosted watchdog that can stop the managed GPU if the control host dies; otherwise explicitly retain that release blocker.
6. Bound cumulative paid work as well as one lease: a stuck queue must not repeatedly restart a GPU immediately after max-lease expiry. Failed runs become terminal or require explicit retry within quota.
7. Verify provider billing semantics for the actual shape and attached resources. Report measured running seconds and any retained storage/network charges separately; STOPPED must not be represented as zero total infrastructure cost without evidence.

Do not shorten safety fences merely to make a smoke test faster. Use the configured idle interval and a deadline that includes reaper cadence, API retry time, and power-state convergence.

### 4. Verify, deploy, and capture browser-to-STOPPED proof

Local/hermetic verification first, on the final integration SHA:

- `make check-all`, with the intended project interpreter/dependencies and unchanged ratchet policy.
- `make test-deploy-contract` plus the new G3/G6 tests and `scripts/deploy/tests` coverage. Verify every actual CI/SSH runner propagates failure.
- `make test-gpu-lifecycle` and `make gpu-burst-smoke` (dry-run).
- Scene tests for load publication, readiness/cancellation and GPU worker behavior; PHPUnit/Vitest suites for public admission and polling; targeted D2/D3/D4/D5 tests named in lane manifests.
- Browser integration: anonymous curated request, progress, final caption, repeat-click/reload, denial and recovery. Test the same production-built assets that will deploy.

Record command, exit code, collection counts, environment, exact SHA and review verdict. Existing GPUUX test receipts (including 3822 passed on its earlier branch) are useful history, not acceptance of this integration.

Deployment sequence:

1. Resolve root dirty configuration separately. Confirm rollback image digests and effective environment snapshots, with secrets redacted.
2. Promote the tested backend/plugin/config combination. Verify DNS/TLS, routing, tenant/API credentials and snapshot bind mounts. If lifecycle install is optional in workflow_dispatch, make it a required verified prerequisite whenever the GPU adapter/public demo is enabled; an optional input alone cannot enforce the invariant for push deploys.
3. Verify timers and watchdog on the real host, initial GPU STOPPED, pinned model and health/readiness endpoint. Keep public admission off until these pass.
4. Run the existing authenticated live smoke in the intended demo environment, then a real browser run against demo.altcontext.com. The old GPUSMOKE plan scoped its proof to dev/staging; do not substitute that for demo acceptance.
5. Capture: deployed commit/digests; browser request/run ID; initial STOPPED; START and readiness times; final GPU tier/model revision/non-fixture caption; load drain; automatic STOPPED; measured running duration; cleanup outcome. Repeat once after idle shutdown to prove a second cold burst.
6. Exercise cancellation/rejected demand and verify no leaked run or extra GPU. Live checks are a separate execution step requiring the applicable spend/deployment authorization; this plan does not start cloud resources.
7. If any step fails, disable new public requests, cancel/drain existing work, ensure STOPPED, then roll back the app/config. Leave the reaper/watchdog operational while any GPU may still be running. A cleanup `finally` STOP is necessary, but must not hide failure of automatic idle shutdown.

Release exit: an anonymous visitor can trigger the intended demo flow, real GPU descriptions return, and automatic post-burst shutdown is evidenced twice. No unresolved stop/cost, admission, tenant-boundary or exit-masking blocker remains.

## Disposition of every remaining local branch

The preceding table accounts for seven implementation lanes (G1/G3/G6, FIX D2/D5, original D3/D4). Original D2/D5 ancestors are dispositioned below. The following table completes the census; use the inventory for exact full paths/SHAs.

| Branch/group | Disposition |
| --- | --- |
| `main` | Preserve unrelated dirt; publish only after deployment prerequisites are satisfied. |
| `feature/defwave-1` | Already contained in main, two commits behind. Coordinator bookkeeping; no code to merge. |
| `feature/defwave-1-d1-lintratchet`, `review/defwave-1-d1` | Reject proposed parser change per decision 8009 and D1 reviews. Preserve report/commit provenance; salvage only independently verified formatting drift. |
| `feature/defwave-1-d2-uxmap`, `review/defwave-1-d2` | Superseded by corrected FIXWAVE D2. Do not separately merge the rejected original. |
| `feature/defwave-1-d5-gatewrap`, `review/defwave-1-d5` | Superseded by corrected FIXWAVE D5. Keep review evidence; do not merge twice. |
| `feature/ocirrev-1` | Two commits ahead of main. Review and retain/admit the docs-only 87-hunk adjudication, then reconcile handoff. Decision 8009 says "landed c86ccfe3c", but Git proves it is not on main at this snapshot. |
| `feature/ocirv-1-rev-ops` | Historical report/patch material, 318 behind / 3 ahead. OCIRREV classifies all 87 hunks with zero still-novel changes. Confirm report/finding preservation; do not merge obsolete runtime patches wholesale. |
| `feature/cmap-1` | One unique commit, 1928 behind, five hook/config files. Compare against the currently functioning codemap-first setup; port only missing compatible guard behavior after demo. Coordinate with dirty root tool configs. |
| `feature/corpus-1` | Two unique commits, 789 behind, three corpus recipe/spec files. Restore a task worktree, validate recovery behavior and source/licensing requirements, then land or explicitly disposition. Corpus acquisition need not block the curated demo. |
| `feature/vlm-6` | 329 ahead / 789 behind, 221 changed paths. Resume its continuation and unresolved measurement/encoding findings; stage on a new integration candidate, not directly on release main. |
| `lane/l11-rescue` | 350 ahead / 789 behind, 258 paths. Contains evalsurf-1 but does NOT contain current vlm-6. Compare both sides and preserve unique rescue/report/lockfile work; never assume it replaces VLM-6. |
| `feature/vlm6-lex` | Five unique commits, 790 behind. Not contained in VLM-6. Reconcile lexicon/bakeoff schema and lockfile against the selected VLM/rescue combination; regenerate locks with pinned tooling instead of choosing one side. |
| `feature/evalsurf-1` | One unique commit, 790 behind; already contained in l11-rescue. Integrate exactly once through the chosen evaluation candidate, reconciling current Make targets. |
| `feature/fir-12` | 87 ahead / 790 behind. Contains fir12-r7-int; reconcile with DESCQUAL-2 in one candidate as required by FIR-12 continuation. Validate shared thresholds, manifests and full evaluation collection together. |
| `feature/fir12-r7-int` | 81 ahead / 790 behind; ancestor of fir-12. Preserve lane evidence, no independent duplicate merge. |
| `feature/descqual-2` | 62 ahead / 790 behind. Rebase/merge into the FIR-12 candidate; validate reference-fact lineage, audit sampling and shared manifest behavior. Historical five-failure reports need current disposition, not an exemption. |

Counts above are commit reachability, not independent semantic changes. `git cherry main` found no patch-equivalent commits in the nine legacy branch tips inspected, but that does not prove their behavior is absent from rewritten main code.

Legacy landing order: preserve all tips -> compare VLM/rescue/lex/evalsurf -> one validated VLM candidate -> FIR-12 + DESCQUAL-2 combined candidate -> corpus recipe/spec and compatible CMAP salvage. Adjust only for concrete shared-file/API dependencies found during integration. Each candidate gets fresh tests/review; do not import obsolete assertions, whole lockfiles, or old generated reports merely to eliminate branch count.

For all 93 remote-tracking refs, classify by containment and by patch/report novelty against the selected candidates. The 36 uncontained refs may include child lanes and old import bundles. Record retained, integrated or superseded status per ref; refresh relevant upstreams read-only before declaring coverage complete. No blanket fetch-prune, branch deletion, or worktree removal. Final all-work closure requires every inventoried ref to have an evidence-backed disposition, even where the disposition is preservation rather than merger.

## Handoff and continuation lineage

Resume through the public CLI with an explicit task ref, for example:

```bash
mcp-workbay-handoff load-session MAINT-branch-landing-20260904 --read-profile hot_summary
mcp-workbay-handoff continuation --operation load --task-ref MAINT-branch-landing-20260904
```

Consumed continuation IDs (older actions are subordinate to current Git/evidence):

| Task | Packet |
| --- | --- |
| MAINT-branch-teardown-audit-20260903 | `cont-20260903T175233376245Z-836f3ff6` (prior `cont-20260903T163003155717Z-9346180e`) |
| GPUUX-1 | `cont-20260903T221403234588Z-faf3b165` |
| GPUSMOKE-1 | `cont-20260903T062958447073Z-97c5b034` |
| OCIRV-1 | `cont-20260902T190622452784Z-03556428` |
| FEBT-1 | `cont-20260903T015444969762Z-230e7e12` |
| VLM-6 | `cont-20260819T212338900397Z-6ab70ed2` |
| FIR-12 | `cont-20260820T170149332466Z-e89c38e0` |

At load time DEMOLAND-1, FIXWAVE-1, DEFWAVE-1 and MAINT-branch-landing-20260904 had no continuation packet. Their current dispatch decisions/manifests are the operational context: 8005/8006 (DEMOLAND), 8007/8008 (FIXWAVE), and 8009 (review rescue/dispositions). Save this plan's continuation under MAINT-branch-landing-20260904 without switching or closing peer tasks. The packet must name this plan, inventory, current SHA, source packet IDs, next gate, and unverified live state.

After each future intake: refresh branch/task alignment, record tests and findings on the tested SHA, save a new continuation, and render the dashboard. Mark completion only after evidence is on the destination branch. This plan does not claim formal planning-review acceptance or successful deployment.

New plan handoff receipt: decision `8020` (`codex_demo_landing_plan_20260904`); continuation `cont-20260904T215700656619Z-a32e207f`, source row `94`, task `MAINT-branch-landing-20260904`. The CLI inherited the existing task actor label for decision 8020; its session/key identifies this Codex planning turn.
