# Lane `fx5` report — lane-report SHA guard + evidence trail

**Lane:** `fx5`  
**Task:** `VLM-6`  
**Branch:** `feature/vlm-6-fx5` (this lane's branch)  
**Base:** `e2575b5ef09ed75de7f792546439d53624c9d344`

Owned paths only: `scripts/check_lane_report_shas.py`, `scripts/test_check_lane_report_shas.py`,
`.s2a/**`, `docs/tasks/vlm/VLM-6-gpu-vlm-bakeoff-task-plan.md`.

---

## Guard redesign (D-03 / D-04 / D-05 / D-10)

### Behaviour change (one line)

Extract every 7–40 hex token (case-insensitive), resolve against the repo, fail
closed on missing paths and unresolvable tokens; exclude only per-token content
digests / HTML-comment spans / `sha-guard:ignore` — never whole-line keyword vetoes.

### Files

- `scripts/check_lane_report_shas.py` (redesign)
- `scripts/test_check_lane_report_shas.py` (new; 9 tests)
- Report text fixes so the strict guard can stay strict: `.s2a/vlm6-fix-f1a-report.md`,
  `.s2a/vlm6-fix-f2b-report.md`, `.s2a/vlm6-la2-placement-metrics-report.md`

### VLM6-D-03 — missing path fails open

| | |
| --- | --- |
| **Touch** | `scripts/check_lane_report_shas.py` `main()` target loop |
| **RED** (unfixed) | `python3 scripts/check_lane_report_shas.py .s2a/does-not-exist-vlm6.md` → exit **0**, stdout `lane report SHA citations: 1 file(s) checked, all resolve` |
| **Test RED** | `test_missing_path_fails_closed_and_does_not_claim_resolve` → `AssertionError: missing path must exit non-zero; got 0 with stdout='lane report SHA citations: 1 file(s) checked, all resolve\n' stderr=''` |
| **GREEN** | same CLI → exit **1**, stderr contains `target is not a readable file — refusing to claim SHA citations resolve for an unopened path`; test **PASSED** |
| **Change** | Missing/unreadable targets append a violation; success summary counts only opened files. |

### VLM6-D-04 — uppercase hex invisible

| | |
| --- | --- |
| **Touch** | `scripts/check_lane_report_shas.py` `_HEX = re.compile(r'\b([0-9a-fA-F]{7,40})\b')` |
| **RED** | fixture `Landed at commit` + uppercase 7-hex token → exit **0**, `1 file(s) checked, all resolve` |
| **Test RED** | `test_uppercase_sha_is_visible_and_flagged` → `AssertionError: expected fail, got stdout='lane report SHA citations: 1 file(s) checked, all resolve\n'` |
| **GREEN** | exit **1**, stderr names the uppercase token / `does not resolve`; test **PASSED** |
| **Change** | Case-insensitive token extraction. |

### VLM6-D-05 — citation shapes escape + live sandbox SHA

| | |
| --- | --- |
| **Touch** | `scan_file` redesign (no `_CITATION_CONTEXT` gate; per-token digest exclusion; comment-span strip only) |
| **RED** | `**Sandbox base:**` / `Landing SHA` bare hex / digest-line citation / outside-`<!--` citation → exit **0**; live `.s2a/vlm6-fix-f1a-report.md` sandbox base (unresolvable) → exit **0**, `1 file(s) checked, all resolve` |
<!-- example tokens from RED fixtures deliberately omitted from prose so the guard stays strict -->
| **Test RED** | `test_sandbox_base_phrasing_flags_unresolvable_token`, `test_citation_outside_html_comment_is_not_skipped`, `test_digest_keyword_does_not_veto_commit_citation` each → `AssertionError: expected fail, got stdout='lane report SHA citations: 1 file(s) checked, all resolve\n'` |
| **GREEN** | all three tests **PASSED**; live f1a fixed (sandbox SHA moved into HTML comment); full tree `python3 scripts/check_lane_report_shas.py` → `34 file(s) checked, all resolve` exit 0 |
| **Change** | Every non-excluded hex token is resolved; reports with genuine unresolvable sandbox SHAs were corrected (sr-001 — guard not weakened). |

### VLM6-D-10 — zero tests

| | |
| --- | --- |
| **Touch** | `scripts/test_check_lane_report_shas.py` (new) |
| **RED** | 5 discrimination tests **FAILED** against unfixed guard (see D-03/04/05 quotes); 4 pass-path tests already green |
| **GREEN** | `9 passed in 0.56s` — collected count **9** (`--collect-only`) |
| **Change** | Permanent TEST-15 surface for every escape class named above. |

**Command:**
```bash
apps/prototype-description-service/.venv/bin/python -m pytest scripts/test_check_lane_report_shas.py -q
```

---

## Evidence trail

### VLM6-D-01 — missing lc2 report

| | |
| --- | --- |
| **Touch** | `.s2a/vlm6-lc2-cli-report.md` (new) |
| **RED** | n/a executable — documentation defect; verified `git log --all -- '.s2a/*lc2*'` empty and no `*lc2*` under `.s2a/` at base |
| **GREEN** | Report present; marked **reconstructed post-hoc by lane fx5**; claim table derived from `3e57f7e7` and re-checked symbols/tests at HEAD (`ScoreGateError`, evidence gates, `compare`, run multi-record scoring) |
| **Change** | Audit surface for lc2 CLI residual gates exists without inventing closed finding IDs. |

### VLM6-D-02 — missing lb2 report

| | |
| --- | --- |
| **Touch** | `.s2a/vlm6-lb2-load-manifest-report.md` (new) |
| **RED** | n/a executable — documentation defect; only sibling lb1 report existed |
| **GREEN** | Report present; each classification verified at HEAD (`bakeoff.main` weave skip vs pixel `images_dir`, `fusion_runner.main` skip, four test helpers skip, `test_pixel_path_load_manifest_requires_hash_verification` TEST-15) |
| **Change** | Non-CLI `load_manifest` skip decisions are auditable. |

### VLM6-D-06 — s2a-guards false exact messages

| | |
| --- | --- |
| **Touch** | `.s2a/vlm6-s2a-guards-report.md` |
| **RED** | n/a executable — hand-verified: strings `score_manifest_sha256 differs from fetch-time manifest_sha256 — corpus truncation or post-fetch edit` and `golden corpus defines no Must-Right/Easy-Wrong rubric entries; caption hard gate is vacuous` absent from `cli.py` / tests at HEAD |
| **GREEN** | Table re-derived: stable identity = test names; HEAD stems described (`run-record provenance missing fetch-time manifest_sha256…`, `must_right is vacuous corpus-wide` / `easy_wrong is vacuous corpus-wide`) |
| **Change** | Report can no longer rot on the next message-edit by a sibling lane. |

### VLM6-D-07 — lb1 line anchors wrong

| | |
| --- | --- |
| **Touch** | `.s2a/vlm6-lb1-cli-hash-callsites-report.md` |
| **RED** | n/a executable — hand-verified: prior line anchors (631/1536/1638/1693) land on unrelated statements; real calls are `_cmd_fetch`/`_cmd_face_bakeoff` with `images_dir=`, skips on score/face-score/determinism helpers |
| **GREEN** | Table re-anchored on function name + kwargs; re-verified at HEAD |
| **Change** | Reviewer following the table lands on the real classification (`rg-005`). |

### VLM6-D-08 — invented VLM6-R3-06 closure

| | |
| --- | --- |
| **Touch** | `.s2a/vlm6-lc1-report-report.md` row for R3-06 |
| **RED** | n/a executable — hand-verified: ID appears only in this report + trailing comments on R3-01/R3-02 tests; no handoff record |
| **GREEN** | Row marked **not a real finding ID**; points coverage at real **VLM6-R3-01** / **VLM6-R3-02** |
| **Change** | False closure claim removed. |

### VLM6-D-09 — task plan over-claims face baseline

| | |
| --- | --- |
| **Touch** | `docs/tasks/vlm/VLM-6-gpu-vlm-bakeoff-task-plan.md` Slice 0 paragraph |
| **RED** | n/a executable — hand-verified: prior text called face P/R "**real**" / baseline "**genuine**" while corpus boundary records face_boxes/spatial_facts/reference_facts on 0/37 and anchor generator self-stamps GT |
| **GREEN** | Sampling frame rewritten (AUDIT-07): π=0 claim units named; S0 delivery stated as harness/determinism freeze, not adoption-grade face quality; checklist ticks left intact |
| **Change** | Plan no longer over-claims the 37-image face numbers. |

### VLM6-C-06 — `describe_baseline.py` no offline Δ (judgement)

**Disposition: Cross-lane request** (not Deferred).

Reason: Δ reporting is implementable on the current 37-image corpus and does not
require Golden-100. Absolute counts alone cannot answer EVAL-01 ("did the
candidate improve anything?"). The owning file is out of this lane's scope.

Concrete requirement for the owning lane: see **Cross-lane requests** below.

---

## Cross-lane requests

### C-06 / EVAL-01 — `describe_baseline.py` offline baseline deltas

Owner: lane that owns `apps/prototype-description-service/scripts/eval_harness/describe_baseline.py`
(sibling; **not edited here**).

Required behaviour:

1. Load the real golden corpus (not fabricated empty-rubric transport stubs) when
   computing a report that claims baseline status.
2. Emit **Δ** columns vs at least one fixed reference:
   - zero-rule / empty-caption captioner (lower bound), and/or
   - current production Florence path when an offline freeze exists.
3. Report absolute counts **and** deltas for the same metrics the bake-off ranks
   on (at minimum insertion/gated caption metrics the compare gate already uses).
4. Fail closed (non-zero or explicit `undefined`/non-adoption status) when the
   reference arm cannot be scored — do not print a green absolute-only report as
   if it answered "improved?".
5. TEST-15: a fixture where the candidate is strictly worse than the reference
   must go red on the Δ surface; a candidate that only matches absolute counts
   of a vacuous stub must not look like a win.

### Optional (informational)

- Lane `fx1` may continue rephrasing score-gate operator messages; s2a-guards
  report now keys stability on **test names**, not quoted literals.

---

## Deferred

Nothing deferred to Golden-100 for this lane's assigned findings. Vacuity of
positional/placement/fabricated-fact on the 37-image corpus is **documented**
in the task-plan rewrite (D-09) and remains Slice 1 work for producing those
claim units — the gate-honesty fixes for those metrics belong to the scoring
lanes, not this report/guard lane.

---

## Verification summary

```
# RED battery (unfixed guard): 5 failed, 4 passed
# GREEN battery (fixed guard): 9 passed in 0.56s  (9 collected)
# Full-tree guard: lane report SHA citations: 34 file(s) checked, all resolve
```

Heuristics cited: TEST-15, AUDIT-07, sr-001, rg-005, EVAL-01 (C-06 disposition).
