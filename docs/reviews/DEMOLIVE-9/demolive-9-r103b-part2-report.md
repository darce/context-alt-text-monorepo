# DEMOLIVE-9 R1-03B part 2 — adapter-identity smoke gate

Lane: `demolive-9`  
Finding: `DEMOLIVE-9-R1-03B`  
Code checkpoint: `d0bda3057df32ba692f6f5fc6b8f55ec8d87188f`  
Did not touch `apps/prototype-wp-alt-context/`. Did not change `DEMO_ALT_GATE_ENFORCE` or `DEMO_ALT_MIN_COVERAGE_PCT` semantics.

## Edits

- `scripts/deploy/sync-demo.sh:40-50` — concatenation-order comment (describe-gate, then canonical denylist, then smoke-gate)
- `scripts/deploy/sync-demo.sh:207-210` — `cat "$DESCRIBE_GATE_SRC"` ahead of fixture-denylist and smoke-gate
- `scripts/deploy/sync-demo.sh:293` — probe `_fields=id,alt_text,acx_alt_provenance`
- `scripts/deploy/sync-demo.sh:309-317` — scrape whitespace-separated adapter values (`"adapter": *"..."`)
- `scripts/deploy/sync-demo.sh:358-369` — `classify_alt_provenance "$sample" "$adapters" "$with_alt"`; FAIL messages distinguish untrusted/absent identity from seeded fixture caption
- `scripts/deploy/lib/smoke-gate.sh:7-19` — concatenation-order header; fixture-denylist copies win the helper collision
- `scripts/deploy/lib/smoke-gate.sh:157-184` — `classify_alt_identity` (Gate A)
- `scripts/deploy/lib/smoke-gate.sh:197-215` — `classify_alt_provenance` ANDs Gate A with retained Gate B denylist
- `scripts/deploy/tests/test-smoke-gate.sh` — source describe-gate first; identity pins; helper-drift pin; `_fields` pin; pipeline call-site match
- `infra/oci/demo/tests/test-describe-gate.sh:182,205,222` — live-smoke calls pass `florence_small 1` so Gate B stays the corpus bind

No second literal trusted-profile list. `ACX_TRUSTED_DESCRIBE_PROFILES` / `is_trusted_describe_profile` remain defined only in `infra/oci/demo/lib/describe-gate.sh`.

## Verdict table (as shipped)

Gates are ANDed, not fused. PASS only when both pass.

| adapters_blob | denylist (sample) | usable_count | verdict | failing gate |
| --- | --- | --- | --- | --- |
| trusted × N | clean | N | PASS | — |
| trusted × 3 (`florence_small gpu_qwen30b gpu_qwen30b_ensemble`) | clean | 3 | PASS | — |
| `seeded` (untrusted) | clean | 1 | FAIL | A identity |
| mixed trusted + untrusted | clean | 2 | FAIL | A identity |
| empty / whitespace-only | clean | >0 | FAIL | A identity (fail closed) |
| trusted × 1 | clean | 2 (fewer than usable) | FAIL | A identity |
| any | any | empty / non-numeric | FAIL | A identity |
| trusted × N | denylisted fixture caption | N | FAIL | B denylist |
| trusted × N | empty after normalize | N | FAIL | B denylist |
| empty | n/a | 0 | Gate A PASS; Gate B decides | B if empty sample |

Operator FAIL lines (INT-10):

- identity: `untrusted or absent adapter identity behind N published alt texts`
- denylist: `seeded fixture caption detected in N published alt texts`

## Concatenation order

Remote heredoc (later definition wins):

1. `infra/oci/demo/lib/describe-gate.sh` — `ACX_TRUSTED_DESCRIBE_PROFILES` + `is_trusted_describe_profile`. Also carries a VM-self-contained copy of `normalize_fixture_sample` / `fixture_sample_is_denied`.
2. `scripts/deploy/lib/fixture-denylist.sh` — **canonical denylist helpers win**. Source of truth for Gate B. describe-gate's copies exist so `bootstrap-wp.sh` can SCP a single file.
3. `scripts/deploy/lib/smoke-gate.sh` — classifiers.

Neither helper copy was deleted. A drift pin in `test-smoke-gate.sh` FAILs if the two bodies stop agreeing once comments and blank lines are stripped.

## Green suites

### `bash scripts/deploy/tests/test-smoke-gate.sh`

Exit code: **0**

Verbatim final line:

```
all assertions passed
```

### `bash infra/oci/demo/tests/test-describe-gate.sh`

Exit code: **0**

Verbatim final line:

```
all assertions passed
```

## TEST-15

Applied to `scripts/deploy/lib/smoke-gate.sh` after the code commit, re-ran `test-smoke-gate.sh`, reverted. `git status --short` clean afterwards.

### M1 — delete empty-blob `usable_count > 0 → FAIL` arm

Change: in `classify_alt_identity`, empty/whitespace `adapters_blob` falls through to `echo PASS` instead of FAIL when `usable_count > 0`.

Exit code: **1**

Verbatim:

```
FAIL alt provenance empty adapters blob usable 1 (fail closed): expected FAIL, got PASS
FAIL alt provenance whitespace adapters blob usable 1 (fail closed): expected FAIL, got PASS
2 assertion(s) failed
```

Reverted with `git checkout -- scripts/deploy/lib/smoke-gate.sh`.

### M2 — remove Gate B (identity only)

Change: `classify_alt_provenance` returns PASS after Gate A; `normalize_fixture_sample` / `fixture_sample_is_denied` no longer called.

Exit code: **1**

Verbatim (load-bearing pin plus suite):

```
FAIL alt provenance trusted adapter AND denylisted caption: expected FAIL, got PASS
FAIL R1-01B fixture captions ENFORCE=0 still blocked (provenance locked): expected 1, got 0
24 assertion(s) failed
```

Also red: empty-after-normalize, all eight fixture captions, evasion rows, `_FIXTURE_POOL` drift. Proves the gates are independent: identity PASS does not certify a canned caption.

Reverted with `git checkout -- scripts/deploy/lib/smoke-gate.sh`.

## Could not falsify

- WP REST pretty-printing `"adapter"` across a newline (same scrape limit as existing `"alt_text": *"` grep). Compact and space-after-colon forms are handled.
- A future `"adapter"` string field outside `acx_alt_provenance` on the same `_fields` projection. Today's field set is `id,alt_text,acx_alt_provenance` only.
- `DEMO_ALT_GATE_ENFORCE` / `DEMO_ALT_MIN_COVERAGE_PCT` hatch semantics (separate findings).
- Plugin-side projection of `acx_alt_provenance` (part 1; this lane consumes it).
