# DEMOLIVE-9 f1 — bind the claimed adapter to its attachment

Closes R2-02 (Gate A counted instead of joining), R2-05 (the adapter scrape loop
was unasserted) and R2-12 (the min_pct=50 half-empty library).

## What changed

`sync-demo.sh` scraped `alt_text` and `adapter` with two independent
`grep -o` passes and handed Gate A a space-delimited blob plus a count. Nothing
tied an adapter to the attachment it described, so `trusted_count >= usable_count`
could be satisfied by tokens belonging to entirely different images — or by one
space-padded postmeta value word-splitting into many.

Both loops are replaced by `load_alt_counts_from_media_body`, which calls
`parse_wp_media_alt_rows` to JSON-parse the media body once and emit one
`adapter<TAB>alt_text` record per attachment. Each usable alt now contributes
exactly one adapter token — its own — and Gate A requires `trusted == usable`
rather than `>=`. An adapter that is missing, or that contains whitespace or a
glob metacharacter (`*`, `?`, `[`), collapses to the `__invalid__` sentinel,
which is not a trusted profile. The classifier's word-split also runs under
`set -f` so a token of `*` cannot expand against the login cwd.

R2-05 is dissolved rather than patched: the scrape loop no longer lives in the
untestable inline heredoc in `sync-demo.sh`, it lives in the sourced library
where `test-smoke-gate.sh` calls it directly.

`python3` is not a new dependency on this path — `scripts/deploy/recognition-service.sh`
already parses health bodies with the same idiom on the same host. A parse
failure or a missing interpreter yields zero rows, which fails the population
check closed.

## Suites

Executed on the remote VM (`ubuntu@acx-backend`), full tracked tree extracted to
`/tmp/f1check`.

| suite | command | exit | count |
| --- | --- | --- | --- |
| smoke-gate | `bash scripts/deploy/tests/test-smoke-gate.sh` | `0` | `132` `ok` lines, then `all assertions passed` |
| describe-gate | `bash infra/oci/demo/tests/test-describe-gate.sh` | `0` | `118` `ok` lines, then `all assertions passed` |

Baseline before this change was `110` `ok` on smoke-gate, so the branch adds 22
assertions.

## TEST-15 — every new assertion proved red

Each mutation applied alone to a clean extract, suite re-run, file restored.

| mutation | verbatim first FAIL line | failed | exit |
| --- | --- | --- | --- |
| M1 — restore `>=` semantics (`-ne` → `-lt` in `classify_alt_identity`) | `FAIL alt identity extra trusted tokens fail equality (not >=): expected FAIL, got PASS` | 1 | `1` |
| M2 — drop the `__invalid__` sanitize, append the raw adapter | `FAIL TEST-15 padded blob adapters are sentinels not word-split: expected __invalid__ __invalid__ , got florence_small florence_small` | 3 | `1` |
| M3 — restore the independent `grep -o '"alt_text"'` scrape in `sync-demo.sh` | `FAIL TEST-15 sync-demo.sh calls load_alt_counts_from_media_body: expected 1, got 0` | 1 | `1` |

Baseline and post-restore runs both `exit=0`, `all assertions passed`.

M2 also reddened `TEST-15 padded blob identity FAIL` and
`TEST-15 glob adapter sanitized: expected __invalid__ , got *`.

## Finding disposition

- **R2-02** closed by `TEST-15 padded blob identity FAIL` and
  `TEST-15 realistic adapters are per-usable-item join`: a padded value can no
  longer certify attachments it does not belong to, and M1/M2 both prove those
  assertions can fail.
- **R2-05** closed by `TEST-15 sync-demo.sh calls load_alt_counts_from_media_body`
  and `TEST-15 sync-demo.sh has no independent adapter grep`, proved red by M3.
  The loop is now library code the suite exercises directly.
- **R2-12** closed by `TEST-15 empty-alt mix identity FAIL` plus
  `TEST-15 empty-alt mix min_pct=50 smoke_fail=1`: at the legal floor of 50 the
  coverage classifier still returns PASS, but 10 usable alts carrying no
  provenance now fail Gate A, so the run fails. The algebra R5 described no
  longer has a shippable solution.

## Not addressed here

R2-06's raise-only floor was dropped from this work order to keep the lane
inside its turn budget. `DEMO_ALT_MIN_COVERAGE_PCT=50` still prints a real PASS
for coverage; it is Gate A, not coverage, that now stops the half-empty library.
