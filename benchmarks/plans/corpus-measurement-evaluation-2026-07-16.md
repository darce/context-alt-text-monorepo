# Assessment: is the corpus a good measurement instrument? (2026-07-16)

> Evaluates the two benchmark corpora — the **646** live curation corpus and the
> **golden-37** scored set — as instruments for the product goal ("better image
> descriptions"), and gives ranked, concrete improvements. Grounded in measured
> stats from the 2026-07-16 v3 interleave run. Companion to
> [`multi-model-bakeoff-plan-2026-07-16.md`](../../tasks/vlm/multi-model-bakeoff-plan-2026-07-16.md).

## Measured facts (this corpus, today)

| Property | 646 corpus | golden-37 |
| --- | --- | --- |
| Images | 646 | 37 |
| **Reference descriptions** | **0** (`base_caption` empty on all) | **0** |
| Curated identities | 530 named / 116 none | context packs on all 37 |
| Face-count distribution | **116 zero · 512 single · 15 two · 3 three** | mixed (trap-designed) |
| Multi-person images | **18** (2.8%) | several |
| Designed traps (easy_wrong / must_right) | **none** | 37 / 34 |
| Distinct people | 130 (76 appear on >1 image; 3 split identities) | roster-scoped |
| Text/OCR-heavy (proxy) | 136 / 640 | some |
| Provenance | **646/646 localwp (private, unpublishable)** | mock/celeb + personal |
| Frozen + versioned | no (live curation, moving) | yes (seed manifest) |

## What each corpus is actually valid for

- **646 = a coverage / latency / regression harness on realistic data.** It
  proved the pipeline ingests 646 real production uploads, weaves curated
  identities, and emits three surfaces at **p50 5.24 s/img** with a **typed,
  bounded failure rate** (6/646, now root-caused and fixed). That is genuinely
  useful and hard to fake: "does the real pipeline survive real images, how fast,
  where does it break." Keep it for that.
- **golden-37 = a name-handling correctness gate.** Its traps (easy_wrong,
  policy-disabled `maria-pool`) and closed rosters make it a real never-guess /
  insertion gate — the two-pass distractor win (0.216 → 0.081) is a valid,
  discriminating signal *on that axis*.
- **Neither measures description QUALITY** — the product's actual goal. With zero
  reference descriptions anywhere, "better descriptions" has no target to score
  against; every current metric is a proxy for *name handling* and *structure*,
  not for whether the prose is a good description.

## Where the 646 is a weak measurement (and why)

1. **No ground truth for the thing we care about [top gap].** Quality is
   unmeasured — the corpus can rank name-handling and length-band conformance but
   cannot tell you model A writes *better descriptions* than model B. The
   multi-model bake-off would produce N outputs with **nothing to score them
   against** [DIAG-03 — the success criterion isn't falsifiable without a target].
2. **Severe class imbalance.** 512/646 are single-portrait; only 18 are
   multi-person and 116 are face-free. Spatial-relation and multi-subject handling
   — where models most diverge — are **2.8% of the corpus**, so a model that is
   great at portraits and terrible at group scenes scores ~the same as one good at
   both. The instrument can't resolve the differences that matter.
3. **The rubric conflates recognition with error.** `must_right` = *every* curated
   name and any un-curated name counts against precision — so the model's
   *correct* spontaneous celeb recognition (19 verified: Bill Murray, Michelle
   Obama, …) is scored as hallucination, and the 646 `wrong_name_image_rate` 0.317
   is **not a clean quality number** (already flagged in the run report).
4. **The 116 no-identity images are ambiguous.** "No curated name" conflates
   *person-free* with *uncurated person* — so "the model named someone" can't be
   distinguished from a real hallucination vs a correct-but-uncurated name.
   Curation is incomplete, not a gold standard.
5. **Single source, single annotator, all private.** One WP tenant, one curator →
   selection bias, no inter-annotator agreement, and 646/646 unpublishable → the
   benchmark can never be a shareable/reproducible public number.
6. **Not frozen.** Live curation means the "ground truth" moves between runs, so
   two scores aren't comparable — a benchmark must be version-pinned (manifest +
   image hashes).
7. **No OCR ground truth.** 136 text-heavy images, but no verbatim reference text,
   so OCR accuracy (a primary model differentiator) is unmeasurable.

## How to make it a better measurement — ranked by impact

### 1. Add a quality-scoring mechanism (closes the top gap)

Pick per use, cheapest first:
- **Pairwise human preference** on a small sample ("which description is better,
  A or B?"). Cheapest, needs no reference text, and *directly* measures "better
  descriptions" — ideal for the model bake-off (10–50 images, ~an hour of
  labeling). Start here for model selection.
- **LLM-judge rubric** (accuracy / completeness / no-fabrication / WCAG-fit),
  scored 1–5 per axis. ALTQ deliberately deferred this ("Not-Doing: LLM-judge");
  the corpus gap is exactly where it earns inclusion. Scalable to all 646, but
  **must be calibrated** against a human-labeled seed (~50 images) before its
  numbers are trusted, and the judge model must differ from the model under test.
- **Human-written reference captions** on a frozen gold subset. Gold standard,
  enables CIDEr/BLEU-style + exact scoring, but expensive — reserve for the gold
  set, not all 646.

Recommendation: **pairwise-human for the bake-off + a calibrated LLM-judge as the
scalable quality axis**, with a ~50-image human-labeled calibration seed.

### 2. Split the instrument: coverage corpus ≠ quality gate

Stop using the raw 646 as a quality benchmark. Build a **frozen, stratified gold
set** (extend golden-37 → the planned Golden-150) that deliberately includes, in
production-matched proportions: multi-person, OCR-heavy, complex-scene,
low-light/degraded, and **designed-hard / adversarial** items (traps like
golden-37's). Score quality there; keep the 646 for coverage/latency/regression.

### 3. Fix the recognition/error rubric

Three-way name classification instead of binary: **curated-correct** /
**uncurated-unverified** (flag, don't fail — may be correct) /
**contradicts-curated** (real error). Add a **celeb allowlist** so spontaneous
public-figure recognition isn't penalized on the publishable subset, and an
explicit `recognition_disabled` flag per image. Complete the 116 no-identity
curation so "no name" is trustworthy ground truth.

### 4. Add OCR ground truth

Store verbatim in-image text for the 136 text-heavy items → measurable OCR
accuracy (edit distance / exact-match), the axis where MiniCPM-V / Qwen3-VL-8B
most differentiate.

### 5. Publishable gold subset + reproducibility

Curate a **celeb / CC0-only** publishable subset with reference captions → a
shareable, reproducible number (and a research-hub leaderboard, per RND-1). Keep
the private 646 internal-only. Version-pin every gold manifest (image sha256 +
manifest hash) so scores are comparable across runs and models.

### 6. Annotation quality

Dual-annotate a sample for inter-annotator agreement on names/boxes; dedupe the 3
split identities (the roster-person-binding work, deferred to E22) so the roster
is a clean closed set.

## Verdict

The 646 is a **good coverage/latency/regression instrument and a poor
quality-measurement instrument** — and the product goal is quality, so today the
harness cannot answer its most important question. The single highest-leverage
fix is **#1 (add a quality-scoring mechanism)**; without it the multi-model
bake-off can only be read qualitatively (eyeball the side-by-side report) rather
than scored. #2 (a stratified frozen gold set separate from the coverage corpus)
is the structural fix that makes every future comparison trustworthy. The name
metrics currently reported on the 646 should be labeled *coverage evidence, not
quality*, until #3 lands.

## Not-doing (now)

- No new large annotation effort before the bake-off — pairwise-human on the 10
  images is enough to pick a challenger.
- No change to the 646's role as the coverage corpus.
- Roster dedupe stays with E22.
