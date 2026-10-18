# UXW2-6 slice 3 report

Lane: PART A (BR-01 / BR-02) then slice 3 group accept of close matches. Frontend only.

Commits (by subject only):

- `fix(workbench): UXW2-6 naming is cluster-wide and only the review chip opens it`
- `feat(workbench): UXW2-6 Yes offers to accept N close matches with preview`

---

## PART A — review findings

### BR-01 (high) — naming panel stated a falsehood

A name commit is one `schedulePersonCommit` / `commitClusterToRosterEntry` write. Every member is labelled. The UI said faces were omitted because it capped `runSize` at 25.

**Fix:** removed the cap-and-truncate framing from the naming path.

- Deleted `REVIEW_GROUP_NAME_CAP` and `reviewGroupNameScope` from `reviewQueueDriver.ts`.
- Removed the truncation paragraph and `runSize` prop from `LightboxNameFace.tsx`.
- Replaced the saved announcement with `LIGHTBOX_NAME_SAVED_ANNOUNCE`: "Name saved for this person's review group." No count — the client does not have the cluster's true member count and must not invent one from `runSize`.

The 25-cap now lives on the group-accept path (PART B), where the frontend issues one write per suggestion and can actually stop at 25.

### BR-02 (medium) — naming opened for the wrong face

`FaceLightbox` passed `onActivate={onReviewFaceActivate}` into `FaceOverlayLayer`, so curated chips and uncurated markers also opened the review-group name form.

**Fix:** `FaceOverlayLayer` gained `onReviewActivate`, used only by the "?" chip. `FaceLightbox` wires `onReviewActivate={onReviewFaceActivate}` and does not pass `onActivate`. Curated/uncurated chips no longer open naming.

### Tests deleted (false truncation copy)

These asserted the lie. They had to go with the copy.

| Test | Why deleted |
| --- | --- |
| `LightboxNameFace` "shows an explicit truncation signal when the group is larger than 25" | Asserted "Naming the first 25 faces… N more were not included." |
| `LightboxNameFace` "does not show truncation when the group fits in the cap" | Guard for that false paragraph. |
| `reviewGroupNameScope` "includes the full run when it is at or below the cap" | Naming-path cap helper. |
| `reviewGroupNameScope` "caps at 25 and reports how many were omitted" | Naming-path cap helper. |
| `ReviewQueue` "surfaces truncation when the same-group run is larger than 25" | Asserted the false lightbox paragraph. |

### Tests added / updated (PART A)

- `FaceLightbox` "does not invoke onReviewFaceActivate when a curated chip is activated"
- `FaceOverlayLayer` review chip now asserts `onReviewActivate` (not `onActivate`)
- `LightboxNameFace` "does not claim faces were omitted from a cluster-wide name save"
- `LightboxNameFace` "announces that the name applies to this person's review group without a count"
- `ReviewQueue` "names the reviewed face…" now expects the honest announcement (was "Name saved for 2 faces.")

---

## PART B — slice 3 group accept

Yes on an assignment now offers to also accept that review group's **close matches** (canonical chip term), with the count, **before any write**.

### File by file

| File | Why |
| --- | --- |
| `reviewQueueDriver.ts` | `REVIEW_GROUP_ACCEPT_CAP = 25` + `closeMatchGroupForAccept`. Group = pending ASSIGNMENT items sharing the accepted item's `clusterId`, excluding that item, passing `matchesSimilarityBand(..., STRONG)`. First 25 kept; `omitted`/`truncated` when more qualify. MERGE/NAME/CLUSTER never enter (`queueItemSimilarity` is undefined). |
| `useBulkReviewCommit.ts` | `initiateBulkFromItems` reuses the existing hold / Undo / single-in-flight / stop-on-first-failure sequencer. `pinItems` skips the live selection ∩ filter re-cut so group ids still fire. No second sequencer, no batch endpoint, no legacy bulk-accept. |
| `CloseMatchAcceptOffer.tsx` | Controlled dialog (`onOpenChange`). Count in the description. Truncation paragraph when capped. Confirm is the single accent primary. Zero count renders nothing. |
| `ReviewQueue.tsx` | Yes with 0 close matches → existing single hold. Else open the offer after the click settles (so Radix does not treat Yes as an outside-dismiss). Confirm → `initiateBulkFromItems([current, ...included])`. Skip → single `scheduleAccept`. Success announces via the polite live region. Card Yes demotes while the offer owns `data-acx-accent-primary`. |
| `_review-queue.scss` | Token-only truncation class for the offer. |
| `banned-vocabulary.test.tsx` | Sweeps offer copy. |

SuggestionCard still only fires `onAccept` once. The offer lives in ReviewQueue because it needs the queue, not the card.

---

## RED-first evidence

### PART A (before production existed)

| Test | Assertion that failed |
| --- | --- |
| FaceLightbox curated chip | `onReviewFaceActivate` called with `"other"` |
| FaceOverlayLayer keyboard `?` chip | `onReviewActivate` not a function / not called |
| LightboxNameFace honest announce | `LIGHTBOX_NAME_SAVED_ANNOUNCE` was `undefined` |
| ReviewQueue "names the reviewed face…" | live region still said "Name saved for 2 faces." |

### PART B (before production existed)

| Test | Assertion that failed |
| --- | --- |
| `closeMatchGroupForAccept` suite | `closeMatchGroupForAccept is not a function`; `REVIEW_GROUP_ACCEPT_CAP` undefined |
| `initiateBulkFromItems` suite | `initiateBulkFromItems is not a function` |
| CloseMatchAcceptOffer collect | failed to resolve import `../CloseMatchAcceptOffer` |
| ReviewQueue "offers the close-match count…" | `Unable to find role="dialog" name "Accept close matches?"`; Yes went straight to hold |

---

## Mutate-and-restore proofs

Each line was broken, the named test went RED, then the file was restored.

| Proof name | Production line broken | Test that went RED |
| --- | --- | --- |
| `FaceLightbox-onActivate-leak` | `onReviewActivate={onReviewFaceActivate}` → `onActivate={onReviewFaceActivate}` | `does not invoke onReviewFaceActivate when a curated chip is activated` (called with `"other"`) |
| `review-chip-onActivate` | review chip `onReviewActivate` → `onActivate` | `renders a keyboard-operable ? chip` (`onReviewActivate` call count 0) |
| `LIGHTBOX_NAME_SAVED-count` | honest copy → `'Name saved for 2 faces.'` | `announces that the name applies…` |
| `REVIEW_GROUP_ACCEPT_CAP-25-to-10` | cap `25` → `10` | `caps at 25 and reports how many close matches were not included` |
| `pinItems-stillSelected` | fireHeldBulk ignored `pinItems` and filtered by live selection | `pinned group-accept items fire even when resolveItems would drop them` (got `[]`) |
| `CloseMatch-hide-truncation` | `{truncated ?` → `{false && truncated ?` | `surfaces an explicit truncation signal` / ReviewQueue cap test |
| `closeMatch-skip-strong-band` | band predicate short-circuited with `false &&` | `uses the strong band helper…` included `sugg-weaker`; ReviewQueue weaker test expected 1, got 2 |

---

## Gates

From `apps/prototype-wp-alt-context`.

| Gate | Result |
| --- | --- |
| Baseline (this branch before this lane) | vitest **225** files / **2619** tests; typecheck 0; phpunit **1942** / **9558** |
| Intermediate after PART A | **not a full-suite rerun.** Related files: ReviewQueue 105 (was 106), driver 40 (was 42), LightboxNameFace 4 (net 0: −2 +2), FaceLightbox 13 (was 12). Net **−2 tests**, same file count → **225 / 2617** inferred. typecheck exit **0**. |
| Final after PART B | `./node_modules/.bin/vitest run` exit **0** — **226** files, **2637** tests (+1 file CloseMatchAcceptOffer.test.tsx, +20 tests: driver +4, bulk +3, offer +6, ReviewQueue +6, SuggestionCards +1). `npm run typecheck` exit **0**. `./vendor/bin/phpunit` exit **0** — **1942** tests, **9558** assertions (unchanged). |

Deleted tests accounted above. No pre-existing test was weakened to go green.

---

## Gaps (do not understate)

1. **Handoff MCP / Python API** is not importable in this clone; `make context` has no target. No `record_event` was written. This markdown file is the reviewer channel.
2. **Intermediate vitest count after PART A was inferred** from related-file runs, not a full `vitest run`. Final full suite is 226 / 2637.
3. **Radix dialog warning** `Missing Description or aria-describedby={undefined}` still appears in jsdom for FaceLightbox and the new offer. Both dialogs have `DialogDescription` + `aria-describedby`. Close/Esc/focus trap work.
4. **Offer open is deferred one timeout** after Yes so the opening click is not an outside-dismiss. Esc/overlay still cancel with no write; "Just this one" accepts only the current suggestion.
5. **`.lane/`** and `gate1.out` are untracked and were not committed.
6. No PHP, no Python, no new REST endpoint, no shared-contract change.
