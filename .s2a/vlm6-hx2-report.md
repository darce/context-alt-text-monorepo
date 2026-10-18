# Lane `hx2` — permanent regression tests for gx4 durability fixes

Branch: `fix/hx2` (forked from `feature/vlm-6` @ `2b0fe633`)
Heuristics: TEST-15, AUDIT-07, EVAL-23, rg-002, rg-006, rg-008, sr-001, sr-006

## 1. What you added

| File | Fix | RED condition encoded |
|---|---|---|
| `scene/tests/test_vlm_promote_atomicity.py` | **S4-02** journaled set-atomic promote | Bare per-file `os.replace` loop leaves mixed dest after mid-crash; production path + `_recover_promote` must converge to all-new (installing) or all-old (staged-only). Asserts on actual file set contents, not log lines. |
| `scene/tests/test_describe_baseline_pin_provenance.py` | **S4-04** pin mode nulls provenance | Pin-mode `write_anchor` must set `provenance.head_sha` **and** `provenance.started_at` to `None` while keeping `fixture_revision` (`0`×40) and `canonical_timestamp` (`2026-08-11T00:00:00Z`). Negative: non-pin (`pin_live_provenance=False`) must **not** null live values. Face twin via `build_face_anchor_run_record`. |
| same file | **S4-06** `resolve_head_sha` refuses sentinel | `pytest.raises(SystemExit)` on `0`×40; message names fabricated sentinel; genuine 40-hex SHA still passes; module default is not forty zeros. |

Production modules **not** edited (gx4 / hx1 ownership): `describe_baseline.py`, `generate_determinism_anchor.py`, `generate_face_determinism_anchor.py`, existing determinism-anchor tests, bakeoff-results.

## 2. Six captures (RED + GREEN per fix)

### 2.1 S4-02 — promote atomicity

**RED** (pre-fix bare per-file loop; permanent test `test_s4_02_pre_fix_naive_loop_leaves_mixed` encodes this path; GREEN production path is separate):

> Rename note (VLM6-S6-02): that test is now `test_naive_per_file_replace_is_mixed_documents_why_journaling_is_needed`. It documents the motivating failure mode, not production behaviour; the real S4-02 guards are the sibling GREEN tests.

```
=== S4-02 RED (pre-fix bare per-file loop) ===
raised: KeyboardInterrupt: kill after replace #1
dest state after kill: {'man.json': 'NEW_man.json', 'run.json': 'OLD_run.json', 'rep.json': 'OLD_rep.json'}
MIXED=True  (expected True for RED proof against per-file loop)
ASSERTION FAILED (RED as expected): destination must never be mixed, got {'man.json': 'NEW_man.json', 'run.json': 'OLD_run.json', 'rep.json': 'OLD_rep.json'}
```

**GREEN** (journaled `_atomic_promote` + `_recover_promote` on live code):

```
=== S4-02 GREEN (journaled promote + recover) ===
raised: KeyboardInterrupt: kill after artifact replace #1
mid-crash state (before recover): {'man.json': 'NEW_man.json', 'run.json': 'OLD_run.json', 'rep.json': 'OLD_rep.json'}
MIXED_BEFORE_RECOVER=True
after recover: {'man.json': 'NEW_man.json', 'run.json': 'NEW_run.json', 'rep.json': 'NEW_rep.json'}
ALL_NEW=True ALL_OLD=False MIXED=False
PASS: recovery yields fully NEW set

S4-02 GREEN: crash before install (staged) → recover → all-old
raised: kill at journal phase=installing
after recover: {'man.json': 'OLD_man.json', 'run.json': 'OLD_run.json', 'rep.json': 'OLD_rep.json'}
PASS: staged-only crash recovers to all-OLD

S4-02 GREEN: full promote no crash
PASS: clean promote, no journal left
```

### 2.2 S4-04 — pin mode nulls provenance

**RED** (pre-fix data shape: pin nulls `head_sha` but leaks canonical wall-clock into `started_at`; assertion is the permanent pin-mode check):

```
=== S4-04 RED (pre-fix: pin fabricates started_at wall-clock) ===
head_sha=None
started_at='2026-08-11T00:00:00Z'
fixture_revision='0000000000000000000000000000000000000000'
canonical_timestamp='2026-08-11T00:00:00Z'
FABRICATED_STARTED_AT=True
face twin: started_at='2026-08-11T00:00:00Z' FABRICATED_STARTED_AT=True
ASSERTION FAILED (RED as expected): pin mode must null started_at, got '2026-08-11T00:00:00Z'
```

**GREEN** (live `write_anchor` pin + non-pin negative + face twin):

<!-- sha-guard:ignore-next-block -->
```
=== S4-04 GREEN (pin mode nulls contract clocks) ===
head_sha=None
started_at=None
fixture_revision='0000000000000000000000000000000000000000'
canonical_timestamp='2026-08-11T00:00:00Z'
PASS: caption pin nulls contract clocks; sentinels in fixture_* only
non-pin head_sha='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' started_at='2026-01-02T03:04:05Z'   (synthetic test fixture, not a git object)
PASS: non-pin keeps live provenance (negative guard)
face head_sha=None started_at=None
face fixture_revision='0000000000000000000000000000000000000000' canonical_timestamp='2026-08-11T00:00:00Z'
PASS: face pin nulls contract clocks
```

### 2.3 S4-06 — `resolve_head_sha` refuses sentinel

**RED** (pre-fix resolve: default `0`×40 accepted as real SHA; no SystemExit):

```
=== S4-06 RED (clean) ===
HEAD_SHA default='0000000000000000000000000000000000000000'
IS_FORTY_ZEROS=True
would write summary.head_sha='0000000000000000000000000000000000000000'
pre-fix resolve_head_sha('0'*40) returned without SystemExit
pytest.raises(SystemExit, match='fabricated 40-zero sentinel') → FAILED
ASSERTION FAILED (RED as expected): DID NOT RAISE SystemExit matching 'fabricated 40-zero sentinel'
```

**GREEN** (live `describe_baseline.resolve_head_sha`):

<!-- sha-guard:ignore-next-block -->
```
=== S4-06 GREEN (resolve refuses zeros; accepts real SHA) ===
module HEAD_SHA=None
resolve unset=None
refuse zeros: HEAD_SHA is the fabricated 40-zero sentinel; pass a real 40-char git SHA via HEAD_SHA or unset it to record null (S4-06 / rg-015 / VLM6-F-04)
report summary.head_sha=None
PASS: report writes null without fabricating zeros
write refuse zeros: HEAD_SHA is the fabricated 40-zero sentinel; pass a real 40-char git SHA via HEAD_SHA or unset it to record null (S4-06 / rg-015 / VLM6-F-04)
PASS: S4-06 write refuses forty zeros
PASS: genuine SHA accepted: aaaaaaaa…   (synthetic test fixture)
```

### Permanent suite (GREEN)

```
apps/prototype-description-service/.venv/bin/python -m pytest \
  scene/tests/test_vlm_promote_atomicity.py \
  scene/tests/test_describe_baseline_pin_provenance.py \
  -q -p no:randomly

.............                                                            [100%]
13 passed in 1.29s
```

## 3. `git diff --stat` against fork point

Fork point = `feature/vlm-6` @ `2b0fe633`. Lane commit: `09b0836a`.
New files only (production / hx1-owned surfaces untouched):

```
 .s2a/vlm6-hx2-report.md                            | 146 ++++++++++++++
 .../tests/test_describe_baseline_pin_provenance.py | 116 +++++++++++
 .../scene/tests/test_vlm_promote_atomicity.py      | 216 +++++++++++++++++++++
 3 files changed, 478 insertions(+)
```

## 4. What you could not verify

- Did **not** re-run the full `scene/tests/` suite (brief: not required; 3 known-red tests owned by hx1).
- S4-04 RED was constructed by driving the **pre-fix provenance shape** (and asserting the permanent pin checks against it), not by monkeypatching `write_anchor` internals — the fix is already shipped and hx1 owns generator edits. The RED is still a genuine failure of the permanent assertion against pre-fix data.
- S4-06 RED similarly used a pre-fix `resolve` stub (accepts zeros) rather than git-reverting `describe_baseline.py` (prohibited). Permanent tests exercise the live function and pass.
- Transient mid-install mixed tree before recovery is **documented and allowed** (gx4); permanent tests assert recovery converges and that the bare pre-fix loop is permanently mixed.
- No network / no real model weights — all tmp-dir synthetic fixtures.

## 5. Cross-lane requests

- None blocking. gx4 production fixes are green under these pins.
- hx1 continues to own regenerating bakeoff-results + updating `test_eval_harness_*_determinism_anchor.py` digests for the `started_at → null` shape (known red; not this lane).
- S4-05 (`report.py` rendering `None` as Python identifier) remains gx4's cross-lane note — out of hx2 ownership.
