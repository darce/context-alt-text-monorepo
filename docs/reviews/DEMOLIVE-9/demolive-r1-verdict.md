# R1 verdict: fail

Lens: can the DEMOLIVE-2/3 smoke and describe gates be made to PASS while the demo is still broken (empty alt or canned fixture alt)? Yes. Default `DEMO_ALT_GATE_ENFORCE=1` + `min_pct=95` would fail today's live 100/100 empty library. The overrides, the 8-string denylist, and the describe SKIP/`--write` path can still certify a lie.

## Findings

### R1-01 | severity: high | file: scripts/deploy/sync-demo.sh:257

Evidence: `emit_alt_gate` is the only ship switch for all three alt sub-gates. It is called for population (L284), coverage (L301), and provenance (L316):

```
if [ "$gate_verdict" = "FAIL" ] && [ "${DEMO_ALT_GATE_ENFORCE:-1}" = "0" ]; then
  echo "WARN ${msg} (enforcement disabled via DEMO_ALT_GATE_ENFORCE=0)"
  return
fi
```

The header comment (L182–184) tells the operator to set the var so "a known-empty demo can still ship". Replayed the live demo (`curl https://demo.altcontext.com/wp-json/wp/v2/media?per_page=100&_fields=id,alt_text` → `x-wp-total: 100`, 100 items, every `alt_text` `""`). Counters: `header_total=100 body_total=100 with_alt=0` → pop PASS, coverage FAIL, provenance SKIP. With `DEMO_ALT_GATE_ENFORCE=0` the coverage FAIL becomes WARN and `smoke_fail` stays 0. Same knob on 100 exact fixture captions: provenance FAIL → WARN, `smoke_fail=0`.

`infra/oci/demo/bootstrap-wp.sh:170-185` BLOCK (live `seeded` / empty profile) only echoes; it does not `exit`. Describe is not a release gate. The only blocker is this overridable smoke wrapper.

Failure scenario: live 100/100 empty alt (or 100/100 seeded fixtures) + `DEMO_ALT_GATE_ENFORCE=0` → deploy exit 0, public demo still broken/lying.

Canon: SECD-08, RLSE-08

Suggested fix: keep ENFORCE for coverage/population if you must; make provenance (and empty-alt coverage) non-overridable, and `exit 1` bootstrap on describe BLOCK.

### R1-02 | severity: high | file: scripts/deploy/lib/smoke-gate.sh:69

Evidence: `classify_alt_coverage` has no floor on `min_pct` other than "is a number":

```
if [ $((with_alt * 100 / total)) -ge "$min_pct" ]; then
    echo PASS
```

`scripts/deploy/sync-demo.sh:189` ships `DEMO_ALT_MIN_COVERAGE_PCT` default 95. Direct classifier:

```
classify_alt_coverage 100 0 95 → FAIL
classify_alt_coverage 100 0 0  → PASS
```

Live payload through the exact counting block: `cov@95=FAIL`, `cov@0=PASS`, provenance SKIP because `with_alt=0`. Unlike R1-01 this prints PASS, not WARN. `test-smoke-gate.sh` pins `0/100` FAIL only at 95; it never pins `min_pct=0`.

Failure scenario: `DEMO_ALT_MIN_COVERAGE_PCT=0` on today's 0/100 library → population PASS, coverage PASS, provenance SKIP, smoke exit 0, every published image still has empty alt.

Canon: SECD-08, RLSE-08, CLM-04

Suggested fix: reject `min_pct=0` (and treat it as FAIL-closed), and add a characterization assertion `classify_alt_coverage 100 0 0 → FAIL`.

### R1-03 | severity: high | file: scripts/deploy/lib/smoke-gate.sh:106

Evidence: `classify_alt_provenance` is eight literal `case *$fixture*` arms. Coverage treats any non-`""` JSON string as alt (`grep -v '"alt_text": *""'`). Replayed the exact smoke pipelines:

| published alt_text | pop | cov@95 | prov |
|---|---|---|---|
| `A close-up of a small object on a neutral background.` | PASS | PASS | FAIL |
| `A close-up of a small object on a neutral background` (no period) | PASS | PASS | PASS |
| `a close-up of a small object on a neutral background.` | PASS | PASS | PASS |
| `.` × 100 | PASS | PASS | PASS |
| ` ` (space) × 100 | PASS | PASS | PASS |
| `A photograph.` × 80, header 80 | PASS | PASS | PASS |

`test-smoke-gate.sh:105-106` drift guard is `grep '"caption":' seeded_adapter.py`. It goes red if the Python pool grows/changes without a matching shell arm. It does not classify published paraphrases, case-folds, stripped punctuation, or placeholders. Current `_FIXTURE_POOL` strings still FAIL (could not evade the live adapter's exact period-terminated sentences).

Failure scenario: publish 100 copies of `A close-up of a small object on a neutral background` (or `.`) with `x-wp-total: 100` → all three smoke classifiers PASS; demo alt is still machine-canned/useless.

Canon: CLM-04, PROV-10

Suggested fix: fail coverage on whitespace/placeholder alt; key provenance off adapter identity in stored provenance meta, not caption substring matching.

### R1-04 | severity: high | file: infra/oci/demo/lib/describe-gate.sh:66

Evidence: after the allowlist check, full coverage is SKIP:

```
if [ "$with_alt" -eq "$total" ]; then
    echo SKIP
```

`bootstrap-wp.sh:173` on RUN is `wp alt-context describe generate --write --limit=100` (no `--force`). `class-description-command.php:74-75,159` documents `--force` as the overwrite switch and, without it, iterates `list_missing_alt_candidates` only.

Classifiers:

```
classify_describe_gate florence_small 100 100 → SKIP
classify_describe_gate seeded 100 100         → BLOCK (no rewrite either)
classify_alt_provenance '<fixture sentence>'  → FAIL
```

SKIP means "already done". Smoke then FAILs provenance on the same corpus (INT-10: operator cannot predict the next state; bootstrap will never heal). The easy escape is R1-01 (`ENFORCE=0`). If the stored alts are R1-03 paraphrases (`A photograph.`), SKIP + smoke PASS: the lie is frozen and shippable. `with_alt` for SKIP is a wp-cli meta count, not a provenance check.

Failure scenario: 100 attachments already have canned alt; `ACX_DESCRIPTION_ADAPTER=florence_small`; bootstrap prints "Describe pass skipped" and does not call describe; smoke either FAILs provenance forever (exact fixtures) or PASSes (paraphrase/placeholder). No deploy-path `--force` rewrite.

Canon: INT-10, PROV-10, CLM-04

Suggested fix: SKIP only when coverage is full AND provenance would PASS; otherwise RUN `describe generate --write --force` (or clear alt and re-describe).

### R1-05 | severity: high | file: infra/oci/demo/bootstrap-wp.sh:165

Evidence: `ADAPTER_PROFILE="$(env_get ACX_DESCRIPTION_ADAPTER)"` reads `secrets/.env`. `infra/oci/demo/.env.example:39` is `ACX_DESCRIPTION_ADAPTER=`. `apps/prototype-description-service/docker-compose.demo.yml` does not pass that var into `wordpress` or `wpcli` (no `env_file`, no `${ACX_DESCRIPTION_ADAPTER}` interpolation). The description service uses its own `ACX_DESCRIPTION_ADAPTER`; background is that prod is still `seeded`.

Describe BLOCK (L178-185) prints "BLOCKED: … Set ACX_DESCRIPTION_ADAPTER to one of: florence_small, …" then falls through to "Bootstrap complete" with no `exit`. The operator instruction changes only the bootstrap allowlist label, not the producer.

Failure scenario: follow the BLOCK message, set `ACX_DESCRIPTION_ADAPTER=florence_small` in demo secrets while the service stays `seeded`. Next bootstrap: `classify_describe_gate florence_small 100 0 → RUN`, `--write` publishes the 8 fixture sentences. Smoke provenance FAILs (exact strings) or PASSes (R1-03). Combined with R1-01, the demo ships canned alt — the outcome the comments call worse than empty.

Canon: PROV-10, RLSE-08, CLM-04

Suggested fix: allow RUN only when the live description-service profile is a trusted adapter (probe `/health` or equivalent), and fail bootstrap on BLOCK.

## Checks I ran

- `bash scripts/deploy/tests/test-smoke-gate.sh` → exit 0 (`all assertions passed`)
- `bash infra/oci/demo/tests/test-describe-gate.sh` → exit 0 (`all assertions passed`)
- `curl -sS -D /tmp/demo-headers -o /tmp/demo-body --max-time 20 'https://demo.altcontext.com/wp-json/wp/v2/media?per_page=100&_fields=id,alt_text'` → exit 0; `HTTP/2 200`, `x-wp-total: 100`, JSON list len 100, nonempty alt 0
- Live payload through the exact `sync-demo.sh` counting block: `header_total=100 body_total=100 with_alt=0`; pop PASS; cov@95 FAIL; cov@0 PASS; provenance SKIP
- `classify_alt_coverage 100 0 0` → PASS; `DEMO_ALT_GATE_ENFORCE=0` replica → `smoke_fail=0` on both empty-alt and fixture-alt FAIL verdicts
- `classify_describe_gate florence_small 100 100` → SKIP; `seeded 100 0` / `seeded 100 100` → BLOCK
- Synthetic REST bodies for missing-period fixtures, `.` placeholders, space placeholders, HTML 502, missing `X-WP-Total`, `alt_text: null` (see R1-03 table)
- `python3` extract of `bootstrap-wp.sh` DESCRIBE_VERDICT case: `exit` not present (`False`)

## What I could NOT falsify

- Absent `X-WP-Total` fail-closes (`classify_alt_population '' 100` → FAIL; empty curl files → pop FAIL, cov FAIL).
- Live anonymous `/wp/v2/media` returns all 100 attachments (`x-wp-total: 100` matches body 100). Unauthenticated hiding is not the current demo.
- `total == 100` is fully covered by `per_page=100`; `101` vs `100` fail-closes.
- Mid-pipeline grep-miss under `set +o pipefail` yields `0` / empty, which classifies FAIL (fail-closed) for `header_total`, `body_total`, `with_alt`, and `sample`. Could not construct a pipefail miss that classifies PASS.
- Exact `_FIXTURE_POOL` sentences, including the filename-prefix form `antonio_banderas_10. A close-up…`, still FAIL provenance.
- `sync-demo.sh` runs `bootstrap-wp.sh` (describe) before Caddy promote and the smoke heredoc when `PLUGIN_ZIP` is set. Demo Caddyfile has no cache on `/wp-json/`. Smoke reads post-bootstrap public state, not a previous deploy's Caddy config.
- Default `DEMO_ALT_GATE_ENFORCE=1` + `min_pct=95` would FAIL today's live empty library on coverage. The holes are the overrides, the denylist, and describe SKIP/BLOCK — not a missing coverage check for `""`.
