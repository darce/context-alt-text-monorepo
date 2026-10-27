# Description-model decision layer (DESCPICK-1)

Turns the v2 operator review (`qwen-high-precision-20261025/review-all-history-v2`) into a report that can
pick the description model for the OCI A10 24 GB bursty GPU: one **quality** winner and one **best performer**
(best quality for inference time). The rule is pre-registered in `decision-rule.json` (handoff decision 20175)
before any cross-model review. Canon release v0.26.2: <https://github.com/darce/heuristics-canon>.

## Files

| File | Owner | Kind |
| --- | --- | --- |
| `operator-metrics.js` | L1 | UMD (`module.exports` / `root.OperatorMetrics`); adds the decision API, `summarize` unchanged |
| `operator-crossmodel.js` | L2 | new UMD (`root.OperatorCrossModel`): pure cross-model order + progress |
| `operator-review.js`, `operator-review.css` | L2 | DOM IIFE; cross-model blind mode + panel mount |
| `operator-decision.js` | L3 | new UMD (`root.OperatorDecision`): `render`, `view`, `asciiSummary` |
| `../build_decision_report.py` | L4 | Python 3.12 stdlib builder |
| `decision-rule.json`, `DESIGN.md`, `test/fixture.js`, `fixtures/**` | S0 | frozen; lanes never edit |

UMD shape for every new JS module, matching `operator-metrics.js`:
`(function(root){'use strict'; ... const api={...}; if(typeof module==='object'&&module.exports)module.exports=api; else root.X=api;})(typeof globalThis!=='undefined'?globalThis:this);`
No dependencies, no network, no `Date.now()`/`Math.random()` in pure functions.

## Inputs

- `manifest`: `bakeoff-operator-manifest/v1` (embedded block `operator-review-manifest`). Decision cells are the
  cells matching `rule.filter` exactly (`scope`, `extraction_lexicon`, `writing_lexicon`, `arm`). Real data: 86
  cells, 29 images; `incumbent-f16` has 28 (image `c081` unrun), the other two 29 each; 0 generation errors.
- `state`: `bakeoff-operator-reviews/v1` (`schema, dataset_id, manifest_sha256, rubric_version, reviewer_id,
  blind_seed, blind_orders, gold, reviews, pairs`). **No state schema change.**
- `contract`: block `operator-review-contract` (enums `issues`, `severity`, `ocr`).
- `rule`: `decision-rule.json` (embedded as block `operator-decision-rule`).
- `perf`: `description-model-perf/v1` (embedded as block `operator-decision-performance`;
  fixture `fixtures/qwen-high-precision-20261025/decision-performance.json`):
  `{schema, source:{file, sha256, lists}, timing_contract, aliases, rows:[{physical_model_id, image_id, E, W,
  profile_sha256, summed_stage_seconds, response_sha256, source_list}]}`; rows are alias-normalized, candidates
  only, sorted by `(physical_model_id, image_id, E, W, profile_sha256, summed_stage_seconds, source_list)`,
  serialized `json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n"`. 315 rows (1 source row
  without `summed_stage_seconds` dropped).

## L1 — `OperatorMetrics` decision API

- `decisionCells(manifest, rule) -> cell[]` in manifest order.
- `decisionReviewed(cell, review, contract, reviewerId) -> bool`: review exists, `reviewed === true`, binds the
  cell (`output_sha256`, `image_id`, `input_sha256` equal), `!cell.generation_error`, non-empty `reviewerId`,
  severity and ocr are contract enums, `severity !== 'not_assessed'`, `ocr !== 'not_assessed'`,
  and not (`severity === 'none'` with issues).
- `accepted(cell, review, rule) -> bool`: decision-reviewed AND severity in `rule.accepted.severity_in` AND no
  issue in `rule.accepted.factual_issues` AND ocr not in `rule.accepted.ocr_not_in`. Generation error: false.
- `decide(manifest, state, perf, rule, contract) -> DecisionResult` (pure, deterministic, throws on
  dataset/manifest/rubric mismatch between manifest, state and rule):

```
{ schema: 'description-model-decision/v1',
  status: 'insufficient_reviews' | 'decided' | 'undecided' | 'coverage_sensitive',
  coverage: { decision_cells, reviewed, pending_keys: [cell.key], missing: [{physical_model_id, image_id}],
              generation_errors },
  models: [{ physical_model_id, label, images, cells, accepted, accepted_rate, accepted_rate_bounds: [lo, hi],
             major_or_worse, major_or_worse_rate,
             latency: { profile_sha256, n, p50_seconds, other_profiles: [{profile_sha256, n, p50_seconds}] } | null,
             timing_missing: [image_id], seconds_per_accepted }],
  comparisons: [{ a, b, n_images, accepted_delta, accepted_delta_ci95: [lo, hi],
                  major_delta, major_delta_ci95: [lo, hi] }],
  quality: { winner: physical_model_id | null, verdict: 'winner' | 'undecided', reason },
  performance: { winner, leader, verdict: 'winner' | 'none', reason },
  power: [{ a, b, ci_half_width, images_needed }],
  notes: [string] }
```

- `missing` = (candidate, image) pairs with no decision cell. `pending_keys` = decision cells (not generation
  errors) that are not decision-reviewed. While `pending_keys` is non-empty: `status = 'insufficient_reviews'`,
  every quality field (`accepted*`, `major*`, `seconds_per_accepted`, `comparisons`, `quality`, `performance`,
  `power`) is `null`; coverage and latency are still returned.
- Per image and model, indicator `acc` (accepted) and `maj` (severity in `rule.major_or_worse`). Missing cells are
  imputed twice: **pessimistic** (`acc=0, maj=1`) and **optimistic** (`acc=1, maj=0`). Generation errors are
  `acc=0, maj=0` in both. Reported numbers use the pessimistic imputation; `accepted_rate_bounds` gives both.
  Rates are over `rule.images` (29), the image being the unit.
- Comparisons for each unordered candidate pair (candidates order `a<b` as in `rule.candidates`): per-image
  paired differences `a − b` over all 29 images; CI by the existing `ci()` algorithm verbatim
  (paired-image-xorshift32-v1, seed `rule.bootstrap.seed`, 2000 resamples, indices 49/1949), reseeded per call.
- Quality: winner = the max `accepted_rate` model whose paired `accepted_delta` CI lower bound is `> 0` against
  every other candidate; else `undecided`.
- Performance: leader = quality winner, else the max `accepted_rate` point estimate (ties: `rule.candidates`
  order). Candidates with `latency` sorted by `p50_seconds` ascending; winner = first with CI lower of
  `accepted(c) − accepted(leader)` `> −rule.delta` and CI upper of `major(c) − major(leader)` `< rule.delta`
  (the leader always qualifies against itself).
- Verdicts are computed under both imputations; if quality winner or performance winner differ,
  `status = 'coverage_sensitive'`, else `'decided'` when a quality winner exists, `'undecided'` otherwise.
- Latency: join each decision cell to perf rows on `(physical_model_id, image_id, E=rule.filter.extraction_lexicon,
  W=rule.filter.writing_lexicon)`. Exactly one row joins; zero or several rows, or a cell `response_sha256` that
  differs from the row's, put the image in `timing_missing` (with a note). Per model, group joined rows by
  `profile_sha256`; the latency profile has the most rows (tie: slower p50). Never pool profiles.
  p50 = median (mean of the two middle values for even n). `seconds_per_accepted = p50 / accepted_rate`
  (null when rate is 0).
- Power per comparison: `ci_half_width = (hi − lo)/2` of `accepted_delta_ci95`;
  `images_needed = ceil(29 · (ci_half_width / rule.delta)²)`.
- Real-data pins (initial state): `status 'insufficient_reviews'`, `decision_cells 86`, `reviewed 0`,
  `missing [{incumbent-f16, c081}]`, `generation_errors 0`; timing joins 83/86 (missing: qwen38-bf16 c009, c081,
  c053); latency profiles: incumbent-f16 `144645d2c679…` n17 p50 145.029086, other `bfd8dbe5eefe…` n11
  90.825025; qwen3-vl-8b-f16 `147571bcacad…` n29 14.781613; qwen38-bf16 `cc8a63650812…` n21 295.545954, other
  `fc3d3cc68863…` n5 185.232701. 35 decision cells carry `response_sha256`; the 32 of them that join all equal the joined row.

## L2 — cross-model blind review (UI)

- `OperatorCrossModel.order(manifest, rule, seed) -> {image_id: [cell.key]}`: decision cells per image, sorted by
  `hash(seed + '|' + image_id + '|' + key)` (the FNV-1a `hash` in `operator-review.js`), ties by key. Derived,
  never stored. Counterbalances candidate position across images [EVAL-14].
- `OperatorCrossModel.progress(manifest, rule, state, contract) -> {done, total, pending_keys}` using the same
  decision-reviewed predicate as L1 (call `root.OperatorMetrics.decisionReviewed` when present; the pure module
  must also work standalone in node tests by accepting the predicate as an optional 5th argument).
- `operator-review.js`: a third mode "Cross-model blind review" beside the existing within-model blind A/B
  (mutually exclusive). In it each card shows only its decision cells, in `order(...)`, headed
  "Candidate 1/2/3". Hide everything in the cell column that identifies the model: `.state`, `.model-meta`,
  `.timing`, `.run-accounting`, `.provenance-details`, raw links, and the per-column `--model-hue` /
  `--model-saturation` colour (neutral class). Hide `.operator-pairs`; metrics stay hidden (as in blind A/B).
  Restore the exact original DOM on exit. Toolbar progress: "Decision reviewed n / 86".
- In cross-model mode the "Reviewed" checkbox for a decision cell stays disabled until severity and OCR are both
  set (not `not_assessed`), with a visible reason in the existing feedback line.
- Mount: a `<details id="operator-decision">` in the toolbar; on build and after every `persist()` call
  `root.OperatorDecision.render(host, {manifest, state: clone(state), perf, rule, contract, unsealed, onUnseal})`.
  `perf`/`rule` come from blocks `operator-decision-performance`/`operator-decision-rule`; when either block or
  `root.OperatorDecision` is absent, show "Decision panel unavailable" and change nothing else. `unsealed` is an
  in-memory flag (never in `state`, never in localStorage); any blind mode forces the panel sealed.

## L3 — `OperatorDecision` panel

- `view(result, unsealed) -> plain object` (pure): `{sealed, status, headline, coverage_line, rows, notes}`.
  Sealed when `status === 'insufficient_reviews'` or `!unsealed`; a sealed view exposes coverage only (no rates,
  no winners, no model labels — `headline` says how many cells remain) [EXP-09].
- `render(host, opts)`: computes `OperatorMetrics.decide(...)`, renders `view` into `host` with an "Unseal
  decision" button only when coverage is complete and still sealed (calls `opts.onUnseal`). Status uses a text
  label plus an icon, never colour alone; one `role="status"` live region. Uses `--acx-*` tokens if styling.
- `asciiSummary(result) -> string`: deterministic plain-text table (models, accepted rate + bounds, major rate,
  latency p50 + profile prefix + n, seconds per accepted, verdicts, power), used by the builder receipt and the
  G1 verification.

## L4 — `benchmarks/tools/build_decision_report.py`

`--source <v2 index.html> --gpu-performance <json> --rule <decision-rule.json> --assets <dir with the JS/CSS>
--out <dir> [--copy-from <v2 dir>]`:
- Refuse (exit 2) when manifest `dataset_id`/`manifest_sha256`/`rubric_version` differ from the rule.
- Keep the four existing JSON blocks byte-identical; add blocks `operator-decision-rule` (the rule file) and
  `operator-decision-performance` (normalized perf, byte-identical to the fixture for the fixture input), with
  `</` escaped as `<\/`.
- Emit content-hashed assets `name.<sha256[:12]>.ext` for `operator-metrics.js`, `operator-crossmodel.js`,
  `operator-decision.js`, `operator-review.js`, `operator-review.css`; rewrite the existing tags and add the two
  new `<script defer>` tags before `operator-review.*.js`.
- `--copy-from` copies `images/` and other sibling files the page links, never overwriting the outputs.
- Write `decision-build-receipt.json`: input/output sha256s, block sha256s, counts (decision cells, perf rows,
  timing joins). Deterministic: two runs give identical bytes.

## Verification

Node tests use `node --test` (node 22 on the VM, no npm deps) and are run through pytest wrappers in
`benchmarks/tests/test_drv_*.py` (`subprocess.run(['node', '--test', <file>])`, assert exit 0), so every lane's
`test_cmd` is `LC_ALL=C uv run --no-project --with pytest python -m pytest benchmarks/tests/<wrapper>.py -q -p no:cacheprovider`
(L4: its own `benchmarks/tests/test_build_decision_report.py`). Each lane shows its new
test red on the base and green after [TEST-15].
