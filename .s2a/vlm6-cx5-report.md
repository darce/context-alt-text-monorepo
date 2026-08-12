# VLM-6 Wave C · lane cx5 — SHA-citation guard evasion paths

**Branch:** `fix/cx5`
**Base:** `7812d71c832786328705a8d6ea6e1d7f41dc487b`
**HEAD:** `33427a095adb2dbd47359e2e759b53ac4c05dbc5`
**Owned files:** `scripts/check_lane_report_shas.py`, `scripts/test_check_lane_report_shas.py`
**Heuristics:** TEST-15, TEST-06, DBG-10, DIAG-01, rg-006, sr-001, AUDIT-07

## Commits

| SHA | Finding |
| --- | --- |
| `5c1ca5d4` | G-03 unconditional homoglyph |
| `ec2de447` | G-05 ignore-next-block adjacency |
| `33427a09` | G-04/E-02 shared path predicate + pollution-free test |

---

## Finding 1 — VLM6-R2-G-03 (MEDIUM) — FIXED

### Reviewer probe (reproduced)

Cyrillic-`с`/`е` variant of `c9f7c6e` sha-guard:ignore via in-process `scan_file`:

sha-guard:ignore-next-block
```
'Sandbox base was <sha>.'                                    → 1 violation  (vocab match)
'Work landed under <sha> in the throwaway clone.'            → 0 violations (no vocab)
'The lane worktree HEAD was <sha> at the time of the run.'   → 0 violations (HEAD ∉ vocab)
```

Counter-probe confirmed the reviewer's numbers exactly under base `7812d71c`.

### RED (TEST-15)

Added `test_homoglyph_detection_is_unconditional_not_vocab_gated`. Before production fix:

sha-guard:ignore-next-block
```
AssertionError: homoglyph must fail closed without vocab gate;
body='Work landed under с9f7с6е in the throwaway clone.'
returncode=0  stdout='…0 citations found (none to resolve)'
```

### Fix

Homoglyph runs examined on **every** line. `_COMMIT_VOCAB` only annotates the
violation message (` adjacent to commit vocabulary` when present); never gates.

### GREEN

All three phrases → 1 violation each. Test suite: 36 passed.

---

## Finding 2 — VLM6-R2-G-05 (MEDIUM) — FIXED

### Reviewer probe (reproduced)

Directive on line 3, seven lines of prose, fence on line 11:

sha-guard:ignore-next-block
```
with directive:    scan_file → ([], 0)
without directive: scan_file → 1 violation (aaaaaaaa… does not resolve)
```

Blank-only adjacency already worked under the old "anywhere earlier" semantics.

### RED (TEST-15)

`test_ignore_next_block_requires_immediate_adjacency` failed:

```
AssertionError: non-adjacent ignore-next-block must NOT suppress fence;
returncode=0  (suppressed; 0 citations found)
```

### Fix

- Directive sets pending suppression.
- Blank lines preserve pending state.
- Any intervening **non-blank** content resets pending.
- Fence opener consumes pending for **that fence only**.

### GREEN

Non-adjacent → 1 violation; blank-adjacent → 0. Control tests still pass.

---

## Finding 3 — VLM6-R2-G-04 (MEDIUM) — FIXED

### Reviewer probe (reproduced)

`apps/prototype-description-service/scene/.s2a/_cx5_probe/report.md`:

sha-guard:ignore-next-block
```
deep in defaults? False
predicate says? True
in g1 (.s2a/**)? False
in g2 (*/.s2a/**)? False
```

Docstring claimed shared predicate with `--scan-staged`; `_default_report_paths`
never called `_is_lane_report_relpath`.

### RED (TEST-15)

`test_default_walk_sees_s2a_at_arbitrary_depth_above_star`:

```
AssertionError: default walk missed arbitrary-depth .s2a path
…/scene/.s2a/_cx5_depth_parity/report.md; predicate=True
```

### Fix

`_default_report_paths` walks `repo.rglob("*.md")` and filters through
`_is_lane_report_relpath`. Same predicate as `--scan-staged` (rg-006).

### GREEN

`deep in defaults? True`. Parity test passes.

---

## Finding 4 — VLM6-R2-E-02 (MEDIUM) — FIXED

### Reviewer probe (reproduced)

Ambient default walk (no args):

sha-guard:ignore-next-block
```
returncode 1
deadbee in stderr? True   # substring of ambient deadbeef in vlm6-fx2-report.md
nested path in stderr? (only when fixture present — ambient alone still green for old test)
```

Old test asserted nonzero exit + substring match of a short fixture token in
stderr — both satisfied by ambient long-hex noise in other lane reports even
under a shallow-glob mutant that drops nested paths.

### RED after rewrite + shallow-glob mutant (TEST-15)

Mutant: `_default_report_paths = lambda repo: list(repo.glob(".s2a/*.md"))`

sha-guard:ignore-next-block
```
FAILED test_nested_s2a_path_is_scanned_by_default_walk
  default walk missed nested path …/_rv4_nested/lane-report.md
FAILED test_default_walk_sees_s2a_at_arbitrary_depth_above_star
  default walk missed …/scene/.s2a/_cx5_depth_parity/report.md
```

(Under pre-fix ambient test: mutant stayed green — confirmed discrimination gap.)

### Fix

Rewrite `test_nested_s2a_path_is_scanned_by_default_walk` to:

1. Import `_default_report_paths` and assert **path membership** directly.
2. Use unique fixture token `f00ba12` sha-guard:ignore (not a substring of ambient long-hex noise).
3. When scanning the file, assert path basename / `_rv4_nested` in stderr.

### GREEN

Membership holds under real implementation; mutant goes red.

---

## Disagreements

None. All four probes reproduced verbatim; no counter-evidence.

## New findings

None owned-adjacent left unfixed. Note: whole-fence suppression (every token in
the ignored fence) remains intentional for HARM-08 verbatim captures; G-05 only
closes the unbounded-adjacency bypass. Not expanded.

## Full suite

```
cd apps/prototype-description-service
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
→ 1307 passed, 4 skipped, 32 warnings in 230.85s
```

- **expected-red:** none
- **unexpected-red:** none
- Baseline match: `1307 passed, 0 failed, 4 skipped`

Guard unit suite: **36 passed** (was 31 at base + 5 new/rewritten).

## `git diff --stat` vs `7812d71c`

```
 scripts/check_lane_report_shas.py      |  79 +++++++++------
 scripts/test_check_lane_report_shas.py | 176 +++++++++++++++++++++++++++++----
 2 files changed, 206 insertions(+), 49 deletions(-)
```

(+ this report)

## Could not verify

- Live CI / pre-commit hook wiring of the guard (out of scope; unit + CLI probes only).
- Whether any in-tree report currently relies on non-adjacent `ignore-next-block`
  (would now correctly fail; none found under owned surface).

## Cross-lane requests

None. Did not touch `apps/prototype-description-service/` production code,
`README.md`, or anchors.
