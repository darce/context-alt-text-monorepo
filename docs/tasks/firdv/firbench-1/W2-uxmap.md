# W2 · ux-map for the FIR bench report and label queue

- **Wave:** W2 · **Model:** gpt-6.1-sol xhigh, standard tier · **Depends on:** plan v3
- **Owned paths:**
  - `benchmarks/ux-maps/fir-bench.uxmap.json`
  - `benchmarks/ux-maps/fir-bench.md` (rendered)
  - `docs/tasks/firdv/firbench-1/W2-uxmap-notes.md` (critique disposition, ≤ 60 lines)

## Goal

Make the screen, zone, state, action and flow inventory the single source for S5 and S7 before any UI code exists. The ASCII drafts in the task plan § Screens are seeds; the map is the authority.

## Read first

- Task plan § Screens (S1–S8, L1) and § "Canon checks"
- Schema example: `apps/prototype-wp-alt-context/docs/ux-maps/febt-1-job-error-states.uxmap.json`. Top-level keys: `map_ref`, `product`, `source_fixture`, `goals`, `jobs`, `screens`, `actions`, `flows`, `open_questions`, `not_doing`.
- Renderer: `apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.py`. It honours the `UX_MAPS_DIR` env var. Read its first 60 lines and its `--check` mode before rendering.

## Build

1. Jobs, at minimum: "decide whether a model change is real", "find where faces are lost", "compare two runs", "label occlusion from pixels".
2. Screens: S1 verdict, S2 curves, S3 pair cells, S4 stages, S5 failures, S6 compare, S7 clusters, S8 frames & power, L1 label queue. Add overlays and exits only where a flow needs them.
3. States for every screen: `default`, `empty`, `error`. Add the bench-specific states:
   - `unratified`, `inconclusive` (showing its `InconclusiveReason` text verbatim), `unresolvable_fpir` (display state for an FPIR point below 3/n_eff; the primary point's verdict reason is `primary_fpir_unresolvable`), `incompatible_runs`, `projection_unavailable`
   - for L1: `blind_repeat`, `gold_item`, `skipped_nonresponse`
4. Flows: verdict → pair cell → failures → back (sort and filter kept, INT-25); compare refused → reason → exit (INT-24); label → add missed face → next.
5. Each zone names the canon row it serves: VIZ-23, VIZ-32, VIZ-35, VIZ-40, VIZ-41, VIZ-24, EXP-31, INT-21 to INT-25, PERC-10, FORM-11, VIZ-18, VIZ-19, WRIT-81. Colour states always pair with glyphs.
6. Use only fields the Design Canvas schema accepts. The plugin maps carry extensions (`screens[].action_states`, `actions[].when`) that the canvas parser rejects as `extra_forbidden` (verified 2026-10-14 on `febt-1-job-error-states`). Leave them out so the critique can parse this map.
7. `code_ref` values point to the future modules (`apps/prototype-description-service/scripts/eval_harness/firbench_report.py`, `benchmarks/tools/fir_occ_label_queue.py`).
8. Render: `UX_MAPS_DIR=benchmarks/ux-maps python3 apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.py fir-bench`, then the same command with `--check`. The renderer imports `workbay_canvas_mcp`; W2 inventory § Renderer says whether that works on the VM from an external directory. If the renderer refuses, stop and report the exact error; do not edit the renderer or the plugin's contracts and snapshot files. The coordinator then renders with the canvas CLI (`ux-map render --path ... --format markdown`). No parity gate covers `benchmarks/ux-maps/`, so either renderer's format is acceptable.

## Critique

The coordinator runs the critique after you push, because the critique CLI is not installed on the VM:

```
uv run --directory /Users/daniel/Development/agentic-protocol-monorepo/packages/mcp-workbay-canvas ux-map critique --path <worktree>/benchmarks/ux-maps/fir-bench.uxmap.json --workspace-root <worktree>
```

Fix high and medium critique findings in one follow-up turn. Record the disposition in the notes file.

## Done when

The map loads, the render and `--check` pass, and the critique shows no high findings.
