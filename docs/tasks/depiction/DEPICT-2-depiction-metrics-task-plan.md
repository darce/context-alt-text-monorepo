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
> (F6, F8). **Playbook** (governing §3.1 source): monorepo path
> `docs/runbooks/fir-captioning-orchestrator-playbook.md` §3.1 (signal density;
> §3.2 is stale — ALTQ-1 shipped it). That file is **out-of-tree in this
> plan-review bundle** — `repo/docs/` contains only `assessments/` and `tasks/`;
> the relative link `../../runbooks/…` does **not** resolve here. Cite by
> section number only. A full monorepo checkout carries the file at
> `docs/runbooks/fir-captioning-orchestrator-playbook.md` from the monorepo
> root.
>
> **Canon**: heuristics-canon `v0.17.0-11-ga238620` (bundle `canon/PROVENANCE.txt`;
> private repo, not vendored inside `repo/`). **Resolvable lexicon root
> (`CANON_LEXICONS_ROOT`)**: the plan-review bundle root's `canon/lexicons/`
> directory — sibling of `repo/`, **not** under `repo/`. Citation form only
> (not a path that resolves from `repo/`): `canon/lexicons/<file>.md#anchor`.
> Before implementation review re-verify every rule ID with the
> definition-anchor form against that resolvable root:
> `grep -rE '^\| *`?<ID><a name' "$CANON_LEXICONS_ROOT"/`
> (or the absolute path `<bundle-root>/canon/lexicons/` where `<bundle-root>`
> is the parent of `repo/`). Do **not** run the grep with bare `canon/lexicons/`
> from inside `repo/` — that root does not resolve there.

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
axis — **DEPICT-2's own additional acceptance criterion**, not an assessment
requirement. **Assessment §3.1 / GPU-window gate** (assessment §6b "The GPU
window has a second, cheaper gate than curation" L301-309; §6c "A live
contradiction the bake-off ranking depends on" L311-329, Williams/C5
resolution `#### §6c claim — Williams/C5 resolution (companion axes)`
L321-329; §6a "Playbook status is half-stale" NOT-LANDED evidence
L294): density metric in `caption_metrics.py` + Williams/C5 docstring.
Assessment §6b/§6c list **no** report emit. **Lane C unblocks the GPU window**
(assessment §6e "Dispatch shape — file ownership, not just task ownership"
L373-375). Bake-off ranking *sort* that *orders* candidates by density is an
**optional follow-on consumer**, not the §3.1 / GPU-window gate. Resolve the
Williams/C5 length contradiction in the module docstring so gate policy and
ranking policy cannot be read as opposites.

## Problem Statement

The caption harness can already gate wrong names, score fabrication traps, and
flag meta-framing, but it cannot see the highest-value depiction safety signal
LIBSYN-1 named (inner-state attribution on a depicted person), cannot flag the
cheapest grammar failure in the depiction lexicon (agentless passive / "clash"
frames), and measures no signal density at all. Every length-correlated quality
axis therefore still rewards verbosity. Until these scorers exist, Lane A/B
prompt changes are unmeasurable — exactly what EVAL-08
(`canon/lexicons/ml-systems.md#eval-08`, CACE) forbids — and the GPU window
remains gated by playbook §3.1 (assessment §6b "The GPU window has a second,
cheaper gate than curation" L301-309: §3.1 is the last unlanded gate —
density metric in `caption_metrics.py`; §6a NOT-LANDED row L294). Pure
scorers alone are not enough for *this plan's* DoD: `report.py` today builds
its quality block from `meta_framing_hits` / sentence band /
`mean_gated_score` only (see Current State), so density must also be emitted
there as **DEPICT-2's own additional acceptance criterion** (not attributed
to assessment §6b/§6e). Assessment §6c ("A live contradiction the bake-off
ranking depends on" L311-329; Williams/C5 resolution
`#### §6c claim — Williams/C5 resolution (companion axes)` L321-329) is the
companion-axis write-up; §6e ("Dispatch shape — file ownership, not just
task ownership" / `#### §6e claim — Lane C unblocks the GPU window`
L373-375) is Lane C unblocking the GPU window via the density metric. Bake-off
code that *sorts* survivors by density is an optional follow-on, not a
prerequisite for §3.1 or the GPU window.

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
  sentence-band stats; caption aggregate dict-entry block (L565–574) has
  `mean_gated_score` and existing gate rates. No density or depiction-hit
  keys. Per-image **row dict literal** is `report.py:472-495` (closes at
  L495; L496–517 are post-literal `if short_error…` / `row["long"] = {…}` /
  `per_image.append(...)` **statements**): surfaces `meta_framing_hits` at
  L486 but not inner-state / agentless / density fields.
- `score_caption` is called with only names/traps/objects/roster/context
  (`report.py:398-406`); `reference_facts` is **not** passed. Manifest entry
  type exposes `reference_facts: list[ReferenceFact]`
  (`manifest.py:GoldenEntry` L359), but `score_run_record` receives entries as
  dicts (`report.py:320-327`) and never reads `entry["reference_facts"]` today.
- `bakeoff.py` does **not** import `caption_metrics` today (verified by search).
  A future bake-off *sort* by density is an optional follow-on after Slice 4
  keys exist; it is **not** the §3.1 / GPU-window gate (assessment §6b "The
  GPU window has a second, cheaper gate than curation" L301-309 density
  metric; §6e "Dispatch shape — file ownership, not just task ownership"
  L373-375: Lane C unblocks the GPU window).

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
   JSON quality / per-image sections (Slice 4 thin additive emit) —
   **DEPICT-2's own additional acceptance criterion**, not an assessment
   requirement. Slice 3 (density metric + Williams/C5 docstring) lands the
   assessment §3.1 / GPU-window gate (assessment §6b "The GPU window has a
   second, cheaper gate than curation" L301-309; §6c "A live contradiction
   the bake-off ranking depends on" L311-329 including Williams/C5 resolution
   `#### §6c claim — Williams/C5 resolution (companion axes)` L321-329;
   §6e "Dispatch shape — file ownership, not just task ownership" /
   `#### §6e claim — Lane C unblocks the GPU window` L373-375: Lane C
   unblocks). Bake-off
   ranking code that *orders* candidates by density remains an **optional
   unowned follow-on** — not the §3.1 gate.

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
| Report JSON quality / per-image emit | Lane C (Slice 4) | `report.py` `_quality_block` + per-image rows read known `CaptionScores` fields; no `reference_facts` wire | additive nested `signal_density` object + hit-list keys; SHORT quality mean/counts assigned **after** the `result` dict literal closes at `report.py:604` (do not extend `_quality_block`; do not insert inside the open literal); wire facts → density | no — additive keys | `test_eval_harness_report_depiction.py` exact-value proofs |
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
not orphaned behind zero report consumers — that emit is **DEPICT-2's own**
additional acceptance criterion. Assessment §3.1 / GPU-window gate = density
metric + Williams/C5 (Slice 3 only). Ranking *sort* remains an optional
separate consumer, not the gate.

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
| report emit (Slice 4) | `apps/prototype-description-service/scripts/eval_harness/report.py` | Thin additive: wire `reference_facts` → `score_signal_density`; emit exact density object + hit-list keys in the per-image row dict literal (`report.py:472-495`); assign SHORT quality depiction keys after the `result` literal closes at `report.py:604` (do not extend `_quality_block`); no ranking logic, no gates |
| report tests (Slice 4) | `apps/prototype-description-service/scene/tests/test_eval_harness_report_depiction.py` | **New reserved file** owned by DEPICT-2 only. Assert report JSON carries exact density object + hit-list keys **and values**. Do not extend DEPICT-0's `test_eval_harness_pipeline.py` or any other shared harness test. |

## Related Files

| File | Note |
| --- | --- |
| `scripts/eval_harness/manifest.py` | `ReferenceFact.match_targets()` is the density walkback primitive — read only |
| `scripts/eval_harness/bakeoff.py` | Optional future *sort* consumer of density; **unowned** here — does not import `caption_metrics` today; sort is **not** the §3.1 / GPU-window gate |
| `docs/runbooks/fir-captioning-orchestrator-playbook.md` §3.1 | Governing density-metric requirement (cite by section). **Out-of-tree** in this plan-review bundle; present at that monorepo-relative path in a full checkout. Assessment §6b gate = density metric (Slice 3); report emit is DEPICT-2's own extra (Slice 4). |

### Cross-lane dependency

| File | Exact change needed | Who lands first |
| --- | --- | --- |
| `scripts/eval_harness/report.py` | Emit the new per-image hit lists and density number in **JSON** quality / per-image sections so density is a live report axis (**DEPICT-2 own acceptance criterion**, not assessment §6b/§6e). Markdown human summary is **out of contract** for this task — no `_quality_lines` edit and no markdown proof required (see Slice 4) | **Lane C, Slice 4 of this task** (after pure APIs Slices 1–3 are green); thin additive import of this module only — not a deferred orphan |
| Bake-off ranking *sort* (optional) | Optionally consume density key to order survivors | **unowned by DEPICT-2**; optional follow-on after Slice 4 keys exist; **not** the §3.1 / GPU-window gate (assessment §6b "The GPU window has a second, cheaper gate than curation" L301-309: §3.1 = density metric; §6e "Dispatch shape — file ownership, not just task ownership" L373-375: Lane C unblocks GPU window) |
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
- Assessment §3.1 / GPU-window gate lands when Slice 3 is green (density
  metric + Williams/C5; assessment §6b "The GPU window has a second, cheaper
  gate than curation" L301-309; §6e "Dispatch shape — file ownership, not
  just task ownership" L373-375). Slice 4 report emit is DEPICT-2's own
  additional acceptance criterion. Bake-off ranking *sort* remains an
  optional unowned follow-on (see Cross-lane dependency).

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
- **Hit-list element semantics (locked; Slice 1)**: each element is the
  **matched surface text** of the ownership pattern, **lower-cased**, in
  **source order** of first match — same contract shape as
  `meta_framing_hits` (`caption_metrics.py:242-245` returns the matched
  table phrase; here the matched caption span, lower-cased). Examples of
  legal elements: `"she is anxious"`, `"he wants"`, `"the woman is proud"`.
  Marker tokens (`"inner_state"`, `"copula"`, rule IDs) are **not** legal
  elements. Slice 4 asserts exact literal membership against this contract.
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

**No caption-literal shared with the implementation (locked).** No exact
caption string that appears in any positive or negative fixture may appear as
a string literal in the detector implementation (tables of *grammar members*
— pronouns, nouns, affect adjs, will stems — are allowed; full caption
literals and frozensets of full captions are not). A pure
`frozenset({…every mandated positive…})` membership detector is a [TEST-15]
defect even if every scaffold-variance case is listed.

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
   `as if`) and hedged-WITH-COPULA frames** (locks the full hedge class
   named in Success Criteria so a single-token special case **or** a bare
   copula+affect regex with zero hedge/frame logic cannot pass):
   - **Bare-hedge captions** (no copula; each must return **zero** hits):
     - `"He seems angry near the window."`
     - `"She looks anxious by the doorway."`
     - `"He appears proud in the courtyard."`
     - `"She stands as if anxious near the gate."`
   - **Hedged-WITH-COPULA / external-frame negatives** (person subject +
     copula + affect **adjacent**, with the attributive / named-source /
     epistemic frame sitting **outside** the copula–adjective bigram —
     the only fixtures that force a frame check to exist; each must return
     **zero** hits). Use **adjacent-copula + external frame**, not
     intervening-frame prose:
     - `"Apparently she is {adj} near the window."` for each
       `adj ∈ {anxious, angry, proud}`
       (sentence-initial epistemic frame; copula and adj are adjacent)
     - `"According to the curator, she is {adj} by the doorway."` for each
       `adj ∈ {anxious, angry, proud}`
       (named-source frame before the clause; copula and adj adjacent)
     - `"She is {adj}, it seems, in the courtyard."` for each
       `adj ∈ {anxious, angry, proud}`
       (parenthetical hedge after the adjacent copula+adj)
     - **Keep one intervening-frame case** (frame material between copula
       and adjective — still zero-hit, but does **not** alone force a
       frame check; see cheat analysis below):
       `"She is said to be {adj} near the window."` for each
       `adj ∈ {anxious, angry, proud}`
     - **Hedged-will negative**: `"He appears to want to open the gate."`
       → **zero** hits (will stem present under hedge/frame; must not fire
       as unmarked ownership).
   - Assert each: **zero** hits. An implementation that treats any bare
     hedge like unmarked copula ownership fails the matching bare-hedge
     case. A suite that only proves `seems` / `reads as` does not satisfy
     this item. **Trivial cheating implementation that must fail**: a bare
     adjacency regex for
     `(she|he|they|woman|man|…)\s+(is|are)\s+(anxious|angry|proud)` (plus
     will alternation) with **zero** hedge or bearer-frame logic — that
     detector passes every bare-hedge negative (they omit copula) and every
     pre-existing positive, and it also **passes the intervening-frame
     case** `"She is said to be anxious near the window."` (the frame
     text `said to be` sits **between** the copula and the adjective, so
     the adjacency regex never fires there — an intervening-frame
     negative alone does **not** defeat this cheat). It **does** fire on
     the external-frame fixtures where copula and adjective **are**
     adjacent — e.g. `"Apparently she is anxious near the window."`,
     `"According to the curator, she is anxious by the doorway."`, and
     `"She is anxious, it seems, in the courtyard."` — and fails those
     zero-hit asserts. Those are the ATTRIB-01-licensed attributed
     readings (`canon/lexicons/depiction.md:73`, `attrib-01`: "state
     visible cues only, or attribute the reading to viewer, convention,
     artefact, or named source") that a frame-blind adjacency matcher
     cannot silence.
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
12. **Held-out generalisation — compose frozen tables with novel adjuncts at
    test time** (`test_inner_state_held_out_generalisation` or equivalent;
    kills pure proof-set / frozenset membership detectors that list every
    mandated positive caption):
    - **At test time only** (not as frozen fixture literals that the
      implementation could copy), generate positives by composing:
      - one subject from `_INNER_PERSON_PRONOUNS` ∪ `_INNER_COMMON_PERSON_NOUNS`
      - one predicate from `_INNER_COPULA_AFFECT` (copula form) **or**
        `_INNER_WILL_VERBS` (will form, incl. 3sg)
      - an adjunct / complement drawn from a **held-out adjunct pool declared
        in the TEST module only** (e.g. a module-level
        `_HELD_OUT_ADJUNCTS` / `_HELD_OUT_COMPLEMENTS` tuple in
        `test_eval_harness_caption_metrics.py` — **never** in
        `caption_metrics.py`, and **never** enumerated as concrete strings
        in this plan or any other plan document). **Pool shape (locked;
        members are not published here)**: a small set of locative /
        prepositional adjuncts for the copula branch and a small set of
        infinitival complements for the will branch, each syntactically
        parallel to the scaffolds in proofs 1–11 but using **novel surface
        strings** chosen by the test author at test-authoring time. The
        concrete members **must not appear in any plan document** (this
        one included) — publishing them would let an implementer
        enumerate paraphrases into a lookup table and pass the
        generalisation proof without composing grammar. The pool must
        appear **nowhere** in proofs 1–11 fixture text. **No token
        sequence from this pool may appear in any other Slice 1 proof
        caption.**
    - **Unpredictability / no dual-site literal (locked)**: no caption
      literal **and no adjunct / complement literal from the held-out
      pool** may appear in both the implementation module
      (`caption_metrics.py`) and the test module. Grammar-member tables
      (pronouns, nouns, affect adjs, will stems) are the only shared
      closed sets. The concrete pool members exist **only** in the test
      module; this plan deliberately does not list them.
    - Minimum product size: ≥6 generated captions covering both copula and
      will branches and both pronoun and common-noun subjects.
    - Assert each generated caption: ≥1 hit (matched surface text,
      lower-cased, per hit-list semantics above).
    - **Source-level guard (mandatory; makes the pool held-out)**: a test
      reads `caption_metrics.py` source (or `inspect.getsource` on the
      detector module) and asserts that **none** of the held-out adjunct /
      complement strings from the test-module pool appear as substrings of
      that source. Enumerating the test-module pool into an
      implementation lookup table therefore fails the guard even if every
      generated caption would otherwise hit.
    - **Trivial cheating implementation that must fail**:
      `return [caption.lower()] if caption in _PROOF_CAPTIONS else []`
      or any `frozenset` / dict membership over the finite closed list of
      proof 1–11 captions (scaffold variance enlarges that set; held-out
      adjuncts sit **outside** it). Also fails any implementation that
      embeds those held-out adjunct strings as caption literals (source
      guard goes red).
13. **Command**:
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
  # Violence / oppression context gate for mutual-event nouns (TABLE MEMBERSHIP
  # IS THE CONTRACT — independent of the passive detector). EVERY mutual-event
  # positive must contain ≥1 member; benign negatives must contain none.
  # Membership checks MUST use `_contains` (caption_metrics.py:59-74), not
  # raw `needle in haystack` — see word-boundary lock below.
  # `"shot"` is INTENTIONALLY ABSENT: it is a dominant photographic term in
  # this corpus ("wide shot", "snapshot"). Violence-sense passives remain
  # reachable via the frozen `_AGENTLESS_PASSIVE_FORMS` table if a future
  # form such as `"was shot"` is added there; do not re-add bare `"shot"`
  # to this context gate without a disambiguating rule and a
  # `"…wide shot…"` zero-hit negative.
  _VIOLENCE_CONTEXT_TERMS = (
      "killed",
      "beaten",
      "enslaved",
      "arrested",
      "violence",
      "oppression",
  )
  # Agent PP phrases for same-clause by-agent exemption proofs (parametrized;
  # different word counts + internal capitalisation — do NOT freeze a single
  # "by the Ohio National Guard" literal as the only agent).
  _BY_AGENT_PPS = (
      "by the Ohio National Guard",   # multi-word, internal capitals
      "by soldiers",                  # single common noun, lowercase
      "by a campus patrol officer",   # multi-word, mixed case, article
  )
  ```

  - **agentless passives** on the frozen violence/oppression forms **without**
    a same-clause `by`-agent PP and **without** a same-clause gap-agent phrase
    from `_GAP_AGENT_PHRASES`;
  - **mutual-event / symmetry nouns** from `_MUTUAL_EVENT_NOUNS` when the
    caption also contains ≥1 member of `_VIOLENCE_CONTEXT_TERMS` (closed list;
    do not generalise to every English passive). The violence gate is
    **membership in `_VIOLENCE_CONTEXT_TERMS` via the existing `_contains`
    helper** (`caption_metrics.py:59-74` — word-boundary, case-insensitive;
    documents the `cat`/`scattered` false-positive class). **Do not** use a
    raw `term in caption.lower()` substring test — that passes every
    mandated proof while false-firing on `"skilled"` (`killed`) and
    `"snapshot"` (were `"shot"` still present). Membership is independent of
    whether any `_AGENTLESS_PASSIVE_FORMS` member is present — ATTRIB-08
    (`canon/lexicons/depiction.md:80`, `attrib-08`) names the mutual-event
    noun as an independent failure mode ("do not hide known agents behind
    'clash,' 'incident,' or agentless 'were killed'").
- Surface as report-only hit list on `CaptionScores`
  (`agentless_passive_hits: list[str]`, parallel to `meta_framing_hits`).
  Same surface lock as Slice 1: report-facing field is the `CaptionScores`
  list, not an open "or sibling pure function" fork. No `gated_score` change.
- **Hit-list element semantics (locked; Slice 2)**: each element is the
  **matched surface text**, **lower-cased**, in **source order** of first
  match — same contract as Slice 1 / `meta_framing_hits`. Passive hits emit
  the matched form (e.g. `"were killed"`, `"was enslaved"`); mutual-event
  hits emit the matched noun (e.g. `"clash"`, `"incident"`). Marker tokens
  (`"agentless"`, `"mutual"`, rule IDs) are **not** legal elements.
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
- **Same-clause contract and clause-splitting rule (frozen)**: "same clause"
  is not "anywhere in the caption" and not "any text after the passive to
  end of caption". A junior implementer must split the caption into clause
  segments before testing by-agent / gap exemptions. **Locked clause
  splitters** (any of these ends the current clause segment):
  - sentence terminators: `.` `?` `!` (optionally followed by whitespace /
    end);
  - clause-internal separators: `;` **and coordinating-comma patterns only**
    — `, and ` / `, but ` / `, or ` (case-insensitive; leading comma +
    whitespace + coordinating conjunction). **Bare `,` alone is NOT a
    clause splitter** (see gap-exemption resolution below).
  - subordinators that open a new clause boundary for this detector:
    ` that `, ` which `, ` who `, ` while `, ` when `, ` because `,
    ` although `, ` as ` (word-boundary match, case-insensitive).
  **Gap-exemption resolution (comma / parenthetical)**: a bare-comma
  unconditional splitter would re-break ATTRIB-08-compliant same-clause gap
  prose such as `"Four students were killed, agent unknown, on campus."`
  (splitting the gap into a different segment → false hit). Freezing only
  coordinating-comma patterns keeps that parenthetical gap same-clause
  (zero hit under proof 7's exemption) while still splitting
  `"Four students were killed, and the parade was led by soldiers."`.
  Preferred same-clause gap form in fixtures remains the parenthetical
  `"Four students were killed ({gap}) on campus."` (proof 7); the
  coordinating-comma refinement is the load-bearing rule so an implementer
  who freezes bare `,` as a splitter fails the gap exemption.
  **Exemption locality (locked)**: a `by`-agent PP or gap phrase exempts a
  passive **only** when it falls in the **same clause segment** as that
  passive under this split **and** (for `by`-agent) occurs **at or after**
  the passive form in that segment (agent-complement position). A `by` PP
  that only appears *before* the passive in the segment (e.g.
  `"A report by soldiers says four students were killed on campus."` —
  frozen-table member `"by soldiers"` used as a prior-clause PP, **not**
  as a same-clause agent) does **not** exempt. Material in a prior or
  following sentence / clause segment does **not** exempt. A forward scan
  from the passive to **end of caption** (ignoring these splitters) is a
  [TEST-15] defect — proofs 6b and 7c go red against it.
- **Same-clause `by`-agent and violence-context locks** (proofs force both;
  adjacent-only substring cheats and forward-scan-to-caption-end cheats fail):
  - A `by`-agent PP in a **different** clause (prior **or following**) does
    **not** exempt a passive in this clause.
  - A **non-adjacent** same-clause `by`-agent (material between the passive
    and the `by`-PP) **does** exempt.
  - Mutual-event nouns fire **only** when ≥1 `_VIOLENCE_CONTEXT_TERMS`
    member is present; a benign `"clash of colors"` / `"incident of paint"`
    must not hit. The gate does **not** require an `_AGENTLESS_PASSIVE_FORMS`
    member (active-voice violence + mutual-event still hits the noun).

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
   `_MUTUAL_EVENT_NOUNS` member** (violence context via
   `_VIOLENCE_CONTEXT_TERMS`):
   - Captions: `"Four students were killed during a clash on campus."` and
     `"Four students were killed during an incident on campus."`
   - Assert each: hits include an agentless-passive element **and** a
     mutual-event element with exact lower-cased membership
     `"were killed"` ∈ hits and (`"clash"` ∈ hits or `"incident"` ∈ hits).
     A detector that only knows `clash` fails on `incident`.
3. **Discrimination case — active voice named agent, no mutual-event noun**:
   - Caption: `"Members of the Ohio National Guard killed four students on campus."`
   - Assert: **zero** hits (active voice; no `_MUTUAL_EVENT_NOUNS` member).
     A detector that flags any past-tense violence verb fails discrimination.
3b. **Mutual-event independent of passive — active-voice violence + clash**
   (`test_mutual_event_active_voice_violence_context` or equivalent; locks
   `_VIOLENCE_CONTEXT_TERMS` as an independent gate so gating mutual-event
   hits on `_AGENTLESS_PASSIVE_FORMS` membership cannot pass):
   - Caption: `"Members of the Ohio National Guard killed four students during a clash."`
   - Assert:
     - `"clash"` ∈ `agentless_passive_hits` (mutual-event element; exact
       lower-cased matched surface text)
     - **no** passive-form element
       (`"was killed"` / `"were killed"` / … ∉ hits) — voice is active
     - hit list is non-empty solely because of the mutual-event noun under
       violence context (`"killed"` ∈ `_VIOLENCE_CONTEXT_TERMS`)
   - **Trivial cheating implementation that must fail**:
     `if any(p in caption.lower() for p in _AGENTLESS_PASSIVE_FORMS):
          flag mutual-event nouns else: pass`
     (mutual-event gated on passive presence). This caption has no passive
     form, contains `clash` + `killed`, and must still hit on `clash`.
3c. **Per-term violence-context positives — EVERY remaining
   `_VIOLENCE_CONTEXT_TERMS` member as the SOLE violence signal**
   (`test_mutual_event_each_violence_context_term` or equivalent; kills a
   `"killed" in caption` proxy that would pass proofs 2 / 3b / 8 while
   staying silent on every other context term):
   - One positive caption per remaining term (not only `killed`), with that
     term as the **sole** member of `_VIOLENCE_CONTEXT_TERMS` present and a
     mutual-event noun present. **At least one caption must be active
     voice** (no `_AGENTLESS_PASSIVE_FORMS` member) so ATTRIB-08's
     mutual-event failure is independent of passive voice
     (`canon/lexicons/depiction.md:80`).
   - **Locked fixture set** (parametrize; assert `"clash"` ∈ hits or
     `"incident"` ∈ hits as noted; exact lower-cased matched surface):
     | Term (sole context) | Caption | Voice | Assert |
     | --- | --- | --- | --- |
     | `killed` | covered by proof 3b (active) and proof 2 (passive) | both | (no new fixture required) |
     | `beaten` | `"Guards beaten four students during a clash."` is ungrammatical — use active: `"Guards left four students beaten during a clash."` | active (no passive form) | `"clash"` ∈ hits; no passive-form element |
     | `enslaved` | `"Traders enslaved four people during a clash."` | **active** | `"clash"` ∈ hits; no passive-form element |
     | `arrested` | `"Officers arrested four students during a clash."` | **active** | `"clash"` ∈ hits; no passive-form element |
     | `violence` | `"Witnesses reported violence during a clash on campus."` | active (no passive form) | `"clash"` ∈ hits |
     | `oppression` | `"The mural depicts oppression during a clash."` | active (no passive form) | `"clash"` ∈ hits |
   - **Trivial cheating implementation that must fail**:
     `if "killed" in caption.lower() and re.search(r"\b(clash|incident)\b", …): flag`
     (killed-only violence proxy). Captions whose sole context term is
     `arrested` / `enslaved` / `violence` / `oppression` / `beaten` must
     still hit; the proxy returns `[]` and fails.
   - Note: `"shot"` is **not** in `_VIOLENCE_CONTEXT_TERMS` (photographic
     false-positive class; see table freeze above). Do not add a `shot`
     positive.
4. **Discrimination — same-clause by-agent exemption, parametrized over EVERY
   passive form × EVERY `_BY_AGENT_PPS` member**
   (`test_agentless_passive_by_agent_exempt` or equivalent;
   locks the same-clause `by`-agent non-hit so a naive "any violence passive"
   detector **or** a single-agent-phrase special-case fails):
   - **Adjacent form** (baseline): `"Four students {passive_form} {agent_pp}
     on campus."` for each
     `passive_form ∈ _AGENTLESS_PASSIVE_FORMS` **and** each
     `agent_pp ∈ _BY_AGENT_PPS`
     (`"by the Ohio National Guard"`, `"by soldiers"`,
     `"by a campus patrol officer"`). Full cartesian product
     (5 forms × 3 agents = 15 captions).
   - Assert each: **zero** agentless-passive hits (the clause names the actor
     via `by`). Mutual-event nouns are absent so the whole hit list is empty.
   - Red-first edit: strip the agent PP → the agentless-passive element must
     appear. A constant-empty implementation fails proof 1; a
     fire-on-any-passive implementation fails this case; a detector that
     special-cases only `"by the Ohio National Guard"` fails on
     `"by soldiers"` and `"by a campus patrol officer"`.
5. **Discrimination — non-adjacent same-clause by-agent MUST exempt,
   parametrized over EVERY `_AGENTLESS_PASSIVE_FORMS` member × EVERY
   `_BY_AGENT_PPS` member**
   (`test_agentless_passive_nonadjacent_by_agent_exempt` or equivalent;
   kills form-specific `"were killed by"`-substring-only cheats **and**
   single-agent-phrase cheats):
   - Template: `"Four students {passive_form} on campus yesterday {agent_pp}
     during roll call."` for each
     `passive_form ∈ _AGENTLESS_PASSIVE_FORMS` **and** each
     `agent_pp ∈ _BY_AGENT_PPS` (full product, 15 captions).
   - Assert each: **zero** agentless-passive hits. The `by`-agent PP is in the
     **same clause** as the passive but **not adjacent** to the verb (material
     `on campus yesterday` sits between). A detector that only checks the
     immediate `"were killed by"` bigram, only hardcodes
     `"by the Ohio National Guard"`, or only the single adjacent fixture in
     proof 4, fails on e.g.
     `"was enslaved on campus yesterday by a campus patrol officer…"`.
6. **Discrimination — different-clause `by` does NOT exempt (prior clause),
   using a `_BY_AGENT_PPS` MEMBER**
   (`test_agentless_passive_unrelated_by_still_hits` or equivalent;
   agent **must** be a frozen-table member so a membership-only exemption
   with no clause model cannot pass by ignoring unknown agents):
   - Caption: `"A report by soldiers says four students were killed on campus."`
     (frozen member `"by soldiers"`; also acceptable with any other
     `_BY_AGENT_PPS` member in the same prior-clause scaffold).
   - Assert: ≥1 agentless-passive hit with `"were killed"` ∈ hits (the
     `by soldiers` PP modifies `report` in a **different** clause / before
     the passive; it is **not** a same-clause agent of the passive).
   - **Trivial cheating implementations that must fail**:
     - `if " by " in caption: return []` (whole-caption ` by ` silence).
     - `if any(a in caption.lower() for a in _BY_AGENT_PPS): return []`
       (frozen-list membership with **no** clause model — this caption
       contains a table member and still must hit; the cheat returns `[]`).
6a. **Every locked clause splitter still-hits — full terminator /
   coordinator / subordinator product with `_BY_AGENT_PPS` MEMBERS**
   (`test_agentless_passive_clause_splitters_still_hit` or equivalent;
   kills (a) a sentence-only splitter `re.split(r"[.?!]+", caption)`,
   (b) a partial splitter covering only `.` / `, and ` / ` while `, and
   (c) a frozen-list membership exemption with **no** clause model that
   would silence any caption containing a table-member agent regardless of
   clause locality). **Every still-hit agent PP below is a `_BY_AGENT_PPS`
   member** — non-table agents (e.g. `"by the mayor"`, `"by a journalist"`)
   are **forbidden** in these fixtures; they let a membership-only cheat
   pass without a clause model (the unknown agent is simply never
   considered for exemption).
   - **Locked still-hit fixture table** (parametrize; assert
     `"were killed"` ∈ hits for each). Cycle agents across the three
     `_BY_AGENT_PPS` members so no single agent is the only one proven
     cross-clause:

     | Splitter (locked) | Caption (agent = `_BY_AGENT_PPS` member) |
     | --- | --- |
     | `.` (sentence terminator) | covered by proof **6b** (full passive-form product) |
     | `?` | `"Four students were killed on campus? The parade was led by soldiers."` |
     | `!` | `"Four students were killed on campus! The parade was led by the Ohio National Guard."` |
     | `;` | `"Four students were killed on campus; the parade was led by a campus patrol officer."` |
     | `, and ` | `"Four students were killed, and the parade was led by soldiers."` |
     | `, but ` | `"Four students were killed, but the parade was led by the Ohio National Guard."` |
     | `, or ` | `"Four students were killed, or the parade was led by a campus patrol officer."` |
     | ` while ` | `"Four students were killed while the parade was led by soldiers."` |
     | ` when ` | `"Four students were killed when the parade was led by the Ohio National Guard."` |
     | ` because ` | `"Four students were killed because the parade was led by a campus patrol officer."` |
     | ` although ` | `"Four students were killed although the parade was led by soldiers."` |
     | ` as ` | `"Four students were killed as the parade was led by the Ohio National Guard."` |
     | ` that ` | `"Four students were killed on campus that the parade was led by soldiers to mark."` |
     | ` which ` | `"Four students were killed on campus which the parade was led by the Ohio National Guard to mark."` |
     | ` who ` | `"Four students were killed on campus who the parade was led by a campus patrol officer to honor."` |

   - For each row: the frozen splitter ends the passive's clause segment;
     the `_BY_AGENT_PPS` member sits in a **later** segment and must **not**
     exempt. A sentence-only splitter treats coordinating-comma and
     subordinator rows as one sentence, finds the table-member `by`-PP
     after the passive, and wrongly returns `[]`. A splitter covering only
     `.` / `, and ` / ` while ` wrongly silences every other row. A
     membership-only cheat
     `if any(a in caption for a in _BY_AGENT_PPS): exempt` silences **every**
     row (each contains a table member) and fails.
   - **Gap-exemption re-check under coordinating-comma rule** (resolution
     of the bare-comma re-break):
     `"Four students were killed, agent unknown, on campus."`
     → assert **zero** hits (same-clause gap under the refined rule: bare
     `,` does **not** split, so `agent unknown` remains same-clause and
     exempts). An implementation that freezes bare `,` as a splitter
     wrongly hits this ATTRIB-08-compliant prose and fails.
   - **Trivial cheating implementations that must fail**:
     - `re.split(r"[.?!]+", caption)` then exempt if any segment tail has
       a `_BY_AGENT_PPS` member (sentence-only) — silences `, and ` /
       subordinator / `;` rows.
     - Splitter covering only `.` + `, and ` + ` while ` — silences `?` /
       `!` / `;` / `, but ` / `, or ` / `that` / `which` / `who` / `when` /
       `because` / `although` / `as`.
     - `if any(a in caption.lower() for a in _BY_AGENT_PPS): return []`
       (no clause model) — silences every row above.
6b. **Following-sentence by-agent does NOT exempt, parametrized over EVERY
   `_AGENTLESS_PASSIVE_FORMS` member × using `_BY_AGENT_PPS` MEMBERS**
   (`test_agentless_passive_following_sentence_by_agent_still_hits` or
   equivalent; kills forward-scan-from-passive-to-caption-end with no clause
   model — every exempting fixture before this proof placed the agent PP
   *after* the passive and every hitting fixture placed it *before*):
   - Template: `"Four students {passive_form} on campus. The parade was led
     {agent_pp}."` for each `passive_form ∈ _AGENTLESS_PASSIVE_FORMS` **and**
     each `agent_pp ∈ _BY_AGENT_PPS` (full product, or at minimum every
     passive form with a cycling table member — **never** a non-table
     agent such as `"by the mayor"`).
   - Assert each: ≥1 agentless-passive hit covering that form
     (exact lower-cased form ∈ hits). The following sentence's table-member
     `by`-PP is a **different clause** under the frozen clause-splitting
     rule and must **not** exempt.
   - **Trivial cheating implementations that must fail**:
     - `scan forward from passive match to end of caption; if " by " in tail:
       exempt` (no sentence/clause boundary) — wrongly exempts this caption
       (and `"Four students were killed on campus. Agent unknown."`) and
       passes proofs 4–7b while violating the same-clause contract.
     - `if any(a in caption.lower() for a in _BY_AGENT_PPS): return []`
       (membership, no clause model) — every caption here contains a table
       member and still must hit.
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
   - Assert each: ≥1 agentless-passive hit with `"were killed"` ∈ hits. The
     gap phrase is in a **prior sentence / different clause**, not a
     same-clause exemption on the passive.
   - **Trivial cheating implementation that must fail**:
     `if any(g in caption.lower() for g in _GAP_AGENT_PHRASES): return []`
     (whole-caption substring exemption). Production consequence of the cheat:
     `"Agent unknown. Four students were killed on campus."` would be wrongly
     silent — this proof forces the hit.
7c. **Following-sentence gap does NOT exempt, parametrized over EVERY
   `_AGENTLESS_PASSIVE_FORMS` member × EVERY `_GAP_AGENT_PHRASES` member**
   (`test_agentless_passive_following_sentence_gap_still_hits` or equivalent;
   mirror image of proof 7b; completes the polarity that a forward-scan with
   no clause model would get wrong):
   - Template: `"Four students {passive_form} on campus. {Gap_sentence}."`
     where `Gap_sentence` is the gap phrase with sentence capitalisation
     (e.g. `"Agent unknown"`, `"Agent not in the record"`,
     `"Agent not named in the record"`) for each
     `passive_form ∈ _AGENTLESS_PASSIVE_FORMS` **and** each
     `gap ∈ _GAP_AGENT_PHRASES` (full product).
   - Assert each: ≥1 agentless-passive hit covering that form. The gap is in
     a **following sentence**, not a same-clause exemption.
   - **Trivial cheating implementation that must fail**: the same
     forward-scan-to-end-of-caption exemption as 6b, or whole-caption gap
     substring exemption. Either wrongly silences these captions.
8. **Violence-context discrimination — benign mutual-event nouns, parametrized
   over EVERY `_MUTUAL_EVENT_NOUNS` member**
   (`test_agentless_passive_benign_mutual_event_no_hit` or equivalent):
   - Captions: `"A clash of colors fills the poster."` and
     `"An incident of paint stains the canvas."`
   - Assert each: **zero** mutual-event hits (and zero hits overall). Neither
     caption contains any `_VIOLENCE_CONTEXT_TERMS` member.
   - **Trivial cheating implementation that must fail**:
     `if re.search(r"\b(clash|incident)\b", caption, re.I): return [match]`
     (no `_VIOLENCE_CONTEXT_TERMS` membership gate). These benign captions
     must return `[]`.
8b. **Word-boundary discipline on `_VIOLENCE_CONTEXT_TERMS`**
   (`test_violence_context_word_boundary_no_hit` or equivalent; locks
   membership through `_contains` at `caption_metrics.py:59-74` so a raw
   `in` test cannot pass):
   - Caption: `"A skilled artist captures a clash of colors."`
     (contains substring `killed`⊂`skilled`, a benign mutual-event noun,
     and **no** whole-token violence-context term). Assert: **zero** hits
     overall.
   - **Why no `shot`/`snapshot` arm**: `"shot"` was **intentionally
     removed** from `_VIOLENCE_CONTEXT_TERMS` (photographic dominant sense;
     see table freeze). A `shot`⊂`snapshot` false-positive arm is therefore
     **dead** — the term cannot fire at all, so it cannot prove
     word-boundary discipline. The word-boundary lock rests on the
     `killed`/`skilled` arm above (and the shared `_contains` seam proof
     8c). Do **not** reintroduce a `snapshot` arm unless `"shot"` is
     restored to the table with a disambiguating rule.
   - **Photographic absence (real zero-hit fixture; documents table
     design, not word-boundary)**:
     `"A clash of colors dominates this wide shot."`
     → assert **zero** hits. Confirms bare `"shot"` is not a violence-
     context term; does not substitute for the `skilled`/`killed` arm.
   - **Trivial cheating implementation that must fail**:
     `if any(t in caption.lower() for t in _VIOLENCE_CONTEXT_TERMS) and
          re.search(r"\b(clash|incident)\b", caption, re.I): flag`
     (raw substring membership). `"killed" in "skilled"` is True under raw
     `in`, so the cheat flags `"clash"` on the skilled-artist caption and
     fails. Using the shared `_contains` helper keeps that caption silent.
8c. **Shared `_contains` seam call — violence-context gate MUST invoke
   `caption_metrics._contains`**
   (`test_violence_context_uses_shared_contains` or equivalent; locks the
   **seam**, not merely boundary behaviour):
   - Monkeypatch / spy `caption_metrics._contains` (e.g. `unittest.mock.patch`
     wrapping the real function, or a call-recording wrapper) while scoring a
     mutual-event caption that carries a true violence-context term, e.g.
     `"Four students were killed during a clash on campus."`.
   - Assert: `_contains` is **actually called** at least once with a
     `needle` equal to a `_VIOLENCE_CONTEXT_TERMS` member (typically
     `"killed"`). A private duplicate `(?<!\w)…(?!\w)` regex that never
     calls `_contains` may pass every behavioural fixture in 8/8b and still
     fails this spy — that is the only assertion that binds the shared
     membership seam the mandate at the table freeze requires.
   - **Do not** allow "or an equivalent boundary match" as a substitute for
     calling `_contains`. Behavioural equivalence is not seam ownership.
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
   - `verified_count` — **honest density contract (option a; locked)**:
     1. **Filter first**: keep only `ReferenceFact` rows with
        `polarity is FactPolarity.TRUE`. False-polarity traps never enter the
        numerator (they are fabrication, already scored by
        `score_hallucination`; proof 4 forces this).
     2. **Then dedupe** surviving rows on three-field identity
        `(fact.text, fact.kind, tuple(fact.phrases))`.
     3. **Then count** how many of those distinct rows have a
        `match_targets()` hit via `_contains`.
     **Do not include `polarity` in the density identity key.** After the TRUE
     filter it is constant, so no fixture over `score_signal_density` alone
     can ever discriminate three-field from four-field identity (a prior
     four-field claim was structurally vacuous). Polarity observability for
     dedupe lives in `score_hallucination` at
     `caption_metrics.py:409-422` (`seen` keyed on
     `(text, kind, polarity, phrases)` and gates both trap and covered
     branches) — that function's contract is unchanged and is **not**
     re-proved as a density claim. Proofs 5a–5c force the three-field key.
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
5. **Dedupe control — three-field identity after TRUE filter**
   (honest density contract; **not** the four-field
   `score_hallucination` identity at `caption_metrics.py:409-422`).
   Cases 5a–5c lock the three-field key (a `seen` set keyed on `fact.text`
   alone fails 5b/5c while still passing 5a). Case **5d locks step order**
   (filter TRUE → then three-field dedupe → then count), not polarity-as-
   identity. **No density proof claims to lock polarity as an identity
   field** — after the TRUE filter polarity is constant, so any such
   polarity-in-key proof is structurally vacuous (an implementation that
   filters polarity before a three-field `seen` always matches four-field
   behaviour on density outputs for TRUE-only rows).

   - **5a. Identical rows count once** (retain; DO NOT BREAK arithmetic):
     - Facts: **two** identical true-polarity rows
       `ReferenceFact(text="bicycle", kind=OBJECT, polarity=TRUE,
       phrases=["bicycle"])` (same text/kind/phrases twice).
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
       phrases=["bicycle"])` (same text/phrases; `kind` differs —
       `FactKind.OBJECT` vs `FactKind.SCENE` at `manifest.py:70-78`).
     - Caption: `"A bicycle leans on a wall."` (both `match_targets()` hit).
     - Assert: `verified_count == 2` (not 1). A `seen` set keyed only on
       `fact.text` collapses these to 1 and fails.

   - **5c. Same `text`, different `phrases` — both count when matched**:
     - Facts:
       `ReferenceFact(text="vehicle", kind=OBJECT, polarity=TRUE,
       phrases=["bicycle"])` **and**
       `ReferenceFact(text="vehicle", kind=OBJECT, polarity=TRUE,
       phrases=["wall"])` (same text/kind; `phrases` differ).
     - Caption: `"A bicycle leans on a wall."` (first matches via `bicycle`,
       second via `wall`).
     - Assert: `verified_count == 2` (not 1). A text-only `seen` set
       collapses these to 1 and fails; the three-field identity keeps both.

   - **5d. Step-order lock — filter TRUE before dedupe**
     (`test_signal_density_filter_before_dedupe` or equivalent; **not** a
     polarity-as-identity-field claim). The honest density contract at
     Slice 3 step 2 mandates: (1) filter to `polarity is FactPolarity.TRUE`,
     (2) **then** dedupe survivors on `(text, kind, tuple(phrases))`,
     (3) **then** count matches. Proofs 5a–5c are all TRUE+TRUE (or
     proof 4 uses different texts `bicycle`/`dog`) and therefore cannot
     distinguish filter→dedupe from dedupe→filter. The existing helper at
     `caption_metrics.py:409-415` does `seen.add(identity)` **before**
     branching on `fact.polarity` — exactly the shape a junior will copy.
     - Facts (order load-bearing): **FALSE first, then TRUE**, same three
       identity fields:
       `ReferenceFact(text="bicycle", kind=OBJECT, polarity=FALSE,
       phrases=["bicycle"])` **and**
       `ReferenceFact(text="bicycle", kind=OBJECT, polarity=TRUE,
       phrases=["bicycle"])`.
     - Caption: `"A bicycle leans on a wall."`
     - Assert: `verified_count == 1` (not 0).
     - **Trivial cheating implementation that must fail** ("dedupe before
       the TRUE filter"): build `seen` on three-field
       `(text, kind, phrases)` over **all** rows first, then filter TRUE —
       the TRUE row is dropped as a duplicate of the FALSE row →
       `verified_count == 0`. Filter-first keeps only the TRUE row, dedupes
       a one-element set, and counts the match → `1`.
     - **Do not reframe 5d as a four-field / polarity-in-key proof.** After
       the TRUE filter polarity is constant; polarity-as-identity-field
       discrimination remains structurally vacuous for density and belongs
       on `score_hallucination` only.
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
keys **with live values**. This emit is **DEPICT-2's own additional
acceptance criterion** (not listed in assessment §6b/§6c/§6e). Slice 3 alone
lands the assessment §3.1 / GPU-window gate (density metric + Williams/C5;
assessment §6e "Dispatch shape — file ownership, not just task ownership"
L373-375). Do **not** implement bake-off ranking *sort* here — that remains
an optional unowned follow-on, **not** the §3.1 gate.

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

**Current emit (verified anchors, open the file — dict ENTRY vs statement)**:
- Per-image **row dict literal**: `report.py:472-495` (opens
  `row: dict[str, Any] = {` at L472; closes at L495). Includes
  `meta_framing_hits` **dict entry** at L486, not depiction hits / density.
  L496–517 are **statements after** the literal (`if short_error is not None:
  row["short_error"] = …` at L496-497; `if long_s is not None: row["long"] =
  {…}` at L498-513; `per_image.append(row)` at L517) — **not** part of the
  row dict literal.
- `_quality_block`: `report.py:540-553` — `meta_framing_images`, sentence band,
  etc. only.
- `result` **dict literal**: `report.py:555-604` (opens
  `result: dict[str, Any] = {` at L555; L554 is blank; closes at L604).
  Caption aggregate entries at L565–574 (`mean_gated_score`, gate rates);
  **no density**. SHORT quality is a **dict entry** at L575:
  `"quality": _quality_block(caption_scores, SHORT_SENTENCE_BAND),`
  — **not** a statement `result["quality"] = …`. There is no assignment
  statement at L575. L575 is **20** lines inside the open literal
  (575 − 555 = 20), not a free statement site.
- After `result` closes: `short_failed_images` block at `report.py:608-610`
  is the first post-literal statement that mutates `result["caption"]`
  (L606–607 are the ALTQ-1 comment only).
- Long quality is a **dict entry** inside the `result["caption_long"] = {…}`
  literal at `report.py:636-644`:
  `"quality": _quality_block(long_scores, LONG_SENTENCE_BAND),` at L643 —
  **not** a statement `result["caption_long"]["quality"] = …`.
- `score_caption` call site: `report.py:398-406` builds `score_kwargs` with
  names/traps/objects/roster/context only — **no `reference_facts`**.
- `short_error` path: `report.py:412-417` — `scores` starts `None` and is
  only populated when `short_error is None`; the per-image row literal is
  still built at `report.py:472-495` (and stamps `row["short_error"]` via
  the post-literal statement at L496-497).
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

**Per-image row** (additive keys **inside** the row dict literal at
`report.py:472-495`; when `scores is None` because of `short_error`, emit
the same keys with `None` / empty values as noted):

| Key | Type when scored | Type when `scores is None` |
| --- | --- | --- |
| `inner_state_attribution_hits` | `list[str]` (from `scores.inner_state_attribution_hits`) | `[]` (key always present; empty list, never omit) |
| `agentless_passive_hits` | `list[str]` (from `scores.agentless_passive_hits`) | `[]` (key always present) |
| `signal_density` | **nested object** (not flat keys): `{ "verified_count": int, "word_count": int, "density_per_100w": float \| null }` | `{ "verified_count": 0, "word_count": 0, "density_per_100w": null }` |

`signal_density` is **always** the nested object mirroring `SignalDensityScores`
field names. Density is computed by the **sibling pure function**
`score_signal_density` (Slice 3) — **not** a `CaptionScores` field.

**Quality / corpus block — SHORT surface only** (additive keys on
`result["quality"]` assigned **after** the `result` dict literal closes at
`report.py:604` — e.g. immediately before the `short_failed_images` block at
`report.py:608-610` — **not** by extending `_quality_block`, and **not** by
inserting statements inside the open `result` literal):

| Key | Type | Definition |
| --- | --- | --- |
| `inner_state_attribution_images` | `int` | `sum(1 for s in caption_scores if s.inner_state_attribution_hits)` — short-surface `caption_scores` only |
| `agentless_passive_images` | `int` | `sum(1 for s in caption_scores if s.agentless_passive_hits)` — short-surface only |
| `mean_signal_density` | `float \| null` | Mean of per-image short-surface `density_per_100w` over the retained density list (see denominator below) |

**Do not extend `_quality_block`** (`report.py:540-553`). That helper is
referenced **twice as a dict ENTRY** (not as free statements):
- SHORT: inside the `result` literal at `report.py:575` —
  `"quality": _quality_block(caption_scores, SHORT_SENTENCE_BAND),`
- LONG: inside the `result["caption_long"] = {…}` literal at
  `report.py:643` —
  `"quality": _quality_block(long_scores, LONG_SENTENCE_BAND),`
Putting `mean_signal_density` (or the depiction hit-image counts) inside
`_quality_block` would either emit a short-surface number under
`caption_long.quality` or invent a null key the locked schema never
sanctioned. Inserting assignment statements at L575 (20 lines inside the
open `result` literal that runs L555–604) is a `SyntaxError` — never do that.

**`caption_long.quality` contract (locked)**:
- `inner_state_attribution_images`, `agentless_passive_images`, and
  `mean_signal_density` **do not belong** in `caption_long.quality`.
- Long quality retains **only** the existing `_quality_block` key set
  (`meta_framing_images`, `mean_context_duplication`,
  `name_front_loaded_rate`, `sentence_band`, `sentence_band_ok_rate`).
- This task does **not** wire density or depiction hit lists for the long
  surface (`alt_text_long` → `long_scores` at `report.py:423-426`).

**Aggregation denominator (locked)**: retain a per-image list
`density_scores: list[SignalDensityScores]` for every **short-surface**
caption that was scored (same loop iteration that calls `score_caption` when
`short_error is None`). Then, **after** the `result` dict literal closes at
`report.py:604` — immediately before the `short_failed_images` block at
`report.py:608-610` (not inside the open literal; not inside
`_quality_block`):

```
# Placement: AFTER `result: dict[str, Any] = { … }` closes at report.py:604,
# BEFORE the short_failed_images block at report.py:608-610.
# result["quality"] already exists from the dict ENTRY at report.py:575:
#   "quality": _quality_block(caption_scores, SHORT_SENTENCE_BAND),
non_none = [d.density_per_100w for d in density_scores if d.density_per_100w is not None]
mean_signal_density = round(sum(non_none) / len(non_none), 4) if non_none else None
result["quality"]["inner_state_attribution_images"] = sum(
    1 for s in caption_scores if s.inner_state_attribution_hits
)
result["quality"]["agentless_passive_images"] = sum(
    1 for s in caption_scores if s.agentless_passive_hits
)
result["quality"]["mean_signal_density"] = mean_signal_density
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
     density_scores.append(density)  # retain for short-surface quality aggregation
     ```

   When `short_error is not None` (no short caption scored), do **not** append
   a density score and do **not** read an uninitialised `density` variable;
   emit the empty/zero `signal_density` object on the row (table above).
   `entry.get("reference_facts", [])` is required because entries arrive as
   dicts (`score_run_record` signature
   `manifest_entries: list[dict[str, Any]]` at `report.py:320-327`), not as
   `GoldenEntry` models.
3. **Per-image emit** (extend the **row dict literal** at `report.py:472-495`
   — add keys **inside** the `{…}` that closes at L495; do **not** treat
   L496–517 as part of the literal):
   - `"inner_state_attribution_hits": scores.inner_state_attribution_hits if scores is not None else []`
     — elements are lower-cased matched surface text (Slice 1 contract).
   - `"agentless_passive_hits": scores.agentless_passive_hits if scores is not None else []`
     — elements are lower-cased matched surface text (Slice 2 contract).
   - `"signal_density": {"verified_count": density.verified_count, "word_count": density.word_count, "density_per_100w": density.density_per_100w}`
     when a short caption was scored; else the empty/zero object
     `{"verified_count": 0, "word_count": 0, "density_per_100w": None}`.
     Initialise `density = None` before the `short_error` branch (or branch
     the emit) so the `scores is None` path never reads an unbound name.
4. **Quality block emit (SHORT only)**: **after** the `result` dict literal
   closes at `report.py:604` (immediately before `short_failed_images` at
   `report.py:608-610`), **assign the three additive keys onto
   `result["quality"]`** per the locked schema and denominator above.
   `result["quality"]` already exists from the dict ENTRY at L575
   (`"quality": _quality_block(caption_scores, SHORT_SENTENCE_BAND),`).
   **Do not** modify `_quality_block`'s body or signature. **Do not** insert
   statements inside the open `result` literal. **Do not** add these keys to
   the long quality dict ENTRY at `report.py:643`
   (`"quality": _quality_block(long_scores, LONG_SENTENCE_BAND),` inside
   `result["caption_long"] = {…}`).
5. **JSON only is the report-axis contract.** The JSON keys above are the
   sole contract for DEPICT-2's report-axis emit (matches Cross-lane
   dependency: JSON quality / per-image sections). Markdown human summary
   (`_quality_lines` at `report.py:766-773`, which today renders only
   pre-existing quality fields) is **explicitly out of contract** for this
   task — do **not** require a `_quality_lines` edit, do **not** mandate
   markdown mention of the new metrics, and do **not** add a markdown
   assertion in Slice 4 proofs. No other JSON key shape is permitted.
   Bake-off ranking *sort* is out of scope (optional follow-on, not the
   gate).

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
   - Assert on `report["per_image"][0]` with **exact hit-list literals**
     (Slice 1 / Slice 2 element semantics — matched surface text,
     lower-cased, source order; **no** "or the detector's hit span string"
     alternative):
     - `"she is anxious"` ∈ `inner_state_attribution_hits`
       (list non-empty; exact membership — marker strings like
       `["inner_state"]` fail).
     - `"were killed"` ∈ `agentless_passive_hits`
     - `"clash"` ∈ `agentless_passive_hits`
     - `signal_density == {"verified_count": 1, "word_count": <exact _WORD_RE
       count of that caption>, "density_per_100w": pytest.approx(100 *
       1 / word_count)}`.
   - Assert on `report["quality"]` (SHORT surface only):
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
     (unconditional empty/zero emit). Exact-value asserts above fail. Also
     fails: `row["inner_state_attribution_hits"] = ["inner_state"]` (marker
     token ≠ `"she is anxious"`).
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
6. **`caption_long.quality` key set — long surface does not grow depiction
   density / hit-image keys**
   (`test_report_emit_depiction_caption_long_quality_keys` or equivalent;
   kills extending `_quality_block` with short-surface density so that the
   long quality dict silently carries wrong or extra keys):
   - One-item fixture: short caption `"A bicycle leans on a wall."` with one
     true bicycle fact; **and** `describe["alt_text_long"]` set to a non-empty
     long caption (e.g. `"A bicycle leans on a wall near the gate."`) so
     `long_scores` is non-empty and `report["caption_long"]` is emitted
     (`report.py:423-426, 629-644`).
   - Assert `report["caption_long"]` is present.
   - Assert **exact** key set of `report["caption_long"]["quality"]`:
     ```python
     set(report["caption_long"]["quality"]) == {
         "meta_framing_images",
         "mean_context_duplication",
         "name_front_loaded_rate",
         "sentence_band",
         "sentence_band_ok_rate",
     }
     ```
     — **no** `mean_signal_density`, **no** `inner_state_attribution_images`,
     **no** `agentless_passive_images`.
   - Assert the SHORT surface still carries the three depiction keys:
     `"mean_signal_density" in report["quality"]`,
     `"inner_state_attribution_images" in report["quality"]`,
     `"agentless_passive_images" in report["quality"]`.
   - **Trivial cheating implementation that must fail**: extend
     `_quality_block` to always emit `mean_signal_density` (and/or the
     hit-image counts). Those keys then appear under
     `caption_long.quality` and the exact key-set assert fails.
7. **Command** (exact path; not "chosen by implementer"):
   ```
   uv run --extra dev pytest scene/tests/test_eval_harness_report_depiction.py -q
   ```

**§3.1 / GPU-window unblock condition**: Slice 3 green means the density
metric exists and Williams/C5 is documented in-module — that **is** the
assessment §3.1 / GPU-window gate (assessment §6b "The GPU window has a
second, cheaper gate than curation" L301-309: §3.1 is the last unlanded
gate; assessment §6e "Dispatch shape — file ownership, not just task
ownership" L373-375: Lane C unblocks the GPU window). Slice 4 green is
**DEPICT-2's own additional acceptance criterion** (live report JSON density
+ hit lists) — not attributed to assessment §6b/§6e. Bake-off *ranking sort*
that orders candidates by density remains an optional separate unowned
consumer; it is **not** a prerequisite for §3.1 or the GPU window.

## Consolidated Checklist

### Context and Ownership

- [ ] Loaded testing-python / backend-python / development-workflow rules.
- [ ] Confirmed owned paths: `caption_metrics.py`,
      `test_eval_harness_caption_metrics.py`, Slice 4 thin `report.py` emit,
      and reserved `test_eval_harness_report_depiction.py` only; no bakeoff
      ranking, schemas, prompts, `test_eval_harness_pipeline.py`, or `canon/`
      edits.
- [ ] Re-verified cited rule IDs with definition-anchor grep against
      `$CANON_LEXICONS_ROOT` / `<bundle-root>/canon/lexicons/` (sibling of
      `repo/`; not bare `canon/lexicons/` from inside `repo/`) before
      implementation review.
- [ ] Relative markdown links resolve from `docs/tasks/depiction/` (no
      `../../docs/...` extra segment; no `../../../canon/...` links). Playbook
      is out-of-tree here — cite by section only.

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
- [ ] Write hedged-WITH-COPULA / external-frame negatives → 0 hits:
      adjacent-copula + external frame `"Apparently she is {adj}…"`,
      `"According to the curator, she is {adj}…"`,
      `"She is {adj}, it seems, …"`; keep one intervening-frame
      `"She is said to be {adj}…"`; hedged-will
      `"He appears to want to open the gate."` (external-frame fixtures
      force frame check; intervening-frame alone does not defeat adjacency).
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
- [ ] Write held-out generalisation proof: compose frozen subject × predicate
      tables with adjuncts from a pool declared in the TEST module only;
      assert ≥1 hit each; no caption **or** held-out adjunct literal shared
      between implementation and tests; source-level guard asserts
      `caption_metrics.py` contains none of the fixture adjunct strings.
- [ ] Hit-list elements = lower-cased matched surface text in source order
      (not marker tokens).
- [ ] Implement detector + `CaptionScores.inner_state_attribution_hits` in `caption_metrics.py`.
- [ ] Confirm `gated_score` unchanged on positive hits.
- [ ] Terminology: attributive/bearer frame only — not "register".
- [ ] `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -k inner_state -q` green.

### Checklist for Slice 2: Agentless-passive / mutual-event detector

- [ ] Freeze `_AGENTLESS_PASSIVE_FORMS`, `_MUTUAL_EVENT_NOUNS`,
      `_GAP_AGENT_PHRASES`, `_VIOLENCE_CONTEXT_TERMS` (**no** `"shot"`),
      `_BY_AGENT_PPS`.
- [ ] State frozen clause-splitting rule (sentence terminators + `;` +
      coordinating-comma patterns `, and `/`, but `/`, or ` + subordinators;
      bare `,` is NOT a splitter) as part of the same-clause contract.
- [ ] Violence-context membership uses `_contains` (`caption_metrics.py:59-74`),
      not raw `in`.
- [ ] Parametrize agentless-passive red-first over EVERY passive form
      (`was killed`, `were killed`, `were beaten`, `was enslaved`, `were arrested`).
- [ ] Parametrize mutual-event red-first over EVERY noun (`clash`, `incident`)
      under `_VIOLENCE_CONTEXT_TERMS` membership.
- [ ] Write discrimination: active-voice named agent, no mutual-event → 0 hits.
- [ ] Write active-voice + clash under violence context → `"clash"` hit,
      no passive-form element (proof 3b).
- [ ] Write per-term violence-context positives (proof 3c): each remaining
      `_VIOLENCE_CONTEXT_TERMS` member as SOLE signal, ≥1 active-voice → hit
      (kills `"killed"`-only proxy).
- [ ] Parametrize adjacent same-clause by-agent exemption over EVERY passive
      form × EVERY `_BY_AGENT_PPS` member → 0 hits.
- [ ] Parametrize non-adjacent same-clause by-agent exemption over EVERY
      passive form × EVERY `_BY_AGENT_PPS` member → 0 hits.
- [ ] Write different-clause unrelated-`by` still-hits (prior clause) using a
      `_BY_AGENT_PPS` MEMBER
      (`"A report by soldiers says four students were killed…"`) → ≥1 hit.
- [ ] Write clause-splitter still-hits (proof 6a): parametrize over EVERY
      locked terminator / coordinator / subordinator with `_BY_AGENT_PPS`
      MEMBERS only (table in proof 6a) → `"were killed"` ∈ hits each; re-check
      gap `"…were killed, agent unknown, on campus."` → 0 hits under bare-comma
      non-split rule. No non-table agents (`"by the mayor"`, etc.).
- [ ] Parametrize following-sentence by-agent still-hits over EVERY passive
      form × `_BY_AGENT_PPS` members
      (`…{passive_form} on campus. The parade was led {agent_pp}."`)
      → ≥1 hit each.
- [ ] Write shared `_contains` seam spy (proof 8c): monkeypatch
      `caption_metrics._contains` and assert the violence-context gate calls
      it for a `_VIOLENCE_CONTEXT_TERMS` member.
- [ ] Parametrize gap-language **exemption** over EVERY `_GAP_AGENT_PHRASES` member
      (same-clause parenthetical) → 0 hits.
- [ ] Write different-clause / prior-sentence gap still-hits
      (`"Agent unknown. Four students were killed on campus."` and the other
      two gap phrases as prior sentence) → ≥1 hit each.
- [ ] Parametrize following-sentence gap still-hits over EVERY passive form ×
      EVERY gap phrase → ≥1 hit each.
- [ ] Parametrize benign mutual-event no-hit over EVERY noun
      (`clash of colors`, `incident of paint`) → 0 hits.
- [ ] Write word-boundary negative (proof 8b):
      `"A skilled artist captures a clash of colors."` → 0 hits
      (`killed`⊂`skilled` only; no dead `shot`/`snapshot` arm — `"shot"`
      intentionally absent from the table); plus photographic absence
      `"A clash of colors dominates this wide shot."` → 0 hits.
- [ ] Hit-list elements = lower-cased matched surface text in source order
      (form / noun strings, not marker tokens).
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
- [ ] Write step-order 5d: FALSE-then-TRUE same `(text, kind, phrases)` →
      `verified_count == 1` (filter TRUE **before** three-field dedupe; kills
      "dedupe before the TRUE filter"). Do **not** reframe 5d as polarity-
      as-identity-field (structurally vacuous after TRUE filter). Contract:
      filter TRUE → three-field `(text, kind, phrases)` dedupe → count matches.
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
      next to the `score_caption` call; retain `density_scores` for **short**
      aggregation.
- [ ] Initialise density safely so the `short_error` / `scores is None` path
      never reads an unbound name; emit exact fallback empty/zero object.
- [ ] Emit locked per-image keys: `inner_state_attribution_hits`,
      `agentless_passive_hits` (exact lower-cased matched surface text), nested
      `signal_density` object only (no flat keys).
- [ ] Emit locked SHORT quality keys **after** the `result` dict literal
      closes at `report.py:604` (immediately before `short_failed_images` at
      `report.py:608-610`; do **not** extend `_quality_block`; do **not**
      insert statements inside the open literal at the L575 dict ENTRY):
      `inner_state_attribution_images`, `agentless_passive_images`,
      `mean_signal_density` with the non-`None` density denominator. Those
      three keys **must not** appear under `caption_long.quality`.
- [ ] Write `scene/tests/test_eval_harness_report_depiction.py` with exact-value
      proofs: non-zero (exact hit literals `"she is anxious"` / `"were killed"`
      / `"clash"`), clean-zero, short_error fallback, multi-image mean
      (unequal densities + empty row + exact denominator), all-empty → None,
      caption_long.quality exact key set with `alt_text_long` fixture.
- [ ] Use `"polarity": "true"` (string) in fixtures; assert
      `ReferenceFact.model_validate` succeeds before `score_run_record`.
- [ ] Leave `test_eval_harness_report.py` deliberately unedited.
- [ ] Confirm no new hard gate / threshold; bakeoff ranking *sort* stays out of scope
      (optional follow-on — not required for §3.1).
- [ ] `uv run --extra dev pytest scene/tests/test_eval_harness_report_depiction.py -q` green.
- [ ] Slice 3 green ⇒ assessment §3.1 / GPU-window gate landed (density +
      Williams/C5; §6b "The GPU window has a second, cheaper gate than
      curation" L301-309; §6e "Dispatch shape — file ownership, not just
      task ownership" L373-375). Slice 4 green ⇒ DEPICT-2's own report-emit
      acceptance criterion (bake-off sort not required).

### Review Readiness

- [ ] No new hard gate or threshold on first land.
- [ ] Every new assertion has red input + discrimination case in the same PR.
- [ ] Williams/C5 resolution is written in-module, not only in this plan.
- [ ] No colour IDs, no `FM-11`, no fabricated `REG`/`ICON`/`FRAM`/`SEL` IDs.
- [ ] Report emit owned by Slice 4 via reserved
      `test_eval_harness_report_depiction.py`; existing
      `test_eval_harness_report.py` deliberately unedited; bake-off ranking
      *sort* still explicit non-scope (optional follow-on, **not** the §3.1 gate).
- [ ] §3.1 / GPU-window gate is treated as density metric + Williams/C5
      (Slice 3; assessment §6b "The GPU window has a second, cheaper gate
      than curation" L301-309; §6e "Dispatch shape — file ownership, not
      just task ownership" L373-375), not as bake-off sort and not as requiring
      report emit. Report emit is DEPICT-2's own extra.
- [ ] Canon IDs cited as plain text with lexicon path, not monorepo markdown
      links; verification grep uses `$CANON_LEXICONS_ROOT` / bundle-root
      `canon/lexicons/` (sibling of `repo/`).
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
      (not a single railing adjunct/complement) **and** held-out adjuncts
      composed at test time from a test-module-only pool (source-level guard);
      hit elements are lower-cased matched surface text; stays silent on
      attributive/bearer frames (including attributed common-noun frames **and**
      adjacent-copula + external-frame hedges such as
      `"Apparently she is anxious…"` /
      `"According to the curator, she is anxious…"` /
      `"She is anxious, it seems, …"` / intervening-frame
      `"She is said to be anxious…"` /
      `"He appears to want…"`), epistemic hedges (`seems` / `looks` /
      `appears` / `as if` — each proved zero-hit), visible-cue inventory,
      non-person subjects with affect/will, and person subjects without a
      frozen predicate; mixed hedged+unhedged captions still fire on the
      unhedged clause; no caption-literal frozenset detector passes the suite.
- [ ] Agentless-passive detector fires on **every** frozen passive form and
      **every** frozen mutual-event noun under `_VIOLENCE_CONTEXT_TERMS`
      membership via `_contains` (including active-voice violence + `clash`
      → `"clash"` hit with no passive-form element, and **every** remaining
      context term as sole signal — not a `"killed"`-only proxy); fires on
      passives whose only `by` is in a different clause (prior **or following**,
      including coordinating-comma and subordinator splitters) **and** on
      passives whose only gap phrase is in a prior **or following** sentence /
      different clause; stays silent on named-agent active voice without
      mutual-event, adjacent **and** non-adjacent same-clause `by`-agent
      passives for **every** frozen passive form × **every** `_BY_AGENT_PPS`
      agent phrase, benign mutual-event uses, substring false-positives
      (`killed`⊂`skilled` word-boundary via `_contains`), photographic
      `"shot"` (term intentionally absent from the table; wide-shot fixture
      zero-hit), cross-clause still-hits for **every** locked splitter with
      table-member agents only, shared `_contains` seam call for violence-
      context membership, and ATTRIB-08-compliant same-clause gap-language
      statements for **every** `_GAP_AGENT_PHRASES` member (including
      `"…killed, agent unknown, …"` under bare-comma non-split); clause-
      splitting rule is frozen; hit elements are lower-cased matched surface
      text.
- [ ] Signal density ranks grounded captions above rare-ungrounded and
      ornament-padded captions with equal or fewer verified facts; rare
      ungrounded nouns never raise the score; false-polarity traps never
      increment `verified_count` (TRUE filter before count); duplicate
      identical true-fact rows count once; true facts sharing `text` but
      differing in `kind` or `phrases` are not collapsed by a text-only
      `seen` key (5a–5c: three-field identity after TRUE filter — polarity is
      **not** a density identity field); FALSE-then-TRUE same three-field
      identity still yields `verified_count == 1` (5d step-order: filter
      before dedupe); empty caption → `density_per_100w is None`.
- [ ] `score_signal_density` returns the mandated multi-field score object
      (`word_count == 6` and `approx(100/6)` on the bicycle fixture) as a
      **sibling pure function**, not a `CaptionScores` field.
- [ ] Module docstring states Williams (gate) and C5 (ranking) as distinct roles.
- [ ] Report JSON emits the locked schema: per-image nested `signal_density`
      object + hit lists with **exact lower-cased matched surface literals**
      (keys inside row dict literal `report.py:472-495`), SHORT quality-level
      `mean_signal_density` (multi-image mean with non-None denominator;
      all-empty → None) + hit-image counts assigned **after** the `result`
      literal closes at `report.py:604` (not via `_quality_block`; not inside
      the open literal at the L575 dict ENTRY), `caption_long.quality` keeps
      only pre-existing `_quality_block` keys, and exact fallback keys when
      `short_error` makes `scores is None` (Slice 4 — DEPICT-2 own criterion).
- [ ] Fixtures use `"polarity": "true"` (StrEnum string); `ReferenceFact.model_validate`
      succeeds on them.
- [ ] Metrics tests and
      `scene/tests/test_eval_harness_report_depiction.py` green at branch HEAD.
- [ ] No files outside the owned paths (`caption_metrics.py`,
      `test_eval_harness_caption_metrics.py`, `report.py`,
      `test_eval_harness_report_depiction.py`) modified; existing
      `test_eval_harness_report.py` deliberately unedited.
- [ ] Assessment §3.1 / GPU-window gate **landed** by Slice 3 (density metric
      + Williams/C5; §6b "The GPU window has a second, cheaper gate than
      curation" L301-309; §6e "Dispatch shape — file ownership, not just
      task ownership" L373-375). Slice 4 report emit is DEPICT-2's own additional
      acceptance criterion. Bake-off ranking *sort* remains optional unowned
      follow-on (not the §3.1 gate).

## Not-Doing

- Prompt text / emotion-bearer edits (Lane A; DEPICT-4).
- Contract, schema, enum, `voice`, `DescriptionRegister`, bound-term fields
  (Lane B). Future register-compliance metric that would read
  `DescriptionRegister` is named only (Stretch); not implemented here.
- Bake-off ranking *order* / sort-by-density logic (`bakeoff.py` consumer) —
  **unowned** by this task; keys land in Slice 4 but sort code does not.
  Sort is an **optional follow-on**, not the §3.1 / GPU-window gate
  (assessment §6b "The GPU window has a second, cheaper gate than curation"
  L301-309: §3.1 = density metric; §6e "Dispatch shape — file ownership, not
  just task ownership" L373-375: Lane C unblocks).
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
  violations (Slice 2 exempts same-clause `_GAP_AGENT_PHRASES`; prior- **and**
  following-sentence / different-clause gap phrases still hit — see proofs
  7b and 7c).
- Edits to the existing shared `test_eval_harness_report.py` (deliberately
  unedited; DEPICT-2 owns only the reserved depiction report-emit file).
- LLM-judge scoring, model training, non-deterministic axes.
