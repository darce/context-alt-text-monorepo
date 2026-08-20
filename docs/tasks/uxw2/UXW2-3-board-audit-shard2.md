# UXW2-3 board audit — shard 2 of 3

Read-only re-anchor of shard findings against this checkout HEAD. Line numbers re-derived with `sed -n` immediately before this file was written. Fix subjects from r2/r3 lane reports are **not** present as standalone commits here (squashed into the feature mirror); **Fixed by** is omitted unless `git log --format=%s --fixed-strings --grep` matched.

### UXW2-3-R1-02 — PARTIAL

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/PersonCommitControl.tsx:115`
- **Evidence:** Race/gate half is gone. Commit bails while the roster is unsettled:

```
    if (isBusy || rosterQuery.isLoading || rosterQuery.isError) {
```

Error notice at `:164`/`:167`: `rosterQuery.isError` → `role=alert` copy `Unable to load people. Retry before naming someone new.` Loading disables the control (`:187` `isLoading={rosterQuery.isLoading}`). Tests in `PersonCommitControl.test.tsx:245` pin loading (`Loading people…`) and error. Panel success invalidates roster + projection (`ClusterLabelingPanel.tsx:141`/`142`). Residual: `useClusterMutations.ts:50-56` still has no `queryKeys.roster.entries()` (no `roster` token in that file). Library rename can still leave the matcher stale for `staleTime` 30s.
- **Fixed by:** not a standalone subject on this transplanted history
- **Reasoning:** PersonCommitControl duplicate-create race is gone; the compounding invalidation claim is only half-done.

### UXW2-3-R1-06 — PARTIAL

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/__tests__/banned-vocabulary.test.tsx:560`
- **Evidence:** Headline “cannot fail” is gone. Review collector at `:564` concatenates `textContent` plus `aria-label`/`title`/`alt`/`placeholder`/`aria-description`. Mutant pin at `:715`: `aria-label="Open cluster"` must match `/\bcluster\b/i`. `it.each` at `:721-735` mounts NameFaceControl, ClusterEditForm, PersonCommitControl, SuggestionCards, TopClusterCard, ReviewQueue, ClusterActions, IdentityClusterItem. Identity-cluster-item fixture clicks `Remove from group` so the dialog is on `document.body`. Residual: `collectVisibleText` at `:560` is still `container.textContent ?? ''` (PAGE_SWEEP). `reservedLabel.ts` is not imported. Hook mock `:517` is `truncated: false` (show-all never swept). `MergeSuggestionCard` is not in the `it.each` list. ClusterReviewPanel default mount at `:709` does not open the removal dialog.
- **Fixed by:** not a standalone subject on this transplanted history
- **Reasoning:** The sweep can now go red on AT attributes and on the listed surfaces; the original gap list is not fully closed.

### UXW2-3-R1-09 — FIXED

- **Anchor now:** `docs/tasks/uxw2/UXW2-3-fix-lane-report.md:3` (root `REPORT.md` absent)
- **Evidence:** `test ! -f REPORT.md` → confirmed absent. Replacement at `docs/tasks/uxw2/UXW2-3-fix-lane-report.md:3`: `Lane cwd. Commits cited by subject line only.` Final HEAD at `:81-83` is a subject line, not a 40-hex. Task plan exists (`docs/tasks/uxw2/UXW2-3-one-naming-surface-task-plan.md:32` slices ticked). Grep of `docs/tasks/uxw2/` for the cited fabricated tokens (`24f894a`, `b26e682`, `e2f6a0a`, and the named 40-hex Final HEAD) returned no hits.
- **Fixed by:** not a standalone subject on this transplanted history
- **Reasoning:** The unverifiable provenance artifact is gone; current reports cite subjects. This does not re-validate every historical RED sentence.

### UXW2-3-R1-13 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterEditForm.tsx:103`
- **Evidence:**

```
        if (sameFoldCount <= 1 && folded === normalizeNameFaceLabel(prefillRef.current)) {
          return;
```

Enter on an unchanged prefill that case-folds to a unique roster person no-ops. Pin: `ClusterEditForm.test.tsx:44` `no-ops Enter when the resolved name matches the prefill (UXW2-3-R1-13)` — `onSave`/`onPersonSelect` not called.
- **Fixed by:** not a standalone subject on this transplanted history
- **Reasoning:** The old “alice + Enter against Alice writes a rename” path is gone. Same-fold count >1 still binds (R3-12).

### UXW2-3-R2-01 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/NameFaceControl.tsx:250`
- **Evidence:** Overlay is query-filtered then budgeted:

```
  const matchingOptions = React.useMemo(() => matchingOptionsFor(options, value), [options, value]);
  const displayedOptions = React.useMemo(
    () => budgetOverlayOptions(matchingOptions),
```

`matchingOptionsFor` at `:141` substring-filters by folded label. Row confirm at `:321` binds the chosen `rosterEntryId`, not a folded re-resolve. Pin: `NameFaceControl.test.tsx:154` `typed Zed shows Zed Offslice; typed Gra does not`.
- **Fixed by:** not a standalone subject on this transplanted history
- **Reasoning:** The static first-5 dump and folded-label deadlock are gone in this control. Caller drop of the id is R3-12.

### UXW2-3-R2-05 — FIXED

- **Anchor now:** `docs/tasks/uxw2/UXW2-3-fix-lane-report.md:1`
- **Evidence:** Report lives at `docs/tasks/uxw2/UXW2-3-fix-lane-report.md`, not repo root. `:3` cites subjects only. Task plan at `docs/tasks/uxw2/UXW2-3-one-naming-surface-task-plan.md:32-37` is present and ticked (`[x]`). Grep for the named absent SHAs (`86d3bb89` / `34d61916` / `40fe0a1b`) in `docs/tasks/uxw2/` returned no hits.
- **Fixed by:** not a standalone subject on this transplanted history
- **Reasoning:** Second-strike provenance issues on the r2 report are gone in the current files. Historical GREEN-paste accuracy is not re-proven here (audit did not run the suite).

### UXW2-3-R2-08 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/docs/ux-maps/workbench-2pane.uxmap.json:13`
- **Evidence:** Labels/verbs no longer say Cluster/identities:

```
      "label": "Build & recognize face groups (refresh groups, run recognition)"
```

`:17` `Name & curate people…`; `:33` `face-group/recognize/name/curate`; `:148` `Face-group/recognition controls`. Remaining `cluster` tokens are ids / `url_params` / job ids, which the sibling render’s Vocabulary section explicitly allows.
- **Fixed by:** not a standalone subject on this transplanted history
- **Reasoning:** The SSOT label/verb drift the finding named is gone. Ids were not the claim.

### UXW2-3-R3-03 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/NameFaceControl.test.tsx:55`
- **Evidence:** Default harness no longer injects `onOptionConfirm`:

```
  if (!('onOptionConfirm' in overrides)) {
    delete props.onOptionConfirm;
```

Caller pins exist: `ClusterEditForm.test.tsx:121`, `ClusterLabelingPanel.test.tsx:1130`. Production person rows in `NameFaceControl.tsx:316-323` bind via `onCommit` before the `onOptionConfirm` branch at `:325`.
- **Fixed by:** not a standalone subject on this transplanted history
- **Reasoning:** The structural hide is gone. Those caller tests still assert a **name**, not `rosterEntryId` — that remaining hole is R3-12, not this harness bug.

### UXW2-3-R3-06 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterLabelingPanel.tsx:698`
- **Evidence:** Rename anyway no longer calls `mutateAsync` directly:

```
                    void submitLabel(duplicateGuard.label, { skipDuplicateGuard: true });
```

`submitLabel` latches `submittingRef` at `:338`. Pin: `ClusterLabelingPanel.test.tsx:1186` `two rapid Rename anyway clicks fire the mutation once`.
- **Fixed by:** not a standalone subject on this transplanted history
- **Reasoning:** The warned-path double-submit is on the same latch as Save/Enter.

### UXW2-3-R3-09 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterActions.tsx:74`
- **Evidence:** Live copy rewritten:

```
          {__('Remove from group', 'alt-context')}
```

`:86` `Split group`. `IdentityClusterItem.tsx:76` `Unnamed person`; `:411`/`:413` `Remove this face from the group`; `:420` `Remove member`. Both components are in the banned-vocab `it.each` (`banned-vocabulary.test.tsx:734-735`).
- **Fixed by:** not a standalone subject on this transplanted history
- **Reasoning:** The four operator-facing strings the finding named are gone. JSDoc/comments still say “Split cluster”; that is not visible text.

### UXW2-3-R3-12 — PARTIAL

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterLabelingPanel.tsx:390`
- **Evidence:** Bypass half is gone: `NameFaceControl.tsx:321` person rows `onCommit({ kind: 'roster', rosterEntryId, name })` and **return** before `onOptionConfirm` at `:325`. Drop-id half remains. Panel:

```
      void submitLabel(resolution.name, { skipPersonOnlyGuard: true });
```

Library: `ClusterEditForm.tsx:107` `onPersonSelect(resolution.name)`. Tests named “roster id” assert labels: `ClusterEditForm.test.tsx:138` `toHaveBeenCalledWith('ALEX CARTER')`; `ClusterLabelingPanel.test.tsx:1173-1176` `updateClusterLabel(..., 'Alex\tCarter', ...)`. PersonCommitControl is still the only write that keeps `rosterEntryId`.
- **Fixed by:** not a standalone subject on this transplanted history
- **Reasoning:** Chosen-row **name** is preserved; numeric id never reaches the panel/Library write. Do not close as FIXED.

### UXW2-3-R3-15 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/styles/components/_name-face.scss:87`
- **Evidence:** Hidden reject is out of the hit-test:

```
    pointer-events: none;
```

Reveal on row hover/active (`:44-47`) and `:hover`/`:focus-visible` restores `pointer-events: auto`. Markup: `NameFaceControl.tsx:566` `tabIndex={-1}` on the reject `<button>` (sibling of `role=option`, not tabbable). Pin: `name-face-surface.test.ts` `the hidden suggestion-reject is not click-targetable`.
- **Fixed by:** not a standalone subject on this transplanted history
- **Reasoning:** Opacity-0 tap-to-destroy and listbox tab stop are gone. Touch still has no hover; with `pointer-events: none` that tap is a no-op, not a silent reject.

### UXW2-3-R3-18 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterActions.tsx:74`
- **Evidence:** Same live strings as R3-09 (`Remove from group` / `Split group` / `Unnamed person` / `Remove this face from the group`). Sweep mounts both components (`banned-vocabulary.test.tsx:734-735`) and opens the item removal dialog.
- **Fixed by:** not a standalone subject on this transplanted history
- **Reasoning:** Duplicate of R3-09 against current code; both closed.

### UXW2-3-R3-21 — PARTIAL

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/ClusterLabelingPanel.test.tsx:1210`
- **Evidence:** Coverage expanded: `:1186` Rename anyway, `:1210` “second checkmark”, `:1237` “second option selection”, plus the original Enter/Enter case. Named mutant still would not go red: `handleOptionConfirm` (`ClusterLabelingPanel.tsx:411-416`) and `handleSelectOption` (`:418-457`) no longer write (cluster rows only `setDuplicateGuard`; person rows go through `onCommit` → `resolveCommit`). No test double-clicks the Save name button.
- **Fixed by:** not a standalone subject on this transplanted history
- **Reasoning:** “Only Enter/Enter is tested” is false now; the specific TEST-15 mutant the finding named is still insensitive, and Save is still unpinned.

### UXW2-3-R3-24 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/docs/ux-maps/workbench-2pane.uxmap.json:188`
- **Evidence:** `z-name-curate` states now include the three shipped ones:

```
            "roster-error",
            "ambiguous",
            "overlay-closed"
```

Sibling render `workbench-2pane.md:88-89` lists the same three. Old anchor `:170` is now `z-cluster-list`, not this zone.
- **Fixed by:** not a standalone subject on this transplanted history
- **Reasoning:** Map/render catch up to roster-error / ambiguous / overlay-closed.

### UXW2-3-R3-27 — OPEN

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterEditForm.tsx:132`
- **Evidence:** Row click still writes immediately (no fill-then-review):

```
        onConfirmSuggestion(clusterId, option.label, suggestionId);
```

Else `onSave(option.label)` at `:134`. Test `ClusterEditForm.test.tsx:97` title still says “calls onLabelChange when a suggestion is clicked”; body `:114` `expect(onLabelChange).not.toHaveBeenCalled()` and then `onConfirmSuggestion`. No undo on this path.
- **Fixed by:** n/a
- **Reasoning:** The claimed behaviour is still the code. A later lane report marked this wontfix; that is a board policy call, not a code change. Keep OPEN until the board records wontfix.

## Tally
FIXED: 10 | OPEN: 1 | PARTIAL: 4 | INVALID: 0 | MOVED: 0

## Undone

- R1-02: add `queryKeys.roster.entries()` to `useClusterMutations.invalidateQueries`.
- R1-06: sweep `reservedLabel.ts`; `truncated: true` show-all; mount `MergeSuggestionCard`; open ClusterReviewPanel removal dialog; PAGE_SWEEP still `textContent`-only.
- R3-12: panel/Library writes are still label strings; `rosterEntryId` never leaves NameFaceControl on those callers.
- R3-21: pin Save-button double-submit; the handleOptionConfirm/handleSelectOption mutant is still green because those paths do not write.
- R3-27: still immediate commit on Library suggestion click (wontfix proposed, not recorded on the board).

## New observations

- `ClusterEditForm.test.tsx:97` test title claims `onLabelChange` is called on suggestion click; the assertion at `:114` is the opposite. Stale title, not a product bug.
- Tests titled “binds that roster id” / “carries that id into the write” (`ClusterEditForm.test.tsx:121`, `ClusterLabelingPanel.test.tsx:1130`) assert distinctive **labels**, not `rosterEntryId`. They cannot fail a write that drops the id and keeps the chosen name.
- `handleSelectOption` (`ClusterLabelingPanel.tsx:418-457`) ends in `setDuplicateGuard` / `setDuplicateGuard(null)` — no mutation. Future double-submit mutants aimed at that function will stay green.

Final HEAD: recorded by the integrator in the canonical worktree after transplant.
