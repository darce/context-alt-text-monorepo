# /planning-review

Active skill: `planning-review`

Makefile entry point: `make plan-review DOC=<path>`

Execution context: use for task plans, epics, ADRs, and other planning artifacts that need formal review before implementation.

Loop:
- load the planning doc and minimum code/contract anchors
- run the planning-review checklist
- record findings and verdict in MCP
- record the planning review run
- block approval until open planning findings are resolved
