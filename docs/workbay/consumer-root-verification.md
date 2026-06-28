# Consumer Root Verification

## Goal

Use this note when you need to prove that a scratch consumer repo can discover active task plans from its root workspace while keeping `CURRENT_TASK.json` on-demand.

## Fixture

Create a scratch repo at `/tmp/e17-14-scratch-consumer/` plus two sibling task roots. The consumer root must come from `git init`, not from a clone of this monorepo.

```bash
rm -rf /tmp/e17-14-scratch-consumer /tmp/e17-14-scratch-consumer-task-a /tmp/e17-14-scratch-consumer-task-b
mkdir -p /tmp/e17-14-scratch-consumer /tmp/e17-14-scratch-consumer-task-a/docs/tasks /tmp/e17-14-scratch-consumer-task-b/docs/tasks
cd /tmp/e17-14-scratch-consumer
git init
python3 -m venv .venv
./.venv/bin/pip install "workstate-stack==0.1.12"
./.venv/bin/workbay-bootstrap install --target /tmp/e17-14-scratch-consumer --remote-ref v0.1.22
./.venv/bin/workbay-bootstrap doctor
```

Seed two active tasks after install. Each active row must carry a distinct `task_plan_path` plus the matching `target_worktree_path`.

```text
set_handoff_state(task_ref='E17-14-A', target_branch='feature/a', target_worktree_path='/tmp/e17-14-scratch-consumer-task-a', task_plan_path='docs/tasks/task-a.md', status='in_progress')
set_handoff_state(task_ref='E17-14-B', target_branch='feature/b', target_worktree_path='/tmp/e17-14-scratch-consumer-task-b', task_plan_path='docs/tasks/task-b.md', status='in_progress')
```

## Probe

From `/tmp/e17-14-scratch-consumer/`, run:

```bash
make context
```

Then verify three things:

- `DASHBOARD.txt` shows both active task refs and both resolved task-plan paths.
- `render_handoff(kind='current_task', task_ref='E17-14-A')` returns a task-scoped snapshot without regenerating the other task's snapshot.
- `CURRENT_TASK.json` must not be auto-written by either `make context` or the seed/probe writes.

## Recording Results

Record the resolved reviewed SHA, the exact command lines, the `DASHBOARD.txt` excerpt, the `render_handoff(kind='current_task'` excerpt, and the no-auto-write result in the owning task's proof artifact or slice-complete handoff decision.

Do not treat the probe as complete until the proof artifact includes the real runtime excerpts for all pass criteria.
