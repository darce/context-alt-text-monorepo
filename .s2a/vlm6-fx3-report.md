# VLM-6 lane `fx3` — lane-report SHA guard: close evasion channels

**Branch:** `fix/fx3`  
**Fork point:** `b28e126e89bc41202e0168276f8493511212c80d` (resolves in this worktree)  
**Owned files:** `scripts/check_lane_report_shas.py`, `scripts/test_check_lane_report_shas.py`,
`.s2a/vlm6-hx2-report.md` (HARM-08 markers only), this report.

Heuristics: `TEST-15`, `AUDIT-07`, `EVAL-23`, `rg-006`, `rg-015`, `sr-001`.

Foreign probe tokens in the RED/GREEN captures below are deliberately non-resolving;
each capture fence is preceded by `sha-guard:ignore-next-block` so the guard does not
re-flag documentation of the bug it closes (HARM-08 pattern).

---

## RV4-02 (high) — digest labels vetoed short hex without digest shape

### What changed
`_is_content_digest` no longer returns True on a `_BEFORE_DIGEST` label alone.
Exclusion now requires digest **shape**:

1. explicit `sha256:` prefix (any length), or
2. digest label **and** (`len(token) >= 16` **or** ellipsis after the token), or
3. sha256sum-style `hex…  path` remainder.

Bare 7–12 hex after `golden sha is` / `fetch sha` / `manifest sha` / `freeze … sha`
is treated as a commit citation and must resolve.

### Why
Lane prose already uses golden/fetch/manifest/freeze vocabulary next to real commit
SHAs. Label-only veto stamped false certification (`0 citations found`) over foreign
sandbox SHAs — worse than no guard (AUDIT-07 fail-closed).

### RED (unfixed guard — verbatim)

```
$ python3 -m pytest scripts/test_check_lane_report_shas.py -q -p no:randomly \
    -k 'digest_label_with_short'
FAILED … golden_sha_is — short hex after digest label must fail closed;
  stdout='lane report SHA citations: 1 file(s), 0 citations found (none to resolve)\n'
FAILED … fetch_sha — same (exit 0, 0 citations)
FAILED … manifest_sha_was — same
FAILED … freeze_golden_sha_is — same
FAILED … score_time_golden_sha_is — same
FAILED … model_dump_sha_was — same
```

Live probe (unfixed, via `_is_content_digest`):

<!-- sha-guard:ignore-next-block -->
```
digest=True:  'Sandbox golden sha is c9f7c6e (history-stripped clone).'
digest=True:  'fetch sha c9f7c6e was the sandbox base'
digest=True:  'manifest sha was c9f7c6e before rewrite'
digest=True:  'The freeze golden sha is 7ad6d52 at score-time.'
digest=False: 'Sandbox base was c9f7c6e (history-stripped clone).'  # control
```

### GREEN (fixed)

<!-- sha-guard:ignore-next-block -->
```
exit=1 :: cited commit `c9f7c6e` does not resolve   # golden sha is
exit=1 :: cited commit `c9f7c6e` does not resolve   # fetch sha
exit=1 :: cited commit `c9f7c6e` does not resolve   # manifest sha was
exit=1 :: cited commit `7ad6d52` does not resolve   # freeze golden sha is
exit=1 :: cited commit `c9f7c6e` does not resolve   # control Sandbox base was
```

Happy-path digests still pass: `sha256:` prefix, labelled ≥16 hex, labelled+ellipsis,
sha256sum listings (`test_content_digest_exclusions_do_not_flag`).

---

## RV4-03 (medium) — ASCII-only hex extractor / unicode evasion

### What changed
- `_normalize_scan_line`: NFKC-normalise each line, strip Unicode category `Cf`
  (soft hyphen U+00AD, ZWSP U+200B, …) before `_HEX` scanning.
- `_homoglyph_sha_runs`: fold Cyrillic/Greek confusables; if a 7–40 run looks like
  hex only after folding and sits next to commit vocabulary, emit a hard violation
  (do **not** resolve the folded form — that could false-pass).

### Why
Soft-hyphen / ZWSP / fullwidth / Cyrillic-mixed tokens render as plausible short SHAs
in Markdown viewers but were invisible to `_HEX`, yielding exit 0 with
`0 citations found`.

### RED (unfixed)

```
soft-hyphen: exit=0  stdout='… 0 citations found (none to resolve)'
ZWSP:        exit=0  stdout='… 0 citations found (none to resolve)'
fullwidth:   exit=0  stdout='… 0 citations found (none to resolve)'
cyrillic:    exit=0  stdout='… 0 citations found (none to resolve)'
```

### GREEN (fixed)

<!-- sha-guard:ignore-next-block -->
```
soft: exit=1  cited commit `c9f7c6e` does not resolve
zwsp: exit=1  cited commit `c9f7c6e` does not resolve
full: exit=1  cited commit `c9f7c6e` does not resolve
cyrl: exit=1  homoglyph / non-ASCII hex-lookalike `с9f7с6е` adjacent to commit vocabulary
```

---

## RV4-04 (medium) — default walk one level; staged walk recursive

### What changed
- `_is_lane_report_relpath(name)` — single predicate: `"/.s2a/" in f"/{name}"` and
  `.md` suffix (any depth).
- `_default_report_paths(repo)` — recursive globs `.s2a/**/*.md` + `*/.s2a/**/*.md`.
- `_staged_reports` uses the same predicate.

### Why
Default walk missed nested paths under `.s2a/` while `--scan-staged` and explicit
path args would catch them — scope drift (rg-006).

### RED (unfixed)

<!-- sha-guard:ignore-next-block -->
```
$ echo 'Sandbox base was deadbee' > .s2a/_rv4_nested/lane-report.md
$ python3 scripts/check_lane_report_shas.py
lane report SHA citations: 50 file(s), 43 citation(s) resolved   # exit 0; deadbee absent
$ python3 scripts/check_lane_report_shas.py .s2a/_rv4_nested/lane-report.md
exit 1; names deadbee
```

Also: `AttributeError: module has no attribute '_is_lane_report_relpath'` on the
parity unit test (API did not exist).

### GREEN (fixed)

<!-- sha-guard:ignore-next-block -->
```
$ python3 scripts/check_lane_report_shas.py   # with nested fixture present
exit 1
  - .s2a/_rv4_nested/lane-report.md:1: cited commit `deadbee` does not resolve
test_default_walk_and_staged_predicate_agree_on_nested_paths PASSED
```

---

## RV4-06 (low) — tests pinned only the happy path

### What changed
Added negative tests that fail closed for:

- each exclusion label with bare 7–12 hex (no ellipsis, no `sha256:`) — parametrize
- soft hyphen, ZWSP, fullwidth, Cyrillic homoglyph
- nested `.s2a/` default walk
- walker / staged predicate parity via shared helpers
- block-scoped ignore (HARM-08)

Updated `test_content_digest_exclusions_do_not_flag` so the labelled happy path uses
≥16 hex / ellipsis (shape-correct digests), not bare 8-hex that the new rule correctly
treats as a commit citation.

Fixture dir renamed to `_fx3_guard_fixtures` with recursive cleanup.

### RED → GREEN
RED suite against unfixed guard: **14 failed, 1 passed** (the fence-without-ignore
control, which already failed closed).  
GREEN suite after fix: **32 passed**.

---

## HARM-08 (low) — `sha-guard:ignore` inside verbatim fenced output

### What changed
1. **Guard feature:** `sha-guard:ignore-next-block` (also as
   `<!-- sha-guard:ignore-next-block -->`) immediately before a fenced block skips
   all hex tokens inside the next fence only. Nearest-token `sha-guard:ignore` is
   unchanged. The ignore-next-block string is excluded from nearest-token matching
   so the `ignore` prefix cannot steal a token.
2. **hx2 report:** moved markers **outside** the two GREEN fenced captures in
   `.s2a/vlm6-hx2-report.md` (S4-04 and S4-06); restored interior lines to verbatim
   program output (no marker text inside the fence).

### Why
A fenced block labelled as captured output must be exactly what the program printed.
Editing `sha-guard:ignore` into it destroys evidentiary status.

### RED (unfixed — no block directive)

<!-- sha-guard:ignore-next-block -->
```
fence_with_ignore.md: exit=1
  cited commit `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa` does not resolve
  # HTML comment on previous line was not a skip channel (S5-01) and no block ignore existed
```

### GREEN (fixed)

<!-- sha-guard:ignore-next-block -->
```
test_ignore_next_block_alone_allows_fence_with_foreign_sha PASSED
test_ignore_next_block_skips_tokens_inside_following_fence PASSED
  # beef001 after the fence still fails; synthetic a-run inside fence ignored
```

---

## Findings disagreed with

None. All five reproduced with live probes before the fix; each has a RED capture above.

---

## Whole-tree guard run (post-fix)

```
$ python3 scripts/check_lane_report_shas.py
lane report SHA citations: 50 file(s), N citation(s) resolved
EXIT:0
```

N grows as this report cites additional resolvable SHAs from `fix/fx3` commits;
exit code is the acceptance criterion. Last measured: 46 citations, exit 0.

## Test suite (post-fix)

```
$ python3 -m pytest scripts/test_check_lane_report_shas.py -q -p no:randomly
................................                                         [100%]
32 passed in 2.02s
```

## `git diff --stat` against fork point

```
 .s2a/vlm6-fx3-report.md                | 375 ++++++++++++++++++++-------------
 .s2a/vlm6-hx2-report.md                |   6 +-
 scripts/check_lane_report_shas.py      | 233 +++++++++++++++++---
 scripts/test_check_lane_report_shas.py | 273 +++++++++++++++++++++++-
 4 files changed, 700 insertions(+), 187 deletions(-)
```

(Against `b28e126e89bc41202e0168276f8493511212c80d`.)

## What could not be verified

- Did not re-run the full monorepo CI / `make check-all` (out of scope; owned files only).
- Homoglyph table covers Cyrillic аеорсх + Greek ο/Ο/α; other confusable scripts
  (fullwidth already handled by NFKC) are not exhaustively enumerated — new scripts
  would need table extensions. Stated limitation, not a silent skip.
- Did not exercise `--scan-staged` against a real index entry for a nested path in
  a dirty worktree (predicate unit-tested; staged path uses the same helper).

## Cross-lane requests

None. Other lanes (fx1/fx2/fx4 service code, fx5 bakeoff docs) untouched.
Coordinator: integrate `fix/fx3` onto `feature/vlm-6` after review.

---

## Commits on `fix/fx3`

- `a21fa99610d0386e90e9b55bb813f2430b238bc5` — fix(fx3): close lane-report SHA guard evasion channels
- `f3e54b890322f15099a8e265070f4b0d32b5469f` — docs(fx3): record RED/GREEN captures and resolving commit SHAs
- `d984abd02afd4f7c71c3fa2869380fcbbb1f6fb3` — docs(fx3): finalise lane report counts and commit list
