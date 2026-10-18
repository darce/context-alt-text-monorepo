# demolive-w — bind claimed adapter to live producer (R2-07)

Lane `demolive-f3`. Task `DEMOLIVE-9`. Work order w.

`classify_claimed_adapter_matches_probe` cross-checks the WP media payload's claimed adapter names against the independently probed description-service `/health/detailed` `description_adapter`. Gate A still only proves the payload *claims* a trusted adapter; this classifier proves the claim matches what the producer is *currently* running.

Owned files: `infra/oci/demo/lib/describe-gate.sh`, `infra/oci/demo/tests/test-describe-gate.sh`, this report. `extract_probed_description_adapter`, `classify_describe_gate`, `classify_describe_provenance`, the trusted-profile allowlist, and the `fixture_sample_is_denied` / `normalize_fixture_sample` copies were not edited. `scripts/deploy/` and `sync-demo.sh` were not opened for write; wiring is orchestrator-owned after merge.

## Function

```
classify_claimed_adapter_matches_probe <probed_adapter> <claimed_adapters_blob>
  -> PASS | FAIL | UNKNOWN
```

`claimed_adapters_blob` is the whitespace-separated list of adapter names the WP media payload claims (same shape `classify_alt_identity` consumes).

Documented semantics:

1. `probed_adapter` empty (probe unavailable / no python3 / non-JSON) -> UNKNOWN. Callers decide policy; do not guess. UNKNOWN is not a pass.
2. claimed blob empty -> UNKNOWN (nothing claimed yet; coverage gate owns that).
3. any claimed token that is not byte-identical to `probed_adapter` -> FAIL. Live failure mode: production serves `seeded` while postmeta claims `florence_small`.
4. every claimed token equals `probed_adapter` -> PASS.
5. a claimed token containing whitespace, a glob metacharacter (`*` `?` `[`) or that is otherwise unsplittable -> FAIL, not UNKNOWN.

Word-split runs under `set -f` so a claimed `*` cannot glob against cwd. Comparison is byte-identical, not case-folded (`Florence_Small` vs `florence_small` FAILs).

## Suite

```
$ bash infra/oci/demo/tests/test-describe-gate.sh; echo "exit=$?"
...
all assertions passed
exit=0
```

| suite | command | exit | `ok` lines | trailer |
|---|---|---|---|---|
| describe-gate | `bash infra/oci/demo/tests/test-describe-gate.sh` | `0` | `181` | `all assertions passed` |

170 prior + 11 new R2-07 assertions = 181.

## TEST-15 mutation table

Each mutant was applied, observed, then restored. After restore, `git diff` on `describe-gate.sh` contained only the new function (no leftover PASS substitutions).

| mutant | change | verbatim FAIL line(s) | assertion count | exit |
|---|---|---|---|---|
| M1 — mismatch arm | `echo FAIL` → `echo PASS` in the `$adapter != $probed_adapter` arm | `FAIL claimed one mismatch among matches: expected FAIL, got PASS` | `5` | `1` |
| M2 — empty-probe arm | `echo UNKNOWN` → `echo PASS` when `probed_adapter` is empty | `FAIL empty probe UNKNOWN: expected UNKNOWN, got PASS` | `2` | `1` |

M1 remaining FAIL lines:

```
FAIL claimed one mismatch among matches: expected FAIL, got PASS
FAIL claimed seeded vs probed florence_small: expected FAIL, got PASS
FAIL claimed florence_small vs probed seeded: expected FAIL, got PASS
FAIL claimed token with embedded space: expected FAIL, got PASS
FAIL claimed Florence_Small vs probed florence_small (case): expected FAIL, got PASS
5 assertion(s) failed
```

`claimed bare glob star` stayed FAIL under M1 because glob tokens hit the `* ? [` case arm, not the mismatch arm.

M2 remaining FAIL lines:

```
FAIL empty probe UNKNOWN: expected UNKNOWN, got PASS
FAIL both empty UNKNOWN: expected UNKNOWN, got PASS
2 assertion(s) failed
```

Empty-claim-only stayed UNKNOWN under M2: that is a separate arm.

## What this does not prove

This cross-check binds the WP-claimed adapter name to the producer's *current* `/health/detailed` adapter. It does not bind each caption to per-image production history. A caption produced while a different adapter was live still passes as long as today's probe and today's postmeta agree.
