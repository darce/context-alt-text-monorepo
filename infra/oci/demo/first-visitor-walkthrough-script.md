# First-visitor walkthrough script (E21-13 · roadmap §Phase-3 Gate)

Scripted session proving a first-time visitor completes **scan → review → first named
person unaided** on the live demo, with `time-to-first-named-person` recorded. Gates
Phase-3 construction funding (E21-5/P3-A `plan-accept`); findings re-rank P3/P4.

Two runs, same script:

1. **Instrumented (automated)**: `make walkthrough-first-visitor` — Playwright drives the
   steps below, emits `walkthrough-manifest.json` (per-step timings,
   `time_to_first_named_person_ms`) + screenshots + a paste-ready fragment.
2. **Unaided (human)**: a naive participant — not the operator, no coaching — follows only
   the task prompt below while an observer records the same step timestamps and every
   hesitation/wrong turn. The automated run is the rehearsal and baseline, not the proof
   of "unaided".

## Preconditions

- [ ] Phase 1 landed on the demo deploy (E21-1 status strip, E21-2 cull, E21-3 confirm-tab removal, E21-12 roster zero-state)
- [ ] Demo reachable over TLS; seeded media present; recognition API up
- [ ] Participant has WP admin creds but has never used the product

## Task prompt (read to the participant, then stop talking)

> "This site can recognize people in your photo library. Using the admin, get it to
> analyze some photos and put a name to one of the people it finds. Say 'done' when
> you believe you've named someone."

## Steps + timestamps to record

| # | Step | Timestamp | Notes (hesitations, wrong turns, words they say) |
| --- | --- | --- | --- |
| 1 | Lands on Workbench | | where did they go first — Dashboard? Media? |
| 2 | Starts a scan (selects media, "Analyze selected media") | | did they find the CTA unaided? |
| 3 | Scan completes; notices review surface ("Name These People" / "Review next") | | did status vocabulary confuse? |
| 4 | Opens naming ("Name this person") | | or wandered into suggestions/roster? |
| 5 | Types a name and saves | | combobox friction? |
| 6 | Says "done" — believes a person is named | | **time-to-first-named-person = t6 − t1** |
| 7 | (probe) "Where would you find that person again?" | | do they reach the Roster? |

## Outputs → gate decision

- Fill this table into `docs/tasks/21.0/E21-13-walkthrough-findings.md` with the automated
  manifest fragment pasted alongside.
- Record findings in handoff under `E21-13` (`review_findings` batch), then answer the gate
  question explicitly: **do the findings re-rank P3-A (unified review queue) or P4?**
  Record the answer as a decision; E21-5 Slice-1 funding waits on it (E21-5 plan
  §Preconditions).
