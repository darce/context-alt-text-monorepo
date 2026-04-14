# /branch-review

Active skill: `branch-review`

Makefile entry point: `make review-run`

Execution context: use for implementation branch diffs, pre-merge review passes, and code audit requests.

Loop:
- load the latest slice packet or branch diff
- pre-triage existing findings
- run the branch-review checklist
- record findings, verdict decision, and branch review run
- confirm whether the branch is actually merge-ready
