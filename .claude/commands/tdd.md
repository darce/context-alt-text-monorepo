# /tdd

Active skill: `tdd`

Makefile entry point: `make slice-start TASK=<task-ref> TEST_CMD="<command>"`

Execution context: use at the start of every implementation slice before editing production files.

Loop:
- choose the behavior to change
- run the failing test first
- record the RED gate with `make slice-start`
- implement the minimum to turn the test green
- record passing test evidence, then hand off to `make slice-commit`
