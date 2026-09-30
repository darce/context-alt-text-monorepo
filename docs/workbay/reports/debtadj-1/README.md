# DEBTADJ-1 adjudication reports

- `dadj-01..28.json`: first-pass verdict per open review finding (FIXED, LIVE, NOT_DEFECT, OBSOLETE, OPERATOR, DUPLICATE, UNSURE).
- `drfu-01..14.json`: second pass over the 105 high-severity closing verdicts (CONFIRMED, REFUTED, UNSURE).
- `dispositions.json`: reconciled record and the only authoritative status per `db_id`.

Precedence: a drfu outcome overrides the dadj verdict for the same `db_id`.

- REFUTED on a closing verdict: `fix_refuted`; the defect is still live and a DEBTFIX-1 fix lane owns it.
- UNSURE: `defer_unsure`.
- CONFIRMED: `close_confirmed`.
- No drfu result on a closing verdict (123 low, 21 medium, 1 high): `close_unrefuted_low`; the name is historical and covers every severity. held for a second reader, not closed. The 105-result drfu pass covered only the high-severity closing verdicts it received; the one high row without a drfu result is db_id 15201, which stays held for the next refutation pass.
- LIVE: `fix_live`. OPERATOR: `defer_operator`.

A dadj FIXED verdict whose drfu result is REFUTED is therefore not a closure; `dispositions.json` records it as `fix_refuted`.
`notes` lists `fix_files` that do not exist on `main`; the fix lane creates them. `dadj-*.json` rows may also list such not-yet-existing files in `fix_files` (for example db_id 6292); `dispositions.json` `notes` is the authoritative list of them.
