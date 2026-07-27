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
`caption_metrics.py` so prompt-side depiction work (Lanes A/B) becomes
measurable: an inner-state-attribution counter
(ATTRIB-01, `canon/lexicons/depiction.md#attrib-01`), an
agentless-passive / mutual-event detector
(ATTRIB-08, `canon/lexicons/depiction.md#attrib-08`), and a
**verified** signal-density ranking *measurement*
(EVAL-11, `canon/lexicons/ml-systems.md#eval-11`). Emit the new hit lists and
density from `report.py` (thin additive Slice 4) so density is a live report
axis. **§3.1 lands here as metric + report-axis** (assessment §6b/§6c:
`caption_metrics.py` density + Williams/C5 docstring + report emit) — that is
the last unlanded GPU-window gate and Lane C's owned unblock
(assessment §6b L284-290, §6e L344-348). Bake-off ranking *sort* that *orders*
candidates by density is an **optional follow-on consumer**, not the §3.1 /
GPU-window gate. Resolve the Williams/C5 length contradiction in the module
docstring so gate policy and ranking policy cannot be read as opposites.

## Problem Statement

The caption harness can already gate wrong names, score fabrication traps, and
flag meta-framing, but it cannot see the highest-value depiction safety signal
LIBSYN-1 named (inner-state attribution on a depicted person), cannot flag the
cheapest grammar failure in the depiction lexicon (agentless passive / "clash"
frames), and measures no signal density at all. Every length-correlated quality
axis therefore still rewards verbosity. Until these scorers exist, Lane A/B
prompt changes are unmeasurable — exactly what EVAL-08
(`canon/lexicons/ml-systems.md#eval-08`, CACE) forbids — and the GPU window
remains gated by playbook §3.1 (assessment §6b: §3.1 is the last unlanded
gate). Pure scorers alone are not enough: `report.py` today builds its quality
block from `meta_framing_hits` / sentence band / `mean_gated_score` only (see
Current State), so density must also be emitted there. **Landing the metric +
report-axis *is* landing §3.1** (assessment §6c Williams/C5 companion axis;
§6e Lane C owns it). Bake-off code that *sorts* survivors by density is an
optional follow-on, not a prerequisite for §3.1 or the GPU window.

## Constraints

- **Owned paths only** (exact set; no unbound "any test" path):
  `apps/prototype-description-service/scripts/eval_harness/caption_metrics.py`,
  `apps/prototype-description-service/scene/tests/test_eval_harness_caption_metrics.py`,
  and (Slice 4 only)
  `apps/prototype-description-service/scripts/eval_harness/report.py` plus the
  **reserved** report-emit test
  `apps/prototype-description-service/scene/tests/test_eval_harness_report_depiction.py`.
  No edits under any other path in this task. Do **not** edit
  `scene/tests/test_eval_harness_pipeline.py` (DEPICT-0) or any other shared
  harness test.
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
- Test commands from `apps/prototype-description-service/`:
  `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -q`
  and (Slice 4)
  `uv run --extra dev pytest scene/tests/test_eval_harness_report_depiction.py -q`.

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
  (`canon/lexicons/depiction.md#attrib-08`) trigger. Explicit same-clause
  unknown-agent / gap statements (`agent not named in the record`) are an
  ATTRIB-08 **exemption**, not a hit.
- **Verified fact (density numerator)**: a `ReferenceFact` with
  `polarity=FactPolarity.TRUE` (StrEnum value `"true"`, `manifest.py:81-91`)
  whose `match_targets()` hit the caption under the existing word-boundary
  matcher (`_contains`). Claims with no such membership hit contribute
  **zero** to the numerator, even if lexically rare or specific. (Operational
  membership only — not a PROV-01 citation.)
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
- `report.py` `_quality_block` (L540–553) emits only
  `meta_framing_images`, context-duplication, name-front-loaded rate, and
  sentence-band stats; caption aggregate (L565–574) has
  `mean_gated_score` and existing gate rates. No density or depiction-hit
  keys. Per-image row dict opens at L472 and the associated long-block emit
  runs through L517 (`report.py:472-517`): surfaces `meta_framing_hits` but
  not inner-state / agentless / density fields.
- `score_caption` is called with only names/traps/objects/roster/context
  (`report.py:398-406`); `reference_facts` is **not** passed. Manifest entry
  type exposes `reference_facts: list[ReferenceFact]`
  (`manifest.py:GoldenEntry` L359), but `score_run_record` receives entries as
  dicts (`report.py:320-327`) and never reads `entry["reference_facts"]` today.
- `bakeoff.py` does **not** import `caption_metrics` today (verified by search).
  A future bake-off *sort* by density is an optional follow-on after Slice 4
  keys exist; it is **not** the §3.1 / GPU-window gate (assessment §6b/§6e:
  Lane C unblocks the window by landing density metric + report axis).

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
   JSON quality / per-image sections (Slice 4 thin additive emit). Together
   with the pure density metric and Williams/C5 docstring (Slice 3), this
   **lands playbook §3.1** as metric + report-axis and unblocks the GPU window
   (assessment §6b L284-290, §6e L344-348). Bake-off ranking code that
   *orders* candidates by density remains an **optional unowned follow-on** —
   not the §3.1 gate (explicit; §3.1 = measurement + report axis, not sort).

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
  and (Slice 4, **new reserved file**)
  `apps/prototype-description-service/scene/tests/test_eval_harness_report_depiction.py`
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
| Caption scoring pure API | Lane C (this task) | `score_caption` / `score_hallucination` in `caption_metrics.py` | additive `CaptionScores` hit-list fields + sibling `score_signal_density` | no — greenfield additive | unit tests below |
| Report JSON quality / per-image emit | Lane C (Slice 4) | `report.py` `_quality_block` + per-image rows read known `CaptionScores` fields; no `reference_facts` wire | additive nested `signal_density` object + hit-list keys + quality mean/counts; wire facts → density | no — additive keys | `test_eval_harness_report_depiction.py` exact-value proofs |
| Bake-off ranking *sort* (optional follow-on) | **unowned** by this task | `bakeoff.py` does not import `caption_metrics` | **none in this task** (keys available after Slice 4; sort is optional, not the §3.1 gate) | n/a | explicit non-scope |

## Proposed Solution

Shape new detectors after the existing report-only meta-framing pattern: closed
phrase / grammar tables, word-boundary regex, hit lists on a score object, no
gate side-effects. Implement density as a separate pure function over
`(caption, reference_facts)` so it reuses the hallucination harness's authored
true-polarity facts as the verified set — an **operational** membership
predicate (true-polarity `ReferenceFact` + `_contains` hit), not a PROV-01
citation (PROV-01 obligates model/input lineage on outputs; see scope decision
below). Document Williams/C5 in the module header so ranking and gate cannot
be collapsed. Emit the new fields from `report.py` (Slice 4) so pure APIs are
not orphaned behind zero report consumers. Metric + report-axis **is** §3.1;
ranking *sort* remains an optional separate consumer, not the gate.

### `CAL-02` and density numerator — metric side only (scope decision)

Assessment §10f mentions `CAL-02` abstain and `PROV-01` evidence-walkback on
the prompt+metric surface. Prompt side is out of this lane. Metric side:

| Rule / topic | What existing metrics already cover | What would be new | Decision |
| --- | --- | --- | --- |
| Density numerator membership (operational; **no PROV-01 citation**) | `fabricated_fact_rate` catches known-false traps; `HallucinationScores.coverage` measures true-fact hit rate | A **positive** verified-membership filter on density's numerator | **In scope as density definition**, not a second headline metric and **not** a PROV-01 application. Density counts only true-polarity `ReferenceFact` rows whose `match_targets()` hit via `_contains`. PROV-01 (`canon/lexicons/ml-systems.md#prov-01` → `distilled/ml-systems/model-cards.md`) obligates model revision / preprocessing / threshold / source-observation lineage on emitted outputs — not gold-label membership for a density numerator — so it is **not cited** here. Restating coverage as a new named metric is refused. |
| CAL-02 (`canon/lexicons/ml-systems.md#cal-02` → `distilled/ml-systems/designing-ml-systems.md`, Confidence measurement) | `score_hallucination` already scores the failure mode CAL-02 forbids when a trap is authored: forced precise wrong label under weak/no evidence | A true *abstain* rate needs weak-evidence fixtures and an explicit abstain surface ("unknown" / omitted precision) so correct abstention is distinguishable from lucky omission | **Scoped out of DEPICT-2.** A dedicated abstain counter would either restate fabrication (trap hit = failed abstain) or be vacuous without corpus annotations. Revisit when a weak-evidence / abstain fixture class exists. |

**No canon warrant invented** for a second fabrication restatement. Explicitly
refusing a restated metric is preferred to citing `CAL-02` on a clone of
`fabricated_fact_rate`. **No PROV-01 citation** on density membership.

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
| metrics | `apps/prototype-description-service/scripts/eval_harness/caption_metrics.py` | Inner-state counter; agentless-passive detector; `score_signal_density` sibling pure function; Williams/C5 docstring resolution; additive `CaptionScores` hit-list fields |
| tests | `apps/prototype-description-service/scene/tests/test_eval_harness_caption_metrics.py` | Red-first + discrimination tests for every new pure signal (Slices 1–3) |
| report emit (Slice 4) | `apps/prototype-description-service/scripts/eval_harness/report.py` | Thin additive: wire `reference_facts` → `score_signal_density`; emit exact density object + hit-list keys in per-image rows and quality block; no ranking logic, no gates |
| report tests (Slice 4) | `apps/prototype-description-service/scene/tests/test_eval_harness_report_depiction.py` | **New reserved file** owned by DEPICT-2 only. Assert report JSON carries exact density object + hit-list keys **and values**. Do not extend DEPICT-0's `test_eval_harness_pipeline.py` or any other shared harness test. |

## Related Files

| File | Note |
| --- | --- |
| `scripts/eval_harness/manifest.py` | `ReferenceFact.match_targets()` is the density walkback primitive — read only |
| `scripts/eval_harness/bakeoff.py` | Optional future *sort* consumer of density; **unowned** here — does not import `caption_metrics` today; sort is **not** the §3.1 / GPU-window gate |
| `docs/runbooks/fir-captioning-orchestrator-playbook.md` §3.1 | Density metric + ranking-axis requirement; §3.2 stale. Lands via Slices 3–4 of this task (assessment §6b/§6e) |

### Cross-lane dependency

| File | Exact change needed | Who lands first |
| --- | --- | --- |
| `scripts/eval_harness/report.py` | Emit the new per-image hit lists and density number in JSON/markdown quality sections so density is a live report axis (completes §3.1 with Slice 3) | **Lane C, Slice 4 of this task** (after pure APIs Slices 1–3 are green); thin additive import of this module only — not a deferred orphan |
| Bake-off ranking *sort* (optional) | Optionally consume density key to order survivors | **unowned by DEPICT-2**; optional follow-on after Slice 4 keys exist; **not** the §3.1 / GPU-window gate (assessment §6b: §3.1 = density metric; §6e: Lane C unblocks GPU window) |
| Lane A prompt emotion-bearer (DEPICT-4) | Prompt text change so attributed emotion is licensed | **After** Slice 1 counter exists (EVAL-08 ordering) |
| Lane B contracts / `DescriptionRegister` | None for DEPICT-2 metrics; a future register-compliance arm would read `DescriptionRegister` (`FORENSIC\|EDITORIAL\|INTERPRETIVE`) from the contract envelope — not planned here | n/a |

This plan does **not** edit bakeoff ranking, Lane A prompts, or Lane B contracts.

## Verification Strategy

- Deterministic tests (from `apps/prototype-description-service/`):
  - `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -q`
  - Per-slice filters as named under each slice Proof (Slices 1–3).
  - Slice 4 (exact path):
    `uv run --extra dev pytest scene/tests/test_eval_harness_report_depiction.py -q`
- No runtime-parity / GPU / live endpoint required — pure CPU scoring + report
  dict emit.
- No contract/fixture boundary work.
- Manual: re-read module docstring after Slice 3 and confirm Williams (gate) and
  C5 (ranking) both appear as distinct roles, not a single averaged policy.
- §3.1 (metric + report-axis) is landed when Slices 3–4 are green; that
  unblocks the GPU window (assessment §6b/§6e). Bake-off ranking *sort*
  remains an optional unowned follow-on (see Cross-lane dependency).

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
  compiled regexes + hit list). **Frozen closed tables** (implementation may
  refine regex detail, **not** the member sets or the discrimination contract):

  ```python
  # Freeze these exact frozensets / tuples in caption_metrics.py (names may vary;
  # membership is the contract). Proofs parametrize ≥1 positive per member.
  _INNER_PERSON_PRONOUNS = ("she", "he", "they")
  _INNER_COMMON_PERSON_NOUNS = (
      "woman", "man", "child", "person", "girl", "boy",
  )  # EVERY member must have a positive; no open "…" tail
  _INNER_COPULA_AFFECT = ("anxious", "angry", "proud")  # copula + interior adj
  _INNER_WILL_VERBS = ("want", "refuse")  # stems; match 3sg -s too (wants/refuses)
  ```

  Minimum detectable patterns:
  - person pronoun / common person noun subject + **unmarked** copula +
    interior adjective from `_INNER_COPULA_AFFECT` (`she is anxious`,
    `he is angry`, `the person is proud` — person as fact-owner of the mental
    predicate with no attributive / hedge frame);
  - person subject + will / intent verb from `_INNER_WILL_VERBS`
    (`she wants`, `he refuses`, `they refuse` as interior will — not physical
    refusal with visible object when framed as action). Detector must match
    stem **and** 3sg (`want`/`wants`, `refuse`/`refuses`); proofs use both.
- **Must not fire** when an attributive / bearer frame or epistemic hedge owns
  the reading: `her expression reads as anxious`, `she looks anxious`,
  `appears anxious`, `he seems angry`, `as if anxious`, `read as anxious`,
  furrowed-brow **visible cue** inventory without mental-state ownership.
  `seems` is the same hedge class as `looks` / `appears` (ATTRIB-01 / Berger
  recipe); do **not** treat hedged readings as person-as-fact-owner.
- Surface hits as an additive report-only field on `CaptionScores`
  (`inner_state_attribution_hits: list[str]`, parallel to
  `meta_framing_hits` at `caption_metrics.py:115`) populated inside
  `score_caption`. Do **not** leave the surface shape open (no "or sibling
  pure function" fork for the hit list that report emits). A pure helper used
  internally by `score_caption` is fine; the report-facing field is the
  `CaptionScores` list. Do not touch `gated_score`.
- Document in a short comment that this is report-only (LIBSYN-1 / F8) and that
  picture-in-picture style false positives are accepted at this stage the same
  way meta-framing accepts them.
- **Subject branch locked**: detector must accept **both** every member of
  `_INNER_PERSON_PRONOUNS` **and** every member of
  `_INNER_COMMON_PERSON_NOUNS`. A pronoun-only regex is a [TEST-15] defect;
  a fixture-literal detector limited to `She is anxious` / `She wants` /
  `woman is anxious` / `child wants`, or to a single adjunct scaffold
  (`beside the railing` / `to leave the railing`), is also a defect —
  proofs below parametrize the full tables **and** vary scaffolds.
  Common-noun copula is the full noun × `_INNER_COPULA_AFFECT` product
  (not `anxious` alone).

Proof (TEST-15, `canon/lexicons/engineering.md#test-15`):

**Scaffold-variance lock (applies to every positive branch below).** Positives
must **not** share a single frozen adjunct / complement scaffold. A detector
implemented as a lookup table of `frozen-tables × {"… beside the railing.",
"… to leave the railing."}` is a [TEST-15] defect — it passes every
single-scaffold case while staying silent on grammar-equivalent prose with a
different adjunct/object (e.g. `"She is anxious near the window."`). Each
branch therefore requires ≥1 positive whose **only** shared structure with
the other positives is the grammar (person subject + unmarked predicate),
with a **different adjunct / object and no `"railing"`**.

1. **Red-first — copula / affect, parametrized over every pronoun × every
   `_INNER_COPULA_AFFECT` adjective** (must fail before implementation):
   - **Varied-scaffold templates** (use `is` for she/he, `are` for they;
     **no single shared adjunct**):
     - `"She is {adj} near the window."`
     - `"He is {adj} by the doorway."`
     - `"They are {adj} in the courtyard."`
     with `adj ∈ {anxious, angry, proud}` — full cartesian product (9
     captions). Do **not** reuse `"beside the railing"` as the sole scaffold.
   - Assert each: ≥1 hit on the interior ownership span. A no-op `[]` fails;
     a fixture-literal detector that only knows `"She is anxious beside the
     railing."` fails on `"He is proud by the doorway."` and on
     `"She is anxious near the window."`.
2. **Red-first — will / intent, parametrized over every pronoun × every
   `_INNER_WILL_VERBS` stem** (a no-op on will alone must not pass
   `-k inner_state`):
   - **Varied-scaffold positives** (parametrize; agreement forms as written;
     **no `"railing"` / no shared infinitival complement**):
     - `"She wants to open the gate."` / `"She refuses to answer the question."`
     - `"He wants to cross the street."` / `"He refuses to sign the paper."`
     - `"They want to leave the room."` / `"They refuse to join the crowd."`
   - Assert each: ≥1 hit on the will / intent ownership span. A detector that
     only covers copula+affect, only `want`/`wants` but not
     `refuse`/`refuses`, or only the old `"to leave the railing"` complement,
     fails.
3. **Discrimination — attributive / bearer frame, paired per affect family**
   (vacuous detectors fail):
   - For each `adj ∈ {anxious, angry, proud}`: clean / attributed caption
     `"Her expression reads as {adj} near the window."`
   - Assert each: **zero** hits. An implementation that greps bare affect
     adjectives anywhere fails — that is the point of the attributive-frame cut.
4. **Discrimination — epistemic hedges (`seems` / `looks` / `appears` /
   `as if`)** (locks the full hedge class named in Success Criteria so a
   single-token special case cannot pass):
   - Captions (each must return **zero** hits):
     - `"He seems angry near the window."`
     - `"She looks anxious by the doorway."`
     - `"He appears proud in the courtyard."`
     - `"She stands as if anxious near the gate."`
   - Assert each: **zero** hits. An implementation that treats any of these
     hedges like unmarked copula ownership fails the matching case. A suite
     that only proves `seems` / `reads as` does not satisfy this item.
5. **Discrimination — will branch non-hit** (physical action / no interior
   ownership):
   - Caption: `"She reaches for the gate."`
   - Assert: **zero** hits. A detector that flags any person-subject verb fails.
6. **Visible-cue control**:
   - `"She stands with a furrowed brow and tight jaw."`
   - Assert: zero hits (inventory of visibles, no mental-state ownership).
7. **Red-first — common person noun, copula / affect, parametrized over EVERY
   `_INNER_COMMON_PERSON_NOUNS` member × EVERY `_INNER_COPULA_AFFECT` member**
   (pronoun-only, partial-noun, and `anxious`-only detectors fail):
   - **Varied-scaffold templates** (cycle adjuncts; **no sole `"railing"`
     scaffold**; full cartesian product of 6 nouns × 3 affect adjs = 18
     captions). Example cycle (repeat pattern across the product):
     - `"The {noun} is anxious near the window."`
     - `"The {noun} is angry by the doorway."`
     - `"The {noun} is proud in the courtyard."`
     for each `noun ∈ {woman, man, child, person, girl, boy}`.
   - Assert each: ≥1 hit on the interior ownership span for that affect.
   - **Trivial cheating implementations that must fail**:
     - pronoun-only:
       `re.search(r"\b(she|he|they)\b.+\b(is|are)\b.+\b(anxious|angry|proud)\b", …)`
       — no `she`/`he`/`they` subject; returns `[]`.
     - fixture-literal limited to `woman` + `child` only — fails on
       `"The person is proud in the courtyard."` and
       `"The man is angry by the doorway."` (and `girl` / `boy`).
     - `anxious`-only common-noun copula (templates all fixed to `anxious`) —
       fails on every `angry` / `proud` common-noun case.
8. **Red-first — common person noun, will / intent, parametrized over EVERY
   common-person noun × EVERY will stem** (includes `refuse`/`refuses`):
   - **Varied-scaffold templates** (3sg surfaces; **no `"railing"`**):
     `"The {noun} wants to open the gate."` and
     `"The {noun} refuses to answer the question."` for each
     `noun ∈ {woman, man, child, person, girl, boy}`.
   - Assert each: ≥1 hit. A copula-only common-noun detector fails; a
     `want`/`wants`-only detector fails on every `refuses` case; a
     `"to leave the railing"`-only complement cheat fails these complements.
9. **Discrimination — attributed common-noun bearer frame, paired per noun**
   (common-noun subject + attributive frame must **not** hit):
   - Template: `"The {noun}'s expression reads as anxious near the window."`
     for each `noun ∈ {woman, man, child, person, girl, boy}` (possessive
     form as natural English allows; `"the child's expression…"` etc.).
   - Assert each: **zero** hits.
   - **Trivial cheating implementation that must fail**: flag any caption
     containing both a common person noun and `anxious` (no frame check).
     Each attributed reading has both and must still return `[]`.
10. **Permanent discrimination guard — subject class AND predicate class both
    required** (TEST-15 permanent mutation; a pure adjunct lookup still needs
    this so dropping either class goes red):
    - **Subject-class strip (must stay silent)**:
      `"The window is anxious near the garden."` and
      `"The chair wants to open the gate."`
      → assert **zero** hits (no person subject from either frozen subject
      table). An implementation that fires on bare `is {affect}` /
      `wants to …` without a person-subject class returns non-empty and fails.
    - **Predicate-class strip (must stay silent)**:
      `"She is standing near the window."` and
      `"The woman reaches for the gate."`
      → assert **zero** hits (person subject present; no frozen affect /
      will predicate). An implementation that fires on any person subject
      returns non-empty and fails.
    - **Positive scaffold outside any railing lookup** (must hit; kills the
      cartesian product of frozen tables × two railing scaffolds):
      `"She is anxious near the window."` → ≥1 hit (already in proof 1; keep
      as the permanent red-first mutation witness: hardcode-only-railing or
      drop subject/predicate class → this assertion goes red).
11. **Discrimination — mixed caption: hedged clause + separate unhedged
    inner-state clause** (kills whole-caption hedge suppression):
    - Caption: `"He seems angry near the window. She is anxious by the doorway."`
    - Assert: ≥1 hit covering the **unhedged** second clause
      (`She is anxious…`); the hedged first clause must not be the sole
      reason for silence.
    - **Trivial cheating implementation that must fail**:
      `if any(h in caption.lower() for h in ("seems","looks","appears","as if")): return []`
      (caption-wide hedge short-circuit). This caption contains `seems` and
      still must hit on the unhedged clause — the cheat returns `[]` and fails.
12. **Command**:
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

- Add phrase / pattern tables. **Frozen closed tables** (membership is the
  contract; proofs parametrize every member):

  ```python
  # Freeze these exact tuples in caption_metrics.py (names may vary).
  _AGENTLESS_PASSIVE_FORMS = (
      "was killed",
      "were killed",
      "were beaten",
      "was enslaved",
      "were arrested",
  )  # EVERY form must have a positive + same-clause by-agent negative
  _MUTUAL_EVENT_NOUNS = (
      "clash",
      "incident",
  )  # with determiner variants a/the/an as applicable; EVERY noun must have
     # a violence-context positive AND a benign-context negative
  _GAP_AGENT_PHRASES = (
      "agent not named in the record",
      "agent not in the record",
      "agent unknown",
  )  # ATTRIB-08 exemption: explicit unknown-agent statement
  ```

  - **agentless passives** on the frozen violence/oppression forms **without**
    a same-clause `by`-agent PP and **without** a same-clause gap-agent phrase
    from `_GAP_AGENT_PHRASES`;
  - **mutual-event / symmetry nouns** from `_MUTUAL_EVENT_NOUNS` in violence
    contexts only (closed list; do not generalise to every English passive).
- Surface as report-only hit list on `CaptionScores`
  (`agentless_passive_hits: list[str]`, parallel to `meta_framing_hits`).
  Same surface lock as Slice 1: report-facing field is the `CaptionScores`
  list, not an open "or sibling pure function" fork. No `gated_score` change.
- **Scope (ATTRIB-08-aligned grammar + gap exemption, locked)**: detector is
  grammar + closed violence/oppression lexicon, not a full voice tagger and
  not a compliance rewriter. Canon ATTRIB-08
  (`canon/lexicons/depiction.md#attrib-08`) and distilled
  `anti-racist-description-resources.md:29-30` treat
  "Agent truly unknown from the record → state unknown" as an **Exemption**,
  and the verification recipe requires "named agent OR explicit 'agent not in
  record'". Therefore:
  - A passive **without** a same-clause `by`-agent and **without** a
    same-clause gap-agent phrase is a hit.
  - An explicit same-clause unknown-agent / gap statement from
    `_GAP_AGENT_PHRASES` **does** exempt the passive (zero hit) — this is
    compliant ATTRIB-08 prose, not a violation. Do **not** flag captions that
    correctly state the gap.
  - Name the gap-language test so a pure-syntax flip that re-flags compliant
    gap prose is a regression.
- **Same-clause `by`-agent and violence-context locks** (proofs force both;
  adjacent-only substring cheats fail):
  - A `by`-agent PP in a **different** clause does **not** exempt a passive in
    this clause (same-clause requirement is real, not "any ` by ` substring").
  - A **non-adjacent** same-clause `by`-agent (material between the passive
    and the `by`-PP) **does** exempt.
  - Mutual-event nouns fire **only** in violence / oppression contexts from
    the closed list; a benign `"clash of colors"` / `"incident of paint"` must
    not hit.

Proof (TEST-15, `canon/lexicons/engineering.md#test-15`):

1. **Red-first — agentless passives, parametrized over EVERY
   `_AGENTLESS_PASSIVE_FORMS` member**:
   - Template: `"Four students {passive_form} on campus."` for each form in
     `{was killed, were killed, were beaten, was enslaved, were arrested}`.
   - Assert each: ≥1 agentless-passive hit covering that form. Empty list fails.
   - **Trivial cheating implementation that must fail**: hardcode only
     `"were killed"` (or only the two phrases used by a multi-signal fixture).
     Every other form must still hit.
2. **Red-first — mutual-event nouns, parametrized over EVERY
   `_MUTUAL_EVENT_NOUNS` member** (violence context):
   - Captions: `"Four students were killed during a clash on campus."` and
     `"Four students were killed during an incident on campus."`
   - Assert each: hits include an agentless-passive span **and** a mutual-event
     noun span (`clash` / `incident`). A detector that only knows `clash`
     fails on `incident`.
3. **Discrimination case — active voice named agent**:
   - Caption: `"Members of the Ohio National Guard killed four students on campus."`
   - Assert: **zero** hits. A detector that flags any past-tense violence verb
     fails discrimination.
4. **Discrimination — same-clause by-agent exemption, parametrized over EVERY
   passive form** (`test_agentless_passive_by_agent_exempt` or equivalent;
   locks the same-clause `by`-agent non-hit so a naive "any violence passive"
   detector fails):
   - **Adjacent form** (baseline): `"Four students {passive_form} by the Ohio
     National Guard on campus."` for each `_AGENTLESS_PASSIVE_FORMS` member.
   - Assert each: **zero** agentless-passive hits (the clause names the actor
     via `by`). Mutual-event nouns are absent so the whole hit list is empty.
   - Red-first edit: strip the `by the Ohio National Guard` PP → the
     agentless-passive span must appear. A constant-empty implementation fails
     proof 1; a fire-on-any-passive implementation fails this case.
5. **Discrimination — non-adjacent same-clause by-agent MUST exempt,
   parametrized over EVERY `_AGENTLESS_PASSIVE_FORMS` member**
   (`test_agentless_passive_nonadjacent_by_agent_exempt` or equivalent;
   kills form-specific `"were killed by"`-substring-only cheats that only
   handle one passive form or only the adjacent fixture in proof 4):
   - Template: `"Four students {passive_form} on campus yesterday by the Ohio
     National Guard during roll call."` for each
     `passive_form ∈ {was killed, were killed, were beaten, was enslaved,
     were arrested}`.
   - Assert each: **zero** agentless-passive hits. The `by`-agent PP is in the
     **same clause** as the passive but **not adjacent** to the verb (material
     `on campus yesterday` sits between). A detector that only checks the
     immediate `"were killed by"` bigram, or only hardcodes the single
     `"were killed … by the Ohio National Guard"` non-adjacent fixture, fails
     on e.g. `"was enslaved on campus yesterday by the Ohio National Guard…"`.
6. **Discrimination — different-clause `by` does NOT exempt**
   (`test_agentless_passive_unrelated_by_still_hits` or equivalent):
   - Caption: `"A report by a journalist says four students were killed on campus."`
   - Assert: ≥1 agentless-passive hit on `were killed` (the `by a journalist`
     PP modifies `report` in a **different** clause; it is **not** a
     same-clause agent of the passive).
   - **Trivial cheating implementation that must fail**:
     `if " by " in caption: return []; flag "were killed"`. This caption
     contains ` by ` and still must hit — the cheat returns `[]` and fails.
7. **Gap-language exemption (ATTRIB-08 compliant prose → zero hit),
   parametrized over EVERY `_GAP_AGENT_PHRASES` member**
   (`test_agentless_passive_gap_language_exempt` or equivalent):
   - Template (explicit same-clause unknown-agent statement) for each
     `gap ∈ {agent not named in the record, agent not in the record,
     agent unknown}`:
     `"Four students were killed ({gap}) on campus."`
   - Assert each: **zero** agentless-passive hits. Distilled exemption
     (`anti-racist-description-resources.md:29-30`) and ATTRIB-08's
     "state the gap rather than invent an agent" make this compliant, not a
     violation.
   - **Trivial cheating implementations that must fail**:
     - fire on every `were killed` regardless of gap phrase (pure-syntax
       counter with no ATTRIB-08 exemption);
     - hardcode only the single string
       `"agent not named in the record"` — fails on
       `"agent not in the record"` and `"agent unknown"`.
   - Companion red-first (no gap phrase): `"Four students were killed on campus."`
     still hits (proof 1) so a constant-empty "always exempt" cheat fails.
7b. **Different-clause / prior-sentence gap does NOT exempt**
   (`test_agentless_passive_gap_different_clause_still_hits` or equivalent;
   mirrors proof 6's different-clause `by` lock; kills whole-caption substring
   exemption):
   - Caption: `"Agent unknown. Four students were killed on campus."`
     (also parametrize the prior-sentence gap over the other two phrases:
     `"Agent not in the record. Four students were killed on campus."` and
     `"Agent not named in the record. Four students were killed on campus."`).
   - Assert each: ≥1 agentless-passive hit on `were killed`. The gap phrase is
     in a **prior sentence / different clause**, not a same-clause exemption
     on the passive.
   - **Trivial cheating implementation that must fail**:
     `if any(g in caption.lower() for g in _GAP_AGENT_PHRASES): return []`
     (whole-caption substring exemption). Production consequence of the cheat:
     `"Agent unknown. Four students were killed on campus."` would be wrongly
     silent — this proof forces the hit.
8. **Violence-context discrimination — benign mutual-event nouns, parametrized
   over EVERY `_MUTUAL_EVENT_NOUNS` member**
   (`test_agentless_passive_benign_mutual_event_no_hit` or equivalent):
   - Captions: `"A clash of colors fills the poster."` and
     `"An incident of paint stains the canvas."`
   - Assert each: **zero** mutual-event hits (and zero hits overall). Neither
     noun is a violence / oppression frame here.
   - **Trivial cheating implementation that must fail**:
     `if re.search(r"\b(clash|incident)\b", caption, re.I): return [match]`
     (no violence-context gate). These benign captions must return `[]`.
9. **Command**:
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
- **Density numerator membership is operational, not a PROV-01 citation.**
  PROV-01 (`canon/lexicons/ml-systems.md#prov-01` →
  `distilled/ml-systems/model-cards.md`) obligates model/input lineage on
  emitted outputs ("Can this output be reproduced after the model changes?") —
  it does **not** govern gold-label membership for a density numerator. Do
  **not** cite PROV-01 as the warrant for true-polarity `ReferenceFact`
  filtering. The verified set is defined operationally: true-polarity
  `ReferenceFact` rows whose `match_targets()` hit via `_contains`.
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
   — **mandated sibling pure function** (not a `CaptionScores` field; density
   needs `reference_facts`, which `score_caption` does not take — see
   `score_caption` signature at `caption_metrics.py:191-201`). Frozen
   dataclass (or `NamedTuple`) with fields `verified_count: int`,
   `word_count: int`, `density_per_100w: float | None`. Do **not** return a
   bare `float`; every Slice 3 proof asserts the three fields, so a float
   return makes the stated tests unwritable.
   - `word_count` = existing `_WORD_RE` tokenisation (same as `score_caption`;
     `caption_metrics.py` L27: `re.compile(r"[A-Za-z']+")`).
   - `verified_count` = number of **distinct** true-polarity `ReferenceFact`
     rows whose `match_targets()` hit via `_contains`. Dedupe identity is
     **exactly** the `score_hallucination` pattern at
     `caption_metrics.py:409-414`:
     `(fact.text, fact.kind, fact.polarity, tuple(fact.phrases))` — a
     duplicated reference fact must not double-count. Proof 5 forces this.
   - **False-polarity traps never increment the numerator** (they are
     fabrication, already scored elsewhere).
   - `density_per_100w = (verified_count / word_count) * 100` when
     `word_count > 0`; **`density_per_100w is None` only when
     `word_count == 0`** (empty / whitespace-only caption → `word_count == 0`
     under `_WORD_RE`; proof 6 forces this).
   - Unmatched free text — including rare, precise-sounding nouns with no
     fact membership — contributes **zero** to `verified_count`.
3. Optional pure corpus helper
   `mean_signal_density(scores: Sequence[SignalDensityScores]) -> float | None`
   may land in `caption_metrics.py` if useful for unit tests; Slice 4 defines
   the **report** aggregation independently (exact schema locked there).
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
5. **Dedupe control — four-field identity**
   (locks `score_hallucination` identity at `caption_metrics.py:409-415`:
   `(fact.text, fact.kind, fact.polarity, tuple(fact.phrases))`).
   Four cases; a `seen` set keyed on `fact.text` alone fails 5b/5c while
   still passing 5a; a three-field `(text, kind, phrases)` key fails 5d while
   still passing 5a–5c:

   - **5a. Identical rows count once** (retain; DO NOT BREAK arithmetic):
     - Facts: **two** identical true-polarity rows
       `ReferenceFact(text="bicycle", kind=OBJECT, polarity=TRUE,
       phrases=["bicycle"])` (same text/kind/polarity/phrases twice).
     - Caption: `"A bicycle leans on a wall."`
     - Assert: `verified_count == 1` (not 2), `word_count == 6`,
       `density_per_100w == pytest.approx(100 / 6)`.
     - **Trivial cheating implementation that must fail**:
       `verified_count = sum(1 for fact in reference_facts if fact.polarity is
       TRUE and any(_contains(caption, t) for t in fact.match_targets()))`
       with **no `seen` set**. Two identical rows both match → returns 2.

   - **5b. Same `text`, different `kind` — both count when matched**:
     - Facts:
       `ReferenceFact(text="bicycle", kind=OBJECT, polarity=TRUE,
       phrases=["bicycle"])` **and**
       `ReferenceFact(text="bicycle", kind=SCENE, polarity=TRUE,
       phrases=["bicycle"])` (same text/polarity/phrases; `kind` differs —
       `FactKind.OBJECT` vs `FactKind.SCENE` at `manifest.py:70-78`).
     - Caption: `"A bicycle leans on a wall."` (both `match_targets()` hit).
     - Assert: `verified_count == 2` (not 1). A `seen` set keyed only on
       `fact.text` collapses these to 1 and fails.

   - **5c. Same `text`, different `phrases` — both count when matched**:
     - Facts:
       `ReferenceFact(text="vehicle", kind=OBJECT, polarity=TRUE,
       phrases=["bicycle"])` **and**
       `ReferenceFact(text="vehicle", kind=OBJECT, polarity=TRUE,
       phrases=["wall"])` (same text/kind/polarity; `phrases` differ).
     - Caption: `"A bicycle leans on a wall."` (first matches via `bicycle`,
       second via `wall`).
     - Assert: `verified_count == 2` (not 1). A text-only `seen` set
       collapses these to 1 and fails; the four-field identity keeps both.

   - **5d. Same `text`/`kind`/`phrases`, different `polarity` — both survive
     dedupe** (locks the fourth identity field; `score_hallucination` at
     `caption_metrics.py:409-415` keys `seen` on
     `(text, kind, polarity, phrases)` and that set gates **both** the
     FALSE-polarity trap branch and the covered/missing branch, so polarity
     **is** observable — density must use the same four-field key):
     - Facts **in this order** (FALSE first so a three-field `seen` collapses
       the TRUE):
       1. `ReferenceFact(text="bicycle", kind=OBJECT, polarity=FALSE,
          phrases=["bicycle"])` (trap)
       2. `ReferenceFact(text="bicycle", kind=OBJECT, polarity=TRUE,
          phrases=["bicycle"])` (verified membership)
     - Caption: `"A bicycle leans on a wall."` (both `match_targets()` hit).
     - Assert on `score_signal_density`:
       - `verified_count == 1` (the TRUE fact is still scored; not dropped)
       - `word_count == 6`, `density_per_100w == pytest.approx(100 / 6)`
     - Optional companion assert on `score_hallucination` with the same facts
       (proves polarity observability on the identity pattern the density
       scorer mirrors): `trap_count == 1` **and** `"bicycle"` ∈
       `covered_facts` (or equivalent coverage of the TRUE row) **and**
       fabrication list non-empty for the trap. Both rows must survive;
       collapsing either loses a trap count or a verified hit.
     - **Trivial cheating implementation that must fail**:
       `seen` keyed on `(fact.text, fact.kind, tuple(fact.phrases))`
       (polarity omitted). With FALSE first, the TRUE row is skipped →
       `verified_count == 0` (and `trap_count` alone would pass a
       trap-only check while silently losing the TRUE). Four-field identity
       keeps both.
     - **Red-first mutation**: reorder is already fixed (FALSE then TRUE);
       dropping `polarity` from the `seen` key makes
       `assert verified_count == 1` go red. Permanent discrimination guard:
       keep 5d in the suite so a future three-field refactor fails here.
6. **Empty / whitespace caption — density is None, not 0.0**
   (locks `density_per_100w is None iff word_count == 0`):
   - Facts: one true fact `bicycle` (same as proof 1).
   - Caption: `""` **and** a second parametrize case `"   \n\t  "`
     (whitespace-only; `_WORD_RE` yields no tokens → `word_count == 0`).
   - Assert for both: `word_count == 0`, `verified_count == 0`,
     `density_per_100w is None`.
   - **Trivial cheating implementation that must fail**:
     `density_per_100w = 0.0 if word_count == 0 else …` (treats empty as zero
     density). Assertion `is None` kills it. Also kills a hard-coded
     `verified_count=1` that ignores the empty caption.
7. **Command**:
   `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -k signal_density -q`
8. **Docstring check** (lightweight): a test or review step confirms the module
   docstring contains both the Williams gate statement and the C5 ranking /
   density statement as distinct roles (string presence is enough; do not parse
   prose quality in pytest).

### Slice 4: Report emit of density + depiction hit lists (thin additive)

**Goal**: Close the orphaned-consumer gap for *measurement*. Pure scorers in
`caption_metrics.py` that nobody emits leave density numbers unreachable.
Own a **thin additive** emit in `report.py` so report JSON carries the new
keys **with live values**. Together with Slice 3 this **lands playbook §3.1**
(metric + report-axis; assessment §6b/§6c/§6e) and unblocks the GPU window.
Do **not** implement bake-off ranking *sort* here — that remains an optional
unowned follow-on, **not** the §3.1 gate.

**Depends on**: Slices 1–3 pure APIs green.

**Owned paths for this slice only** (exact; no unbound path):
- `apps/prototype-description-service/scripts/eval_harness/report.py`
- `apps/prototype-description-service/scene/tests/test_eval_harness_report_depiction.py`
  (**new reserved file** — DEPICT-2 only).
  The existing shared harness test
  `scene/tests/test_eval_harness_report.py` **exists** and already calls
  `score_run_record` (see that file's `_run_record` / `_manifest_entries`
  helpers and `test_score_run_record_shapes`). It remains
  **DELIBERATELY UNEDITED** by this task to avoid ownership collision with
  other harness owners. Do not extend `test_eval_harness_pipeline.py` /
  DEPICT-0 either. All DEPICT-2 report-emit proofs live only in the new
  reserved file.

**Current emit (verified anchors, open the file)**:
- Per-image row dict + long-block emit: `report.py:472-517` — includes
  `meta_framing_hits` (L486), not depiction hits / density.
- `_quality_block`: `report.py:540-553` — `meta_framing_images`, sentence band,
  etc. only.
- Caption aggregate: `report.py:565-574` — `mean_gated_score` and gate rates;
  no density.
- `score_caption` call site: `report.py:398-406` builds `score_kwargs` with
  names/traps/objects/roster/context only — **no `reference_facts`**.
- `short_error` path: `report.py:412-417` — `scores` starts `None` and is
  only populated when `short_error is None`; the per-image row is still built
  at `report.py:472-517` (and stamps `row["short_error"]` at L496-497).
- Manifest adjacency: `GoldenEntry.reference_facts` at `manifest.py:359`;
  `score_run_record` takes `manifest_entries: list[dict]` (`report.py:320-327`)
  so facts arrive as dicts and must be re-validated via
  `ReferenceFact.model_validate`.
- `FactPolarity` is a **StrEnum** (`manifest.py:81-91`) with values
  `"true"` / `"false"`; `ReferenceFact.polarity` uses it under
  `extra="forbid"` (`manifest.py:209-223`). JSON fixtures must use
  `"polarity": "true"` (string), **not** boolean `true`.
- `bakeoff.py`: no `caption_metrics` import (ranking consumer remains unowned).

#### Locked report JSON schema (exact; no "or flat keys" fork)

**Per-image row** (additive keys on the dict opened at `report.py:472`; when
`scores is None` because of `short_error`, emit the same keys with
`None` / empty values as noted):

| Key | Type when scored | Type when `scores is None` |
| --- | --- | --- |
| `inner_state_attribution_hits` | `list[str]` (from `scores.inner_state_attribution_hits`) | `[]` (key always present; empty list, never omit) |
| `agentless_passive_hits` | `list[str]` (from `scores.agentless_passive_hits`) | `[]` (key always present) |
| `signal_density` | **nested object** (not flat keys): `{ "verified_count": int, "word_count": int, "density_per_100w": float \| null }` | `{ "verified_count": 0, "word_count": 0, "density_per_100w": null }` |

`signal_density` is **always** the nested object mirroring `SignalDensityScores`
field names. Density is computed by the **sibling pure function**
`score_signal_density` (Slice 3) — **not** a `CaptionScores` field.

**Quality / corpus block** (additive keys on `_quality_block` return at
`report.py:540-553`, parallel to `meta_framing_images`):

| Key | Type | Definition |
| --- | --- | --- |
| `inner_state_attribution_images` | `int` | `sum(1 for s in scores if s.inner_state_attribution_hits)` |
| `agentless_passive_images` | `int` | `sum(1 for s in scores if s.agentless_passive_hits)` |
| `mean_signal_density` | `float \| null` | Mean of per-image `density_per_100w` over the retained density list (see denominator below) |

**Aggregation denominator (locked)**: retain a per-image list
`density_scores: list[SignalDensityScores]` for every short-surface caption
that was scored (same loop iteration that calls `score_caption` when
`short_error is None`). Then:

```
non_none = [d.density_per_100w for d in density_scores if d.density_per_100w is not None]
mean_signal_density = round(sum(non_none) / len(non_none), 4) if non_none else None
```

Denominator = count of scored short-surface images with `word_count > 0`
(equivalently `density_per_100w is not None`). Empty corpus or all-empty
captions → `mean_signal_density is None`. Do **not** ship "per-image density
only" without the quality-level mean key. Proofs 4–5 force multi-image
aggregation (a single-image fixture cannot prove the mean).

Changes (additive only; no gates, no thresholding, no ranking sort):

1. **Import** from `caption_metrics`:
   `score_signal_density` (and `ReferenceFact` from `manifest` if not already
   imported). Do not re-implement detectors inside `report.py`.
2. **Wire `reference_facts` at the call site**:
   - **Init** (with the other accumulators near `caption_scores: list[CaptionScores] = []`
     at `report.py:335`):
     `density_scores: list[SignalDensityScores] = []`
     (import `SignalDensityScores` from `caption_metrics` alongside
     `score_signal_density`).
   - **Per item** (inside the `for item in run_record["items"]` loop, after
     `entry` is resolved and the short caption is available — next to
     `score_caption` at L416–417, only on the `short_error is None` path):

     ```python
     facts = [
         ReferenceFact.model_validate(f)
         for f in entry.get("reference_facts", [])
     ]
     density = score_signal_density(caption, reference_facts=facts)
     density_scores.append(density)  # retain for quality aggregation
     ```

   When `short_error is not None` (no short caption scored), do **not** append
   a density score and do **not** read an uninitialised `density` variable;
   emit the empty/zero `signal_density` object on the row (table above).
   `entry.get("reference_facts", [])` is required because entries arrive as
   dicts (`score_run_record` signature
   `manifest_entries: list[dict[str, Any]]` at `report.py:320-327`), not as
   `GoldenEntry` models.
3. **Per-image emit** (extend the row dict at `report.py:472-517`):
   - `"inner_state_attribution_hits": scores.inner_state_attribution_hits if scores is not None else []`
   - `"agentless_passive_hits": scores.agentless_passive_hits if scores is not None else []`
   - `"signal_density": {"verified_count": density.verified_count, "word_count": density.word_count, "density_per_100w": density.density_per_100w}`
     when a short caption was scored; else the empty/zero object
     `{"verified_count": 0, "word_count": 0, "density_per_100w": None}`.
     Initialise `density = None` before the `short_error` branch (or branch
     the emit) so the `scores is None` path never reads an unbound name.
4. **Quality block emit** (extend `_quality_block` or the quality dict that
   consumes it): add `inner_state_attribution_images`,
   `agentless_passive_images`, and `mean_signal_density` per the locked schema
   and denominator above. `mean_signal_density` needs the retained
   `density_scores` list — pass it in or compute beside `_quality_block`.
5. Markdown human summary may mention the new numbers; the JSON keys above are
   the contract for the §3.1 report-axis emit. No other key shape is permitted.
   Bake-off ranking *sort* is out of scope (optional follow-on, not the gate).

#### Minimal fixture shape (locked; proof-green from plan text alone)

Shape mirrors the existing helpers in
`scene/tests/test_eval_harness_report.py:32-114` (`_run_record` /
`_manifest_entries`) plus the `reference_facts` key and `short_error` stamp.
`score_run_record` reads these keys as **dicts** (not `GoldenEntry` models);
fields below are the minimum the scorer path actually touches.

**Run-record skeleton** (one or more items; multi-image proofs extend `items`):

```python
{
    "schema": "acx-eval/v1",           # SCHEMA at schema.py:13
    "kind": "run_record",              # DocKind.RUN_RECORD
    "provenance": {
        "manifest_sha256": "m" * 64,
        "base_url": "https://api.example.com",
        "head_sha": "0" * 40,
        "started_at": "2026-07-06T00:00:00Z",
        # omit eval_mode → defaults to "standard" (report.py:330)
    },
    "items": [
        {
            "media_id": 1,             # int; must match a manifest entry
            "path": "mock_images/depict-1.jpg",
            "describe": {
                "alt_text_draft": "<caption under test>",
                "visual_facts": {"objects": []},
                "adapter": "seeded",
                "model_id": "seeded-fixtures",
                "model_version": "1",
                "cached": False,
                # optional: "short_error": "<msg>"  # scores stays None (report.py:412-417)
            },
            "identities": [],
            "face_count": 0,
            "error": None,             # non-None → failures path, skip scoring
        },
    ],
}
```

**Manifest entry skeleton** (one dict per `media_id`; keys `score_run_record`
actually reads — see `report.py:366-406, 454`):

```python
{
    "path": "mock_images/depict-1.jpg",
    "media_id": 1,
    "face_count": 0,                   # required (report.py:454); int
    "present_identities": [],          # list[str]
    "must_right": [],                  # list[str]
    "easy_wrong": [],                  # list[str]
    "policy": {"recognition_enabled": True},  # EntryPolicy; required
    "reference_facts": [               # optional; default []
        {
            "text": "bicycle",
            "kind": "object",          # FactKind.OBJECT value
            # FactPolarity is StrEnum — string "true", NOT boolean true
            # (manifest.py:81-91, 209-223; extra="forbid")
            "polarity": "true",
            "phrases": ["bicycle"],
        },
    ],
}
```

**Pre-score validation gate** (required in every proof that uses
`reference_facts`): before calling `score_run_record`, assert

```python
from scripts.eval_harness.manifest import ReferenceFact
for f in entry["reference_facts"]:
    ReferenceFact.model_validate(f)  # must succeed; boolean polarity must NOT
```

so a drifted fixture fails at the proof, not inside an opaque report error.

Proof (TEST-15) — file
`scene/tests/test_eval_harness_report_depiction.py` only:

Build fixtures from the locked skeletons above and call `score_run_record`.
Do **not** assert key presence alone.

1. **Red-first — non-zero fixture, exact values**
   (`test_report_emit_depiction_nonzero_values` or equivalent):
   - Manifest entry carries one true `reference_facts` row for `bicycle`
     with **`"polarity": "true"`** (string; see skeleton). Assert
     `ReferenceFact.model_validate` succeeds on that row before scoring.
   - Run-record item caption (short surface):
     `"She is anxious. A bicycle leans on a wall. Four students were killed during a clash."`
     (preferred: **one image** with a caption that trips inner-state +
     agentless-passive + density together, so a single row carries all keys).
   - Assert on `report["per_image"][0]`:
     - `"anxious"` (or the detector's hit span string) ∈
       `inner_state_attribution_hits` (non-empty; exact span membership as
       returned by the Slice 1 detector).
     - agentless-passive hit list is non-empty and includes a span covering
       `were killed` **and** a mutual-event span covering `clash`.
     - `signal_density == {"verified_count": 1, "word_count": <exact _WORD_RE
       count of that caption>, "density_per_100w": pytest.approx(100 *
       1 / word_count)}`.
   - Assert on `report["quality"]`:
     - `inner_state_attribution_images == 1`
     - `agentless_passive_images == 1`
     - `mean_signal_density == pytest.approx(per-image density_per_100w)`
   - **Red before Slice 4**: pre-emit `report.py` raises `KeyError` or fails
     equality on missing keys.
   - **Trivial cheating implementation that must fail**:
     ```python
     row["inner_state_attribution_hits"] = []
     row["agentless_passive_hits"] = []
     row["signal_density"] = {
         "verified_count": 0, "word_count": 0, "density_per_100w": None
     }
     ```
     (unconditional empty/zero emit). Exact-value asserts above fail.
   - **Mutation that provably flips the report assertion**: after a correct
     wire-up, change the fixture caption's verified noun from `bicycle` to
     `velocipede` (no matching true fact) **or** monkeypatch
     `score_signal_density` to return `verified_count=0` — the report
     assertion `verified_count == 1` must fail. This proves the report reads
     live scorer output, not a hardcoded literal.
2. **Discrimination — clean fixture, exact empty/zero values**
   (`test_report_emit_depiction_clean_zeros` or equivalent):
   - Caption: `"A red bicycle leans on a wall."` with **empty**
     `reference_facts` (and no inner-state / agentless patterns).
   - Assert on `report["per_image"][0]`:
     - `inner_state_attribution_hits == []`
     - `agentless_passive_hits == []`
     - `signal_density == {"verified_count": 0, "word_count": 7,
       "density_per_100w": 0.0}`
       (`_WORD_RE` on that caption → 7 tokens: A red bicycle leans on a wall).
   - Assert on `report["quality"]`:
     - `inner_state_attribution_images == 0`
     - `agentless_passive_images == 0`
     - `mean_signal_density == 0.0` (one scored image with non-`None` density).
   - **Trivial cheating implementation that must fail**: omit the keys entirely
     on clean rows, **or** emit non-empty hit lists / non-zero
     `verified_count` unconditionally. Key-present + exact-empty asserts kill
     both.
3. **`scores is None` / `short_error` branch — exact fallback keys and values**
   (`test_report_emit_depiction_short_error_fallback` or equivalent):
   - One-item fixture; `describe` carries
     `"short_error": "RemoteClientError: POST /v1/chat/completions failed: 500"`
     and **no** usable short caption (omit `alt_text_draft` or leave it
     unused — `report.py:412-417` skips `score_caption` when `short_error` is
     set). Manifest entry may still carry `reference_facts`; they must not be
     scored on the short surface.
   - Assert on `report["per_image"][0]`:
     - `"short_error"` key present (stamped at `report.py:496-497`)
     - `inner_state_attribution_hits == []`
     - `agentless_passive_hits == []`
     - `signal_density == {"verified_count": 0, "word_count": 0,
       "density_per_100w": None}`
     - existing short-surface fields remain `None` where the current path
       already emits None (`gated_score is None`, `sentence_count is None` —
       same shape as `test_short_error_item_scores_long_surface_only` in
       `test_eval_harness_pipeline.py:511-527`).
   - Assert on `report["quality"]`:
     - `inner_state_attribution_images == 0`
     - `agentless_passive_images == 0`
     - `mean_signal_density is None` (no scored short-surface density retained;
       denominator empty).
   - **Trivial cheating implementation that must fail**: an emit path that
     reads an uninitialised `density` / `scores` attribute on this branch
     (NameError / AttributeError), **or** copies scored-path values, **or**
     omits the depiction keys when `scores is None`. Exact fallback asserts
     kill all three.
4. **Multi-image corpus-mean denominator**
   (`test_report_emit_depiction_mean_density_multi_image` or equivalent):
   - **Three** items (unequal non-None densities + one empty). Caption for A/B
     is the locked 6-token bicycle fixture `"A bicycle leans on a wall."`
     (`_WORD_RE` → word_count **6**; DO NOT BREAK):
     - Image A: that caption; one true fact
       `{"text":"bicycle","kind":"object","polarity":"true","phrases":["bicycle"]}`
       → `verified_count=1`, `word_count=6`, `density_A = 100/6`.
     - Image B: **same caption**; **two** true facts (both polarity `"true"`):
       bicycle as above **and**
       `{"text":"wall","kind":"object","polarity":"true","phrases":["wall"]}`
       → both match → `verified_count=2`, `word_count=6`,
       `density_B = 200/6` (≠ density_A).
     - Image C: caption `""` (empty); any true-fact set →
       `density_per_100w is None`, `word_count == 0` (not in denominator).
   - Assert:
     - `len(report["per_image"]) == 3`
     - per-image `signal_density` objects equal
       `{1, 6, approx(100/6)}`, `{2, 6, approx(200/6)}`,
       `{0, 0, None}` respectively
     - `mean_signal_density == pytest.approx(
         round((100/6 + 200/6) / 2, 4)
       )` i.e. `round(150/6, 4) == 25.0` **and** the denominator is **2**
       (only non-None densities; empty row excluded).
   - **Trivial cheating implementation that must fail**:
     `mean_signal_density = density_scores[0].density_per_100w` (first-only
     → `100/6 ≈ 16.6667`, not `25.0`). Exact mean of two unequal values
     kills it. Also kills averaging over all three including `None`.
5. **All-empty captions → `mean_signal_density is None`**
   (`test_report_emit_depiction_mean_density_all_empty` or equivalent):
   - Two items, both caption `""` (or whitespace-only), any `reference_facts`.
   - Assert: each per-image `signal_density["density_per_100w"] is None`,
     and `report["quality"]["mean_signal_density"] is None`.
   - **Trivial cheating implementation that must fail**: hardcode
     `mean_signal_density = 0.0` for empty corpora.
6. **Command** (exact path; not "chosen by implementer"):
   ```
   uv run --extra dev pytest scene/tests/test_eval_harness_report_depiction.py -q
   ```

**§3.1 / GPU-window unblock condition**: Slices 3–4 green means the density
metric exists, Williams/C5 is documented in-module, and report JSON carries
live density + hit-list values — that **is** landing playbook §3.1
(assessment §6b L284-290: §3.1 is the last unlanded gate; §6e L344-348:
Lane C unblocks the GPU window). Bake-off *ranking sort* that orders
candidates by density remains an optional separate unowned consumer; it is
**not** a prerequisite for §3.1 or the GPU window.

## Consolidated Checklist

### Context and Ownership

- [ ] Loaded testing-python / backend-python / development-workflow rules.
- [ ] Confirmed owned paths: `caption_metrics.py`,
      `test_eval_harness_caption_metrics.py`, Slice 4 thin `report.py` emit,
      and reserved `test_eval_harness_report_depiction.py` only; no bakeoff
      ranking, schemas, prompts, `test_eval_harness_pipeline.py`, or `canon/`
      edits.
- [ ] Re-verified cited rule IDs with definition-anchor grep before
      implementation review.
- [ ] Relative markdown links resolve from `docs/tasks/depiction/` (no
      `../../docs/...` extra segment; no `../../../canon/...` links).

### Checklist for Slice 1: Inner-state-attribution counter

- [ ] Freeze closed tables `_INNER_PERSON_PRONOUNS`, `_INNER_COMMON_PERSON_NOUNS`,
      `_INNER_COPULA_AFFECT`, `_INNER_WILL_VERBS` exactly as Slice 1 lists.
- [ ] Parametrize copula/affect red-first over every pronoun × every affect adj
      (incl. `proud`) with **varied scaffolds** (no sole `"beside the railing"`;
      e.g. near the window / by the doorway / in the courtyard).
- [ ] Parametrize will red-first over every pronoun × every will stem
      (`want`/`refuse`, incl. 3sg `wants`/`refuses`) with **varied complements**
      (no sole `"to leave the railing"`).
- [ ] Write discrimination: attributed `"Her expression reads as {adj}…"` for
      every affect adj → 0 hits.
- [ ] Write hedge discrimination for **each** of `seems` / `looks` / `appears` /
      `as if` → 0 hits (not just `seems` / `reads as`).
- [ ] Write will-branch non-hit: `"She reaches for the gate."` → 0 hits.
- [ ] Write visible-cue control: furrowed brow / tight jaw → 0 hits.
- [ ] Parametrize common-noun copula over EVERY noun × EVERY affect adj
      (`anxious`/`angry`/`proud`) with varied scaffolds → ≥1 hit each.
- [ ] Parametrize common-noun will over EVERY noun × EVERY will stem
      (`wants` and `refuses` surfaces; varied complements) → ≥1 hit each.
- [ ] Parametrize attributed common-noun discrimination over EVERY noun → 0 hits.
- [ ] Write permanent subject-class / predicate-class strip guards
      (non-person subject + affect/will → 0; person subject + no frozen
      predicate → 0) and keep scaffold-variance positive
      `"She is anxious near the window."` as the railing-lookup kill.
- [ ] Write mixed-caption hedge discrimination:
      `"He seems angry…. She is anxious…."` → still ≥1 hit on unhedged clause.
- [ ] Implement detector + `CaptionScores.inner_state_attribution_hits` in `caption_metrics.py`.
- [ ] Confirm `gated_score` unchanged on positive hits.
- [ ] Terminology: attributive/bearer frame only — not "register".
- [ ] `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -k inner_state -q` green.

### Checklist for Slice 2: Agentless-passive / mutual-event detector

- [ ] Freeze `_AGENTLESS_PASSIVE_FORMS`, `_MUTUAL_EVENT_NOUNS`, `_GAP_AGENT_PHRASES`.
- [ ] Parametrize agentless-passive red-first over EVERY passive form
      (`was killed`, `were killed`, `were beaten`, `was enslaved`, `were arrested`).
- [ ] Parametrize mutual-event red-first over EVERY noun (`clash`, `incident`).
- [ ] Write discrimination: active-voice named agent → 0 hits.
- [ ] Parametrize adjacent same-clause by-agent exemption over EVERY passive form → 0 hits.
- [ ] Parametrize non-adjacent same-clause by-agent exemption over EVERY passive form
      (`…{passive_form} on campus yesterday by the Ohio National Guard…`) → 0 hits.
- [ ] Write different-clause unrelated-`by` still-hits
      (`"A report by a journalist says four students were killed…"`) → ≥1 hit.
- [ ] Parametrize gap-language **exemption** over EVERY `_GAP_AGENT_PHRASES` member
      (same-clause parenthetical) → 0 hits.
- [ ] Write different-clause / prior-sentence gap still-hits
      (`"Agent unknown. Four students were killed on campus."` and the other
      two gap phrases as prior sentence) → ≥1 hit each.
- [ ] Parametrize benign mutual-event no-hit over EVERY noun
      (`clash of colors`, `incident of paint`) → 0 hits.
- [ ] Implement detector + `CaptionScores.agentless_passive_hits`.
- [ ] Confirm no gate side-effect.
- [ ] `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -k agentless_passive -q` green.

### Checklist for Slice 3: Signal density + Williams/C5

- [ ] Write red-first density test: bicycle caption → `word_count == 6`,
      `verified_count == 1`, `density_per_100w == pytest.approx(100 / 6)`.
- [ ] Write mandatory rare-ungrounded discrimination pair (`vermilion velocipede` vs `bicycle`) with expected scores.
- [ ] Write padding/verbosity density drop test.
- [ ] Write false-trap control: trap-only dog caption → `verified_count == 0`;
      paired bicycle+dog → `verified_count == 1`.
- [ ] Write dedupe 5a: two identical true-fact rows → `verified_count == 1`.
- [ ] Write dedupe 5b: same text, different kind, both match → `verified_count == 2`.
- [ ] Write dedupe 5c: same text, different phrases, both match → `verified_count == 2`.
- [ ] Write dedupe 5d: same text/kind/phrases, FALSE then TRUE polarity →
      `verified_count == 1` (polarity is the fourth identity field; three-field
      `seen` collapses TRUE when FALSE is first).
- [ ] Write empty/whitespace caption control: `word_count == 0`,
      `verified_count == 0`, `density_per_100w is None`.
- [ ] Implement sibling pure function `score_signal_density` → frozen
      `SignalDensityScores` with `verified_count`, `word_count`,
      `density_per_100w` only — no bare float, not a `CaptionScores` field.
- [ ] Rewrite module docstring: Williams = gate, C5 = ranking axis.
- [ ] Do **not** cite PROV-01 as density-numerator warrant.
- [ ] `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -k signal_density -q` green.
- [ ] Full metrics file:
      `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -q` green.

### Checklist for Slice 4: Report emit

- [ ] After Slices 1–3 green, wire
      `facts = [ReferenceFact.model_validate(f) for f in entry.get("reference_facts", [])]`
      and `score_signal_density(caption, reference_facts=facts)` in `report.py`
      next to the `score_caption` call; retain `density_scores` for aggregation.
- [ ] Initialise density safely so the `short_error` / `scores is None` path
      never reads an unbound name; emit exact fallback empty/zero object.
- [ ] Emit locked per-image keys: `inner_state_attribution_hits`,
      `agentless_passive_hits`, nested `signal_density` object only (no flat keys).
- [ ] Emit locked quality keys: `inner_state_attribution_images`,
      `agentless_passive_images`, `mean_signal_density` with the non-`None`
      density denominator.
- [ ] Write `scene/tests/test_eval_harness_report_depiction.py` with exact-value
      proofs: non-zero, clean-zero, short_error fallback, multi-image mean
      (unequal densities + empty row + exact denominator), all-empty → None.
- [ ] Use `"polarity": "true"` (string) in fixtures; assert
      `ReferenceFact.model_validate` succeeds before `score_run_record`.
- [ ] Leave `test_eval_harness_report.py` deliberately unedited.
- [ ] Confirm no new hard gate / threshold; bakeoff ranking *sort* stays out of scope
      (optional follow-on — not required for §3.1).
- [ ] `uv run --extra dev pytest scene/tests/test_eval_harness_report_depiction.py -q` green.
- [ ] Slices 3–4 green ⇒ playbook §3.1 landed as metric + report-axis; GPU window
      unblocked per assessment §6b/§6e (bake-off sort not required).

### Review Readiness

- [ ] No new hard gate or threshold on first land.
- [ ] Every new assertion has red input + discrimination case in the same PR.
- [ ] Williams/C5 resolution is written in-module, not only in this plan.
- [ ] No colour IDs, no `FM-11`, no fabricated `REG`/`ICON`/`FRAM`/`SEL` IDs.
- [ ] Report emit owned by Slice 4 via reserved
      `test_eval_harness_report_depiction.py`; existing
      `test_eval_harness_report.py` deliberately unedited; bake-off ranking
      *sort* still explicit non-scope (optional follow-on, **not** the §3.1 gate).
- [ ] §3.1 / GPU-window gate is treated as metric + report-axis landing (this task),
      not as bake-off sort (assessment §6b L284-290, §6e L344-348).
- [ ] Canon IDs cited as plain text with lexicon path, not monorepo markdown links.
- [ ] No PROV-01 citation on density numerator membership.

## Stretch Goals

- [ ] Corpus-level `mean_signal_density` helper mirroring `insertion_rate` (if not already landed in Slice 3/4).
- [ ] Report-only rate helpers (`inner_state_image_rate`, `agentless_passive_image_rate`) once per-image fields exist — still no gates.
- [ ] Future **register-compliance** metric arm that reads DEPICT-1
      `DescriptionRegister` (`FORENSIC | EDITORIAL | INTERPRETIVE`) from the
      contract envelope — separate from the attributive/bearer-frame grammar cut
      in Slice 1; not planned in DEPICT-2.

## Success Criteria

- [ ] Inner-state counter fires on unmarked person-as-fact-owner mental-state and
      will prose for **every** frozen pronoun, **every** frozen common-person
      noun (`woman`/`man`/`child`/`person`/`girl`/`boy`), **every** frozen
      affect adjective (incl. `proud` — common-noun copula is the full
      noun × affect product, not `anxious` alone), and **every** frozen will
      stem (incl. `refuse`/`refuses`); positives use **varied scaffolds**
      (not a single railing adjunct/complement); stays silent on
      attributive/bearer frames (including attributed common-noun frames),
      epistemic hedges (`seems` / `looks` / `appears` / `as if` — each proved
      zero-hit), visible-cue inventory, non-person subjects with affect/will,
      and person subjects without a frozen predicate; mixed hedged+unhedged
      captions still fire on the unhedged clause.
- [ ] Agentless-passive detector fires on **every** frozen passive form and
      **every** frozen mutual-event noun in violence context; fires on
      passives whose only `by` is in a different clause **and** on passives
      whose only gap phrase is in a prior sentence / different clause; stays
      silent on named-agent active voice, adjacent **and** non-adjacent
      same-clause `by`-agent passives (**every** frozen passive form, not only
      `were killed`), benign mutual-event uses, and ATTRIB-08-compliant
      same-clause gap-language statements for **every** `_GAP_AGENT_PHRASES`
      member (`agent not named in the record` / `agent not in the record` /
      `agent unknown`).
- [ ] Signal density ranks grounded captions above rare-ungrounded and
      ornament-padded captions with equal or fewer verified facts; rare
      ungrounded nouns never raise the score; false-polarity traps never increment
      `verified_count`; duplicate identical true-fact rows count once; facts
      sharing `text` but differing in `kind`, `phrases`, **or `polarity`**
      are not collapsed by a three-field `seen` key (5d: FALSE+TRUE same
      text/kind/phrases → `verified_count == 1`); empty caption →
      `density_per_100w is None`.
- [ ] `score_signal_density` returns the mandated multi-field score object
      (`word_count == 6` and `approx(100/6)` on the bicycle fixture) as a
      **sibling pure function**, not a `CaptionScores` field.
- [ ] Module docstring states Williams (gate) and C5 (ranking) as distinct roles.
- [ ] Report JSON emits the locked schema: per-image nested `signal_density`
      object + hit lists with **exact values**, quality-level
      `mean_signal_density` (multi-image mean with non-None denominator;
      all-empty → None) + hit-image counts, and exact fallback keys when
      `short_error` makes `scores is None` (Slice 4).
- [ ] Fixtures use `"polarity": "true"` (StrEnum string); `ReferenceFact.model_validate`
      succeeds on them.
- [ ] Metrics tests and
      `scene/tests/test_eval_harness_report_depiction.py` green at branch HEAD.
- [ ] No files outside the owned paths (`caption_metrics.py`,
      `test_eval_harness_caption_metrics.py`, `report.py`,
      `test_eval_harness_report_depiction.py`) modified; existing
      `test_eval_harness_report.py` deliberately unedited.
- [ ] Playbook §3.1 is **landed** as metric + report-axis (Slices 3–4);
      GPU window unblocked per assessment §6b/§6e. Bake-off ranking *sort*
      remains optional unowned follow-on (not the §3.1 gate).

## Not-Doing

- Prompt text / emotion-bearer edits (Lane A; DEPICT-4).
- Contract, schema, enum, `voice`, `DescriptionRegister`, bound-term fields
  (Lane B). Future register-compliance metric that would read
  `DescriptionRegister` is named only (Stretch); not implemented here.
- Bake-off ranking *order* / sort-by-density logic (`bakeoff.py` consumer) —
  **unowned** by this task; keys land in Slice 4 but sort code does not.
  Sort is an **optional follow-on**, not the §3.1 / GPU-window gate
  (assessment §6b/§6e: §3.1 = density metric + report axis; Lane C unblocks).
- Colour vocabulary of any kind; `FM-11` citations; Lane D trigger work.
- Race warrant / parity gate (ATTRIB-06) — pass-level property; harness is
  per-image only.
- Thresholding or hard-gating any new counter on first land.
- Dedicated CAL-02 abstain-rate metric (would restate fabrication or be
  vacuous without weak-evidence fixtures) — see scope decision above.
- Second fabrication metric that restates `score_hallucination` /
  `fabricated_fact_rate`. PROV-01 is **not** cited for density numerator
  membership (PROV-01 = model/input lineage on outputs, not gold-label
  membership).
- Flagging ATTRIB-08-compliant **same-clause** gap-language passives as
  violations (Slice 2 exempts same-clause `_GAP_AGENT_PHRASES`; prior-sentence
  / different-clause gap phrases still hit — see proof 7b).
- Edits to the existing shared `test_eval_harness_report.py` (deliberately
  unedited; DEPICT-2 owns only the reserved depiction report-emit file).
- LLM-judge scoring, model training, non-deterministic axes.
