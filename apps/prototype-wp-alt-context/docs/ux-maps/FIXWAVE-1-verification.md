# FIXWAVE-1 D2 round-9 verification

All paths below are relative to `apps/prototype-wp-alt-context`.

| Findings | Change and mutation evidence |
| --- | --- |
| D2-R7-01 / D2-R8-01 — FIXED | `docs/ux-maps/render_ux_maps.py:54`: fallback is limited to absence of the top-level optional canvas package. The internal-ImportError probe returned success before the fix and now fails without consulting the snapshot. Nested missing dependencies also fail closed. |
| D2-R7-02 / D2-R8-02 / D2-R8-07 — FIXED | `docs/ux-maps/render_ux_maps.py:343`: retained text, fences, tables, and heading anchors come from the independently reviewed `render_ux_maps.contracts.json`. Regeneration never writes this source. Before the fix, mutated banner text and recovery tables could refresh the snapshot successfully; both now reject the write. The recovery-table mutation fails both projection paths, and real `render()` restores the source contract even when the current Markdown is mutated. Duplicate retained headings also fail. |
| D2-R7-03 / D2-R8-03 — FIXED | `docs/ux-maps/render_ux_maps.py:120` and `js/admin/__tests__/uxmap-render-parity.test.ts:950`: generated Python Unicode property ranges replace approximate TypeScript ranges; cluster handling agrees for flags, modifiers, format characters, and VS16. The prior WATCH row measured 61 in TypeScript. Python-rendered rows for WATCH, a US flag, soft hyphen, standalone skin tone, and VS16 now all measure 62; existing CJK, combining, spacing-mark, keycap, and ZWJ cases remain covered. |
| D2-R7-04 / D2-R8-04 — FIXED | `docs/ux-maps/render_ux_maps.py:481`: universal-newline decoding precedes source hashing. The same LF-to-CRLF mutation that previously changed the digest now leaves it unchanged. |
| D2-CX-01 / D2-R8-05 — FIXED | `docs/ux-maps/workbench-operator-loop.md:313`: all five original task slices are restored from the donor's original map into JSON and generated Markdown. Each deletion changes the parsed projection, and exact source text is pinned by the test at `js/admin/__tests__/uxmap-render-parity.test.ts:1576`. Exact reducer and per-tag copy is preserved in the independent retained source, including the requested stalled-banner example. |
| D2-R8-06 — FIXED | `docs/ux-maps/render_ux_maps.py:278`: `action_states` and `when` express mutually exclusive recovery cases. Both validators reject extra unconditional primaries, overlapping conditions, and empty/unknown conditions. The extra-primary probe was green before the fix and now rejects the mutation. Generated sketches show the appropriate recovery under each case; the action table carries lossless conditions without reordering existing columns. |

## Verification limits

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
