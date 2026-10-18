# UXW2-5 fix lane r6 report

Nine senior findings. R6-01 first: the r5 4xx widening swallowed the designed 404. Contract moved in that same commit (R6-05). TDD.

Final HEAD: recorded by the integrator in the canonical worktree after transplant.

## GREEN (this checkout)

- PHP `composer test`: `OK (1785 tests, 8678 assertions)`. Exit 0.
- PHPCS `composer cs-check`: exit 0, no findings.
- PY (`recognition/tests/api/test_roster_candidates.py` + `recognition/tests/unit/test_roster_candidates.py`): `30 passed in 5.08s`.

## Closure

| ID | commit subject | test | mutant RED line | GREEN |
|---|---|---|---|---|
| R6-01 | `fix(api): UXW2-5-R6-01 pass through upstream roster-candidates 4xx` | `testGetRosterCandidatesUpstream404PassesThroughClusterNotFound`; `testGetRosterCandidatesUpstream429PreservesRetryAfter`; `testGetRosterCandidatesUpstream400IsEndpointErrorNotMappedPayload` | 404: `upstream 404 Cluster not found must not be widened to 502 endpoint_error` / `Failed asserting that an object is an instance of class WP_REST_Response.` 429: `upstream 429 must not be widened to 502 endpoint_error` / `Failed asserting that an object is an instance of class WP_REST_Response.` 400 (non-top_k half): `non-top_k upstream 400 must not be classified as endpoint_error; === 400 is too wide` / `Failed asserting that an object is an instance of class WP_REST_Response.` Mutant `is_proxy_endpoint_error($response, 400)` reddens 404 and 429. Mutant `=== 400` (drop the `detail` names `top_k` conjunct): 404 stays `OK (1 test, 5 assertions)`; 400 goes red on the same non-top_k assertion. | `OK (3 tests, 21 assertions)` |
| R6-05 | `fix(api): UXW2-5-R6-01 pass through upstream roster-candidates 4xx` | same commit as R6-01; taxonomy pinned by the 404/429/400 tests plus `recognition-clustering.md` / schema `data_source` | n/a — contract moved with the code (REF-26). A revert of the `:562` / `:573` / schema `data_source` sentences would contradict the PHP tests. | same as R6-01 |
| R6-02 | `fix(contracts): UXW2-5-R6-02 pin SPA no-resort carve-out` | `test_schema_and_contract_agree_on_php_candidate_ordering` | Phrase `Browser/SPA`: `assert "Browser/SPA" in desc` / `AssertionError: assert 'Browser/SPA' in 'Server-ranked labelled clusters. Python top_k is cluster-grain. PHP fetches the Python max window (50), collapses to one row per roster_entry_id (max similarity wins, keep that row's band + name), then ranks committable rows (roster_entry_id non-null) before uncommittable ones, then similarity DESC, then cluster_id ASC, then slices people-grain top_k so a person split across N clusters cannot starve later people. clients must render in payload order and must not re-sort. The PHP roster-entry mapping proxy is required to perform that committable-first re-rank; it is a PHP-layer contract obligation, not a client-side sort.'` Phrase `mapping proxy` / `PHP-layer`: `assert "mapping proxy" in desc or "PHP-layer" in desc` / `AssertionError: assert ('mapping proxy' in 'Server-ranked labelled clusters. Python top_k is cluster-grain. PHP fetches the Python max window (50), collapses to one row per roster_entry_id (max similarity wins, keep that row's band + name), then ranks committable rows (roster_entry_id non-null) before uncommittable ones, then similarity DESC, then cluster_id ASC, then slices people-grain top_k so a person split across N clusters cannot starve later people. Browser/SPA clients must render in payload order and must not re-sort. The PHP roster-entry adapter is required to perform that committable-first re-rank; it is a server-side contract obligation, not a client-side sort.' or 'PHP-layer' in 'Server-ranked labelled clusters. Python top_k is cluster-grain. PHP fetches the Python max window (50), collapses to one row per roster_entry_id (max similarity wins, keep that row's band + name), then ranks committable rows (roster_entry_id non-null) before uncommittable ones, then similarity DESC, then cluster_id ASC, then slices people-grain top_k so a person split across N clusters cannot starve later people. Browser/SPA clients must render in payload order and must not re-sort. The PHP roster-entry adapter is required to perform that committable-first re-rank; it is a server-side contract obligation, not a client-side sort.')` Phrase old sentence: `assert old_unqualified not in text` / `AssertionError: assert 'Clients must render in payload order and must not re-sort client-side.' not in text`. | `1 passed, 8 deselected` |
| R6-03 | `fix(contracts): UXW2-5-R6-03 pin people-grain on ranking sentence` | `test_schema_and_contract_agree_on_php_candidate_ordering` | `assert "people-grain" in rank_line` / `AssertionError: assert 'people-grain' in '- Server rank is committable-first, then similarity DESC, then \`cluster_id\` ASC. Browser/SPA clients must render in payload order and must not re-sort. The PHP roster-entry mapping proxy is required to perform that committable-first re-rank; it is a PHP-layer contract obligation, not a client-side sort.'` Other php_block people-grain bullets left in place. | `1 passed, 8 deselected` |
| R6-04 | `docs(uxw2): UXW2-5-R6-04 correct r5 cap and composer-test claims` | `composer test` at this HEAD; `find . -name '._*' -not -path './.git/*' \| wc -l` is 0 | n/a — report falsehood, not a production mutant | `OK (1785 tests, 8678 assertions)` |
| R6-06 | `fix(tests): UXW2-5-R6-06 pin emitted cluster_id to schema uuid` | `testGetRosterCandidatesEmittedClusterIdsMatchSchemaUuidFormat` | `emitted cluster_id must match schema format uuid` / `Failed asserting that '550e8400e29b41d4a716446655440000' matches PCRE pattern "/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i".` Production mutant: `attach_roster_entry_ids` stripped dashes from `cluster_id`. | `OK (1 test, 2 assertions)` |
| R6-07 | `fix(tests): UXW2-5-R6-07 strip hash comments in window-token guard` | `testProxyQueryReferencesPythonWindowConstantByTokenForRosterCandidates` | `Failed asserting that '\n\t\t\t\'tenant_id\' => $this->get_tenant_id(),\n\t\t\t\n\t\t\t\n\t\t\t\'top_k\'     => 50, ' [ASCII](length: 73) contains "self::ROSTER_CANDIDATES_PYTHON_WINDOW" [ASCII](length: 37).` Mutant: `'top_k' => 50, # self::ROSTER_CANDIDATES_PYTHON_WINDOW`. | `OK (1 test, 5 assertions)` |
| R6-08 | `fix(tests): UXW2-5-R6-08 pin interpolated top_k description numerals` | `testRegisterRoutesIncludesRosterCandidates` | `description must interpolate ROSTER_CANDIDATES_TOP_K_MIN` / `Failed asserting that 'People-grain cap applied after PHP collapses upstream cluster rows to one row per roster person. Not forwarded upstream: PHP always requests the full cluster-grain window.' [ASCII](length: 171) contains "1" [ASCII](length: 1).` Mutant: dropped `%d` placeholders; extra sprintf args ignored. | `OK (1 test, 14 assertions)` |
| R6-09 | `fix(api): UXW2-5-R6-09 interpolate invalid top_k message from bounds` | `testDispatchRosterCandidatesInvalidTopKUsesSpecificError` | `Failed asserting that two strings are identical.` / `--- Expected` / `+++ Actual` / `@@ @@` / `-'top_k must be an integer between 1 and 50.'` / `+'top_k must be an integer between %d and %d.'` Mutant: `invalid_top_k_error` returned the format const without sprintf. | `OK (1 test, 24 assertions)` |

Subjects above each match exactly one commit via `git log --format=%H --fixed-strings --grep="<subject>"` (hashes not copied here).

## Line cites (re-derived after the last code commit)

- R6-01: `is_proxy_endpoint_error()` at `class-abstract-recognition-proxy-controller.php:336` stays `$min_status = 500`; roster-candidates no longer passes 400. `get_roster_candidates` at `class-suggestions-controller.php:405` classifies 502 only for redirect-refused, 5xx, or `is_roster_candidates_top_k_drift` (`:393`, status 400 **and** `detail` naming `top_k`) at `:439-441`. Tests at `SuggestionsControllerTest.php:1480`, `:1503`, `:1527`.
- R6-05: missing cluster stays 404 at `recognition-clustering.md:562`. Degraded/offline at `:573` names 4xx passthrough and the top_k-detail 502 exception. Schema `data_source` at `roster-candidates-response.schema.json:49` says the same.
- R6-02: ranking carve-out at `recognition-clustering.md:571`. Schema client-scope + proxy obligation at `roster-candidates-response.schema.json:69`. Test tokens at `test_roster_candidates.py:397-398` (schema) and `:419-420` (php_block); old sentence absent at `:400`, `:411`, `:422`.
- R6-03: `rank_line` at `test_roster_candidates.py:417-418`. `people-grain` is on the Server-rank sentence at `recognition-clustering.md:571`.
- R6-04: r5 L3 now says max `top_k` is 50 at `UXW2-5-fix-r5-report.md:3`. GREEN composer tail at `:9`. Cap source `MAX_ROSTER_CANDIDATES_TOP_K = 50` at `roster_candidates.py:19`; PHP `ROSTER_CANDIDATES_TOP_K_MAX` / `ROSTER_CANDIDATES_PYTHON_WINDOW` at `class-suggestions-controller.php:42` / `:44`.
- R6-06: RFC `format: uuid` pattern at `SuggestionsControllerTest.php:1417`. Test `testGetRosterCandidatesEmittedClusterIdsMatchSchemaUuidFormat` at `:1382`.
- R6-07: `#.*$` strip at `SuggestionsControllerTest.php:1596`. Production token still `self::ROSTER_CANDIDATES_PYTHON_WINDOW` at `class-suggestions-controller.php:426`.
- R6-08: description sprintf at `class-suggestions-controller.php:231`. Constant pins at `SuggestionsControllerTest.php:899-916`.
- R6-09: `INVALID_TOP_K_MESSAGE` format at `class-suggestions-controller.php:46`; sprintf in `invalid_top_k_error` at `:375-383`. Test formats from MIN/MAX at `SuggestionsControllerTest.php:937-950`. Contract quote at `recognition-clustering.md:572`. Schema window sentence at `roster-candidates-response.schema.json:69`.

## Canon

- TEST-15: 404/429/400 tests observed red; `=== 400` left 404 green and reddened the non-top_k 400 half; `#` comment-plus-literal; sprintf `%d` drop; format-string without sprintf; dash-stripped `cluster_id`; each schema/markdown phrase mutated out.
- TEST-06: uuid format assertion observed red on a production-side dash-strip, not a fixture edit.
- REF-26: 4xx taxonomy moved in the same commit as the PHP change (R6-01/R6-05). Invalid `top_k` message, contract quote, and schema window sentence share MIN/MAX/WINDOW (R6-09).
- CLM-03 / PERC-04: schema and markdown now agree on Browser/SPA vs PHP mapping-proxy; the old unqualified client-side sentence is asserted absent from both.
- REF-09: PHP re-rank remains a named proxy obligation, not a client-side sort.
- API-05: operator-facing invalid `top_k` prose is sprintf of the bound constants.
- REF-25: r5 L3 cap and AppleDouble/exit-1 claims boarded up.
- CLM-03: this report has zero 40-hex strings.

## Undone

- 401/403 have no dedicated tests. 429 covers header-preserving 4xx passthrough; auth 4xx ride the same 5xx-default path and were not separately queued.
- Exact gate invocation `uv run --extra dev pytest …` is not the command that ran green here. The copied `.venv` pytest shebang points at a missing sibling-tree interpreter; `uv run --extra dev python -m pytest recognition/tests/api/test_roster_candidates.py recognition/tests/unit/test_roster_candidates.py -q` is `30 passed in 5.08s`.
- `$min_status` remains on `is_proxy_endpoint_error` (default 500, no roster-candidates caller). Left in place; ownership said prefer not to change the abstract predicate.
- FE `useLiveReviewTarget` gone-cluster branch (`status === 404`) is still untested in this lane (`js/**` out of ownership).
- MCP handoff not written: this throwaway lane has no workbay MCP tools.
- Python production modules and `suggestions.py` untouched (out of ownership).
