# Lane `hx1` — oracle-pin determinism anchor, then regenerate stale freezes

Branch: `fix/hx1` (forked from `feature/vlm-6`)
Heuristics: `TEST-15`, `AUDIT-07`, `EVAL-23`, `EVAL-13`, `rg-005`, `rg-006`, `sr-001`.

## 1. Fork baseline

Re-asserted before any edit:

```
3 failed, 1254 passed, 4 skipped, 31 warnings in 180.34s (0:03:00)
```

Matches the wave-C brief exactly. Three reds were the caption/face generator
byte-identity tests + caption expect-report green path — all cause (2) stale
freeze after gx2 S2-06/S2-07 and gx4 S4-04.

## 2. Job 1 — VLM6-S4-01 oracle-pinned scoring assertions

**File:** `scene/tests/test_eval_harness_determinism_anchor.py`

### What the oracle computes

`_seeded_deviation_oracle(manifest)` walks every golden entry with the same
seed predicates as the generator (`_predicted_face_count` / `_identity_rows`)
and applies the count-based detection formula
(`TP=min(pred,labeled)`, FP/FN = overshoot/undershoot) plus identification
wrong-name counting. It does **not** read freeze digests, `_FROZEN_DIGESTS`, or
committed report JSON.

On the shipped golden-37 corpus the oracle yields:

| quantity | value |
|---|---|
| `det_tp` | 51 |
| `det_fp` | 3 |
| `det_fn` | 6 |
| `det_precision` | 51/54 |
| `det_recall` | 51/57 |
| `wrong_name_count` | 4 |

`test_seeded_predictions_are_not_pure_gt_echo` still asserts existence of
deviations, then **scores once** via `score_run_record` and pins lower bounds
against the oracle (`fn >= oracle.fn`, `fp >= oracle.fp`,
`len(wrong_names) >= oracle.wrong_name_count`, detection P/R strictly `< 1.0`)
plus equality of the scored detection tuple against the oracle's own output
(not freeze literals).

### RED proof (GT-echo scorer stub)

Stub forces perfect detection (`tp=57`, `fp=0`, `fn=0`, P/R `1.0/1.0`) and
empty `wrong_names` while the run-record still carries seeded deviations
(existence would stay green):

```
=== GT-echo stub scores ===
detection: tp=57 fp=0 fn=0 P=1.0 R=1.0
wrong_names len=0
oracle: fn>=6 fp>=3 wrong>=4

existence face_deviations=9 id_deviations=11 (would stay GREEN)

FAILED (expected): detection fn=0 below oracle lower bound 6 (scorer may be GT-echoing; VLM6-S4-01)
FAILED (expected): detection fp=0 below oracle lower bound 3 (scorer may be GT-echoing; VLM6-S4-01)
FAILED (expected): wrong_names=0 below oracle lower bound 4 (VLM6-S4-01)
FAILED (expected): detection precision=1.0 must be strictly below 1.0 (oracle precision=0.9444444444444444; VLM6-S4-01 / TEST-15)
FAILED (expected): detection recall=1.0 must be strictly below 1.0 (oracle recall=0.8947368421052632; VLM6-S4-01 / TEST-15)

RED_PROOF_FAILURES=5
PASS: GT-echo stub trips S4-01 oracle assertions (existence would stay green)
```

### GREEN proof (unpatched)

```
scene/tests/test_eval_harness_determinism_anchor.py::test_seeded_predictions_are_not_pure_gt_echo PASSED
```

(full module post-regen: both anchor modules `33 passed`)

## 3. Job 2 — regenerate the three stale freezes

### Commands run

```
python -m scripts.eval_harness.generate_determinism_anchor
python -m scripts.eval_harness.generate_face_determinism_anchor
```

(from `apps/prototype-description-service/`; default out-dir is
`docs/tasks/vlm/bakeoff-results/`). Digests recomputed via `sha256sum` and
written into `_FROZEN_DIGESTS` — not hand-edited hex.

### Caption freeze — old→new field attribution

| field | old → new | explaining bullet |
|---|---|---|
| run-record `provenance.started_at` | `"2026-08-11T00:00:00Z"` → `null` | gx4 S4-04 pin-mode nulls contract wall-clock |
| report `provenance.started_at` | same | same |
| `faces.identity_ordering.degraded_images` | `37` → `0` | gx2 S2-07: true DEGRADED stamp count only (golden has none) |
| `faces.identity_ordering.degraded_paths` | 37 paths → `[]` | gx2 S2-07: empty when no true degraded stamps |
| verdict reason positional | cites `degraded_images=37` → cites `order_unknown_excluded=37` | gx2 S2-07 vacuity text |
| verdict reason fabricated_fact | `…AUDIT-07)` → `…AUDIT-07 / S2-01)` | gx2 S2-01 trailer on stamped-null/vacuous fab |
| verdict reasons | +1 row | gx2 S2-06: `category-vacuity: identity_ordering — positional_images=0 …` |
| MD `head_sha` | `` `None` `` → `` `null` `` | gx2 S4-05 `_fmt_prov` (renderer already fixed; regen surfaces it) |
| MD `started_at` | sentinel clock → `null` | gx4 S4-04 + S4-05 |
| MD identity-ordering warning | "degraded on 37…" + path list → "order unknown (no face_boxes) on 37…" | gx2 S2-07 disclosure |

No unexplained field moved. Run-record body (items / seeded deviations) is
byte-stable except the provenance clock null; scoring numbers that are not
vacuity-related (detection P/R, wrong_names, caption rates) did not move.

### Face freeze — old→new field attribution

| field | old → new | explaining bullet |
|---|---|---|
| run-record `provenance.started_at` | sentinel → `null` | gx4 S4-04 |
| face-report `provenance.started_at` | sentinel → `null` | gx4 S4-04 |
| MD `head_sha` | `` `None` `` → `` `null` `` | gx2 S4-05 |
| manifest | unchanged (digest stable) | expected — corpus body untouched |

Face rates / slice numbers / unknown_rejection rate all identical.

### Optional AUDIT-07 (`missed_stranger_gt` on `slices.unknown_rejection`)

**Skipped.** Surfacing the key requires editing
`scripts/eval_harness/report.py` (explicit comment at the freeze-stability
deferral), which this lane does **not** own. Regen alone cannot invent the
key. Cross-lane request below.

### `_FROZEN_DIGESTS` updated

Caption triple + face quadruple digests recomputed after regen and written into:

- `scene/tests/test_eval_harness_determinism_anchor.py`
- `scene/tests/test_eval_harness_face_determinism_anchor.py`

(Digest hex intentionally omitted from this prose report so
`check_lane_report_shas.py` is not asked to resolve artifact digests as SHAs.)

## 4. Final suite

```
1257 passed, 4 skipped, 31 warnings in 173.28s (0:02:53)
```

(`0 failed` — baseline was 3 failed / 1254 passed; Job 1 added no net tests that
stay red, Job 2 cleared the three freeze reds.)

## 5. What you could not verify

- End-to-end operator adoption path on a real golden-100 corpus (unit +
  harness-37 only).
- That a future generator edit which silently changes seed predicates would
  still keep oracle and generator in lockstep — the oracle imports the same
  helpers (`_predicted_face_count` / `_identity_rows`), so a helper rewrite
  that preserves pure-GT-echo behaviour would still fail the lower-bound
  self-check on the oracle itself; a scorer-only GT-echo is the controlled RED.
- Optional `missed_stranger_gt` JSON disclosure (blocked on report.py ownership).
- Concurrent lane hx2 edits to the generators while this regen ran — generators
  were treated as read-only entry points; no generator source was modified.

## 6. Cross-lane requests

1. **AUDIT-07 optional disclosure** (report.py owner): add
   `"missed_stranger_gt": unknown.missed_stranger_gt` (or equivalent) under
   `slices.unknown_rejection` in `score_face_run_record` / the freeze JSON path,
   then re-run the face generator. Rates already embed the count; only the
   explicit key is missing. Comment at the deferral site already anticipates
   post-regen surfacing.
2. No generator defects found; no hx2 coordination needed beyond "do not land
   generator behaviour changes that alter freeze bytes without a paired regen".
