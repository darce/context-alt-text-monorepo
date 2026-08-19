# UXW2-4-R7b — ux-map SSOT parity + PHP report restore

## Result

Owned ux-map JSON/MD pairs now match. `z-review-cta` has a `code_ref`. Invented `z-review-name` is gone. PHP-lane section restored at the canonical task-doc path. A vitest render-parity guard pins the two owned maps.

Final HEAD: recorded by the integrator in the canonical worktree after transplant.

Rendered sibling for `workbench-operator-loop.uxmap.json` is `workbench-operator-loop.md` (ASCII screen boxes). `workbench-operator-loop.uxmap.md` is a starter inventory, not the render; left untouched.

`file:line` cites below were re-derived with `sed -n '<N>p' <file>` after the last commit.

## Gate

From `apps/prototype-wp-alt-context`:

```
Test Files  209 passed (209)
      Tests  2344 passed (2344)
```

`npm run typecheck`: clean (`tsc --noEmit --project tsconfig.type-check.json`).

Targeted: `npx vitest run js/admin/__tests__/uxmap-render-parity.test.ts -t 'every json screen and zone label'` → **1 / 1** (`Test Files  1 passed (1)` / `Tests  1 passed (1)`).

PHP untouched; `composer test` not run.

## Closure

| ID | Disposition | Evidence |
| --- | --- | --- |
| R4-04 | **fixed** | `roster-people.md` re-derived from JSON. Mechanical extras beyond the four brief rows: full evidence-thumb label, unicode `→` on the CTA, `first_time` untruncated, purpose strings, action/flow verbs. |
| R2-19 | **fixed** (split) | Jargon half already in JSON this lane (not renamed here). Stale MD = R4-04. Missing `code_ref` added. |
| R4-03 | **fixed** | `z-review-name` deleted. `ClusterReviewPanel.tsx` has no name input. MD re-rendered without `Name control`. |
| R2-15.1 | **already-closed-with-evidence** | `UXW2-4-fe-report.md` closure table carries `R1-15` through `R1-31` verbatim (`sed -n '44,60p'`). |
| R2-15.2 | **already-closed-with-evidence** | `UXW2-4-fe-report.md` 40-hex count **0**. |
| R2-15.3 | **fixed** | PHP section landed at `docs/tasks/uxw2/UXW2-4-php-report.md`. Root `REPORT.md` not recreated. Historical blob does not resolve in this clone; body recovered from the r4 historical reconstruction of that same section. Subjects only; no 40-hex. |
| Item 5 | **fixed** | Owned-map parity test. Repo-wide would go red on `workbench-2pane.md` (9 missing labels, other lane). |

## R4-04 — before / after (md vs json)

No mutant. Strings now match the JSON source.

| Before (stale md) | After (md = json) | JSON source (`sed -n`) |
| --- | --- | --- |
| `Face-group drawer host (other)` | `Face-group drawer host (cluster= shim)` | `roster-people.uxmap.json:95` |
| `Linked identities / faces` | `Linked faces` | `roster-people.uxmap.json:140` |
| `Face-group drawer (shim)` | `Face-group drawer (deep-link shim)` | `roster-people.uxmap.json:176` |
| `Person identity header` | `Person header` | `roster-people.uxmap.json:131` |

MD after (`sed -n`): `roster-people.md:49` host; `:83` Linked faces; `:33` drawer title; `:82` Person header.

## R2-19 — split

JSON already had `Person header` / `Linked faces` (R2-19 jargon). This lane did **not** rename those JSON labels. The md still showed the old operator-facing identities copy until R4-04.

Missing `code_ref` was real. Added:

```
"code_ref": "apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx:215-244"
```

JSON `roster-people.uxmap.json:66`. CTA region `RosterPage.tsx:215` `<section` / `:216` `className="acx-roster__review-cta"` / `:244` `</section>`. Production `.tsx` not edited.

## R4-03 — before / after

| Before | After | Source |
| --- | --- | --- |
| zone `z-review-name` label `Name control` role `form` | deleted | was `workbench-operator-loop.uxmap.json` under `workbench-review-panel` |
| MD ASCII `- Name control (form)` | gone | `workbench-operator-loop.md` review-panel zones are `Header + Back` + `Faces grid` only |

`sed -n`: `workbench-operator-loop.uxmap.json:203-210` `z-review-header` / `z-review-faces`. No `z-review-name` / `Name control` remain.

`ClusterReviewPanel.tsx` is 238 lines. `sed -n '119,130p'`: header + Back + `Review these faces`. No `<input`, combobox, or name field. Name control not moved into production (other lane).

Re-render also put json-already-present scan zones into the md so the guard is green: `Review Suggestions queue header / count`, `Face-group review panel (panel=review&cluster=)`.

## R2-15 — clauses

1. **already-closed-with-evidence.** `sed -n '44,60p' docs/tasks/uxw2/UXW2-4-fe-report.md` is `R1-15` … `R1-31`. Sibling lane owns that file; not edited.
2. **already-closed-with-evidence.** Python `\b[0-9a-f]{40}\b` count on that file: **0**.
3. **fixed.** `git show` of the named historical blob: invalid object in this clone. Recovered PHP section only → `docs/tasks/uxw2/UXW2-4-php-report.md`. Heading `sed -n '1p'`: `# UXW2-4-PHP — persons are the single label authority`. FE half omitted. No 40-hex; commits are subject lines.

## Item 5 — TEST-15 mutant

Scope: `roster-people` + `workbench-operator-loop` only. Repo-wide fails `workbench-2pane.md` (other lane) and the starter `.uxmap.md`.

Mutant: rename `z-entries` label in JSON to `Roster entries table MUTANT`; md untouched. Restore after.

RED verbatim:

```
AssertionError: zone z-entries label "Roster entries table MUTANT" missing from roster-people.md: expected false to be true // Object.is equality
```

Names zone `z-entries`. Restore → targeted **1 / 1** green.

## Files

- `apps/prototype-wp-alt-context/docs/ux-maps/roster-people.uxmap.json`
- `apps/prototype-wp-alt-context/docs/ux-maps/roster-people.md`
- `apps/prototype-wp-alt-context/docs/ux-maps/workbench-operator-loop.uxmap.json`
- `apps/prototype-wp-alt-context/docs/ux-maps/workbench-operator-loop.md`
- `apps/prototype-wp-alt-context/js/admin/__tests__/uxmap-render-parity.test.ts`
- `docs/tasks/uxw2/UXW2-4-php-report.md`
- this file

No `.tsx` / `.ts` / `.php` production edits. `UXW2-4-fe-report.md` not edited. `workbench-operator-loop.uxmap.md` not edited.

## Undone

- `composer test` skipped (PHP untouched).
- Historical root `REPORT.md` blob still does not resolve here; PHP restore is the r4 reconstruction of that section, not a `git show` of the original object.
- Those PHP-lane commit subjects still return 0 hits from `git log --grep` in this clone.
- `ClusterReviewPanel` show-all control and remove-confirm modal are still unmapped (deleted invented name control only).
- `workbench-2pane.md` still missing 9 JSON labels (other lane).
- Name control not added to `ClusterReviewPanel.tsx` (other lane; this lane must not touch `.tsx`).
- `UXW2-4-fe-report.md` sibling-owned; not edited.

## Commits (subjects)

- `docs(uxmap): UXW2-4-R7b render parity, code_ref, php restore`
- this report commit
