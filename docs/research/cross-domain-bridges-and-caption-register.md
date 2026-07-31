# Cross-Domain Bridges, Bonsai Evaluation, and Caption Register

**Task**: LIBSYN-1 · **Date**: 2026-07-25
Companion to [`library-heuristics-intake-consolidation.md`](library-heuristics-intake-consolidation.md)
and [`../runbooks/fir-captioning-orchestrator-playbook.md`](../runbooks/fir-captioning-orchestrator-playbook.md).

---

## Part 1 — Cross-domain bridges

The Werner's-Nomenclature find has a general shape worth naming, because it
predicts where the next ones are:

> **A domain that has already been forced to describe images in words under an
> external constraint — legal, archival, reproducible, or spoken-only — has
> already solved a sub-problem of alt text, and encoded the solution as a
> vocabulary, a grammar, or an ordering rule.**

The constraint is what makes the output usable. Colour naming needed
reproducibility across observers with no shared referent, so Werner produced a
closed vocabulary with named exemplars. Below, ranked by leverage, are the
other domains that have paid that price.

### 1.1 Iconclass — closed taxonomy for *what is depicted*

Art-historical iconographic classification, in continuous development since the
1940s, hierarchical, multilingual, open, with stable notation codes. It is a
controlled vocabulary for subject matter at the *conceptual* level — the layer
above object detection and below interpretation.

**Why it matters here.** Every context-injection design so far supplies
*entities* (who, where, when). Iconclass supplies *scene kinds* with stable IDs.
That converts an unbounded generative decision ("what is this a picture of?")
into a constrained classification with a checkable answer, which is the same
move Werner makes for colour. Also gives multilingual output for free.

**Actionable.** Phase 2 provider returning Iconclass codes; Phase 3 renders the
code's label rather than inventing a phrase. Deterministic, cacheable.

### 1.2 Getty vocabularies — AAT, ULAN, TGN

Art & Architecture Thesaurus (object types, materials, styles, techniques),
Union List of Artist Names, Thesaurus of Geographic Names. Open linked data
with stable URIs and documented hierarchies.

**Why it matters.** Same lever as Iconclass, scaled, and it supplies **entity
IDs** — which converts the "match a WordPress person/place to a retrieved
entity" problem from a prompting problem into a record-linkage problem with a
resolvable target. TGN in particular gives place disambiguation with no web
call.

### 1.3 Shot grammar (cinematography / film language)

Extreme long shot · long · medium long · medium · medium close-up · close-up ·
extreme close-up; plus angle (high/eye/low), and framing (single, two-shot,
group, over-the-shoulder).

**Why it matters, and why it is the cheapest item on this list.** It is a closed
vocabulary for spatial composition that is **directly computable from the face
boxes FIR already produces** — the ratio of face-box height to frame height
determines shot size almost entirely, and box count gives framing. "A
medium close-up of a woman, slightly below eye level" costs nine words and
carries more spatial information than any twenty words a VLM will generate
unprompted, with **zero hallucination risk** because it is measured, not
inferred.

**Actionable now.** A pure function over the existing detection output. No
model, no context call, no latency. It belongs in Phase 1 (visual facts,
context-free, cacheable), not Phase 3.

### 1.4 Cartographic generalization — the length-budget theory

Cartography's core problem: a 1:1,000,000 map is not a shrunken 1:10,000 map.
It is a *different selection*, produced by named operators — selection,
simplification, aggregation, displacement, exaggeration — each with rules about
what may be dropped and what must survive at any scale.

**Why it matters.** The system will need captions at several length budgets
(short alt attribute, long description, spoken AD slot). The naïve approach —
generate long, then truncate or summarise — is exactly the mistake cartography
names: the short caption is not a compressed long caption, it is a different
selection with different survival rules. Cartographic generalization is the
only mature theory of *what must survive compression* that I know of, and the
catalog already has a GIS section.

**Actionable.** Define, per length budget, which fact classes are mandatory
(persons present, primary action, safety/medical relevance) and which are
droppable (colour, material, secondary objects). That is a generalization rule
set, and it makes the multi-budget renderer deterministic instead of a second
LLM call.

### 1.5 Heraldic blazon — ordering as contract

The medieval formal grammar for describing coats of arms is strictly ordered
(field, then principal charge, then secondary, then position) and
**reconstructible**: a competent reader can redraw the arms from the text alone.

**Not a vocabulary to adopt — a design pattern to steal.** Blazon proves that
description order is part of the contract, not a style choice, and that
ordering is what makes a description reconstructible rather than merely
evocative. This generalises the standing project rule (*bind names to faces by
left-to-right box order, never a flat list*) from a one-off fix into a whole-
caption **ordering grammar**: spatial frame → persons in box order → action →
setting → sourced context. Fixed order also makes the output diffable across
models, which the multi-model fusion in Part 2 needs.

### 1.6 Archival reparative description

Archivists have spent roughly fifteen years on precisely the question in Part 3
— how to describe photographs of people without imposing the describer's frame
— and unlike the critical-theory literature they produced *rules*. The
Archives for Black Lives "Anti-Racist Description Resources" and the broader
reparative-description literature give operational guidance, of which the load-
bearing principle is:

> **Describe the record, not the subject.** Attribute framing to the artefact
> and its creator, not to the depicted person.

That one sentence is mechanically checkable and is the operational core of
Part 3. It arrives from archival practice already stripped of theory.

### 1.7 Audio description standards

DCMP Description Key, Netflix and BBC AD style guides, ACB/ADP guidance. These
are industry documents that already answer, operationally and with worked
examples, "how much interpretation is permitted," "when may a describer name an
emotion," and "what must never be described." Canon already carries
`rescribe-audio-descriptions`; the *style guides themselves* are a distinct and
more prescriptive source class.

**This is the single most actionable item for Part 3.** The philosophical
question Berger and Sontag raise has already been answered pragmatically by
people who had to ship.

### 1.8 Barthes — the missing theory book

*Rhetoric of the Image* gives **anchorage vs relay**: text that fixes an
image's meaning versus text that advances it. That is a theory of what a
caption *is*, and it maps directly onto the register scale in Part 3.
*Camera Lucida* gives **studium vs punctum** — the culturally-legible content
versus the detail that pierces the individual viewer — which is, near enough,
the measurable/conceptual split described in the request.

Not in the inbox. Should be acquired alongside the Berger/Sontag set.

### 1.9 Considered and rejected

Wine/perfume sensory vocabularies (structured but no ordering discipline worth
importing); bird-field-guide plumage topography (real, but redundant with
blazon's lesson); Schenkerian/music notation (no image bridge); forensic
description protocols (useful only as the sterile end-point of the register
scale, which §3 already provides).

---

## Part 2 — Bonsai / PrismML evaluation

### 2.1 What each collection actually is

| Collection | Base | Task | Verdict |
|---|---|---|---|
| `bonsai-image` (4B) | FLUX.2 Klein 4B | **Text-to-image generation** | **Not relevant.** Every entry is text→image. It is not a captioner and not identity-conditioned, so it does not serve the FIR synthetic-data path either (DCFace/IDiff-Face do). Value here is evidential only — see §2.3. |
| `Ternary-Bonsai-1.7B/4B/8B-gguf` | Qwen3 family | **Text-only** | **Relevant, but not as a captioner.** These are the strongest fit for the *fusion* role — see §2.4. |
| `bonsai-onnx` (1.7B/4B/8B) | Qwen3 family | Text-only, ONNX | Same role as above, in the runtime FIR already uses. |
| `bonsai-27b` | Qwen3.6-27B | **Multimodal** per the vendor announcement (262K context) | **The one real VLM candidate.** See §2.2. |

Note the trap: the collection listing implies multimodality is present only in
some artefact formats (AWQ/safetensors) and absent from the GGUF/MLX ones. That
distinction is load-bearing and the listing is not authoritative — **verify
vision capability per artefact before benchmarking**, because a text-only GGUF
of a multimodal base is useless as a captioner and will not announce itself.

### 2.2 Bonsai-27B as a VLM-6 candidate

Vendor figures: ternary 5.9 GB / 1-bit 3.9 GB footprint; 163 tok/s (1-bit) and
134 tok/s (ternary) on RTX 5090; Apache-2.0; 15-benchmark aggregate retention
95% (ternary) and 90% (1-bit) against a full-precision baseline of 85.0 →
80.5 → 76.1.

This matters because the prior VLM evaluation already selected Qwen3.6-27B as a
candidate and rejected larger models specifically because they do not fit the
A10. A **5.9 GB** ternary 27B does not merely fit the A10 — it leaves room to
hold multiple candidates resident simultaneously, which changes the economics of
the whole GPU window.

**The disqualifying risk, stated plainly.** The retention figures are
**aggregates over a 15-benchmark suite**, and the ranking discipline for VLM-6
is **hallucination-first**. A 5-point aggregate drop can be entirely
concentrated in factuality while fluency is untouched — low-bit weight
quantization is known to damage calibration far more than it damages
plausibility, and a fluent confident wrong caption is the worst output the
system can produce. This is exactly the aggregate-hiding-a-cell failure the
canon already names.

**Therefore:** admit Bonsai-27B as a candidate, and require a
**quantization-delta measurement on hallucination rate specifically**, reported
per Golden-100 difficulty stratum, against the full-precision Qwen3.6-27B on
the same corpus and prompt. Do not accept the vendor aggregate as evidence for
anything. Expect the damage, if present, to concentrate in the hard stratum.

**Second risk: runtime fork dependency.** The Q2_0 kernel is **not in mainline
`llama.cpp`** — it requires the PrismML fork. A production inference path on a
vendor fork of a runtime is a maintenance and supply-chain commitment, and it
generalises the licence-provenance card: *the licence of the weights is not the
whole provenance question; the runtime you must fork to execute them is part of
it.* Acceptable for a benchmark. Requires an explicit decision before
production. The ONNX artefacts avoid this and are the safer production shape if
they turn out to be vision-capable.

### 2.3 What `bonsai-image` is still good for

One thing only: it is independent evidence that the ternary scheme retains ~95%
of a *diffusion* model's quality on a 4B base, in a completely different
modality. That raises confidence in the method without saying anything about
where the lost 5% lands in a captioner. Read as method evidence, not as a
candidate.

### 2.4 The genuinely strong fit: ternary small models as the fusion stage

This is the part that maps directly onto the stated interest — *assembling
captions computed from different sources such as multiple models like
JoyCaption and Qwen3.6*.

The three-phase architecture puts prose composition in Phase 3, and Tier 1 of
that phase is *instructed fusion*: take structured facts from several producers
and merge them into one description under a **merge-only contract**
(`units_out ⊆ units_in`). That is a **text task**, not a vision task — which is
why the text-only ternary models are the right tool and the image models are
not.

A Ternary-Bonsai-4B at **1.02 GB** running llama.cpp NEON on the OCI A1.Flex
ARM CPU is a strong candidate for that role: it never touches the GPU, so the
fusion stage stops competing with the VLM for the burst host, and the CPU
inline tier's ≤20 s p95 budget becomes reachable for a fusion step that
currently has nowhere cheap to live.

**Critically, fusion is the stage where a small model is *safe*.** Under a
merge-only contract the model is forbidden to introduce facts, so its
hallucination surface is bounded by construction — its job is ordering,
deduplication, and prose, and the contract is mechanically checkable. Model
capability buys fluency there, not truth. This is the opposite of the captioner
role, where capability buys truth and a small model is dangerous.

**Recommendation.** Two separate, separately-scored benchmarks:

1. **Captioner benchmark** (VLM-6, GPU window): admit Bonsai-27B ternary and
   1-bit as candidates alongside full-precision Qwen3.6-27B, with the
   hallucination-delta requirement of §2.2.
2. **Fusion benchmark** (new, CPU only, no GPU window needed): Ternary-Bonsai
   1.7B / 4B / 8B, ONNX and GGUF, scored **only** on merge-contract compliance,
   ordering-grammar compliance (§1.5), signal density, and latency. Never on
   caption quality — that is the captioner's job and scoring it here would
   select for a model that rewrites rather than merges.

The fusion benchmark is cheap, needs no GPU, and can run before the GPU window.

### 2.5 Boltzmann machines and DBMs — honest assessment

**As a production architecture: no.** RBMs and deep Boltzmann machines were
superseded on every axis relevant here. Sampling-based training (contrastive
divergence) is slow and finicky, the partition function is intractable, the
layerwise-pretraining motivation evaporated with better initialisation and
normalisation, and there is no tooling path — no ONNX export story, no serving
story, no maintained implementations at the quality the rest of the stack
assumes. Adopting one would be a research project with a strong prior on a
negative result.

**As a source of a transferable idea: yes, one, and it is worth having.** The
Boltzmann-machine framing is *energy-based*: rather than generating an output
directly, define a scalar compatibility score over a joint configuration and
prefer low-energy configurations. Applied here, the multi-producer assembly
problem in §2.4 has exactly that shape — several models emit overlapping,
partly-contradictory facts, and the task is to select the jointly most coherent
subset rather than to trust any one producer.

But the correct modern tool for that is **not** a Boltzmann machine. It is the
annotator-aggregation literature: Dawid–Skene and item-response models, which
estimate per-producer reliability *and* the latent truth simultaneously from
their agreement pattern, with no ground truth required. That is the
statistically principled version of "combine JoyCaption and Qwen3.6," it has
maintained implementations, it produces a **calibrated confidence per fact**
that the merge contract can threshold on, and it connects to sources already in
canon on misclassification models and human-in-the-loop labelling.

The other live descendants are already in the stack or already rejected: modern
Hopfield networks are attention; energy-based generative modelling became
diffusion, whose primaries were acquired 2026-07-25. There is nothing left to
recover from the DBM line itself.

**Verdict.** Do not implement. Do adopt Dawid–Skene-style per-producer
reliability weighting as the fusion stage's fact-selection mechanism, which is
the thing the DBM intuition was reaching for.

---

## Part 3 — Cultural framing and the caption register

### 3.1 The problem, restated precisely

The stated intuition is right but underspecified: *the captioning LLM can be
prompted to be steered into a direction the system uses.* It can. The failure
mode is doing it as **prompt style**, because a style instruction is
unversioned, unscored, silently model-dependent, and degrades invisibly when the
model changes. Under low-bit quantization (§2.2) style adherence is among the
first things to go, and nothing in the pipeline would notice.

The fix is to make the cultural stance a **typed contract parameter with a
scored evaluation arm**, not a paragraph of prompt.

### 3.2 What Berger and Sontag actually contribute, operationally

Reading them for aesthetics yields nothing implementable. Reading them for
*constraints on description practice* yields three, and all three are
mechanically checkable.

**One — separate the depicted from the depiction.** Sontag's central claim in
*On Photography* is that a photograph is not transparent evidence: it carries
the photographer's framing, selection, and moment, and treating it as a window
launders an authored artefact into fact. Operationally: a caption makes two
distinct kinds of claim — about *what was photographed* and about *how it was
photographed* — and they must not be blended into one voice. §1.3's shot
grammar is precisely the vocabulary for the second kind, which is why that item
is cheap and this one is not merely theoretical.

**Two — attribute every non-visual claim to its bearer.** This is the archival
principle from §1.6 arriving independently. A caption may say the photograph is
composed a certain way, or that a source records a name; it may not say the
depicted person *is* anything not visible, and above all may not narrate their
inner state. "A woman looks anxious" is an assertion about a person the system
cannot make; "her brow is furrowed" is a visual fact; "the photograph is framed
to isolate her" is a claim about the artefact. All three are describable; only
the first is forbidden. **This single rule prevents most of the harm Sontag
names, and it is checkable by grammar over the output.**

**Three — the caption constructs the meaning, so its bounds are a design
decision.** Berger's recurring argument is that a photograph is ambiguous
without its before-and-after, and words supply the missing narrative — meaning
is not recovered from the image, it is constructed by the text. Operationally:
the set of assertable facts from an image alone is *bounded*, and everything
beyond it must be sourced from Phase 2 or dropped. Barthes' anchorage/relay
(§1.8) is the same claim with better terminology and belongs in the same
distillation.

Notably, none of the three requires the model to be *told about* Berger or
Sontag. They are contract clauses.

### 3.3 Proposed design — `DescriptionRegister`

A typed enum on the description request, chosen by the **operator or tenant**,
never by the model, and never inferred from the image.

| Register | May assert | Must not |
|---|---|---|
| `FORENSIC` | Visually verifiable facts only; measured spatial/shot grammar; controlled-vocabulary colour and object terms | Any affect, relationship, occasion, intent, or cultural significance. No sourced context. |
| `EDITORIAL` *(default)* | Everything in FORENSIC, plus Phase-2 sourced context: names, place, date, event, with source precedence | Any inner-state attribution to a depicted person. Any unsourced context. |
| `INTERPRETIVE` | Everything in EDITORIAL, plus explicit claims about the *artefact* — framing, composition, genre, iconographic classification from a controlled vocabulary (§1.1) | Still no inner-state attribution. Every interpretive claim must be syntactically attributed to the photograph or a named source, never to the subject. |

Plus an orthogonal **gravity** flag, derived from detected sensitive content,
which may only **restrict** the active register — never expand it. A monotone
restriction is safe under model substitution; a monotone expansion is not.

Three properties make this worth building rather than prompting:

- **It is versioned and diffable.** A register is data; a prompt paragraph is
  not.
- **It is scoreable.** Register compliance becomes an eval arm: count
  inner-state attributions (must be zero in all registers), count unsourced
  context claims (must be zero outside INTERPRETIVE), count unattributed
  interpretive claims. Add it to the obedience arm already proposed for VLM-6.
- **It survives model change.** When a candidate wins the bake-off, or a model
  is swapped for a quantized variant, compliance is re-measured rather than
  re-hoped-for.

### 3.4 Phasing — what lands when

The parameter must exist in the contract from the start or adding it later is a
rewrite of every call site. The *behaviour* can land much later.

- **Now, cheap, additive.** The `DescriptionRegister` enum in the request/
  response contract, defaulting to `EDITORIAL`; the gravity flag as
  restrict-only; the inner-state-attribution counter in the eval harness (it is
  a scored metric even with a single register, and it is the highest-value
  safety signal in the whole caption pipeline). Shot grammar (§1.3) as a pure
  function over existing FIR face boxes — Phase 1, deterministic, no model.
- **Next phase.** FORENSIC and EDITORIAL enforced end to end; register
  compliance as an eval arm alongside context obedience; controlled colour
  vocabulary (Werner) and controlled object/scene vocabulary (Iconclass, Getty)
  wired as Phase-2 providers; ordering grammar (§1.5) as the Phase-3 contract.
- **Later phase, as anticipated.** INTERPRETIVE, with attribution enforcement,
  the cartographic length-budget selection rules (§1.4), and the register
  choice surfaced to tenants as a setting.

### 3.5 Ingestion plan for the inbox

**Scope.** The Berger and Sontag titles plus the two adjacent works. Explicitly
**excluded**: every Robert C. Martin title, the pattern-language volumes, the
Dask/GPU/Python titles, and the code-review book — different vector, later.

In scope, present in `_inbox`:
*On Photography*, *Under the Sign of Saturn*, *Illness as Metaphor*, *On
Women*, *Posters*, the Rolling Stone interview, the journals (*Reborn*, *As
Consciousness Is Harnessed to Flesh*) — Sontag; *Understanding a Photograph*,
*Portraits*, *The Shape of a Pocket*, *Permanent Red*, *Confabulations*,
*Selected Essays*, *Photocopies*, *And Our Faces, My Heart, Brief as Photos*,
*Hold Everything Dear*, *From A to X*, *Mural*, the Merrifield critical
biography — Berger; plus *The Many Ways of Seeing* (Moore) and *Nine Ways of
Seeing a Body* (Reeve).

**Priority order — the first four carry nearly all the operational content:**
*On Photography* · *Understanding a Photograph* · *The Shape of a Pocket* ·
*Portraits*. The journals, letters, and poetry (*From A to X*, *Mural*,
*Reborn*, *As Consciousness…*) contain almost nothing about description
practice; extract last or not at all.

**Missing and worth acquiring** — three of the four most directly relevant works
in this vector are absent:

- Berger, *Ways of Seeing* — **the canonical one.** Its arguments about
  reproduction changing meaning, and about the constructed gaze, are the most
  directly applicable text in the entire vector, and it is not in the inbox.
- Sontag, *Regarding the Pain of Others* — the late revision of *On
  Photography*, specifically about describing images of suffering. Directly
  governs the gravity flag.
- Berger, *About Looking*.
- Barthes, *Camera Lucida* and *Rhetoric of the Image* (§1.8).
- Azoulay, *The Civil Contract of Photography* — the strongest counter-position
  to Sontag, worth having so the distillation is not single-voiced.

**Extraction is local, and must stay local.** The EPUBs are single-file
archives; stdlib `zipfile` extracts them with no dependencies — verified this
session against *On Photography*. Note that **these files must not be shipped
to a third-party VM for processing.** They are copyrighted books from a shadow
library; sending them to an external inference host is a data-egress decision
nobody has made, and it is avoidable at zero cost since extraction and chunking
run fine on the laptop. Distillation of the *extracted operational claims* —
short restatements, not source text — can go to remote lanes safely; the raw
book text should not.

**Distillation output contract.** Per extracted claim: a one-line operational
restatement · the register(s) it constrains · a checkability verdict
(mechanically checkable / requires a judge model / not checkable) · the failure
it prevents. **Discard anything not checkable** — literary appreciation is not
the deliverable, and a distillation that keeps it will drown the three rules in
§3.2 that actually matter. Target is on the order of 30 retained claims across
the whole corpus, not 300.

---

## Consolidated next actions

| # | Action | Cost | Blocks |
|---|---|---|---|
| 1 | Shot grammar as a pure function over FIR face boxes (§1.3) | Hours | Nothing. Highest value-per-hour item in this document. |
| 2 | Inner-state-attribution counter in the eval harness (§3.4) | Hours | Nothing. Highest-value safety signal. |
| 3 | `DescriptionRegister` enum + restrict-only gravity flag in the contract (§3.3) | Small | Must precede Phase-3 work or it becomes a rewrite. |
| 4 | Fusion benchmark: Ternary-Bonsai 1.7B/4B/8B, CPU only, merge-contract scoring (§2.4) | Small, no GPU | Can run before the GPU window. |
| 5 | Admit Bonsai-27B to VLM-6 **with** the hallucination-delta requirement (§2.2) | Fits existing window | Verify vision capability per artefact first. |
| 6 | Local extraction + distillation of the four priority titles (§3.5) | Small | Feeds the register contract. |
| 7 | Acquire *Ways of Seeing*, *Regarding the Pain of Others*, Barthes, Azoulay | Operator | The distillation is thin without them. |
| 8 | Iconclass / Getty AAT as Phase-2 providers (§1.1, §1.2) | Medium | Later phase. |
| 9 | Cartographic length-budget selection rules (§1.4) | Medium | Later phase; needs multi-budget rendering first. |

## Candidate reasoning cards added to the intake queue

Extending the eight in the consolidation manifest:

- **C9 · `constrained-domains-have-solved-it`** — when a task requires
  describing something in words, look first for a domain already forced to do
  it under an external constraint; the constraint is what produced a reusable
  vocabulary, grammar, or ordering rule. Predicted failure without it:
  reinventing a controlled vocabulary badly, and generating where a lookup
  would do.
- **C10 · `attribute-claims-to-their-bearer`** — every non-visual claim in a
  description is attributed to the artefact, the source, or the viewer, never
  to the depicted person. Predicted failure: the system asserts inner states,
  relationships, and significance it cannot know, in the confident register
  readers trust most.
- **C11 · `compression-is-selection-not-truncation`** — a short output at a
  tighter budget is a different selection under declared survival rules, not a
  truncated long one. Predicted failure: the short caption loses the mandatory
  facts and keeps the decorative ones, because truncation is position-based and
  importance is not.
- **C12 · `quantization-delta-on-the-failure-metric`** — an aggregate retention
  figure for a quantized model is not evidence about the metric that ranks it;
  measure the delta on the failure mode that decides adoption, stratified.
  Predicted failure: a model that retains 95% of aggregate score while losing
  most of its factual calibration is adopted on the aggregate.
- **C13 · `runtime-fork-is-part-of-provenance`** — a model that requires a
  vendor fork of the inference runtime carries that fork as a production
  dependency; the weight licence is not the whole provenance question.
  Extends C3.
- **C14 · `bounded-role-lets-a-small-model-be-safe`** — where a contract
  forbids introducing new facts, model capability buys fluency rather than
  truth, and a small model is the correct choice; where capability buys truth,
  it is not. Predicted failure: one model tier is chosen for the whole
  pipeline, over-paying at the fusion stage and under-paying at the captioner.
