# VLM-6 lane `gx5` — SHA guard fail-closed (S5-01…S5-07)

**Lane:** `gx5`  
**Branch:** `fix/gx5` (forked from `feature/vlm-6` @ `8ae228aa0ec8af2b3235f16e47855dbf4b5b3e6b`)  
**Implementation land:** `a35ecf2cfeb88c53577a1c6e6e7c9ab2f4007113`  
**Scope:** `scripts/check_lane_report_shas.py`, its unit tests, f1a/f2b comment tokens only.  
**Heuristics:** TEST-15, AUDIT-07, EVAL-23, rg-006, rg-015, sr-001.

> Deliberate example tokens below that are not git objects in this repo carry
> nearest-token `sha-guard:ignore` (S5-01 / S5-07 — visible, not comment-hidden).

## What changed

- `scripts/check_lane_report_shas.py` — fail closed on comment-hidden unresolvable hex, unclosed HTML comments, bare-commit+ellipsis digests; nearest-token `sha-guard:ignore`; empty `--scan-staged` + zero-citation success wording (S5-01…05, S5-07).
- `scripts/test_check_lane_report_shas.py` — RED-first discrimination tests for the three escapes + empty staged + nearest ignore + real f1a/f2b shape; revisit content-digest exclusions.
- `.s2a/vlm6-fix-f1a-report.md` — delete hex token from HTML comment (prose-only; no fabricated object name).
- `.s2a/vlm6-fix-f2b-report.md` — same comment-token strip.
- `.s2a/vlm6-gx5-report.md` — this report.

## Per-finding resolution

### S5-01 [high] — unresolvable SHA relocated into skipped HTML comment

**Done.** (1) f1a/f2b comments no longer contain hex — prose: `history-stripped sandbox clone; the base object does not exist here`. (2) Guard **no longer skips HTML comments** for token scanning. Unresolvable hex in `<!-- ... -->` fails like visible prose. Deliberate foreign SHAs must use **visible** prose with nearest-token `sha-guard:ignore`. No new blanket skip category (sr-001).

Evidence: restored f1a/f2b shape fixture exits 1 naming the former sandbox tokens `c9f7c6e` sha-guard:ignore and `7ad6d52` sha-guard:ignore (see TEST-15). Owned reports pass: `2 file(s), 3 citation(s) resolved`.

### S5-02 [high] — unclosed comment fails open for rest of file

**Done.** Lines after an unclosed `<!--` are still scanned (no `continue` skip). File ending while `in_block_comment` is a hard violation: `unclosed HTML comment — refusing to claim SHA citations resolve for a partially scanned file`.

Evidence: fixture with unclosed comment then later fake tokens `beef001` sha-guard:ignore / `cafebab` sha-guard:ignore exits non-zero; never prints `all resolve`.

### S5-03 [high] — any hex + ellipsis treated as content digest

**Done.** `_is_content_digest` applies ellipsis exclusion only when `_BEFORE_DIGEST` matches **or** the after-span is sha256sum-listing form (`hex…  path` via `_SHA256SUM_LISTING_AFTER`). Bare commit + ellipsis (example token `deadbee` sha-guard:ignore) must resolve.

Evidence: `test_bare_commit_ellipsis_is_not_a_content_digest` fails pre-fix / passes post-fix. Genuine listings still pass via `test_content_digest_exclusions_do_not_flag`.

### S5-04 [medium] — empty `--scan-staged` claims resolve

**Done.** Zero staged targets → `0 staged lane reports; nothing to check` (exit 0). Never `all resolve` over empty sample (AUDIT-07).

### S5-05 [medium] — success string over-claims when zero tokens

**Done.** Track `tokens_checked`. Success messages:
- `N file(s), K citation(s) resolved` when K > 0
- `N file(s), 0 citations found (none to resolve)` when K == 0

Removed the `all resolve` success string entirely.

### S5-07 [low] — ignore marker blanks whole line

**Done.** `_ignored_token_spans` associates each `sha-guard:ignore` with the **nearest** hex token only. Sibling tokens on the same line remain checked.

## TEST-15 proofs

Command: `apps/prototype-description-service/.venv/bin/python -m pytest scripts/test_check_lane_report_shas.py -q --tb=line`

### RED (before guard fix; tests already present, guard still old)

8 new/updated assertions failed; 8 older cases still passed. Failure mode for every new case was the same pre-fix loophole: exit 0 with stdout containing `all resolve`.

Verbatim excerpts:

```
AssertionError: bare commit+ellipsis must fail; got stdout='lane report SHA citations: 1 file(s) checked, all resolve\n' stderr=''
AssertionError: comment-hidden unresolvable SHA must fail; stdout='lane report SHA citations: 1 file(s) checked, all resolve\n' stderr=''
AssertionError: restored f1a/f2b comment-hide shape must fail; stdout='lane report SHA citations: 2 file(s) checked, all resolve\n' stderr=''
AssertionError: unclosed comment must exit non-zero; stdout='lane report SHA citations: 1 file(s) checked, all resolve\n' stderr=''
AssertionError: empty sample claimed resolve: 'lane report SHA citations: 0 file(s) checked, all resolve\n'
AssertionError: second token must still fail; stdout='lane report SHA citations: 1 file(s) checked, all resolve\n' stderr=''
AssertionError: assert 'all resolve' not in 'lane report...ll resolve\n'
8 failed, 8 passed in 1.21s
```

Quoted RED assertions required by brief:

1. Landed-at-commit + ellipsis must exit 1 → RED stdout was `1 file(s) checked, all resolve` exit 0.
2. Unclosed HTML comment + later citation must exit non-zero → RED exit 0 / `all resolve`.
3. `--scan-staged` empty must not print `all resolve` → RED printed exactly that.
4. Real f1a/f2b shape with sandbox hex restored must exit 1 → RED `2 file(s) checked, all resolve`.
5. Content-digest exclusions revisited: bare-commit+ellipsis fails (new test); genuine sha256sum / msha= / sha256: still pass.

### GREEN (after guard fix)

```
................                                                         [100%]
16 passed in 1.73s
```

Owned reports alone:

```
$ python3 scripts/check_lane_report_shas.py .s2a/vlm6-fix-f1a-report.md .s2a/vlm6-fix-f2b-report.md
lane report SHA citations: 2 file(s), 3 citation(s) resolved
EXIT:0
```

Empty staged:

```
$ python3 scripts/check_lane_report_shas.py --scan-staged
0 staged lane reports; nothing to check
EXIT:0
```

### Full `.s2a/` tree (tightened guard — exit 1 expected; other reports not owned)

```
$ python3 scripts/check_lane_report_shas.py
Lane reports cite commits that do not exist in this repository:
  - .s2a/vlm6-fix-f2d-report.md:7: cited commit does not resolve (sandbox SHA in HTML comment)
  - .s2a/vlm6-fix-f2e-report.md:7: cited commit does not resolve (sandbox SHA in HTML comment)
  - .s2a/vlm6-fix-f3-report.md:153: two cited commits do not resolve (sandbox SHAs in HTML comment)
  - .s2a/vlm6-fix-f4-report.md:133: cited commit does not resolve (sandbox SHA in HTML comment)
  - .s2a/vlm6-fx4-report.md:178: truncated digest without digest-label / ignore
  - .s2a/vlm6-fx7-report.md:119: truncated manifest digest without accepted label / ignore
EXIT:1
```

(Exact token strings named in the live stderr; paraphrased here so this report itself does not re-introduce unresolvable bare tokens. See Cross-lane for file:line + fix recipes. Intentional fail-closed — sr-001.)

## Suite result

```
$ cd apps/prototype-description-service && .venv/bin/python -m pytest scene/tests/ -q -p no:randomly
...
FAILED scene/tests/test_eval_harness_cli.py::test_cli_score_determinism_guard_pins_import_root_against_cwd_decoy
1 failed, 1236 passed, 4 skipped, 28 warnings in 184.40s (0:03:04)
```

**Not caused by this lane.** gx5 touches only the SHA guard scripts + two report comments + this report — nothing under `apps/`. The failure is a decoy-probe `ModuleNotFoundError: No module named 'recognition'` when `exec`'ing real `report.py` under a symlink tree (cwd probe path). Baseline claimed 1237 passed; this red is outside ownership — see Cross-lane / What you could not verify.

Guard unit surface (owned): **16 passed**.

## Cross-lane requests

Outside gx5 file ownership. Apply these report fixes so whole-tree guard exits 0. **Do not weaken the guard.**

### 1. Comment-hidden sandbox SHAs (same class as S5-01) — any docs/report owner

Replace hex-bearing correction comments with prose-only (mirror f1a/f2b), **or** move the quote to visible prose with nearest-token `sha-guard:ignore`.

Exact patches (prose-only, preferred):

**`.s2a/vlm6-fix-f2d-report.md` lines 7–8** — replace the correction comment body so it contains no hex:
```markdown
<!-- Corrected (VLM6-S2A-F2D-01): the lane wrote its own sandbox-clone SHA,
     which does not exist here. This is the commit that landed this report locally. -->
```

**`.s2a/vlm6-fix-f2e-report.md` lines 7–8** — same:
```markdown
<!-- Corrected (VLM6-S2A-F2D-01 class): the lane wrote a sandbox-clone SHA
     that does not exist here. This is the commit that landed this report locally. -->
```

**`.s2a/vlm6-fix-f3-report.md` lines 153–155**:
```markdown
<!-- Corrected (VLM6-S2A-F3-02): the lane cited sandbox-clone SHAs that resolve
     nowhere here, and paired them with a verify command guaranteed to fail.
     Replaced with the commit that actually landed this report. -->
```

**`.s2a/vlm6-fix-f4-report.md` lines 133–136**:
```markdown
<!-- Corrected (VLM6-S2A-F3-02 class, 4th instance): the lane cited a sandbox-clone
     SHA and its own cat-file verification — both true in its sandbox clone, neither
     resolvable here. See scripts/check_lane_report_shas.py for the guard. -->
```

### 2. Truncated digests without digest label — fx4 / fx7 report owners

These are **visible** truncated content digests that no longer get a free ellipsis pass (S5-03). Prefer removing the hex entirely:

**`.s2a/vlm6-fx4-report.md:178`** suggested:
```markdown
- **Behaviour:** Removed the hardcoded truncated manifest digest literal; operators must read digest from the artifact. Inventory adds `demographic_cohort` 0/37 and fabricated-fact = undefined.
```

**`.s2a/vlm6-fx7-report.md:119`** suggested:
```markdown
| manifest digest | **unchanged** (truncated prefix omitted; corpus body byte-identical) |
```

If a truncated prefix must remain visible, put it in prose with nearest-token `sha-guard:ignore` — never in an HTML comment alone.

### 3. Suite red — apps/ owner (not gx5)

`test_cli_score_determinism_guard_pins_import_root_against_cwd_decoy` fails when the decoy `report.py` `exec`s real report under a symlink tree and transitive imports need `recognition` on `sys.path`. gx5 did not edit `apps/` or that test. Owning lane should re-establish the probe env (PYTHONPATH / package root) so the hazard documentation probe returns 0.

## What you could not verify

- Did not re-run the full scene suite after the final wording-only polish of the guard (last full run: 1236 passed / 1 failed as quoted; guard unit tests re-run green after polish).
- Did not fix non-owned `.s2a/` reports; whole-tree guard remains exit 1 until Cross-lane items land.
- Did not root-cause the `recognition` ModuleNotFoundError in the decoy probe beyond confirming it is outside this lane's diff.
- MCP handoff (`make context` / workbay tools) unavailable in this worktree (`make: *** No rule to make target 'context'`). Report file is the transport.
- Mutation of `_resolves` / always-return-0 was not re-run this lane; S5-06 discrimination was taken as given from the brief.

## Landing note

Commits on `fix/gx5` only. No merge/rebase into `feature/vlm-6`. Coordinator integrates.
