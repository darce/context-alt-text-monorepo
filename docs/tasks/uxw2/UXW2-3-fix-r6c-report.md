# UXW2-3-fix-r6c report

Commits by subject. Suite green. No 40-hex SHAs.

## Gate

From `apps/prototype-wp-alt-context` at the last code commit:

```
Test Files  211 passed (211)
      Tests  2423 passed (2423)
```

`npx tsc --noEmit --project tsconfig.type-check.json` — exit 0.

## Items

| Finding | Commit subject | Proving test | Verbatim RED | GREEN |
| --- | --- | --- | --- | --- |
| UXW2-3-R1-06 | `test(fe): UXW2-3-R1-06 page sweep reads accessible-name copy` | `renders DashboardPage without banned jargon`; `demonstrates failure when jargon is injected into the DOM` | See mutants below | sweep 31 passed (after item 4) |
| UXW2-3-R3-17 | `test(fe): UXW2-3-R3-17 fixtures enter their named states` | `ClusterLabelingPanel error`; `PersonCommitControl loading`; `ReviewQueue pending` | See per-fixture REDs | all three entered named state |
| UXW2-3-R3-27 | `fix(fe): UXW2-3-R3-27 suggestion row fills then Save commits` | `suggestion row click fills the name and does not commit (UXW2-3-R3-27)` | `expected "vi.fn()" to be called with arguments: [ 'Person B' ]` / `Number of calls: 0` | ClusterEditForm 28 passed |
| UXW2-3-R3-23 | `test(fe): UXW2-3-R3-23 guard workbench-2pane operator copy` | `workbench-2pane operator-visible copy has no retired vocabulary (UXW2-3-R3-23)` | `Cluster list: expected 'Cluster list' not to match /\bclusters?\b/i` | guard 1 passed; open_questions/not_doing still name `cluster` |

Final HEAD: recorded by the integrator in the canonical worktree after transplant.

## 1. UXW2-3-R1-06 — page sweep reads accessible-name copy

`collectVisibleText` deleted. `PAGE_SWEEP` (`banned-vocabulary.test.tsx:627`) and the injection meta-test (`:637`) both call `collectReviewSurfaceText(container)` (`:629`, `:645`). Injection is now `aria-label="topology backlog leak"` (`:641`) so the demo uses the same attribute path as the sweep.

Pre-change: `aria-label="cluster topology"` on Dashboard People stat — `renders DashboardPage without banned jargon` **passed** (blind `textContent`).

TEST-15 after the switch, same mutant, same filter (1 test / 29 skipped):

```
AssertionError: expected 'alt contextalt context dashboardmonit…' not to contain 'topology'
```

Received included `cluster topology`. Restore: production `DashboardPage.tsx` clean.

### Violations the widened collector surfaced

**BANNED_STRINGS hits on PAGE_SWEEP pages: none.** Suite stayed green. Did not stop after item 1.

Surfaced by the collector (now in the same string as titles) but **not** a `BANNED_STRINGS` hit, so the page sweep does not fail:

| File | Attribute | String | Action |
| --- | --- | --- | --- |
| `DashboardPage.tsx:166` | `title` | `Clusters that have been matched to a person.` | Left. Not owned. Not a concurrent-lane file. |
| `DashboardPage.tsx:175` | `title` | `New clusters waiting for your review and labeling.` | Left. Same. |

Those titles appeared in the TEST-15 received blob. They are retired operator vocab (`cluster`) but PAGE_SWEEP still only bans `BANNED_STRINGS` (topology/replay/projection/…). Not weakened.

Attribute copy that would fail a `cluster`/`instance` sweep if those surfaces were mounted (empty Roster fixture does not mount them):

- `PersonFaceFilmstrip.tsx:86` `aria-label` `Face instances for Cluster %d`
- `PersonWorkspacePanel.tsx:265` `aria-label` `Assigned cluster evidence`
- `ClusterDrawerPanel.tsx:419` `aria-label` `Choose a target cluster`

None of those are concurrent-lane files. None are in this lane's Ownership list. Not fixed.

## 2. UXW2-3-R3-17 — fixtures enter their named states

Edited the test file only. Components untouched.

| Fixture | Outcome |
| --- | --- |
| `'error'` | **Entered named state.** `mockReturnValue` (not Once) with `isError: true` (`:819`). Asserts `acx-cluster-members-error` + `Unable to load these faces` (`:1027`, `:1030`). |
| `'commit-loading'` | **Entered named state.** Hangs `listRosterEntries` (`:833`) so `NameFaceControl` stays on roster-loading (`Loading people…`, `:1034`). Not renamed. Distinct from `'commit-pending'` (`phase="committing"`). |
| `'queue-pending'` | **Entered named state.** Explicit never-resolving fetches (`:809`). Pins `.acx-review-queue--loading` + `Loading review queue…` (`:1052`, `:1055`). Global hang already did this; it is now intentional. Not renamed. |

RED vs old fixture setup (assertion present, old wiring):

- `'error'` with no error mock: `error fixture must enter the members-error state: expected null to be truthy`
- `'commit-loading'` + `waitFor(/Loading people/)` against idle/resolved roster: waitFor timeout, text stays `Name this person` / `Save name`
- `'queue-pending'` after durable empty mocks + empty settled: `queue-pending fixture must enter the loading branch: expected null to be truthy`

## 3. UXW2-3-R3-27 — suggestion row fills; Save commits

Canon (grep-verified): [INT-07] preview before commit; [HAI-12] output is a proposal; [A11Y-18] reversible, checked, or confirmed.

`handleOptionConfirm` fills (`ClusterEditForm.tsx:151`, `:155`). Save/Enter still commits; a matching stashed suggestion still threads `clusterId` / `suggestion_id` on that explicit control.

Existing tests that encoded click-to-commit (updated, not worked around):

- `calls onLabelChange when a suggestion is clicked, and onConfirmSuggestion when confirm is clicked` — body now matches the name: click fills, Save unwraps
- `unwraps cluster: namespaced values on confirm` — Save after fill
- `threads option.suggestion_id into onConfirmSuggestion (BR-16 / L1R-01)` — Save after fill

New test `ClusterEditForm.test.tsx:97`. Filter selected 1 test.

TEST-15: restore immediate `onConfirmSuggestion` / `onSave` on row click:

```
AssertionError: expected "vi.fn()" to be called with arguments: [ 'Person B' ]

Number of calls: 0
```

Restore: production `ClusterEditForm.tsx` is the fill path only.

Person-row click still commits immediately inside `NameFaceControl.tsx:321` (`onCommit` on person source). That file is a concurrent-lane exclusive. Not edited.

## 4. UXW2-3-R3-23 — UX map vocabulary guard

Guard in the sweep file (`:1091`). Operator-visible keys only: `title` / `label` / `purpose` / `verb` / `goals` / `description` / `branch_label`. Exempt (`:595`): `id`, `url_params`, `code_ref`, `open_questions`, `not_doing`.

No operator-visible field still on cluster/identities/embeddings. Map + sibling `.md` not rewritten.

TEST-15: `z-cluster-list` label → `Cluster list`:

```
AssertionError: Cluster list: expected 'Cluster list' not to match /\bclusters?\b/i
```

Same test stays GREEN with `open_questions` / `not_doing` untouched (`workbench-2pane.uxmap.json:705`, `:714` still name `cluster`). Restore: map `git diff` empty.

## Undone

- Dashboard `title` copy at `DashboardPage.tsx:166` and `:175` still says `Clusters…`. Widened collector sees it. `BANNED_STRINGS` does not. File not owned.
- Roster accessible-name leftovers (`PersonFaceFilmstrip.tsx:86`, `PersonWorkspacePanel.tsx:265`, `ClusterDrawerPanel.tsx:419`) not mounted by the PAGE_SWEEP empty Roster fixture. Not owned.
- Person-row click-to-commit remains in `NameFaceControl.tsx:321`. Concurrent lane owns that file. Cluster/suggestion rows only are fill-then-Save.
- Handoff MCP and `workbay_handoff_mcp` Python package are unavailable in this throwaway mirror. No `record_event`. This report is the lane record.
- `PAGE_SWEEP` still does not ban `cluster` / `identity` / `instance` (those stay on `BANNED_REVIEW_SURFACE_WORDS` for review-surface fixtures). Extending the page sweep is a different finding.
