# E17-14 Slice 2 Verification Proof

> Status: `FAIL - PUBLISHED PACKAGE BLOCKER` - the actual scratch-consumer probe was run, and the latest published package set still cannot satisfy the Slice 2 task-plan visibility criteria.

This artifact records the rebased inputs, the actual scratch-consumer probe executed on 2026-04-30, and the published-package blockers that currently prevent the Slice 2 pass criteria from succeeding end to end. It is intentionally explicit about what was observed versus what remains deferred to an external package follow-up.

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

## Pass-Criteria Checklist

- [x] `agentic-bootstrap install` exited `0` against `/tmp/e17-14-scratch-consumer/` when run with the explicit `--remote-url git@github.com:darce/agentic-protocol-monorepo.git` override required by published `agentic-bootstrap@v0.2.0`.
- [x] Handoff doctor exited `0` from the scratch consumer root.
- [ ] `DASHBOARD.txt` lists both seeded task refs but does not expose `task_plan_path` or resolved task-plan files; the published package only renders task refs, status, and workflow-integrity warnings.
- [ ] `render_handoff(kind='current_task', task_ref='E17-14-A')` returns a parseable snapshot for task A only, but the published output contains no `task_plan_path` metadata.
- [x] `CURRENT_TASK.json` was not auto-written during the probe; the explicit `render_handoff(..., --no-write)` response reported `written: false`, and `ls /tmp/e17-14-scratch-consumer/CURRENT_TASK.json` returned `No such file or directory`.

## Captured Outputs

Install output:

```text
installed agentic-system overlay: git@github.com:darce/agentic-protocol-monorepo.git@e057c18254190dd36c20fb8b793e25d4c5cb8493 -> /tmp/e17-14-scratch-consumer
```

Doctor output:

```text
doctor: no drift detected.
```

`make context` output from the scratch consumer root:

```text
make: *** No rule to make target `context'.  Stop.
```

`DASHBOARD.txt` excerpt:

```text
ALL TASKS

  Task                                          Status         Find  Block  Act  Last
  ────────────────────────────────────────────  ─────────────  ────  ─────  ───  ────────────────
  E17-14-B                                      in_progress       0      0    0  21:48
  E17-14-A                                      in_progress       0      0    0  21:48

WORKFLOW INTEGRITY
------------------
  ! [E17-14-A] missing branch: feature/a does not exist
  ! [E17-14-B] missing branch: feature/b does not exist
```

`render_handoff(kind='current_task', task_ref='E17-14-A')` excerpt:

```json
{
  "active": {
    "objective": "Scratch proof task A",
    "status": "in_progress",
    "target_branch": "feature/a",
    "target_worktree_path": "/tmp/e17-14-scratch-consumer-task-a",
    "task_ref": "E17-14-A"
  },
  "surface": "current_task",
  "task_ref": "E17-14-A"
}
```

No-auto-write check:

```text
ls: /tmp/e17-14-scratch-consumer/CURRENT_TASK.json: No such file or directory
```

## Current Status

Current status is `FAIL - PUBLISHED PACKAGE BLOCKER`.

What is already verified in this repo:

- The local consumer overlay was refreshed from the reviewed external tag and rebased cleanly onto `origin/main`.
- The generated surfaces now present the v0.1.4-era launcher and skill layout that Slice 2 must verify from a scratch consumer.
- A real scratch-consumer run proved that the published `agentic-bootstrap@v0.2.0` path only succeeds when the remote URL is overridden to `git@github.com:darce/agentic-protocol-monorepo.git`.
- A real scratch-consumer run proved that the published `mcp-agent-handoff@v0.4.3` current-task/dashboard surfaces still do not expose `task_plan_path` metadata.

What blocks Slice 2 closure today:

- Published `agentic-bootstrap@v0.2.0` still defaults to the old `darce/agentic-system.git` remote, so the documented `agentic-bootstrap install --target /tmp/e17-14-scratch-consumer --remote-ref v0.1.4` command does not succeed without an explicit `--remote-url` override.
- Published `mcp-agent-handoff@v0.4.3` still lacks a `task_plan_path` input on `set_handoff_state`, and its rendered dashboard/current-task outputs therefore cannot satisfy the root-visible-plan pass criteria.
- The scratch consumer does not provide a working `make context` target after install, so the exact operator flow promised by the plan is not yet delivered by the published package set.
