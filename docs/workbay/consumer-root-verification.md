# Consumer Root Verification

## Goal

Use this note when you need to prove that a scratch consumer repo can discover active task plans from its root workspace while keeping `CURRENT_TASK.json` on-demand.

## Fixture

Create a scratch repo at `/tmp/wb-scratch-consumer/` plus two sibling task roots. The consumer root must come from `git init`, not from a clone of this monorepo.

```bash
rm -rf /tmp/wb-scratch-consumer /tmp/wb-scratch-consumer-task-a /tmp/wb-scratch-consumer-task-b
mkdir -p /tmp/wb-scratch-consumer /tmp/wb-scratch-consumer-task-a/docs/tasks /tmp/wb-scratch-consumer-task-b/docs/tasks
cd /tmp/wb-scratch-consumer
git init
REF=workbay-v0.3.6
R="git+https://github.com/darce/workbay.git@$REF"
uv tool install --no-sources \
  --with "$R#subdirectory=packages/workbay-protocol" \
  --with "$R#subdirectory=packages/mcp-workbay-handoff" \
  --with "$R#subdirectory=packages/mcp-workbay-orchestrator" \
  --with "$R#subdirectory=packages/workbay-bootstrap" \
  --with "$R#subdirectory=packages/workbay-system" \
  --from "$R#subdirectory=packages/workbay" \
  workbay
workbay install --target /tmp/wb-scratch-consumer --remote-ref "$REF"
workbay doctor --target /tmp/wb-scratch-consumer
```

Seed two active tasks after install. Each active row must carry a distinct `task_plan_path` plus the matching `target_worktree_path`.

```text
set_handoff_state(task_ref='E17-14-A', target_branch='feature/a', target_worktree_path='/tmp/wb-scratch-consumer-task-a', task_plan_path='docs/tasks/task-a.md', status='in_progress')
set_handoff_state(task_ref='E17-14-B', target_branch='feature/b', target_worktree_path='/tmp/wb-scratch-consumer-task-b', task_plan_path='docs/tasks/task-b.md', status='in_progress')
```

## Probe

From `/tmp/wb-scratch-consumer/`, run:

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
