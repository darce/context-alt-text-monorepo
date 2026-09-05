# FIXWAVE-1 D2 round-10 verification

All paths below are relative to `apps/prototype-wp-alt-context`.

Review findings are tracked by the orchestrator: D2-R9-01, D2-R9-02, D2-LV-01.

## Current verification

The targeted parity suite passed (83 tests), both Python mutation suites passed
(10 tests), and the renderer check, Unicode fixture check, and TypeScript check passed.
The version-only mutation failed before the change and passed afterward; mutations to
each of the three property ranges still fail. A hostile-PATH probe selected a failing
stub with the old command and succeeded with the repository interpreter. The findings
placement probe rejected the prior document and accepted the updated document.
See `README.md` for reproducible commands and interpreter selection.

An initial standalone Node subprocess probe encountered sandbox `EPERM`; shell execution
and in-process Node checks completed the same probe successfully.

## Prior verification limits

The targeted parity and dashboard suites passed together (90 tests). The standalone
Python mutation suite, Unicode fixture verification, TypeScript check, and dependency-free
`render_ux_maps.py --check` also passed. The final standalone lane suite executes the
Python mutation probes as part of its provenance checks.

The approved node_modules donor is
`/home/gate/grok-sandbox/feature-gpuux-1-n4-gpu-chip-unknown-3cbb91cf/apps/prototype-wp-alt-context/node_modules`.
It is linked for tooling only and is not part of the commit. No package installation ran.

For an additional renderer-backed check, the managed lane Python interpreter used the
read-only canvas source at
`/home/gate/grok-sandbox/feature-wb-parwave-01-g7-wave-c7a1a7ec/packages/mcp-workbay-canvas/src`.
Its enum verification passed. Both regenerated maps pass with that renderer. The complete
renderer-backed check reports snapshot mismatches for **dashboard and roster-people**.
A scratch probe using the untouched baseline renderer, JSON, Markdown, and snapshots
reproduced the identical two mismatches. Their snapshots were not refreshed. The
orchestrator needs to reconcile these baseline mismatches with the intended canvas revision.

The full-app Vitest run was attempted and interrupted (exit 130) after two style suites
each spent 72–92 seconds without executing their tests. It is inconclusive and requires
verification in the normal app environment; it is not recorded as passing.
