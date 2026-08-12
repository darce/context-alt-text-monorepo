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

Wired placement + fabricated-fact hallucination into scored report JSON/MD;
excluded cache hits from latency percentiles; expanded public-report redaction
(secrets, absolute paths); surface gated-score components and quality-axis
aggregates that were previously computed only on `per_image`. `build_reports()`
signature unchanged (no breaking CLI interface change).

## Gate counts

| When | Result |
| --- | --- |
| **Before** | **86 passed** |
| **After** | **97 passed** |

```
cd apps/prototype-description-service && uv run --extra dev pytest \
  scene/tests/test_eval_harness_report.py scene/tests/test_eval_harness_bakeoff_report.py -q -p no:randomly
```

## Note on findings source

`.lane-brief/findings.md` was **not provisioned** into this sandbox (git-excluded
and absent from the clone; handoff.db empty). Findings below were reconstructed
from the assignment themes + code probes + sibling-lane reports (la1/la2).
IDs marked *reconstructed* map to assignment clusters; line anchors from the
original brief are unavailable here.

## Per-finding table

| Finding ID | What changed | RED-before assertion | GREEN-after |
| --- | --- | --- | --- |
| **VLM6-R4-02** (placement) | `score_placement` / `placement_accuracy` wired into `score_run_record` → top-level `placement` + per-image `placement` + MD line | `assert 'placement' in scored` → **AssertionError: assert 'placement' in {…}** | accuracy=1.0 on correct claim; accuracy=0.0 on wrong claim; MD has `placement accuracy` |
| **VLM6-R2-02** (hallucination) | `score_hallucination` / `fabricated_fact_rate` / `fabrication_by_kind` → top-level `hallucination` + per-image + MD | `assert 'hallucination' in scored` → **AssertionError: assert 'hallucination' in {…}** | fabricated_fact_rate=1.0 when trap hit; 0.0 when clean; MD has `fabricated-fact rate` |
| **VLM6-R4-04** (latency/cache) | `_latency_summary` skips `describe.cached=True`; reports `cache_hits_excluded` | `assert summary["images_timed"] == 2` → **assert 3 == 2** (cache hit counted) | images_timed=2 over live only; cache_hits_excluded=1; all-cache → None |
| **VLM6-R3-01..05** (public leaks, cluster) | Expanded `_PUBLIC_PROVENANCE_WITHHELD_FIELDS` (api_key, tenant_id, tokens…); render-boundary `_redact_public_paths` collapses absolute paths to basename; still redacts `base_url` | `assert 'sk-live-TOPSECRET-xyz' not in blob` **fails**; `assert '/Users/daniel' not in blob` **fails** | secrets → `"redacted"`; abs path → basename only; LOCAL unchanged |
| **VLM6-R2-04** (positional labeled-order) | When `face_boxes` missing, positional `labeled=[]` + `labeled_order_known=False` (no alphabetical `present` fallback as dead labeled input) | Pre-existing exclude behavior; new test pins `compared_images==0` / empty totals | excluded legacy entries; no alphabetical compare |
| **R4-05/06/07/09 group** (quality aggregates, *reconstructed*) | `quality` block now surfaces `mean_fkre`, `mean_repetition_ratio`, `mean_tag_coverage`, `first_sentence_gist_ok_rate` (were per_image-only dead paths) | `assert quality.get("mean_fkre") is not None` → **assert None is not None** | mean_fkre present; MD lines for FKRE/repetition/tag/gist |
| **gated components** (la1 wiring / *likely R4 or S2A-B-09*) | `aggregate_gated_scores` → `gated_score_scored` / `gated_score_excluded` on caption + MD | `assert 'gated_score_scored' in scored["caption"]` fails | components sum to scored count; MD shows `excluded=` |
| **RH-07 / S2A-B-09** | Mapped into gated components + quality aggregate surfacing above; exact original text unavailable without findings.md | (see gated/quality rows) | (see gated/quality rows) |

## Explicitly NOT fixed / caveats

| Item | Why |
| --- | --- |
| Exact R3-01 vs R3-02 vs … split | findings.md missing; treated as one public-redaction cluster with 5 leak surfaces (base_url already present, api_key, tenant_id, abs paths, local-name exclusion already covered by existing tests) |
| RH-07 / S2A-B-09 exact text | IDs named in assignment group only; implemented closest dead-path surfaces (quality rollups + gated components). Orchestrator should re-map if IDs targeted different lines. |
| `build_reports()` signature change | **Not done** — hard pin for concurrent `vlm6-lc2-cli` |
| `cli.py` / `--audience` flag | Out of owned paths (sibling lc2) |
| `manifest.py`, bakeoff-results anchors | Forbidden by runtime guidance |
| `build_bakeoff_report.py` | Not owned; bakeoff_report tests untouched (still pass) |

## Cross-lane dependencies

- **vlm6-lc2-cli**: no interface break; `build_reports(..., audience=, rubric_gate=)` unchanged.
- **la1 caption-metrics**: consumes `aggregate_gated_scores` as recommended in la1 report.
- **la2 placement-metrics**: consumes fixed `score_placement` (paraphrase-capable).

## Diff summary (`report.py`)

1. Import placement + hallucination scorers and `aggregate_gated_scores`.
2. Per-item: parse `spatial_facts` / `reference_facts`; score; attach to `per_image`.
3. Corpus: `placement` + `hallucination` blocks; gated scored/excluded; quality axis rollups.
4. Latency: skip cache hits; optional `cache_hits_excluded`.
5. Public render: expand provenance redaction fields; basename absolute paths.
6. Markdown: placement, hallucination, gated components, quality axes, cache-hit note.

## Commits

Only owned paths + `.s2a/` (see `git diff --cached --name-only` discipline).
