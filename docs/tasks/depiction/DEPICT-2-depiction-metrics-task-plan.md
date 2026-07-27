# DEPICT-2. Depiction Metrics (inner-state, agentless-passive, signal density)

> **Metadata**
>
> - **Date**: 2026-07-27
> - **Author**: grok-4.5 (remote flock lane C)
> - **Project**: `prototype-description-service`
> - **Task ID**: `DEPICT-2`
> - **Target Branch**: `feature/depict-2`
> - **Review Coverage Target**: 2
>
> **Governing assessment**: [`docs/assessments/current/depiction-canon-triage-and-backlog-2026-07-27.md`](../../docs/assessments/current/depiction-canon-triage-and-backlog-2026-07-27.md)
> (§2 items 3–4, §6b–§6c, §10f–§10g). Upstream eval:
> [`depiction-canon-fit-captioning-pipeline-2026-07-27.md`](../../docs/assessments/current/depiction-canon-fit-captioning-pipeline-2026-07-27.md)
> (F6, F8). Playbook:
> [`fir-captioning-orchestrator-playbook.md`](../../docs/runbooks/fir-captioning-orchestrator-playbook.md)
> §3.1 (signal density; §3.2 is stale — ALTQ-1 shipped it).
>
> **Canon**: heuristics-canon `v0.17.0-11-ga238620` (bundle `canon/PROVENANCE.txt`).
> Every rule ID below was verified with the definition-anchor form
> `grep -rE '^\| *`?<ID><a name' canon/lexicons/` before citation.

## Objective

Land three pure, deterministic, report-only scoring signals in
`caption_metrics.py` so prompt-side depiction work (Lanes A/B) and the GPU
bake-off window become measurable: an inner-state-attribution counter
([ATTRIB-01](../../../canon/lexicons/depiction.md#attrib-01)), an
agentless-passive / mutual-event detector
([ATTRIB-08](../../../canon/lexicons/depiction.md#attrib-08)), and a
**verified** signal-density ranking axis
([EVAL-11](../../../canon/lexicons/ml-systems.md#eval-11)). Resolve the
Williams/C5 length contradiction in the module docstring so gate policy and
ranking policy cannot be read as opposites.

## Problem Statement

The caption harness can already gate wrong names, score fabrication traps, and
flag meta-framing, but it cannot see the highest-value depiction safety signal
LIBSYN-1 named (inner-state attribution on a depicted person), cannot flag the
cheapest grammar failure in the depiction lexicon (agentless passive / "clash"
frames), and measures no signal density at all. Every length-correlated quality
axis therefore still rewards verbosity. Until these scorers exist, Lane A/B
prompt changes are unmeasurable — exactly what
[EVAL-08](../../../canon/lexicons/ml-systems.md#eval-08) (CACE) forbids — and
the GPU window remains gated by playbook §3.1.

## Constraints

- **Owned paths only**:
  `apps/prototype-description-service/scripts/eval_harness/caption_metrics.py`
  and
  `apps/prototype-description-service/scene/tests/test_eval_harness_caption_metrics.py`.
  No edits under any other path in this task.
- **Report-only first**: no new hard gate, no threshold, no zeroing of
  `gated_score` from the new counters or the density axis in their first slice.
- **Deterministic, pure, no network**: preserve bit-identical re-score.
- **Greenfield**: no compatibility shims, no feature flags for old metrics.
- **No colour vocabulary, colour term, colour catalogue, or colour field.**
  Colour is trigger-gated off the critical path (assessment §10e). `FM-11` is
  retired and not citable.
- **No prompt, schema, or contract changes** (Lanes A and B).
- **[TEST-15] red-first is mandatory** for every new check: exact failing input
  before green, plus a discrimination case that a vacuous implementation fails.
- Test command from `apps/prototype-description-service/`:
  `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -q`.

## Workflow Principles

- **Measurement before change.** Land scorers before (and independent of) the
  prompt edits they make measurable ([EVAL-08](../../../canon/lexicons/ml-systems.md#eval-08)).
- **Williams vs C5 — both hold, different roles.** Williams governs the **gate**:
  do not hard-cap length; do not zero a long description for being long.
  C5 / playbook §3.1 governs the **ranking axis**: do not reward verbosity;
  rank on verified facts per 100 words. Density is a companion ranking column,
  never a length penalty on `gated_score`. Write this into the module docstring
  in Slice 3 so the two governing documents stop pointing opposite ways.
- **Register, not silence for affect.** Attributed readings
  ("her expression reads as anxious") are legitimate access content; unmarked
  person-as-fact-owner ("she is anxious") is the defect. The counter must
  distinguish them — that distinction *is* the discrimination test.
- **Verified numerator or the metric is wrong.** Unverifiable specificity
  scores zero, not one. A naive facts/100w that counts rare free nouns trips
  the reasoning card
  `controlled-vocabulary-caps-hallucination` and fails
  [EVAL-11](../../../canon/lexicons/ml-systems.md#eval-11).
- **Delete over flag; report-only over gate.** First landing of each new
  counter is observational so false-positive shape can be measured on real
  captions before any gate decision.

## Terminology

- **Inner-state attribution**: a clause that makes a depicted person the
  grammatical owner of an interior state, will, trait, or essence no pixel can
  confirm ("she is anxious", "he wants", "they are proud"), with no attributive
  frame naming viewer, convention, artefact, or source.
- **Attributive frame (bearer)**: a grammatical frame that moves ownership of
  the reading off the depicted person — e.g. "her expression reads as…",
  "appears…", "looks…", "as if…", "read as…", "according to…".
- **Agentless passive / mutual-event noun**: oppression or violence prose that
  hides a record-supported actor behind passive voice ("were killed") or a
  symmetry noun ("a clash", "an incident") — the
  [ATTRIB-08](../../../canon/lexicons/depiction.md#attrib-08) trigger.
- **Verified fact (density numerator)**: a `ReferenceFact` with
  `polarity=true` whose `match_targets()` hit the caption under the existing
  word-boundary matcher (`_contains`). Claims with no such walkback contribute
  **zero** to the numerator, even if lexically rare or specific.
- **Signal density (ranking axis)**: verified facts per 100 words =
  `(verified_count / word_count) * 100`, or `None` when `word_count == 0`.
  Ranking companion only — not a hard gate.
- **Williams gate policy**: no hard length cap; longer descriptions are not
  penalised for length; missing content is penalised via existing axes.
- **C5 ranking policy**: length-correlated quality alone ranks the most verbose
  candidate highest; density is the required companion column that prevents
  that outcome.

## Current State Analysis

- `caption_metrics.py` already ships Must-Right / policy / wrong-name **gates**,
  insertion / name-precision / wrong-name-image rates, FKRE, repetition, tag
  coverage, first-sentence gist, meta-framing detector
  (`_META_FRAMING_PHRASES` at L39), context-trigram duplication, sentence-count
  band helpers, and VLM-6 hallucination scoring
  (`score_hallucination`, `fabricated_fact_rate`, `fabrication_by_kind`).
- **No** inner-state / affect / attribution counter (eval F8; confirmed by
  absence in this module).
- **No** agentless-passive / mutual-event detector (eval F6).
- **No** facts-per-100-words or density axis (playbook §3.1; assessment §6b).
  The only `distinct*` helpers are name-token matchers.
- Module docstring L8–10 states Williams ("no hard length cap — longer
  descriptions score higher") with no C5 companion. Playbook §3.1 treats
  length-only ranking as a defect. The contradiction is live and unrecorded.
- `score_hallucination` / `fabricated_fact_rate` already measure the
  **known-false assertion** axis against authored traps. They do **not**
  measure attribution grammar, agentless passive, or verified density.

## Target Outcome

1. Pure functions (and additive score fields where they fit the existing
   `CaptionScores` / aggregate pattern) that:
   - count inner-state-attribution hits (report-only);
   - list agentless-passive / mutual-event hits (report-only);
   - compute verified signal density as a ranking companion.
2. Module docstring resolves Williams (gate) vs C5 (ranking) in writing.
3. Every new assertion has a red-first proof and a discrimination case that
   rejects vacuous implementations.
4. Consumers (`report.py`, bake-off ranking) can import the new APIs later;
   this task does not edit those files.

## Context Loading

Load before implementing any slice:

- Rules: `docs/workbay/rules/testing-python.md`,
  `docs/workbay/rules/backend-python-guidelines.md`,
  `docs/workbay/rules/development-workflow.md`
- Owned implementation:
  `apps/prototype-description-service/scripts/eval_harness/caption_metrics.py`
- Owned tests:
  `apps/prototype-description-service/scene/tests/test_eval_harness_caption_metrics.py`
- Manifest types already imported by the module:
  `scripts/eval_harness/manifest.py` (`ReferenceFact`, `FactKind`,
  `FactPolarity`) — **read-only adjacency**, not owned
- Governing assessment §§2, 6b, 6c, 10f, 10g
- Canon rows + distilled evidence named per slice below
- Reasoning cards:
  `canon/public/reasoning/attribute-claims-to-their-bearer.md`,
  `canon/public/reasoning/controlled-vocabulary-caps-hallucination.md`,
  `canon/public/reasoning/signal-density-not-length.md`

## Contract and Boundary Impact

Strictly local pure scoring. No service, schema, HTTP, or WP boundary change.

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Caption scoring pure API | Lane C (this task) | `score_caption` / `score_hallucination` in `caption_metrics.py` | additive fields + new pure functions | no — greenfield additive | unit tests below |
| Report / bake-off consumption | unowned by this lane | `report.py` reads known `CaptionScores` fields | **none in this task** | n/a | see Cross-lane dependency |

## Proposed Solution

Shape new detectors after the existing report-only meta-framing pattern: closed
phrase / grammar tables, word-boundary regex, hit lists on a score object, no
gate side-effects. Implement density as a separate pure function over
`(caption, reference_facts)` so it reuses the hallucination harness's authored
true-polarity facts as the verified set
([PROV-01](../../../canon/lexicons/ml-systems.md#prov-01) walkback) without
re-deriving fabrication. Document Williams/C5 in the module header so ranking
and gate cannot be collapsed.

### `CAL-02` and `PROV-01` — metric side only (scope decision)

Assessment §10f adds `CAL-02` abstain and `PROV-01` evidence-walkback on the
prompt+metric surface. Prompt side is out of this lane. Metric side:

| Rule | What existing metrics already cover | What would be new | Decision |
| --- | --- | --- | --- |
| [PROV-01](../../../canon/lexicons/ml-systems.md#prov-01) (`ml-systems.md` → `distilled/ml-systems/model-cards.md`) | `fabricated_fact_rate` catches known-false traps; `HallucinationScores.coverage` measures true-fact walkback | A **positive** walkback filter on density's numerator | **In scope as density definition**, not a second headline metric. Density counts only facts that walk back to true-polarity `ReferenceFact` match targets. Restating coverage as a new named metric is refused. |
| [CAL-02](../../../canon/lexicons/ml-systems.md#cal-02) (`ml-systems.md` → `distilled/ml-systems/designing-ml-systems.md`, Confidence measurement) | `score_hallucination` already scores the failure mode CAL-02 forbids when a trap is authored: forced precise wrong label under weak/no evidence | A true *abstain* rate needs weak-evidence fixtures and an explicit abstain surface ("unknown" / omitted precision) so correct abstention is distinguishable from lucky omission | **Scoped out of DEPICT-2.** A dedicated abstain counter would either restate fabrication (trap hit = failed abstain) or be vacuous without corpus annotations. Revisit when a weak-evidence / abstain fixture class exists. |

**No canon warrant invented** for a second fabrication restatement. Explicitly
refusing a restated metric is preferred to citing `CAL-02` on a clone of
`fabricated_fact_rate`.

### Deferred (named, not planned)

- **Race warrant / parity (`ATTRIB-06`)**: assessment §2 item 11. Parity is a
  property of a *pass*, not an image; this harness scores per-image only.
  Deferred until a pass-level aggregate is sized. Do not implement here.
- **Gating / thresholding** any new counter on first land.
- **Colour / FM-04 catalog work**: trigger-gated (§10e); out of critical path.
- **Prompt emotion-bearer edit (DEPICT-4 / F2)**: Lane A; unmeasurable until
  Slice 1 of this plan lands.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| metrics | `apps/prototype-description-service/scripts/eval_harness/caption_metrics.py` | Inner-state counter; agentless-passive detector; `score_signal_density`; Williams/C5 docstring resolution; additive score fields |
| tests | `apps/prototype-description-service/scene/tests/test_eval_harness_caption_metrics.py` | Red-first + discrimination tests for every new signal |

## Related Files

| File | Note |
| --- | --- |
| `scripts/eval_harness/manifest.py` | `ReferenceFact.match_targets()` is the density walkback primitive — read only |
| `scripts/eval_harness/report.py` | Will eventually surface new fields; **not edited here** |
| `scripts/eval_harness/bakeoff.py` | Ranking consumer of density; Lane A owns prompt constants here, not metrics |
| `docs/runbooks/fir-captioning-orchestrator-playbook.md` §3.1 | Density requirement; §3.2 stale |

### Cross-lane dependency

| File | Exact change needed | Who lands first |
| --- | --- | --- |
| `scripts/eval_harness/report.py` | Emit the new per-image hit lists and density number in JSON/markdown quality sections so the GPU window can rank on density | After DEPICT-2 pure APIs are green; unowned by Lanes A/B/C file table — schedule as a thin follow-on that *imports* this module only |
| Lane A prompt emotion-bearer (DEPICT-4) | Prompt text change so attributed emotion is licensed | **After** Slice 1 counter exists (EVAL-08 ordering) |
| Lane B contracts | None for DEPICT-2 | n/a |

This plan does **not** edit those files.

## Verification Strategy

- Deterministic tests (from `apps/prototype-description-service/`):
  - `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -q`
  - Per-slice filters as named under each slice Proof.
- No runtime-parity / GPU / live endpoint required — pure CPU scoring.
- No contract/fixture boundary work.
- Manual: re-read module docstring after Slice 3 and confirm Williams (gate) and
  C5 (ranking) both appear as distinct roles, not a single averaged policy.

## Slice Delivery

### Slice 1: Inner-state-attribution counter (report-only)

**Goal**: Count descriptions that make a depicted person the grammatical owner
of an interior state / will / trait the pixels cannot confirm — without gating.

**Canon**: [ATTRIB-01](../../../canon/lexicons/depiction.md#attrib-01)
(`canon/lexicons/depiction.md` → distilled multi-source:
`canon/distilled/depiction/berger-ways-of-seeing.md` face-reading / spectator-owner
mechanisms; `sontag-on-photography.md`;
`berger-understanding-a-photograph.md`; card
`attribute-claims-to-their-bearer`). Supporting sequencing:
[EVAL-08](../../../canon/lexicons/ml-systems.md#eval-08)
(`ml-systems.md` → `distilled/ml-systems/hidden-technical-debt-ml.md`).
Proof discipline: [TEST-15](../../../canon/lexicons/engineering.md#test-15)
(`engineering.md` → `distilled/engineering/modern-software-engineering.md`).

**Distilled load-bearing residue used here**: Berger's face-reading mechanism
forbids treating the person as fact-owner of mental-state predicates without a
frame ("prefer visible cues… or frame the reading"); the card's required action
is "never make the depicted person fact-owner of will, essence…". The register
nuance from assessment §2 item 5 is the operational cut: attributed surface
readings stay; unmarked ownership fails.

Changes:

- Add a closed interior-predicate / person-subject detector in
  `caption_metrics.py`, shaped after `_META_FRAMING_PHRASES` (phrase table +
  compiled regexes + hit list). Minimum detectable patterns (implementation may
  refine regex detail, not the discrimination contract):
  - person pronoun / common person noun subject + copula + interior adjective
    (`she is anxious`, `he seems angry` **without** an attributive frame on the
    expression);
  - person subject + will / intent verb (`she wants`, `he refuses` as interior
    will — not physical refusal with visible object when framed as action).
- **Must not fire** when an attributive frame owns the reading:
  `her expression reads as anxious`, `she looks anxious`, `appears anxious`,
  `as if anxious`, `read as anxious`, furrowed-brow **visible cue** inventory
  without mental-state ownership.
- Surface hits as an additive report-only field (e.g.
  `CaptionScores.inner_state_attribution_hits: list[str]`) populated from
  `score_caption`, **or** a sibling pure function
  `score_inner_state_attribution(caption) -> list[str]` called by tests and
  later by report. Prefer extending `score_caption` only if the field stays
  zero-cost when absent; do not touch `gated_score`.
- Document in a short comment that this is report-only (LIBSYN-1 / F8) and that
  picture-in-picture style false positives are accepted at this stage the same
  way meta-framing accepts them.

Proof ([TEST-15](../../../canon/lexicons/engineering.md#test-15)):

1. **Red-first input (must fail before implementation)**:
   - Caption: `"She is anxious beside the railing."`
   - Assert: at least one inner-state hit containing the anxious / interior
     ownership span. A no-op implementation returning `[]` fails.
2. **Discrimination case (vacuous detectors fail)**:
   - Clean / attributed: `"Her expression reads as anxious beside the railing."`
   - Assert: **zero** hits. An implementation that greps bare `anxious`
     anywhere fails this case — that is the point of the register cut.
3. **Visible-cue control**:
   - `"She stands with a furrowed brow and tight jaw."`
   - Assert: zero hits (inventory of visibles, no mental-state ownership).
4. **Command**:
   `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -k inner_state -q`

### Slice 2: Agentless-passive / mutual-event detector (report-only)

**Goal**: Pure-grammar detector for agentless passives and mutual-event nouns in
violence / oppression prose; no model, no context, no aggregate, no gate.

**Canon**: [ATTRIB-08](../../../canon/lexicons/depiction.md#attrib-08)
(`canon/lexicons/depiction.md` →
`canon/distilled/accessibility/anti-racist-description-resources.md`, named
mechanism **active voice** for oppressive relationships, L00205–L00216 Kent
State contrast). Proof:
[TEST-15](../../../canon/lexicons/engineering.md#test-15).

**Distilled load-bearing residue**: "Avoid passive voice… when describing
oppressive relationships. Use active voice in order to embed responsibility
within description." The Kent State pair is the discrimination template:
`"were killed … during a clash"` fails; `"Members of the Ohio National Guard
killed …"` passes.

Changes:

- Add phrase / pattern tables for:
  - **agentless passives** on violence/oppression verbs: e.g. `were killed`,
    `was killed`, `were beaten`, `was enslaved`, `were arrested` without a
    by-agent in the same clause;
  - **mutual-event / symmetry nouns**: e.g. `a clash`, `the clash`,
    `an incident`, `the incident` in violence contexts (closed list; do not
    generalise to every English passive).
- Surface as report-only hit list
  (`agentless_passive_hits` or sibling pure function). No `gated_score`
  change.
- Scope comment: detector is grammar + closed violence/oppression lexicon, not
  a full voice tagger; unknown-agent cases that *state the gap*
  (`agent not in the record`) are out of the hit set when that explicit gap
  language is present (ATTRIB-08 second branch).

Proof ([TEST-15](../../../canon/lexicons/engineering.md#test-15)):

1. **Red-first input**:
   - Caption: `"Four students were killed during a clash on campus."`
   - Assert: hits include an agentless-passive span **and** a mutual-event
     noun span (`clash`). Empty list fails.
2. **Discrimination case**:
   - Caption: `"Members of the Ohio National Guard killed four students on campus."`
   - Assert: **zero** hits. A detector that flags any past-tense violence verb
     fails discrimination.
3. **Gap-language control** (ATTRIB-08 second branch):
   - Caption: `"Four students were killed; the agent is not named in the record."`
   - Assert: either zero hits or a documented non-hit on the gap clause — plan
     requires the test to lock the chosen behaviour so it cannot silently
     flip. Preferred: still report the agentless passive span (grammar is true)
     but do not invent an actor; the metric is a detector, not a rewriter.
     Record that choice in the test name.
4. **Command**:
   `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -k agentless_passive -q`

### Slice 3: Verified signal-density ranking axis + Williams/C5 resolution

**Goal**: Land **verified facts per 100 words** as a ranking companion (not a
gate), with the EVAL-11 / card guard that unverifiable specificity scores zero;
write the Williams/C5 resolution into the module docstring.

**Canon**:

- [EVAL-11](../../../canon/lexicons/ml-systems.md#eval-11)
  (`canon/lexicons/ml-systems.md` →
  `canon/distilled/ml-systems/ai-engineering.md`, mechanism
  **functional-and-rubric scoring**: open-ended generation has no exact-match
  oracle; the scorer must measure task success, not wording flash).
- [PROV-01](../../../canon/lexicons/ml-systems.md#prov-01)
  (`canon/lexicons/ml-systems.md` →
  `canon/distilled/ml-systems/model-cards.md`): every counted fact walks back
  to evidence — operationalised as true-polarity `ReferenceFact` membership.
- Reasoning cards (design warrants, not extra IDs):
  `signal-density-not-length` (C5 operationalisation; verified facts per 100
  words; unverifiable specificity → 0);
  `controlled-vocabulary-caps-hallucination` Verification list: *"Metric
  definition for attribute quality does not reward lexical rarity without
  membership or grounding."*
- Proof: [TEST-15](../../../canon/lexicons/engineering.md#test-15).

**Distilled load-bearing residue for EVAL-11**: Huyen ch.3 — open-ended
generation scored by exact match / lexical flash rejects good novel phrasings
and accepts fluent wrong ones; pick a scorer from task success. Density is that
scorer for the bake-off ranking axis: checkable substance per listen cost, not
word count or rare nouns.

Changes:

1. **Module docstring (Williams/C5 resolution)** — replace / extend L8–10 so it
   states both policies without averaging them:
   - Gate (Williams): no hard length cap; do not zero a long description for
     length; existing gates remain Must-Right / policy / wrong-name /
     fabrication.
   - Ranking (C5 / playbook §3.1): report **verified signal density** as a
     separate axis; do not rank candidates by length-correlated quality alone.
2. **`score_signal_density(caption, *, reference_facts) -> SignalDensityScores
   | float | None`** (exact return type implementer's choice; prefer a small
   frozen dataclass with `verified_count`, `word_count`, `density_per_100w`
   for attributability):
   - `word_count` = existing `_WORD_RE` tokenisation (same as `score_caption`).
   - `verified_count` = number of **distinct** true-polarity `ReferenceFact`
     rows whose `match_targets()` hit via `_contains` (reuse the dedupe
     identity pattern from `score_hallucination` so duplicate authored facts
     do not inflate the numerator).
   - **False-polarity traps never increment the numerator** (they are
     fabrication, already scored elsewhere).
   - `density_per_100w = (verified_count / word_count) * 100` when
     `word_count > 0`, else `None`.
   - Unmatched free text — including rare, precise-sounding nouns with no
     fact membership — contributes **zero** to `verified_count`.
3. Optional corpus helper `mean_signal_density(scores)` only if tests need it;
   not required for the first land.
4. **Extensible verified-term predicate**: the true-polarity `ReferenceFact`
   set is the verified predicate for this slice. Do **not** hard-code a colour
   catalogue. Comment that future bound-term providers (assessment §6d C7
   chain) plug in by authoring additional true-polarity facts — density itself
   does not import a vocabulary. No colour field.

Proof ([TEST-15](../../../canon/lexicons/engineering.md#test-15)):

1. **Red-first input (naive density must not ship)**:
   - Facts: one true fact `ReferenceFact(text="bicycle", kind=OBJECT,
     polarity=TRUE, phrases=["bicycle"])`.
   - Caption: `"A bicycle leans on a wall."` (4 words, 1 verified).
   - Assert: `verified_count == 1`, `density_per_100w == pytest.approx(25.0)`.
   - Empty / wrong implementation fails.
2. **Mandatory discrimination case — rare ungrounded noun must not raise the
   score** (assessment §10f / lane brief):
   - Same true fact set: only `bicycle` is verified membership.
   - **Grounded caption** `G`: `"A bicycle leans on a wall."`
     → `verified_count=1`, `word_count=6`, density ≈ `16.667`.
   - **Rare ungrounded caption** `U`: `"A vermilion velocipede leans on a wall."`
     → `verified_count=0` (neither `vermilion` nor `velocipede` is a match
     target), `word_count=7`, density `0.0`.
   - Assert: `density(U) < density(G)` **and** `verified_count(U) == 0`.
   - An implementation that counts any token or rewards lexical rarity fails.
3. **Padding / verbosity control (C5)**:
   - Caption `P`: `"A bicycle leans on a wall near decorative ironwork and
     ornamental brickwork under an expansive firmament."` with the same single
     true fact.
   - Assert: `verified_count == 1` and `density(P) < density(G)` because the
     denominator grew with unverifiable ornament.
4. **False-trap control**:
   - Caption asserts a false-polarity phrase; assert it does not increase
     `verified_count`.
5. **Command**:
   `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -k signal_density -q`
6. **Docstring check** (lightweight): a test or review step confirms the module
   docstring contains both the Williams gate statement and the C5 ranking /
   density statement as distinct roles (string presence is enough; do not parse
   prose quality in pytest).

## Consolidated Checklist

### Context and Ownership

- [ ] Loaded testing-python / backend-python / development-workflow rules.
- [ ] Confirmed owned paths only; no edits under `report.py`, bakeoff prompts,
      schemas, or `canon/`.
- [ ] Re-verified cited rule IDs with definition-anchor grep before
      implementation review.

### Checklist for Slice 1: Inner-state-attribution counter

- [ ] Write red-first test: `"She is anxious beside the railing."` expects ≥1 hit.
- [ ] Write discrimination test: `"Her expression reads as anxious…"` expects 0 hits.
- [ ] Write visible-cue control: furrowed brow / tight jaw → 0 hits.
- [ ] Implement detector + report-only surface in `caption_metrics.py`.
- [ ] Confirm `gated_score` unchanged on positive hits.
- [ ] `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -k inner_state -q` green.

### Checklist for Slice 2: Agentless-passive / mutual-event detector

- [ ] Write red-first test: `"Four students were killed during a clash on campus."` expects passive + clash hits.
- [ ] Write discrimination test: active-voice named agent → 0 hits.
- [ ] Lock gap-language behaviour in a named test.
- [ ] Implement detector + report-only surface.
- [ ] Confirm no gate side-effect.
- [ ] `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -k agentless_passive -q` green.

### Checklist for Slice 3: Signal density + Williams/C5

- [ ] Write red-first density test (grounded bicycle caption).
- [ ] Write mandatory rare-ungrounded discrimination pair (`vermilion velocipede` vs `bicycle`) with expected scores.
- [ ] Write padding/verbosity density drop test.
- [ ] Write false-trap non-contribution test.
- [ ] Implement `score_signal_density` with true-polarity-only numerator.
- [ ] Rewrite module docstring: Williams = gate, C5 = ranking axis.
- [ ] `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -k signal_density -q` green.
- [ ] Full file:
      `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -q` green.

### Review Readiness

- [ ] No new gate or threshold on first land.
- [ ] Every new assertion has red input + discrimination case in the same PR.
- [ ] Williams/C5 resolution is written in-module, not only in this plan.
- [ ] No colour IDs, no `FM-11`, no fabricated `REG`/`ICON`/`FRAM`/`SEL` IDs.
- [ ] Cross-lane report wiring recorded, not implemented here.

## Stretch Goals

- [ ] Corpus-level `mean_signal_density` helper mirroring `insertion_rate`.
- [ ] Report-only rate helpers (`inner_state_image_rate`, `agentless_passive_image_rate`) once per-image fields exist — still no gates.

## Success Criteria

- [ ] Inner-state counter fires on person-as-fact-owner mental-state prose and
      stays silent on attributed readings and visible-cue inventory.
- [ ] Agentless-passive detector fires on the Kent State failure shape and stays
      silent on named-agent active voice.
- [ ] Signal density ranks grounded captions above rare-ungrounded and
      ornament-padded captions with equal or fewer verified facts; rare
      ungrounded nouns never raise the score.
- [ ] Module docstring states Williams (gate) and C5 (ranking) as distinct roles.
- [ ] `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -q` green at branch HEAD.
- [ ] No files outside the two owned paths modified.

## Not-Doing

- Prompt text / emotion-bearer edits (Lane A; DEPICT-4).
- Contract, schema, enum, `voice`, register, bound-term fields (Lane B).
- `report.py` / bake-off ranking wiring (cross-lane follow-on).
- Colour vocabulary of any kind; `FM-11` citations; Lane D trigger work.
- Race warrant / parity gate (`ATTRIB-06`) — pass-level property; harness is
  per-image only.
- Thresholding or hard-gating any new counter on first land.
- Dedicated `CAL-02` abstain-rate metric (would restate fabrication or be
  vacuous without weak-evidence fixtures) — see scope decision above.
- Second fabrication metric that restates `score_hallucination` /
  `fabricated_fact_rate` under a `PROV-01` label — PROV-01 is carried as the
  density numerator's walkback definition only.
- LLM-judge scoring, model training, non-deterministic axes.
