# LAND-1 continuation: landing inflight GPU work

## Intended outcome

One bounded image-description burst from `demo.altcontext.com`, using the deployed incumbent model, with evidence connecting the browser result to OCI provisioning, RUNNING, completion, STOPPED, and the metered interval. Repository integration and successful deployment are separate acceptance claims.

### Active goal clarification and live evidence

The user subsequently explicitly requested Qwen 30B and activated a persistent goal. Do not substitute the current Florence adapter or evidence-tool completion for that goal. The exact browser entrypoint is awaiting clarification: anonymous public picker versus signed-in guided celebrity-image UI.

Read-only live observations, 2026-09-08 approximately 06:43–06:47 UTC:

| Boundary | Observed evidence | Required next state |
| --- | --- | --- |
| Producer health | `/health` 200, commit `73264a126`, `image_variant=recognition`; `/ready` 503, centroid typmod `-1` | Reviewed VLMHEAL repair and healthy intended producer deployment |
| Model profile | Running API `ACX_DESCRIPTION_ADAPTER=florence_small` | Verified `gpu_qwen30b` profile and actual model identity |
| GPU wake-up | `acx-gpu-start.timer` inactive and disabled | Reviewed, bounded start policy activated through operational gate |
| GPU shutdown | `acx-gpu-reap.timer` active and enabled | Verify effective target, maximum lease and final STOPPED receipt; timer status alone is insufficient |
| GPU endpoint | Configured private endpoint `/health` connection timed out | Reachable model-ready service after authorized activation |
| Anonymous UI | WordPress `acx_public_demo_enabled=false`, allowlist empty; public pages list only Sample Page | Confirm target UI; do not implicitly publish anonymous paid inference or select an image allowlist |
| Browser deadline | Explicit 120-second ceiling introduced by `2c7bd0bca`; server returns warm-up + inference budget | Adjudicate UX policy; do not simply remove an intentional tested ceiling |

Claude acknowledgment `9382` reserves GUIDEDQM admin UI and VLMHEAL producer repair paths; Codex owns public-demo/GPU lifecycle boundary investigation and EVID. No peer main merge or deployment occurs without coordination. Findings `GPU-LIVE-CONFIG-01` and `GPU-LIVE-PUBLIC-01` record the live prerequisites. The user deferred upstream agent-messaging feature assessment until later.

```text
Claude VLMHEAL repair + deployment gate ----+
Codex GPU profile/start/reap preflight -----+--> authorized producer activation
UI target + reviewed UI/artifact ----------+--> consumer publication
EVID reviewed checker/exporter ------------+--> real browser Qwen burst -> STOPPED evidence
```

These are acceptance dependencies, not permission to bypass the operational gate. LAND/reaper cleanup is secondary to this active GPU goal.

## Evidence baseline

Inventory target: `main` at `e37428d805e4ef978957c22a6f00978559a6f67f`.
Continuation: `cont-20260907T202646663744Z-9393124b`, task LAND-1, lane `land-1-reap-tool`.
Load by packet ID or lane scope; task-only lookup returns no packet.

The initial inventory contained 20 clean worktrees. Recompute before any mutation; new execution lanes are not part of that historical count.

| Component | Commit evidence | Treatment |
| --- | --- | --- |
| GPUOPS-1 | `c97a6addc29079431d69bdd04c7ee251aeb6539c` is an ancestor of main | Do not reimplement or merge again |
| GPU SPA | `dd25030fc77a9090cd8fe254bd0f3317a772d356` is an ancestor of main | Remove old SPA fix from queue |
| GPU public API | `417fd940de97b247c8d8e0e72fca41fa9ceb5287` is an ancestor of main | Remove old API fix from queue |
| GPU subsidiary work | cx1, cx2, fix-intent, fix-process, gid, journal, svcintent, review/gpuops-1 all have zero ahead commits | Reconcile ownership rows only after activity checks |
| Warm-start fix | `22ec2c0e2fd8df4b33326d84e0f8d8aa7ca7ae97` is an ancestor of main | Do not reimplement |
| EVID-1 | `95e413f79f3e067996827a92f703a7232e907707`: 33 ahead commits, 21 cherry-plus patches | Complete residual fixes and gate the parent union |
| LAND-1 | `64b844dbf9456308ecdb41f955a4bd790db5174c`: 18 ahead commits, 15 cherry-plus patches | Gate existing reaper and landing protocol |

Both remaining parent branches passed `git merge-tree --write-tree main <branch>` without conflicts. This is mergeability evidence, not test or semantic correctness evidence. Subsidiary EVID/LAND branches are subsets of their parent unions; they must not be landed independently a second time.

Codemap confirms `post_gpu_intent` derives `requested_by` from the authenticated principal, and locates durable intent and the decomposed lifecycle cycles in main. Coverage metadata matches those files. Main has neither `scripts/worktree_reap.py` nor `scripts/gpu_burst_evidence.py`; read their branch sources explicitly. Semantic reinjection returned `embeddings_mode=verified`, `semantic_degrade_reason=null`; similarity supplies prior-art candidates, never proof of landedness (GRPH-36).

## Work decomposition

Existing finding records remain authoritative in MCP. Route EVID1F-M-04 to the checker lane; EVID1F-M-07/M-09 to exporter; EVID1F-L-05/L-06/L-09 to docs. L-06 and L-09 describe the same change and receive one implementation plus separate evidence-backed dispositions.

| Node | Owned output | Verification |
| --- | --- | --- |
| C checker | `scripts/gpu_burst_evidence.py`, `scripts/test_gpu_burst_evidence.py` | Recorded RED for nested unlisted manifest, then scoped pytest GREEN |
| E exporter | `scripts/deploy/lib/export-gpu-evidence.sh`, its two shell-test files | Recorded RED for outside-repo invocation and decimal 08/010, then mocked-OCI GREEN |
| D documentation | `docs/runbooks/gpu-evidence-capture.md`, exporter brief | Verify commands exist, query-string wording matches exporter, diff check |
| L LAND gate | Existing reaper/plan candidate plus review receipts | Current-SHA reaper tests, adversarial review, bounded remote gate, enforced close check |
| U deployed inventory | Deployment SHA, model ID, unit config, UI states | Read-only inspection; no inference from repository configuration alone |

C, E, and D have disjoint write sets and consume the same EVID parent snapshot. They form an independent set in the conflict graph. The original evidence and fix lanes are predecessor producers because their commits are in that snapshot. No sibling waits for another sibling's patch.

```text
C checker ----+
E exporter ---+--> ER1 / ER2 / ER3 --> EVID gate --> EVID intake --+
D docs -------+                                                 |
                                                               +--> row reconciliation --> reap preview
L LAND review ---------------------> LAND gate --> LAND intake -+

U deployed inventory + both required release artifacts
    --> deployment convergence --> live burst --> evidence verdict
```

ER1 examines failure containment; ER2 test integrity and audit completeness; ER3 boundary/schema consistency. Use remote Grok reviewers. Permit at most one local reviewer across the coordinated merge gate. Review refs contain task, date, commit prefix and lens; findings merge into the owning task with source retirement. Feed each reviewer a slice packet, exact diff, codemap coverage notes, and `semantic_reinjection_packet(anchor_texts=...)` output. Finish slice-mode rounds with an integration-only harmonization review.

The main-ref lock and shared remote test gate are resource constraints, not fabricated data dependencies (GRPH-32). Queue root mutations, re-read HEAD and recompute the candidate after every intake. A failed EVID gate does not prevent independent LAND preparation. Schedule ready work by longest remaining chain (GRPH-31), bounded by actual admission rather than a claimed optimal worker count.

## Execution protocol

### Checkpoint and peer coordination (2026-09-08 06:11 UTC)

- Checker commit `92cbae7f7` is preserved on its execution branch; remote self-verification passed 83 tests. Its smoke review failed, so this is not a merge approval. Raw reviewer claims were harvested as `EVID1-R5-AUDIT-01` through `04` and await producer-contract adjudication. Do not repeat the original nested-manifest implementation.
- Exporter checkpoint `5923d2667a183e234e69260ef504f4b06b397ed9` passed its scoped verification. Resume pass `evid1-exporter-r5-20260908-pass3` uses the original continuation dispatch; docs pass `evid1-docs-r5-20260908-pass4` remains in flight.
- The single local LAND reviewer returned FAIL. Five findings `LAND-1-REV-A-01` through `05` were merged into LAND-1 with scratch-source retirement. Resolve ownership fencing, unverified/malformed ownership handling, and command behavior before attempting its gate again. A last-moment registry reread is not assumed to eliminate a concurrent-upsert race; verify the actual synchronization contract.
- Claude's VLM deployment / GUIDEDQM session was identified at cmux workspace:2 surface:4. An attributed message proposes separate ownership (Codex LAND/EVID; Claude deployment/UI) and explicit coordination before shared-main merges. Delivery is visible in the queued-message area; acknowledgment is pending. Peer deployment rollback output is not independent production verification. Decision `9366` records the exchange.

### Required lifecycle steps

1. Preserve dirty or active peer work. Capture exact refs, worktree status, lane activity, findings and current test receipts before each landing decision.
2. Dispatch implementation to `grok-remote`, model `grok-4.6`, high reasoning. Use xhigh only if the adapter accepts it. No Grok fast-tier field is exposed. Current preflight requires at least 120000 advisory tokens and gives 30 turns/900 seconds; actual token telemetry is unavailable, so time and turns are the enforceable bounds.
3. Apply `/wb-tdd` and `/wb-implement` to C/E: intended RED before production edits, minimal GREEN, bounded smoke review, committed scoped output. Documentation requires evidence checks, not artificial tests mirroring text.
4. Harvest by typed outcome and actual commits/tests. `commit_landed=true` means lane output exists, not that main changed. A startup statement, empty patch, no tests, or `merge_ready` prose alone cannot pass.
5. Intake reviewed lane changes into the owning parent, rerun affected checks at its new SHA, then conduct the adversarial merge gate. Retain current-SHA remote logs and enforce `handoff_close_check`; accept the LAND plan baseline before its final lifecycle gate.
6. Merge each accepted parent under the root-ref lock. Prove ancestry afterward. Reconcile only completed inactive lane rows, read back exact statuses, then preview the reaper. Preserve archive/rollback evidence and revalidate cleanliness and tips immediately before any approved deletion.
7. Inspect the deployed incumbent model; do not switch to Qwen 30B merely because it appeared in an earlier plan. Confirm image/model digest, GPU readiness, start/reap units, durable intent, lease and warm-up budgets, and observability against deployment SHA.
8. Perform live provisioning or start/stop only with the concrete operational authorization required by the existing continuation. Capture a bounded browser run and OCI receipts. Successful HTTP, a submitted job, and STOP requested are insufficient: prove description output and final OCI STOPPED. Correlate instance identity, request/run ID, timestamps and successful audit actions. A stopped VM does not by itself prove zero storage or ancillary charges.

## UI inventory for verification

Reuse `docs/ux-maps/public-demo-describe.md` and the guided-prototype map; validate a `.uxmap.json` with Design Canvas before proposing UI changes. Public input is the configured image picker, not an upload or arbitrary URL form.

```text
+-- Describe an image -----------------------------------+
| ( ) Garden       ( ) Lake       ( ) Street             |
| [ Describe selected image ]                           |
| Select -> Warming -> Describing -> Description result  |
|           |             |                             |
|           +-> Limited / Error / Deadline reached       |
+-------------------------------------------------------+
```

Check keyboard selection, focus on result, live status announcements, disabled controls during an active run, recovery after errors, and truthful deadline wording. A browser timeout must not imply backend cancellation or invite duplicate paid work.

## Canon and acceptance

Consult the current [heuristics canon](https://github.com/darce/heuristics-canon) and local `heuristics-canon-research` corpus. DDIA chapters 8/11/12 ground fencing, durable intent and reconstructable evidence. Release It stability patterns ground bounded waits, circuit breakers, bulkheads and steady-state cleanup. Latency chapters 1/2 ground warm-up feedback, end-to-end deadlines and percentile measurement. GRPH-01/06/09/14/31/32/36 distinguish dependency order, independence, interference and evidence from similarity.

Completion requires the parent commits on main, current-SHA passing gate receipts, truthful terminal task/lane state, a reviewed reclamation inventory, and a real deployed burst evidence verdict. Until then, record exact blockers and continuation IDs; never convert absent events or absent verification into success.
