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
- Renderer (read-only reference): `apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.py`. It cannot render a new map (Build 8). Read its first 60 lines to confirm that, and do not run it for `fir-bench`.

## Build

1. Jobs, at minimum: "decide whether a model change is real", "find where faces are lost", "compare two runs", "label occlusion from pixels".
2. Screens: S1 verdict, S2 curves, S3 pair cells, S4 stages, S5 failures, S6 compare, S7 clusters, S8 frames & power, L1 label queue. Add overlays and exits only where a flow needs them.
3. States for every screen: `default`, `empty`, `error`. Add the bench-specific states:
   - `unratified`, `inconclusive` (showing its `InconclusiveReason` text verbatim), `unresolvable_fpir` (display state for an FPIR point below 3/n_eff; the primary point's verdict reason is `primary_fpir_unresolvable`), `incompatible_runs`, `projection_unavailable`
   - for L1: `skipped_nonresponse` is the only item state the annotator sees. `blind_repeat` and `gold_item` are internal states. They are never rendered to the annotator, and no label, glyph, header or tooltip on L1 shows them.
4. Flows: verdict → pair cell → failures → back (sort and filter kept, INT-25); compare refused → reason → exit (INT-24); label → add missed face → next.
5. Each zone names the canon row it serves: VIZ-23, VIZ-32, VIZ-35, VIZ-40, VIZ-41, VIZ-24, EXP-31, INT-21 to INT-25, PERC-10, FORM-11, VIZ-18, VIZ-19, WRIT-81. Colour states always pair with glyphs.
6. Use only fields the Design Canvas schema accepts. The plugin maps carry extensions (`screens[].action_states`, `actions[].when`) that the canvas parser rejects as `extra_forbidden` (verified 2026-10-14 on `febt-1-job-error-states`). Leave them out so the critique can parse this map.
7. `code_ref` values point to the future modules (`apps/prototype-description-service/scripts/eval_harness/firbench_report.py`, `benchmarks/tools/fir_occ_label_queue.py`).
8. Rendering is out of this lane. The repository renderer cannot take a new benchmark map: its visible-map registry and contracts file are global, `fir-bench` is not registered, and it writes a global visible snapshot. Do not run it for `fir-bench` and do not edit it or the plugin's contracts and snapshot files. The coordinator renders the committed JSON with the canvas CLI: `ux-map render --path benchmarks/ux-maps/fir-bench.uxmap.json --format markdown`, which writes `benchmarks/ux-maps/fir-bench.md`. This lane does not hand-write the `.md`. A `--check` of an already registered map (for example `febt-1-job-error-states`) is not evidence that `fir-bench` renders.

## Critique

Commit on the lane branch and do not push (README rule 2). The coordinator runs the critique on the committed map, because the critique CLI is not installed on the VM:

```
uv run --directory /Users/daniel/Development/agentic-protocol-monorepo/packages/mcp-workbay-canvas ux-map critique --path <worktree>/benchmarks/ux-maps/fir-bench.uxmap.json --workspace-root <worktree>
```

Fix high and medium critique findings in one follow-up turn. Record the disposition in the notes file.

## Done when

The map loads against the Design Canvas schema, the coordinator's canvas render writes `fir-bench.md`, and the coordinator critique shows no high findings. The lane's disposition goes in `W2-uxmap-notes.md`.
