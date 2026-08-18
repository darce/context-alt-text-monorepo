# ALTQ-1 — Alt-Text Quality Research Findings (2026-07-14)

Synthesis of the research pass that followed the VLM-3B Slice-7b bake-off. Feeds the
ALTQ-1 task plan: eval-harness upgrades first, then generation-pipeline upgrades,
benched A/B on the golden manifest. Sources: 12 papers (4 local PDFs + 8 arXiv),
2 accessibility books, heuristics-canon lexicons (accessibility, writing), NSW gov +
Harvard HUIT guidelines, and the measured 7b head-to-head.

## 1. Where this started: the 7b quality verdict

The live A10 bake-off (`VLM-3-bakeoff-*-report.json`, 2026-07-14) showed
Qwen3-VL-30B-A3B Q4 is the only candidate honoring the name-injection contract
(gated 1.0 vs ≤ 0.222 for InternVL3.5-8B / Qwen3-VL-8B / MiMo-VL-7B-RL — smaller
models produce fluent but *nameless* captions, ignoring the injected roster context).
The winner's output still has quality defects the saturated 10-image benchmark cannot
see, e.g. the Antarctica caption's closer: "The scene captures a moment during her
2023 research residency" — meta-framing, context duplication (restates the caption
instead of describing pixels), and a ceremonial trailing clause [WRIT-13].

Current prompt (identical across candidates, `scripts/eval_harness/bakeoff.py`):
system = describe only what's visible, 2-4 sentences, context block is editorial
metadata between fenced markers, "weave the people's names … where they fit
naturally", never name anyone the context doesn't name, pixels win. User = "Write
the alt text for this image." + fenced context rendered as JSON strings. Greedy.

## 2. Convergent findings — generation pipeline

Ranked by strength of evidence; all implementable black-box (llama.cpp
OpenAI-compatible API, no training).

### 2.1 Two-pass "describe-first, ground-second" (strongest lever)

Pass 1: image only, NO context — structured objective description (people count,
positions, setting, legible text; no names, no speculation). Pass 2: image +
pass-1 description + context, prompted to weave names into the committed visual
evidence. Context can decorate but never overwrite what's visible.

- Hierarchical Multi-Modal Retrieval (arXiv:2606.18553, EVENTA'25): visual-analysis-
  first pipeline tripled CIDEr (0.039→0.123) with flat CLIPScore — context injection
  without visual-grounding loss. Drop their "contextual inference / potential
  headline" stage-1 fields (invite speculation we forbid).
- EAMA (arXiv:2402.19404): inference-time "self-supplemented generation" (extract
  entity-relevant context first, then generate) was their largest single gain
  (+2.55 CIDEr) — separable from their training.
- DFKI zero-shot study (arXiv:2408.04331): two-stage caption-then-contextualize ≈
  direct LMM (no loss from staging); focused NE context beat full-article context.
- Rule-driven captioning (arXiv:2403.05101): structured semantic rule before
  generation is the win (−6.2 CIDEr without it); our version = pass-1 JSON.

### 2.2 Face-gated name injection (our structural advantage)

Eligible names = {context-pack names} ∩ {face-service roster matches with bboxes};
inject with positional binding ("Ana, on the left in the red jacket"). Names the
face service did not confirm get hedged or omitted. Optional hard binding via
llama.cpp multi-image prompts: labeled face crops ("image 2 is Alice").

- VACNIC (arXiv:2308.08325): face-name contrastive alignment gave the biggest
  PERSON-entity precision gains — they *train* what our recognition service
  computes deterministically.
- Inserting Faces (local PDF, 2024): attention-guided name↔face grounding, 93.2%
  insertion success; names substitute the generic referent slot ("Yuri O. in an
  orange space suit", never "a man, who is Yuri, …"); ≥90%-confidence gate =
  mechanical never-guess.
- GoodNews (arXiv:1904.01475): template-then-insert decouples describe from name;
  their insertion precision was only ~9% because they *guess* the entity — ours is
  exact because roster + faces are trusted.
- BreakingNews (arXiv:1603.07141) ablation: anonymizing person names degraded
  caption-based retrieval 6× (median rank 7→42) — identity is the dominant
  information in people-photos. Validates the whole context-pack architecture.
- CIAN (local PDF): named failure mode "Entity Grounding and Narrative Integration
  Error" — described Paul Whelan as "a man in a blue shirt" despite the article
  naming him. Exactly the 8B failure we measured in 7b.

### 2.3 Context format: structured entity list beats prose

`People present: Russet Fathom (center)` as a first-class field; keep the pack
tight. EAMA: oracle entity-list (90.44 CIDEr) beat oracle sentences (87.56); whole
articles ≈ no gain; length-matched irrelevant context *hurt*. DFKI: NE context beat
full text. Both RAG papers: sentence-level, top-1 source, less-is-more.

### 2.4 Mismatch few-shot (never-guess, taught black-box)

1-2 contrastive exemplars in the fusion prompt where context names someone NOT
face-confirmed and the correct output omits/hedges them (ReCap/EVENTA'25 used a
tennis-photo/swimming-article exemplar for exactly this). Golden-manifest
easy_wrong entries are ready-made material.

### 2.5 Deterministic post-check + bounded repair

Assert output names ⊆ confirmed roster and all must-right names present; on
violation, ONE constrained text-only repair re-prompt (not full regeneration).
GoodNews template-insert inverted; ReCap "entity enricher" analog.

### 2.6 One-shot gold exemplar (deferred, cheap win available)

GRIP (local PDF): even naive CLIP-similarity retrieval of one (photo, gold alt)
exemplar beat zero-shot captioning by ~7 CIDEr; feedback-vetted selection beats
similarity. Needs a small gold set of hand-approved alt texts first — defer until
the site has some.

### 2.7 Crop-verify pass (optional hallucination guard)

Attention-guided ensemble decoding (local PDF, ICLR'25) needs logit/attention access
(not available), but its input-side finding transfers: existence/attribute claims
verified against person crops flip errors to correct; don't trust crops for counts.
Optional third pass if hallucinations ever show up in per-item review.

## 3. Convergent findings — prose style (encode in prompt v2 + rubric)

From Kalbag *Accessibility for Everyone* ch.4, Matuzovic *Web Accessibility
Cookbook* ch.3.5 (+ Léonie Watson), Williams et al. W4A'22, heuristics-canon
[A11Y-02] and WRIT rows, NSW gov guidance:

- Front-load subject + salient action in the first ~5 words; screen-reader users
  decide by the first syllables (Watson). No "photo of / image of" prefix (NSW,
  Matuzovic exemplar).
- General→specific: sentence 1 = one-line overview; then only details that are
  unusual or meaning-carrying ("a dog by a hundrastplats sign" — Kalbag).
- Complement, don't duplicate, the visible caption/title (Williams; NSW "align,
  don't contradict"). Describe what the context *doesn't* say.
- Emotion/expression/atmosphere are legitimate describable content (Watson).
- Plain prose read verbatim: short sentences, terminal periods, no keyword lists,
  no meta-framing ("the image shows", "the scene captures"), no ceremonial trailing
  clauses [WRIT-04/12/13]. Must stand alone as replacement content.
- Quality bar = purpose: "what must a non-seeing user get from this?" [A11Y-02].
  For a personal photo gallery: identity, relationship, place, moment outrank
  compositional detail.
- Williams et al. 0-4 descriptiveness scale (κ=0.91): 4 = overview + most needed
  visual content. Their data: top-rated alt averaged 117 words — completeness of
  needed content beats brevity dogma; length itself is not the criterion.

## 4. Short vs long: dual-length output (operator decision)

Community tension is real: brevity camp (NSW "a sentence or two", Harvard, WebAIM)
vs richness camp (Williams data; blind-user studies value emotion-rich description).
Resolution is the standards-sanctioned BOTH: WCAG 1.1.1 / W3C WAI images tutorial
model a short text alternative (`alt`) plus a long description in an associated
surface (`aria-describedby` / visible adjacent text / expandable).

**Operator preference (2026-07-14): longer descriptions — "they paint a better
image in the mind of the user."** Design:

- Generate long first (two-pass pipeline output, 4-8 sentences, emotion included),
  then compress to short (~≤125-char first-sentence gist, names kept) in a cheap
  text-only third call. Compression from a committed long description means the
  short can never contradict the long (NSW alignment rule, by construction).
- WordPress surfaces: short → attachment alt-text field; long → attachment
  description (figcaption/`aria-describedby` later). Plugin setting
  `alt_style: short | long | both`; `long`-in-alt is legitimate under [A11Y-02]
  purpose logic for a photo-content site.
- Contract note: `describe` response and acx-eval/v1 run-records carry a single
  `alt_text_draft` today; adding `alt_text_long` is a schema/boundary change —
  goes through contract discipline, additive/optional for back-compat.

## 5. Eval-harness upgrades (ALTQ-1 Slice 1 — build before the pipeline)

The 7b benchmark saturated (winner at 1.0 on 10 images). Unsaturate:

1. **Activate the easy_wrong wrong-name trap** (currently an inert stub in
   `caption_metrics.py`): any easy_wrong name in the caption ⇒ hard fail (gated 0).
2. **Name precision/recall + hallucinated-name rate** as first-class corpus
   metrics (every news-captioning paper's headline metric; trivial with a closed
   roster — string match, no NER).
3. **Context-distractor eval mode** (fetch-time): inject an easy_wrong name into
   the context pack; assert it is NOT woven (tests pixels-win + face-gating; EAMA
   hard-negative insight, ReCap mismatch exemplar as test).
4. **Name-ablation eval mode** (fetch-time): strip names from context; assert
   output contains zero roster names (BreakingNews ablation as a mechanical test
   of never-guess).
5. **Style axes** (deterministic): meta-framing detector, context-duplication
   ratio (n-gram overlap vs context pack), sentence-count bands, name-front-loaded
   check. Report-only signals first; promote to gates once baselined.
6. **Dual-surface scoring**: optional `alt_text_long` scored on the long rubric
   (sentence band, all name gates) while `alt_text_draft` scores as the short
   surface (gist/front-load); absent long ⇒ axes null (back-compat).
7. Run future benches on the **full 37-image golden manifest**, not the 10-image
   bakeoff subset.

## 6. Explicitly not applicable (and why)

- All training machinery: VACNIC contrastive module, EAMA alignment fine-tune,
  Rule-driven prefix-tuning/CLIP fine-tune, GoodNews LSTM — white-box, out of
  scope; A10 24 GB can't LoRA the served 30B GGUF usefully.
- Retrieval modules (DINOv2/CLIP article retrieval): our context pack is ground
  truth by construction — ReCap's private-test collapse was retrieval-induced, a
  failure mode we structurally lack.
- CIDEr length-normalization games; sampling-temperature sweeps (greedy by
  design); attention-level ensemble decoding (no logit access).

## 7. Measured baseline to beat (7b, 10-image subset, single-pass prompt v1)

| Model | Gated | Insertion | Must-right fail | s/img (tunnel) | Cold load |
| --- | --- | --- | --- | --- | --- |
| Qwen3-VL-30B-A3B Q4 | 1.0 | 1.0 | 0/8 | 4.42 | 57 s |

Bench protocol for pipeline upgrades: fresh A10 from golden image
(`acx-gpu-qwen3vl30b-golden`), 37-image manifest, configs = {single-pass v1,
prompt v2, two-pass, two-pass + face-gating}, plus distractor and ablation modes;
GPU-on budget ≤ 1 h (~$2).

## 8. Slice-3 A/B bench results & adoption decision (golden-37, A10 2026-07-16)

Four configs measured on the 37-image golden manifest against a black-box
Qwen3-VL-30B-A3B Q4 llama.cpp endpoint (A10, greedy), comparator = the
same-window **v1 baseline** [EVAL-01]. Raw + scored run-records in
`docs/tasks/altq/bakeoff-results/`; re-score is bit-identical. **Independently
cross-checked** by a remote-grok high-effort pass over the same committed JSONs,
which converged on the same winner and corrected two coordinator misreads (see
§8.7). Config-4 (two-pass + face-gate) is **not** in this matrix — golden-37
carries 0/37 `face_boxes`, so the fail-closed gate ablates every name and the
cell is vacuous; the face-weave path was exercised on the separate 646-image
interleave corpus (584 manifest face boxes, 530 named; 575 grounded in the scored
report) — see §8.6.

### 8.1 Standard mode — name-safety saturated under clean context

`meta-frame` is the **short**-surface count; `p50 s`/`×v1` are median wall-clock
(the latency-**gate** axis); `$/1k` is **mean**-derived cost (§8.4).

| config | insertion | name_prec | wrong-name | mean_gated | MR-fail | meta-frame | ctx-dup | p50 s | ×v1 | $/1k |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **v1** | 1.00 | 1.00 | 0.00 | 1.000 | 0 | 0 | 0.281 | 2.595 | 1.0× | 2.33 |
| v2 | 0.97 | 1.00 | 0.00 | 0.973 | **1** | **2** | 0.199 | 2.572 | 0.99× | 2.39 |
| two_pass | 1.00 | 1.00 | 0.00 | 1.000 | 0 | 0 | **0.125** | 5.744 | 2.21× | 5.06 |
| dual_length | 1.00 | 1.00 | 0.00 | 1.000 | 0 | 0 | 0.219 | 3.539 | 1.36× | 2.89 |

(dual_length's **long** surface carries 5 meta-framing images — the short-surface
0 above understates the product surface; see §8.6.)

With a **clean** context pack every config names people (insertion ≈ 1.0) and
names them **correctly** (name_prec 1.0, 0 wrong) — so the name-safety axes are
**saturated** and non-discriminating here [EVAL-04]; the abstention contract
[CAL-02] is exercised only under stress (§8.2). `policy_violations = 0` in every
cell (omitted). `faces.*` is transport-stubbed in the bake-off and is **not**
recognition evidence. Standard-mode signal is therefore style/latency only:
**v2 regresses** — the sole Must-Right failure in the whole matrix, +2
meta-framing images, mean_gated 1.0→0.973 — a prompt-only change that hurt with
no offsetting name gain [EVAL-08]. two_pass wins ctx-duplication (0.125) but at
2.2× latency.

### 8.2 Context-distractor mode — the discriminating name-safety test

Wrong context names injected to probe the never-guess contract [CAL-02] under
pressure.

| config | name_prec | wrong-name rate | mean_gated | meta-frame | Δ wrong-name vs v1 |
| --- | --- | --- | --- | --- | --- |
| **v1** | 0.818 | 0.216 (8/37) | 0.784 | 2 | — |
| v2 | 0.818 | 0.216 (8/37) | 0.784 | 2 | 0% (no change) |
| **two_pass** | **0.923** | **0.081 (3/37)** | **0.919** | 1 | **−62.5%** |
| dual_length | 0.900 | 0.108 (4/37) | 0.892 | 1 | −50.0% |

Prompt v2 alone buys **nothing** under distractor (identical to v1); the
describe-then-ground **structure** is what moves name-safety. two_pass is
strongest (wrong-name 0.216→0.081), dual_length close behind (→0.108). At n=37
the two_pass↔dual_length gap is a single image (3 vs 4) — within sampling noise;
do not over-rank the two on peak safety.

### 8.3 Decision-rule evaluation vs v1

Hard gates (a): halluc-rate held (0), wrong-name held-or-reduced, zero new
Must-Right failures, zero policy violations (all configs hold policy at 0).

| config | (a) hard gates | (b) improves prec/gated/long | (c) ≤2× latency (gate 5.19s) | verdict |
| --- | --- | --- | --- | --- |
| v2 | **FAIL** — the sole Must-Right failure in the matrix on standard is the hard-gate breach (+2 meta-framing is supporting, report-only); no distractor gain | no | pass (2.57s) | **eliminated** |
| two_pass | pass — wrong-name reduced, zero new MR/policy | yes (prec 0.818→0.923) | **FAIL** — 5.74s = 2.21× | pass *with explicit cost trade* |
| dual_length | pass — wrong-name reduced, zero new MR/policy | yes (prec→0.90; **ships long surface**) | **pass** — 3.54s = 1.36× | **pass, all gates** |

### 8.4 Cost/latency axis [COST-04]

Two distinct axes, deliberately on different statistics: the **latency gate** (c)
is on **median** (p50) per the decision rule, while **cost** follows the plan's
formula `instance $/hr × wall_hours ÷ images × 1000`, which is **mean**-based.
$/1k images (derived, not a stored field; A10 $2/hr × **mean** per-image
wall-clock / 3600 × 1000): v1 **2.33**, v2 2.39, two_pass **5.06** (+117%),
dual_length **2.89** (+24%). (A p50-based proxy would understate these by
1.47–1.68× because per-image latency is right-skewed.) Per-image cost is rendered
in the HTML report via `build_bakeoff_report.py --hourly-rate` / `--cost-total`
(Slice-3 tooling). Latency gate = 2× v1 p50 (2.595s) = **5.19s**.

### 8.5 Decision — detailed-tier default = **dual_length** (`--prompt-variant v2 --dual-length`)

It is the only measured config that simultaneously (1) ships **both** product
surfaces the detailed tier requires (long: 37/37 imgs, mean 78.9 words, long
name_prec 1.0, long mean_gated 1.0, sentence-band-ok 1.0), (2) clears every hard
gate vs v1, (3) improves name-safety under distractor (wrong-name 0.216→0.108,
prec 0.818→0.90), and (4) stays inside the 2× latency gate (1.36×) at +24% cost.
**two_pass** is the superior *pure* name-safety mechanism (wrong-name 0.081) but
emits no long surface and breaches the latency gate — so promoting it as the
detailed default would violate the decision rule, not apply it. Its
describe-then-ground structure is the recommended **next lever to stack onto**
dual-length (+ face-gate) in a follow-up, targeting two_pass's 0.081 wrong-name
at dual-length's surface coverage [COST-07]. Tie-break moot (dual_length uniquely
clears (c)).

### 8.6 Caveats & operator-deferred cells

- **Distractor-only signal**: standard-mode name axes are saturated, so the
  entire name-safety comparison rests on the distractor slice (n=37) [EVAL-04].
  Treat deltas as directional, not tight confidence intervals.
- **Long-surface quality debt**: dual_length's long surface carries 5 (standard)
  / 3 (distractor) meta-framing images — report-only, not a hard gate, but a
  tightening target for the long rubric.
- **Same-window**: standard cells scored @`4be31eae`; the two_pass/dual_length
  distractor cells @`c6dfc1fc` — a **docs-only** commit (eval_harness + scene are
  byte-identical between the two heads), so the comparison stays same-window.
- **Face-gate unmeasured on golden-37** (0/37 boxes → vacuous fail-closed cell);
  exercised on the 646-corpus interleave instead. Golden-37 face enrichment via
  the curation tenant is **operator-deferred**.
- **Deferred (operator-gated, real $/infra)**: fresh A10 re-run; the live
  **CPU-weave** cell (`--weave-bench` against a CPU llama.cpp T1d candidate). The
  weave + latency-summary tooling is landed and unit-tested — only the live
  endpoint execution is deferred.

### 8.7 Independent cross-check (remote-grok high-effort)

An independent grok-4.5 high-effort pass over the same committed report JSONs
(ZDR, history-stripped cwd) reached the **same** detailed-tier default
(dual_length) by the same gate logic, and caught two coordinator misreads that
are corrected above: (1) `policy_violations` is 0 in every cell (an earlier draft
mis-copied meta-framing counts into a policy column); (2) `faces.identification`
is a transport stub, so its `macro_recall` is not a valid name-recall axis and
was removed. The winner and its rationale are unchanged by both corrections.
