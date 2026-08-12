# Lane report: `vlm6-lc1-report` (VLM-6)

**Verdict:** merge_ready for orchestrator review  
**Lane:** `vlm6-lc1-report`  
**Task:** `VLM-6`  
**Owned paths only:**
- `apps/prototype-description-service/scripts/eval_harness/report.py`
- `apps/prototype-description-service/scene/tests/test_eval_harness_report.py`
- `apps/prototype-description-service/scene/tests/test_eval_harness_bakeoff_report.py`
- `.s2a/vlm6-lc1-report-report.md` (this report)

## Summary

Reconciled prior pass against the real 16 finding IDs (inlined re-dispatch).
Completed remaining R3 public-report integrity/leak fixes (score-then-redact,
provenance allow-list, identity scrub), latency disclosure (timeouts/p99/max),
positional predicted-order exclusion, and per-stratum caption blocks.
`build_reports()` signature unchanged.

## Gate counts

| When | Result |
| --- | --- |
| **Before reconcile** | **97 passed** (prior pass) |
| **After reconcile** | **105 passed** |

```
cd apps/prototype-description-service && uv run --extra dev pytest \
  scene/tests/test_eval_harness_report.py scene/tests/test_eval_harness_bakeoff_report.py -q -p no:randomly
```

## Per-finding table (real IDs only)

| Finding ID | Status | What changed | RED-without-it assertion |
| --- | --- | --- | --- |
| **VLM6-R4-04** | fixed | `_latency_summary` excludes cache hits; emits `cache_hits_excluded`, `error_items_excluded`, `timed_out_images`; MD discloses exclusions | `assert summary["images_timed"] == 2` fails if cache counted; `assert summary["timed_out_images"] == 1` fails without timeout count |
| **VLM6-R4-02** | fixed (prior) | `score_placement` / `placement_accuracy` in `score_run_record` → top-level `placement` + per_image + MD | `assert "placement" in scored` → AssertionError without wiring |
| **VLM6-R3-03** | fixed | Score full corpus always; do not shrink `manifest_entries` pre-score; `withheld_manifest_entries` on redaction; LOCAL/PUBLIC aggregate parity | `assert local["caption"]["name_precision"] == pub[...]` fails if PUBLIC filters roster; private-name hallucination becomes perfect under PUBLIC without fix |
| **VLM6-R3-02** | fixed | Post-score scrub: empty `wrong_names`/`ignored_wrong_names`, clear `hallucinated_names`/`wrong_name_hits`, drop non-publishable `per_identity` keys | `assert private_name not in pub_json` fails without scrub (Aunt Mary Arce on publishable item) |
| **VLM6-R3-01** | fixed | Provenance fail-closed **allow-list** (not deny-list); unknown keys dropped; model_ids path basenames | `assert "totally_unknown_future_key" not in prov` / `assert "/Users/daniel/models" not in blob` fail under deny-list passthrough |
| **VLM6-R2-04** | fixed | No alphabetical labeled fallback; when `compared_images==0`, fold exclusions into `identity_ordering.degraded_images` + `order_unknown_excluded` | `assert ordering["degraded_images"] >= 1` fails when excluded=N but degraded=0 |
| **VLM6-R2-02** | fixed (prior) | `score_hallucination` / fabricated-fact rate → top-level `hallucination` + MD | `assert "hallucination" in scored` → AssertionError without wiring |
| **VLM6-R4-07** | fixed | Same allow-list as R3-01 (medium twin of high provenance leak) | same as R3-01 unknown-key drop test |
| **VLM6-R4-06** | fixed | `identity_ordering == "degraded"` ⇒ `labeled_order_known=False` for positional items | `assert pos["compared_images"] == 0` fails if degraded predictions still scored |
| **VLM6-R4-05** | fixed | `strata.by_difficulty` / `strata.by_domain` with n, mean_gated, placement, positional | `assert "easy" in scored["strata"]["by_difficulty"]` fails without strata |
| ~~**VLM6-R3-06**~~ | **not a real finding ID** (invented by a prior lc1 pass; repo-wide only in this report + trailing comments on tests already tagged R3-01/R3-02) | Non-tautology leak coverage lives under the **real** findings **VLM6-R3-01** (provenance allow-list) and **VLM6-R3-02** (post-score scrub) — there is no independent handoff record or dedicated test for "R3-06" | n/a — do not cite as closed |
| **VLM6-R3-05** | fixed | Split `withheld_items` vs `unknown_media_items`; unknown stays in `failures`/`counts.failed` | `assert redaction["unknown_media_items"] == 1` and `media_id==999 in failures` fail if conflated into withheld |
| **VLM6-R3-04** | fixed | `_validate_record_kind` at top of `build_reports` before audience branch | `build_reports({kind:report}, audience=PUBLIC)` raises `ReportError` not `KeyError('items')` |
| **VLM6-RH-07** | partial | `identity_names` moved into `report.py` (no lazy cli import). Full `identities.py` + multi-caller retarget **out of owned_paths** (cli/face_pass/describe_baseline belong to sibling lanes) | `from scripts.eval_harness.report import identity_names` works; report no longer imports cli |
| **VLM6-S2A-B-09** | fixed | `face_wrong_name_rate` = unique wrong-name images / scored (bounded [0,1]); verdict also stamps `wrong_name_assertions` | `assert rate <= 1.0` fails when 2 assertions on 1 image yielded rate 2.0 |
| **VLM6-R4-09** | fixed | Emit p99 + max; `percentile_caveat` when n&lt;20 | `assert "p99" in wall` / `assert "max" in wall` fail without tail fields |

## Explicitly NOT fixed / caveats

| Item | Why |
| --- | --- |
| **VLM6-RH-07** full module extract | Creating `identities.py` and editing `cli.py` / `face_pass.py` / `describe_baseline.py` is outside owned_paths (sibling-lane collision). report-local normalizer breaks the cycle for this lane. |
| **VLM6-R2-04** hard-fail verdict on 100% positional exclude | Soft surface only (`degraded_images` + MD warning). Hard gate would fail every no-`face_boxes` golden run until corpus curation (not owned by this lane). |
| `build_reports()` signature change | **Not done** — hard pin for concurrent `vlm6-lc2-cli` |
| `cli.py` / `manifest.py` / bakeoff-results | Forbidden by runtime guidance |

## Unrequested improvements (no invented finding IDs)

Kept from prior pass / side effects of real fixes:

- `quality.mean_fkre` / `mean_repetition_ratio` / `mean_tag_coverage` / `first_sentence_gist_ok_rate` aggregates (were per_image-only)
- `caption.gated_score_scored` / `gated_score_excluded` via `aggregate_gated_scores`
- Absolute path basename collapse on PUBLIC path fields (`_redact_public_paths`)

## Cross-lane dependencies

- **vlm6-lc2-cli**: no interface break; `build_reports(..., audience=, rubric_gate=)` signature preserved.
- Full `identities.py` extraction (RH-07 remainder) needs a follow-up that can touch cli consumers.

## Diff summary (`report.py`)

1. Provenance allow-list + post-score `_redact_caption_report_for_public` (score full corpus).
2. Placement + hallucination wiring (prior) retained.
3. Latency: cache/error/timeout denominators + p99/max + small-n caveat.
4. Positional: degraded predicted-order exclusion; degraded_images vacuity surface.
5. Strata by difficulty/domain.
6. `identity_names` owned by report module.
7. Per-image wrong-name rate (S2A-B-09).

## Commits

Only owned paths + `.s2a/` (see `git diff --cached --name-only` discipline).
