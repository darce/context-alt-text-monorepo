# Post-curation naming — UX map (IDWEAVE-1, ADR-018)

**Status:** Proposed sketch for the implementation task plan. Nothing here has shipped.

**Decision source:** [ADR-018](../../adrs/ADR-018-post-curation-identity-weaving.md).

**Surfaces extended:** [workbench review queue](../../ux-maps/workbench-review-queue.md) and [roster and people](../../ux-maps/roster-people.md). This map adds no new queue, page or poller.

**Example:** 40 photos are described while the roster is empty. Daniel appears in 14 of them, and most of the photos also show people nobody will name.

## Placement

| Need | Where it lives | Why there |
| --- | --- | --- |
| Name a group | Review Queue suggestion card (existing) | Identity truth has one home ([NAV-05]). |
| Leave a group unnamed | The same card. The existing durable dismiss gets new copy. | It gives the group a terminal state, so the group stops coming back ([INT-24]). |
| Re-weave status, pause, retry | Activity status strip (existing `useActivityStatus()` authority), plus a `naming` state | Background work gets quiet status ([NAV-18]), and there is no second poller. |
| Review name proposals | Media queue, as a filter: `?hasDraft=1&proposal=names` | Proposals are drafts, so they need no second queue ([NAV-05]), and the view deep-links ([NAV-11]). |
| Don't name a person in one photo | A proposal row, or the editor correction chip | Disclosure is decided per photo, beside that photo's text ([NAV-19]). |
| Not this person | Proposal row, face grid, editor chip | Identity errors go back to the cluster ([HAI-02]). |
| Consent and pause | Settings, under People in descriptions | Override and operate are separate controls ([HAI-04]). |

## Screens

### S1. First run: generic drafts, with a forward pointer

```text
+-- Workbench · Media queue (Has draft) -------------------------------------+
| Activity: Done · 40 descriptions drafted        [Review drafts] [Dismiss]  |
|                                                                            |
| [ ] [img] IMG_0412.jpg                                                     |
|     Draft: "A man and a woman by a fountain."                              |
|     People: 2 not named                     [Accept] [Edit] [Dismiss]      |
| [ ] [img] IMG_0440.jpg                                                     |
|     Draft: "A man reading on a bench."                                     |
|     People: 1 not named                     [Accept] [Edit] [Dismiss]      |
|                                                                            |
| (i) 31 drafts describe people without names. If you name people in the     |
|     Review Queue, their names are added for your review. Accepting a       |
|     draft now loses nothing.                         [Open Review Queue]   |
+----------------------------------------------------------------------------+
```

- **First success first ([INT-12]).** The generic drafts are usable now. Accepting one makes it machine-owned alt, and later names arrive as proposals.
- **Name the future effect ([HAI-18]).** The ADR placed this copy only at curation time. The first run is where the operator decides whether to accept or wait.
- **One note per run, not one per row ([PERC-07]).**
- **Copy never says "stranger" or "unknown" (ADR rule 5).**

### S2. Name a group, or leave it unnamed

```text
+-- Review Suggestions · Unlabeled group (3 of 9) ---------------------------+
| [face][face][face][face][face] +9                 in 14 photos             |
|                                                                            |
| Who is this?  [ Daniel______________ ]  [Name group]                       |
|               Adds "Daniel" to the descriptions of these 14 photos,        |
|               for your review. Nothing changes until you apply.            |
|                                                                            |
| [Leave unnamed]   [Review these faces]                [Previous] [Next]    |
+----------------------------------------------------------------------------+

after Name group (inline, at the card):
| ✓ Named Daniel. Names for 14 descriptions will be ready to review.        |
|   [View in roster]                                                        |

after Leave unnamed:
| Left unnamed. Its photos keep their current wording.            [Undo]    |
```

- **Leave unnamed.** Today's Skip button runs a durable dismiss (`curation_state='dismissed'`). Its title, though, says "Skip this group for now". The label promises the opposite of the effect ([INT-22]).
  - Rename it to Leave unnamed and offer Undo, which is the existing undismiss.
  - The group then leaves the queue for good, so no group of unknown people comes back every session ([INT-24], [PERC-07]).
- **Counts.** The "14 photos" count has to be known when the operator names the group. This answers the ADR open question: WordPress derives the affected media from its own projection. The service stays the authority for the mirror version.
- **Pronouns.** The copy never assigns a pronoun to the named person. The system does not know it.
- **No-op changes stay quiet.** Leaving a group unnamed changes no text. Its re-weave must yield no proposal and no notice ([INT-20]: a trivial internal update need not interrupt).

### S3. Re-weave status in the activity strip

```text
| Activity: Adding names · 9 of 14 descriptions              [Pause] [Details] |
| Activity: Names ready for 14 descriptions          [Review names] [Dismiss]  |
| Activity: Name updates paused · 3 changes waiting                 [Resume]   |
| Activity: 2 descriptions couldn't get names                [Retry] [Details] |
```

- **Status, next step and stop ([INT-10], [HAI-04]).** Pause is the HAI-04 control that the ADR left without a place.
- **Coalesce.** Naming five people in a row produces one rolling entry, not five. Toasts are already suppressed while the strip is mounted.
- **Manual recovery ([INT-20]).** When the bounded retries run out (rg-007), the item says so and offers Retry. The ADR had bounded retries but no way to recover by hand.
- **Visible mode ([INT-15]).** While paused, the strip says so wherever names would otherwise appear.

### S4. Names to review (media queue filter)

```text
+-- Media queue · Names to review (14) ---------------------------------------+
| Check faces first:                                                          |
| Daniel  [crop][crop][crop][crop][crop][crop][crop] ... 14                   |
|         (select a crop that is not Daniel -> [Not Daniel])                  |
|                                                                             |
| [x] [img] IMG_0412.jpg                        Placed by face position       |
|       A man and a woman by a fountain.                                      |
|     → [Daniel] and a woman by a fountain.     [crop]                        |
|       [Apply] [Edit] [Not Daniel] [Don't name here]                         |
| [x] [img] IMG_0440.jpg                        Only person in photo          |
|       A man reading on a bench.                                             |
|     → [Daniel] reading on a bench.            [crop]                        |
| [x] [img] IMG_0451.jpg                        Named, position not shown     |
|       Three people at a market stall.                                       |
|     → Three people at a market stall. Among those pictured: [Daniel].       |
|                                                                             |
| footer: [Add names to 14 descriptions]                    [Previous] [Next] |
+-----------------------------------------------------------------------------+

after batch apply:
| ✓ Added names to 14 descriptions.                  [Undo all] (rows: [Undo]) |
```

- **Proposal, not answer ([HAI-12]).**
  - Each row is a diff, and the name appears with the crop the weave used.
  - Verification is placed where the risk is (the name span and its crop), not in a standing banner ([HAI-13]).
- **Per-person crop strip.** The question "is this Daniel?" is answered once across all 14 crops. An outlier face stands out in a uniform strip ([PERC-03]). Rubber-stamping row by row is how a wrong name slips through.
- **Three reasons, three actions ([HAI-02], [HAI-11], [INT-19]).**

  | Action | Records | Reaches |
  | --- | --- | --- |
  | Not Daniel | Unbind | The cluster. This also corrects other photos and roster views. |
  | Don't name here | Withhold | This photo only |
  | Edit | A human edit | This text. Later updates arrive as suggestions. |

  In the first draft, a single Reject recorded a withhold. A wrong-identity error would then be filed as a disclosure preference, and the wrong binding would stay live everywhere else.
- **Unsure is allowed ([CAL-10]).** A row left unselected stays a proposal. Nothing forces a match or non-match.
- **Reason chips in plain words.**

  | Chip | Realizer |
  | --- | --- |
  | Placed by face position | grounded |
  | Only person in photo | lone-noun substitution |
  | Named, position not shown | presence |
- **Smart label ([INT-06]).** The batch label carries the selected count and is disabled at zero.
- **Undo ([INT-09]).** Undo restores the previous alt and puts the row back in the list. Undo is not a rejection and records no withhold.

### S5. Removal executes, and Undo reverses the curation

```text
+-- Review these faces · Daniel (14) ----------------------------------------+
| [face][face][face][face][face][face] ...                                   |
|                         selected: 1   [Not Daniel — remove from group]     |
+----------------------------------------------------------------------------+

strip, after removal (no confirm dialog):
| ✓ Removed 1 face from Daniel. IMG_0440's published description no longer   |
|   names Daniel: "A man reading on a bench."                       [Undo]   |
```

- **Removal is the safe direction for privacy.** It runs immediately, with a notice that states the effect on published text ([INT-22], [PERC-05]).
  - There is no per-face confirm dialog. WBTRUST C4 already found per-face confirms costly, and [INT-13] applies.
- **Undo reverses the unbind, not the text.** An undo that only re-applied the old text would publish a name with no binding behind it. Replay would fail (PROV-01), and the next re-weave would remove the name again, so it would flap.
  - The alt text is never edited apart from its source. It follows the weave.

### S6. A human-edited alt gets a suggestion, never a replacement

```text
| [img] IMG_0477.jpg     Alt text (edited by you):                           |
|       "Man in a blue jacket by the Plaza Mayor fountain."                  |
|       Daniel is in this photo. [crop]                                      |
|       [Add Daniel to my text…]  [Don't name here]                          |

after an unbind or a consent-off, when the human text still contains the name:
|       Your text names Daniel, but Daniel was removed from this photo.      |
|       [Edit text]  [Keep my text]                                          |
```

- **Never offer the woven text here.** It is built over the machine base, which the operator has already replaced. Offering it would overwrite their work (ADR-017: human edits are preserved).
  - "Add Daniel to my text…" opens the editor on the operator's own text.
- **Keep my text is a logged override ([HAI-06]).** The text stays human-owned.

### S7. Editor correction chip

```text
| Alt text: [ A man and a woman by a fountain.                         ]     |
|           [Save alt text] [Cancel]                                         |

after Save, where the edit removed a woven name (inline, not a modal):
| You removed "Daniel". Is Daniel in this photo?                             |
|   [Not Daniel — unlink]   [It's Daniel — don't name here]   [Just wording] |
|   Later name updates for this photo will be suggestions.                   |
```

- **Modeless and after save ([INT-13], [INT-28]).** "Just wording" is the default and records nothing.
- **The identity correction reaches the cluster ([HAI-02]).**
- **The effect of becoming human-edited is stated ([HAI-18]).**

### S8. Consent and pause

```text
+-- Settings · People in descriptions ---------------------------------------+
| [x] Add the names of people you named in People to image descriptions      |
|     Names come only from People. People you haven't named are never        |
|     labeled.                                                               |
| Name updates   ● Running   [Pause]                                         |
+----------------------------------------------------------------------------+

on unchecking (rare, consequential, so it confirms):
| Turn off names? 37 published descriptions go back to unnamed wording.      |
| 2 descriptions you edited keep your text and are flagged for review.       |
|                               [Cancel]  [Turn off and remove names]        |
```

- **Mass change to published alt, so preview before commit ([INT-07]).** This is the one confirm in the flow. It is rare and hard to reverse, so it does not habituate ([PERC-07]).
- **Disclosure ([HAI-05]).** The copy says where names come from.
- **Pause and consent are separate.**

  | Control | Effect |
  | --- | --- |
  | Pause | Stops updates ([HAI-04], operate) |
  | Turn off names | Removes names (override) |

## Per-photo naming states

```text
generic draft ──(curation event, mirror ACK)──► names proposal
     │                                          ├─ Apply ──────► machine-owned alt
     │ Accept (generic)                         ├─ Not <name> ─► unbind, re-weave
     ▼                                          ├─ Don't name ─► withhold, re-weave
machine-owned alt ──(curation)──► proposal      ├─ Edit ───────► human-edited alt
     │                                          └─ unselected ─► stays a proposal
     │ removal event ──► auto-revert + notice
     │                   Undo = undo the curation op
     ▼
human-edited alt ──(curation)──► name-only suggestion
                 ──(removal)───► review item
```

## What this walkthrough changed

The screens were drawn after the first ADR draft (`d5fe620`), not before it. These changes come from walking each screen against the canon rows below.

| ADR rule | First draft | Changed to |
| --- | --- | --- |
| 10 | A rejected proposal records a withhold. | Three actions: Not \<name\> (unbind), Don't name here (withhold), Edit (wording). There is no bare Reject. |
| 9 | Removal auto-reverts "with a notice and undo". | Undo reverses the curation operation, and the text follows the weave. |
| 9 | Human-edited alt is "shown only as a suggestion". | The suggestion is the name and the crop, never woven machine text. |
| 5 | Strangers are left unbound or skipped, "nothing new is needed". | Skip is renamed Leave unnamed (durable dismiss plus undo). The copy matches the effect, and no-op re-weaves stay silent. |
| 9, 12 | Review queue, pause and disclosure have no placement. | Proposals are a media-queue filter. Status, pause and retry live in the activity strip as a `naming` state. |
| 12 | Deferred-effect copy appears at curation time only. | It also appears on the first-run drafts. |
| 7 | Bounded retries. | Bounded retries plus a per-item manual Retry. |
| 11 | Turning consent off runs the removals. | The removals are previewed with counts before commit, and Pause stays separate from consent. |
| Open question | Which side derives the affected media? | The WordPress projection, because curation-time copy needs the count. |

## Canon v0.26.2 rows used

| ID | Rule | Lexicon |
| --- | --- | --- |
| [CAL-10] | Inconclusive is a valid human output | ml-systems |
| [HAI-02] | Correction must reach the source | interaction-ux |
| [HAI-04] | Activate–operate–override | interaction-ux |
| [HAI-05] | Imperceptible AI is not ethical | interaction-ux |
| [HAI-06] | Audit trail as design fuel | interaction-ux |
| [HAI-11] | Interface-mode trade-off | interaction-ux |
| [HAI-12] | Output is a proposal, not the answer | interaction-ux |
| [HAI-13] | User is the last error detector | interaction-ux |
| [HAI-18] | Name the deferred effect | interaction-ux |
| [INT-06] | Smart action labels | interaction-ux |
| [INT-07] | Preview before commit | interaction-ux |
| [INT-09] | Reversible command stack | interaction-ux |
| [INT-10] | Status–predict–stop | interaction-ux |
| [INT-12] | First success before extract | interaction-ux |
| [INT-13] | Run the likely path with recovery | interaction-ux |
| [INT-15] | Make mode visible | interaction-ux |
| [INT-19] | One outcome per interaction | interaction-ux |
| [INT-20] | Manage automatic starts | interaction-ux |
| [INT-22] | Explain the result | interaction-ux |
| [INT-24] | Specify loop exits | interaction-ux |
| [INT-28] | Use modals sparingly; animate spatial jumps | interaction-ux |
| [NAV-05] | MECE categories | interaction-ux |
| [NAV-11] | Deep Links encode place and state | interaction-ux |
| [NAV-18] | Fit posture to work cadence | interaction-ux |
| [NAV-19] | Keep related work adjacent | interaction-ux |
| [PERC-03] | Seven-principle Gestalt audit | interaction-ux |
| [PERC-05] | Fovea-first feedback | interaction-ux |
| [PERC-07] | Don't habituate alarms | interaction-ux |
