# UXW2-5 fix lane r4 report

Close two prover survivors + 9 R4 findings. TDD. Token pin, cross-language cap, fail-closed empty samples.

## GREEN (this checkout)

- PHP `--filter 'RosterCandidates'`: `OK (14 tests, 118 assertions)` (baseline 12 / 109)
- PHP `composer test`: `OK (1781 tests, 8652 assertions)` (baseline 1778 / 8640). Zero NEW failures.
- PY targeted (`recognition/tests/unit/test_roster_candidates.py` + `recognition/tests/api/test_roster_candidates.py`): `29 passed in 5.35s` (baseline 26 passed)

## Closure

| ID | commit subject | test | mutant RED line | GREEN |
|---|---|---|---|---|
| R4-08 | `fix(tests): UXW2-5-R4-08 pin python window query token` | `testProxyQueryReferencesPythonWindowConstantByTokenForRosterCandidates` | `Failed asserting that '…ROSTER_CANDIDATES_TOP_K_MAX…' contains "self::ROSTER_CANDIDATES_PYTHON_WINDOW".` Suite under mutant: `FAILURES! Tests: 13, Assertions: 112, Failures: 1.` | `OK (1 test, 4 assertions)` |
| R4-02 | `fix(tests): UXW2-5-R4-02 cross-language roster top_k cap guard` | `test_php_python_window_matches_python_cap`; `testPythonWindowConstantMatchesPythonCapSource` | PY: `AssertionError: assert 50 == 25`. PHP: `Failed asserting that 50 is identical to 25.` Pair: `1 failed, 26 passed`. | PY `1 passed`; PHP `OK (1 test, 3 assertions)` |
| R4-07 | `fix(recognition): UXW2-5-R4-07 empty-probe flag fails closed` | `test_quality_flag_from_empty_samples_fails_closed`; renamed `test_roster_candidates_empty_probe_when_reps_have_zero_dim_embeddings` | Unit: `AssertionError: assert <QualityFlag.OK: 'ok'> is <QualityFlag.LOW_QUALITY: 'low_quality'>`. See before/after below. | unit `1 passed`; api `-k zero_dim` `1 passed` |
| R4-09 | `fix(api): UXW2-5-R4-09 client-facing roster top_k description` | `testRegisterRoutesIncludesRosterCandidates` | `Failed asserting that '…window ROSTER_CANDIDATES_PYTHON_WINDOW.' does not contain "ROSTER_CANDIDATES_PYTHON_WINDOW".` | `OK (1 test, 11 assertions)` |
| R4-04 | `fix(api): UXW2-5-R4-04 private top_k validator no dead wrap` | `testRosterCandidatesTopKValidatorIsNotPublicApi`; helper `invokeRosterCandidatesRoute` | Mutant 1: `validator is internal; no validate_callback is registered` / `Failed asserting that true is false.` Mutant 2: `top_k=-5 Failed asserting that an object is an instance of class WP_Error.` | `OK (2 tests, 26 assertions)` |
| R4-05 | `fix(tests): UXW2-5-R4-05 hex cluster id in tie-break fixture` | `testGetRosterCandidatesTieBreaksEqualSimilarityByClusterIdAsc` | Mutant 1: `fixture id must match the route regex` / `Failed asserting that 'zzzzzzzz-0000-0000-0000-00000000000z' matches PCRE pattern "/^[a-f0-9-]+$/".` Mutant 2: `Failed asserting that two arrays are identical.` `- 0 => 'aaaaaaaa-0000-0000-0000-00000000000a'` / `+ 0 => 'ffffffff-0000-0000-0000-00000000000f'` | `OK (1 test, 4 assertions)` |
| R4-06 + R4-03 | `fix(contracts): UXW2-5-R4-06 UXW2-5-R4-03 php candidate ordering SSOT` | `test_schema_and_contract_agree_on_php_candidate_ordering` | Mutant 1: `AssertionError: assert 'roster_entry_id null rows are uncommittable and kept flagged' not in '…'`. Mutant 2: `AssertionError: assert 'must not re-sort' in '…'`. `-k contract` stayed GREEN (`2 passed`). | `-k ordering or contract` `2 passed` |
| R4-01 | `fix(docs): UXW2-5-R4-01 strip dead SHAs from r3 report` | gate loop + `grep -cE '\b[0-9a-f]{40}\b'` | `DEAD 0000000000000000000000000000000000000000` | loop silent; `grep -c` = `0` | <!-- sha-lint:allow verbatim mutant payload, not a commit citation -->

## Item 3 before/after (ternary mask)

Mutant: `roster_candidates.py:94` `if not samples: return QualityFlag.OK`.

- **WITH ternary** (`quality_flag=quality_flag if usable_probes else QualityFlag.LOW_QUALITY`): `uv run --extra dev pytest -q recognition/tests/api/test_roster_candidates.py -k zero_dim` → `1 passed, 6 deselected` (mask; empty-samples default never observed).
- **WITHOUT ternary** (`quality_flag=quality_flag`): same command → `AssertionError: assert 'ok' == 'low_quality'`.

Deleting the dead `else` restored discrimination. Baseline pair before delete: `28 passed in 5.26s` (no test needed the `else` leg).

## Canon

- TEST-15: token swap killed at `SuggestionsControllerTest.php:1434`; cap `= 25` killed at `recognition/tests/unit/test_roster_candidates.py:690` + `SuggestionsControllerTest.php:1422`; empty-samples at `recognition/tests/unit/test_roster_candidates.py:704` + `recognition/tests/api/test_roster_candidates.py:98`.
- REF-26: PHP `class-suggestions-controller.php:393` token + both-suite cap at `recognition-clustering.md:569`.
- REF-09: contract names both tests at `recognition-clustering.md:569`; schema/markdown ordering at `roster-candidates-response.schema.json:69` + `recognition-clustering.md:571`.
- TEST-06: renamed zero-dim test names the real driver (`recognition/tests/api/test_roster_candidates.py:98-101`); hex fixture now route-shaped (`SuggestionsControllerTest.php:1318`).
- REF-25: dead ternary deleted `roster_candidates.py:200`; dead wrap deleted; validator `class-suggestions-controller.php:355` private, 1 arg; SHA tables gone from r3 report.
- API-05: client-facing copy `class-suggestions-controller.php:229`; guard `SuggestionsControllerTest.php:897`.
- PERC-04: payload order is the render order (`recognition-clustering.md:571`; schema `:69`).
- CLM-03: r3 report has zero 40-hex SHAs.

## Undone

None. Items 1–8 committed in order. FE `js/**` untouched (out of lane).
