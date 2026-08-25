# DEMOLIVE-7 describe-gate TEST-15 report

Lane `demolive-7`. Command: `bash infra/oci/demo/tests/test-describe-gate.sh`.

The original 38 assertions remain and still pass. New assertions cover live-adapter probing, BLOCK `exit 1`, and provenance-aware SKIP/RUN_FORCE. Each fix was mutated back to the old behaviour, the suite was run, the verbatim FAIL line(s) and exit code captured, then the mutation reverted. After restore the suite is green. No mutation remains in the tree.

`--force` exists on `wp alt-context describe generate` (`[--force]` in `apps/prototype-wp-alt-context/src/cli/class-description-command.php`) before RUN_FORCE wiring.

## Fix 1 — R1-05 live producer probe

**Change.** `bootstrap-wp.sh` no longer reads `env_get ACX_DESCRIPTION_ADAPTER`. It GETs `/health/detailed` with `ACX_RECOGNITION_URL` + `ACX_RECOGNITION_API_KEY` from the existing `WORDPRESS_CONFIG_EXTRA` defines, and gates on the probed top-level `description_adapter` string. Probe failure, non-2xx, missing field, or unparseable body yields an empty profile → BLOCK. Never falls back to `secrets/.env`. The config-fault BLOCK message names the live service adapter and tells the operator to change the description SERVICE profile, not the demo env file.

**Mutation.** Replaced `ADAPTER_PROFILE="$(probe_live_description_adapter)"` with `ADAPTER_PROFILE="$(env_get ACX_DESCRIPTION_ADAPTER)"`.

**Command.** `bash infra/oci/demo/tests/test-describe-gate.sh`

**Exit code.** 1

**Verbatim FAIL line.**

```
FAIL bootstrap does not env_get ACX_DESCRIPTION_ADAPTER: expected /home/gate/grok-sandbox/feature-demolive-7-5581e3c5/infra/oci/demo/tests/../bootstrap-wp.sh NOT to match /env_get ACX_DESCRIPTION_ADAPTER/
```

**After restore.** PASSED (`all assertions passed`, exit 0).

## Fix 2 — BLOCK exits 1 (RLSE-08)

**Change.** The describe-apply `*)` BLOCK arm ends with `exit 1`. Config-fault (untrusted / unprobed producer) and environment-fault (trusted adapter, unmeasurable coverage or provenance) keep distinct messages; both abort bootstrap instead of printing "Bootstrap complete".

**Mutation.** Deleted the BLOCK arm's `    exit 1` line so the script falls through again.

**Command.** `bash infra/oci/demo/tests/test-describe-gate.sh`

**Exit code.** 1

**Verbatim FAIL line.**

```
FAIL config-fault BLOCK exits 1: expected /home/gate/grok-sandbox/feature-demolive-7-5581e3c5/infra/oci/demo/tests/../bootstrap-wp.sh to match /exit 1/
```

**After restore.** PASSED (`all assertions passed`, exit 0).

## Fix 3 — R1-04 provenance SKIP / RUN_FORCE

**Change.** `classify_describe_gate` takes a 4th argument `provenance` (`PASS|FAIL|UNKNOWN`; omitted/garbage = UNKNOWN). Full coverage + PASS → SKIP. Full coverage + FAIL → `RUN_FORCE`. Full coverage + UNKNOWN → BLOCK. Partial coverage still RUN. `bootstrap-wp.sh` samples published alt text, classifies fixture-caption provenance, and on `RUN_FORCE` runs `wp alt-context describe generate --write --force --limit=100`.

The two original full-coverage SKIP assertions now pass explicit `PASS` so they keep expecting SKIP without weakening the 38-assertion baseline. 3-arg full coverage (omitted provenance) now BLOCKs.

**Mutation.** Restored unconditional `echo SKIP` when `with_alt -eq total`, ignoring provenance.

**Command.** `bash infra/oci/demo/tests/test-describe-gate.sh`

**Exit code.** 1

**Verbatim FAIL lines.**

```
FAIL florence_small 10 10 FAIL -> RUN_FORCE: expected RUN_FORCE, got SKIP
FAIL gpu_qwen30b_ensemble 100 100 FAIL -> RUN_FORCE: expected RUN_FORCE, got SKIP
FAIL florence_small 10 10 UNKNOWN -> BLOCK: expected BLOCK, got SKIP
FAIL florence_small 10 10 omitted provenance -> BLOCK: expected BLOCK, got SKIP
FAIL florence_small 10 10 garbage provenance -> BLOCK: expected BLOCK, got SKIP
```

**After restore.** PASSED (`all assertions passed`, exit 0).

## Residual (out of lane)

`generate --limit` still selects only `missing_alt` candidates. `--force` overwrites when a media id is already selected, but a 100/100 canned corpus may still no-op until the CLI enumerates existing-alt ids. Not changed here (PHP CLI is not this lane).

## Round 2 — XLANE-01

**Route.** (b), plus a canonical extra file for DEMOLIVE-6 to concatenate later.

Both ship paths are single-file and this lane cannot edit them: `sync-demo.sh` SCPs only `infra/oci/demo/lib/describe-gate.sh`, and smoke-gate is `cat "$SMOKE_GATE_LIB"` into the remote bash. An extra sourced file would break the VM unless `scripts/deploy/sync-demo.sh` or `smoke-gate.sh` changed (forbidden). So describe-gate stays self-contained. `scripts/deploy/lib/fixture-denylist.sh` is the canonical normalizer + denylist; describe-gate inlines the same two functions. A corpus + function-body test FAILs if the copies drift. `classify_alt_provenance` was not rewritten.

**Diff.** `classify_describe_provenance` now lowercases, collapses whitespace with `tr -s '[:space:]' ' '`, strips trailing `.!?` in a loop, then matches lowercase punctuation-free arms via `fixture_sample_is_denied`. Empty sample still UNKNOWN. `classify_describe_gate` / bootstrap wiring unchanged.

**Corpus (specified smoke / describe).** Live `classify_alt_provenance` in *this* worktree is still the pre-DEMOLIVE-6 exact-match copy, so evasion rows are bound against the shared matcher (`smoke-sem`) rather than by rewriting their file. After trial-merge, if live smoke FAILs a lowercased fixture, the same rows assert live-smoke too.

| sample | smoke-sem | describe | live smoke (this worktree) |
| --- | --- | --- | --- |
| `A close-up of a small object on a neutral background.` | FAIL | FAIL | FAIL |
| `A close-up of a small object on a neutral background` | FAIL | FAIL | PASS (pre-normalization copy) |
| `a close-up of a small object on a neutral background.` | FAIL | FAIL | PASS (pre-normalization copy) |
| ` A Close-Up Of A Small Object On A Neutral Background ` | FAIL | FAIL | PASS (pre-normalization copy) |
| `A close-up of a small object on a  neutral background!` | FAIL | FAIL | PASS (pre-normalization copy) |
| `A close-up of a small object on a neutral background!` | FAIL | FAIL | PASS (pre-normalization copy) |
| `A woman in a red coat crossing Charing Cross Road.` | PASS | PASS | PASS |
| `""` | FAIL | UNKNOWN | FAIL (documented difference) |

Empty sample is asserted as FAIL / UNKNOWN on purpose: smoke fails closed, describe reports UNKNOWN because nothing was measured.

**TEST-15.** Reverted `classify_describe_provenance` to the case-sensitive exact-match arms. Command: `bash infra/oci/demo/tests/test-describe-gate.sh`. Exit code: 1.

Verbatim FAIL line:

```
FAIL corpus describe no period: expected FAIL, got PASS
```

Also red (same mutation): `lowercased`, `case + padding`, `double space + bang`, `bang only` (5 assertions failed). Restored the normalizer; suite green (`all assertions passed`, exit 0). No mutation remains.

**Command.** `bash infra/oci/demo/tests/test-describe-gate.sh` — PASS, exit 0. `bash scripts/deploy/tests/test-smoke-gate.sh` — PASS, exit 0 (read-only; smoke-gate logic not edited).
