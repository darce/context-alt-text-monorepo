# Lane wE6 report — `check_lane_report_shas.py` guard evasion paths

**Branch:** `fix/we6`
**Base:** `88ed0e524bea8ee625afd405ca7f551d8ae1b5ba`
**Scope:** `scripts/check_lane_report_shas.py`, `scripts/test_check_lane_report_shas.py` only.

## 1. Per finding

### RF-07 — Homoglyph violations bypass `sha-guard:ignore` (medium)

**Reproduction probe (unfixed, wrong FAIL — remediation does not work):**

```
=== rf07.md rc=1 ===
STDOUT:
STDERR: Lane reports cite commits that do not exist in this repository:
  - .s2a/_we6_probe/rf07.md:1: homoglyph / non-ASCII hex-lookalike `с9f7с6е` adjacent to commit vocabulary — refuse to treat lookalike SHAs as invisible; use ASCII hex or mark deliberately foreign tokens with `sha-guard:ignore`
```

**RED (test against unfixed):**

```
FAILED test_homoglyph_respects_sha_guard_ignore - AssertionError: homoglyph + sha-guard:ignore must pass; ... returncode=1
  stderr names lookalike and prints `use ... sha-guard:ignore` while ignore is already present
```

**Fix:** Shared `_hex_like_token_spans` (ASCII hex + confusable-folded spans). `_ignored_token_spans` and the homoglyph loop both consume it; ignored spans skip both paths.

**GREEN:**

```
=== rf07.md rc=0 ===
STDOUT: lane report SHA citations: 1 file(s), 0 citations found (none to resolve)
```

Control without ignore still fails (`homoglyph / non-ASCII hex-lookalike`).

---

### RF-08 — `ignore-next-block` + unclosed fence silences remainder, exit 0 (medium)

**Reproduction probe (unfixed, wrong PASS):**

```
=== rf08.md rc=0 ===
STDOUT: lane report SHA citations: 1 file(s), 0 citations found (none to resolve)
STDERR:
```

**RED:**

```
FAILED test_unclosed_fence_after_ignore_next_block_fails_closed
  AssertionError: unclosed ignored fence must fail closed;
  stdout='lane report SHA citations: 1 file(s), 0 citations found (none to resolve)\n' stderr=''
  assert 0 != 0
```

**Fix:** At EOF, if `in_fence` still true → hard violation (mirrors unclosed HTML comment / S5-02).

**GREEN:**

```
=== rf08.md rc=1 ===
STDERR: ... unclosed fenced block — refusing to claim SHA citations resolve for a partially scanned file
```

---

### RF-09 — Default walk enters `.venv` / `node_modules` (low)

**Reproduction probe (unfixed):**

```
found: ['.s2a/real.md', '.venv/lib/.s2a/x.md', 'node_modules/pkg/.s2a/y.md']
```

**RED:**

```
FAILED test_default_walk_prunes_vendored_trees
  AssertionError: default walk entered vendored trees: [..., '.venv/lib/.s2a/venv_report.md', 'node_modules/pkg/.s2a/nm_report.md']
```

**Fix:** Replace `rglob("*.md")` with `os.walk` that prunes `_PRUNE_DIR_NAMES` (`.venv`, `node_modules`, `.git`, caches, …).

**GREEN:**

```
found: ['.s2a/real.md']
```

---

### RF-10 — Default-walk zero targets exit 0 (low/medium)

**Reproduction probe (unfixed):** empty tree → falls through to success with `0 file(s), 0 citations found (none to resolve)`, rc=0.

**RED:**

```
FAILED test_default_walk_zero_targets_fails_closed
  AssertionError: empty default walk must exit non-zero; rc=0
  Captured stdout: lane report SHA citations: 0 file(s), 0 citations found (none to resolve)
```

**Fix:** When default walk (no paths, not `--scan-staged`) yields zero targets → stderr honesty message + exit 1. Empty staged index remains exit 0 with "nothing to check" (legitimate empty sample).

**GREEN:**

```
rc=1
stderr: 0 lane reports found by default walk; nothing to check — refusing to claim success over an empty sample
```

---

### RF-11 — Markdown-emphasis interior evasion (low)

**Reproduction probe (unfixed, wrong PASS):**

<!-- sha-guard:ignore-next-block -->
```
=== rf11.md rc=0 ===
STDOUT: lane report SHA citations: 1 file(s), 0 citations found (none to resolve)
body: Landed at commit dead*beef*1234567 in the sandbox.
```

**RED:**

```
FAILED test_markdown_emphasis_interior_hex_is_visible_and_flagged
  AssertionError: emphasis-interior hex must fail closed;
  stdout='lane report SHA citations: 1 file(s), 0 citations found (none to resolve)\n'
  assert 0 != 0
```

**Fix:** `_collapse_md_emphasis_in_hex_runs` inside shared `_normalize_scan_line` (with NFKC + Cf strip). Collapses interior `*` / `~` in hex runs only; leaves `manifest_sha256` alone (underscore not collapsed). One normaliser for every detection path.

**GREEN:**

<!-- sha-guard:ignore-next-block -->
```
=== rf11.md rc=1 ===
STDERR: ... cited commit `deadbeef1234567` does not resolve ...
```

---

### RF-12 — Test writes into real repo tree (medium)

**Reproduction:** `test_default_walk_sees_s2a_at_arbitrary_depth_above_star` did `mkdir` under `REPO_ROOT/apps/.../scene/.s2a/_cx5_depth_parity` and rglob'd the real checkout.

**RED:** N/A as a runtime guard failure — this is a test-design defect. Fix is the test rewrite itself.

**Fix:** Build fixture under `tmp_path`; call `_default_report_paths(tmp_path)`. Same cleanup applied to `test_default_walk_and_staged_predicate_agree_on_nested_paths`.

**GREEN:** both tests pass without touching REPO_ROOT.

---

## 2. Disagreements

None. All six findings reproduced as claimed (RF-12 by reading the test, others by probe).

## 3. New findings (not owned)

None observed outside owned files.

## 4. Full suite

```bash
cd apps/prototype-description-service
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
```

Guard unit suite (owned):

```bash
python3 -m pytest scripts/test_check_lane_report_shas.py -q -p no:randomly
# 42 passed
```

Scene suite result line:

```
5 failed, 1338 passed, 4 skipped, 33 warnings in 324.84s (0:05:24)
```

- **Expected-red (5):** the five anchor-freeze byte-identity failures named in the wave preamble (owned by regeneration stage; not this lane):
  - `test_generator_regenerates_byte_identical_committed_anchor`
  - `test_expect_report_matches_committed_freeze_green`
  - `test_face_generator_regenerates_byte_identical_committed_anchor`
  - `test_face_expect_report_matches_committed_freeze_green`
  - `test_cli_score_face_expect_report_end_to_end_green`
- **Unexpected-red:** none.

## 5. `git diff --stat` against base

```
 scripts/check_lane_report_shas.py      | 184 +++++++++++++++++++++++++++-----
 scripts/test_check_lane_report_shas.py | 186 +++++++++++++++++++++++++++------
 .s2a/vlm6-wE6-report.md                | (this report)
```

## 6. Could not verify

- Whether CI invokes the guard via default walk vs `--scan-staged` only (RF-10 incidence depends on that; mechanism fixed either way).
- (none remaining)

## 7. Cross-lane requests

| To | Request |
| --- | --- |
| — | None |

## Commits (TEST-15 order)

1. tests (RED against unfixed)
2. production (GREEN)
3. this report
