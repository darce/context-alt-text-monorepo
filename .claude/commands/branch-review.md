# /branch-review

Active skill: `branch-review`

Makefile entry point: `make review-run` for lane/local working-tree review; for merged-slice or committed feature-branch diff review, load the skill and review `git diff main...HEAD` scope directly.

Execution context: use for implementation branch diffs, pre-merge review passes, and code audit requests.

Loop:
- decide whether the review scope is a lane/local working tree or a committed feature-branch diff
- use `make review-run` only when reviewing lane/local working-tree scope
- load the latest slice packet or branch diff
- pre-triage existing findings
- run the branch-review checklist
- record findings, verdict decision, and branch review run
- confirm whether the branch is actually merge-ready
