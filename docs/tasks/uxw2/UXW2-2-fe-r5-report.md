# UXW2-2 FE r5 report

Cite commits by subject. Subjects verified with `git log --format=%s --fixed-strings --grep="<subject>"` (count 1 each). File:line cites re-derived with `sed -n '<N>p'` after the last code commit.

Canon (grepped): DATA-14, TEST-06, TEST-15, A11Y-04, A11Y-21, RLSE-04. Project guards used: rg-015.

## Closed

| Finding | Subject | RED (verbatim) |
|---|---|---|
| R8-01 / R7-03 | `fix(fe): UXW2-2-R8-01 derive gated servedCount from page zeros` | `Unable to find an element with the text: 3 groups missing face data. This could be because the text is broken up by multiple elements. In this case, you can provide a function for your text matcher to make your matcher more flexible.` |
| R8-02 | `fix(fe): UXW2-2-R8-02 latch repair announce on the message` | `Expected element to have text content: 2 groups elsewhere are missing face data` / `Received: 7 groups elsewhere are missing face data` |
| R8-02 follow | `fix(fe): UXW2-2-R8-02 re-announce repair copy without first-mount drain` | UI-04 hold stayed on the card when first-mount empty always announced |
| R8-03 | `fix(fe): UXW2-2-R8-03 bulk-accept refetches when response has no ids` | `expected [] to deeply equal [ 'name-1', 'name-2' ]` |
| R5-09 | `fix(fe): UXW2-2-R5-09 distinct accessible names for Resync controls` | `Unable to find role="button" and name /^Resync findings$/` |
| R5-08 | `docs(ux-maps): UXW2-2-R5-08 inventory z-identity-preview states` | no mutant; state list below |

## Cites (sed after last code commit)

- `WorkbenchFindingsPanel.tsx:434` `zeroEvidenceClusterCount,` — servedCount is page-local gated clusters, not evidence-preview length (DATA-14).
- `WorkbenchFindingsPanel.tsx:431` `repairGatedCount(zeroEvidenceClusterCount, counts.unlabeledClusters)` — unlabeled total only when this surface served no chips.
- `WorkbenchFindingsPanel.tsx:471` `aria-label={__('Resync findings', 'alt-context')}` (A11Y-04; visible `Resync` stays in the name).
- `representativeVocabulary.ts:13` `repairGatedCount` — prefers page zeros over server-wide unlabeled.
- `representativeVocabulary.ts:20` `if (servedCount === 0)`.
- `ReviewQueue.tsx:294` boolean enter-guard latch kept; `:295` `repairAnnouncedMessageRef` holds the announced sentence (A11Y-21).
- `ReviewQueue.tsx:594` `repairCopyChanged` re-enters when repair wording changes and the surface is actually announcing repair.
- `ReviewQueue.tsx:1366` `aria-label={__('Resync review queue', 'alt-context')}`.
- `useSuggestionReviewMutations.ts:1016` `onSuccess: (data) => {` — no id list on `BulkAcceptResponse`; refetch instead of evicting by `matched.length` (rg-015, DATA-14).
- `workbench-operator-loop.uxmap.json:110` `z-identity-preview` states (RLSE-04).

## TEST-15 mutants

- R8-01 servedCount forced to `0` → `Unable to find an element with the text: 3 groups missing face data`.
- R8-01 delete `servedCount === 0` arm → `Unable to find an element with the text: 5 groups elsewhere are missing face data`.
- R8-01 swap `repairGatedCount` args → `Unable to find an element with the text: 3 groups missing face data` and `expected 7 to be 3`.
- R8-02 drop `repairCopyChanged` (boolean enter-guard only) → `Expected element to have text content: 2 groups elsewhere are missing face data` / `Received: 7 groups elsewhere are missing face data`.
- R8-03 restore `matched.length === data.accepted_count` eviction → `expected [] to deeply equal [ 'name-1', 'name-2' ]`.
- R5-09 drop findings `aria-label` → `Unable to find role="button" and name /^Resync findings$/`.
- Restores: production diffs after each mutant were the intended fix only.

## R5-08 `z-identity-preview` states

Before: `["default", "empty", "loading"]`

After: `["default", "empty", "loading", "error", "degraded", "unavailable", "repair", "zero_evidence"]`

`code_ref` added to `WorkbenchFindingsPanel.tsx`. Sibling renders (`workbench-operator-loop.uxmap.md`, `workbench-operator-loop.md`) updated.

## Suite

`npx vitest run` from `apps/prototype-wp-alt-context`:

`Test Files  212 passed (212)`
`Tests  2401 passed (2401)`

`npm run typecheck` clean (`tsc --noEmit --project tsconfig.type-check.json`).

Final HEAD: recorded by the integrator in the canonical worktree after transplant.

## Undone

- First-mount true drain is still visual-only. Announcing it doubles `REVIEW_QUEUE_DRAIN_MESSAGE` and broke `getByText` plus the UI-04 accept hold. AT hears drain only after leaving an item or leaving repair.
- Boolean enter-guard remains; the message ref only re-opens the repair-copy arm. A future collapse to one string latch must re-prove UI-04.
- `BulkAcceptResponse` still has no accepted ids. Full accept invalidates; the hook test has no observer, so the header count stays at the pre-accept cache until a real refetch. ReviewQueue still has no chrome that calls `mutations.bulkAccept`.
- `data-findings-state` is still `loading|error|unavailable|degraded|empty|data`. Map `repair` / `zero_evidence` / `default` are zone inventory, not attribute values.
- R5-11 / R3-11 i18n literal msgids were out of this brief and stay open.
