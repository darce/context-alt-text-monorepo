# UX-map rendering sources

`<map_ref>.uxmap.json` owns the machine inventory. `render_ux_maps.contracts.json`
owns the retained vocabulary, operator, and reducer sections and their heading anchors,
including recovery tables and exact operator copy. Edit these sources deliberately in
review, then run `render_ux_maps.py`. The renderer never imports retained content from
the generated Markdown or rewrites the contract source when refreshing visible snapshots.
Both `--check` paths compare retained sections with this independent authority.

Local schema extensions are rendered outside the upstream canvas model:

- `slices` is an ordered list rendered as the suggested task-slice decomposition.
- A screen's `action_states` enumerates mutually exclusive recovery cases. An action's
  `when` selects cases from that screen; omission means always available. At most one
  primary action may be available in each case. Empty or unknown conditions fail
  validation. In the request-error map, `http` means a non-cooldown HTTP failure and
  `http_cooldown` means `http` with `isCooldown`; neither introduces a new AppError tag.

The Python and TypeScript width calculations share Python-generated Unicode property
ranges. Run `sync_unicode_width.py --write` to explicitly update the committed fixture
for a Unicode-version change, then `sync_unicode_width.py --check` and the parity tests.

Run `python3 -m unittest discover -s docs/ux-maps -p test_render_ux_maps.py` from the app
directory for the renderer boundary mutation probes. The Vitest parity suite runs them
as well. Only a missing top-level canvas package permits the dependency-free snapshot
check; import failures within an installed renderer fail closed.
