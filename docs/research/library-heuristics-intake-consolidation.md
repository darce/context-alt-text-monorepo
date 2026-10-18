# Library → Heuristics Canon Intake Consolidation

**Task**: LIBSYN-1 · **Date**: 2026-07-25 (§11 appended 2026-07-27) · **Status**: candidate manifest, not canon

Consolidates every book and paper surfaced across the library sweeps
(FIR occlusion · research-paper sweep · VLM-6 / captioning sweep · gap-closure
proposal · cross-domain bridges · photography-criticism vector) into a single
intake queue for the **private research corpus**,
`github.com/darce/heuristics-canon-research`.

> **Target repo.** All intake lands in `heuristics-canon-research`. The public
> `heuristics-canon` repo is a **projection** of it, produced by
> `tools/publish.py --public ../heuristics-canon`, and **must never be edited
> directly** — a change that lands there without a research-repo source is
> overwritten at the next cut. Nothing in this queue targets the public repo.

**This file is the complete intake instruction surface.** It carries every
title, every extraction rule, every exclusion, and every output contract the
distillation needs. Nothing else must be read to run the intake. Mechanism
briefs for the cross-domain and register work live in
[`cross-domain-bridges-and-caption-register.md`](cross-domain-bridges-and-caption-register.md);
that file is the *reasoning*, this one is the *queue*.

## 0. Boundary and authority

- Canon lives **only** in the private `heuristics-canon-research` repo, cloned
  at `/Users/daniel/Development/heuristics-canon-research`. This file is a
  *proposal*: source-registry candidates, family placements, and card
  mechanisms. It contains **no copied lexicon rows** and is not a snapshot.
- **Never write to the public `heuristics-canon` clone.** It is regenerated
  from the research repo by `tools/publish.py`; direct edits are silently lost
  and break the projection's provenance. If a change is needed publicly, make
  it in the research repo and cut a release.
- `public/reasoning/CONTRACT.md` (in the research repo — the `public/` tree is
  the projection *template*, authored privately) forbids inventing rule IDs,
  principle numbers, or source slugs. Every ID cited below as *existing* was
  read directly out of `lexicons/*.md`. Everything proposed is marked **NEW**
  and carries no ID.
- **ID assignment is tooled, not manual.** In-flight authoring claims a
  short-lived block via `tools/canon.py reserve` (`rule-reservations.json`),
  and IDs are owned by the append-only `rule-ledger.json` once promoted into a
  lexicon. Do not hand-pick an ID because a range looks free.
- Card prose, when authored, follows the 14 required sections in order and the
  WRIT style family. Nothing here is card text; it is the mechanism brief a
  card would be written from.
- **Lane names differ from lexicon filenames.** `distilled/` and
  `literature/extracted/` use short lane names: `accessibility`, `business`,
  `design`, `engineering`, `epistemics`, `graph`, `interaction`, `ml-systems`,
  `security`, `writing`. Where this file says *target lexicon*
  `design-aesthetics` / `graph-theory` / `interaction-ux` / `business-marketing`,
  the corresponding lane is `design` / `graph` / `interaction` / `business`.

## 1. Rescan result — `/Users/daniel/Documents/__research_papers/`

108 files (107 excluding `.DS_Store`), up from ~61. **27 added 2026-07-25,
18:45–19:14** — effectively the entire prior recommendation list.

| Cluster | Acquired |
|---|---|
| PEFT / adaptation | Rebuffi *Residual Adapters* · Houlsby *PEFT for NLP* · *Side-Tuning* · *LoRA* · *DoRA* · *BitFit* · *Scaling Down to Scale Up* |
| Transfer & forgetting | Yosinski *How transferable are features* · *AdaBN* · Kirkpatrick *EWC* |
| Synthetic identity | *DCFace* · *SDFR* competition · *IDiff-Face* · *Arc2Face* · *DigiFace-1M* |
| Diffusion mechanics | *DDPM* · *Classifier-Free Guidance* · *Latent Diffusion* |
| Segmentation | *Segment Anything* · *SAM 2* · *EfficientSAM* · *HQ-SAM* |
| Compositing | *Simple Copy-Paste* · *Deep Image Matting* · Porter & Duff *Compositing Digital Images* |
| Other | *LeJEPA* · (one unrelated: news-centric crossword generation) |

**Still missing, ranked by plan risk:**

1. **Statistics primaries — highest risk.** Tango 1998 (score interval for
   paired difference), Newcombe 1998 (×2), Nam 1997, Fagerland 2014, and
   Fagerland/Lydersen/Laake (CRC, 2017). FIR-7's gate implements a
   Tango/Newcombe paired score interval from these; the library currently has
   only design-level coverage (Pepe, Lohr). Paywalled — needs institutional or
   purchased access, or a vetted reference implementation to validate against.
2. **Cluster-adjusted inference.** Donner & Klar · Field & Welsh ·
   Cameron/Gelbach/Miller. Needed for the design effect and `n_eff` that set
   `δ_floor`; without them the cluster bootstrap is unvalidated.
3. **Boutros et al. 2308.04688** *Synthetic Data for Face Recognition: Current
   State and Future Prospects* — the survey that frames DCFace/IDiff-Face/
   Arc2Face against each other.
4. **MobileSAM (2306.14289)** and **SAM 3** — only if a mobile/CPU mask path is
   actually in scope. Note the exclusion in §4.
5. **ONNX / ONNX Runtime** — specifications and docs, not papers. No intake
   candidate; cite the spec version in the task plan instead.

## 2. Source-registry candidates (NEW)

Not present in `SOURCES.md` as of this session. Proposed slug · citation ·
target lexicon(s).

### 2a. Adaptation and transfer → `ml-systems` (FM, EMB, PROV)

| Proposed slug | Work | Why it earns a slug |
|---|---|---|
| `residual-adapters-multi-domain` | Rebuffi, Bilen, Vedaldi. *Learning multiple visual domains with residual adapters*. NeurIPS 2017 | The actual ancestor of FIR-7's 128→32→128 residual head. Vision, not transformer-LLM. |
| `peft-adapters-nlp` | Houlsby et al. *Parameter-Efficient Transfer Learning for NLP*. ICML 2019 | Bottleneck-adapter + near-zero init; the trainable-fraction accounting `[C-PEFT]` gates on. |
| `lora-low-rank-adaptation` | Hu et al. *LoRA*. ICLR 2022 | Low-rank delta; merge-at-inference and the rank/α trade. |
| `side-tuning-additive` | Zhang et al. *Side-Tuning*. ECCV 2020 | The frozen-base-plus-side-network form, closest to a two-session ONNX composition. |
| `catastrophic-forgetting-ewc` | Kirkpatrick et al. *Overcoming catastrophic forgetting*. PNAS 2017 | Names the failure the clean-anchor loss exists to prevent. |
| `transferable-features` | Yosinski et al. *How transferable are features in deep neural networks?* NeurIPS 2014 | Layer-depth transferability; why freezing the SFace trunk is defensible. |

*Deliberately not proposed as separate slugs*: DoRA, BitFit, AdaBN,
*Scaling Down to Scale Up*. They are variants or surveys over the same
mechanism; folding them in would produce one-card-per-paper, which
`CONTRACT.md`'s coverage policy rejects. Cite them inside the adapter card's
evidence set if the maintainer wants breadth.

### 2b. Synthetic identity generation → `ml-systems` (MLDATA)

| Proposed slug | Work |
|---|---|
| `dcface-dual-condition` | Kim, Liu, Jain. *DCFace: Synthetic Face Generation with Dual Condition Diffusion Model*. CVPR 2023 |
| `sdfr-synthetic-competition` | *SDFR: Synthetic Data for Face Recognition Competition*. FG 2024 |
| `digiface-1m` | Bae et al. *DigiFace-1M*. WACV 2023 |

Canon already carries `sface-synthetic-data` (Boutros) with MLDATA-18/19/20
covering: synthetic substitution when authentic galleries are unlawful,
measured identity-linkage before a privacy claim, and synthetic-train accuracy
not certifying deployment. **The DCFace cluster does not need new rules for
those three claims** — it needs the *generation-operations* claims those rows
do not make (identity/style separation, intra-class diversity as an explicit
knob, uniqueness collapse at scale). One card, three or four rows.

*Not proposed*: IDiff-Face, Arc2Face — cited as evidence breadth, not slugged.

### 2c. Segmentation and compositing → `ml-systems` (MLDATA), `engineering`

| Proposed slug | Work |
|---|---|
| `segment-anything` | Kirillov et al. *Segment Anything*. ICCV 2023 |
| `simple-copy-paste` | Ghiasi et al. *Simple Copy-Paste is a Strong Data Augmentation Method*. CVPR 2021 |
| `porter-duff-compositing` | Porter and Duff. *Compositing Digital Images*. SIGGRAPH 1984 |

Porter & Duff is the one that actually prevents a bug: alpha-over is
associative only under premultiplied alpha, and a naïve occluder paste at
non-premultiplied alpha leaves a dark or light fringe that a detector can
shortcut on. That is the mechanism behind the **artifact-control-arm** card in
§3. SAM 2 / EfficientSAM / HQ-SAM / Deep Image Matting are evidence breadth.

### 2d. Entity resolution and controlled vocabulary → `ml-systems`, `writing`

| Proposed slug | Work |
|---|---|
| `christen-data-matching` | Christen, Peter. *Data Matching*. Springer, 2012 |
| `werner-nomenclature-of-colours` | Syme, Patrick (after Werner). *Werner's Nomenclature of Colours*. 1821 |

Werner is the cheapest high-leverage item in the whole sweep: a closed,
pre-photographic colour lexicon with named referents. Binding descriptive
colour words to a closed vocabulary raises signal per word *and* removes a
hallucination surface, and it supplies the vocabulary source the caption
assessment's informativeness metric currently lacks. Canon already carries
`dictionary-of-color-combinations` (Wada) and `interaction-of-color`; Werner is
distinct because it is a *naming* system, not a combination or perception one.

> **Superseded in part by §11.** Werner has since been distilled, and §11
> records the vocabulary decision that follows. "Closed vocabulary" is the
> wrong frame: the source argues for referring unlisted shades *into* a
> versioned standard with public referents, never for refusing them — and the
> vocabulary that meets that bar is ISCC–NBS, not Werner itself. Read §11
> before acting on this entry or on Card C7.

### 2e. Statistics primaries → `epistemics` (MEAS, EXP), `ml-systems` (EVAL, AUDIT)

Slugs deferred until the works are actually obtained. Canon already carries
`pepe-medical-test-evaluation`, `lohr-sampling-design-analysis`,
`gustafson-misclassification`, `reinhart-statistics-done-wrong`, and
`trustworthy-controlled-experiments` — enough to author the *design* card in
§3 now, and to hold the *interval-implementation* card until Tango/Newcombe
are in hand. **Do not author an interval card from secondary descriptions.**

### 2f. Already registered — no action

`chatpid-graphrag-engineering-diagrams` · `storm-knowledge-curation-system` ·
`storm-multi-perspective-prewriting` · `graphrag-local-to-global` ·
`manning-information-retrieval` · `bruch-vector-retrieval` ·
`building-knowledge-graphs` · `rescribe-audio-descriptions` ·
`screen-parsing` · `llm-security-playbook` · `human-in-the-loop-ml` ·
`trustworthy-controlled-experiments` · `adaface` · `sface-synthetic-data` ·
`handbook-face-recognition` · `janus-benchmark-c` ·
`video-to-video-face-surveillance` · `surveillance-fiqa` ·
`nist-frvt-demographics` · `gender-shades` ·
`face-recognition-compulsory-visibility` · `computer-vision-szeliski` ·
`designing-ml-systems` · `ml-test-score` · `hidden-technical-debt-ml`.

The 27 papers dispositioned in
`docs/assessments/current/caption-context-enrichment-assessment-2026-07-05.md`
(CIAN, Whitened CLIP, RE-VLM, CoTalk, Eluvio, Ensemble Decoding, FAST-GOAL,
GRIP, PhaseWin, ImageAuditor, Williams) are **already judged** in that
assessment's §9 verdict table. Intake should read that table, not re-sweep.

## 3. Candidate reasoning cards

One causal mechanism per card, per `CONTRACT.md`. Ordered by leverage. The
"Existing IDs" column lists only IDs read directly from the canon this session;
any other cross-reference must be verified before the card is authored.

### C1 · `frozen-base-additive-delta`

**Mechanism.** When an embedding's consumers have already persisted vectors,
the cost of a change is not training cost — it is re-embedding the corpus and
invalidating every stored comparison. An additive, zero-initialised residual
path leaves the base function bit-identical at initialisation, so the
adaptation is provably a no-op until it is trained, and the un-adapted path
stays available as a control arm and a rollback.

**Predicted failure without it.** Fine-tuning the trunk silently changes the
space; old and new vectors coexist in one index and every similarity is
meaningless. Detected only as a slow accuracy rot, months later.

**Existing IDs.** `EMB-01` (one embedding space per comparison),
`EMB-05` (pin embedding and mapping versions), `DRIFT-02`.
**NEW rows.** FM family — additive-delta adaptation; trainable-fraction as a
declared budget; the zero-init identity check as a required test.
**Sources.** `residual-adapters-multi-domain`, `peft-adapters-nlp`,
`side-tuning-additive`, `lora-low-rank-adaptation`, `catastrophic-forgetting-ewc`.
**Project anchor.** FIR-7 `[C-REEMBED]`, `[C-PEFT]`, `sface-occ-adapter`.

### C2 · `synthetic-artifact-control-arm`

**Mechanism.** Synthetic occlusion is produced by compositing an occluder over
a face. Every compositing pipeline leaves a signature — alpha fringing at
non-premultiplied blend, matting halo, resampling ringing, lighting mismatch.
A model trained on it can reach the target metric by detecting the *signature*
rather than the *occlusion*, and the held-out synthetic test set carries the
same signature, so the evaluation confirms the shortcut.

**Predicted failure without it.** Masked-face recall climbs on synthetic
evaluation and does not move on real masked images. The gate passes; the
product does not improve.

**Required action.** Ship an artifact-only control arm — the same compositing
operation applied with a *non-occluding* patch (identity-preserving, e.g.
paste of the underlying pixels through the same alpha and resample path). If
the metric moves on the control arm, the gain is signature detection.
Independently, require a real-occlusion holdout that the synthetic pipeline
never touched.

**Existing IDs.** `MLDATA-09` (a filter that removes the regime under test
deletes the test), `MLDATA-10` (match training degradation to measured target
statistics), `EVAL-06`.
**NEW rows.** MLDATA family — the compositing-signature shortcut and its
control arm; premultiplied-alpha as a correctness precondition for synthetic
occlusion.
**Sources.** `simple-copy-paste`, `porter-duff-compositing`, `segment-anything`.
**Project anchor.** FIR-7 `yunet-occ` training corpus; `a_s` = 0.321 masked
synthetic recovery is currently measured *on synthetic*.

### C3 · `licence-provenance-is-transitive`

**Mechanism.** A permissively licensed wrapper does not launder the licence of
what it calls or what it was trained on. Copyleft and non-commercial terms
attach to derived outputs, and the derivation is usually invisible at the
import site — the offending dependency is two levels down, inside a package
whose own licence field reads permissive.

**Predicted failure without it.** A "fast SAM" or "fast detector" benchmark
entry pulls Ultralytics (AGPL-3.0) transitively; or a synthetic corpus is
generated by a model whose weights are non-commercial and its *outputs* inherit
the restriction. The violation ships and is discovered at commercialisation.

**Required action.** Enforce at the *registry* level, not at review: the
candidate registry (`bakeoff_candidates.yaml` and equivalents) carries a
licence field per entry, and CI refuses an entry whose transitive licence set
intersects the ban list. Record operator clearance as a dated decision, not a
comment.

**Existing IDs.** `PROV` family (verify specific row IDs before authoring),
`MLDATA-14` (capture basis is a column, not a policy page) — same mechanism,
different field.
**NEW rows.** PROV family — transitive licence closure; output-inherited
restrictions; registry-level enforcement.
**Sources.** existing canon (`llm-security-playbook`) plus project record.
**Project anchor.** FIR-7 bans Ultralytics (AGPL) and buffalo weights *and
outputs*; `dcface_operator_clearance_20260723` is the pattern for a dated
clearance. **FastSAM is built on Ultralytics YOLOv8 — it appears in every
"fast SAM" comparison table and must be excluded at registry level, not caught
in review.**

### C4 · `margin-and-design-effect-before-the-run`

**Mechanism.** A non-inferiority margin chosen after seeing the data is not a
margin; it is a description of the result. And when the evaluation units are
clustered (multiple images per subject, multiple faces per image), the
effective sample size is smaller than the row count by the design effect — so
a margin set against the row count is set against power the study does not
have. Both errors move the same direction: toward passing.

**Predicted failure without it.** The gate passes at a margin that a
correctly-sized study would have failed, and the failure is undetectable from
the report because both numbers look principled.

**Required action.** Seal the margin, the interval method, the harm direction
per floor, and the α allocation over K candidates *before* the run. Compute
`n_eff` from the measured cluster design effect and set the floor from
`n_eff`, not from row count. State the estimand as a paired difference and use
a paired interval.

**Existing IDs.** `EXP` and `MEAS` families (epistemics), `AUDIT-07` (name the
sampling frame for a population rate), `EVAL-06`, `FAIR-05`.
**NEW rows.** EXP/MEAS — pre-sealed margin; design-effect-adjusted floor;
harm-direction declaration per floor.
**Sources.** `pepe-medical-test-evaluation`, `lohr-sampling-design-analysis`,
`trustworthy-controlled-experiments`, `reinhart-statistics-done-wrong`.
**Project anchor.** FIR-7 gate: `δ_floor = max(0.02, MDE_paired(n_eff,
p_disc_prior=0.10))`, α_total 0.05 over K=3, AUDIT-11 cluster design effect.
**Hold.** The *interval implementation* (Tango/Newcombe score form) is a
separate card and must wait for the primaries — see §1.

### C5 · `signal-density-not-length`

**Mechanism.** Every length-correlated caption metric rewards more words. A
system optimised against them produces longer descriptions that a screen-reader
user must listen through linearly, at a fixed rate, with no skim. Length is a
cost paid in time by the person the feature exists for, and it is scored as a
benefit.

**Predicted failure without it.** The bake-off winner is the most verbose
candidate. Comprehension per second falls while every reported number rises.

**Required action.** Score verified facts per 100 words (or per second of
speech) alongside any quality metric, and treat length as a budget, not a free
variable. Verified means checkable against the image or a trusted source —
unverifiable specificity counts as zero, not as a fact.

**Existing IDs.** `EVAL` family, accessibility lexicon rows (verify IDs).
**NEW rows.** EVAL — signal density as a required companion metric to any
length-correlated score.
**Sources.** `rescribe-audio-descriptions`, existing accessibility sources.
**Project anchor.** VLM-6 measures no signal density at all. Cheapest fix in
the plan; see playbook §3.

### C6 · `context-obedience-is-a-separate-capability`

**Mechanism.** A model's caption quality on a bare image and its willingness to
*use injected context faithfully* are different capabilities and are not
correlated. A model can write excellent prose and quietly ignore, contradict,
or over-trust a supplied name/date/place block. Ranking candidates on the first
and deploying them into a pipeline that depends on the second selects on the
wrong axis.

**Predicted failure without it.** The bake-off winner ships, and the whole
context-assembly phase produces no measurable improvement — because the model
was never scored on whether it obeyed context.

**Required action.** Every candidate is run in two arms: no-context and
context-supplied. Score obedience explicitly — insertion of supplied facts,
non-contradiction of supplied facts, and refusal to invent facts that were *not*
supplied. A merge-only fusion contract (`units_out ⊆ units_in`) makes the last
one checkable mechanically.

**Existing IDs.** `RAG` family (verify IDs), `FM` family, `HITL`.
**NEW rows.** FM/RAG — obedience as a scored arm; merge-only fusion contract.
**Sources.** existing assessment corpus (CoTalk, RE-VLM, Eluvio) plus
`graphrag-local-to-global`, `storm-*`.
**Project anchor.** VLM-6 §13 names "CapRL's instruction obedience unknown" as
an open risk, and the plan cannot answer it as written. See playbook §3.

### C7 · `controlled-vocabulary-caps-hallucination`

**Mechanism.** Specificity and accuracy are independent. Free-form descriptive
language lets a model emit a precise-sounding word it has no evidence for
("cerulean", "Edwardian", "anxious"), and precision is what readers trust. A
closed vocabulary with named referents makes the specific word *checkable*, so
specificity stops being free.

**Predicted failure without it.** Informativeness metrics rise with
hallucination rate, because rare confident nouns score highest.

**Required action.** For attribute classes with a defensible closed set —
colour above all — bind output to a controlled vocabulary and validate the
emitted term against it deterministically. Terms outside the set are rejected
or degraded to the nearest in-set term, not passed through.

**Existing IDs.** `CAL-01` (threshold/abstention), writing-lexicon rows.
**NEW rows.** writing / ml-systems — controlled vocabulary as a hallucination
bound for attribute description.
**Sources.** `werner-nomenclature-of-colours`, `dictionary-of-color-combinations`,
`interaction-of-color`.

### C8 · `compose-at-the-boundary-before-inside-the-graph`

**Mechanism.** Two independently-exported inference graphs run as two sequential
runtime sessions have a debuggable seam: each side can be tested, versioned, and
rolled back alone. Merging them into one graph deletes the seam to buy latency
that has not yet been shown to matter, and graph-surgery failures surface as
silent numeric drift, not as errors.

**Required action.** Ship the two-session composition first. Earn the merged
graph later with a bit-parity test against the two-session reference on a fixed
input set, and keep the two-session path as the reference implementation.

**Existing IDs.** `SERVE` family, `PERF` family (engineering), `MODEL-03`.
**NEW rows.** SERVE — boundary composition before graph composition; parity
test as the merge precondition.
**Sources.** `side-tuning-additive`, ONNX/ORT specification (cited by version,
not slugged).
**Project anchor.** FIR-7 Slice 3 — **do not use `onnx.compose.merge_models`
for the first landing.** Two sequential ORT sessions; defer the merge.

## 4. Exclusions and traps

- **FastSAM / Ultralytics** — AGPL-3.0. Banned by FIR-7 and present in nearly
  every fast-segmentation comparison. Exclude at registry level (C3).
- **InsightFace / buffalo** — weights *and* outputs are non-commercial. Any
  synthetic corpus generated through them inherits the restriction.
- **Two different papers named "SFace"** are in the library: Boutros
  (privacy-friendly synthetic data, arXiv:2206.10520 — canon slug
  `sface-synthetic-data`) and the Sigmoid-constrained Hypersphere Loss paper,
  which is the one the FIR pipeline actually runs. Do not conflate them in a
  citation.
- **"Thinking with visual primitives"** is DeepSeek-AI (with Peking and
  Tsinghua), not DeepFace. No relevance to FIR occlusion; high relevance to the
  captioning path — it is the principled form of the standing rule that names
  must be bound to faces by left-to-right box order rather than emitted as a
  flat list.
- **PEFT literature is overwhelmingly transformer-LLM literature.** FIR-7's
  128→32→128 residual head is a Rebuffi/Houlsby *vision adapter*, not LoRA.
  Reading LoRA as the primary will produce rank/α advice that does not transfer.
- **Do not author the score-interval card from secondaries** (§2e).

## 5. Cross-domain bridge sources (NEW)

Domains already forced to describe images in words under an external
constraint. Full reasoning in the companion doc; the intake queue is here.

| Proposed slug | Work / body | Target lexicon | Priority |
|---|---|---|---|
| `werner-nomenclature-of-colours` | Syme (after Werner). *Werner's Nomenclature of Colours*. 1821 | `writing`, `design-aesthetics` | High — see §2d |
| `iconclass` | Iconclass iconographic classification system (Brill / RKD), continuous since the 1940s | `ml-systems` (RAG/FM), `writing` | High |
| `getty-vocabularies` | Getty Research Institute. *Art & Architecture Thesaurus*, *ULAN*, *TGN*. Open linked data | `ml-systems` (RAG), `graph-theory` | High |
| `shot-grammar-cinematography` | Standard shot-size / angle / framing taxonomy (film language) | `ml-systems`, `interaction-ux` | **Highest value-per-hour** |
| `cartographic-generalization` | Map generalization operator theory (selection, simplification, aggregation, displacement, exaggeration) | `ml-systems` (EVAL), `interaction-ux` (VIZ) | Medium |
| `heraldic-blazon` | The blazon grammar; ordering as reconstruction contract | `writing`, `engineering` (API) | Medium |
| `anti-racist-description-resources` | Archives for Black Lives in Philadelphia. *Anti-Racist Description Resources*; reparative-description literature | `accessibility`, `writing` | High |
| `dcmp-description-key` | DCMP *Description Key*; Netflix / BBC audio-description style guides | `accessibility` | **High — most actionable for register** |

`christen-data-matching` (§2d) supports the Getty/Iconclass entity-linkage
path. Canon already carries `dictionary-of-color-combinations`,
`interaction-of-color`, `rescribe-audio-descriptions`, `screen-parsing`,
`building-knowledge-graphs` — do not duplicate them.

## 6. Photography-criticism corpus — `/Volumes/Chimay/___Books/_inbox/`

The register vector (`DescriptionRegister`, cards C10 / C11). Rescanned
2026-07-26; **12 titles added 2026-07-25 20:16–20:27**, closing every gap
flagged in the prior pass except Azoulay.

### 6a. Proposed slugs

| Proposed slug | Work |
|---|---|
| `berger-ways-of-seeing` | Berger, John, and Michael Dibb. *Ways of Seeing*. Penguin, 1972 (2008 printing) |
| `berger-understanding-a-photograph` | Berger, John, ed. Geoff Dyer. *Understanding a Photograph*. Penguin Classics, 2013 |
| `berger-about-looking` | Berger, John. *About Looking*. Vintage International, 2011 |
| `sontag-on-photography` | Sontag, Susan. *On Photography*. Penguin Modern Classics, 2008 |
| `sontag-regarding-the-pain-of-others` | Sontag, Susan. *Regarding the Pain of Others*. Picador, 2004 |
| `barthes-camera-lucida` | Barthes, Roland, tr. Richard Howard. *Camera Lucida*. 2011 |
| `barthes-image-music-text` | Barthes, Roland, tr. Stephen Heath. *Image, Music, Text* — contains *Rhetoric of the Image* |
| `azoulay-civil-contract-of-photography` | Azoulay, Ariella. *The Civil Contract of Photography*. Zone Books, 2021 |

Eight slugs, not thirty. The remainder of the inbox is evidence breadth or out
of scope; see §6b–§6d. One-card-per-book is rejected by `CONTRACT.md`.

### 6b. Priority tiers — extract in this order

**Tier 1 — carries nearly all the operational content. Extract first.**

1. *Ways of Seeing* (Berger) — **the canonical text of this vector**, and newly
   present. Reproduction changes meaning; the constructed gaze; publicity.
2. *On Photography* (Sontag) — photographs are not transparent evidence.
3. *Regarding the Pain of Others* (Sontag) — the late self-revision,
   specifically on describing suffering. **Governs the gravity flag directly.**
4. *Rhetoric of the Image*, inside *Image, Music, Text* (Barthes) — anchorage
   vs relay: the theory of what a caption *does*. Extract the essay, not the
   volume.
5. *Camera Lucida* (Barthes) — studium vs punctum; the culturally-legible
   content versus the detail that pierces one viewer. This is the
   measurable-versus-conceptual split in its original terms.
6. *Understanding a Photograph* (Berger) — the most directly practical Berger.
7. *The Civil Contract of Photography* (Azoulay) — **read against Sontag, not
   after her.** Where Sontag treats the photograph as an authored artefact that
   risks aestheticising its subject, Azoulay treats photography as a civil
   relation among photographer, photographed, and spectator in which the
   photographed person is a participant with a claim, not a passive object.
   That reframing is what makes the attribution rule (§7d.2) a *right* rather
   than a stylistic preference, and it is the direct source for treating the
   depicted person as a party the description is accountable to. Its presence
   is what allows the register contract to be derived from a genuine tension
   rather than from one tradition's settled opinion.

**Tier 2 — extract if Tier 1 yields under ~25 retained claims.**

*About Looking* (Berger) · *The Shape of a Pocket* (Berger) · *Portraits*
(Berger) · *Permanent Red* (Berger) · *Selected Essays* (Berger) ·
*Confabulations* (Berger) · *Under the Sign of Saturn* (Sontag) · *Posters*
(Sontag) · *The Many Ways of Seeing* (Moore).

**Tier 3 — Barthes secondary. Extract only for the semiotic apparatus, and
only if Tier 1 leaves the anchorage/relay treatment thin.**

*Mythologies* (as *The Eiffel Tower Effect and Other Mythologies*) ·
*Système de la Mode* (a full formal grammar for describing garments in words —
structurally the closest thing in the corpus to §5's blazon entry, and worth a
look on that ground alone) · *Empire of Signs* · *Le degré zéro de l'écriture*
· *Roland Barthes by Roland Barthes*.

**Tier 4 — do not extract.** Almost nothing on description practice; high token
cost, near-zero yield. Journals, letters, poetry, correspondence, biography:
*Reborn* · *As Consciousness Is Harnessed to Flesh* · *Mourning Diary* ·
*Album* · *From A to X* · *Mural* · the Rolling Stone interview ·
*John Berger (Critical Lives)* · *Illness as Metaphor* · *On Women* ·
*Nine Ways of Seeing a Body* (somatics — the title is a false friend) ·
*Synaesthesia in Cixous and Barthes*.

### 6c. Hard exclusions

Every software title in `_inbox` is **out of scope for this vector**: all
Robert C. Martin volumes (*Clean Code*, *Clean Architecture*, *Clean Agile*,
*The Clean Coder*, *Agile Software Development*, *Designing OO C++ with
Booch*), the three *Pattern Languages of Program Design* volumes, *Patterns of
Distributed Systems*, *Implementing Effective Code Reviews*, *Clean Code in
Python*, *Scaling Python with Dask*, *Hands-On GPU Computing with Python*.
These are a separate later sweep against the `engineering` lexicon and must not
be mixed into this run.

### 6d. Acquisition status — complete

**Nothing further is outstanding.** Azoulay arrived 2026-07-25 20:34 and was
the last gap. Every Tier-1 title is present and extractable. The corpus is
closed for this intake run.

Verified extractable, no OCR required: Azoulay (31 XHTML documents, 1.6 MB of
text; the 83 MB file size is 92 embedded images), *On Photography* (single-file
EPUB). The one known OCR case is *Image, Music, Text* — see §7b.

### 6e. Required tension — do not resolve it

The corpus now contains a genuine disagreement, and the distillation must
preserve it rather than average it away. Sontag argues the photograph is an
authored artefact whose circulation can aestheticise or anaesthetise suffering;
Azoulay argues photography is a civil relation in which the photographed person
holds a standing claim on the spectator. Both bear directly on what a caption
may say about a person, and they do not reduce to one rule.

`CONTRACT.md` requires a **Tensions** table with an explicit cut. For card C10
the cut is: *the depicted person is a party the description is accountable to
(Azoulay), which is why non-visual claims are attributed to the artefact or
source rather than to them (Sontag's caution operationalised) — accountability
is discharged by attribution, not by silence.* A distillation that returns only
one side has filtered wrongly and should be rerun.

Berger sits across both and supplies the third rule (the assertable set is
bounded); Barthes supplies the vocabulary (anchorage/relay, studium/punctum).

## 7. Extraction and distillation contract

Binding for whoever runs the intake.

### 7a. Egress — non-negotiable

**Revised 2026-08-06 — the decision this paragraph deferred has now been made.**
The original rule said raw book text must not leave the laptop, because
"shipping them to a third-party inference host is a data-egress decision nobody
has made." Daniel has made it, and the bound is narrower than the original text
assumed. Two facts moved it:

1. **The lane host is not a third party.** `remote_agent.sh` dispatches into a
   sandbox on Daniel's own OCI VM. Text on that box has not left his control;
   it is the same posture as the laptop, not a disclosure to a vendor.
2. **The old rule protected nothing it claimed to.** The tree was gitignored and
   a lane is shipped by pushing its branch, which carries committed content only,
   so a lane briefed to distil a book received no book — and could not tell. The egress rule was not preventing a
   leak; it was silently producing invented distillations.

**The operative rule.** Raw book text may reach Daniel-controlled compute — this
laptop and the OCI lane sandbox — and reaches model vendors only as the
inference payload a lane necessarily sends. It must never reach the **public
projection** or any repo that is not private. `literature/extracted/` is
therefore tracked in the private research repo (since 2026-08-06) and the guard
moved from `.gitignore` to
`tools/test_publish.py::test_public_projection_carries_no_extracted_source_text`,
which asserts on bytes in the projected tree — an ignore rule holds only until
someone passes `-f`, a failing cut holds always. Extraction still runs locally,
because `extract.py` needs the shelf files, which are not in git at all.

`literature/extracted/<lane>/<slug>.txt` holds full third-party text
(research-copy-only under `RIGHTS_DEFAULT`);
`literature/extraction-manifest.json` is committed and carries **provenance
only** — slug, lane, title/creator, source basename, sha256, byte and char
counts, extractor id, date. No source text. The distillation is the publishable
artifact.

### 7b. Extraction mechanics — use the repo's tooling

Do **not** hand-roll EPUB unzipping. The research repo ships an extractor that
also records the provenance the distillation must cite:

```
python3 tools/extract.py <source.epub|pdf> --lane <lane> --slug <slug>
python3 tools/extract.py --list
python3 tools/extract.py --verify --sources <dir>     # or set CANON_SOURCE_DIR
```

Photography-criticism sources take **`--lane writing`**. Not
`--lane accessibility`: that lexicon is WCAG conformance mechanics and owns
whether a text equivalent exists, not what it may claim — see §10. If the
distillation clears the §10d threshold and a `depiction` lexicon is opened, the
lane is renamed then; extracting into `writing` first costs nothing and the
manifest records the move.

- Run `--verify` before authoring. It re-hashes each manifest source and
  reports `ok` / `DRIFTED` / `MISSING`, so an edition cannot change under a
  distillation unnoticed (`[PROV-03]`, `[GRPH-14]`). The manifest records
  **basenames only**, so point it at `/Volumes/Chimay/___Books/_inbox/` via
  `--sources` or `CANON_SOURCE_DIR`.
- **PDFs in this corpus may be image scans.** *Image, Music, Text* yields no
  extractable strings, so it needs OCR or a different edition. Check before
  budgeting time; do not assume PDF means text. (Verified separately: the EPUBs
  including Azoulay are real text.)
- Never quote at length. The distillation stores restatements, not passages —
  both a `CONTRACT.md` anti-reconstruction requirement and the reason the
  output is safe to send anywhere.

### 7c. Output contract — per retained claim

**`distilled/DISTILLATION_SPEC.md` is binding and takes precedence.** The table
below is a lane-local tightening for this corpus, not a replacement: every
distillation must still make findable the spec's required facts — Source,
Contributes, stable retrieval key, evidence body, observable trigger,
action-and-consequence, provenance, applicability and exemptions, and
**candidate disposition** (what happened to every proposed row, including the
rejected ones). The fields below map onto that skeleton; they do not shorten it.

| Field | Content |
|---|---|
| Restatement | One line, operational, imperative. Not a paraphrase of the author's prose. |
| Register(s) | Which of `FORENSIC` / `EDITORIAL` / `INTERPRETIVE` it constrains |
| Checkability | `mechanical` (grammar or counter over the output) · `judge` (requires a judge model) · `none` |
| Failure prevented | The concrete wrong output it stops |
| Source | Slug from §6a plus section pointer — must resolve to a durable anchor, not a page number |

**Discard every claim scoring `none` on checkability.** Literary appreciation
is not the deliverable, and a distillation that keeps it will bury the three
rules that matter. **Target ≈30 retained claims across the entire corpus**, not
300. If a tier yields more, the filter is too loose.

### 7d. Expected load-bearing output

The distillation should independently rediscover these three; if it does not,
the extraction filter is wrong and should be rerun before the cards are
drafted:

1. **Separate the depicted from the depiction** — claims about what was
   photographed and claims about how it was photographed are different kinds
   and must not share a voice.
2. **Attribute every non-visual claim to its bearer** — the artefact, the
   source, or the viewer; never the depicted person. Mechanically checkable.
   The single highest-value rule in the vector.
3. **The assertable set from an image alone is bounded** — everything past it
   is construction and must be sourced or dropped.

## 8. Intake sequence

0. Work in `/Users/daniel/Development/heuristics-canon-research/`. Never in the
   public projection.
1. Maintainer reviews §2, §5, §6a slugs; reserves an ID block with
   `tools/canon.py reserve` and lets the ledger own the IDs on promotion. No
   IDs are assigned in this file.
2. Author C1, C2, C3 first — each blocks live FIR-7 implementation decisions.
3. Author C5, C6 next — each blocks a VLM-6 slice that is still open and cheap
   to change.
4. C4 authored now for *design*; the interval-implementation card held pending
   the Tango/Newcombe primaries.
5. C9 (`constrained-domains-have-solved-it`) and C12
   (`quantization-delta-on-the-failure-metric`) next — C9 is the generating
   rule behind §5 and pays for itself on every future sweep; C12 gates the
   Bonsai-27B adoption decision.
6. Run the §6/§7 photography-criticism intake, then author C10
   (`attribute-claims-to-their-bearer`) from its output. **C10 is the highest-
   value card in the whole queue for user safety** — do not author it from
   these notes alone; it needs the distillation behind it.
7. C7, C8, C11, C13, C14 last — real, but none blocks a decision this week.

### C9–C14 · candidate cards (inlined — no companion read required)

C1–C8 are specified in full in §3. C9–C14 are stated here at brief depth: the
causal mechanism and the predicted failure, which is what `CONTRACT.md` needs to
open a card. Deeper argument for each lives in
`docs/research/cross-domain-bridges-and-caption-register.md`, but that read is
**optional** — no card below depends on it.

- **C9 · `constrained-domains-have-solved-it`** — when a task requires
  describing something in words, look first for a domain already forced to do it
  under an external constraint; the constraint is what produced a reusable
  vocabulary, grammar, or ordering rule. Predicted failure: reinventing a
  controlled vocabulary badly, and generating where a lookup would do. This is
  the generating rule behind §5.
- **C10 · `attribute-claims-to-their-bearer`** — every non-visual claim in a
  description is attributed to the artefact, the source, or the viewer, never to
  the depicted person. Predicted failure: the system asserts inner states,
  relationships, and significance it cannot know, in the confident register
  readers trust most. Tension cut in §6e.
- **C11 · `compression-is-selection-not-truncation`** — a short output at a
  tighter budget is a different selection under declared survival rules, not a
  truncated long one. Predicted failure: the short caption drops mandatory facts
  and keeps decorative ones, because truncation is position-based and importance
  is not.
- **C12 · `quantization-delta-on-the-failure-metric`** — an aggregate retention
  figure for a quantized model is not evidence about the metric that ranks it;
  measure the delta on the failure mode that decides adoption, stratified.
  Predicted failure: a model retaining 95% of aggregate score while losing most
  of its factual calibration is adopted on the aggregate.
- **C13 · `runtime-fork-is-part-of-provenance`** — a model requiring a vendor
  fork of the inference runtime carries that fork as a production dependency;
  the weight licence is not the whole provenance question. Extends C3.
- **C14 · `bounded-role-lets-a-small-model-be-safe`** — where a contract forbids
  introducing new facts, model capability buys fluency rather than truth, and a
  small model is correct; where capability buys truth, it is not. Predicted
  failure: one model tier chosen for the whole pipeline, over-paying at the
  fusion stage and under-paying at the captioner.

## 9. Corpus locations and completeness

### 9a. Absolute paths

| Corpus | Absolute path | State |
|---|---|---|
| Photography criticism (§6) | `/Volumes/Chimay/___Books/_inbox/` | **Closed.** 30 in-scope titles + 12 excluded software titles. Rescanned 2026-07-26. |
| Research papers | `/Users/daniel/Documents/__research_papers/` | 108 files. Complete for CV/PEFT/diffusion/segmentation; **incomplete for statistics** — see §1. |
| Book catalogue | `/Volumes/Chimay/___Books/CATALOG.md` | 1,966 lines, 72 sections. Swept; §2f lists what is already registered. |
| **Canon target** | `/Users/daniel/Development/heuristics-canon-research/` | **Private research corpus — the only write target.** `github.com/darce/heuristics-canon-research`. Outside the monorepo boundary; writes go via the maintainer. |
| Public projection | `/Users/daniel/Development/heuristics-canon/` | **Read-only.** Generated by `tools/publish.py --public ../heuristics-canon`. Never edit; edits are lost at the next cut. |
| This queue | `/Users/daniel/Development/context-alt-text-monorepo/docs/research/library-heuristics-intake-consolidation.md` | On `main`. |
| Companion reasoning | `/Users/daniel/Development/context-alt-text-monorepo/docs/research/cross-domain-bridges-and-caption-register.md` | On `main`. Optional depth — see §9c. |

Tier-1 photography titles, exact filenames under
`/Volumes/Chimay/___Books/_inbox/`:

```
Ways of seeing - based on the BBC television series directed -- John Berger; Michael Dibb -- Penguin Books for Art, 2008 -- Penguin Books Ltd -- isbn13 9780140135152 -- 8d6d01a254c3f90dced09998c57b976e -- Anna’s Archive.epub
On Photography -- Susan Sontag -- Penguin modern classics, Reissued, London, 2008 -- Penguin Classics -- isbn13 9780141035789 -- 6b0a00d96b998a8c6fa0994f4bb6a2b0 -- Anna’s Archive.epub
Regarding the Pain of Others -- Susan Sontag -- First Picador edition, New York, 2004 -- Farrar, Straus and Giroux -- isbn13 9781466853577 -- 317c1f6bd0892acd7539e3411e83159a -- Anna’s Archive.epub
Image, music, text (Barthes, Roland, 1915-1980, Heath, Stephen) (z-library.sk, 1lib.sk, z-lib.sk).pdf
Camera Lucida- Reflections on Photography -- Barthes, Roland -- 2011 -- 504c753f6934a6a8407553e8e0cb22ae -- Anna’s Archive.epub
Understanding a Photograph -- Berger, John; Dyer, Geoff; Dyer, Geoff -- Penguin classics, London, 2013 -- Penguin Books, Limited -- isbn13 9780718196011 -- 503c5cab6b4cb75220175a6e77dc96e7 -- Anna’s Archive.epub
The Civil Contract of Photography -- Ariella Azoulay -- 2021 -- Zone Books -- 2c84bfd4c0ab85c7c900417db2776f5e -- Anna’s Archive.epub
```

### 9b. Completeness statement

**This file is sufficient to run the intake.** It contains every source
candidate, every priority tier, every exclusion, the extraction mechanics, the
egress rule, and the per-claim output contract. No other project file must be
read to *execute* the distillation.

**One external read remains necessary**, and it is not a gap in this document:
the canon's own contract, all of it inside
`/Users/daniel/Development/heuristics-canon-research/` —
`public/reasoning/CONTRACT.md` (card structure),
`distilled/DISTILLATION_SPEC.md` (distillation structure), `SOURCES.md`,
`PRINCIPLES.md`, `AGENTS.md` (family routing), and the target `lexicons/*.md`.
Card sections, existing IDs, and existing slugs are defined there and must
never be invented. Unavoidable by design: this file is the *input queue*, the
research repo is the *schema*.

Everything else is now inlined. C9–C14 briefs are in §8. The companion doc is
optional depth, not a dependency.

The one deliberate pointer that stays a pointer:
`docs/assessments/current/caption-context-enrichment-assessment-2026-07-05.md`
§9, the verdict table for 27 already-dispositioned captioning papers. Copying
it here would create a second source of truth that rots. Read it *only* to
avoid re-sweeping those papers — it feeds no card in this queue, so a distiller
that skips it loses nothing but time.

Known incompleteness, already stated and not resolvable by editing this file:
the **statistics primaries** (§1) are unacquired and paywalled, which is why
the interval-implementation card is explicitly held rather than queued.

### 9c. Project-document corpus — absolute paths

Priority classes, not a reading order. **Distil P1 and P2 only unless
instructed otherwise**; P3 is listed for completeness and will mostly regenerate
rules the `engineering` lexicon already holds.

All paths below are on `main` in the root worktree
`/Users/daniel/Development/context-alt-text-monorepo/`.

**P1 — the driver (1). Send this alone if sending one thing.**

```
/Users/daniel/Development/context-alt-text-monorepo/docs/research/library-heuristics-intake-consolidation.md
```

**P1b — optional depth (3). Not required by any card in this queue.**

```
/Users/daniel/Development/context-alt-text-monorepo/docs/research/cross-domain-bridges-and-caption-register.md
/Users/daniel/Development/context-alt-text-monorepo/docs/research/arxiv-2605-27361-query2conf-applicability-2026-07-14.md
/Users/daniel/Development/context-alt-text-monorepo/docs/runbooks/fir-captioning-orchestrator-playbook.md
```

`cross-domain-bridges-and-caption-register.md` carries the long-form argument
behind the eight bridges (§5), the Bonsai/PrismML triage, and the
`DescriptionRegister` product design. The heuristics engine does not need it —
its card-relevant content is in §5 and §8 of this file. It is an artefact of
record and a design input, not an intake source. The playbook is an
implementation dispatch surface; it generates no cards. The Query2Conf note is
a single-paper applicability check already dispositioned.

**P2 — assessments that carry pipeline claims (8)**

```
/Users/daniel/Development/context-alt-text-monorepo/docs/assessments/current/caption-context-enrichment-assessment-2026-07-05.md
/Users/daniel/Development/context-alt-text-monorepo/docs/assessments/current/commercial-face-pipeline-replacement-assessment-2026-07-15.md
/Users/daniel/Development/context-alt-text-monorepo/docs/assessments/current/vector-store-and-vlm-upgrade-evaluation-2026-07-18.md
/Users/daniel/Development/context-alt-text-monorepo/docs/assessments/current/google-edge-ai-stack-evaluation-fir-2026-07-18.md
/Users/daniel/Development/context-alt-text-monorepo/docs/assessments/current/segmentation-vlm-pipeline-feasibility-2026-06-15.md
/Users/daniel/Development/context-alt-text-monorepo/docs/assessments/current/identity-prose-merge-design-2026-06-15.md
/Users/daniel/Development/context-alt-text-monorepo/docs/assessments/current/privacy-trust-and-vlm-fit-investigation-2026-06-13.md
/Users/daniel/Development/context-alt-text-monorepo/docs/assessments/current/cpu-tiered-serving-plan-2026-07-16.md
```

**P3 — remaining assessments (43), rooted at
`/Users/daniel/Development/context-alt-text-monorepo/docs/assessments/`**

`current/`: `ace-framework-usefulness-audit-2026-06-18.md` ·
`agent-skill-workflow-friction-assessment-2026-05-15.md` ·
`alt-context-dashboard-ux-assessment-2026-05-05.md` ·
`context7-usefulness-audit-2026-06-18.md` ·
`durability-gap-fixes-plan-2026-07-10.md` ·
`e15-app-refactoring-preimplementation-assessment-2026-05-06.md` ·
`gpu-availability-async-pool-adversarial-review-2026-07-16.md` ·
`identity-schema-truth-divergence-assessment-2026-07-05.md` ·
`localwp-batch-smoke-argument-plumbing-2026-05-05.md` ·
`opportunistic-gpu-provisioning-plan-2026-07-16.md` ·
`opportunistic-gpu-provisioning-plan-2026-07-16-grok-review.md` ·
`portfolio-quadrant-mvp-strategy-assessment-2026-06-11.md` ·
`public-demo-wp-plugin-launch-assessment-2026-04-30.md` ·
`python-env-unification-uv-assessment-2026-07-10.md` ·
`recognition-roster-suggestion-workflow-assessment-2026-05-05.md` ·
`remote-gate-oci-tailscale-security-assessment-2026-07-12.md` ·
`roster-dashboard-workbench-ux-assessment-2026-07-04.md` ·
`ux-ui-pass-assessment-2026-07-15.md` ·
`workbench-ui-refactor-assessment-2026-07-04.md` ·
`wp-alt-context-cross-cutting-assessment.md` ·
`wp-demo-provisioning-assessment-triage-2026-04-30.md`

top level: `README.md` ·
`clustering-pipeline-postgres-refactor-literature-2026-04-26.md` ·
`pgcache-description-service-db-read-write-assessment-2026-04-30.md` ·
`security-review-prototype-wp-alt-context-2026-07-11.md`

`archive/`: `README.md` ·
`agent-handoff-mcp-cli-vs-native-tools-investigation-2026-04-16.md` ·
`agent-performance-cold-start-compaction-tree-layout-2026-04-23.md` ·
`agent-skills-vs-spec-kit-evaluation.md` ·
`dashboard-md-vs-txt-guidance-drift-investigation-2026-04-16.md` ·
`e15-3a-br21-clustering-insert-statement-timeout-2026-04-23.md` ·
`e17-12-codex-skill-registration-discovery-2026-04-18.md` ·
`e17-13-hoisted-surface-inventory.md` ·
`infailed-sql-transaction-investigation-2026-04-09.md` ·
`infailed-sql-transaction-persistent-after-slr-2026-04-10.md` ·
`parallel-reviews-and-autonomous-debug-assessment-2026-04-16.md` ·
`review-guide-hardening-source-crosswalk.md` ·
`review-runs-tool-bridge-gap-investigation-2026-04-16.md` ·
`skill-pattern-extraction-assessment.md` · `superpowers-evaluation.md`

**Egress note.** These are project documents, not shadow-library text. The §7a
egress prohibition does **not** apply to them — they may go to remote lanes
whole. §7a governs only the book and paper corpora.

## 10. Proposed new lexicon — `depiction` (NEW)

**Photography criticism does not belong in `accessibility`.** That lexicon is
WCAG conformance mechanics: contrast floors, programmatic structure, accessible
names, reflow. Its one adjacent row, `A11Y-02`, governs *whether a text
equivalent exists and states the content's purpose* — not what the equivalent
may claim. Twenty rows about register, attribution, and the assertable set
would swamp a conformance lexicon and would fire on artifacts that have no
accessibility context at all.

**Recommendation: open a new lexicon.** Proposed name `depiction` (alternative:
`image-description`; prefer the shorter — it covers analysis as well as
description).

### 10a. Scope

Rules that fire on **an artifact that describes or interprets a depicted image
in words**. Deliberately artifact-triggered, not audience-triggered, so it
serves alt text, museum and archival catalogue records, audio-description
scripts, art-historical analysis, VLM captions, and image-dataset labels
without special-casing any of them. The art-image use is not a bonus — it is
the generality test that keeps the rules from collapsing into alt-text
folklore.

### 10b. Proposed families (NEW — no IDs, no prefix collisions with the
existing 74)

| Prefix | Covers | Feeding sources |
|---|---|---|
| `REG` | Register and voice: `FORENSIC` / `EDITORIAL` / `INTERPRETIVE`, the restrict-only gravity flag, register declared per artifact rather than inferred | Sontag (both), Azoulay, DCMP/Netflix/BBC style guides |
| `ATTR` | Claim attribution and the assertable set: what an image alone supports, who a non-visual claim is attributed to, depicted vs depiction | Azoulay, Sontag, Berger, Barthes (anchorage/relay) |
| `ICON` | Iconography and subject vocabulary: closed classification, entity binding, name-to-region binding | Iconclass, Getty AAT/ULAN/TGN, `christen-data-matching` |
| `FRAM` | Framing as meaning: shot grammar, gaze, crop, reproduction context altering sense | Berger *Ways of Seeing*, shot-grammar taxonomy |
| `SEL` | Selection under a length budget, and ordering as a reconstruction contract | Cartographic generalization, heraldic blazon |

**Colour stays where it is.** `COL` already exists in `design-aesthetics`;
Werner extends it rather than seeding `ICON`. C7's *binding rule* is a `COL`/
`ICON` row, while the *measurement* of hallucination under that binding stays
in `ml-systems` EVAL.

### 10c. Boundary cuts — state these in the lexicon header

- **vs `accessibility`** — a11y owns whether a text equivalent exists, reaches
  AT, and serves the content's purpose. `depiction` owns what it is permitted
  to say. `A11Y-02` is the handoff point and should cross-reference, not absorb.
- **vs `writing`** — writing owns prose mechanics: clarity, structure, register
  discipline in general. `depiction` owns claims about an image. A rule that
  would be true of a memo belongs in `writing`.
- **vs `epistemics`** — epistemics owns evidence and claim discipline in
  general. `depiction` rules are its image-specific instance and must **cite**
  the epistemics row, never restate it. This is the largest duplication risk.
- **vs `design-aesthetics`** — that lexicon is about *making* visual artifacts;
  `depiction` is about *reading* them.
- **vs `ml-systems`** — EVAL/CAL/FM own how caption quality is measured and how
  a model is ranked. `depiction` owns what the output must contain and may
  assert. C5 and C6 stay in `ml-systems`; C10 and C11 move here.

### 10d. The falsifiable test — decide after distillation, not before

A new lexicon earns its existence at roughly the scale of the smallest current
one (`writing`, 46 rows; `graph-theory`, 39). §7c targets ≈30 retained claims
across the whole photography corpus, and the §5 bridges should add ~10–15 more.

**If the §6/§7 run yields fewer than ~15 rows that survive the checkability
filter, do not open the lexicon** — fold them into `writing` as a `REG`/`ATTR`
family pair and revisit when the art-analysis use case actually lands. Opening
a thin lexicon that mostly cross-references `epistemics` and `writing` is worse
than a well-placed family, and `CONTRACT.md`'s coverage policy rejects it on
the same grounds it rejects one-card-per-book.

Sequence: run the distillation first (§8 step 6), count survivors, then decide.
The lane for extraction in the meantime is `writing` — it is the correct
fallback and requires no new tree.

## 11. Bound colour vocabulary — Werner's warrant, ISCC–NBS as provider

**Added and amended 2026-07-27.** Werner was acquired, extracted, and distilled
in the research repo (`distilled/design/werner-nomenclature-of-colours.md`).
That distillation changes what §2d and Card **C7** can claim, and a subsequent
live check of a machine-readable colour list changes which vocabulary C7 should
bind to. This section supersedes §2d's optimism about a "closed vocabulary",
states what Werner actually licenses, and records the provider decision:
**ISCC–NBS is the default colour vocabulary; Werner remains the warrant for the
normalisation half, not the set the contract emits.** It is a request back to
this repo, not canon.

### 11a. The two halves — one is sourced, one is not

A candidate canon rule (`FM-11`, *Closed colour identity*) proposed binding
colour to a named vocabulary **and rejecting membership outside it**. It was
retired 2026-07-26 and never published (`literature/HELD.md`). Werner was
acquired specifically to re-source it, and the answer was no.

| Half | Claim | Werner's position |
|---|---|---|
| **Rejection** | A colour term outside the set is invalid and must be refused | **Not argued.** `reject`, `refuse`, `must not`, `forbid`, `invalid`, `improper`, `inadmissible`, `ought not` return zero hits across the whole extract. The distillation's decision table records: *"No rule in this source to reject membership; author maps unknowns into the series."* |
| **Normalisation** | Free colour names are unreliable between observers; prefer a versioned standard and refer an out-of-set variety *into* it | **Directly argued.** Description is defective "when the terms used are ambiguous; and where there is no regular standard to refer to"; "the names of colours are frequently misapplied" (L00109). Method for placing an unlisted shade is comparison against the series by component parts (L00113–L00115). |

**Consequence for C7.** C7 as written in
[`fir-captioning-orchestrator-playbook.md:219`](../runbooks/fir-captioning-orchestrator-playbook.md)
says *"out-of-set terms degrade to the nearest in-set term."* That is the
normalisation half, and it **is** sourceable from Werner. The card needs no
rewrite for warrant. Only the canon's rejection-flavoured phrasing failed. The
distillation labels the operational move *refer-in, not refuse*; C7 should adopt
that wording so the two repos do not drift back toward the retired claim. The
vocabulary named on the card is a separate decision — §11c–§11d.

### 11b. The structure worth transferring is not the colour list

Werner is four layers, and the reusable one is the fourth:

1. **Name** — Werner's 79 tints, Syme's extension to 110 "standard colours" (L00111).
2. **Exemplar patch** — the printed sample. The standard is explicitly *not* a
   bare word list; it requires "proper coloured examples of the different tints"
   as the thing "to refer to" (L00109).
3. **Tri-kingdom annexes** — each tint also points at well-known objects across
   animal, vegetable and mineral kingdoms, so the name survives when the pigment
   is not at hand (L00113). Completeness is partial, by the author's own note.
4. **Component parts and referral** — the decomposition that places an unlisted
   variety *into* the series: *incline towards* / *intermediate* / *fall or pass
   into* (L00115). Modifiers plus tingeing multiply the 110 to tens of thousands
   of controlled variants without leaving the standard language (L00111–L00113).

Layer 4 is not about colour. It is the degradation rule that every controlled
vocabulary in the caption pipeline currently lacks — §1.1 Iconclass, §1.2 Getty
AAT/ULAN/TGN, §1.3 shot grammar all face the same question and none of them
answers it: **what is emitted when the observed thing is not in the set?**
Werner's answer is nearest-in-set plus the delta; never a free string, never
silence, never a rejection. That answer travels. The 110 names do not: they are
a specimen vocabulary for the photography and cataloguing lane that moved off
accessibility at `41d9f591`, not the default emission set for screen-reader
captions (§11d).

### 11c. Request — one bound-term shape in the transfer contract

The highest-value move is *not* a colour field on the description response. It
is a single term shape that every controlled vocabulary in the
`DescriptionRegister` contract (§3.3 of
[`cross-domain-bridges-and-caption-register.md`](cross-domain-bridges-and-caption-register.md))
uses identically:

| Field | Purpose |
|---|---|
| `term` | The emitted string |
| `vocabulary` | Which set it is drawn from (`iscc-nbs`, `werner`, `iconclass`, `aat`, `ulan`, `tgn`, `shot-grammar`) |
| `vocabulary_version` | Pinned; a vocabulary that cannot be versioned cannot be diffed or re-scored |
| `binding` | `exact` \| `nearest` \| `unbound` |
| `delta` | Present only when `binding: nearest` — the attributes separating the observation from the term chosen, computed per §11c-i |

`iscc-nbs` is the default colour provider (§11d). `werner` remains a permitted
value for the cataloguing and specimen lane that still wants the 1821 names; it
is not the accessibility default. Keeping both values in the enum prevents a
later second enum when that lane is wired, and makes the register choice
explicit rather than implicit in prompt text.

**`vocabulary_version` is fillable for the first time.** Under Werner the field
could not be filled honestly: there is a single 1821 edition and no version
scheme. ISCC–NBS supplies a real pin — `NBS SP 440 (1976)` (prior editions 1955,
1965). The field was unfillable for the vocabulary this section was originally
built around; the provider change is what makes the row operational.

Three reasons this belongs in the contract rather than in prompt text, matching
§3.3's own argument for the register:

- **It makes the FORENSIC clause enforceable.** §3.3 permits FORENSIC to assert
  "controlled-vocabulary colour and object terms". That is currently aspiration;
  with this shape it is a check — `unbound` must be zero in FORENSIC.
- **It makes degradation observable.** A `nearest` binding with a recorded delta
  is auditable. A model silently substituting a plausible free colour word is
  not, and that is the hallucination surface §2d wanted removed.
- **It costs one contract change now instead of a rewrite later.** Same argument
  §3.4 already makes for the register enum itself: the parameter must exist from
  the start; the behaviour can land in the next phase.

**Admission criterion for any Phase-2 vocabulary provider**, taken from Werner's
own bar (L00109): a vocabulary qualifies as *controlled* only if it is versioned
**and** every term carries a public referent. A bare word list fails. This is
worth stating in §3.3's table, because it is the test that keeps "controlled
vocabulary" from degrading into "a list someone wrote down."

**The criterion works correctly against its own first candidate.** Werner fails
both clauses of the bar §11c states: it is a single 1821 edition with no version
scheme, and §11d already concedes that its hand-coloured referents "do not
survive as text." ISCC–NBS passes both: it is versioned (NBS SP 440, 1976, with
prior editions) and every term carries a public referent (Munsell-block
membership, plus published hex and LAB centroids). Werner remains the source
that *argues* for a versioned standard with public referents (L00109 / L00113 /
L00115). It is not itself that standard. The warrant stays Werner's; the
vocabulary becomes ISCC–NBS.

| Axis the criterion states | Werner | ISCC–NBS |
|---|---|---|
| Versioned | none (single 1821 edition) | NBS SP 440 (1976); prior editions 1955, 1965 |
| Public referent | 1821 hand-coloured plate; does not survive as text | Munsell blocks, plus published hex/LAB centroids |
| Attributes without encoding decisions | prose recipes; distillation records entries are only "**typically**" number / name / composition | carried in the name itself (published modifier × hue structure of SP 440) |
| Register depth | none | nested 13 / 29 / 267 (published structure of SP 440) |

**Verified live 2026-07-27** at `https://api.color.pizza/v1/?list=nbsIscc`: 267
entries; fields per entry `name`, `hex`, `rgb`, `hsl`, `lab`, `luminance`,
`luminanceWCAG`, `bestContrast`, `swatchImg`. Spot checks: `Vivid Pink` =
`#ffb5ba`, LAB `(80.93, 28.16, 8.79)`; `Strong Pink` = `#ea9399`, LAB
`(70.28, 34.21, 11.41)`. The same endpoint also serves a `werner` list (110
entries with `hex` and `lab`, plus a per-entry `meta` object) — see the named
trap in §11d. Licence: reported CC0; licence to be confirmed from the upstream
list repository, not the API. The 13-basic / 29-intermediate / 267-block nesting
is the published structure of SP 440; the live check confirmed the 267-entry
leaf list only.

### 11c-i. How `nearest` and `delta` are computed — published centroids, not a lattice

The open question in the shape above is what `nearest` *means*. When Werner was
the candidate vocabulary the answer had to be constructed, because Werner has no
numeric layer in the text. That construction was Formal Concept Analysis over
component parts (§11c-i as first written). Two things retire it from the
`binding` path:

1. **Its premise was false even under Werner.** The first draft claimed Werner's
   component parts form "a complete binary object × attribute table, present in
   the text, requiring no encoding decisions." The distillation records that
   entries are only "**typically**" number, name, and composition — non-uniform —
   so building the formal context *is* an encoding decision. The distillation's
   own verdict on the catalogue is that it is a pure **exhibit** of a bound
   vocabulary, not a machine-ready context.
2. **Its motive is gone under ISCC–NBS.** The lattice was needed to avoid
   importing "a numeric layer Werner does not contain." For ISCC–NBS the numeric
   layer is part of the published standard: every block has a published centroid.
   `nearest` is distance to that centroid; `delta` is the modifier/hue difference
   readable straight off the name. No lattice, no lookup table to generate, no
   version-pinning of a derived artifact.

| Field | Derivation under ISCC–NBS |
|---|---|
| `binding: exact` | Observation falls inside the named block (or matches the centroid within a declared tolerance pinned next to `vocabulary_version`) |
| `binding: nearest` | Closest published centroid among the 267 blocks (LAB distance against the standard's own centroids, not a third-party digitisation) |
| `delta` | The modifier and/or hue difference between observation and chosen term, read from the two names (e.g. `Vivid Pink` → `Strong Pink`); no separate encoding table |

The FCA construction was reasonable when Werner was the only candidate: it tried
to honour the source's component-part method without smuggling in an uncited
digitisation. It is no longer the binding path. Do not generate or pin a concept
lattice for colour degradation.

**Second, weaker FCA use — do not build infrastructure for it.** Over eval
output, with captions as objects and the register's compliance predicates as
attributes (inner-state attribution present, unsourced context claim,
unattributed interpretive claim, `unbound` term, active register, gravity flag),
the Duquenne-Guigues implication basis returns a minimal non-redundant set of
implications holding with zero counterexamples. Those are failure-mode
hypotheses generated from the run rather than guessed. The caveat is real:
implications are exceptionless by definition, so noisy eval data yields few or
none, and the relaxed support/confidence version is ordinary frequent-itemset
mining with FCA only as framing. Worth one afternoon as a post-hoc diagnostic
against a real eval run; not worth a component.

**FCA does not apply to FIR.** Detection, embedding and matching are continuous,
compared by cosine — FIR-3's parity gate is `embeddings cosine ≥ 0.999`. A
formal context is binary, so applying FCA means thresholding embeddings into
attributes and discarding the metric that does the work. Roster record linkage
is a genuine formal context but is already assigned to `christen-data-matching`
(§2d); blocking plus scored comparison solves it with better tooling. Neither is
worth opening.

### 11d. Register default, provider choice, and constraints

**EDITORIAL is the default register.** The consumer of a description is a
screen-reader user. EDITORIAL is the main path, not an edge case to be handled
after FORENSIC is designed. The first draft of this section filed "110 archaic
names will hurt EDITORIAL captions" as a constraint bullet and proposed a
two-vocabulary split (Werner in FORENSIC; an unnamed "common-language colour
set" in EDITORIAL). That had the governing case backwards.

"Skimmed-milk White" is worse alt text than "pale off-white." The same objection
already made against the ~30k crowd-sourced name lists does not stop applying
because the vocabulary is old rather than crowd-sourced. Werner is a **specimen
vocabulary**: it belongs to the photography and cataloguing lane that moved off
accessibility at `41d9f591`, not on the path where users receive text.

**ISCC–NBS dissolves the split rather than staffing it.** Its nesting *is* the
register ladder — one vocabulary, three depths:

| Depth | Size | Register use |
|---|---|---|
| Basic names | 13 (published structure of SP 440) | EDITORIAL default |
| Intermediate hue names | 29 (published structure of SP 440) | EDITORIAL when a basic name underspecifies |
| Full blocks | 267 (live-verified leaf list) | FORENSIC |

The two-vocabulary split the first draft proposed is no longer needed. Same
`binding` shape, one provider, depth selected by register.

**Named trap — the color.pizza `werner` list does not give Werner a numeric
layer.** The same endpoint that serves `nbsIscc` also serves `werner` (110
entries with `hex` and `lab`). That looks like it settles the numeric-layer
objection in Werner's favour. It does not. Per-entry `meta` carries a field
`"color ids in color"` (e.g. `Reddish White` → `"1,93,9"`) that is a
**third-party encoding of Werner's component parts**, and the payload states no
source or method for either that encoding or the hex values. Adopting it would
be exactly the failure this section warns about: a digitised mapping from an
uncited source, let in unattributed — the error that retired `FM-11`, an exhibit
mistaken for an argument. The existence of a Werner hex list therefore
**strengthens** the case for ISCC–NBS rather than rescuing Werner: ISCC–NBS
centroids are published *in the standard*; Werner's hex values on that endpoint
are published by a list maintainer. Do not treat the `werner` list as a
controlled numeric layer.

Other constraints still in force:

- **Do not re-introduce rejection.** Werner does not license it, and the
  refer-in contract does not either. Out-of-set terms degrade (`nearest` +
  `delta`); they are never refused.
- **Licence of the machine-readable list is not settled by the API.** Reported
  CC0; confirm from the upstream list repository before shipping. Underlying NBS
  centroid data is US Government work, but that fact alone does not license a
  third-party packaging.
- **Numeric mapping, when used, is the standard's own.** Under ISCC–NBS, LAB
  distance against published centroids is legitimate for `binding`. Under
  Werner, any numeric mapping remains a second source that must be cited and
  versioned separately, and is never the accessibility default.

### 11e. Canon-side status — what this repo should and should not expect

| Item | State |
|---|---|
| `werner-nomenclature-of-colours` in `SOURCES.md` | **Not present.** Distilled but not promoted. |
| Rows citing Werner | **None.** |
| Distillation marking | `REFERENCE-ONLY`; must not be cited as rejection-half authority. |
| `FM-11` | Retired, never published. Stays retired. Unblocking it needs a source that argues the rejection half; Werner is not it. |
| Colour vocabulary provider | **ISCC–NBS** (`iscc-nbs`), version pin `NBS SP 440 (1976)`. Machine-readable list verified live 2026-07-27; licence to be confirmed upstream. |

What is *available* on the canon side is a different rule from `FM-11`: a
normalisation row in `design-aesthetics` `COL` — when a colour term must travel
between observers who do not share the object, name a member of a versioned
standard that carries a public referent, and refer an out-of-set variety into
the series rather than emitting a free name. Sourced at L00109 / L00113 /
L00115 (Werner's warrant). **The wording is now satisfiable:** ISCC–NBS is that
versioned standard with public referents; Werner argued for it and is not it.
Provider on the row: `iscc-nbs`. **NEW, no ID** — per §0, assignment is tooled
(`tools/canon.py reserve`), not hand-picked here. Promoting it also requires a
`SOURCES.md` entry for ISCC–NBS (and, if the warrant trail is kept explicit, for
Werner as the normalisation argument only), lifting `REFERENCE-ONLY` for the
positive half only, and leaving the `HELD.md` block on the rejection half
intact.

§10b's placement call stands: **colour stays in `design-aesthetics`**, the
bound-term rule extends `COL`, it does not seed `ICON`. Measurement of
hallucination under the binding stays in `ml-systems` EVAL. Werner may still
extend a cataloguing-side specimen path; it does not become the default
emission vocabulary.

### 11f. Not `depiction`

`depiction` governs what a description may *assert* — `ATTRIB` and `BOUND`. A
vocabulary-binding rule is about how a term is spelled and which set it comes
from, which is a different question and a different lexicon. The one honest
connection is a cross-reference, not a row: anchoring a name to a public
referent is the same move the anti-racist-description and DCMP naming rows
already do for identity terms, and Werner's tri-kingdom annex is one historical
instance of it. Note it as a cross-ref when the `depiction` rows are authored;
do not fold colour into the new lexicon.
