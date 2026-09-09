# Lane wF3 — promote/anchor hygiene: stale contract docs + cross-namespace basename collision

**Branch:** `fix/wf3`  
**Base:** `f406193709619d143f463cc5dfa3f316fecb7333` (`integ/fx-wave`)  
**Owned files:** `promote_atomic.py`, `generate_determinism_anchor.py` (no code change needed), `test_vlm_promote_atomicity.py`, `test_describe_baseline_pin_provenance.py` (no change)  

**Verdict:** both cross-lane items **confirmed and closed**. Task 1 docstring-only (callers already refuse-correct). Task 2 fail-closed refuse on stamped foreign dest basename (not published-name change).

---

## 1. Per finding

### wE2 → wF3: `validate_live_head_sha` docstring contradicts refuse-uniform (`rg-006`)

**Origin:** wE2 Cross-lane — docstring still said “degrade when git is missing”.

#### Reproduction / shipped behaviour (read-only `provenance_sha.py`)

`provenance_sha.normalize_head_sha` (wE2 refuse-uniform): every unverifiable SHA raises `SystemExit` — missing git binary, non-worktree cwd, foreign `GIT_*`, impostor git, non-resolvable commit, non-SHA verify stdout. No format-only degrade hatch.

Wrapper delegates with `empty_policy="refuse"`, `verify_git=True`.

**Old docstring text (verbatim, pre-fix):**
```
- git verify is **always on** with degrade when git is missing / not a repo
  (fx6 reconciliation with ``resolve_head_sha``; RV3-05 / rg-015). Callers
  cannot opt out — the ``verify_git`` parameter was removed (VLM6-R2-B-04 /
  cx3 delegated cleanup for cx4 VLM6-R2-D-03) so fabricated SHAs cannot slip
  through a false flag.
```

**Probe (real behaviour):**
<!-- sha-guard:ignore-next-block -->
```
accept real: True
refuse '': --live-head-sha must not be empty; ...
refuse '000…0': --live-head-sha is the fabricated 40-zero sentinel; ...
refuse 'deadbeef': --live-head-sha must be a 40-char lowercase hex git SHA ...
None→ None
```

#### Caller audit (refusal vs degraded value)

Production call sites of `validate_live_head_sha`:

| Site | Handling |
|------|----------|
| `promote_atomic.validate_live_head_sha` | definition; raises via `normalize_head_sha` |
| `generate_determinism_anchor.write_anchor` L297 | bare call — `SystemExit` propagates |
| `generate_determinism_anchor.main` L457 | bare call — `SystemExit` propagates to CLI exit |
| tests in `test_describe_baseline_pin_provenance.py` | `pytest.raises(SystemExit)` throughout |

**No caller expects a degraded return value.** Face generator does not call this symbol.  
`describe_baseline.resolve_head_sha` is a sibling wrapper (not a caller) and still has its own stale “degrade when git is missing” docstring — see Cross-lane / New findings.

#### Fix

Docstring rewritten to refuse-uniform; states callers must treat refusal as `SystemExit`, not degraded `None`/hex.

#### TEST-15

**Docstring-only change — no test added.** Vacuous tests forbidden. Caller correctness established by enumerating the three production sites above + existing refuse-path tests in `test_describe_baseline_pin_provenance.py` (already green; they assert `SystemExit`, not degrade).

#### GREEN

```
docstring stale claim removed: OK
assert "degrade when git is missing" not in doc
```

---

### wE3 → wF3: caption/face final basenames collide on shared `--stem` (CDX-04 residual)

**Origin:** wE3 Cross-lane — temps namespaced; final dest still last-writer-wins if basenames match.

#### Naming surface

| Generator | Artifacts from `--stem` |
|-----------|-------------------------|
| caption (`write_anchor`) | `{stem}.json`, `{stem}-report.json`, `{stem}-report.md` |
| face (`write_face_anchor`) | `{stem}.json`, `{stem}-face-report.json`, `{stem}-face-report.md` (+ `{manifest_stem}.json`) |

Defaults differ (`S2A-determinism-…` vs `S2A-face-determinism-…`). **Same user `--stem` → `{stem}.json` collides.** Reports do not (different suffixes).

#### Reproduction probe (verbatim, pre-fix)

```
=== CAPTION first ===
caption wrote: ['.vlm-caption-promote.lock', 'shared-stem-collision-report.json',
  'shared-stem-collision-report.md', 'shared-stem-collision.json']
caption generator='scripts.eval_harness.generate_determinism_anchor'
caption run size=28935

=== FACE second (same stem, same out_dir) ===
after face: [..., 'shared-stem-collision-face-report.json', ...,
  'shared-stem-collision.json']
face generator='scripts.eval_harness.generate_face_determinism_anchor'
face run size=8581
caption body still present? False
OVERWRITE confirmed: caption content lost=True
caption report still present? True
face report present? True
final shared-stem-collision.json is face? scripts.eval_harness.generate_face_determinism_anchor
```

**Confirmed (not refuted).** Blast radius of renaming published defaults: high (freeze paths, README, CLI tests). **Chose fail-closed refuse** over published-name change.

#### RED (TEST-15 — gate disabled, tests present)

```
FAILED test_wf3_foreign_namespace_stamped_dest_refused - Failed: DID NOT RAISE PromoteError
FAILED test_wf3_caption_face_generators_same_stem_refuse - Failed: DID NOT RAISE PromoteError
2 failed, 2 passed
```

#### Fix

In `atomic_promote`, after recover and before staging:

- `_infer_artifact_namespace(path)` reads JSON `provenance.generator` / top-level `generator`, maps known caption/face module paths → `PromoteNamespace.generator`.
- `_refuse_foreign_dest_overwrite` raises `PromoteError` when dest exists and is stamped foreign.
- Same-namespace regen allowed; unstamped plain files remain LWW (preserves CDX-04 concurrent hybrid guard).

No change to default stems / committed bakeoff basenames.

#### GREEN

```
.....  # 5 wf3 + cdx04 concurrent tests
REFUSED: refuse to overwrite .../shared-stem-collision.json owned by foreign
  generator namespace 'caption' with 'face' promote of basename ...
caption preserved: True
face report absent: True
REFUSED reverse: ... owned by foreign generator namespace 'face' with 'caption' ...
face preserved: True
```

Unit + e2e tests in `test_vlm_promote_atomicity.py`:
- `test_wf3_foreign_namespace_stamped_dest_refused`
- `test_wf3_same_namespace_regen_allowed`
- `test_wf3_unstamped_dest_still_last_writer_wins`
- `test_wf3_caption_face_generators_same_stem_refuse`

---

## 2. Disagreements

None. Both claims reproduced.

---

## 3. New findings (not owned)

| Id | Finding | Owner hint |
|----|---------|------------|
| wF3-N1 | `describe_baseline.resolve_head_sha` docstring still says “degrade when git is missing” while implementation is refuse-uniform via `normalize_head_sha` (`rg-006`). | whoever owns `describe_baseline.py` (not wF3) |
| wF3-N2 | Face synthetic **manifest** has no `generator` stamp. If face installs an unstamped `{manifest_stem}.json` first, caption can later LWW-overwrite that basename (provenance gate has nothing to read). Reverse order is protected (caption run is stamped). | `generate_face_determinism_anchor.py` (not owned) — stamp `generator` on the manifest document or use a manifest basename that cannot equal caption run stems |
| wF3-N3 | Concurrent caption+face promote of the **same unstamped** basename remains last-writer-wins by design (separate per-ns locks). Stamped sequential collision is now refused; concurrent race on two stamped installs of the same basename can still LWW if both pass the pre-install check before either finishes. Residual, not fixed (would need a global dest lock). | future promote_atomic hardening |

---

## 4. Full suite

```bash
cd apps/prototype-description-service
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
```

**Result:** `5 failed, 1376 passed, 4 skipped, 34 warnings in 180.61s`

**Expected-red (anchor-freeze byte-identity — not this lane; do not regenerate):**
1. `test_generator_regenerates_byte_identical_committed_anchor`
2. `test_expect_report_matches_committed_freeze_green`
3. `test_face_generator_regenerates_byte_identical_committed_anchor`
4. `test_face_expect_report_matches_committed_freeze_green`
5. `test_cli_score_face_expect_report_end_to_end_green`

**Unexpected-red:** none.

Baseline was `5 failed, 1372 passed, 4 skipped`; +4 new wF3 tests → `1376 passed`. No new freeze fields published.

Owned modules only: `90 passed` (`test_vlm_promote_atomicity` + `test_describe_baseline_pin_provenance`).

---

## 5. `git diff --stat` vs base

```
 .../scene/tests/test_vlm_promote_atomicity.py      | 103 ++++++++++++++++++++
 .../scripts/eval_harness/promote_atomic.py         | 107 +++++++++++++++++++--
 2 files changed, 204 insertions(+), 6 deletions(-)
```

(`generate_determinism_anchor.py` / pin-provenance tests unchanged — callers already correct.)

---

## 6. Could not verify

- Concurrent dual-stamped race under real process-pool load (only sequential generator e2e + unit refuse + CDX-04 unstamped concurrent). Residual wF3-N3.
- Whether any operator runbook documents the old degrade-on-missing-git contract outside this repo (no network).

---

## 7. Cross-lane requests

| To | Request |
|----|---------|
| Owner of `describe_baseline.py` | Align `resolve_head_sha` docstring with refuse-uniform (same stale “degrade when git is missing” claim as pre-wF3 `validate_live_head_sha`). |
| Owner of `generate_face_determinism_anchor.py` | Stamp `provenance.generator` (or top-level `generator`) on the synthetic face **manifest** JSON so unstamped `{manifest_stem}.json` cannot be LWW-clobbered / clobber without the promote_atomic foreign-namespace gate (wF3-N2). Optional: default `manifest_stem` policy that cannot equal a caption run stem. |

---

## Commits (this lane)

1. production: `promote_atomic.py` (docstring + foreign-dest refuse)
2. tests: `test_vlm_promote_atomicity.py` (wF3 TEST-15 suite)
3. report: `.s2a/vlm6-wF3-report.md`
