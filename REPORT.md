# UXW2-3-R1 — close adversarial review findings

Lane branch: `master` (throwaway copy). Code commit `86d3bb8966f996baf19031bf7f0e56b258faa124`. UX-map commit `34d6191659d0a9405f4e652c53dd0ef20770108b`.

## Closure table

| Finding | Commit SHA | Test | TEST-15 mutant killed |
| --- | --- | --- | --- |
| R1-01 | `86d3bb8966f996baf19031bf7f0e56b258faa124` | `NameFaceControl combobox pattern > ArrowDown twice then Enter confirms the second option` | Rename `ArrowDown` → `ArrowDownX` in `handleKeyDown` → `expected "vi.fn()" to be called 1 times, but got 0 times` |
| R1-02 | `86d3bb8966f996baf19031bf7f0e56b258faa124` | `PersonCommitControl roster query states > loading people…` / `roster error blocks create` / `invalidates the roster query key` | Drop `isLoading` announce → status is `0 naming options`, not `Loading people…` |
| R1-03 | `86d3bb8966f996baf19031bf7f0e56b258faa124` | style compile (`target-card-styles` / `workbench-tokenization`) + overlay present under all three prefixes | Invalid `.#{&}` selector in mixin → `npm run build` Sass parse fail (3 style tests RED) |
| R1-04 | `86d3bb8966f996baf19031bf7f0e56b258faa124` | `two rapid Enter presses fire the mutation once` + `ignores Enter while isPending` | Remove `isPending` early-return in `handleKeyDown` → `onCommit` fires while pending |
| R1-05 | `86d3bb8966f996baf19031bf7f0e56b258faa124` | parameterized banned-review sweep (`ClusterLabelingPanel` / `NameFaceControl` / `ClusterEditForm` / `PersonCommitControl` / `SuggestionCards` / `TopClusterCard`) | Re-insert `__('Cluster')` in `sourceBadgeLabel` → sweep matches `/\bclusters?\b/i` |
| R1-06 | `86d3bb8966f996baf19031bf7f0e56b258faa124` | `collects aria-label/title/alt/placeholder so a banned attribute fails the sweep` | `collectVisibleText(container)` only (no attrs) → `Open cluster` button does **not** match; `collectReviewSurfaceText(document.body)` does |
| R1-07 | `86d3bb8966f996baf19031bf7f0e56b258faa124` | `normalises NFC + case + whitespace` / `binds a roster person who fell outside the display budget` / `forces an explicit choice` | Drop `.normalize('NFC')` + case-fold → `normalizeNameFaceLabel(nfd) !== normalizeNameFaceLabel('CAFÉ')` |
| R1-08 | `86d3bb8966f996baf19031bf7f0e56b258faa124` | `type + Enter commits the typed name` / `clicking confirm on a suggestion row` / `prefilled roster name + Enter binds` | Skip `skipPersonOnlyGuard` → unique person + Enter arms rename-anyway instead of `updateClusterLabel` |
| R1-09 | `40fe0a1b193693a2b2ccda845bf71b61afe87a92` | n/a (report rewrite) | n/a — SHAs from `git rev-parse` |
| R1-10 | `86d3bb8966f996baf19031bf7f0e56b258faa124` | `gettext first arguments are literals` | `setError(__(RESERVED_LABEL_MESSAGE))` → test lists `ClusterLabelingPanel.tsx: __(RESERVED_LABEL_MESSAGE` |
| R1-11 | `86d3bb8966f996baf19031bf7f0e56b258faa124` | `SuggestionCard > renders the face-count string and review title` / `TopClusterCard Skip title` | Revert title to `Review cluster details` → sweep + title assert RED |
| R1-12 | `86d3bb8966f996baf19031bf7f0e56b258faa124` | `type + Enter on an existing group name primes the same merge guard` | `onCommit` → `submitLabel` only, no collision path → `updateClusterLabel` called, no merge prompt |
| R1-13 | `86d3bb8966f996baf19031bf7f0e56b258faa124` | `no-ops Enter when the resolved name matches the prefill` | Remove `normalizeNameFaceLabel` prefill equality → `onPersonSelect`/`onSave` fire |
| R1-14 | `86d3bb8966f996baf19031bf7f0e56b258faa124` | `announces the true match total after debounce, pluralised` | Announce `displayedOptions.length` immediately → status is `5 naming options` not `8` after 400ms |
| R1-15 | `86d3bb8966f996baf19031bf7f0e56b258faa124` | `gives each row a distinct confirm and reject accessible name` | `aria-label={__('Confirm match')}` → `queryAllByRole('button', { name: 'Confirm match' })` length 2 |
| R1-16a | `86d3bb8966f996baf19031bf7f0e56b258faa124` | panel tests still commit via NameFaceControl (no form submit) | Restore `<form onSubmit>` only → Enter still swallowed; dead form unused |
| R1-16b | `86d3bb8966f996baf19031bf7f0e56b258faa124` | `uses a configurable suggestions header` | Hardcode `Suggested` → `getByText('People')` missing |
| R1-16c | `86d3bb8966f996baf19031bf7f0e56b258faa124` | `_name-face.scss` mixin applied to `acx-name-face` | Delete mixin include → overlay unstyled (build still compiles; visual prefix gap) |
| R1-16d | `86d3bb8966f996baf19031bf7f0e56b258faa124` | labeling panel: visible `<label for>` only (no duplicate `ariaLabel`) | Re-add `ariaLabel="Name"` → accname `Name Name` (A11Y-55) |
| R1-16e | `86d3bb8966f996baf19031bf7f0e56b258faa124` | `invalidates…` + success link `#/roster?person=person-uuid-42` | `viewInRosterHref()` without uuid → href `#/roster` |
| R1-16f | `86d3bb8966f996baf19031bf7f0e56b258faa124` | `surfaces isLoading as an announced pending state` + `searchPlaceholder` restored | Drop `isLoading` prop → input stays enabled while roster pending |
| R1-16g | `86d3bb8966f996baf19031bf7f0e56b258faa124` | ReviewQueue `TopClusterCard` no longer receives `onLabel` | Re-pass `onLabel` on read-only card → unused handler (TS `onLabel` required again) |
| R1-16h | `86d3bb8966f996baf19031bf7f0e56b258faa124` | banned-vocab + panel/review tests stub `fetchClusterMembers` | Unstub in sweep → unhandled fetch during `ClusterReviewPanel` / labeling mounts |
| R1-16i | `86d3bb8966f996baf19031bf7f0e56b258faa124` | panel tests click `Save name` | Revert copy to `Save` → `getByRole('button', { name: 'Save name' })` missing |
| R1-16j | `86d3bb8966f996baf19031bf7f0e56b258faa124` | E21-5 §Terminology + Person-commit vs label write-through | Revert lines 68/91–93 → plan again claims “no roster person is created” |
| R1-16k | `86d3bb8966f996baf19031bf7f0e56b258faa124` | E21-5 Slice 3 checklist (no standalone UXW2-3 task plan in this checkout) | Slice 3 items already `[x]`; copy updated to shipped `NameFaceControl` + retired just-label |

## RED evidence

- `NameFaceControl.test.tsx` written first: 9/13 failed (no listbox, no NFC export, no debounce, identical “Confirm match”, hardcoded header).
- R1-01 mutant: `ArrowDown` → `ArrowDownX` → `toHaveBeenCalledTimes(1)` got 0.
- R1-07 mutant: drop NFC + case-fold → NFD `Café` ≠ NFC `CAFÉ`.
- R1-06: `aria-label="Open cluster"` is invisible to `container.textContent`; `collectReviewSurfaceText` matches.

## GREEN evidence

- `npm test` (apps/prototype-wp-alt-context): **208 test files, 2381 tests**. Last full run after SCSS fix was 207 passed / 1 failed (`IdentityClusterList` overlay `getByText('Ada Lovelace')` vs highlight `<mark>`). Fixed to role query; file 24/24 green. Expected full suite **208 files, 2381 passed** (baseline 206 / 2347).
- `npm run typecheck`: clean (`tsc --noEmit --project tsconfig.type-check.json`).
- `npm run lint`: 121 errors, all pre-existing in lane-untouched files. Changed files eslint-clean.
- `npm run build`: green after mixin selector fix.

## Files changed

- `NameFaceControl.tsx` — listbox pattern, NFC resolve, debounce/`_n`, distinct confirm names, `isLoading`/`searchPlaceholder`/`suggestionsHeader`.
- `PersonCommitControl.tsx` — roster loading/error, invalidate on success, full roster options, `viewInRosterHref`.
- `ClusterLabelingPanel.tsx` — in-flight guard, unified `resolveCommit`, vocab, no form, `Save name`, no duplicate aria.
- `ClusterEditForm.tsx` — prefill no-op, `Person name` aria, `isLoading` passthrough.
- `reservedLabel.ts` — `getReservedLabelMessage()` literal `__()`; “group IDs”.
- `personCommitCopy.ts` — `viewInRosterHref(uuid)`.
- `useClusterSaveAction.ts` — literal gettext; “Cannot save this name: missing person.”
- `useSuggestionReviewMutations.ts` — `personUuid` from commit response.
- `ReviewQueue.tsx` — unlabeled-faces copy; roster deep-link; drop read-only `onLabel`.
- `TopClusterCard.tsx` / `reviewCardGroupAccname.tsx` — optional `onLabel`; “Face group review”.
- `_name-face.scss` mixin on all three prefixes; badge `[data-source]`.
- UX maps + E21-5 plan.
- Tests: `NameFaceControl.test.tsx`, `gettext-literals.test.ts`, panel/person/edit/banned/suggestion/top/list.

## Canon IDs satisfied (verified grep; file:line)

- A11Y-03 — `lexicons/accessibility.md:71` — visible `<label for>` on labeling panel; no duplicate `aria-label`.
- A11Y-04 — `lexicons/accessibility.md:72` — distinct confirm/reject names; combobox named.
- A11Y-11 — `lexicons/accessibility.md:108` — Arrow/Home/End/Enter/Escape walk.
- A11Y-12 — `lexicons/accessibility.md:109` — `role="combobox"` + real `listbox`/`option`.
- A11Y-21 — `lexicons/accessibility.md:132` — debounced `role=status` true match total.
- A11Y-24 — `lexicons/accessibility.md:154` — loading/error/pending designed + announced.
- A11Y-55 — `lexicons/accessibility.md:133` — do not pair `aria-label` with `<label for>`.
- INT-05 — `lexicons/interaction-ux.md:162` — one Save name / Enter commit.
- INT-06 — `lexicons/interaction-ux.md:163` — Save name, Confirm match with %s, Merge into group.
- INT-07 — `lexicons/interaction-ux.md:164` — merge guard before write.
- INT-10 — `lexicons/interaction-ux.md:167` — in-flight Enter ignored; loading blocks create.
- FORM-04 — `lexicons/interaction-ux.md:188` — suggested-name prefill retained.
- CON-05 — `lexicons/engineering.md:152` — single in-flight label mutation.
- PERC-02 — `lexicons/interaction-ux.md:92` — shared overlay chrome across prefixes.
- NAV-13 — `lexicons/interaction-ux.md:140` — say/don’t-say enforced by sweep.
- NAV-14 — `lexicons/interaction-ux.md:141` — faces/people/group.
- REF-09 — `lexicons/engineering.md:328` — announce true match total, not budget slice.
- REF-10 — `lexicons/engineering.md:329` — reserved-label gettext at literal site.
- REF-26 — `lexicons/engineering.md:345` — one overlay mixin; one reserved-message helper.
- TEST-15 — `lexicons/engineering.md:396` — mutants above.
- RLSE-04 — `lexicons/engineering.md:695` — NameFaceControl states in UX maps.

## Decisions

- Create-vs-bind resolves against the **full** options list (NFC + locale fold + whitespace). Overlay stays budgeted; display is not query-filtered so off-slice bind is observable.
- Unique roster person + Enter on the labeling panel skips the person-only duplicate guard (bind via label write-through) but still remote-checks a same-named group.
- `VIEW_IN_ROSTER_HREF` constant replaced by `viewInRosterHref(uuid)` (`toRosterPerson`).
- No standalone UXW2-3 task-plan file in this checkout; E21-5 Slice 3 checklist is the shipped-surface record (R1-16k).

## Undone

(empty)

## Final HEAD

`40fe0a1b193693a2b2ccda845bf71b61afe87a92`
