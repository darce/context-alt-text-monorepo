# VLM-6 Wave C · lane cx2 — face PUBLIC redaction + report arithmetic

**Branch:** `fix/cx2`  
**Worktree:** `/home/ubuntu/lane-gx3`  
**Base:** `7812d71c832786328705a8d6ea6e1d7f41dc487b` (`integ/fx-wave`)  
**Code commit:** `748f3226` — face PUBLIC shared redaction + score policy honesty  
**Python:** `apps/prototype-description-service/.venv/bin/python`  
**Heuristics:** TEST-15, TEST-06, DBG-10, rg-015, sr-001, AUDIT-07

---

## 1. Per finding

### VLM6-R2-A-02 (HIGH) — face PUBLIC export leaks — **FIXED**

**Reproduction (reviewer probe, pre-fix):**

```
face redact calls path redaction? False False False
LEAK: found '/home/ubuntu/private/JaneDoePrivate/cache'
LEAK: found 'http://127.0.0.1:8765/v1'
LEAK: found 'local scoring for Jane Doe Private'
LEAK: found '/home/ubuntu/secret/face-run.json'
```

Confirmed: `redact_face_report_for_public` co_names lacked `_public_provenance` /
`_redact_public_paths` / `_scrub_identity_names`. `score_face_run_record` still
copies `**fetch_provenance` into the report.

**RED (TEST-15):**

```
pytest …::test_face_public_redaction_drops_operator_paths_base_url_identity_text
E   assert '/home/ubuntu/private' not in '<serialized redacted report…>'
1 failed
```

Control asserts the leak strings are present in the pre-redaction scored report,
then fails when they survive PUBLIC.

**Fix:**
- After face-specific decision/wrong_names/labels/failures strip, call the **same**
  helpers as caption PUBLIC: `_public_provenance` → `_redact_public_paths` →
  `_scrub_identity_names` (via `_scrub_face_public_free_text`).
- Extended shared `_PUBLIC_PROVENANCE_ALLOW_FIELDS` with face-safe protocol keys
  (`zero_box_corpus`, `total_gt_boxes`, `canon_version`, `protocol_id`, `k_folds`,
  `tau_fit_status`, `sampling_frames`) — **not** a forked face allow-list (rg-015).
- Private names for scrub harvested from pre-strip non-publishable decisions /
  wrong_names / path stems (`_face_private_identity_names_for_public_scrub`).

**GREEN re-probe:**

```
face redact calls path redaction? True True True
OK '/home/ubuntu/private/JaneDoePrivate/cache'
OK 'http://127.0.0.1:8765/v1'
OK 'local scoring for Jane Doe Private'
OK '/home/ubuntu/secret/face-run.json'
OK 'Jane Doe Private'
OK 'JaneDoePrivate'
provenance keys: ['canon_version', 'head_sha', 'manifest_sha256', 'started_at',
                  'total_gt_boxes', 'zero_box_corpus']
```

Test: `test_face_public_redaction_drops_operator_paths_base_url_identity_text` — GREEN.

---

### VLM6-R2-A-03 (MEDIUM) — n=5 sample-size derivation dishonest — **FIXED (docs)**

**Reproduction:** Comment at `SCORE_PASS_MIN_SCORED_IMAGES` claimed
`0.5^5 = 0.03125 < 0.05` as gate justification. Reviewer arithmetic holds:

```
0.5**5  = 0.03125          # coin-flip all-heads, not gate false-pass
0.95**5 ≈ 0.7738           # realistic p_ok
n for 0.95^n < 0.05 → 59   # Wilson / Golden-100 territory
```

**Fix shape (a):** documentation honesty only. **Constant kept at 5** (sr-001: do
not lower a floor). Comment now states:

- n=5 = operational minimum so sparse corpora cannot certify adoption pass
- coin-flip null vs realistic p_ok=0.95 false-pass arithmetic, explicitly separated
- 5% false-pass under p_ok≈0.95 is compare/Golden-100, not this floor

**RED:** N/A for a pure comment rewrite (no production branch to invert). Arithmetic
verified in the re-probe block above.

**Cross-lane (cx6):** `cli.py` / `README.md` must not invent a 0.5^5 gate story.
Replacement wording for any operator-facing copy that mentions the floor:

> Score pass requires at least `SCORE_PASS_MIN_SCORED_IMAGES` (5) scored images.
> This is an operational minimum so undersized corpora cannot certify adoption-
> shaped pass (`not_ready`, not `fail`). It is **not** a 5% false-pass bound under
> a realistic per-image clean probability: `0.95^5 ≈ 0.77`; for `0.95^n < 0.05`
> you need `n ≈ 59` (Wilson / Golden-100 sizing). The coin-flip null
> `0.5^5 = 0.03125` is a different model and must not be cited as this gate's
> false-pass rate.

Current README only mentions sample-size in the vacuity/exit table without the
false coin-flip derivation — still should stay aligned if anyone expands it.

---

### VLM6-R2-G-06 (LOW) — quality floor magnitude + joint blast radius — **FIXED (justify + test)**

**Bake-off evidence (read, not guessed):**
`docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811-report.json`
reports `position_accuracy=None`, `placement.accuracy=None`, `placement.claims=0`.
Floors are **dormant** when `compared_images==0` / `claims==0` (code already
gates on those). No live bake-off accuracy distribution below 0.5 to conflict.

**Named frame for 0.5:** binary chance on a two-way claim (L→R / spatial
correct-incorrect). `accuracy <= 0.5` is at-or-below coin-flip → measured-and-bad
for adoption. Comparison is `<=` so the floor itself fails. **Not** the worked
example of `< 0.05` that only showed why IEEE-corner floors of 0.0 were vacuous.

**Joint blast radius (fx1 floor × fx4 hard exit):** when a measured slice hits
`<= 0.5`, score stamps `verdict=fail` with `quality-floor:` reasons **and** CLI
exits non-zero. Comment now states this combination explicitly. Constant **unchanged**
at 0.5 (sr-001).

**Test:** `test_quality_floor_realistic_midrange_and_chance_boundary`
- mid-range 0.72 / 0.65 → no quality-floor, `pass`
- exact floor 0.5 / 0.5 with `<=` → `fail` with both tokens
- unmeasured bake-off shape (compared=0, claims=0, accuracy=0.0) → dormant

**RED:** Existing floor was already 0.5 with `<=`; new test encodes intended
boundary rather than flipping a broken constant. No production revert needed to
see RED for magnitude — the finding was honesty + joint-radius documentation +
mid-range coverage.

---

### VLM6-R2-A-04 (LOW) — `coupling_flag=False` raw Python — **FIXED**

**Reproduction:** `_markdown_face` line used
`couple.get('detection_recall_coupling_flag')` raw → `False` / `True` in MD.

**RED (also visible as anchor mismatch):**

```
- coupling_flag=True
+ coupling_flag=true
test_face_generator_regenerates_byte_identical_committed_anchor FAILED
```

**Fix:** route through `_fmt_prov` (and `missed_gt` / `unmatched_det` for
consistency). Keep `"" → default` branch with comment: still live for
`base_url` / `manifest_sha256` / `started_at` / face model fields; do not delete
without a producer-invariant. Unit assert: `_fmt_prov("") == "unknown"`.

**GREEN:** face MD test asserts `coupling_flag=false|true` and rejects
`False`/`True`. `_fmt_prov(False) == "false"`.

---

## 2. Disagreements

None on defect existence. On A-03/G-06: chose **documentation honesty + keep
constants** rather than raising floors/n — sr-001 and the findings' allowed
shapes (a).

## 3. New findings (not owned)

| Item | Notes |
|------|--------|
| Face determinism MD freeze stale after A-04 | `coupling_flag=True` → `true` only diff. Cross-lane regen required. |
| Operator free-text only dropped via allow-list | If a future face-safe free-text key is allow-listed without scrub wiring, leak returns — allow-list comment warns; scrub walk covers residual strings. |

## 4. Full suite

```
cd apps/prototype-description-service
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
→ 1 failed, 1308 passed, 4 skipped, 32 warnings in ~329s
```

Baseline on base commit: `1307 passed, 0 failed, 4 skipped`.

| Class | Count | Detail |
|-------|-------|--------|
| **Expected-red** | 1 | `test_face_generator_regenerates_byte_identical_committed_anchor` — frozen face MD has `coupling_flag=True`; A-04 correctly emits `true`. Anchor freeze out of scope (must NOT touch). |
| **Unexpected-red** | 0 | — |
| **New greens** | +2 | A-02 public leak test; G-06 mid-range/chance boundary test. Face MD test extended (A-04). Net 1308 pass = 1307−1+2. |

## 5. `git diff --stat` against `7812d71c`

```
 apps/prototype-description-service/scene/tests/test_eval_harness_report.py | 108 +
 apps/prototype-description-service/scripts/eval_harness/report.py         | 174 +-
 .s2a/vlm6-cx2-report.md                                                   | (this file)
 3 files changed, …
```

Code commit only (pre-report): `2 files changed, 267 insertions(+), 15 deletions(-)`.

## 6. Could not verify

- Live bake-off runs with measured mid-range position/placement accuracy (anchors
  have `None` / `claims=0`). Floor dormancy verified from JSON + unit test, not
  a live score CLI exit path (cli.py out of scope; fx4 already owns hard exit).
- Full producer inventory for empty-string provenance fields — kept `""` branch
  rather than claiming it is dead.

## 7. Cross-lane requests

| To | Request |
|----|---------|
| **cx6** (cli/README) | Do **not** document `SCORE_PASS_MIN_SCORED_IMAGES=5` via `0.5^5 < 0.05`. Use replacement wording in §A-03 above. |
| **Anchor regen lane** (face freeze / generate_face_determinism_anchor owner) | Regenerate `S2A-face-determinism-anchor-run-20260811-face-report.md` (and JSON if needed) so `coupling_flag=true` matches `_fmt_prov`. Single-token MD drift from A-04. |
| **Coordinator** | Expected-red on face anchor is intentional until freeze regen; do not revert A-04 to keep anchor green. |

---

## TEST-15 summary

| Finding | RED captured? | How |
|---------|---------------|-----|
| A-02 | Yes | New test failed on pre-fix code with concrete leak strings |
| A-03 | N/A (comment) | Arithmetic counter-probe documented |
| G-06 | Boundary test added | Constant already correct; mid-range + `<=` edge pinned |
| A-04 | Yes | Anchor golden showed `True`→`true`; unit asserts JSON tokens |
