# Task Plan — BAKECACHE-1 owned cache executor and memory collector

> **Metadata**
>
> - **Date**: 2026-10-17
> - **Status**: implementation-ready proposal; implementation and target admission not performed
> - **Project**: apps/prototype-description-service
> - **Task ID**: `BAKECACHE-1`
> - **Target Branch**: `feature/bakecache-1-owned-cache-executor`
> - **Review Coverage Target**: 2
> - **Source**: snapshot `b2e0c98458023fb8864e1ff5a434765c691f902c`, tree `41b684a04dda562adbc01e564b2a0b6f2139d8f2`
> - **Research readiness**: **NOT_READY** throughout this task

## Objective and authority

Add the smallest owned single-model cache/lifecycle boundary around the existing bake-off runner, plus a concurrent memory collector. Deliver deterministic CPU/filesystem/process fixture evidence first. Actual model downloads, GPU runs, target admission and research protocol approval are separate operations. This plan does not authorize those operations, new model selection, new metric thresholds or promotion. Current native remote execution is the authorized Codex worker; no nested dispatch is needed for this document.

The [operator reference](../../../benchmarks/experiments/rounds-20261017/accepted-packet.md) describes missing requirements; it is informational, not an implementation task plan. This document supplies the contracts, file ownership, RED cases and implementation slices. Preserve every sealed registry revision, quant, eligibility and runtime bound; selection10, report20 and regression37 retain their distinct roles. Do not redraw fixtures, infer GPU fit from disk bytes, change baselines or manually create published score markers. The four required baseline labels and actual incumbent/report comparability gates remain unchanged.

Use canon **v0.26.2**, specifically the exact supplied rule rows, with [upstream source](https://github.com/darce/heuristics-canon). Do not replace this pin with another cached release. Rule citations below give actual names and bibliography sources at the decisions they govern; they are design guidance, not additional research gates.

## Grounded current seams

All application paths in this document are relative to `apps/prototype-description-service/` unless rooted at `docs/`.

| Verified path / symbol | Current contract and resulting change |
| --- | --- |
| `scripts/eval_harness/bakeoff_runner.py:119 CandidatePlan`, `:135 build_plans`, `:519 _plan_candidate` | Frozen serve/run argv, revision and output path. Planner supports competing llama.cpp only; keep other stacks and incumbents' current refusal behavior. Never invent vLLM/Transformers recipes. Add an explicit owned execution mode, not an alternate ranking framework. |
| `bakeoff_runner.py:254 _emit_ready_run_lines` | Fetch → score → marker only on both successes; preserves existing scorer semantics. Reuse this action generator inside the owned lifecycle. |
| `bakeoff_runner.py:280 emit_shell` | Download is a comment; EXIT trap kills/waits only the last PID, suppresses errors. Lines 352–354 remove prior run/marker; 368–370 kill/wait PID, not a process group or cache. Add owned-mode delegation before these legacy statements; never run them against published outputs. |
| `bakeoff_runner.py:232 _emit_ready_poll_lines`, `:608 _emit_runtime_build_preflight` | Existing readiness and runtime-bound policy. Keep build-bound semantics and serve-to-ready window; owned executor must enforce a monotonic deadline including each poll, and record build preflight outcome. |
| `bakeoff_runner.py:680 _score_argv`, `:793 _emit_report_lines` | Reuse scoring and report roster/baseline wiring; no manual score-marker shortcut. Separate lifecycle receipts from quality verdicts. |
| `scripts/eval_harness/prepull_weights.py:plan_downloads`, `already_present`, `check_disk_budget`, `run_downloads` | Existing reusable argv planning; presence is ≥90% declared size, not local hash verification. Budget is sum of missing estimated jobs plus margin, not a one-slot reservation. Do not treat these helpers as ownership, completeness or integrity proof; use explicit verified inventory in owned mode. |
| `scripts/eval_harness/bakeoff.py:1479 build_parser`, `:1651 main` | Accepts explicit output and model revision. `_plan_candidate` currently omits `--model-revision`; owned mode must pass the verified revision without changing pins. Main always creates module `out`, starts sampler at 1787 after ready, and calls `prune_out_dir` at 1874 even with custom `--out`. Add scoped output-root/no-prune behavior for owned mode so it never prunes historical module outputs. |
| `scripts/eval_harness/bench_capture.py:143 VramSampler` | Post-ready sampled device aggregate, sum of returned GPU rows; no owned PID filtering. Keep historical semantics. New collector is a lifecycle sidecar, not a reinterpretation of these fields. |
| `scripts/eval_harness/cli.py:821 prune_out_dir` | Deletes timestamp-grouped run artifacts. Owned mode must never invoke this on an existing shared output root. Scorer output side effects must be constrained to new attempt directory and tested. |
| `scene/tests/test_eval_harness_bakeoff_runner.py` | Existing exact tests include `test_emit_shell_is_bash_n_clean_and_mentions_incumbents` (asserts legacy deletion), `test_emit_shell_download_hint_includes_artifacts`, `test_emit_shell_runtime_preflight_failure_is_nonfatal_per_candidate`, readiness/cold-stamp tests. Keep legacy tests; owned-mode behavior gets separate cases. |

The supplied 254–277 / 280–394 anchors are correct in this snapshot. There is no verified existing cache executor or concurrent owned-memory symbol to reuse. Any names introduced below are **proposed**, not claims of shipped APIs. Old task-plan references to `docs/workbay/rules/development-workflow.md` are stale (file absent); do not make that path a dispatch prerequisite. The existing Python test conventions are in `docs/workbay/rules/testing-python.md`.

## Files, ownership groups and compatibility

| Group | Future owned files | Responsibility |
| --- | --- | --- |
| C — cache | NEW `scripts/eval_harness/owned_cache.py`; NEW `scene/tests/test_eval_harness_owned_cache.py` | Inventory validation, lease, reservations, no-follow file operations, owned inactive cleanup, byte receipts. No process discovery or scoring. |
| M — collector | NEW `scripts/eval_harness/owned_memory.py`; NEW `scene/tests/test_eval_harness_owned_memory.py` | Injected proc/device readers, identity-bound concurrent sampling, explicit scopes/unavailable reasons. No deletion, model fetching or marker writes. |
| E — integration | NEW `scripts/eval_harness/owned_executor.py`; NEW `scene/tests/test_eval_harness_owned_executor.py`; existing `bakeoff_runner.py`, `bakeoff.py`, `test_eval_harness_bakeoff_runner.py`; scoped cases in existing bakeoff tests | Lifecycle, process supervision, owned-mode CLI/emission, output confinement and existing fetch/score/report reuse. E is sole writer of shared producer modules. |

C and M share no implementation files. Their interface specifications below are frozen inputs, not mutable shared test utilities. Keep fixtures local to each group's tests initially. E imports their public contracts after review. Do not change candidate registry, intake, manifest, scorer metrics, production adapters, OCI configuration or shared runtime environments. No new dependency is needed: use stdlib on Linux; explicitly refuse unsupported identity/locking platforms.

## Proposed machine contracts

Use versioned, strictly validated JSON sidecars (`bakecache-execution/v1`, `bakecache-receipt/v1`, `owned-memory/v1`); reject unknown fields/versions, nonfinite values, negative bytes and inconsistent references. Dataclasses plus explicit validation are enough; do not create a generic manifest platform. PROV-01, **Every output walks back to its evidence** ([Model Cards + AI Engineering](https://github.com/darce/heuristics-canon/blob/v0.26.2/SOURCES.md#src-model-cards)), applies to inventory/runtime/attempt references and collector provenance.

### Admission input (private, before mutation)

- `attempt_id`: generated random unique ID; `candidate_id`, exact `repo`, 40-character `revision`, `quant`, runtime executable digest/build, argv/config/context/vision recipe and source tree. Verify against current CandidatePlan; reject disagreements. Numeric minimum-build preflight is not immutable runtime identity or runtime qualification.
- `components[]`: complete closure of backbone/shards, projector, tokenizer/processor/config and other runtime-required files. Each has role, relative path, pinned source revision, exact byte count and expected SHA256 from an authoritative pinned manifest or verified primary listing. Require a completeness attestation with source; a downloader's observed checksum is not an expected hash. Missing any expected hash or completeness proof yields `INVENTORY_INCOMPLETE` before fetch. MiniCPM 4.6 stays blocked until its closure is supplied; never fabricate shards or use its listed small weight as whole-model size.
- `cache_root`, `output_root`, target filesystem identities, owner namespace and single slot key. Roots must be dedicated and disjoint in both ancestor directions, outside shared/user/production weights. Pre-existing unknown directory cannot become owned by writing a marker. Bootstrap only a new exclusive directory under an explicitly admitted dedicated parent; record uid/device/inode and random owner token. Token is an ownership aid, not authority to delete arbitrary paths.
- `target_admission`: actual target host and device UUID/partition, observed disk/RAM/VRAM, isolation/co-tenant status, CPU quota, runtime qualification reference, resource lock key and approved operation bounds. These may be absent for synthetic fixtures; real execution refuses absent evidence. Orchestration-host capacity is never substituted.
- `reservation`: integer `download_bytes`, `temporary_bytes`, `resident_cache_bytes`, `runtime_bytes`, `report_bytes`, `headroom_bytes` and per-filesystem allocation map. Sum simultaneously live allocations conservatively; avoid double-counting final downloaded bytes only with a documented storage-phase proof. Headroom is a required admitted value, not a new universal threshold. No estimate from `artifact_gb` satisfies this input.
- `bounds`: download, readiness, run, score, TERM grace, KILL/reap, device-unload and collector stop/query deadlines; sample interval and maximum diagnostic bytes. Every real blocking subprocess/lock/readiness loop has a finite bound. RES-02, **Timeout on every blocking call** ([Release It!, ch. 5](https://github.com/darce/heuristics-canon/blob/v0.26.2/SOURCES.md#src-release-it)), governs this contract.

### C: cache API and receipts

Proposed public operations: `validate_inventory(spec)`, `acquire_slot(spec)`, `reserve_bytes(lease, spec)`, `verify_components(lease, inventory)`, `cleanup_inactive(lease, exit_proof)`. Return typed records, not truthy shell strings.

Acquire one persistent slot lock with `flock(LOCK_EX|LOCK_NB)` and an open FD retained by the executor through cleanup/free-byte verification. Record `lease_id`, attempt, owner pid/start/boot identity, root device/inode and state; a stale marker never authorizes takeover or deletion. A second lane gets `LEASE_BUSY`; unknown/stale ownership gets `OWNERSHIP_UNKNOWN`, requiring scoped reconciliation without automatic steal. Downloads also run under supervision. Use an isolated owned staging directory and explicit cache/temp environment so a producer cannot write to default shared Hugging Face caches. Reuse planned download argv only after checking all destinations and dependencies; missing downloader yields `SUBPROCESS_MISSING`.

Validate every relative path: no absolute path, `..`, empty component, symlink, hard link (`st_nlink != 1`), special file or mount crossing. Open dedicated directories/files using dirfd-relative operations, `O_NOFOLLOW` and `fstat`; compare device/inode before reads/unlink and before final rename. A single `resolve()` prefix check is insufficient against replacement races. Reject unexpected files instead of recursive `rmtree`. Parent must not be writable by foreign actors; if identity changes, stop with `PATH_UNSAFE` and preserve it. Include adversarial replacement tests. Hash regular bytes from the validated open FD; verify exact size and expected digest before atomic staging→ready publication. Corrupt partials may be deleted only with creation-ledger ownership and stopped writer proof; unknown files are quarantined logically, never swept.

Reserve under the slot lock: record `statvfs` available-to-user bytes (`f_bavail * f_frsize`), filesystem IDs and admitted request; require free bytes ≥ summed phase reservation + headroom on each filesystem, with output reservation on its own device if different. A logical reservation excludes cooperating peers only; use actual allocated reservation files for temporary/runtime/report allowance where supported, account for released allocation as phase data is written, and recheck free/headroom before each phase. If allocation is unsupported or foreign writes invalidate it, fail closed (`RESERVATION_UNPROVEN` / `SPACE_INSUFFICIENT`), not a claim of guaranteed capacity. Do not use sparse-file length as physical reservation proof. No disk reservation proves RAM/VRAM capacity.

Receipt fields: `schema`, attempt/lease IDs, inventory reference, transition/state, per-device `before`, `after_download`, `before_cleanup`, `after_cleanup` free bytes with monotonic timestamps, requested/allocated/released reservation bytes, owned weight/partial byte totals removed, errors and `can_advance`. Free-space deltas are observations; other activity/filesystem allocation can change them. Do not assert delta equals logical file lengths or use `du` as free-space proof. Advance only if remeasured next-phase headroom is satisfied.

### M: concurrent owned collector API

Proposed `OwnedMemoryCollector(readers, clock, limits)` exposes `start(target_scope) -> armed_receipt`, `bind(process_identity)`, `mark(event)`, `stop() -> memory_receipt`. Start and acknowledge the reader loop **before** spawning the server. A launcher child waits behind a pipe barrier before `exec`; parent captures PID/start-time/boot-id/PGID/session identity, binds collector, takes an identity sample, then releases exec. This closes the quick-exit binding race; timestamps alone do not prove pre-load coverage. Failed spawn/exec remains a recorded outcome.

Track the owned session/process group and known descendants while alive, keyed by PID plus start time and boot identity, not `pgrep` or executable name. Revalidate before every sample/signal. Membership comes from `/proc` PGID/session identity; inaccessible `/proc`, PID reuse, escaped children, or unprovable membership produce explicit incomplete/unknown status. Prohibit daemonizing/detaching recipes in this initial executor; do not kill a name match to recover them. Proc traversal is read-only, with bounded overhead and no command-line/private-caption logging.

Record separately: (a) per-owned-process sampled RSS/HWM bytes and timestamps; (b) concurrent sum of sampled owned-group RSS, explicitly double-counting shared pages and subject to membership race; never sum independent HWM values as a simultaneous group peak; (c) target device usage keyed by stable UUID/partition, including foreign users; (d) owned-process GPU usage only when the backend exposes trustworthy PID/device allocation rows and identity correlation. Device aggregate minus baseline is not owned GPU allocation. MIG/unsupported per-process queries yield null plus reason. Preserve existing `VramSampler` fields unaltered; new sidecar fields cannot masquerade as its historical window.

Memory receipt: scope and units, backend/query identity, sample interval/requested and actual timestamps, first/last sample, event markers (armed/bound/exec/ready/run-start/run-end/TERM/reaped/unload), successful/missed/error counts, longest gap, CPU quota, target-device identity and per-field availability/reasons. Sample through load, readiness, warmup, inference and teardown, then final sample and bounded collector join. Samples are lower bounds on instantaneous peaks; a short-lived process or subprocess query interval can miss a peak. HWM may supply an OS-observed process lifetime peak but not a device or group instantaneous peak. Missing binary/query permission/zero samples is unavailable/null, never zero MB. Measured sampling coverage cannot certify first-token latency, KV allocation, cold filesystem/OS cache state or full cold GPU peak; these remain UNKNOWN unless an independent producer is later admitted. Serve-to-ready retains that exact name and poll/deadline uncertainty.

### E: owned execution and output contract

Proposed executor `execute_owned(spec, plan, ready_action) -> execution_receipt`, module CLI `python3 -m scripts.eval_harness.owned_executor --spec PATH`. CLI is NEW and not runnable in this planning slice. `emit_shell` gets optional `owned_execution` specs; each owned leg delegates lifecycle to this executor, then uses existing `_emit_report_lines` only with actual immutable paths. Legacy mode remains explicitly legacy/unqualified for residency. Build the ready action from `_emit_ready_run_lines`; executor owns the server/readiness and runs the action in a separately tracked owned process group, so no second server launcher or ad-hoc scorer exists. Capture scorer/fetch exits via the action's structured result; `_fail` must become a nonzero action exit on either failure. A shell's final successful diagnostic command must not hide fetch/score failure.

Create output attempt directory with exclusive mkdir under private permanent root, outside cache and all pruning scopes; collision refuses, never overwrite/reuse. Stage stdout/stderr, raw/partial/aborted run records, score reports, provenance, memory samples and lifecycle journal there. Persist monotonic ordered events and terminal receipt atomically; keep all earlier attempts byte-identical on success and every failure. Add additive `bakeoff --output-root PATH --no-prune` (proposed flags): in owned mode constrain internal `out_dir` to this new directory, disable `prune_out_dir`, retain explicit `--out`; defaults unchanged. Test scorer side effects and diagnostic paths also stay inside this directory, using a narrow optional output-root parameter only if current scorer paths escape. Never solve preservation with enormous `--keep`.

Owned mode passes exact `--model-revision`, verifies runtime digest before execution, confines environment cache paths, and validates endpoint host/port matches the leased local server. Require process alive and an attributable readiness response; a foreign endpoint responding while own launch fails is not ready. Port/device locks are acquired before launch. Preserve warmup and frozen recipe; no extra requests. New outputs can have a score marker only through successful existing score control flow; never touch, delete or repair a published marker. Freeze terminal artifacts after writers stop; append no later observations to a sealed attempt. A rerun always creates a new attempt.

## Lifecycle, cleanup and refusal semantics

State machine: `VALIDATED → LEASED → RESERVED → FETCHING → VERIFIED → COLLECTOR_ARMED → BOUND → RUNNING → STOPPING → EXIT_PROVEN → UNLOAD_PROVEN → CLEANED → SEALED → RELEASED`. A terminal error branches to STOPPING if any child exists, otherwise to owned partial cleanup; no transition skips ownership proof. Journal transitions before/after side effects for interruption recovery. Catch ordinary exceptions and SIGINT/SIGTERM; use bounded finally teardown. SIGKILL/power loss cannot guarantee immediate cleanup: next invocation sees an unresolved lease/journal, refuses advance, and offers an explicit owned reconciliation operation using the same proofs. No automatic stale PID kill.

Spawn server with `start_new_session=True`, record process identity and group; supervise downloader and action subprocesses as well. Stop with TERM to the proven owned group, wait finite grace, KILL only after identity revalidation, reap the direct child and verify no tracked/group members remain. Direct-child `wait()` alone is insufficient for surviving children. Record each return code/signal; unknown exit (`EXIT_UNPROVEN`) or ownership mismatch blocks unload/eviction/advance. Expected executor-initiated TERM may be a known teardown result; unrequested early signal/nonzero exit is failure. Retain original run/scorer error as well as cleanup errors.

On real target, poll admitted device backend for absence of owned process allocations and release of attributable runtime allocation; device total need not be zero. If backend cannot prove unload, set `UNLOAD_UNPROVEN`, preserve cache and resource lock disposition for reconciliation, and forbid next arm. Fixture backend can prove synthetic unload only, never target GPU unload.

After exit/unload proof, mark server's component-use sublease inactive. Keep the **exclusive slot lock** while deleting only ledger-owned inactive regular component/partial files and releasing reservation files. Recheck ownership/inodes immediately before unlink; no globs, shared cache eviction, user-weight deletion or recursive unknown tree removal. Successful, error and interrupted runs use the same teardown/cleanup. Verify free-byte/headroom receipt, seal outputs, then release slot FD. This distinguishes ending active model use from releasing the slot lock: releasing the exclusive lock before eviction would admit a racing next writer. If any cleanup proof fails, `can_advance=false`; close process on exit but leave durable blocked state that a new lock holder must honor.

Typed terminal reasons include `INVENTORY_INCOMPLETE`, `HASH_MISMATCH`, `PATH_UNSAFE`, `OWNERSHIP_UNKNOWN`, `LEASE_BUSY`, `SPACE_INSUFFICIENT`, `RESERVATION_UNPROVEN`, `TARGET_ADMISSION_MISSING`, `SUBPROCESS_MISSING`, `READINESS_TIMEOUT`, `RUN_FAILED`, `SCORE_FAILED`, `EXIT_UNPROVEN`, `UNLOAD_UNPROVEN`, `CLEANUP_UNPROVEN`, `COLLECTOR_UNAVAILABLE`. Distinguish optional measurement unavailability (run may be preserved as partial) from required admission/unload proof (no advance). Report no PASS for unknown ownership/hash/exit and no quality PASS from executor success.

## Field-edge DAG and resource exclusivity

GRPH-01, **Model the work as a DAG, then topological-sort** ([The Algorithm Design Manual, ch. 7](https://github.com/darce/heuristics-canon/blob/v0.26.2/SOURCES.md#src-algorithm-design-manual)), and GRPH-32, **An edge exists only where data moves** ([bootstrap practice](https://github.com/darce/heuristics-canon/blob/v0.26.2/SOURCES.md#src-bootstrap)), govern this table. GRPH-06, **Partition by connected components first** ([Graph Theory with Applications, ch. 1](https://github.com/darce/heuristics-canon/blob/v0.26.2/SOURCES.md#src-graph-theory-with-applications)), motivates disjoint C/M ownership; E connects them via explicit records, so they are independent branches, not falsely claimed disconnected components of the whole graph.

| Node | Reads named fields | Emits |
| --- | --- | --- |
| P contract freeze | this reviewed spec, source tree | `contract_version`, `source_tree`, ownership map |
| C-R cache RED | P contract_version/source_tree | `cache_red_receipt.case_ids/failures` |
| M-R collector RED | P contract_version/source_tree | `memory_red_receipt.case_ids/failures` |
| E-R integration RED | P contract_version/source_tree | `executor_red_receipt.case_ids/failures` |
| C-I cache implementation | C-R failures + P contract | `cache_green_receipt`, cache API |
| M-I collector implementation | M-R failures + P contract | `memory_green_receipt`, collector API |
| E-I integration implementation | E-R failures, C-I API/green receipt, M-I API/green receipt | `integration_receipt`, owned shell/spec parser |
| G fixture review | all RED/green receipts, integrated tree | `review_receipt`, fixture limitations, code readiness |
| T real admission (separate future work) | G reviewed tree, complete inventory, measured target/runtime/operation authorization | `target_admission` or typed blockers |

Edges are exactly the reads above. Legal order: P; C-R/M-R/E-R; C-I/M-I; E-I; G; optional separately admitted T. Test-only commits are reviewed before their corresponding implementation; tests and source are separate slices. C/M fixtures and cleanup can run concurrently only in different temp roots and with distinct fake process groups; no dependency arrow is invented between them. Shared runner edits have one E writer. Reviews are not claimed performed by writing this plan.

Resource constraints are separate from data edges: one cache slot lease; one loaded vision generator per measured GPU slot; exclusive local endpoint/port; per-filesystem reservation; admitted CPU/RAM envelope. Logical ready width three does not admit three model loads. GRPH-31, **Critical-path schedule the task DAG** ([Algorithm Design Manual ch. 17 + Scheduling: Theory, Algorithms, and Systems ch. 5/§D.4](https://github.com/darce/heuristics-canon/blob/v0.26.2/SOURCES.md#src-pinedo-scheduling)), requires worker/capacity bounds separately. No measured task durations exist, so no numeric critical-path or speedup claim is made; the dependency spine is P→RED→C/M implementation→E-I→G, and remote concurrency is admitted dynamically.

## RED-first remote dispatch slices and verification cases

First remote **test-only** slice owns new C/M/E test files and additive owned-mode cases in runner/bakeoff tests; no production edits, weights or GPU. Dispatch C/M independently only if separately assigned disjoint ownership; this current planning attempt delegates nothing. Before each new test predict the failure, execute and record actual output; missing module/import failure is bootstrap evidence only, then rerun behavioral failures after the smallest API scaffold. TEST-06, **Watch it fail once / predict the failure** ([Modern Software Engineering, ch. 8](https://github.com/darce/heuristics-canon/blob/v0.26.2/SOURCES.md#src-modern-software-engineering)), applies here. Predict bootstrap `ModuleNotFoundError: No module named 'scripts.eval_harness.owned_cache'` (and corresponding memory/executor modules); once importable, require explicit assertion messages below, not acceptance of any exception.

| Future test case / assertion message | Fixture and required oracle |
| --- | --- |
| `test_slot_excludes_second_owner` / `second owner entered occupied slot` | Two real CPU processes contend for same temp slot; second refuses; distinct roots can proceed. Stale/foreign token refuses takeover, foreign sentinel unchanged. |
| `test_inventory_requires_complete_expected_hashes` / `incomplete inventory admitted` | Missing shard/projector/hash/completeness, observed-only hash, revision disagreement each refuse before spawn/fetch. Complete synthetic multi-component inventory accepted. |
| `test_corrupt_expected_hash_refuses_load` / `corrupt expected hash reached server` | Expected digest deliberately wrong for known fixture bytes; no server event; owned inactive partial cleanup receipt and free bytes recorded. Unknown file not deleted. |
| `test_paths_refuse_escape_and_replacement` / `unsafe path mutated sentinel` | Parent/file symlink, `..`, absolute path, hardlink, FIFO and replaced directory/inode; sentinel outside owned root remains byte-identical. Controlled hook swaps path after validation to expose TOCTOU. |
| `test_reservation_and_free_receipts` / `insufficient bytes admitted` | Inject statvfs before/after, separate filesystems, boundary equality, missing headroom, ENOSPC, sparse reservation and allocation failure. Exact requested/allocated/free bytes; no disk→GPU arithmetic. |
| `test_success_error_interrupt_cleanup` / `owned inactive bytes remain` | Tiny owned regular files and real fake child/grandchild; success, fetch error, score error, SIGINT and SIGTERM all stop/reap then delete only owned weights/partials. Existing raw/report/marker sentinels survive. |
| `test_unknown_exit_blocks_eviction` / `unknown exit advanced arm` | PID/start mismatch, inaccessible group identity, child outliving parent, TERM ignored then bounded KILL, reap timeout and escaped child. No foreign signal/deletion; can_advance false, typed proof error. |
| `test_missing_subprocess_is_typed` / `missing executable lost diagnostics` | Missing downloader/server/action executable separately; preserved terminal receipt, no fake successful exit or marker. No model needed. |
| `test_collector_armed_before_exec` / `exec preceded collector bind` | Pipe-barrier fake server and event-controlled readers; exact armed→bind→initial sample→exec ordering, quick-exit case, sampling through final reap. No timing sleeps as synchronization. |
| `test_owned_identity_and_scopes` / `foreign process attributed` | Synthetic proc PID reuse/membership and GPU UUID rows with foreign consumer; actual target device aggregate stays distinct from owned rows. Asynchronous process peaks never summed as simultaneous HWM. |
| `test_sampling_unavailable_and_gaps` / `unavailable measurement became zero` | Missing nvidia-smi, nonzero query exit, malformed/zero rows, denied proc read, changing topology/MIG and reader stall; bounded stop and null/reason, counted gaps, no fabricated KV/TTFT/cold peak. |
| `test_owned_shell_preserves_outputs_and_score_control` / `prior artifact changed` | Execute emitted owned shell with fake server/downloader/readers/fetch/score, no endpoint calls. Two attempts preserve all old bytes; score failure leaves no new marker, fetch failure skips score, diagnostic echo cannot hide failure, report gets actual new paths. `bash -n` passes. |
| `test_custom_out_does_not_prune_module_out` / `historical run pruned` | Real producer path with injected clients and sentinel old timestamp files; owned flags confine outputs and suppress pruning; legacy semantics unchanged. |
| `test_no_next_arm_without_cleanup_receipt` / `next arm started without proof` | Ready second fake candidate consumes prior receipt's lease/state/free bytes; unload/cleanup unknown blocks its launch. Synthetic device proof explicitly labeled fixture. |

Separate subsequent remote **implementation** slices own C/M source modules then E integration files; retain test-only commits and RED receipts. Implement one failing behavior at a time, then refactor under green. Review boundary contracts, subprocess identity and failure preservation before code-readiness acceptance. No full suite or historical 219/75 rerun.

Commands below run REMOTE ONLY from service root with the existing qualified interpreter; new test paths become valid in the test-only slice. No installs, modelweights, full suite or real target probes:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ../../.venv/bin/python -B -m pytest --noconftest -o required_plugins= -p no:cacheprovider -q scene/tests/test_eval_harness_owned_cache.py
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ../../.venv/bin/python -B -m pytest --noconftest -o required_plugins= -p no:cacheprovider -q scene/tests/test_eval_harness_owned_memory.py
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ../../.venv/bin/python -B -m pytest --noconftest -o required_plugins= -p no:cacheprovider -q scene/tests/test_eval_harness_owned_executor.py
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ../../.venv/bin/python -B -m pytest --noconftest -o required_plugins= -p no:cacheprovider -q scene/tests/test_eval_harness_bakeoff_runner.py
```

Run only the newly named no-prune bakeoff test selectors after adding them, not its entire historical suite. Each process fixture has an outer timeout, pipe/event synchronization, and finally cleanup of its own subprocess group/temp root even on failed assertions; never `pkill`/`killall`. A leaked fixture makes the receipt partial and blocks further process fixtures until reconciled.

## Completion, rollout and blockers

- [ ] P: exact paths/contracts/ownership reviewed; source tree refreshed if producer bytes change.
- [ ] C-R/M-R/E-R: separate test-only commits with predicted and observed RED outputs, including interruption, unknown ownership, corrupt expected hash, symlink and missing subprocess.
- [ ] C-I/M-I: disjoint modules pass scoped CPU fixtures and publish typed interfaces.
- [ ] E-I: owned emission reuses fetch/score/report, unique output/no-prune behavior, process/unload/cleanup receipts and failure preservation pass.
- [ ] G: independent code review covers kill/delete boundary, expected hashes, reservations, measurement attribution and preservation; reviewed code readiness only.
- [ ] T: separately admitted actual target operations; complete component closure and expected hashes, target/runtime/device/capacity and operation bounds supplied. Otherwise emit typed blocker, no launch.

No component inventory or real capacity measurement was produced in this plan. Supplied sealed pins remain unchanged; MiniCPM 4.6 completeness and all target GPU capacity/unload facts remain unknown. Actual KV/first-token/cold-memory fields remain unknown. CPU fixture success cannot close these blockers or qualify loader/pixels, subject disjointness, independent human gold, baselines or any research quality gate. Existing research readiness stays **NOT_READY**.

Roll out via opt-in owned mode first. Legacy shell must carry a clear residency-unqualified status; do not silently route it through destructive cleanup. Rollback disables owned-mode admission while preserving its outputs and durable blocked leases; it never deletes evidence or automatically reopens an unresolved slot. No main merge authority is conferred.
