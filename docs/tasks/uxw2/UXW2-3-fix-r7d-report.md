# UXW2-3-fix-r7d report

Commits by subject. Suite green. No 40-hex SHAs.

## Gate

From `apps/prototype-wp-alt-context` at the last code commit:

```
Test Files  211 passed (211)
      Tests  2426 passed (2426)
```

`npm run typecheck` (`tsc --noEmit --project tsconfig.type-check.json`) — exit 0.

## Items

| Finding | Commit subject | Proving test | Verbatim RED | GREEN |
| --- | --- | --- | --- | --- |
| UXW2-3-R1-02 | `fix(fe): UXW2-3-R1-02 Library rename invalidates roster.entries` | `successful Library rename invalidates roster.entries (UXW2-3-R1-02)` | `expected "invalidateQueries" to be called with arguments: [ { queryKey: [ 'roster', …(1) ] } ]` | 1 passed / 7 skipped |
| UXW2-3-R1-16 (h) | `test(fe): UXW2-3-R1-16 stub members query in heading test` | `headline uses plain language: Review these faces (UXW2-3 / NAV-13)` | n/a (stub only) | 1 passed / 20 skipped; RQ undefined-data stderr gone |

Subjects verified with `git log --format=%s --fixed-strings --grep="<subject>"` (one hit each).

Final HEAD: recorded by the integrator in the canonical worktree after transplant.

## 1. UXW2-3-R1-02 — Library rename invalidates roster.entries

Shape **(1)**: add `queryKeys.roster.entries()` to `invalidateQueries` in `useClusterMutations.ts:54`. Not folded into `invalidateSuggestionProjection`.

Why not (2): the seam (`suggestionProjection.ts:320-323`) invalidates only `queryKeys.suggestions.projection.all`. Production callers besides this hook:

- `ClusterReviewPanel.tsx:91` — member removal. No new roster person.
- `ClusterLabelingPanel.tsx:142/:153/:272` — already invalidates `roster.entries()` itself (`:141`).
- `useSuggestionReviewMutations.ts:298/:767/:1007` — mixed accept/reject/bulk. One path already invalidates roster; others do not create a person.
- `useClusterActions.ts:125/:188/:201/:216` — roster-page cluster actions; that file already invalidates `roster.entries()` on the commit path (`:127`).

Folding roster into the seam would extra-refetch on member removal and on suggestion reject — callers this lane did not test. Panel (`ClusterLabelingPanel.test.tsx:1325`) and queue-card (`PersonCommitControl.test.tsx:308`) keep their own keys. Three call sites stay independent.

Shared `invalidateQueries` also runs on merge/split/reassign/reject from this hook. Extra roster refetch there is the cost of (1); it does not create a second person.

Queue-card matcher (`PersonCommitControl.tsx:74`) uses `staleTime: 30_000`. Without this invalidate, a Library-created name is invisible there for up to 30s and a second roster row is born.

Presence assert (`suggestionProjectionInvalidation.test.tsx:256`, `:284`) matches the panel/queue-card pattern: `toHaveBeenCalledWith({ queryKey: queryKeys.roster.entries() })`. Filter selected 1 test.

TDD RED (assertion present, production missing the key; 5 calls: media.identities, clusters.labels, clusters, suggestions.projection, suggestions.merge):

```
AssertionError: expected "invalidateQueries" to be called with arguments: [ { queryKey: [ 'roster', …(1) ] } ]
```

GREEN: `Tests  1 passed | 7 skipped (8)`.

TEST-15 mutant: remove `useClusterMutations.ts:54`. Same filter, 1 failed. Same RED line. Restore: `git diff` on that file shows only the added roster line.

## 2. UXW2-3-R1-16 (h) — stub members query in the heading test

`ClusterReviewPanel.test.tsx:258`. Heading assertion unchanged (`:263-265`). Added `mockResolvedValue(makeClusterMembersResponse())` (`:259`) using the file helper (`:245`).

Before stub (filter selected 1 test; assertion still passed):

```
Query data cannot be undefined. Please make sure to return a value other than undefined from your query function. Affected query key: ["clusters","members","cluster-123"]
Query data cannot be undefined. Please make sure to return a value other than undefined from your query function. Affected query key: ["clusters","members","cluster-123","live-target"]
```

After stub: that RQ stderr is gone. Same heading still found. Test name already cites NAV-13 (canon: controlled vocabulary before label freeze); copy not changed.

No TEST-15 (no production mutant). No UX-map edit (no user-facing surface change).

## Undone

- Handoff MCP / `workbay_handoff_mcp` Python package unavailable in this throwaway mirror. No `record_event`. This report is the lane record.
- `invalidateSuggestionProjection` still does not touch roster. Intentional (shape 1). `ClusterReviewPanel` member-removal still does not invalidate `roster.entries()`.
- Naming controls (`NameFaceControl.tsx`, `PersonCommitControl.tsx`, `ClusterLabelingPanel.tsx`, `ClusterEditForm.tsx`) not edited. Concurrent lanes own those.
- No browser-level duplicate-person repro. Proof is the presence assert, not a 30s staleTime e2e.
- Queue-card `staleTime: 30_000` (`PersonCommitControl.tsx:74`) left as-is. Invalidate-on-success is the fix, not shortening staleTime.
