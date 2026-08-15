# WBUX-5 Slice 6 roster-hardening gap audit (ROSTER-W-05)

**Status:** audit-only. No production code was changed.  
**Lane:** `e21-19-r3` · **Task:** `E21-19` · **Assignment:** `#653`  
**Anchor:** assignment cited main `04474863134cdf0945c2a4f9e79343ad16da58a9`. This sandbox is history-stripped; files were read at worktree `HEAD` on `feature/e21-19-r3`.  
**Plan:** `docs/tasks/21.0/WBUX-5-workbench-2pane-roster-v1-task-plan.md` Slice 6 (no `slice_complete` decision).  
**Scope:** `apps/prototype-wp-alt-context/js/admin/pages/roster/` (`RosterEntriesSection` / `RosterEntriesTable`, `PersonWorkspacePanel`, `NeedsAssignmentSection`, `ClusterDrawerPanel`, `BulkActionBar`, `IdentityThumbnail`) and `js/admin/styles/components/_roster.scss`.

Slice 6 asked for three load-bearing heuristics. Verdicts below use **LANDED** (cite file+line) / **PARTIAL** / **GAP** (missing behavior + minimal fix + pinning test).

## Verdict table

| Heuristic | Ask | Status | Evidence | Gap / minimal fix | Pinning test |
| --- | --- | --- | --- | --- | --- |
| **INT-06 / A11Y-04** | Smart action labels that **name the person** + disable-on-empty | **PARTIAL** | **Disable-on-empty is landed.** `BulkActionBar` disables merge at `count < 2` and dismiss at `count < 1` (`BulkActionBar.tsx` 98–101, 118–137) and names *count + cluster object* (`Merge %d cluster(s)`, 28–40). `RosterEntriesTable` Save is `disabled={updatePerson.isPending \|\| !name.trim()}` (224–229). `RosterEntriesSection` Create is `disabled={createPerson.isPending \|\| !newName.trim()}` (437–440). Drawer commit is `disabled={!canCommit \|\| isCommitting}` where `canCommit` requires a selected roster id or a non-blank new name (`ClusterDrawerPanel.tsx` 276, 524–528). Pin representative is `disabled={!canPin \|\| isPinning}` (`PersonWorkspacePanel.tsx` 271–274). Workspace region names the person: `Person workspace: %s` (215). **Person-named action labels are not landed.** Directory Edit/Delete use generic `title`s only: `Edit person` / `Delete person` (`RosterEntriesTable.tsx` 258–274). Delete confirm is `title="Delete person"`, `confirmLabel="Delete"` (282–287) — no name. Drawer primary is generic `Confirm Assignment` (536–538); workspace link is `Open person review` (560). Pin copy is `Set as representative` (282). Bulk bar names *clusters*, never a person. Icon-only row actions have no `aria-label`; AT name is the generic `title` (fails A11Y-04 “name states destination/action” for a named person). | Interpolate `entry.name` / selected roster name into accessible names: `Edit %s`, `Delete %s`, `Save changes to %s`, `Assign to %s` / `Confirm assignment to %s`, `Open %s review`, `Set as representative for %s`. Keep current empty-selection disable rules. Add `aria-label` on icon-only buttons so the name is not title-only. | RTL: `RosterEntriesTable` `getByRole('button', { name: 'Edit Alice' })` and delete confirm `Delete Alice`. `ClusterDrawerPanel` after selecting Alice: `getByRole('button', { name: /Assign to Alice/ })`. Extend `BulkActionBar.test.tsx` “accessible names name count + cluster object” only if a person-named bulk path is added; do not weaken the existing count+object pins. |
| **A11Y-14** | **44px** target-size floor on **all** roster controls (stricter HIG; lexicon also allows WCAG 24px) | **PARTIAL** | **24px WCAG floor is landed on some drawer/rail controls, and those controls stay visible (not hover-only).** `_roster.scss`: `.acx-cluster-drawer__move-btn` `min-width/min-height: 24px` (279–284); `.acx-cluster-drawer__move-option` / `__move-cancel` 24px (320–326); face actions `opacity: 1` / `visibility: visible` (274–277); `.acx-needs-assignment__open` 24px (436–438). Filmstrip cells wrap a 64px thumb (`PersonFaceFilmstrip.tsx` 9, 100–110) so those options exceed 44px in practice. Combobox *search input* is `height: 44px` in `_combobox.scss` 55–57 — not `_roster.scss`, and that is the typeahead field, not every roster control. `IdentityThumbnail` has **no CSS floor**; size is a prop (default 96, `IdentityThumbnail.tsx` 51). **44px is not the roster floor.** `.acx-icon-button` is hard-coded `32×32` (`_roster.scss` 172–177) — Edit / Delete / Save / Cancel / Clear / drawer Close. `.acx-button` uses `padding: var(--acx-space-8) var(--acx-space-16)` (203–208) with `--acx-space-8: 0.5rem` and **no** `min-height: 44px` — Add Person, Create, Retry, Confirm Assignment, Set as representative. Directory thumbs are `DIRECTORY_THUMB_SIZE = 32` (`RosterEntriesTable.tsx` 26) (display, not a control). Rail cells have no 44px min (`_roster.scss` 592–605). E2E still asserts the 24px contract: `roster-keyboard-walk.spec.ts` 108–109 (`Move to… min width/height ≥24`). | In `_roster.scss`, set `min-width`/`min-height: 44px` (or a token) on every roster interactive class: `.acx-icon-button`, roster-scoped `.acx-button`, `.acx-cluster-drawer__move-btn` / `__move-option` / `__move-cancel`, `.acx-needs-assignment__open`, `.acx-roster__person-workspace-rail-cell`. Do not leave the 32px icon-button rule in place. If `IdentityThumbnail` is ever the sole hit target (`onClick`), require `size >= 44`. Raise the e2e floor from 24 → 44. | Raise `tests/e2e/a11y/roster-keyboard-walk.spec.ts` bounding-box asserts from 24 to 44 for Move to…, then add the same `boundingBox() >= 44` check for directory Edit/Delete, Add Person, Confirm Assignment, needs-assignment open, and pin. Optional RTL: assert computed `min-width`/`min-height` on those class names so a SCSS revert fails without Playwright. |
| **COG-02** | Recognition-over-recall person picker: **face thumbnail + name in the directory** | **PARTIAL** | **Directory browse path is landed.** Each row renders `DirectoryFace` (representative `IdentityThumbnail`) beside `<strong>{entry.name}</strong>` (`RosterEntriesTable.tsx` 55–94, 250–252). Representative rule is highest `identity_count`, ties `cluster_id` ASC (28–52). Cropped bbox path is wired (83–93). RTL already pins this: `RosterEntries.test.tsx` “directory face thumbnails [COG-02]” (~308+). Search + browse also exist (`RosterEntriesSection.tsx` 342–352) — NAV-10, not scored here. **Assignment picker is name-only.** Drawer `Combobox` options are `{ value: entry.id.toString(), label: entry.name }` with no thumbnail (`ClusterDrawerPanel.tsx` 507–512). `Combobox` already supports `renderOption` (`js/components/ui/combobox.tsx` 80, 233); `ClusterLabelingPanel` uses it, the roster drawer does not. Move-to menu options are cluster text labels only (`ClusterDrawerPanel.tsx` 422–435). 32px directory thumbs are small for recognition but the face is present. | Keep the directory row as the browse picker. For the drawer assignment `Combobox`, pass `renderOption` that renders `IdentityThumbnail` via `selectRepresentativeIdentity(entry)` plus `entry.name`. Optionally raise `DIRECTORY_THUMB_SIZE` to ≥44 so directory faces are easier to recognise (also helps A11Y-14 if thumbs become controls). | `ClusterDrawerPanel.personAware.test.tsx`: open “Assign to…”, assert each roster option exposes an `img` (or placeholder) **and** the person name. Do not regress `RosterEntries.test.tsx` COG-02 directory cases. |

## Control inventory (A11Y-14)

| Control | File | Current target | vs 44px |
| --- | --- | --- | --- |
| Directory Edit / Delete / Save / Cancel | `RosterEntriesTable.tsx` + `.acx-icon-button` | 32×32 CSS | **below** |
| Bulk Clear | `BulkActionBar.tsx` 113 + `.acx-icon-button` | 32×32 | **below** |
| Drawer Close | `ClusterDrawerPanel.tsx` ~350 + `.acx-icon-button` | 32×32 | **below** |
| Add Person / Create / Retry / Confirm Assignment / Set as representative | `.acx-button` in `_roster.scss` | padding 8/16, no min 44 | **below** (typically ~36px tall) |
| Move to… / move options | `_roster.scss` 279–326 | min 24×24 | **WCAG ok, HIG fail** |
| Needs-assignment open | `_roster.scss` 436–438 | min 24×24 | **WCAG ok, HIG fail** |
| Person-workspace filmstrip option | `PersonFaceFilmstrip.tsx` 9, 100 | 64px thumb | **meets 44 in practice** |
| Combobox typeahead input | `_combobox.scss` 55–57 | height 44 | **meets**, not roster-owned |
| `IdentityThumbnail` | size prop | 32 directory / 96 default / 128 drawer | not a control unless `onClick` |

## Already landed (not in the three-heuristic ask)

Observed while reading the same files; do not treat as Slice-6 complete:

- MECE person states named / unnamed / needs-review with icon+text (`personState.ts`, `RosterEntriesTable.tsx` 97–134, `_roster.scss` 143–169) — NAV-05 / PERC-02.
- Search people (`RosterEntriesSection.tsx` 342–352) — NAV-10.
- Designed zero-state + always-visible Add Person (`RosterEntriesSection.tsx` 327–338, 463+).
- Cluster drawer (not a tab) with keyboard Move to… (`ClusterDrawerPanel.tsx` 397–446) — A11Y-15 click/keyboard alternative for drag.
- Person-workspace evidence + every-reference surfaces (`PersonWorkspacePanel.tsx` 251–349) — HAI-01 / HAI-17.

## Recommended next implementation slice

One roster-hardening slice, still extend-not-absorb:

1. Person-named `aria-label`s on Edit / Delete / Save / Confirm Assignment / Open review / Pin; keep disable-on-empty.
2. `_roster.scss` 44px min on every roster interactive class listed above; bump e2e from 24 → 44.
3. Drawer `Combobox.renderOption` = face + name (reuse `selectRepresentativeIdentity`).

Do not record Slice-6 `slice_complete` until those three land with the pinning tests above.
