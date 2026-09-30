# DEBTADJ-1 adjudication reports

- `dadj-01..28.json`: first-pass verdict per open review finding (FIXED, LIVE, NOT_DEFECT, OBSOLETE, OPERATOR, DUPLICATE, UNSURE).
- `drfu-01..14.json`: second pass over the 105 high-severity closing verdicts (CONFIRMED, REFUTED, UNSURE).
- `dispositions.json`: reconciled record and the only authoritative status per `db_id`.

Precedence: a drfu outcome overrides the dadj verdict for the same `db_id`.

- REFUTED on a closing verdict: `fix_refuted`; the defect is still live and a DEBTFIX-1 fix lane owns it.
- UNSURE: `defer_unsure`.
- CONFIRMED: `close_confirmed`.
- No drfu result on a low-severity closing verdict: `close_unrefuted_low`; held for a second reader, not closed.
- LIVE: `fix_live`. OPERATOR: `defer_operator`.

A dadj FIXED verdict whose drfu result is REFUTED is therefore not a closure; `dispositions.json` records it as `fix_refuted`.
`notes` lists `fix_files` that do not exist on `main`; the fix lane creates them.
