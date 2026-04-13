# /incremental-implementation

Active skill: `incremental-implementation`

Makefile entry points:
- open: `make slice-start TASK=<task-ref> TEST_CMD="<command>"`
- close: `make slice-commit TASK=<task-ref> MSG="..."`

Execution context: use when decomposing active task-plan work into bounded implementation slices instead of horizontal layer-by-layer waves.

Loop:
- choose one end-to-end behavior path
- advance the plan item cursor with a clean prior slice
- open the slice through the `tdd` gate
- keep the diff bounded to that one path
- close with `make slice-commit`
