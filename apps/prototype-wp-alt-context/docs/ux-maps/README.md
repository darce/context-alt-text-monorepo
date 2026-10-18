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
The fixture records `unicode_version`. The check reports version mismatches explicitly;
identical property ranges pass, while changed ranges require deliberate regeneration.

The Vitest suite uses the absolute `ACX_UXMAP_PYTHON` override when set, otherwise the
repository-root `.venv/bin/python`. A missing interpreter fails with instructions to set
the override; the suite never searches PATH for Python. Use a Python interpreter with the
fixture's Unicode properties (currently Unicode 15.0.0) for reproducible verification.
From the app directory, run the same checks with that interpreter:

```sh
uxmap_python="${ACX_UXMAP_PYTHON:-$(git rev-parse --show-toplevel)/.venv/bin/python}"
"$uxmap_python" docs/ux-maps/render_ux_maps.py --check
"$uxmap_python" docs/ux-maps/sync_unicode_width.py --check
"$uxmap_python" -m unittest discover -s docs/ux-maps -p 'test_*.py'
./node_modules/.bin/vitest run js/admin/__tests__/uxmap-render-parity.test.ts
./node_modules/.bin/tsc --noEmit -p tsconfig.json
```

The Vitest parity suite runs both Python mutation suites as well.
Only a missing top-level canvas package permits the dependency-free snapshot
check; import failures within an installed renderer fail closed.
