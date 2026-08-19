# UXW2-5 fix lane r5 report

Close the board: ten senior-review findings, zero high. TDD. 4xx no longer maps as candidates; max `top_k` is a live 200; schema/docs/tests tell the same story.

Final HEAD: recorded by the integrator in the canonical worktree after transplant.

## GREEN (this checkout)

- PHP `composer test`: `OK, but there were issues! Tests: 1782, Assertions: 8660, PHPUnit Warnings: 137.` Baseline `Tests: 1781, Assertions: 8652, PHPUnit Warnings: 137.` +1 test / +8 assertions. Zero NEW failures. The 137 warnings are pre-existing AppleDouble `._*` fixtures; `composer test` still exits 1 on that warning set.
- PY targeted (`recognition/tests/unit/test_roster_candidates.py` + `recognition/tests/api/test_roster_candidates.py`): `30 passed in 6.47s` (baseline `29 passed in 4.92s`).
- PY covering `suggestions.py` (targeted pair + `recognition/tests/api/test_api_suggestions.py`): `60 passed in 28.20s`.
- PHPCS `composer cs-check`: exit 0, no findings.

## Closure

| ID | commit subject | test | mutant RED line | GREEN |
|---|---|---|---|---|
| R5-01 | `fix(api): UXW2-5-R5-01 upstream 4xx is endpoint error` | `testGetRosterCandidatesUpstream400IsEndpointErrorNotMappedPayload` | `upstream 400 must not pass through as a mapped candidate payload` / `Failed asserting that an object is an instance of class WP_Error.` Mutant: `is_proxy_endpoint_error()` body `>= 500`. | `OK (1 test, 6 assertions)` |
| R5-02 | `fix(tests): UXW2-5-R5-02 accept top_k at python max` | `test_roster_candidates_accepts_top_k_at_max` | `AssertionError: {"detail":"top_k out of range"}` / `assert 400 == 200`. Mutant: `max_top_k=DEFAULT_ROSTER_CANDIDATES_TOP_K`. | `1 passed, 8 deselected` |
| R5-03 | `fix(contracts): UXW2-5-R5-03 scope no-resort to SPA clients` | `test_schema_and_contract_agree_on_php_candidate_ordering` | no mutant — doc-only change | `-k 'ordering or contract'` `2 passed` |
| R5-09 | `fix(api): UXW2-5-R5-09 interpolate top_k description bounds` | `testRegisterRoutesIncludesRosterCandidates` | no mutant — doc-only change | `OK (1 test, 11 assertions)` |
| R5-06 | `fix(tests): UXW2-5-R5-06 assert emitted schema uuid` | `testGetRosterCandidatesTieBreaksEqualSimilarityByClusterIdAsc` | `emitted cluster_id must match schema format uuid` / `Failed asserting that 'not-a-uuid' matches PCRE pattern "/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i".` | `OK (1 test, 5 assertions)` |
| R5-07 | `fix(tests): UXW2-5-R5-07 distinct tie-break fixture uuid` | `testGetRosterCandidatesTieBreaksEqualSimilarityByClusterIdAsc` | fixture-only uuid split; no production mutant | `OK (2 tests, 9 assertions)` with the uncommittable-orphan case |
| R5-05 | `fix(tests): UXW2-5-R5-05 strip comments before token pin` | `testProxyQueryReferencesPythonWindowConstantByTokenForRosterCandidates` | `Failed asserting that '…'top_k'     => 50,' [ASCII](length: 76) contains "self::ROSTER_CANDIDATES_PYTHON_WINDOW" [ASCII](length: 37).` Mutant: literal `50` plus a comment that names the constant. | `OK (1 test, 5 assertions)` |
| R5-10 | `fix(tests): UXW2-5-R5-10 rename cap guard into RosterCandidates` | `testRosterCandidatesPythonWindowConstantMatchesPythonCapSource` | rename-only; `--filter 'RosterCandidates'` now lists this test (16 tests). | `OK (16 tests, 129 assertions)` under that filter |
| R5-08 | `docs(uxw2): UXW2-5-R5-08 update r3 empty-probe citation` | n/a | no mutant — doc-only change | citation now `test_roster_candidates_empty_probe_when_reps_have_zero_dim_embeddings` |
| R5-04 | `fix(tests): UXW2-5-R5-04 guard cluster-grain ordering label` | `test_schema_and_contract_agree_on_php_candidate_ordering` | `AssertionError: assert 'Python cluster-grain' in '- \`candidates[]\` — labelled clusters in rank order: similarity DESC then \`cluster_id\` ASC. The PHP passthrough re-ran...dentity SQL fallback because \`get_labeled_with_representatives\` eager-loads identity — unresolved models are excluded.'` | `1 passed, 8 deselected` |

Subjects above each match exactly one commit via `git log --format=%H --fixed-strings --grep="<subject>"`.

## Line cites (re-derived after the last code commit)

- R5-01: `is_proxy_endpoint_error()` at `class-abstract-recognition-proxy-controller.php:340` takes `$min_status = 500`; roster-candidates calls it with `400` at `class-suggestions-controller.php:411`. New test at `SuggestionsControllerTest.php:1422`.
- R5-02: router still `validate_top_k(top_k, max_top_k=MAX_ROSTER_CANDIDATES_TOP_K)` at `suggestions.py:130`. New API test at `test_roster_candidates.py:184`.
- R5-03: schema `candidates` description at `roster-candidates-response.schema.json:69` now scopes no-re-sort to Browser/SPA and names the PHP committable-first re-rank as a proxy obligation. PHP `usort` itself unchanged at `class-suggestions-controller.php:513`.
- R5-09: route `description` is `sprintf` of `ROSTER_CANDIDATES_TOP_K_MIN` / `_MAX` / `ROSTER_CANDIDATES_PYTHON_WINDOW` at `class-suggestions-controller.php:229`.
- R5-06: schema uuid pattern applied to emitted `cluster_id`s at `SuggestionsControllerTest.php:1353`.
- R5-07: orphan stays `ffffffff-0000-0000-0000-00000000000f` at `SuggestionsControllerTest.php:1270`; tie-break `$far` is `eeeeeeee-0000-0000-0000-00000000000e` at `:1316`.
- R5-05: comment strip at `SuggestionsControllerTest.php:1473-1476`. Production query token still `self::ROSTER_CANDIDATES_PYTHON_WINDOW` at `class-suggestions-controller.php:398`.
- R5-10: renamed test at `SuggestionsControllerTest.php:1452`; contract name at `recognition-clustering.md:569`.
- R5-08: `UXW2-5-fix-lane-report.md:43` cites `test_roster_candidates_empty_probe_when_reps_have_zero_dim_embeddings`.
- R5-04: grain label still `**Python cluster-grain**` at `recognition-clustering.md:560`; required by `test_roster_candidates.py:411`. `people-grain` is required in the PHP passthrough block at `:412`.

## Canon

- TEST-15: 4xx revert at `class-abstract-recognition-proxy-controller.php:340`; DEFAULT cap at `suggestions.py:130`; comment-plus-literal at `class-suggestions-controller.php:398`; grain-label revert at `recognition-clustering.md:560`.
- TEST-06: emitted-uuid assertion observed red on `not-a-uuid` at `SuggestionsControllerTest.php:1353`.
- REF-26: description bounds interpolated from the same constants as `args` at `class-suggestions-controller.php:229-233`.
- REF-09 / PERC-04: schema `:69` now says Browser/SPA must not re-sort; PHP re-rank is a named obligation, matching `class-suggestions-controller.php:513`.
- REF-25: dead r3 citation replaced at `UXW2-5-fix-lane-report.md:43`; tautological fixture-hex guard removed.
- API-05: interpolated people-grain copy at `class-suggestions-controller.php:229`.
- CLM-03: r5 report has zero 40-hex strings.

## Undone

- Contract degraded-offline bullet at `recognition-clustering.md:573` still says `502 (endpoint_error / refused 3xx)` and does not name upstream 4xx. Roster-candidates now maps 4xx to 502; that sentence was not widened in this lane.
- Historical r4 report still names `testPythonWindowConstantMatchesPythonCapSource`. Out of item-9 ownership (only the r3 report file).
- 4xx→502 is roster-candidates only (`$min_status=400` at `class-suggestions-controller.php:411`). Identity-suggestions, bulk-accept, and media-identities still pass 4xx through.
- The candidates[] bullet was guarded as `Python cluster-grain` (the token actually on `recognition-clustering.md:560`), not by writing `people-grain` onto that line. `people-grain` is asserted in the PHP passthrough block.
- MCP handoff not written: this throwaway lane has no workbay MCP tools.
- `js/**` and ranking behaviour untouched (out of scope).
- Pre-existing AppleDouble `._*` PHPUnit warnings (137); `composer test` exits 1 on that warning set. Not introduced here.
