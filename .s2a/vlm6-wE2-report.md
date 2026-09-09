# Lane wE2 report — `provenance_sha.py` refuse-uniform

**Branch:** `fix/we2`  
**Base:**

sha-guard:ignore-next-block
```
88ed0e524bea8ee625afd405ca7f551d8ae1b5ba
```

**Design:** **Refuse-uniform** — any unverifiable HEAD SHA raises `SystemExit`. No silent format-only hatch; no degraded stamp that looks like a verified SHA (`S2-07`, `rg-015`).

**Why refuse over stamp:** A stamp field would need consumer edits in non-owned modules (`report.py`, promote callers). Refuse makes every failure mode identical and keeps the artifact free of ambiguous `head_sha` values. Consumers that need a live SHA either get a git-verified 40-hex or nothing (error / pin-null).

**Owned files touched:**
- `scripts/eval_harness/provenance_sha.py` — core fix
- `scripts/eval_harness/generate_determinism_anchor.py` — help text only (ENOENT-degrade claim removed)
- `scene/tests/test_describe_baseline_pin_provenance.py` — RED→GREEN locks

---

## 1. Per finding

### RD-01 / CDX-02 — Missing-git / ENOENT / bad cwd still stamped fabricated hex

**Reproduction (pre-fix, verbatim):**
<!-- sha-guard:ignore-next-block -->
```text
=== RD-01 empty PATH ===
empty PATH: ACCEPTED aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
dangling symlink git: ACCEPTED aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
=== CDX-02 nonexistent git_cwd ===
bad git_cwd: ACCEPTED aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
```

**RED (tests vs unfixed):**
```text
FAILED ...::test_vlm6_r2_d02_missing_git_binary_refuses - Failed: DID NOT RAISE SystemExit
FAILED ...::test_vlm6_r2_d02_enoent_oserror_refuses - Failed: DID NOT RAISE SystemExit
FAILED ...::test_we2_rd01_empty_path_refuses_fabricated - Failed: DID NOT RAISE SystemExit
FAILED ...::test_we2_rd01_dangling_symlink_git_refuses - Failed: DID NOT RAISE SystemExit
FAILED ...::test_we2_cdx02_nonexistent_git_cwd_refuses - Failed: DID NOT RAISE SystemExit
```

**Fix:** `_resolve_git_binary()` + no format-only return on ENOENT/`FileNotFoundError`. Missing binary, dangling symlink, and unhappy probes all call `_refuse_git_probe`.

**GREEN (post-fix probe):**
<!-- sha-guard:ignore-next-block -->
```text
empty PATH no system git: REFUSED HEAD_SHA='aaaaaaaa…' git provenance probe failed (git binary missing/unusable: FileNotFoundError…
dangling symlink git: REFUSED … git binary missing/unusable: FileNotFoundError…
bad git_cwd: REFUSED … is-inside-work-tree rc=128 … fatal: cannot change to …
```

---

### RD-02 — Second-probe ENOENT degrades after first probe alive

**Reproduction (pre-fix):**
<!-- sha-guard:ignore-next-block -->
```text
=== E2E5 / RD-02 second ENOENT ===
second ENOENT: ACCEPTED aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
```

**RED:**
```text
FAILED ...::test_we2_rd02_second_probe_enoent_refuses - Failed: DID NOT RAISE SystemExit
```

**Fix:** Second-probe `OSError`/`SubprocessError` always refuses (`missing-binary-after-alive` detail). No hatch after `is-inside-work-tree` succeeded (`DIAG-03`).

**GREEN:**
```text
second ENOENT: REFUSED … rev-parse --verify missing-binary-after-alive: FileNotFoundError…
```

---

### RD-03 / CDX-03 — `GIT_DIR` / alternates verify foreign commits

**Reproduction (pre-fix):**
<!-- sha-guard:ignore-next-block -->
```text
=== B1 / RD-03 GIT_DIR foreign ===
GIT_DIR attacker foreign SHA: ACCEPTED ed1e2920…
```

**RED:**
```text
FAILED ...::test_we2_rd03_git_dir_foreign_repo_refuses - Failed: DID NOT RAISE SystemExit
FAILED ...::test_we2_rd03_git_alternate_objects_refuses - Failed: DID NOT RAISE SystemExit
```

**Fix:** `_sanitized_subprocess_env()` drops `GIT_DIR`, `GIT_WORK_TREE`, `GIT_COMMON_DIR`, `GIT_OBJECT_DIRECTORY`, `GIT_ALTERNATE_OBJECT_DIRECTORIES`, `GIT_INDEX_FILE`, `GIT_NAMESPACE`. Probes use `git -C <abs>` when `git_cwd` is set.

**GREEN:**
```text
GIT_DIR attacker foreign SHA: REFUSED … is not a resolvable commit in this repository
clean monorepo real HEAD: ACCEPTED 88ed0e524bea8ee625afd405ca7f551d8ae1b5ba
```

---

### RD-04 / CDX-03 — Impostor `git` on `PATH`

**Reproduction (pre-fix):**
<!-- sha-guard:ignore-next-block -->
```text
=== RD-04 impostor ===
impostor PATH: ACCEPTED aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa^{commit}}
```
(stdout also proved RD-05: non-hex accepted)

**RED:**
```text
FAILED ...::test_we2_rd04_impostor_git_on_path_refuses - Failed: DID NOT RAISE SystemExit
```

**Fix:** Prefer `/usr/bin/git` then `/bin/git` via `_SYSTEM_GIT_CANDIDATES` before `shutil.which`. Absolute path used for both probes.

**GREEN:**
```text
impostor PATH fabricated: REFUSED … is not a resolvable commit in this repository
```

---

### RD-05 — Verify trusts returncode only; stdout not re-hexed

**Reproduction (pre-fix):**
<!-- sha-guard:ignore-next-block -->
```text
=== RD-05 garbage stdout ===
garbage stdout: ACCEPTED totally-not-a-sha
empty stdout fallback: ACCEPTED aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
```

**RED:**
```text
FAILED ...::test_we2_rd05_verify_garbage_stdout_refuses - Failed: DID NOT RAISE SystemExit
FAILED ...::test_we2_rd05_verify_empty_stdout_refuses - Failed: DID NOT RAISE SystemExit
```

**Fix:** Require `_HEX40.fullmatch(stdout.strip().lower())`; never fall back to input `sha`.

**GREEN:**
```text
garbage stdout: REFUSED … returned non-SHA stdout 'totally-not-a-sha'
empty stdout: REFUSED … returned non-SHA stdout ''
```

---

### RD-06 — `normalize_head_sha(verify_git=False)` library opt-out

**Reproduction (pre-fix):**
<!-- sha-guard:ignore-next-block -->
```text
=== RD-06 verify_git=False ===
verify_git=False: ACCEPTED aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
```

**RED:**
```text
FAILED ...::test_we2_rd06_verify_git_false_refuses - Failed: DID NOT RAISE SystemExit
```

**Fix:** `verify_git=False` raises `SystemExit` (parameter kept so `promote_atomic` / `describe_baseline` can still pass `verify_git=True` without a cross-lane signature edit).

**GREEN:**
```text
verify_git=False: REFUSED … verify_git=False is refused — git verification is mandatory …
```

---

### RE-03 — Static call-site lock watched the wrong symbol

**Pre-fix:** `test_vlm6_r2_d03_no_call_site_passes_verify_git` only grepped `validate_live_head_sha(...verify_git=)`.

**Proof the old scan is vacuous (scratch rewrite):** `test_we2_re03_scratch_normalize_false_scan_detects` writes a producer calling `normalize_head_sha(..., verify_git=False)` — new regex matches; old wrapper-only regex does **not**.

**Fix:** Expand scan to `normalize_head_sha(...verify_git=False)` and any harness `verify_git=False`. Behavioural refuse on RD-06 is the runtime twin.

---

## 2. Disagreements

**None.** All owned findings reproduced on base

sha-guard:ignore-next-block
```
88ed0e524bea8ee625afd405ca7f551d8ae1b5ba
```

Mechanism matches reviewer probes (RD + CDX independent convergence on missing-git and GIT_DIR / impostor).

---

## 3. New findings (not owned)

| Id | Note |
| --- | --- |
| CDX-04 | Shared-stem temp collision — owned by **wE3** / `promote_atomic.py`. Not fixed here. |
| — | `promote_atomic.validate_live_head_sha` docstring still says “degrade when git is missing” — **wE3** file; see Cross-lane. |
| — | `describe_baseline` still passes `verify_git=True` explicitly (harmless). Removing the kwarg entirely needs a coordinated signature cleanup outside this lane. |

---

## 4. Full suite

```bash
cd apps/prototype-description-service
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
```

**Result:** `5 failed, 1349 passed, 4 skipped` (baseline was `5 failed, 1338 passed, 4 skipped`).

**Expected-red** (anchor-freeze byte-identity; not this lane — do **not** regenerate bakeoff artifacts):
- `test_generator_regenerates_byte_identical_committed_anchor`
- `test_expect_report_matches_committed_freeze_green`
- `test_face_generator_regenerates_byte_identical_committed_anchor`
- `test_face_expect_report_matches_committed_freeze_green`
- `test_cli_score_face_expect_report_end_to_end_green`

**Unexpected-red:** none.

Pin-provenance file alone: `47 passed`.

---

## 5. `git diff --stat` vs base

```text
 .../tests/test_describe_baseline_pin_provenance.py | 382 +++++++++++++++++++--
 .../eval_harness/generate_determinism_anchor.py    |  13 +-
 .../scripts/eval_harness/provenance_sha.py         | 171 +++++++--
 3 files changed, 505 insertions(+), 61 deletions(-)
```
(+ report file in its own commit)

---

## 6. Could not verify

- Production CI image incidence of empty `PATH` / impostor `git` / poisoned `GIT_DIR` (AUDIT-07 — mechanism only).
- Whether every out-of-tree consumer imports `normalize_head_sha` with `verify_git=False` (runtime now refuses if they do).
- Full five-name anchor failure list from the second suite run was truncated by `tail`; count stayed at 5 and matches the brief’s expected-red set.

---

## 7. Cross-lane requests

| To | Request |
| --- | --- |
| wE3 (`promote_atomic.py`) | Update `validate_live_head_sha` docstring: remove “degrade when git is missing / not a repo”; state refuse-uniform. Optional: drop `verify_git=True` kwarg once all callers updated. |
| wE3 (`promote_atomic.py`) | CDX-04 shared-stem lock — your ownership; no `generate_determinism_anchor.py` change from this lane beyond help text. |
| wE5 (`cli.py` / README) if docs mention ENOENT format-only degrade for `--live-head-sha` | Align docs with refuse-uniform (rg-006). Not verified whether CLI help still claims degrade. |
