# Lane wE1 — `report.py` PUBLIC export identity/path leak

**Branch:** `fix/we1`  
**Base:** `88ed0e524bea8ee625afd405ca7f551d8ae1b5ba`  
**Owned files:** `scripts/eval_harness/report.py`, `scene/tests/test_eval_harness_report.py`

## Summary

Face PUBLIC redaction rewritten to a **fail-closed structural walk**. Independent convergence from RB/RF/CDX/RE on residual A-02 leaks confirmed by probe (`DBG-13`). RE-01/RB-07 false-green test rewritten first (RED on unfixed code), then production fixed.

---

## Per finding

### RB-01 / RF-02 — `list[str]` free text never scrubbed (high)

**Reproduction (verbatim, unfixed):**
```
>>> _scrub_face_public_free_text(obj, ["Jane Doe Private"])
{
  "protocol_disclosures": ["mean_prototype; exclude Jane Doe Private"],  # LEAK
  "gate_proposal": {
    "scope_amendments_for_operator_ack": ["ack Jane Doe Private"],  # LEAK
    "flag_dict": {"msg": "<redacted>"}  # dict path worked
  }
}
```

**RED:** `test_scrub_face_public_free_text_scrubs_list_str_elements` — `assert 'Jane Doe Private' not in blob` failed; list elements unchanged.

**Fix:** `_walk` scrubs bare `str` nodes (list elements + free-floating strings) via `_scrub_face_public_string`.

**GREEN:**
```
{
  "protocol_disclosures": ["<redacted>"],
  "gate_proposal": {
    "scope_amendments_for_operator_ack": ["<redacted>"],
    "flag_dict": {"msg": "<redacted>"}
  }
}
```

---

### RF-01 — demographic `wrong_names` never cleared (high)

**Reproduction (verbatim, unfixed):**
```
demographic block: {'by_cohort': {'adult_f': {'wrong_names': [[1, 0, 'Jane Doe Private', 'Alice']], ...}}}
contains Jane Doe Private: True
```

**RED:** acceptance test — `PUBLIC JSON leaked 'Jane Roster Private'` via `slices.demographic.by_cohort.adult_f.wrong_names`.

**Fix:** `_clear_wrong_names_everywhere` recursive clear of `wrong_names` / `ignored_wrong_names` under all slices (not two-key enum). Harvest also walks all wrong_names cells.

**GREEN:** `demographic: {'by_cohort': {'adult_f': {'wrong_names': [], 'precision': 0.0}}}`; name absent from full JSON.

---

### CDX-01 / RB-04 — private `predicted_name`/`name_star` on publishable decisions (high)

**Reproduction (verbatim, unfixed):**
```
>>> _face_private_identity_names_for_public_scrub(report)
[]
>>> redact_face_report_for_public(report)["decisions"]
[{'true_name': 'Ada Lovelace', 'predicted_name': 'Jane Doe Private', 'name_star': 'Jane Doe Private', ...}]
```

**RED:** acceptance test leaked private predicted names on Ada row.

**Fix:** Harvest any identity not in the publishable-true-name set (including predicted/name_star on publishable probes). Scrub walk keeps `true_name`; keeps `predicted_name`/`name_star` only when value ∈ publishable set; else `<redacted>`.

**GREEN:**
```
decisions: [{'true_name': 'Ada Lovelace', 'predicted_name': '<redacted>', 'name_star': '<redacted>', 'path': 'media_id:2'}]
```

---

### RB-02 — `preserved_aggregate_denominators.sampling_frame` post-scrub bypass (high)

**Reproduction (verbatim, unfixed):**
```
slices.sampling_frame (should scrub): <redacted>
preserved.sampling_frame (LEAK): ops: Jane Doe Private @ /home/ubuntu/secret/notes
JSON contains /home/ubuntu/secret: True
```

**RED:** acceptance test found private path/name under `redaction.preserved_aggregate_denominators`.

**Fix:** Drop free-text `sampling_frame` from preserved (numeric denominators only). Re-scrub the redaction envelope after stamp.

**GREEN:** preserved has only numerators/denominators; no sampling_frame; no private tokens in envelope.

---

### RB-03 — path redaction key-name gated (medium)

**Reproduction (verbatim, unfixed):**
```
>>> step = _redact_public_paths({"error_context": "/home/ubuntu/secret/face-run.json", "path": "..."})
>>> _scrub_face_public_free_text(step, [])
{'error_context': '/home/ubuntu/secret/face-run.json', 'path': '<absolute>'}
```

**Fix:** `_scrub_face_public_string` collapses absolute path strings and free text containing operator path shapes (`/home`, `/var`, `file://`, Windows drive) regardless of key name. Scrub always walks (even empty name roster).

**GREEN:** `error_context` → `<absolute>` or `<redacted>`; no `/home/ubuntu` in PUBLIC blob.

---

### RB-06 — allow-listed free text not fail-closed; harvest too narrow (medium)

**Reproduction (verbatim, unfixed):**
```
>>> _face_private_identity_names_for_public_scrub(report)  # names only in sampling_frames
[]
>>> redact_face_report_for_public(report)["provenance"]
{'tau_fit_status': 'status for /var/op/cache', 'sampling_frames': {'face_id': 'eval of Quinn Murphy'}}
```

**Fix:**
- `tau_fit_status`: closed enum (`fitted` / `mid_grid_unfitted` / `error`); else `<redacted>`.
- `sampling_frames`: only values in `FACE_BAKEOFF_SAMPLING_FRAMES` pass; else `<redacted>`.
- Harvest expanded (all non-publishable identity refs + recursive wrong_names).

**GREEN:** hostile allow-listed free text collapses; protocol enums pass.

---

### RB-05 — raw Python `None` in face markdown (low)

**Fix:** `_manifest_drift_line`, `_fmt_rate_n_over_n`, and `_markdown_face` route scalars through `_fmt_prov` / `_fmt`. Acceptance test bans `\bNone\b` / `\bTrue\b` / `\bFalse\b` on planted fully-null gate fields.

---

### RB-07 / RE-01 — false-green A-02 test (high / medium)

**Reproduction:** existing test planted secrets only in deny-listed provenance keys; deleting `_redact_public_paths` / `_scrub_face_public_free_text` still passed.

**Fix:** Rewrote `test_face_public_redaction_drops_operator_paths_base_url_identity_text` to plant secrets in allow-listed free text, `list[str]`, demographic wrong_names, preserved path, and publishable predicted_name. Added whole-document acceptance test.

**RED on unfixed:** 7/7 new/rewritten tests failed. **GREEN after fix:** 10/10 related tests pass.

---

### RA-01 — `order_degraded` still scored as full spatial GT (high)

**Reproduction (verbatim, unfixed):**
```
# identical x, no y → invented alpha order scored as GT
positional: compared_images=1, exact_order_images=1, position_accuracy=1.0
ordering: labeled_y_missing_images=1  # disclosure present; scoring semantics wrong
```

**Decision / justification:** Exclude `order_degraded` images from positional scoring (`labeled_order_known=False`). A missing-y / invented-alpha L→R sequence is **not** spatial ground truth (`EVAL-03` / `S2-07`). Disclosure remains on `labeled_y_missing_*` (do not overload predicted `degraded_*`). Sibling fully-coordinated images still score.

**RED:** `test_order_degraded_excluded_from_positional_scoring` — `assert 2 == 1` (compared_images).

**GREEN:** `compared_images == 1`, degraded path in `excluded_images`, `labeled_y_missing_images == 1`.

---

### RA-04 — empty-string `y` crashes (low)

**Reproduction:** `labeled_order([{"name":"A","x":0.5,"y":""}])` → `ValueError: could not convert string to float: ''`

**Fix (report boundary):** `_normalize_face_boxes_for_order` maps blank/non-numeric `y` → `None` before `labeled_order`. Source fix remains face_metrics (cross-lane wE4).

**RED:** `test_empty_string_y_normalized_before_labeled_order_in_report` raised ValueError.

**GREEN:** `score_run_record` returns; `labeled_y_missing_images == 1`.

---

### RF-13 — path-basename stem over-scrub (low)

**Reproduction:** harvest of `/ops/al.jpg` → scrub set `['al']` → collapses `alignment` / `image_count`.

**Fix:** Stop harvesting path basenames as scrub targets entirely. Paths handled by path redaction + absolute-path free-text collapse. Identity harvest covers true private names without short stems.

**GREEN:** `"al" not in harvested`; `protocol_disclosures` with "alignment image_count" survives.

---

### RF-15 — A-03/G-06 comment-only closure (low)

**Fix:** Do **not** change `SCORE_PASS_MIN_SCORED_IMAGES=5` or 0.5 floors. Stamp `provenance.low_sample_warning` when `scored < min`, plus static `quality_floor_caveat`. Surface both in caption + face markdown. Added to `_PUBLIC_PROVENANCE_ALLOW_FIELDS`.

**RED:** `assert warn` failed (`None`). **GREEN:** warning present with `scored=2` and min=5; markdown contains `low_sample_warning`.

---

## Disagreements

**None on the owned leak class.** All RB/RF/CDX/RE redaction findings reproduced.

**RA-01 partial prior work:** lane wd-A already aggregated `labeled_y_missing_*` and called `labeled_order` (disclosure half). Residual defect was **scoring semantics** — confirmed live (`position_accuracy=1.0` on invented alpha). Implemented exclusion, not just more disclosure.

**RF-03** (consumer of labeled_order) was already partially closed by wd-A; RA-01 scoring exclusion completes the safety contract.

---

## New findings (not owned)

| Id | Note |
| --- | --- |
| RA-04 source | `face_metrics.labeled_order` still raises on `y:""` for non-report callers — cross-lane wE4 |
| RF-14 | Face `.md` freeze stale after `_fmt_prov` changes — regen stage |
| Caption PUBLIC | Share more of face's free-text path detector? Out of scope |

---

## Full suite

```bash
cd apps/prototype-description-service
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
```

**Result:** `5 failed, 1344 passed, 4 skipped` (baseline was `5 failed, 1338 passed, 4 skipped`).

### Expected-red (not ours — anchor freeze / regen stage)

Same five as baseline + any field-driven growth:

| Test | Cause / owner |
| --- | --- |
| `test_generator_regenerates_byte_identical_committed_anchor` | caption freeze bytes (prior wave) |
| `test_expect_report_matches_committed_freeze_green` | caption freeze |
| `test_face_generator_regenerates_byte_identical_committed_anchor` | face freeze |
| `test_face_expect_report_matches_committed_freeze_green` | face freeze |
| `test_cli_score_face_expect_report_end_to_end_green` | face freeze e2e |

**New published fields that may widen freeze diffs after regen:**

- `provenance.low_sample_warning` (when scored < 5)
- `provenance.quality_floor_caveat` (always on caption score path)
- face markdown: more `_fmt_prov` on nulls (`null` vs raw `None`)
- face PUBLIC `redaction.note` wording; preserved_* no longer carries `sampling_frame`
- positional: `order_degraded` images excluded → `compared_images` / `excluded_images` / accuracy may shift on corpora with missing-y boxes

### Unexpected-red

**None.**

---

## `git diff --stat` vs base

```
 .../scene/tests/test_eval_harness_report.py        | 501 ++++++++++++++++++++-
 .../scripts/eval_harness/report.py                 | 395 ++++++++++++----
 2 files changed, 797 insertions(+), 99 deletions(-)
```

---

## Could not verify

- Live bake-off PUBLIC artifact incidence of private `predicted_name` confusions (`AUDIT-07` — mechanism confirmed, rate unmeasured).
- Whether any committed freeze already embeds empty-string `y` (manifest validation may reject upstream).
- MCP handoff write (lane preamble; no workbay task registration in this worktree).

---

## Cross-lane requests

| To | Request |
| --- | --- |
| wE4 (`face_metrics.py`) | RA-04 source: treat blank/non-numeric `y` as missing (`None`) inside `labeled_order` so non-report callers don't raise. Report already normalizes at the consumer boundary. |
| Regen stage | Expect freeze reds from `low_sample_warning` / `quality_floor_caveat` / `_fmt_prov` face MD / positional exclusion of `order_degraded` / PUBLIC preserved_* shape. Do not weaken tests. |
| wE5 (`cli.py` / README) | Optional: document `low_sample_warning` in score provenance surface if operator docs list provenance keys. |

---

## Design notes (fail-closed shape)

Face PUBLIC redaction is now:

1. Decision filter (publishable ∧ named)
2. Recursive wrong_names clear (all slices)
3. Failures drop
4. Numeric-only preserved denominators
5. `_public_provenance` allow-list with enum/protocol fail-closed for free-text keys
6. `_redact_public_paths`
7. Structural free-text walk (list+dict+str; identity scrub + path shapes; predicted_name publishability gate)
8. Scrub redaction envelope again

Not a deny-list of keys. Not two allow-listed block names.
