# VLM-6 Wave C · lane cx4 — provenance SHA guard degrade predicate

Lane: `cx4` · Worktree: `~/lane-gx5` · Branch: `fix/cx4`  
Base: `7812d71c832786328705a8d6ea6e1d7f41dc487b` (`integ/fx-wave`)  
HEAD after lane:

sha-guard:ignore-next-block
```
650a5f66d9066fe8994e2b5de0c687610e62ff20
```

Commits (finding order 2 → 3 → 1):

sha-guard:ignore-next-block
```
6f8a4d1a fix(cx4): drop dead --verify-live-head-sha flag (VLM6-R2-D-01)
3483f38d test(cx4): lock CLI boundary against verify_git reentry (VLM6-R2-D-03)
650a5f66 fix(cx4): degrade SHA guard only on missing git binary (VLM6-R2-D-02)
```

Owned files:
- `scripts/eval_harness/provenance_sha.py`
- `scripts/eval_harness/generate_determinism_anchor.py`
- `scene/tests/test_describe_baseline_pin_provenance.py`

Off-limits (respected): `promote_atomic.py`, `test_vlm_promote_atomicity.py`, `report.py`, `cli.py`, `face_metrics.py`, `scripts/check_lane_report_shas.py`, `README.md`, any anchor freeze.

Heuristics: `TEST-15`, `TEST-06`, `DBG-10`, `DBG-11`, `DIAG-01`, `DIAG-03`, `rg-006`, `rg-015`, `sr-001`, `AUDIT-07`.

---

## Signature compiled against (cx3 coordination)

At compile/run time in this worktree, `promote_atomic.validate_live_head_sha` still had:

```
(raw: 'str | None', *, verify_git: 'bool' = True, git_cwd: 'Path | None' = None) -> 'str | None'
```

cx4 call site in `generate_determinism_anchor.main` now is:

```python
live_head = validate_live_head_sha(args.live_head_sha)
```

No `verify_git=` kwarg. Compatible with both current signature (defaulted) and the signature cx3 is required to ship without `verify_git`. **Cross-lane request to cx3** below.

`normalize_head_sha` retains `verify_git: bool = True` (internal shared helper; describe_baseline / promote still pass `True`). The opt-out path is not exposed at the operator CLI.

---

## Finding 2 — VLM6-R2-D-01 (MEDIUM) — dead `--verify-live-head-sha` flag

### Reproduction (verbatim, pre-fix)

<!-- sha-guard:ignore-next-block -->
```
$ .venv/bin/python -c 'from scripts.eval_harness import generate_determinism_anchor as g; g.main(["--help"])'
...
  --verify-live-head-sha
                        also require git rev-parse --verify <sha>^{commit} for
                        --live-head-sha

# WITHOUT flag and WITH flag: identical SystemExit refuse of a*40
SystemExit: --live-head-sha='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' is not a resolvable commit ...
```

Confirmed: flag value discarded; help lied (`rg-006`).

### Fix

1. Deleted `--verify-live-head-sha` argument.
2. Rewrote `--live-head-sha` help: always-on git verify; degrades only on missing git binary (`FileNotFoundError`/`ENOENT`); refuses empty / forty zeros / non-hex / non-resolvable.
3. Call site: `validate_live_head_sha(args.live_head_sha)` — no `verify_git=`.

### GREEN (post-fix)

<!-- sha-guard:ignore-next-block -->
```
$ .venv/bin/python -c 'from scripts.eval_harness import generate_determinism_anchor as g; g.main(["--help"])'
# usage line has no --verify-live-head-sha
# --live-head-sha help states always-on verify + ENOENT-only degrade

# unknown flag now argparse-errors:
$ main([..., "--verify-live-head-sha", ...]) → usage + exit 2

# without flag still refuses fabricated hex:
SystemExit: --live-head-sha='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' is not a resolvable commit ...
```

Commit: `6f8a4d1a`.

---

## Finding 3 — VLM6-R2-D-03 (MEDIUM) — divergence test does not lock CLI wiring

### Reproduction / mutant (pre-boundary-lock)

<!-- sha-guard:ignore-next-block -->
```
DIVERGENCE TEST WOULD PASS (defaults): True (refuses under defaults)
validate_honors_flag('a'*40, verify_git=False) → 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
HOLE REOPENED: yes
RED if CLI wired to verify_git=False: CLI boundary would need to refuse but got 'aaaaaaaa...'
```

Defaults-only `validate_live_head_sha(value)` never exercises `main` or a false flag.

### Tests added (TEST-15)

1. `test_vlm6_r2_d03_cli_main_refuses_fabricated_40_hex` — `gen.main([..., '--no-pin', '--live-head-sha', 'a'*40])` must `SystemExit` match `not a resolvable commit`.
2. `test_vlm6_r2_d03_validate_live_head_sha_has_no_verify_git_param` — `inspect.signature` must not contain `verify_git`.
3. `test_vlm6_r2_d03_no_call_site_passes_verify_git` — regex scan of `scripts/eval_harness/*.py` for `validate_live_head_sha(... verify_git=)`.

Also tightened fx6 divergence missing-git fixture from generic `OSError` → `FileNotFoundError` so it encodes the real degrade contract (feeds finding 1).

### RED / GREEN

| Test | Result |
|------|--------|
| CLI main refuses fake 40-hex | GREEN immediately (always-on verify already) |
| signature has no `verify_git` | **RED** — expected until cx3 lands |
| no call site passes `verify_git=` | GREEN (cx4 call site cleaned in finding 2) |

Signature RED capture:

```
AssertionError: validate_live_head_sha must not expose verify_git=
  (got params ['raw', 'verify_git', 'git_cwd']); cx3 removes it — VLM6-R2-D-03
```

Commit: `3483f38d`.

---

## Finding 1 — VLM6-R2-D-02 (HIGH) — over-broad degrade accepts fabricated SHAs

### Reproduction (verbatim, pre-fix)

<!-- sha-guard:ignore-next-block -->
```
$ cd apps/prototype-description-service
$ .venv/bin/python - <<'PY'
...
--- clean env ---
SystemExit: --live-head-sha='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' is not a resolvable commit ...
--- GIT_DIR=/nonexistent/path ---
'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
```

Supporting probes (all ACCEPTED pre-fix):

| Path | Pre-fix |
|------|----------|
| poisoned `GIT_DIR` | ACCEPTED |
| is-inside timeout | ACCEPTED |
| is-inside rc=128 | ACCEPTED |
| is-inside empty stdout | ACCEPTED |
| bare repo (`false`) | ACCEPTED |
| generic `OSError` EACCES | ACCEPTED |
| `FileNotFoundError` missing binary | ACCEPTED (correct offline hatch) |
| verify-path timeout | REFUSE (asymmetric with first probe) |

### RED (tests vs pre-fix production)

```
FAILED test_vlm6_r2_d02_poisoned_git_dir_refuses — DID NOT RAISE SystemExit
FAILED test_vlm6_r2_d02_is_inside_timeout_refuses — DID NOT RAISE SystemExit
FAILED test_vlm6_r2_d02_is_inside_rc128_refuses — DID NOT RAISE SystemExit
FAILED test_vlm6_r2_d02_is_inside_empty_stdout_refuses — DID NOT RAISE SystemExit
FAILED test_vlm6_r2_d02_bare_repo_refuses — DID NOT RAISE SystemExit
FAILED test_vlm6_r2_d02_non_enoent_oserror_refuses — DID NOT RAISE SystemExit
PASSED test_vlm6_r2_d02_missing_git_binary_degrades
PASSED test_vlm6_r2_d02_enoent_oserror_degrades
PASSED test_vlm6_r2_d02_verify_timeout_still_refuses
6 failed, 3 passed
```

### Fix shape (refuse, not silent `degraded=true`)

Chose **refuse** over a provenance `degraded=true` flag: any git answer that is not "binary missing" raises `SystemExit`. Offline escape hatch preserved only for hard missing-binary (`FileNotFoundError` / `errno.ENOENT`). Both probes share `_is_missing_git_binary` + `_refuse_git_probe` so the exception policy is symmetric.

### GREEN (post-fix)

```
12 passed  (all vlm6_r2_d02 + related rv3_05/fx6)
```

Reviewer probe post-fix:

```
--- clean env ---
SystemExit: ... is not a resolvable commit ...
--- GIT_DIR=/nonexistent/path ---
SystemExit: ... git provenance probe failed (is-inside-work-tree rc=128 stdout='':
  fatal: not a git repository: '/nonexistent/path'); refuse to stamp fabricated provenance ...
```

### TEST-15 discrimination (predicate widened → RED)

Pre-fix mutant that re-opens format-only on `rc=128`:

<!-- sha-guard:ignore-next-block -->
```
pre-fix is-inside rc=128 → 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
  (would make test_vlm6_r2_d02_is_inside_rc128_refuses RED if production restored)
current: REFUSE OK
```

Commit: `650a5f66`.

---

## Disagreements

None. All three findings reproduced exactly as quoted.

---

## New findings (not owned — recorded only)

1. **`normalize_head_sha(verify_git=False)` remains an internal opt-out.** CLI no longer reaches it, but any future library caller can still bypass git verify. Consider removing the parameter in a later wave once all call sites are audited (cx3 only removes it from `validate_live_head_sha`). Not fixed here to avoid expanding into `describe_baseline.py` call-site churn beyond the finding.

2. **`test_rv2_04_cli_refuses_bad_live_head_sha` only covers the forty-zero sentinel**, not format-valid non-commit hex. Finding 3's new CLI test closes that; the older test is still valid for the sentinel class.

---

## Full suite

```
cd apps/prototype-description-service
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
```

**Result:** `1 failed, 1318 passed, 4 skipped, 32 warnings in 301.57s`

Baseline was `1307 passed, 0 failed, 4 skipped`. Delta = **+12 tests** (11 green + 1 expected-red).

### Expected-red (another lane's scope)

| Failure | Owner | Reason |
|---------|-------|--------|
| `test_vlm6_r2_d03_validate_live_head_sha_has_no_verify_git_param` | **cx3** | `validate_live_head_sha` still exposes `verify_git`; cx3 finding 6 removes it from `promote_atomic.py` |

### Unexpected-red

**None.**

---

## `git diff --stat` against `7812d71c`

```
 .../tests/test_describe_baseline_pin_provenance.py | 239 ++++++++++++++++++++-
 .../eval_harness/generate_determinism_anchor.py    |  22 +-
 .../scripts/eval_harness/provenance_sha.py         |  73 +++++--
 3 files changed, 301 insertions(+), 33 deletions(-)
```

---

## What I could not verify

1. **cx3 final signature** — cx3 (`~/lane-gx4`, `fix/cx3`) had not yet removed `verify_git` from `validate_live_head_sha` at the time of this report. Call site is forward-compatible; signature lock test is expected-red until integration.
2. **Power-loss / real bare-repo operator workflows** beyond synthetic `git init --bare` in tmp — bare-repo path is covered by real `git init --bare` + `git_cwd=`.
3. **Artifact-level `degraded=true` route** was not implemented (chose refuse); no end-to-end artifact provenance flag to verify.

---

## Cross-lane requests

### → cx3 (`promote_atomic.py`)

1. Remove `verify_git` from `validate_live_head_sha` entirely (finding 6 in your brief). **Do not honor it.** Final signature cx4 compiled call site against (desired):

   ```python
   def validate_live_head_sha(
       raw: str | None,
       *,
       git_cwd: Path | None = None,
   ) -> str | None: ...
   ```

   Internal call may keep `normalize_head_sha(..., verify_git=True)` until a later wave drops that param from the shared helper.

2. After you land, `test_vlm6_r2_d03_validate_live_head_sha_has_no_verify_git_param` in `test_describe_baseline_pin_provenance.py` goes GREEN with no further cx4 change.

### → coordinator

- Integrate cx3 before treating the signature lock as a merge blocker against cx4; the single expected-red is intentional cross-lane contract glue (`rg-015`).

---

## Scope check

Touched only owned paths. Did not edit `promote_atomic.py` / promote atomicity tests / report / cli / face_metrics / sha-guard script / README / anchors. No `uv sync`, no merge/rebase, no Co-Authored-By.
