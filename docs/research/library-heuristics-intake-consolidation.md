# Library → Heuristics Canon Intake Consolidation

**Task**: LIBSYN-1 · **Date**: 2026-07-25 · **Status**: candidate manifest, not canon

Consolidates every book and paper surfaced across the library sweeps
(FIR occlusion · research-paper sweep · VLM-6 / captioning sweep · gap-closure
proposal · cross-domain bridges · photography-criticism vector) into a single
intake queue for `github.com/darce/heuristics-canon`.

**This file is the complete intake instruction surface.** It carries every
title, every extraction rule, every exclusion, and every output contract the
distillation needs. Nothing else must be read to run the intake. Mechanism
briefs for the cross-domain and register work live in
[`cross-domain-bridges-and-caption-register.md`](cross-domain-bridges-and-caption-register.md);
that file is the *reasoning*, this one is the *queue*.

## 0. Boundary and authority

- Canon lives **only** in the private `heuristics-canon` repo. This file is a
  *proposal*: source-registry candidates, family placements, and card
  mechanisms. It contains **no copied lexicon rows** and is not a snapshot.
- `reasoning/CONTRACT.md` forbids inventing rule IDs, principle numbers, or
  source slugs. Every ID cited below as *existing* was read directly out of
  `lexicons/*.md` this session. Everything proposed is marked **NEW** and
  carries no ID — IDs are assigned by the canon maintainer at intake.
- Card prose, when authored, follows the 14 required sections in order and the
  WRIT style family. Nothing here is card text; it is the mechanism brief a
  card would be written from.

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

Seven slugs, not thirty. The remainder of the inbox is evidence breadth or out
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

### 6d. Still to acquire

**Azoulay, Ariella. *The Civil Contract of Photography*** — the strongest
counter-position to Sontag. Without it the distillation is single-voiced, and a
register contract derived from one critical tradition will encode that
tradition's blind spots as system behaviour. This is the last real gap.

## 7. Extraction and distillation contract

Binding for whoever runs the intake.

### 7a. Egress — non-negotiable

**Raw book text must not leave the laptop.** These are copyrighted works from a
shadow library; shipping them to a third-party inference host is a data-egress
decision nobody has made, and it is avoidable at zero cost. Extraction,
chunking, and claim identification run locally. **Distilled claims** — one-line
operational restatements, no source prose — may be sent to remote lanes for
clustering and card drafting.

### 7b. Extraction mechanics

- EPUBs are single-file archives; stdlib `zipfile` opens them with no
  dependencies. Verified against *On Photography* — two HTML documents, whole
  book in `index.html`.
- **PDFs in this corpus may be image scans.** `Image, Music, Text` yields no
  extractable strings, so it needs OCR or a different edition. Check before
  budgeting time; do not assume PDF means text.
- Never quote at length. The distillation stores restatements, not passages —
  this is both a `CONTRACT.md` anti-reconstruction requirement and the reason
  the output is safe to send anywhere.

### 7c. Output contract — per retained claim

| Field | Content |
|---|---|
| Restatement | One line, operational, imperative. Not a paraphrase of the author's prose. |
| Register(s) | Which of `FORENSIC` / `EDITORIAL` / `INTERPRETIVE` it constrains |
| Checkability | `mechanical` (grammar or counter over the output) · `judge` (requires a judge model) · `none` |
| Failure prevented | The concrete wrong output it stops |
| Source | Slug from §6a plus section pointer |

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

1. Maintainer reviews §2, §5, §6a slugs; assigns IDs. No IDs are assigned in
   this file.
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

**Card index.** C1–C8 in §3 of this file. C9–C14 in the companion doc's final
section: C9 `constrained-domains-have-solved-it` · C10
`attribute-claims-to-their-bearer` · C11 `compression-is-selection-not-truncation`
· C12 `quantization-delta-on-the-failure-metric` · C13
`runtime-fork-is-part-of-provenance` · C14 `bounded-role-lets-a-small-model-be-safe`.
