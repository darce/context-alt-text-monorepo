# dux-w2v-d verdicts

Subject: `useBulkReviewCommit.ts` HAI-17 complete mediation (DUX-W2R2-RV-06).
Host: `ReviewQueue.tsx` `isApprovalBlocked` → `assignmentById` + `isStoredFaceApprovalBlocked`.
Network write: `commitOne` = `commitOneNow` → `executeHeldCommit` → `fireCommitApi`. `commitOneNow` has no HAI-17 check of its own.

## Write-path enumeration (every path to POST)

`runSequence` is the only in-hook loop that POSTs. Sole caller: `fireHeldBulk` (:550).
`fireHeldBulk` callers (both `limitToFirstOnly: false`):
1. `armBulkTimer` timeout — ordinary hold expiry.
2. `awaitBulkIdleOrFlush` when `phase===HOLDING` — forced flush (concurrent single Accept/Reject, navigate-after-flush).

Direct POST, bypassing `runSequence`:
3. Unmount-while-holding drain (:887) — `commitOneRef.current` for `drainItems[0]` only.

Hold openers (POST happens later via 1 or 2, or 3 on unmount):
4. `initiateBulk` → `openBulkHold(items)` (`pinItems=false`). Tray Accept.
5. `initiateBulkFromItems` → `openBulkHold(nextItems, true)` (`pinItems=true`). Close-match confirm.
6. `retryBulk` → `initiateBulk()`. Partial-failure Retry.

Not this sequencer (no `runSequence` / `initiateBulk*`):
- Per-card Yes/No → `scheduleAccept`/`scheduleReject` (single hold). SuggestionCard disables Yes when `approvalRequiresReview`.
- Keyboard: no identity-clusters shortcut reaches this sequencer (`WorkbenchTwoPaneLayout` keydown is splitter-only).
- Select-all: none on this surface. `SelectToggle` → `toggleSelect` only. MediaSelection "select all" is a different page.

## Dominance of the approval re-check

`itemsAreApprovalBlocked` (:390-397) reads `isApprovalBlockedRef.current` (assigned every render). Missing function → `items.length > 0` (fail-closed). Else `items.some(blocked)` (all-or-nothing, not filter).

| Path | Recut at fire | Approval dominates? |
| pinItems=false fireHeldBulk | live selection ∩ `resolveItems` (BR-50/BR-62), then check | YES :548 `toCommit = blocked ? [] : items` immediately before `runSequence` |
| pinItems=true fireHeldBulk | NO selection/filter recut (`held.items` snapshot) | YES :548 still runs on the pinned set — original hole closed |
| awaitBulkIdleOrFlush | same fireHeldBulk | YES |
| bulkHoldPaused (hover) | pause only delays timer; fire still fireHeldBulk | YES; check is live ref, not initiate snapshot |
| initiateBulk | n/a (no POST) | YES :623 preview + :666 post-flush live resolve |
| initiateBulkFromItems | n/a (no POST) | YES :695 + :728 (snapshot minus flushed single) |
| retryBulk | then initiateBulk | YES :825 on `resolveItems(selectedIdsRef)` then initiateBulk's gates |
| unmount drain | pinItems skips recut like fireHeldBulk | YES :878-884 `typeof blocked!=='function' \|\| drainItems.some(...)` then maybe first id |

Live vs snapshot: `HeldBulk.items` is initiate-time ids/kind/label. The predicate is not snapshotted. Host `isApprovalBlocked` closes over live `assignmentById` (`flattenAssignmentSuggestions(data.reviewItems)`) and `reviewedStoredFaceSuggestionIds`. Mid-hold refetch that flips `identityCount`/presence is visible at fire/drain.

retryBulk widening: `isIdSelectable` is false only during HOLDING/COMMITTING, so PARTIAL_FAILED allows selection growth. Guard is on the resolved retry set; a later-selected blocked id fails :825. Post-flush initiateBulk re-resolves `selectedIdsRef` and checks again. FireHeldBulk checks a third time. No unguarded `initiateBulk` after PARTIAL_FAILED.

Fail-closed unknown: helper does not consult `assignmentById`. Production host returns `true` when `assignmentById.get(id)` misses (queued-but-unloaded race: `resolveBulkItems` uses `queueBySuggestionId`, so the id still reaches the predicate). Unknown is blocked, not permitted.

All-or-nothing: `.some()` then empty `toCommit` / early return. Mixed blocked+clear POSTs nothing. Not `.filter()` of the clear subset.

`react-hooks/exhaustive-deps` missing `isBulkActiveRef` at :679 / :741: those callbacks write the busy latch (`isBulkActiveRef.current = true`). A stale ref object could desync single-vs-bulk busy detection. It cannot skip `itemsAreApprovalBlocked` (via `isApprovalBlockedRef`). Not a HAI-17 bypass.

FINDINGS_BEGIN
FINDING: DUX-W2R2-RV-06
VERDICT: sustained
EVIDENCE: Original check-once/use-many is impossible on every bulk POST. Network writes from this hook are only (1) runSequence←fireHeldBulk and (2) unmount drain commitOne. fireHeldBulk always applies itemsAreApprovalBlocked on the final fire-time set immediately before runSequence (:548), including pinItems (pinned set is not selection/filter recut, but IS approval-checked via live isApprovalBlockedRef, not the initiate snapshot). Timer expiry (armBulkTimer) and awaitBulkIdleOrFlush forced flush both call that fireHeldBulk. bulkHoldPaused only defers the same fire. initiateBulk gates at :623 and :666 (live resolve after flush). initiateBulkFromItems gates at :695 and :728 then openBulkHold(..., true). retryBulk gates resolved retry items at :825 then initiateBulk (not unguarded). Unmount drain re-checks isApprovalBlockedRef with .some() on the full drain set then POSTs at most item 0. Keyboard/select-all do not reach this sequencer. Helper is .some() all-or-nothing; missing predicate fail-closes non-empty sets; host unknown assignmentById → true (blocked). commitOneNow itself is ungated — complete mediation is the sequencer + host predicate.
FINDING: DUX-W2V-D-NEW-1
VERDICT: sustained
EVIDENCE: no new defect. Hold-mutation coverage exists: DUX-W2R2-RV-06 timer-expiry test mutates blockedIds after phase===holding then expireBulkHold(); forced-flush test mutates then awaitBulkIdleOrFlush(); pinned group-accept test mutates then expireBulkHold(); unmount-drain test mutates then unmount(). All assert zero POSTs / all-or-nothing idle. [TEST-06] [TEST-15]
FINDINGS_END
