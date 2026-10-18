# E17-14 Slice 2 Verification Proof

> Status: `PASS` (rerun 2026-05-01) - the scratch-consumer probe was rerun against the now-published `agentic-bootstrap-v0.3.0` and `mcp-agent-handoff-v0.5.1` packages from `agentic-protocol-monorepo` tag `v0.1.4`, and all four root-visible-plan pass criteria are satisfied end to end.

This artifact records the rebased inputs, the actual scratch-consumer probe executed on 2026-05-01 against the upstream-fixed package set, and the previous 2026-04-30 failure run that surfaced the upstream blockers. The 2026-04-30 history is preserved because the fix lives in `agentic-protocol-monorepo` Plan 0004 + bootstrap 0.3.x, which were already merged to that repo's `main` and tagged before the rerun.

## Recorded Inputs

- Task ref: `E17-14`
- Branch head after the `origin/main` rebase: `5dfdd24a7d7f837f4127070f8d13a0bc5b48bb65`
- Reviewed overlay commit materialized into `.agentic/remote/`: `e057c18254190dd36c20fb8b793e25d4c5cb8493`
- Reviewed overlay tag on that remote commit: `v0.1.4`
- Overlay manifest note: `.agentic-overlay.json` now records `remote_sha` for the reviewed commit, while `remote_ref` remains `main` because the generated manifest tracks the clone's default branch label rather than the tag used during install.

## Scratch Consumer Fixture

The runtime proof target remains a fresh repo rooted at `/tmp/e17-14-scratch-consumer/`. It must be created from `git init`, not from a clone of this monorepo, and it must use sibling worktree directories so `task_plan_path` resolution can be checked from the consumer root.

Required fixture layout:

- Consumer root: `/tmp/e17-14-scratch-consumer/`
- Task A worktree placeholder root: `/tmp/e17-14-scratch-consumer-task-a/`
- Task B worktree placeholder root: `/tmp/e17-14-scratch-consumer-task-b/`
- Placeholder task plans created before the probe:
  - `/tmp/e17-14-scratch-consumer-task-a/docs/tasks/task-a.md`
  - `/tmp/e17-14-scratch-consumer-task-b/docs/tasks/task-b.md`

Each seeded active task must include distinct values for `task_ref`, `target_branch`, `target_worktree_path`, and `task_plan_path` so the consumer-root dashboard can prove that the reviewed package resolves plan metadata without switching away from `main`.

## Probe Commands

The following commands were used for the actual 2026-04-30 probe against the latest published consumer packages. `agentic-bootstrap@v0.2.0` still defaulted to `git@github.com:darce/agentic-system.git`, so the real run required an explicit `--remote-url git@github.com:darce/agentic-protocol-monorepo.git` override to reach the reviewed overlay tag.

```bash
rm -rf /tmp/e17-14-scratch-consumer /tmp/e17-14-scratch-consumer-task-a /tmp/e17-14-scratch-consumer-task-b
mkdir -p /tmp/e17-14-scratch-consumer /tmp/e17-14-scratch-consumer-task-a/docs/tasks /tmp/e17-14-scratch-consumer-task-b/docs/tasks
cd /tmp/e17-14-scratch-consumer
git init
agentic-bootstrap install --target /tmp/e17-14-scratch-consumer --remote-ref v0.1.4
agentic-bootstrap doctor
```

Actual published-package command line used for the successful install step:

```bash
/tmp/e17-14-proof-venv/bin/agentic-bootstrap install \
  --target /tmp/e17-14-scratch-consumer \
  --remote-url git@github.com:darce/agentic-protocol-monorepo.git \
  --remote-ref v0.1.4
```

After install, seed two active tasks through the reviewed handoff surface. The reviewed package was expected to accept `task_plan_path` as structured metadata on the active task rows, but the latest published `mcp-agent-handoff@v0.4.3` API still omits that parameter from `set_handoff_state`. The actual probe therefore seeded only `task_ref`, `target_branch`, and `target_worktree_path`, which is sufficient to demonstrate the current published-package failure mode.

```text
set_handoff_state(task_ref='E17-14-A', target_branch='feature/a', target_worktree_path='/tmp/e17-14-scratch-consumer-task-a', task_plan_path='docs/tasks/task-a.md', status='in_progress')
set_handoff_state(task_ref='E17-14-B', target_branch='feature/b', target_worktree_path='/tmp/e17-14-scratch-consumer-task-b', task_plan_path='docs/tasks/task-b.md', status='in_progress')
```

The consumer-root probe is then:

```bash
cd /tmp/e17-14-scratch-consumer
make context
```

Read `DASHBOARD.txt` from the consumer root and capture the rows for both active tasks. Then request the task-scoped snapshot directly through `render_handoff(kind='current_task', task_ref='E17-14-A')` and capture that output separately from the dashboard excerpt.

The proof must also verify that `CURRENT_TASK.json` must not be auto-written by `make context` or by the state-changing writes used during the probe.

## Pass-Criteria Checklist (2026-05-01 rerun)

- [x] `agentic-bootstrap install --target /tmp/e17-14-scratch-consumer --remote-ref v0.1.4` exited `0` **without** any `--remote-url` override; published `agentic-bootstrap-v0.3.0` defaults to `git@github.com:darce/agentic-protocol-monorepo.git`.
- [x] Handoff doctor exited `0` from the scratch consumer root (`agentic-bootstrap doctor --target /tmp/e17-14-scratch-consumer` → `doctor: no drift detected.`).
- [x] `DASHBOARD.txt` exposes the `ACTIVE TASK PLANS` operator section with both seeded task refs, their relative `task_plan_path`, the resolved `task_plan_abs_path`, and `✓` existence markers (see captured output below).
- [x] `render_handoff(kind='current_task', task_ref='E17-14-A')` returns a parseable snapshot for task A only, and the snapshot's `active.task_plan_path` is `docs/tasks/task-a.md`.
- [x] `CURRENT_TASK.json` is not auto-written by `set_handoff_state` writes; explicit `render_handoff(kind='current_task', write_file=False)` returned `data.written = false` with the file absent on disk; explicit `render_handoff(kind='current_task', write_file=True)` then materialized the file on demand.

## Captured Outputs (2026-05-01 rerun)

Verification venv pins (proof venv `/tmp/e17-14-proof-venv`):

```text
agentic-bootstrap   0.3.0   (git+ssh://git@github.com/darce/agentic-protocol-monorepo.git@agentic-bootstrap-v0.3.0)
mcp-agent-handoff   0.5.1   (git+ssh://git@github.com/darce/agentic-protocol-monorepo.git@mcp-agent-handoff-v0.5.1)
```

Install output (no `--remote-url` override):

```text
✓ agent-workflows: wrote 41 adapter files.
installed agentic-system overlay: git@github.com:darce/agentic-protocol-monorepo.git@e057c18254190dd36c20fb8b793e25d4c5cb8493 -> /tmp/e17-14-scratch-consumer
```

Doctor output:

```text
doctor: no drift detected.
```

`DASHBOARD.txt` `ACTIVE TASK PLANS` section (full file: `proof-2026-05-01/dashboard-excerpt.txt`):

```text
ACTIVE TASK PLANS
-----------------
  [E17-14-A] branch=feature/a
      plan: docs/tasks/task-a.md
      abs:  ✓ /tmp/e17-14-scratch-consumer-task-a/docs/tasks/task-a.md
  [E17-14-B] branch=feature/b
      plan: docs/tasks/task-b.md
      abs:  ✓ /tmp/e17-14-scratch-consumer-task-b/docs/tasks/task-b.md
```

`render_handoff(kind='current_task', task_ref='E17-14-A', write_file=False)` excerpt (full snapshot: `proof-2026-05-01/CURRENT_TASK.E17-14-A.json`):

```json
{
  "active": {
    "objective": "Probe task A",
    "status": "in_progress",
    "target_branch": "feature/a",
    "target_worktree_path": "/tmp/e17-14-scratch-consumer-task-a",
    "task_plan_path": "docs/tasks/task-a.md",
    "task_ref": "E17-14-A"
  },
  "surface": "current_task",
  "task_ref": "E17-14-A"
}
```

On-demand `CURRENT_TASK.json` semantics:

```text
# After set_handoff_state writes, before any explicit render:
$ ls /tmp/e17-14-scratch-consumer/CURRENT_TASK.json
ls: ... No such file or directory

# After render_handoff(kind='current_task', write_file=False):
data.written = false; file still absent

# After render_handoff(kind='current_task', write_file=True):
file materialized at /tmp/e17-14-scratch-consumer/CURRENT_TASK.json
```

## Current Status

Current status is `PASS` as of the 2026-05-01 rerun.

What is verified end to end against the published packages:

- `agentic-bootstrap-v0.3.0` defaults the install remote to `agentic-protocol-monorepo`; no `--remote-url` override is needed for the documented Slice 2 install command.
- `mcp-agent-handoff-v0.5.1` accepts `task_plan_path` on `set_handoff_state`, persists it as a first-class column, and enriches reads with `task_plan_abs_path`, `task_plan_exists`, and `task_plan_resolution`.
- `DASHBOARD.txt` renders the `ACTIVE TASK PLANS` operator section with task ref, branch, declared plan, resolved abs path, and existence markers — the contract the consumer relies on.
- `CURRENT_TASK.json` is on-demand only: routine `set_handoff_state` writes do not materialize it, explicit `render_handoff(kind='current_task', write_file=False)` returns the snapshot without writing, and `write_file=True` writes on demand.

## Historical Run (2026-04-30, FAIL)

The original probe ran against `agentic-bootstrap@v0.2.0` and `mcp-agent-handoff@v0.4.3` and recorded these blockers, all subsequently resolved upstream and reverified above:

- `agentic-bootstrap@v0.2.0` defaulted to `darce/agentic-system.git`; install required `--remote-url` override.
- `mcp-agent-handoff@v0.4.3` `set_handoff_state` did not accept `task_plan_path`.
- The published dashboard had no `ACTIVE TASK PLANS` section.
- The current-task snapshot omitted `task_plan_path`.

The fix lives upstream in `agentic-protocol-monorepo` Plan 0004 (`docs/plans/0004-task-plan-metadata-and-current-task-demotion.md`) plus the bootstrap default-remote change shipped in `agentic-bootstrap-v0.3.0`. Both are merged to that repo's `main` and tagged.
