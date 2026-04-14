# /plan-analyze

Active skill: `plan-analyze`

Makefile entry point: `make plan-analyze DOC=<path>`

Execution context: use for pre-review triage of a planning artifact before the formal `planning-review` pass.

Loop:
- load the plan, constitution, and minimal adjacent anchors
- run the six analysis passes
- record findings with `review_mode="analysis"`
- recommend revise-first or proceed-to-planning-review
- stop without recording a review run
