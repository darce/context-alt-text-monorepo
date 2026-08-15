# Lane gx4 — set-atomic freeze promotion + kill fabricated provenance

Branch: `fix/gx4` (forked from `feature/vlm-6` @ `8ae228aa`)
Heuristics: TEST-15, EVAL-04, EVAL-23, AUDIT-07, rg-002, rg-006, rg-009, rg-015, sr-001

## 1. What changed

- `apps/prototype-description-service/scripts/eval_harness/generate_determinism_anchor.py` — journaled set-atomic promote (S4-02); pin mode nulls `started_at` (S4-04); empty-string started_at → None.
- `apps/prototype-description-service/scripts/eval_harness/generate_face_determinism_anchor.py` — same set-atomic promote (S4-02); CLI `--fixture-revision` / `--canonical-timestamp` primary with legacy aliases (S4-03); pin mode nulls `started_at` (S4-04); docstring corrected.
- `apps/prototype-description-service/scripts/eval_harness/describe_baseline.py` — remove forty-zero default; `resolve_head_sha()` returns None or real SHA, refuses explicit zeros (S4-06).
- `.s2a/vlm6-gx4-report.md` — this report.

## 2. Per-finding resolution

### S4-02 [high] — set-atomic promote

**Done.** Both generators share the same algorithm:

1. `_recover_promote` repairs any prior journal.
2. Stage the full named set under `dest/.vlm-promote-stage-<token>/` and fsync every file + dir.
3. Journal `phase=staged` then `phase=installing`.
4. Install each name from the durable stage via tmp + `os.replace`.
5. Drop journal + stage.

**Why not a single directory rename of `dest_dir`:** `out_dir` is the shared `bakeoff-results` tree (many unrelated freezes). Renaming the whole directory is not workable (justified alternative from the brief).

**Guarantee (docstring-accurate):** after return, **or after crash + `_recover_promote`** (auto on next promote), every named path is fully old or fully new — never mixed. A crash mid-install can leave a transient mixed tree until recovery; the durable stage + journal always recover to all-new when install had begun, or all-old if only staged.

### S4-03 [medium] — face CLI fabricated `head_sha` advertising

**Done.** Face CLI mirrors caption:

- Primary: `--fixture-revision`, `--canonical-timestamp`
- Legacy: `--head-sha` / `--started-at` map onto fixture sentinels; help text states they do **not** write contract `provenance.head_sha` / `started_at`
- Module docstring updated to fixture_* sentinels; contract fields null in pin mode

### S4-04 [medium] — `started_at` fabricated wall-clock

**Done.** Pin mode (both generators) now writes:

| field | value |
|---|---|
| `provenance.head_sha` | `null` |
| `provenance.started_at` | `null` |
| `provenance.fixture_revision` | typed sentinel (`0`×40 default) |
| `provenance.canonical_timestamp` | typed sentinel (`2026-08-11T00:00:00Z`) |

Choice: null the contract wall-clock key (same shape as `head_sha`), keep `canonical_timestamp` as the sole byte-stability clock sentinel. No renamed pin namespace.

### S4-06 [medium] — `describe_baseline` forty zeros

**Done.**

- Module `HEAD_SHA` default is `None` (not `"0"*40`).
- `resolve_head_sha()`: unset/empty → `None`; explicit forty zeros → `SystemExit`; other values must be 40 lowercase hex.
- Report `summary.head_sha` uses `resolve_head_sha()` (null when unset).
- `fetch_run_record(..., head_sha=resolve_head_sha() or "")` — empty string when unset (cli.py requires `str`; not edited).

## 3. TEST-15 proofs

File ownership forbade adding permanent test modules. Proofs are ad-hoc scripts against the owned generators; RED captured **before** the fix, GREEN after.

### 3.1 S4-02 crash-atomicity

**RED (pre-fix per-file loop):**

```
S4-02 RED: crash mid per-file promote
raised: KeyboardInterrupt: kill after replace #1
dest state after kill: {'man.json': 'NEW_man.json', 'run.json': 'OLD_run.json', 'rep.json': 'OLD_rep.json'}
MIXED=True  (expected True for RED proof against per-file loop)
```

**GREEN (post-fix journaled promote + recover):**

```
S4-02 GREEN: crash mid set-promote + recover
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

### 3.2 S4-04 pin path `started_at: null` + typed `fixture_revision`

**RED:**

```
head_sha=None
started_at='2026-08-11T00:00:00Z'
fixture_revision='0000000000000000000000000000000000000000'
canonical_timestamp='2026-08-11T00:00:00Z'
FABRICATED_STARTED_AT=True

face twin: started_at='2026-08-11T00:00:00Z' FABRICATED_STARTED_AT=True
```

**GREEN:**

```
head_sha=None
started_at=None
fixture_revision='0000000000000000000000000000000000000000'
canonical_timestamp='2026-08-11T00:00:00Z'
PASS: caption pin nulls contract clocks; sentinels in fixture_* only

face head_sha=None started_at=None
face fixture_revision='000000…0' canonical_timestamp='2026-08-11T00:00:00Z'
PASS: face pin nulls contract clocks
```

### 3.3 S4-06 describe_baseline refuses / nulls forty zeros

**RED:**

```
HEAD_SHA default='0000000000000000000000000000000000000000'
IS_FORTY_ZEROS=True
would write summary.head_sha='0000000000000000000000000000000000000000'
```

**GREEN:**

```
module HEAD_SHA=None
resolve unset=None
refuse zeros: HEAD_SHA is the fabricated 40-zero sentinel; pass a real 40-char git SHA via HEAD_SHA or unset it to record null (S4-06 / rg-015 / VLM6-F-04)
report summary.head_sha=None
PASS: report writes null without fabricating zeros
write refuse zeros: HEAD_SHA is the fabricated 40-zero sentinel; ...
PASS: S4-06 write refuses forty zeros
```

### 3.4 Generator determinism (hashseed 0 vs 1 → byte-identical tmp)

```
cap/stem.json: match=True sha=d105f3adccb2f574 sha-guard:ignore
cap/stem-report.json: match=True sha=1dea1f8d98bfb55d sha-guard:ignore
cap/stem-report.md: match=True sha=d2eeee5558f240e1 sha-guard:ignore
face/mstem.json: match=True sha=1209733ed2b62e83 sha-guard:ignore
face/fstem.json: match=True sha=a5264540eb1fe7aa sha-guard:ignore
face/fstem-face-report.json: match=True sha=fbea3c228f527d65 sha-guard:ignore
face/fstem-face-report.md: match=True sha=6452cc66134ec07d sha-guard:ignore
PASS: hashseed 0/1 byte-identical for caption+face generators
```

## 4. Suite result

```
3 failed, 1234 passed, 4 skipped, 28 warnings in 143.81s (0:02:23)
```

Baseline at fork: **1237 passed, 4 skipped, 0 failed**.

### Failures

| test | cause | expected? |
|---|---|---|
| `test_generator_regenerates_byte_identical_committed_anchor` | regen writes `started_at: null`; committed freeze still has sentinel clock | **Yes — regen lane** |
| `test_face_generator_regenerates_byte_identical_committed_anchor` | same for face run + face-report JSON | **Yes — regen lane** |
| `test_cli_score_determinism_guard_pins_import_root_against_cwd_decoy` | decoy-root import of `report.py` → `recognition` ModuleNotFoundError; **not caused by this lane** (we did not touch cli/report) | **No — pre-existing / env; note only** |

Committed digest pins (`test_committed_*_digests_match_frozen`) stay green — we did not edit bakeoff-results (sr-001).

## Cross-lane requests

### S4-05 — `report.py` renders `None` as Python identifier

`report.py:1767` (approx):

```python
f"- head_sha: `{prov.get('head_sha', 'unknown')}`",
...
f"- started_at: {prov.get('started_at', 'unknown')}",
```

With pin-mode `started_at: null`, caption MD now shows:

```
- started_at: None
```

Owning lane should render JSON-null as ``null`` / omit / `unknown`, not the Python identifier. Suggested:

```python
def _fmt_prov(value: object, *, default: str = "unknown") -> str:
    if value is None:
        return "null"
    return str(value)

f"- head_sha: `{_fmt_prov(prov.get('head_sha'))}`",
f"- started_at: {_fmt_prov(prov.get('started_at'))}",
```

(Same pattern at the second `head_sha` render ~line 3165 if present.)

### cli.py `fetch_run_record` head_sha type

`describe_baseline` must pass `str` into `fetch_run_record`. When unset we pass `""`. Prefer `head_sha: str | None = None` on the live path so empty string is not written into run-records — out of this lane's ownership.

## Handoff to the regen lane

**Do not regenerate in this lane.** After all parallel lanes land, regenerate once.

### Anchor tests this change turns red

1. **`test_generator_regenerates_byte_identical_committed_anchor`**
   - Message shape: `assert <regen bytes> == <committed bytes>` at run-record compare; first delta is provenance `started_at` (`"2026-08-11T00:00:00Z"` → `null`), which also moves report JSON + report MD (`started_at: None` line until S4-05 lands).

2. **`test_face_generator_regenerates_byte_identical_committed_anchor`**
   - Same assert shape; face run-record + face-report JSON only (`started_at` → null). Manifest + face-report MD digests already match.

3. After regen, **`test_committed_*_digests_match_frozen`** will fail until `_FROZEN_DIGESTS` are updated to the new SHAs (regen lane owns those modules).

### Predicted before → after (headline provenance)

Metrics/gating numbers are **unchanged** by this lane (no `*_metrics.py` / `report.py` / `cli.py` scoring edits). Only provenance contract fields move:

| artifact | field | before (committed) | after (this generator) |
|---|---|---|---|
| caption run JSON | `provenance.started_at` | `"2026-08-11T00:00:00Z"` | `null` |
| caption run JSON | `provenance.head_sha` | `null` | `null` (unchanged) |
| caption run JSON | `provenance.fixture_revision` | `"0"×40` | `"0"×40` |
| caption run JSON | `provenance.canonical_timestamp` | `"2026-08-11T00:00:00Z"` | `"2026-08-11T00:00:00Z"` |
| caption report JSON | `provenance.started_at` | `"2026-08-11T00:00:00Z"` | `null` |
| caption report MD | `started_at` line | `2026-08-11T00:00:00Z` | `None` (until S4-05 → prefer `null`) |
| face run JSON | `provenance.started_at` | `"2026-08-11T00:00:00Z"` | `null` |
| face report JSON | `provenance.started_at` | `"2026-08-11T00:00:00Z"` | `null` |
| face manifest | (body) | unchanged | unchanged |
| face report MD | | unchanged | unchanged |

**Headline metric numbers (detection P/R, identification, caption scores, verdict):** no movement from this lane alone. Sibling lanes changing metrics/gating will move numbers; this lane only forces provenance `started_at → null`.

### Files whose digests must update on regen

- `S2A-determinism-anchor-run-20260811.json`
- `S2A-determinism-anchor-run-20260811-report.json`
- `S2A-determinism-anchor-run-20260811-report.md`
- `S2A-face-determinism-anchor-run-20260811.json`
- `S2A-face-determinism-anchor-run-20260811-face-report.json`

Unchanged (this lane): face manifest, face report MD.

## What you could not verify

- Permanent pytest modules for S4-02/04/06 were **not** added (strict file ownership). Proofs are scripted RED/GREEN captures in this report.
- True single-syscall set flip of public paths inside a shared directory is **not** available on Linux without layout change; journaled stage + recover is the chosen workable alternative.
- Mid-install crash leaves a **transient** mixed tree until `_recover_promote` runs — documented honestly; not hidden.
- Full-suite third failure (`test_cli_score_determinism_guard_pins_import_root_against_cwd_decoy`) was not fixed (out of ownership; looks pre-existing decoy-root/`recognition` path issue).
- End-to-end live `describe_baseline` against a real corpus was not run (no uploads / remote).
- S4-05 MD rendering left to the report.py lane.
