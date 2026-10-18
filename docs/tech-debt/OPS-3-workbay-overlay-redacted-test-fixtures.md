# Tech Debt: OPS-3 publishing redaction corrupts the workbay hook overlay (deferred)

**Status:** deferred · **Owner:** upstream (`agentic-protocol-monorepo` / workbay-system overlay publisher) · **Origin:** FIRPLAN-1 pre-merge gate, 2026-09-12 — `make lint-task-plans` investigation

## What was deferred

Fixing the overlay publisher's redaction pass, which rewrites real finding-style
identifiers to the literal token `internal` in the files it ships under
`scripts/hooks/`. The rewrite lands inside test fixtures and user-facing strings,
not just prose, so the shipped overlay cannot pass its own test suite.

## Evidence

`scripts/hooks/` is untracked and gitignored (`.gitignore:130`), installed by the
workbay bootstrap. Its self-test suite fails on a clean tree:

```
$ python3 -m pytest scripts/hooks/test_guard_task_plan_findings.py -q
14 failed, 42 passed in 2.34s
```

Every failure is the same shape — the fixture no longer contains a finding-style id:

```python
def test_detects_three_consecutive_task_prefixed_findings() -> None:
    text = (
        "## Findings\n\n"
        "- internal: Description here.\n"     # was e.g. "- AOMCP-3-BR-04: ..."
        "- internal: Another finding.\n"
        "- internal: Yet another.\n"
    )
    runs = _detect_finding_runs(text)
    assert len(runs) == 1                      # AssertionError: 0 == 1
```

55 occurrences of the token in `test_guard_task_plan_findings.py`. Synthetic ids
that never resembled a real repo task ref survived the pass (`DEMO-7-BR-01`),
which is what identifies this as an id-shaped redaction rather than a rename.

The same pass damaged `guard-task-plan-findings.py` itself — not its logic, but
its regex documentation and one operator-facing string:

```
guard-task-plan-findings.py:95   # task-prefixed: internal, DEMO-7-BR-01
guard-task-plan-findings.py:351  "(e.g. 'see internal in handoff') instead of ..."
```

Not local corruption: the source repo's copy of the guard is byte-identical
(`diff -q` clean) and `agentic-protocol-monorepo` reproduces the same
`14 failed, 42 passed`. The two checkouts' test files differ by one comment only.

## Why it is safe to defer

**The guard still works.** The redaction hit fixtures and comments, not the
detection regex. Verified directly against a synthetic violation:

```
$ python3 scripts/hooks/guard-task-plan-findings.py --scan-paths /tmp/.../foo-task-plan.md
BLOCKED: Pasted review-finding list detected in a task plan.
    line 5: 3 consecutive finding bullets (H-1, H-2, H-3)
rc=1
```

So the Review Findings Placement rule is enforced in both the `PreToolUse` hook
path and the `make lint-task-plans` path. A `rc=0` from the guard remains
trustworthy evidence.

## Cost of leaving it

1. **`make check-all` can never be green** while it routes through
   `make lint-task-plans` in a checkout that has the overlay installed — 14
   failures unrelated to any branch under test. Agents learn to ignore them,
   which is how a real regression in the guard gets waved through.
2. **The block message misinstructs the agent it blocks.** An agent told to write
   `see internal in handoff` will write exactly that instead of a finding id,
   defeating the link-by-id escape hatch the rule depends on.
3. **The overlay is absent from linked worktrees** (untracked files do not
   propagate), so `make lint-task-plans` fails outright there with
   `can't open file .../scripts/hooks/guard-task-plan-findings.py`. Workaround:
   run the guard from the root checkout with
   `--scan-paths <absolute worktree paths>`. This is a separate defect from the
   redaction but shares the same root cause — a gitignored operator overlay
   carrying a `make check-all` dependency.

## Local mitigation applied (2026-09-12)

The operator-facing string at `guard-task-plan-findings.py:351` was patched in this
checkout only, `internal` -> `AOMCP-3-BR-04`, so a blocked agent is told to write a real
finding id. Verified: the guard still blocks a synthetic violation, and the suite is
unchanged at 14 failed / 42 passed (no test asserts that string).

**This patch is on an untracked, gitignored file and will be silently reverted by the next
overlay install.** It is a stopgap, not a fix. The 55 fixture occurrences and the regex
comments were left alone — repairing those locally would create a second divergent fork of
the overlay, which is precisely the OPS-2 failure mode.

## Trigger for picking it up

Any of: the overlay publisher is next touched upstream; `make check-all` is
wired into CI; or a task-plan findings violation reaches `main` (which would mean
the guard regressed and nobody could tell, because its suite was already red).

## Acceptance criteria

- [ ] The redaction pass excludes test fixtures and user-facing strings, or runs
      before id substitution rather than after.
- [ ] `python3 -m pytest scripts/hooks/test_guard_task_plan_findings.py -q` is
      green in both `agentic-protocol-monorepo` and a consumer checkout.
- [ ] `guard-task-plan-findings.py:351` names a real example finding id.
- [ ] `make lint-task-plans` either works from a linked worktree or fails with an
      actionable message naming the root-checkout `--scan-paths` workaround.

## Related

- [OPS-2 vendored `remote_agent.sh` fork](OPS-2-vendored-remote-agent-fork.md) —
  same class: an untracked operator overlay diverging from upstream with no git
  history to diff against.
