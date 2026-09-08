# GUIDEDGPU-1 / guidedgpu-1-rev-s2a — adversarial review, slice S2

You are an adversarial reviewer. Refute this slice. Do not admire it. When you are
uncertain whether something is a defect, record it: a false positive costs a paragraph,
a missed defect ships to a public demo.

**Read-only.** Do not edit any file. Do not commit. Do not run the test suite.
`git diff`, `git log`, `grep`, and reading files are all fine.

## The diff under review

Branch `feature/guidedgpu-1`, tip `6638d51324d5b1aa6049bb5428f55a020dbae23b`.
Slice S2 is exactly that commit:

```
git show 6638d5132
```

Three files, nothing else:

- `apps/prototype-wp-alt-context/docs/ux-maps/guided-prototype.md`
- `apps/prototype-wp-alt-context/docs/ux-maps/guided-prototype.uxmap.json`
- `docs/ux-maps/guided-prototype-live-description.md`

## What it is supposed to do

Slice S1 added a live GPU description panel to the guided prototype. This slice is the
documentation half: it maps the new live run into the existing guided-prototype UX map
(prose + machine-readable `.uxmap.json`) and adds an ASCII screen doc for the live panel
across its states.

A UX map is only worth having if it is true. The whole value of this slice is that a
future reader can trust it without opening the code.

## Lenses, in priority order

1. **Truth against the code.** This is the top lens and most of your time belongs here.
   For every state, transition, control, copy string, and node the map claims, open the
   implementation and check it:
   - `apps/prototype-wp-alt-context/js/admin/guidedPrototype/liveDescription.ts` — the
     status constants and the state machine.
   - `apps/prototype-wp-alt-context/js/admin/guidedPrototype/useGuidedLiveDescription.ts`
     — what actually drives transitions, what `canRequest` / `canCancel` gate on.
   - `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedLiveDescriptionPanel.tsx`
     — the rendered controls, the `data-testid` values, and the exact user-facing copy in
     `statusLine()` and `blockedLine()`.
   Any state in the code that is missing from the map, any state in the map that the code
   cannot reach, any transition edge that does not exist, any quoted copy string that does
   not match the source character for character, and any `data-testid` or selector the map
   names that does not exist — each of those is a finding. Quote both sides.

2. **`.uxmap.json` schema conformance.** Compare against the sibling `.uxmap.json` files
   already in the repo and any schema or generator that consumes them
   (`grep -rn "uxmap" --include=*.ts --include=*.py --include=*.json --include=*.md .`
   from the repo root, and check whether a make target or script validates them). Wrong
   key names, a node id referenced by an edge but never declared, duplicate ids, an
   orphan node, or a shape that diverges from its siblings is a finding. If a validator
   exists and this file would fail it, that is a high finding.

3. **Prose and JSON agreeing with each other.** The `.md` and the `.uxmap.json` describe
   the same screen. Where they disagree about states, order, or naming, that is a finding
   — say which one you believe matches the code.

4. **The ASCII screens.** `docs/ux-maps/guided-prototype-live-description.md` renders the
   panel per state. Check that each screen shows a state the code can actually produce,
   that the elapsed-time line only appears in waiting states, that the cancel control only
   appears when `canCancel` is true, and that every status glyph matches `STATUS_ICON`.
   A screen that shows an impossible combination teaches the reader something false.

5. **Accessibility claims.** If the map or screens assert a live region, a label, a focus
   order, or a colour-plus-glyph pairing, verify it against the JSX. An accessibility
   claim that the code does not honour is worse than no claim.

6. **Honesty about the GPU.** The demo is guided teaching material. Any place the docs
   imply the live run is fast, guaranteed, or applied to the draft — when the code says
   cold starts take minutes, degradation to CPU is possible, and nothing is ever applied —
   is a finding.

## Recording findings

Write every finding under `task_ref='GUIDEDGPU-1-REV-r09076638-S2-A'`. That scratch ref is
yours alone and is currently empty. Do not write under any other task_ref, and in
particular never under `GUIDEDGPU-1` itself.

Use the handoff Python API from the package root:

```python
from workbay_handoff_mcp import RuntimeConfig, configure_runtime, review_findings
```

with `review_findings(review={"operation": "batch_record", "session":
"codex-review-r09076638-S2-A", "task_ref": "GUIDEDGPU-1-REV-r09076638-S2-A", "findings":
[...], "actor": {"branch": "feature/guidedgpu-1", "commit_sha":
"6638d51324d5b1aa6049bb5428f55a020dbae23b"}})` — one atomic batch when you have three or
more. Finding ids `GUIDEDGPU-1-REV-r09076638-S2-A-01`, `-02`, and so on. Each needs
`finding_id`, `severity` (high|medium|low), `file_path` (repo-relative), `description`,
and `details` with `line_start`, `line_end`, `fix`.

A description must name the concrete divergence: what the doc says, what the code says,
and where. "The map could be clearer" is not a finding. "The uxmap declares state
`stalled`, but `GUIDED_LIVE_STATUS` in liveDescription.ts:31 has no such member, so an
edge to a node the UI can never render is documented as reachable" is a finding.

Style-only nits are at most `low` and must be prefixed `lint(docs):`.

Finish by reporting the count, the ids and severities, and the single most serious
divergence you found between the map and the code.
