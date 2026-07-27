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
> **Governing assessment**: [`depiction-canon-triage-and-backlog-2026-07-27.md`](../../assessments/current/depiction-canon-triage-and-backlog-2026-07-27.md)
> (§2 items 3–4, §6b–§6c, §10f–§10g). Upstream eval:
> [`depiction-canon-fit-captioning-pipeline-2026-07-27.md`](../../assessments/current/depiction-canon-fit-captioning-pipeline-2026-07-27.md)
> (F6, F8). Playbook:
> [`fir-captioning-orchestrator-playbook.md`](../../runbooks/fir-captioning-orchestrator-playbook.md)
> §3.1 (signal density; §3.2 is stale — ALTQ-1 shipped it).
>
> **Canon**: heuristics-canon `v0.17.0-11-ga238620` (bundle `canon/PROVENANCE.txt`;
> private repo, not vendored here — cite rule IDs as plain text with lexicon
> path, never as relative markdown links). Every rule ID below was verified
> with the definition-anchor form
> `grep -rE '^\| *`?<ID><a name' canon/lexicons/` before citation.

## Objective

Land three pure, deterministic, report-only scoring signals in
`caption_metrics.py` so prompt-side depiction work (Lanes A/B) and the GPU
bake-off window become measurable: an inner-state-attribution counter
(ATTRIB-01, `canon/lexicons/depiction.md#attrib-01`), an
agentless-passive / mutual-event detector
(ATTRIB-08, `canon/lexicons/depiction.md#attrib-08`), and a
**verified** signal-density ranking axis
(EVAL-11, `canon/lexicons/ml-systems.md#eval-11`). Emit the new hit lists and
density from `report.py` (thin additive Slice 4) so the playbook §3.1 ranking
gate is not left closed. Resolve the Williams/C5 length contradiction in the
module docstring so gate policy and ranking policy cannot be read as opposites.

## Problem Statement

The caption harness can already gate wrong names, score fabrication traps, and
flag meta-framing, but it cannot see the highest-value depiction safety signal
LIBSYN-1 named (inner-state attribution on a depicted person), cannot flag the
cheapest grammar failure in the depiction lexicon (agentless passive / "clash"
frames), and measures no signal density at all. Every length-correlated quality
axis therefore still rewards verbosity. Until these scorers exist, Lane A/B
prompt changes are unmeasurable — exactly what EVAL-08
(`canon/lexicons/ml-systems.md#eval-08`, CACE) forbids — and the GPU window
remains gated by playbook §3.1. Pure scorers alone are not enough: `report.py`
today builds its quality block from `meta_framing_hits` / sentence band /
`mean_gated_score` only (see Current State), so density must also be emitted
there before the ranking gate opens.

## Constraints

- **Owned paths only**:
  `apps/prototype-description-service/scripts/eval_harness/caption_metrics.py`,
  `apps/prototype-description-service/scene/tests/test_eval_harness_caption_metrics.py`,
  and (Slice 4 only) thin additive emit in
  `apps/prototype-description-service/scripts/eval_harness/report.py` plus any
  test that asserts the report JSON carries the new keys. No edits under any
  other path in this task.
- **Report-only first**: no new hard gate, no threshold, no zeroing of
  `gated_score` from the new counters or the density axis in their first slice.
- **Deterministic, pure, no network**: preserve bit-identical re-score.
- **Greenfield**: no compatibility shims, no feature flags for old metrics.
- **No colour vocabulary, colour term, colour catalogue, or colour field.**
  Colour is trigger-gated off the critical path (assessment §10e). `FM-11` is
  retired and not citable.
- **No prompt, schema, or contract changes** (Lanes A and B).
- **TEST-15 red-first is mandatory** for every new check: exact failing input
  before green, plus a discrimination case that a vacuous implementation fails.
- Test command from `apps/prototype-description-service/`:
  `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -q`
  (plus the report-emit test named under Slice 4).

## Workflow Principles

- **Measurement before change.** Land scorers before (and independent of) the
  prompt edits they make measurable (EVAL-08, `canon/lexicons/ml-systems.md#eval-08`).
- **Williams vs C5 — both hold, different roles.** Williams governs the **gate**:
  do not hard-cap length; do not zero a long description for being long.
  C5 / playbook §3.1 governs the **ranking axis**: do not reward verbosity;
  rank on verified facts per 100 words. Density is a companion ranking column,
  never a length penalty on `gated_score`. Write this into the module docstring
  in Slice 3 so the two governing documents stop pointing opposite ways.
- **Attributive / bearer frame, not silence for affect.** Attributed readings
  ("her expression reads as anxious") are legitimate access content; unmarked
  person-as-fact-owner ("she is anxious") is the defect. The counter must
  distinguish them — that distinction *is* the discrimination test. Reserve
  the word **register** / `DescriptionRegister` for DEPICT-1 contract vocabulary
  (`FORENSIC | EDITORIAL | INTERPRETIVE`); do not reuse "register" for this
  grammar cut.
- **Verified numerator or the metric is wrong.** Unverifiable specificity
  scores zero, not one. A naive facts/100w that counts rare free nouns trips
  the reasoning card
  `controlled-vocabulary-caps-hallucination` and fails
  EVAL-11 (`canon/lexicons/ml-systems.md#eval-11`).
- **Delete over flag; report-only over gate.** First landing of each new
  counter is observational so false-positive shape can be measured on real
  captions before any gate decision.

## Terminology

- **Inner-state attribution**: a clause that makes a depicted person the
  grammatical owner of an interior state, will, trait, or essence no pixel can
  confirm ("she is anxious", "he wants", "they are proud"), with no attributive
  frame naming viewer, convention, artefact, or source.
- **Attributive frame / bearer frame**: a grammatical frame that moves ownership
  of the reading off the depicted person — e.g. "her expression reads as…",
  "appears…", "looks…", "seems…", "as if…", "read as…", "according to…".
  Same epistemic-hedge class (ATTRIB-01 cut: person-subject + mental predicate
  **without** appears / looks / seems / as-if / according-to). Not to be
  confused with DEPICT-1 `DescriptionRegister`.
- **Agentless passive / mutual-event noun**: oppression or violence prose that
  hides a record-supported actor behind passive voice ("were killed") or a
  symmetry noun ("a clash", "an incident") — the ATTRIB-08
  (`canon/lexicons/depiction.md#attrib-08`) trigger.
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
- `report.py` `_quality_block` (approx. L540–553) emits only
  `meta_framing_images`, context-duplication, name-front-loaded rate, and
  sentence-band stats; caption aggregate (approx. L565–574) has
  `mean_gated_score` and existing gate rates. No density or depiction-hit
  keys. Per-image rows (approx. L473–493) surface `meta_framing_hits` but not
  inner-state / agentless / density fields.
- `bakeoff.py` does **not** import `caption_metrics` today (verified by search).
  Bake-off ranking consumption of density remains a separate consumer after
  report emit lands; this plan owns report emit only (Slice 4), not bakeoff
  ranking logic.

## Target Outcome

1. Pure functions (and additive score fields where they fit the existing
   `CaptionScores` / aggregate pattern) that:
   - count inner-state-attribution hits (report-only);
   - list agentless-passive / mutual-event hits (report-only);
   - compute verified signal density as a ranking companion.
2. Module docstring resolves Williams (gate) vs C5 (ranking) in writing.
3. Every new assertion has a red-first proof and a discrimination case that
   rejects vacuous implementations.
4. `report.py` emits the new per-image hit lists and density numbers in its
   JSON quality / per-image sections (Slice 4 thin additive emit) so playbook
   §3.1 can rank on density. Bake-off ranking code that *consumes* those keys
   for ordering remains unowned by this task (explicit; not silently absorbed).

## Context Loading

Load before implementing any slice:

- Rules: `docs/workbay/rules/testing-python.md`,
  `docs/workbay/rules/backend-python-guidelines.md`,
  `docs/workbay/rules/development-workflow.md`
- Owned implementation:
  `apps/prototype-description-service/scripts/eval_harness/caption_metrics.py`
  and (Slice 4) thin emit in
  `apps/prototype-description-service/scripts/eval_harness/report.py`
- Owned tests:
  `apps/prototype-description-service/scene/tests/test_eval_harness_caption_metrics.py`
  (plus report-emit assertion under Slice 4)
- Manifest types already imported by the module:
  `scripts/eval_harness/manifest.py` (`ReferenceFact`, `FactKind`,
  `FactPolarity`) — **read-only adjacency**, not owned
- Governing assessment §§2, 6b, 6c, 10f, 10g
- Canon rows + distilled evidence named per slice below
- Reasoning cards (private canon paths; load if available, not monorepo links):
  `canon/public/reasoning/attribute-claims-to-their-bearer.md`,
  `canon/public/reasoning/controlled-vocabulary-caps-hallucination.md`,
  `canon/public/reasoning/signal-density-not-length.md`

## Contract and Boundary Impact

Strictly local pure scoring plus thin report JSON emit. No service, schema,
HTTP, or WP boundary change.

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Caption scoring pure API | Lane C (this task) | `score_caption` / `score_hallucination` in `caption_metrics.py` | additive fields + new pure functions | no — greenfield additive | unit tests below |
| Report JSON quality / per-image emit | Lane C (Slice 4) | `report.py` `_quality_block` + per-image rows read known `CaptionScores` fields | additive density + hit-list keys only | no — additive keys | Slice 4 report JSON key test |
| Bake-off ranking consumption | **unowned** by this task | `bakeoff.py` does not import `caption_metrics` | **none in this task** (keys available after Slice 4; ranking logic is a separate consumer) | n/a | explicit non-scope |

## Proposed Solution

Shape new detectors after the existing report-only meta-framing pattern: closed
phrase / grammar tables, word-boundary regex, hit lists on a score object, no
gate side-effects. Implement density as a separate pure function over
`(caption, reference_facts)` so it reuses the hallucination harness's authored
true-polarity facts as the verified set (PROV-01,
`canon/lexicons/ml-systems.md#prov-01` walkback) without re-deriving
fabrication. Document Williams/C5 in the module header so ranking and gate
cannot be collapsed. Emit the new fields from `report.py` (Slice 4) so the
GPU ranking window is not left closed behind pure APIs nobody calls.

### `CAL-02` and `PROV-01` — metric side only (scope decision)

Assessment §10f adds `CAL-02` abstain and `PROV-01` evidence-walkback on the
prompt+metric surface. Prompt side is out of this lane. Metric side:

| Rule | What existing metrics already cover | What would be new | Decision |
| --- | --- | --- | --- |
| PROV-01 (`canon/lexicons/ml-systems.md#prov-01` → `distilled/ml-systems/model-cards.md`) | `fabricated_fact_rate` catches known-false traps; `HallucinationScores.coverage` measures true-fact walkback | A **positive** walkback filter on density's numerator | **In scope as density definition**, not a second headline metric. Density counts only facts that walk back to true-polarity `ReferenceFact` match targets. Restating coverage as a new named metric is refused. |
| CAL-02 (`canon/lexicons/ml-systems.md#cal-02` → `distilled/ml-systems/designing-ml-systems.md`, Confidence measurement) | `score_hallucination` already scores the failure mode CAL-02 forbids when a trap is authored: forced precise wrong label under weak/no evidence | A true *abstain* rate needs weak-evidence fixtures and an explicit abstain surface ("unknown" / omitted precision) so correct abstention is distinguishable from lucky omission | **Scoped out of DEPICT-2.** A dedicated abstain counter would either restate fabrication (trap hit = failed abstain) or be vacuous without corpus annotations. Revisit when a weak-evidence / abstain fixture class exists. |

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
| report emit (Slice 4) | `apps/prototype-description-service/scripts/eval_harness/report.py` | Thin additive: emit density + depiction hit-list keys in per-image rows and quality block; no ranking logic, no gates |
| report tests (Slice 4) | existing report / harness test surface under `scene/tests/` (or adjacent harness test that builds report JSON) | Assert report JSON carries density / hit-list keys |

## Related Files

| File | Note |
| --- | --- |
| `scripts/eval_harness/manifest.py` | `ReferenceFact.match_targets()` is the density walkback primitive — read only |
| `scripts/eval_harness/bakeoff.py` | Ranking consumer of density; **unowned** here — does not import `caption_metrics` today; ranking logic that *orders* candidates by density is a separate consumer after Slice 4 keys exist |
| `docs/runbooks/fir-captioning-orchestrator-playbook.md` §3.1 | Density requirement; §3.2 stale |

### Cross-lane dependency

| File | Exact change needed | Who lands first |
| --- | --- | --- |
| `scripts/eval_harness/report.py` | Emit the new per-image hit lists and density number in JSON/markdown quality sections so the GPU window can rank on density | **Lane C, Slice 4 of this task** (after pure APIs Slices 1–3 are green); thin additive import of this module only — not a deferred orphan |
| Bake-off ranking order | Consume density key to rank survivors (playbook §3.1) | **unowned by DEPICT-2**; blocked until Slice 4 keys exist; do not declare bake-off ranking done when only pure APIs land |
| Lane A prompt emotion-bearer (DEPICT-4) | Prompt text change so attributed emotion is licensed | **After** Slice 1 counter exists (EVAL-08 ordering) |
| Lane B contracts / `DescriptionRegister` | None for DEPICT-2 metrics; a future register-compliance arm would read `DescriptionRegister` (`FORENSIC\|EDITORIAL\|INTERPRETIVE`) from the contract envelope — not planned here | n/a |

This plan does **not** edit bakeoff ranking, Lane A prompts, or Lane B contracts.

## Verification Strategy

- Deterministic tests (from `apps/prototype-description-service/`):
  - `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -q`
  - Per-slice filters as named under each slice Proof (Slices 1–3).
  - Slice 4: pytest filter asserting report JSON density / hit-list keys (see
    Slice 4 Proof).
- No runtime-parity / GPU / live endpoint required — pure CPU scoring + report
  dict emit.
- No contract/fixture boundary work.
- Manual: re-read module docstring after Slice 3 and confirm Williams (gate) and
  C5 (ranking) both appear as distinct roles, not a single averaged policy.
- GPU-window measurement emit is unblocked only after Slice 4 green; bake-off
  ranking sort remains unowned (see Cross-lane dependency).

## Slice Delivery

### Slice 1: Inner-state-attribution counter (report-only)

**Goal**: Count descriptions that make a depicted person the grammatical owner
of an interior state / will / trait the pixels cannot confirm — without gating.

**Canon**: ATTRIB-01 (`canon/lexicons/depiction.md#attrib-01`
→ distilled multi-source:
`canon/distilled/depiction/berger-ways-of-seeing.md` face-reading / spectator-owner
mechanisms; `sontag-on-photography.md`;
`berger-understanding-a-photograph.md`; card
`attribute-claims-to-their-bearer`). Supporting sequencing:
EVAL-08 (`canon/lexicons/ml-systems.md#eval-08`
→ `distilled/ml-systems/hidden-technical-debt-ml.md`).
Proof discipline: TEST-15 (`canon/lexicons/engineering.md#test-15`
→ `distilled/engineering/modern-software-engineering.md`).

**Distilled load-bearing residue used here**: Berger's face-reading mechanism
forbids treating the person as fact-owner of mental-state predicates without a
frame ("prefer visible cues… or frame the reading"); the card's required action
is "never make the depicted person fact-owner of will, essence…". Berger
verification recipe: pattern-match person-subject + mental predicate **without**
appears / as-if / according-to (and the same hedge class: looks / seems). The
attributive-frame / bearer-frame cut from assessment §2 item 5 is the
operational cut: attributed surface readings stay; unmarked ownership fails.
Do not call this cut "register" — `DescriptionRegister` is DEPICT-1 contract
vocabulary.

Changes:

- Add a closed interior-predicate / person-subject detector in
  `caption_metrics.py`, shaped after `_META_FRAMING_PHRASES` (phrase table +
  compiled regexes + hit list). Minimum detectable patterns (implementation may
  refine regex detail, not the discrimination contract):
  - person pronoun / common person noun subject + **unmarked** copula +
    interior adjective (`she is anxious`, `he is angry` — person as fact-owner
    of the mental predicate with no attributive / hedge frame);
  - person subject + will / intent verb (`she wants`, `he refuses` as interior
    will — not physical refusal with visible object when framed as action).
- **Must not fire** when an attributive / bearer frame or epistemic hedge owns
  the reading: `her expression reads as anxious`, `she looks anxious`,
  `appears anxious`, `he seems angry`, `as if anxious`, `read as anxious`,
  furrowed-brow **visible cue** inventory without mental-state ownership.
  `seems` is the same hedge class as `looks` / `appears` (ATTRIB-01 / Berger
  recipe); do **not** treat hedged readings as person-as-fact-owner.
- Surface hits as an additive report-only field (e.g.
  `CaptionScores.inner_state_attribution_hits: list[str]`) populated from
  `score_caption`, **or** a sibling pure function
  `score_inner_state_attribution(caption) -> list[str]` called by tests and
  later by report. Prefer extending `score_caption` only if the field stays
  zero-cost when absent; do not touch `gated_score`.
- Document in a short comment that this is report-only (LIBSYN-1 / F8) and that
  picture-in-picture style false positives are accepted at this stage the same
  way meta-framing accepts them.

Proof (TEST-15, `canon/lexicons/engineering.md#test-15`):

1. **Red-first input — copula / affect branch (must fail before implementation)**:
   - Caption: `"She is anxious beside the railing."`
   - Assert: at least one inner-state hit containing the anxious / interior
     ownership span. A no-op implementation returning `[]` fails.
2. **Red-first input — will / intent branch** (half of ATTRIB-01 surface;
   a no-op on will alone must not pass `-k inner_state`):
   - Caption: `"She wants to leave the railing."`
   - Assert: ≥1 hit on the will / intent ownership span. A detector that only
     covers copula+affect still fails this case.
3. **Discrimination case — attributive / bearer frame (vacuous detectors fail)**:
   - Clean / attributed: `"Her expression reads as anxious beside the railing."`
   - Assert: **zero** hits. An implementation that greps bare `anxious`
     anywhere fails this case — that is the point of the attributive-frame cut.
4. **Discrimination case — epistemic hedge `seems`** (locks the hedge class so
   it cannot flip to a false positive):
   - Caption: `"He seems angry beside the railing."`
   - Assert: **zero** hits. An implementation that treats `seems` like unmarked
     copula ownership fails this case.
5. **Discrimination case — will branch non-hit** (physical action / no interior
   ownership):
   - Caption: `"She reaches for the gate."`
   - Assert: **zero** hits. A detector that flags any person-subject verb fails.
6. **Visible-cue control**:
   - `"She stands with a furrowed brow and tight jaw."`
   - Assert: zero hits (inventory of visibles, no mental-state ownership).
7. **Command**:
   `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -k inner_state -q`

### Slice 2: Agentless-passive / mutual-event detector (report-only)

**Goal**: Pure-grammar detector for agentless passives and mutual-event nouns in
violence / oppression prose; no model, no context, no aggregate, no gate.

**Canon**: ATTRIB-08 (`canon/lexicons/depiction.md#attrib-08`
→ `canon/distilled/accessibility/anti-racist-description-resources.md`, named
mechanism **active voice** for oppressive relationships, L00205–L00216 Kent
State contrast). Proof: TEST-15 (`canon/lexicons/engineering.md#test-15`).

**Distilled load-bearing residue**: "Avoid passive voice… when describing
oppressive relationships. Use active voice in order to embed responsibility
within description." The Kent State pair is the discrimination template:
`"were killed … during a clash"` fails; `"Members of the Ohio National Guard
killed …"` passes.

Changes:

- Add phrase / pattern tables for:
  - **agentless passives** on violence/oppression verbs: e.g. `were killed`,
    `was killed`, `were beaten`, `was enslaved`, `were arrested` **without** a
    `by`-agent PP in the same clause;
  - **mutual-event / symmetry nouns**: e.g. `a clash`, `the clash`,
    `an incident`, `the incident` in violence contexts (closed list; do not
    generalise to every English passive).
- Surface as report-only hit list
  (`agentless_passive_hits` or sibling pure function). No `gated_score`
  change.
- **Scope (pure-grammar mode, locked)**: detector is grammar + closed
  violence/oppression lexicon, not a full voice tagger and not a compliance
  rewriter. A passive without a same-clause `by`-agent is a hit **even when**
  the caption also states a gap (`agent not named in the record`). Gap language
  does **not** zero the hit — ATTRIB-08's second branch ("state the gap rather
  than invent an agent") is a *rewrite* obligation for authors, not a detector
  non-fire. Do not implement a silent compliance-mode zeroing of gap-marked
  passives. Name the gap-language test so this choice cannot flip silently.

Proof (TEST-15, `canon/lexicons/engineering.md#test-15`):

1. **Red-first input**:
   - Caption: `"Four students were killed during a clash on campus."`
   - Assert: hits include an agentless-passive span **and** a mutual-event
     noun span (`clash`). Empty list fails.
2. **Discrimination case — active voice named agent**:
   - Caption: `"Members of the Ohio National Guard killed four students on campus."`
   - Assert: **zero** hits. A detector that flags any past-tense violence verb
     fails discrimination.
3. **Discrimination case — by-agent passive exemption**
   (`test_agentless_passive_by_agent_exempt` or equivalent name; locks the
   same-clause `by`-agent non-hit so a naive "any violence passive" detector
   fails):
   - Caption: `"Four students were killed by the Ohio National Guard on campus."`
   - Assert: **zero** agentless-passive hits (the clause names the actor via
     `by`). Mutual-event nouns are absent here so the whole hit list is empty.
   - Red-first edit that proves the assertion can fail: strip the `by the Ohio
     National Guard` PP → the agentless-passive span must appear (same shape as
     proof 1 without `clash`). A constant-empty implementation fails proof 1;
     a fire-on-any-passive implementation fails this case.
4. **Gap-language control (pure-grammar: still hits)**:
   - Caption: `"Four students were killed; the agent is not named in the record."`
   - Assert: ≥1 agentless-passive hit on `were killed`. Explicit gap language
     does **not** suppress the hit (see scope lock above). Test name must
     include `gap_language_still_hits` (or equivalent) so a compliance-mode
     flip that zeros the hit is a regression, not a silent reinterpretation.
5. **Command**:
   `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -k agentless_passive -q`

### Slice 3: Verified signal-density ranking axis + Williams/C5 resolution

**Goal**: Land **verified facts per 100 words** as a ranking companion (not a
gate), with the EVAL-11 / card guard that unverifiable specificity scores zero;
write the Williams/C5 resolution into the module docstring.

**Canon**:

- EVAL-11 (`canon/lexicons/ml-systems.md#eval-11`
  → `canon/distilled/ml-systems/ai-engineering.md`, mechanism
  **functional-and-rubric scoring**: open-ended generation has no exact-match
  oracle; the scorer must measure task success, not wording flash).
- PROV-01 (`canon/lexicons/ml-systems.md#prov-01`
  → `canon/distilled/ml-systems/model-cards.md`): every counted fact walks back
  to evidence — operationalised as true-polarity `ReferenceFact` membership.
- Reasoning cards (design warrants, not extra IDs):
  `signal-density-not-length` (C5 operationalisation; verified facts per 100
  words; unverifiable specificity → 0);
  `controlled-vocabulary-caps-hallucination` Verification list: *"Metric
  definition for attribute quality does not reward lexical rarity without
  membership or grounding."*
- Proof: TEST-15 (`canon/lexicons/engineering.md#test-15`).

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
2. **`score_signal_density(caption, *, reference_facts) -> SignalDensityScores`**
   — **mandated** frozen dataclass (or `NamedTuple`) with fields
   `verified_count: int`, `word_count: int`,
   `density_per_100w: float | None`. Do **not** return a bare `float`; every
   Slice 3 proof asserts the three fields, so a float return makes the stated
   tests unwritable.
   - `word_count` = existing `_WORD_RE` tokenisation (same as `score_caption`;
     `caption_metrics.py` L27: `re.compile(r"[A-Za-z']+")`).
   - `verified_count` = number of **distinct** true-polarity `ReferenceFact`
     rows whose `match_targets()` hit via `_contains` (reuse the dedupe
     identity pattern from `score_hallucination` so duplicate authored facts
     do not inflate the numerator).
   - **False-polarity traps never increment the numerator** (they are
     fabrication, already scored elsewhere).
   - `density_per_100w = (verified_count / word_count) * 100` when
     `word_count > 0`; **`density_per_100w is None` only when
     `word_count == 0`**.
   - Unmatched free text — including rare, precise-sounding nouns with no
     fact membership — contributes **zero** to `verified_count`.
3. Optional corpus helper `mean_signal_density(scores)` only if tests need it;
   not required for the first land.
4. **Extensible verified-term predicate**: the true-polarity `ReferenceFact`
   set is the verified predicate for this slice. Do **not** hard-code a colour
   catalogue. Comment that future bound-term providers (assessment §6d C7
   chain) plug in by authoring additional true-polarity facts — density itself
   does not import a vocabulary. No colour field.

Proof (TEST-15, `canon/lexicons/engineering.md#test-15`):

Tokenisation note (locked to `_WORD_RE`): `"A bicycle leans on a wall."` →
`['A','bicycle','leans','on','a','wall']` → **`word_count == 6`**; with one
verified fact, `density_per_100w == pytest.approx(100 / 6)` (≈ 16.667). Do
**not** assert 4 words or 25.0 — that parenthetical contradicted `_WORD_RE` and
could never go green.

1. **Red-first input (naive density must not ship)**:
   - Facts: one true fact `ReferenceFact(text="bicycle", kind=OBJECT,
     polarity=TRUE, phrases=["bicycle"])` (or the existing `_true_fact`
     helper shape at
     `test_eval_harness_caption_metrics.py` ~L380–381).
   - Caption: `"A bicycle leans on a wall."`
   - Assert: `verified_count == 1`, `word_count == 6`,
     `density_per_100w == pytest.approx(100 / 6)`.
   - Empty / wrong implementation fails. Red-first edit: drop the fact or
     replace caption with ungrounded text → `verified_count` must leave 1.
2. **Mandatory discrimination case — rare ungrounded noun must not raise the
   score** (assessment §10f / lane brief):
   - Same true fact set: only `bicycle` is verified membership.
   - **Grounded caption** `G`: `"A bicycle leans on a wall."`
     → `verified_count=1`, `word_count=6`,
     `density_per_100w == pytest.approx(100 / 6)`.
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
4. **False-trap control** (concrete; shape matches existing trap fixtures at
   `test_eval_harness_caption_metrics.py` ~L376–381 `_false_fact` /
   `_true_fact`):
   - Facts: true fact `bicycle` (`polarity=TRUE`, phrases `["bicycle"]`) **and**
     false-polarity trap `dog` (`polarity=FALSE`, phrases `["dog"]`).
   - Caption trap-only: `"A dog leans on a wall."`
     → `verified_count == 0` (false-polarity match must not increment numerator).
   - Caption paired: `"A bicycle and a dog lean on a wall."`
     → `verified_count == 1` (only the true fact counts; trap still contributes 0).
   - A no-op that always returns `verified_count=0` fails the paired case; an
     implementation that counts any matched phrase regardless of polarity fails
     the trap-only case (or pairs both as 2).
5. **Command**:
   `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -k signal_density -q`
6. **Docstring check** (lightweight): a test or review step confirms the module
   docstring contains both the Williams gate statement and the C5 ranking /
   density statement as distinct roles (string presence is enough; do not parse
   prose quality in pytest).

### Slice 4: Report emit of density + depiction hit lists (thin additive)

**Goal**: Close the orphaned-consumer gap. Playbook §3.1 makes density the
GPU-window ranking gate; pure scorers in `caption_metrics.py` that nobody
emits leave that gate closed. Own a **thin additive** emit in `report.py` so
report JSON carries the new keys. Do **not** implement bake-off ranking order
here (still unowned).

**Depends on**: Slices 1–3 pure APIs green.

**Owned paths for this slice only**:
- `apps/prototype-description-service/scripts/eval_harness/report.py`
- a test under `scene/tests/` (extend an existing report/harness test, or add a
  focused test) that builds report JSON and asserts the new keys

**Current emit (verified anchors)**:
- Per-image row ~L473–493: includes `meta_framing_hits`, not depiction hits /
  density.
- `_quality_block` ~L540–553: `meta_framing_images`, sentence band, etc. only.
- Caption aggregate ~L565–574: `mean_gated_score` and gate rates; no density.
- `bakeoff.py`: no `caption_metrics` import (ranking consumer remains unowned).

Changes (additive only; no gates, no thresholding, no ranking sort):

1. Where per-image `CaptionScores` (and density scores) are available, emit:
   - `inner_state_attribution_hits` (list; empty list when none),
   - `agentless_passive_hits` (list; empty list when none),
   - `signal_density` object or flat keys:
     `verified_count`, `word_count`, `density_per_100w`
     (mirror `SignalDensityScores` field names).
2. In corpus quality / caption aggregate sections, emit at least one
   density-related summary key (e.g. `mean_signal_density` over scored images
   with non-`None` density, or per-image density only if a corpus mean is not
   yet required — prefer mean when cheap) and image counts for non-empty hit
   lists, parallel to `meta_framing_images`.
3. Wire by **importing** the Slice 1–3 pure functions / fields from
   `caption_metrics`; do not re-implement detectors inside `report.py`.
4. Markdown human summary may mention the new numbers; JSON keys are the
   contract for the GPU ranking gate.

Proof (TEST-15):

1. **Red-first**: build a minimal report payload (or call the report builder)
   for a caption that scores non-zero density and/or non-empty hit lists under
   Slices 1–3 fixtures. Assert the report JSON (or the dict the report builder
   returns before write) **contains** the density keys and hit-list keys named
   above. A pre-Slice-4 `report.py` that only knows `meta_framing_hits` fails.
2. **Discrimination / vacuous emit**: a caption with zero hits and
   `verified_count == 0` still **has** the keys present (empty list / zero /
   0.0 or `None` per word_count rule) — absence of keys is a defect; presence
   with empty values is correct. An implementation that only adds keys when
   non-zero fails this case if the test requires key presence on clean rows.
3. **Command**: pytest filter covering the new report-emit test (name must
   include `report` and `density` or `depict` so it is selectable), e.g.
   `uv run --extra dev pytest scene/tests/ -k "report and (density or depict or inner_state or agentless)" -q`
   — exact path chosen by implementer; plan requires at least one assertion on
   report JSON keys.

**GPU-window unblock condition**: playbook §3.1 is unblocked for *measurement
emit* only after Slice 4 is green. Bake-off *ranking order* that sorts on
density remains a separate unowned consumer; say so rather than claiming the
full ranking gate is done.

## Consolidated Checklist

### Context and Ownership

- [ ] Loaded testing-python / backend-python / development-workflow rules.
- [ ] Confirmed owned paths: `caption_metrics.py`, caption-metrics tests,
      and Slice 4 thin `report.py` emit + report key test only; no bakeoff
      ranking, schemas, prompts, or `canon/` edits.
- [ ] Re-verified cited rule IDs with definition-anchor grep before
      implementation review.
- [ ] Relative markdown links resolve from `docs/tasks/depiction/` (no
      `../../docs/...` extra segment; no `../../../canon/...` links).

### Checklist for Slice 1: Inner-state-attribution counter

- [ ] Write red-first test: `"She is anxious beside the railing."` expects ≥1 hit.
- [ ] Write red-first will-branch test: `"She wants to leave the railing."` expects ≥1 hit.
- [ ] Write discrimination test: `"Her expression reads as anxious…"` expects 0 hits.
- [ ] Write hedge discrimination: `"He seems angry beside the railing."` expects 0 hits.
- [ ] Write will-branch non-hit: `"She reaches for the gate."` expects 0 hits.
- [ ] Write visible-cue control: furrowed brow / tight jaw → 0 hits.
- [ ] Implement detector + report-only surface in `caption_metrics.py`.
- [ ] Confirm `gated_score` unchanged on positive hits.
- [ ] Terminology: attributive/bearer frame only — not "register".
- [ ] `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -k inner_state -q` green.

### Checklist for Slice 2: Agentless-passive / mutual-event detector

- [ ] Write red-first test: `"Four students were killed during a clash on campus."` expects passive + clash hits.
- [ ] Write discrimination test: active-voice named agent → 0 hits.
- [ ] Write by-agent exemption test: `"Four students were killed by the Ohio National Guard on campus."` → 0 agentless-passive hits (named test).
- [ ] Lock gap-language pure-grammar behaviour: gap-marked agentless passive still hits (`gap_language_still_hits` or equivalent).
- [ ] Implement detector + report-only surface.
- [ ] Confirm no gate side-effect.
- [ ] `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -k agentless_passive -q` green.

### Checklist for Slice 3: Signal density + Williams/C5

- [ ] Write red-first density test: bicycle caption → `word_count == 6`,
      `verified_count == 1`, `density_per_100w == pytest.approx(100 / 6)`.
- [ ] Write mandatory rare-ungrounded discrimination pair (`vermilion velocipede` vs `bicycle`) with expected scores.
- [ ] Write padding/verbosity density drop test.
- [ ] Write false-trap control: trap-only dog caption → `verified_count == 0`;
      paired bicycle+dog → `verified_count == 1`.
- [ ] Implement `score_signal_density` → frozen `SignalDensityScores` (or NamedTuple)
      with `verified_count`, `word_count`, `density_per_100w` only — no bare float.
- [ ] Rewrite module docstring: Williams = gate, C5 = ranking axis.
- [ ] `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -k signal_density -q` green.
- [ ] Full metrics file:
      `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -q` green.

### Checklist for Slice 4: Report emit

- [ ] After Slices 1–3 green, add thin additive keys to `report.py` per-image and quality blocks.
- [ ] Write test asserting report JSON carries density + hit-list keys (present even when empty/zero).
- [ ] Confirm no new gate / threshold / bakeoff ranking sort.
- [ ] Report-emit pytest filter green.

### Review Readiness

- [ ] No new gate or threshold on first land.
- [ ] Every new assertion has red input + discrimination case in the same PR.
- [ ] Williams/C5 resolution is written in-module, not only in this plan.
- [ ] No colour IDs, no `FM-11`, no fabricated `REG`/`ICON`/`FRAM`/`SEL` IDs.
- [ ] Report emit owned by Slice 4; bake-off ranking order still explicit non-scope.
- [ ] Canon IDs cited as plain text with lexicon path, not monorepo markdown links.

## Stretch Goals

- [ ] Corpus-level `mean_signal_density` helper mirroring `insertion_rate` (if not already landed in Slice 3/4).
- [ ] Report-only rate helpers (`inner_state_image_rate`, `agentless_passive_image_rate`) once per-image fields exist — still no gates.
- [ ] Future **register-compliance** metric arm that reads DEPICT-1
      `DescriptionRegister` (`FORENSIC | EDITORIAL | INTERPRETIVE`) from the
      contract envelope — separate from the attributive/bearer-frame grammar cut
      in Slice 1; not planned in DEPICT-2.

## Success Criteria

- [ ] Inner-state counter fires on unmarked person-as-fact-owner mental-state and
      will prose and stays silent on attributive/bearer frames, epistemic hedges
      (`seems`/`looks`/`appears`), and visible-cue inventory.
- [ ] Agentless-passive detector fires on the Kent State failure shape, stays
      silent on named-agent active voice **and** same-clause `by`-agent passives,
      and still hits gap-marked agentless passives (pure-grammar mode).
- [ ] Signal density ranks grounded captions above rare-ungrounded and
      ornament-padded captions with equal or fewer verified facts; rare
      ungrounded nouns never raise the score; false-polarity traps never increment
      `verified_count`.
- [ ] `score_signal_density` returns the mandated multi-field score object
      (`word_count == 6` and `approx(100/6)` on the bicycle fixture).
- [ ] Module docstring states Williams (gate) and C5 (ranking) as distinct roles.
- [ ] Report JSON emits density + depiction hit-list keys (Slice 4).
- [ ] Metrics and report-emit tests green at branch HEAD.
- [ ] No files outside the owned paths (metrics + tests + Slice 4 report emit)
      modified.

## Not-Doing

- Prompt text / emotion-bearer edits (Lane A; DEPICT-4).
- Contract, schema, enum, `voice`, `DescriptionRegister`, bound-term fields
  (Lane B). Future register-compliance metric that would read
  `DescriptionRegister` is named only (Stretch); not implemented here.
- Bake-off ranking *order* / sort-by-density logic (`bakeoff.py` consumer) —
  **unowned** by this task; keys land in Slice 4 but ranking code does not.
- Colour vocabulary of any kind; `FM-11` citations; Lane D trigger work.
- Race warrant / parity gate (ATTRIB-06) — pass-level property; harness is
  per-image only.
- Thresholding or hard-gating any new counter on first land.
- Dedicated CAL-02 abstain-rate metric (would restate fabrication or be
  vacuous without weak-evidence fixtures) — see scope decision above.
- Second fabrication metric that restates `score_hallucination` /
  `fabricated_fact_rate` under a PROV-01 label — PROV-01 is carried as the
  density numerator's walkback definition only.
- Compliance-mode zeroing of agentless-passive hits when gap language is
  present (Slice 2 is pure-grammar; gap still hits by design).
- LLM-judge scoring, model training, non-deterministic axes.
