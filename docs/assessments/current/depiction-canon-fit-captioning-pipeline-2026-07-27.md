# Depiction-Canon Fit — Captioning Pipeline

> **Metadata**
>
> - **Date**: 2026-07-27
> - **Subject**: `apps/prototype-description-service` — the **captioning** path
>   (two-pass VLM generation + prompt registry + caption eval harness).
>   The FIR/bake-off harness is in scope only where captioning depends on it.
> - **Canon**: heuristics-canon-research `v0.17.2` @
>   `4e099ded65ee33bc4db85dfd4c65409a0087a752` (INDEX.md: 1143 rules across
>   11 lexicons), including `lexicons/depiction.md` (15 rules:
>   `ATTRIB-01..10`, `BOUND-01..05`), the `distilled/depiction/` and
>   `distilled/accessibility/` source distillations, and `public/reasoning/`
>   cards.
> - **Supersedes the captioning half of**:
>   `docs/assessments/current/omg-spec-fit-fir-captioning-pipelines-2026-07-26.md`
>   (that document evaluated OMG *specifications* against the FIR harness; this
>   one evaluates the *captioning pipeline* against the depiction canon —
>   different question, different corpus).
> - **Status**: evaluation only. No code changed, no gate decision made.

---

## 0. Why "System C"? — the label is retired

In the earlier three-repo evaluation I labelled the repositories A / B / C to
keep a comparison table narrow. There was no meaning in the letters and no
scheme behind them: **A** was `agentic-protocol-monorepo` (WorkBay), **B** was
`heuristics-canon-research`, **C** was this repository,
`context-alt-text-monorepo`. It was my own shorthand, it obscured rather than
compressed, and it does not appear again in this document or any successor.
Repositories are named.

---

## 1. What this evaluation is

The captioning pipeline generates prose *about people who did not choose to be
described*, for readers who **cannot cross-check it against the picture**. That
combination is the entire subject of the canon's new `depiction` lexicon. Until
2026-07-26 those rules lived inside `writing.md` and read as prose-hygiene; they
have now been split out on the argument that a rule about *what a text may claim
about something outside itself* is a different kind of rule from one about how
prose reads.

This evaluation asks one question: **where does this pipeline assert more than
it can warrant, or assert it in the wrong voice** — and for each answer, which
of the pipeline's real surfaces could hold the constraint.

### 1.1 The eight enforcement points

Every finding below lands on exactly one of these, or is honestly marked
unenforceable. This vocabulary is the spine of the document and of the
machine-readable block in §7.

| Token | Meaning |
|---|---|
| `system_prompt` | Text in the pass-1 / weave / compress system prompts |
| `output_schema` | A field, enum, or required key in the structured JSON |
| `decode_constraint` | llama.cpp GBNF grammar-constrained sampling or a logit constraint. Mechanical; cannot be talked out of; expensive to design |
| `post_generation_check` | A deterministic pass over generated text before it ships |
| `context_pack_input` | A field the CMS must supply, or a rule on what the pack may carry |
| `eval_metric` | A scored signal in the offline harness (gate or report-only) |
| `human_gate` | Routed to a person; the machine refuses to decide |
| `not_enforceable` | The claim is real but no machine surface can carry it |

`not_enforceable` is a real verdict, not a failure. Four findings use it.

---

## 2. The convergence finding — read this first

**This repository proposed the model the canon then shipped.**

`docs/research/cross-domain-bridges-and-caption-register.md` (LIBSYN-1, commit
`82c5f56a`, 2026-07-25) did two things:

1. It derived three operational constraints from Berger and Sontag — separate
   the depicted from the depiction; attribute every non-visual claim to its
   bearer; the assertable set from an image alone is bounded — and proposed a
   typed `DescriptionRegister` enum (`FORENSIC` / `EDITORIAL` / `INTERPRETIVE`)
   to carry them.
2. It nominated four candidate reasoning cards, among them **C10
   `attribute-claims-to-their-bearer`**.

One day later the canon shipped `lexicons/depiction.md` and the reasoning card
`attribute-claims-to-their-bearer` — whose *Required action* is written in the
FORENSIC / EDITORIAL / INTERPRETIVE vocabulary and which cites `ATTRIB-01..05`
and `BOUND-01..05` by ID.

The practical consequence is more limited than "canon shipped our enum":

> `DescriptionRegister` remains a **local design choice** (LIBSYN-1 §3.3). No
> `REG-*` family exists at v0.17.2 (prefix grep of definition anchors across
> `lexicons/` → zero). The card uses FORENSIC / EDITORIAL / INTERPRETIVE
> *vocabulary* and warrants its Required action with `ATTRIB-01..05` /
> `BOUND-01..05`, so the *behaviours* can cite rule IDs, but the enum itself
> is not a consumer implementation of a lexicon family and must not be reviewed
> as canon compliance (matches triage §5b: contract-shape, not a `REG-xx` row).

**Fifteen depiction rules at the definition anchors** (`grep -E
'^\| (ATTRIB|BOUND)-[0-9]+<a name=' lexicons/depiction.md` → 15:
`ATTRIB-01..10`, `BOUND-01..05`). LIBSYN-1's three constraints map onto four of
them (`ATTRIB-01`, `ATTRIB-03`, `BOUND-01`, `BOUND-02`). The **eleven
unanticipated** rows (15 − those four) with no counterpart in this repository's
design or code are: `ATTRIB-02`, `ATTRIB-04`, `ATTRIB-05`, `ATTRIB-06`,
`ATTRIB-07`, `ATTRIB-08`, `ATTRIB-09`, `ATTRIB-10`, `BOUND-03`, `BOUND-04`,
`BOUND-05`. Findings F1–F9 draw on that set (F9 also uses the compression
reasoning card, which is not a depiction-lexicon row).

---

## 3. Findings

Ranked by value, not by severity. Each carries the canon rule IDs, the
enforcement point, and how it was verified.

### F1 — The context pack can launder *oppressive* creator wording into the model's voice

**Rules**: `ATTRIB-07` (B·d) — **oppressive creator wording only**
**Enforcement point**: `context_pack_input` (primary), `output_schema` (secondary)
**Verified**: in code, `apps/prototype-description-service/scene/infrastructure/vlm/gpu_remote_adapter.py`

The context pack carries CMS-authored strings — the existing `alt`, the
`caption`, `taxonomy_terms`, the post `title` and `excerpt`. `_render_context`
renders each as `key: "<json-escaped value>"`, and its own docstring states the
purpose of the escaping: *"so multi-line or `- `-prefixed content cannot dissolve
the key structure."* That is a **prompt-injection defence** — it protects the
structure of the block. It does nothing to mark the values as *another party's
speech*.

`_user_text` then labels the block `Context block (editorial metadata only)`,
and `_SYSTEM_PROMPT` instructs:

> "Weave the people's names and factual details it supplies into the description
> where they fit naturally."

*Weave* and *fit naturally* dissolve the seam. When the CMS string is **racist
or otherwise oppressive creator language**, it can emerge in the machine's
unmarked voice — the Failure `ATTRIB-07` names (oppressive creator wording
carried into published description with nothing to distinguish it from the
institution's own words). Fix: quote / scope-note / processing-note; never
leave those terms unmarked in describer-supplied fields.

**Warrant scope.** `ATTRIB-07` covers **only** oppressive creator wording, not
all unmarked creator speech. No v0.17.2 lexicon row requires voice-tagging
creator speech in general; a non-oppressive phrase absorbed unmarked is an
engineering seam risk, not an `ATTRIB-07` violation. A4BLiP (L00552–L00554)
states the oppressive case and a verification recipe this pipeline cannot run:
every public string with creator racist language quoted or voice-tagged;
describer notes grepped against creator folder-title lexicon for unmarked reuse.

**Recommendation.** Typed `voice: creator | catalogue | operator | derived` on
each context field (`extra="forbid"` keeps it closed). Creator-tagged fields
are quotable-only. That design is **broader** than `ATTRIB-07` (all creator
fields, not only oppressive ones); the canon blocker is the oppressive subset.
Breadth is defence-in-depth, not a second rule ID.

### F2 — `_PROMPT_V2_SYSTEM` licenses the exact claim `ATTRIB-01` blocks

**Rules**: `ATTRIB-01` (B·d), `ATTRIB-03` (S·d)
**Enforcement point**: `system_prompt`
**Verified**: in code, `apps/prototype-description-service/scripts/eval_harness/bakeoff.py` (`_PROMPT_V2_SYSTEM`, "Facial expressions, emotion, and atmosphere are worth describing.")

The v2 prompt instructs:

> "Facial expressions, emotion, and atmosphere are worth describing."

`ATTRIB-01` is a **blocker**: where face or pose invites an interior or will
inference, the description must *state visible cues only*, **or** attribute the
reading to a viewer, a convention, the artefact, or a named source — never make
the depicted person the fact-owner. LIBSYN-1 §3.2 had already drawn this line
precisely: *"'A woman looks anxious' is an assertion about a person the system
cannot make; 'her brow is furrowed' is a visual fact."*

The prompt bundles the two together. "Facial expressions" is a visible cue and is
fine. "Emotion" is an inner state and is not. Nothing downstream separates them:
there is **no inner-state or affect detector anywhere in
`apps/prototype-description-service/scripts/eval_harness/`** (verified by grep —
the module has `score_hallucination`, `fabricated_fact_rate`,
`_context_trigram_overlap` and a meta-framing detector, and nothing that looks at
attribution).

**This is a documented internal tension, not an oversight.** The comment above
the prompt cites the ALTQ-1 research findings — *"emotion legitimate"* — and
Williams et al. support that emotion carries genuine access value for a
non-seeing reader. The canon does not dispute it. Following the distillation
spec's own rule — **"Register, not silence… deletion is the fallback, not the
default"** — the resolution is not to strip emotion but to **move it to an
attributed voice**, which is `ATTRIB-01`'s own second branch.

**Recommendation.** Keep emotion; give it a bearer. "She looks anxious" or "her
expression reads as anxious" satisfies both ALTQ-1 and `ATTRIB-01`; "she is
anxious" satisfies neither. This is a prompt edit plus a scored counter (F8), and
it is the highest value-per-line change in this document.

### F3 — The gravity flag's monotone-restrict rule is backwards for atrocity

**Rules**: `ATTRIB-05` (S·v)
**Enforcement point**: `context_pack_input` + `human_gate`
**Verified**: two independent remote lanes converged (Sontag *Regarding the Pain
of Others* 10/10 proofs; Azoulay 9/9)

LIBSYN-1 §3.3 proposes a gravity flag derived from detected sensitive content
"which may only **restrict** the active register — never expand it," on the
sound argument that a monotone restriction is safe under model substitution and
a monotone expansion is not.

For most sensitive classes that is right. For **public atrocity and injury
imagery it is the wrong direction**, and both source lanes said so
independently.

Sontag's late position — the self-revision *against* her own earlier work — is
that image quantity does not numb; *passivity* does. The distilled source
records the operational partition:

> "**passivity** dulls feeling more than stills as such… **Partition:**
> desensitization folklore may govern feed design and doomscrolling UX, not
> whether a single catalogue description may name and specify. **Do not cite
> early-Sontag numbness to strip identity fields.**"

Azoulay's civil-contract argument reaches the same place from civic obligation:
silence-as-respect on a circulating emergency-claim image can be abandonment
rather than courtesy. And `ATTRIB-05` forbids the specific move a
restrict-only gravity flag produces. Definition Fix: *never mint a plight-type
to replace a missing name, invent a name when withheld, or write an
interchangeable illustration line.* Auto-restricting a named, singular person
into an anonymous instance of suffering is exactly that. (Only `ATTRIB-05`
warrants this claim; `ATTRIB-04` and `BOUND-03` do not and are not co-cited.)

**Recommendation.** Keep monotone-restrict for the classes it fits; add an
**obligation** class a restriction may not silently enter. No middle setting —
see §5.

### F4 — v3's `caption` field is a rule-violation surface by construction

**Rules**: `ATTRIB-03` (S·d), `ATTRIB-04` (S·e), `BOUND-05` (S·d)
**Enforcement point**: `output_schema`
**Verified**: in code, `apps/prototype-description-service/scripts/eval_harness/bakeoff.py` (`_V3_THREE_SURFACE_INSTRUCTIONS`, `"caption"` field)

`_V3_THREE_SURFACE_INSTRUCTIONS` defines the third publish surface as:

> "a free-form evocative caption of 2-5 sentences. **A lyrical register is
> welcome here**, but every concrete detail — objects, legible text, places,
> counts, names — must come from the committed facts or the supplied context."

The grounding clause is genuinely strong and covers fabrication of *specifics*.
It does not touch **voice**, and voice is what `ATTRIB-03` governs: non-visible
content co-voiced with inventory must move to `EDITORIAL` or `INTERPRETIVE` with
an explicit bearer. A lyrical register co-voiced with a fact inventory is the
definition of the failure.

Two further edges:

- `ATTRIB-04` — a lyrical register on a harm image is aestheticising form in the
  same voice as the harm inventory. The field has no distress branch.
- `BOUND-05` — in a 2–5 sentence caption, what comes first reads as what the
  picture emphasises. Barthes' *emphase* rule says rank words are licensed only
  by a visible pictorial cue (crop, scale, contrast); otherwise the ordering is
  editorial selection and must say so. Sentence order is not image privilege.

**Recommendation.** The fix is structural and cheap because v3 already returns
fenced JSON: split `caption` into a grounded-inventory span and an attributed
span. An attributed span with a named bearer is canon-clean at any register; an
unmarked lyrical block is not, no matter how well its specifics are grounded.

### F5 — Race labels have no warrant-or-parity gate

**Rules**: `ATTRIB-06` (S·v)
**Enforcement point**: `post_generation_check` + `eval_metric`
**Verified**: DCMP distilled, ch-3 L00558 (verbatim)

> "When time allows, and especially when important to the meaning / intent of
> content, describe race using currently-accepted terminology. Do not make
> assumptions as to someone's race and use general terms when information is not
> known. When including descriptions of race, include descriptions of BIPOC as
> well as white individuals."

Pass 1 asks for each person's `appearance` as free text. Nothing checks whether
a race or race-proxy term is warranted, whether it was assumed from pixels
(which is exactly what a VLM does), or whether it was applied with parity.

This finding has a structural property worth flagging to whoever implements it:
**parity is not a per-image property.** The harness scores image-by-image, but
"describe BIPOC and white individuals *in that pass*" is a property of a *set* of
descriptions. Checking it requires a pass-level aggregate the harness does not
currently have a shape for. That is the real cost here, and it should be sized
before the check is promised.

### F6 — Agentless passive is unchecked, and it is the cheapest check available

**Rules**: `ATTRIB-08` (S·d)
**Enforcement point**: `post_generation_check`

`ATTRIB-08` (Failure / Fix columns of one row; join marked — see Appendix
citation convention):

- **Failure:** violence / oppression / enslavement prose uses an agentless
  passive, a mutual-event noun, or an actorless event noun ("a clash", "an
  incident", "were killed").
- **Fix:** make the record-supported actor the grammatical subject, or state
  the gap.

Purely grammatical, deterministic, no model. Highest value-per-effort item here;
report-only signal beside the existing meta-framing detector.

### F7 — FIR confirmation is not consent

**Rules**: `ATTRIB-10` (S·e), `ATTRIB-05` (S·v)
**Enforcement point**: `context_pack_input` + `human_gate`

The identity gate is well built: a name attaches only when a human has confirmed
the cluster against a roster. But confirmation answers *"is this who we think it
is?"* — a different question from *"should this person be named in public
alt text?"*

`ATTRIB-10` makes naming depth subject to "living-person and surveillance risk,"
and the A4BLiP source holds the same tension open deliberately: naming affirms
humanity for recoverable historical subjects and can be surveillance violence for
living people, with no always-rule available. Lane J returned this as a
`human_gate` and it is right to.

**Recommendation.** A withhold flag on the roster entry, honoured by the pack
assembler. The machine should not infer it.

### F8 — The counter LIBSYN-1 called the highest-value safety signal is still not built

**Rules**: `ATTRIB-01`
**Enforcement point**: `eval_metric`

LIBSYN-1 §3.4 listed, under "Now, cheap, additive": *"the
inner-state-attribution counter in the eval harness (it is a scored metric even
with a single register, and it is the highest-value safety signal in the whole
caption pipeline)."*

Verified by grep: `DescriptionRegister` / `FORENSIC` / `EDITORIAL` /
`INTERPRETIVE` appear nowhere under
`apps/prototype-description-service/scene/` or `…/scripts/`; no attribution
counter in `…/scripts/eval_harness/caption_metrics.py`. Still unbuilt. The
*counter* is canon-backed via `ATTRIB-01` (not via any `REG-*` — §2).

### F9 — The compression path truncates where selection is required

**Rules**: none from lexicons at v0.17.2; reasoning card
`compression-is-selection-not-truncation` only
**Enforcement point**: `system_prompt` + `output_schema`

`_COMPRESS_SYSTEM_PROMPT` compresses to ≤125 characters and forbids new facts
but does **not** declare what must survive. The card: a short output is a
*different selection under declared survival rules*, not a tail-cut long draft;
predicted failure is keeping decorative detail and losing purpose-critical
facts.

**Not `A11Y-02`.** That row is missing-alt / decorative-marking purpose
equivalence (Failure: image without alt or decorative mark; Fix: text
equivalent for purpose, or `alt=""`). It is not a compression-survival rule; no
`SEL-*` family shipped. F9 cites the card alone. Harness already has gist ≤125
and Must-Right presence — a ranked keep-list has somewhere to attach.

---

## 4. Already covered — do not rebuild

Stated explicitly so this document cannot be read as recommending work that
exists. The pipeline already enforces, mechanically:

| Property | Where |
|---|---|
| Unconfirmed / ambiguous faces are never named | FIR gate; `review_reasons` instead |
| Pixels beat context on conflict | `_WEAVE_INSTRUCTIONS` — "pixels win" |
| A context name the facts do not account for is dropped entirely | `_WEAVE_INSTRUCTIONS`, with a worked example |
| No invented specifics in any v3 surface | `_V3_THREE_SURFACE_INSTRUCTIONS` |
| No meta-framing prose | `_META_FRAMING_PHRASES` detector |
| Alt ≤125 chars; first-sentence gist bound | `_GIST_MAX_CHARS` |
| Fabrication measured by kind | `fabricated_fact_rate`, `fabrication_by_kind` |
| Context regurgitation measured | `_context_trigram_overlap` |
| Wrong-name trap zeroes the image | `wrong_name_image_rate` |
| **Context obedience scored on two arms** | `name_ablation` + `distractor` eval modes |

That last row deserves emphasis. The reasoning card
`context-obedience-is-a-separate-capability` requires exactly this: two fixed
arms differing only in the context block, scored on insertion of supplied facts,
non-contradiction, and non-invention of unsupplied facts. **This pipeline already
satisfies that card**, which is unusual — most systems the card describes do not.
It is a genuine strength and the register-compliance arm proposed in LIBSYN-1
§3.3 should be added to the same harness rather than built beside it.

The pass-1 / pass-2 split is also independently sound under canon: committing
image-only facts before any context is visible is `BOUND-01`'s assertable-set
discipline implemented as architecture rather than as instruction.

---

## 5. Honestly not enforceable

Four items are real and belong in review guidance, not in code. Manufacturing an
enforcement point for them would produce a check that fails open.

- **`BOUND-04` — refuse restage, refuse erasure.** A tier-J judgment cut:
  address the injury without unmediated restaging of the degrading gaze. Both
  failure directions are harms and the boundary is contextual. `human_gate` at
  most.
- **`ATTRIB-09` — the enslaved person's name is the primary entry.** Archival
  cataloguing. It applies only if this pipeline ingests archival collections;
  today it does not. Recorded so that a future archival tenant does not
  rediscover it late.
- **The restraint / obligation tension itself.** Berger and Sontag pull opposite
  ways on whether description of suffering is consumption or duty. The canon's
  distillation spec is explicit that opposed instructions are "kept whole and the
  partition is stated; they are not averaged into a compromise row," and the
  Berger distillation says outright: *do not synthesize a middle "balance" rule.*
  The pipeline must therefore carry **both**, partitioned by image class — which
  is what F3 asks for and why F3 is not "pick a safer default."
- **Institutional anti-racism work** — advocacy statements, hiring pathways,
  paying community consultants. Real, and correctly outside per-record
  description mechanics.

---

## 6. Suggested sequencing

Not a plan; an ordering by cost against canon weight.

1. **F2** (prompt edit + attributed emotion) and **F6** (passive-voice check) —
   both small, both independently shippable, F2 clears a tier-B rule.
2. **F8** — the inner-state-attribution counter. Already scoped by LIBSYN-1
   §3.4, now canon-backed, and it is what makes F2 measurable rather than hoped-for.
3. **F1** — the `voice` field on context-pack entries. Additive to a closed
   model; clears a second tier-B rule.
4. **F4** — split the v3 `caption` field. Do this before v3 ships to a tenant;
   afterwards it is a contract break.
5. **F3**, **F7** — need a decision, not just an implementation.
6. **F5**, **F9** — real, but size F5's pass-level aggregate before committing.

`FORENSIC` / `EDITORIAL` / `INTERPRETIVE` as a live enum stays where LIBSYN-1 put
it: the enum lands in the contract early because retrofitting it is a rewrite of
every call site; the enforcement lands later.

---

## 7. Machine-readable findings

For downstream ingestion. `rule_ids` resolve against
`heuristics-canon-research/lexicons/depiction.md` at `v0.17.2`
(`4e099ded65ee33bc4db85dfd4c65409a0087a752`) or later.

```yaml
schema: acx-depiction-eval/v1
canon_version: v0.17.2
canon_commit: 4e099ded65ee33bc4db85dfd4c65409a0087a752
evaluated: apps/prototype-description-service
date: 2026-07-27
findings:
  - id: F1
    summary: Context pack can launder oppressive creator wording into the model's unmarked voice
    rule_ids: [ATTRIB-07]
    tier: B
    enforcement_point: context_pack_input
    secondary_enforcement: output_schema
    evidence: apps/prototype-description-service/scene/infrastructure/vlm/gpu_remote_adapter.py::_render_context,_user_text,_SYSTEM_PROMPT
    verified: code
    note: ATTRIB-07 warrants the oppressive-wording subset only; no lexicon row governs all unmarked creator speech
  - id: F2
    summary: v2 prompt licenses inner-state attribution that ATTRIB-01 blocks
    rule_ids: [ATTRIB-01, ATTRIB-03]
    tier: B
    enforcement_point: system_prompt
    evidence: apps/prototype-description-service/scripts/eval_harness/bakeoff.py (_PROMPT_V2_SYSTEM)
    verified: code
    note: tension with ALTQ-1 findings section 3; resolution is attributed voice, not deletion
  - id: F3
    summary: Monotone-restrict gravity flag is the wrong direction for public atrocity imagery
    rule_ids: [ATTRIB-05]
    tier: S
    enforcement_point: context_pack_input
    secondary_enforcement: human_gate
    evidence: docs/research/cross-domain-bridges-and-caption-register.md (LIBSYN-1 §3.3 gravity flag)
    verified: source
  - id: F4
    summary: v3 caption field invites lyrical register with no bearer requirement
    rule_ids: [ATTRIB-03, ATTRIB-04, BOUND-05]
    tier: S
    enforcement_point: output_schema
    evidence: apps/prototype-description-service/scripts/eval_harness/bakeoff.py (_V3_THREE_SURFACE_INSTRUCTIONS)
    verified: code
  - id: F5
    summary: Race labels have no warrant, non-assumption, or parity gate
    rule_ids: [ATTRIB-06]
    tier: S
    enforcement_point: post_generation_check
    secondary_enforcement: eval_metric
    evidence: dcmp-description-key ch-3 L00558
    verified: source
    note: parity is a pass-level property; harness scores per-image only
  - id: F6
    summary: Agentless passive, mutual-event, and actorless event nouns are unchecked
    rule_ids: [ATTRIB-08]
    tier: S
    enforcement_point: post_generation_check
    verified: absence
  - id: F7
    summary: FIR roster confirmation is treated as authority to name; surveillance risk is a separate gate
    rule_ids: [ATTRIB-10, ATTRIB-05]
    tier: S
    enforcement_point: context_pack_input
    secondary_enforcement: human_gate
    verified: source
  - id: F8
    summary: Inner-state-attribution counter proposed in LIBSYN-1 is still unbuilt
    rule_ids: [ATTRIB-01]
    tier: B
    enforcement_point: eval_metric
    evidence: grep - no DescriptionRegister/FORENSIC/EDITORIAL/INTERPRETIVE under apps/prototype-description-service/scene/ or scripts/
    verified: absence
  - id: F9
    summary: Compression prompt truncates without a declared survival list
    rule_ids: []
    tier: B
    enforcement_point: system_prompt
    secondary_enforcement: output_schema
    reasoning_card: compression-is-selection-not-truncation
    note: no lexicon row warrants survival-selection; A11Y-02 is missing-alt purpose equivalence, not cited
    verified: code
not_enforceable:
  - rule_ids: [BOUND-04]
    reason: tier-J judgment cut; both failure directions are harms
  - rule_ids: [ATTRIB-09]
    reason: archival cataloguing; no archival tenant today
  - rule_ids: []
    reason: restraint/obligation tension must be partitioned by image class, never averaged
  - rule_ids: []
    reason: institutional anti-racism work is outside per-record description mechanics
already_covered:
  - unconfirmed faces never named
  - pixels win on conflict
  - unaccounted context names dropped
  - no invented specifics
  - meta-framing detector
  - alt <=125 chars
  - fabrication rate by kind
  - context trigram overlap
  - wrong-name trap
  - context obedience two-arm scoring (name_ablation + distractor)
```

---

## Appendix — method and verification

**Canon currency.** Pinned to heuristics-canon-research `v0.17.2` @
`4e099ded65ee33bc4db85dfd4c65409a0087a752`. INDEX.md: **1143 rules** / 11
lexicons. Lexicon warrants here are depiction definition anchors only (15 rows;
§2). No `REG-*` family. F9 uses the compression reasoning card, not a lexicon
ID. Private `gh` clone (`darce/heuristics-canon-research`) matches local;
`distilled/depiction/*` is tracked — one source.

**Citation convention.** An illustrative quote may join the Failure and Fix
columns of a **single** lexicon row when each column is labelled (see F6); that
join is not continuous source prose.

**Source mining.** Seven remote grok-4.5 lanes, one distilled source each
(history-stripped OCI-VM; full text inlined). Schema required per claim:
`proof_of_reading`, closed enforcement-point vocabulary, `already_covered`.
Multi-source briefs tail-anchored (last source only); one brief per source
fixed it. Every `proof_of_reading` grepped against that lane's own source +
`depiction.md`: 50/66 verbatim, 16 after markdown/punctuation normalise, 0
unverifiable. By lane: A4BLiP 10/10, DCMP 9/10, Sontag *On Photography* 8/8,
Berger *Ways* 7/9, Sontag *Pain* 6/10, Azoulay 6/9, Barthes *IMT* 4/10
(weakest; none of F1–F9 rests on it). One live-research lane rejected (6/7
quotes unfindable); re-derived from local distillations.

**Code verification.** F1, F2, F4, F9 by source read; F6, F8 by absence grep
under `apps/prototype-description-service/scene/` and `…/scripts/`.

**Limit.** Captioning path only. FIR bake-off assessed in
`docs/assessments/current/omg-spec-fit-fir-captioning-pipelines-2026-07-26.md`
(Metadata supersedes note). Tiers B/S/J are the canon's, not this document's.
