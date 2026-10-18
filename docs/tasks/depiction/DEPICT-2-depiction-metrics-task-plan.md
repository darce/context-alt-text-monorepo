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
> (F6, F8). **Playbook** (governing §3.1 source):
> `docs/runbooks/fir-captioning-orchestrator-playbook.md` §3.1 (signal density;
> §3.2 is stale — ALTQ-1 shipped it). Relative from this file:
> `../../runbooks/fir-captioning-orchestrator-playbook.md`. Cite by section
> heading (e.g. `### 3.1 Add a signal-density metric to the eval harness`) —
> line numbers move.
>
> **Canon**: heuristics-canon **`v0.17.2`**, commit
> `4e099ded65ee33bc4db85dfd4c65409a0087a752`. Citable rule surface:
> `canon/lexicons/`. Do **not** cite `canon/PROVENANCE.txt`. Do **not** label
> the pin `v0.17.0-11-ga238620` (that is a pre-tag `git describe` string for
> commit `a238620`; `git describe --tags a238620` resolves to **`v0.17.1`**).
> Slice 2 cites the **v0.17.2** three-disjunct ATTRIB-08 wording at
> `canon/lexicons/depiction.md#attrib-08` (third disjunct + `"an incident"`
> exemplar). Citation form: `canon/lexicons/<file>.md#anchor`. Before
> implementation review re-verify every rule ID with the definition-anchor
> form: `grep -rE '^\| *`?<ID><a name' canon/lexicons/`.

## Objective

Land three pure, deterministic, report-only scoring signals in
`caption_metrics.py` that make **F6 / F8**, **future attributed-emotion
prompt work**, and the **density measurement** measurable (not a claim
that DEPICT-0 lineage or DEPICT-1 contract shape are scored here —
DEPICT-1 register-compliance is Stretch / future work only): an
inner-state-attribution counter
(ATTRIB-01 / F8, `canon/lexicons/depiction.md#attrib-01`), an
agentless-passive / mutual-event / actorless-event-noun detector
(ATTRIB-08 / F6, `canon/lexicons/depiction.md#attrib-08`), and a
**verified** signal-density *measurement*
(EVAL-11, `canon/lexicons/ml-systems.md#eval-11`). Emit the new hit lists and
density from `report.py` (thin additive Slice 4) so density is a **live
report measurement** (JSON emit only — not a ranking consumer).

**Canonical DoD / ownership boundary (authoritative — state once; every
other section cross-refers here and does not restate the full boundary):**

| Boundary | Landed by | Not landed by this plan |
| --- | --- | --- |
| **This plan's §3.1 land DoD** — density *measurement* in `caption_metrics.py` + Williams/C5 docstring | Slice 3 green | bake-off ranking *sort* |
| **Report emit of density + depiction hit lists** (assessment §6e Lane C Carries "report emit of new fields") | Slice 4 green | ranking *sort* |
| Bake-off ranking *sort* that *orders* candidates by density | **unowned** — no lane in this wave owns the ordering change | Slice 3/4 green does **not** land sort |

**Ranking / GPU-window honesty (locked):** `report.py` today emits quality
JSON and performs **no** candidate selection or density ordering (see
`_quality_block` / `result` construction). Playbook §3.1 describes density
as the companion that stops length-only ranking from preferring the most
verbose candidate — but **no consumer in this plan orders by density**.
This plan therefore lands the **measurement + report emit** only. The
bake-off ranking *sort* remains **unowned and unmet**. Do **not** claim
the ranking gate is satisfied by a metric nothing consumes. Resolve the
Williams/C5 length contradiction in the module docstring so gate policy
and ranking policy cannot be read as opposites.

Assessment anchors (cite by heading, not line): playbook
`### 3.1 Add a signal-density metric to the eval harness`; assessment
`#### §6b claim — §3.1 is the last unlanded GPU-window gate`;
`#### §6c claim — Williams/C5 resolution (companion axes)`;
`### 6a. Playbook status is half-stale — verify before dispatching §6's list`
table row **§3.1 signal-density metric** Actual **NOT LANDED**;
`#### §6e ownership table`; `#### §6e claim — Lane C unblocks the GPU window`.

## Problem Statement

The caption harness can already gate wrong names, score fabrication traps, and
flag meta-framing, but it cannot see the highest-value depiction safety signal
LIBSYN-1 named (inner-state attribution on a depicted person), cannot flag the
cheapest grammar failure in the depiction lexicon (agentless passive / "clash"
frames), and measures no signal density at all. Every length-correlated quality
axis therefore still rewards verbosity. Until these scorers exist, F6/F8 and the density axis stay unmeasurable —
exactly what EVAL-08 (`canon/lexicons/ml-systems.md#eval-08`, CACE)
forbids. Pure scorers alone are not enough for *this plan's* DoD: density
must also be emitted from `report.py` (see **Objective** DoD table).
Bake-off ranking *sort* is unowned and unmet — not a DEPICT-2 acceptance
criterion.

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

## Source-guard contract (locked; every held-out proof)

All "source-level guard" assertions share this one mechanical contract.
A prose-only "held-out means held out" sentence is **not** a guard.

### Scope

Owned implementation path set (from **Constraints**):

- `apps/prototype-description-service/scripts/eval_harness/caption_metrics.py`
- any sibling under `scripts/eval_harness/` that `caption_metrics.py`
  imports for string / tuple / list / frozenset detector tables

**Import RED**: AST-parse `caption_metrics.py`; it must not import detector
tables from outside that set, and must not load YAML / JSON / data files of
phrase tables for detector membership. Test modules are **out of guard
scope** — held-out fixtures live there.

### Extraction (constant-fold AST, not raw text)

Guards operate on **fully folded string values** from the AST — not raw
`Path.read_text()` substrings, and not leaf `ast.Constant` nodes alone.
**Constant-fold before matching** so non-contiguous encodings cannot hide
held-out literals:

```python
import ast
from pathlib import Path

def _fold_str(node: ast.AST) -> str | None:
    """Fold literal string expressions; None if not a pure string literal expr."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    # Implicit concat is already one Constant after parse; handle BinOp +
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _fold_str(node.left), _fold_str(node.right)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.JoinedStr):  # f-string of only constants
        parts: list[str] = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            elif isinstance(v, ast.FormattedValue):
                return None  # non-literal f-string arm
            else:
                return None
        return "".join(parts)
    if isinstance(node, ast.Call):
        # "".join([...]) / str.join over a list/tuple of string constants
        func = node.func
        if (isinstance(func, ast.Attribute) and func.attr == "join"
                and isinstance(func.value, ast.Constant)
                and func.value.value == ""
                and node.args):
            elt = node.args[0]
            if isinstance(elt, (ast.List, ast.Tuple)):
                parts = [_fold_str(e) for e in elt.elts]
                if parts and all(p is not None for p in parts):
                    return "".join(parts)  # type: ignore[arg-type]
        # "a".replace("x","y") chain over constants
        if (isinstance(func, ast.Attribute) and func.attr == "replace"
                and len(node.args) >= 2):
            base = _fold_str(func.value)
            a0, a1 = _fold_str(node.args[0]), _fold_str(node.args[1])
            if base is not None and a0 is not None and a1 is not None:
                return base.replace(a0, a1)
    return None

def module_string_constants(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        folded = _fold_str(node)
        if folded is not None:
            out.add(folded.lower())
        # Also collect every Constant str leaf (covers non-expr positions)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.add(node.value.lower())
    return out
```

What this closes beyond leaf-Constant matching:

1. **Comments stay legal** — not `ast.Constant` / not foldable expressions.
2. **Escape / hex** — `'\x73kirmish'` → `'skirmish'`.
3. **Implicit adjacent-literal concat** — `"skir" "mish"` → one Constant.
4. **`+` concatenation** — `"ACX_GPU_" + "PROMPT_VERSION"` folds to one value.
5. **`"".join([...])` over constant fragments** — folds to one value.
6. **`.replace()` over constants** — folds to the replaced value.
7. **Data-file reads** — closed by Import RED (no external table load) **and**
   the **runtime arm** below (positive set must not contain the held-out at
   call time even if built dynamically).

### Matching (whole phrase + article-stripped forms)

```python
import re
_ART_ANY = re.compile(r"\b(the|a|an)\s+", re.I)

def article_stripped_forms(phrase: str) -> set[str]:
    p = phrase.strip().lower()
    forms = {p, _ART_ANY.sub("", p).strip(),
             re.sub(r"^(the|a|an)\s+", "", p).strip()}
    return {f for f in forms if f}

def constant_hides_held_out(constant: str, phrase: str) -> bool:
    c = constant.lower()
    return any(f in c for f in article_stripped_forms(phrase))
```

**Legitimate shapes still accepted**: bare role / person heads (e.g.
`"mayor"`) do **not** hide held-out `"by the mayor"`; only full phrase
forms (`"by the mayor"`, `"by mayor"`) do.

### Semantic arm + runtime positive-set arm (mandatory)

- **Held-out POSITIVES** (must still fire): floor tables at frozen membership
  (**no** held-out token appended) **and** every *additional* membership
  table beyond named floors emptied to `()` → each held-out positive still
  hits.
- **Held-out NEGATIVES / exemptions** (must stay silent): every frozen
  exemption / hedge / bearer / gap / by-agent **floor** the proof extends
  beyond emptied to `()` **and** every additional exemption-membership
  table emptied → each held-out negative still returns **zero** hits under
  the scoped assert the proof names.
- **Runtime positive-set arm (mandatory companion to AST fold)**: after
  import, for every held-out literal `L`, assert `L` (and each
  article-stripped form) is **not** a member of any detector positive /
  exemption membership collection the implementation exposes or that the
  test can reach via the module's table attributes (tuples / lists /
  frozensets / sets of strings used for detector membership). This catches
  tables built at import from concatenation, decoding, or in-module data
  that the fold arm already saw **and** any residual dynamic construction
  the fold arm cannot see. A cheat that builds the held-out only inside a
  function body still fails the semantic arm above.

### Shared helper

One test-module helper: scope walk + import RED + folded-AST extract +
article-strip match + semantic monkeypatch + runtime positive-set arm.
Every "source-level guard" proof calls it.

## Workflow Principles

- **Measurement before change.** Land scorers before (and independent of) the
  prompt edits they make measurable (EVAL-08, `canon/lexicons/ml-systems.md#eval-08`).
- **Williams vs C5 — both hold, different roles.** Williams governs the **gate**:
  do not hard-cap length; do not zero a long description for being long.
  C5 / playbook §3.1 names density as the companion that prevents
  length-only ranking from preferring verbosity. This plan lands the
  **measurement** only (see **Objective** — ranking *sort* unowned/unmet).
  Density is never a length penalty on `gated_score`. Write Williams/C5 into
  the module docstring in Slice 3.
- **Attributive / bearer frame, not silence for affect.** Attributed readings
  ("her expression reads as anxious") are legitimate access content; unmarked
  person-as-fact-owner ("she is anxious") is the defect. The counter must
  distinguish them — that distinction *is* the discrimination test. Reserve
  the word **register** / `DescriptionRegister` for DEPICT-1 contract vocabulary
  (`FORENSIC | EDITORIAL | INTERPRETIVE`); do not reuse "register" for this
  grammar cut.
- **Voice disambiguation (DEPICT-2):** in this plan **voice** means the
  grammatical/narrative surface of caption prose (active vs agentless
  passive, reporting frame). It does **not** mean DEPICT-1's `ContextVoice`
  provenance tag on a context field.
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
  of the reading off the depicted person. Slice 1's exemption proof covers
  **exactly** the frozen floor hedges/bearers plus the five published held-out
  frames in proof 4b (see Slice 1 — **bounded**, not an open class). Recovery
  uses the closed reporting lexicon + linear window named there. Not to be
  confused with DEPICT-1 `DescriptionRegister`.
- **Agentless passive / mutual-event / actorless event noun (ATTRIB-08
  three disjuncts)**: oppression or violence prose that hides a
  record-supported actor behind **any** of the three ATTRIB-08
  (`canon/lexicons/depiction.md#attrib-08`) Trigger-column disjuncts —
  (1) an **agentless passive** ("were killed"), (2) a **mutual-event noun**
  ("a clash"), **or** (3) an **event noun that carries no actor**
  ("an incident"). Do **not** collapse (2) and (3). Floor table members
  `"clash"` / `"incident"` are mandatory hits; disjunct-3 noun heads beyond
  the floor are the **published held-out pool** in Slice 2 proof 2b (bounded
  proof set). Explicit same-clause gap statements are an ATTRIB-08
  **exemption** (lexicon: "when the record does not support naming who
  acted, state the gap rather than invent an agent").
- **Verified fact (density numerator)**: a `ReferenceFact` with
  `polarity=FactPolarity.TRUE` (StrEnum value `"true"`) whose
  `match_targets()` hit the caption under `_contains`. Unmatched claims
  contribute **zero** (operational membership only — not a PROV-01 citation).
- **Signal density (measurement axis)**: verified facts per 100 words =
  `(verified_count / word_count) * 100`, or `None` when `word_count == 0`.
  Report measurement only — not a hard gate and not a landed ranking *sort*
  (see **Objective**).
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
- `report.py` `_quality_block` emits only meta-framing / sentence-band /
  name-front-loaded stats; caption aggregate has `mean_gated_score` and
  existing gate rates. No density or depiction-hit keys. Per-image row
  surfaces `meta_framing_hits` but not inner-state / agentless / density.
- `score_caption` is called without `reference_facts`; manifest entries
  expose `reference_facts` but `score_run_record` never reads them today.
- `bakeoff.py` does **not** import `caption_metrics` today. Ranking *sort*
  by density is unowned and unmet (see **Objective**).

## Target Outcome

1. Pure functions (and additive score fields where they fit the existing
   `CaptionScores` / aggregate pattern) that:
   - count inner-state-attribution hits (report-only; F8);
   - list agentless-passive / mutual-event / actorless-event-noun hits
     (report-only; F6; ATTRIB-08 three disjuncts);
   - compute verified signal density as a report measurement (see
     **Objective** — ranking *sort* unowned/unmet).
2. Module docstring resolves Williams (gate) vs C5 (density measurement).
3. Every new assertion has a red-first proof and a discrimination case that
   rejects vacuous implementations.
4. `report.py` emits the new per-image hit lists and density numbers
   (Slice 4). DoD boundary: see **Objective**.

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
| Report JSON quality / per-image emit | Lane C (Slice 4) | `report.py` `_quality_block` + per-image rows read known `CaptionScores` fields; no `reference_facts` wire | additive nested `signal_density` object + hit-list keys; SHORT quality mean/counts assigned **after** the `result` dict literal closes at `report.py:604` **and after** the `short_failed_images` block at `report.py:608-610` (do not extend `_quality_block`; do not insert inside the open literal; do not insert between the ALTQ-1 comment and its statement); wire facts → density | no — additive keys | `test_eval_harness_report_depiction.py` exact-value proofs |
| Bake-off ranking *sort* | **unowned** | `bakeoff.py` does not import `caption_metrics` | **none** — ranking unowned and unmet (see **Objective**) | n/a | explicit non-scope |

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
not orphaned behind zero report consumers. DoD: see **Objective**.

### `CAL-02` and density numerator — metric side only (scope decision)

Assessment §10f mentions `CAL-02` abstain and `PROV-01` on the
prompt+metric surface. Cite PROV-01 from the **lexicon row only**
(`canon/lexicons/ml-systems.md#prov-01`, definition-anchor form; Failure:
*"A description or identity is emitted without model and input
lineage"*; Fix: *"**Every output walks back to its evidence**: the model
revision, preprocessing, thresholds, and source observations are part of
the result, or the output cannot be reproduced after the model
changes"*). Do **not** substitute the assessment §10f gloss ("an attribute
claim must walk back to evidence, not to fluent invention") or any
`canon/public/reasoning/` card paraphrase — reasoning cards are exposition,
not normative. Prompt side is out of this lane. Metric side:

| Rule / topic | What existing metrics already cover | What would be new | Decision |
| --- | --- | --- | --- |
| Density numerator membership (operational; **no PROV-01 citation**) | `fabricated_fact_rate` catches known-false traps; `HallucinationScores.coverage` measures true-fact hit rate | A **positive** verified-membership filter on density's numerator | **In scope as density definition**, not a second headline metric and **not** a PROV-01 application. Density counts only true-polarity `ReferenceFact` rows whose `match_targets()` hit via `_contains`. PROV-01 (`canon/lexicons/ml-systems.md#prov-01` → `distilled/ml-systems/model-cards.md`) is the lineage-on-outputs rule quoted above — not gold-label membership for a density numerator — so it is **not cited** here. Restating coverage as a new named metric is refused. |
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
| report emit (Slice 4) | `apps/prototype-description-service/scripts/eval_harness/report.py` | Thin additive: wire `reference_facts` → `score_signal_density`; emit exact density object + hit-list keys in the per-image row dict literal (`report.py:472-495`); assign SHORT quality depiction keys after the `result` literal closes at `report.py:604` **and after** the `short_failed_images` block at `report.py:608-610` (do not extend `_quality_block`; do not orphan the ALTQ-1 comment); no ranking logic, no gates |
| report tests (Slice 4) | `apps/prototype-description-service/scene/tests/test_eval_harness_report_depiction.py` | **New reserved file** owned by DEPICT-2 only. Assert report JSON carries exact density object + hit-list keys **and values**. Do not extend DEPICT-0's `test_eval_harness_pipeline.py` or any other shared harness test. |

## Related Files

| File | Note |
| --- | --- |
| `scripts/eval_harness/manifest.py` | `ReferenceFact.match_targets()` is the density walkback primitive — read only |
| `scripts/eval_harness/bakeoff.py` | Unowned ranking *sort* consumer — does not import `caption_metrics` (see **Objective**) |
| `docs/runbooks/fir-captioning-orchestrator-playbook.md` §3.1 | Governing density-metric requirement (cite by heading). DoD: **Objective**. |

### Cross-lane dependency

| File | Exact change needed | Who lands first |
| --- | --- | --- |
| `scripts/eval_harness/report.py` | Emit per-image hit lists + density in **JSON** (Lane C Carries report emit — **Objective**). Markdown summary out of contract. | **Lane C, Slice 4** after Slices 1–3 green |
| Bake-off ranking *sort* | Optionally order survivors by density | **unowned and unmet** (see **Objective**) |
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
- **Williams/C5 docstring (mechanical, not manual):** Slice 3 Proof item 8
  asserts the module docstring contains both the Williams gate statement and
  the C5 ranking / density statement as distinct roles (string-presence
  check). That proof is the acceptance criterion — there is **no**
  subjective manual re-read clause in this plan's DoD.
- DoD land conditions: see **Objective**.

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
frame. The load-bearing lexicon warrant is ATTRIB-01
(`canon/lexicons/depiction.md#attrib-01`): "state visible cues only, or
attribute the reading to viewer, convention, artefact, or named source".
Berger verification recipe (distilled evidence, not vocabulary): person-subject
+ mental predicate **without** appears / as-if / according-to (and looks /
seems). Operational cut: attributed surface readings stay; unmarked ownership
fails. Do not call this cut "register" — `DescriptionRegister` is DEPICT-1
contract vocabulary.

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
  # Exemption floor (must each carry a zero-hit proof). A suppression
  # mechanism that is *only* membership over these two tuples fails proof 4b.
  _INNER_EPISTEMIC_HEDGES = ("seems", "looks", "appears", "as if", "reads as")
  _INNER_BEARER_FRAMES = ("apparently", "according to", "it seems", "said to be")
  # Closed reporting / perception / source-frame lexicon for surface recovery
  # (H-18: enumerated here — not invented by the implementer). Covers exactly
  # the stems/frames needed by the floor + the five published 4b fixtures +
  # the 4c trailing frame. Extending requires amending this plan.
  _INNER_REPORTING_STEMS = (
      "seems", "looks", "appears", "reads",           # perception / hedge
      "records", "insists", "suggest", "suggests",    # reporting (4b)
      "said",                                         # "said to be"
  )
  _INNER_SOURCE_FRAME_PATTERNS = (
      "according to",           # floor bearer
      "on ",                    # prefix for "on the curator's reading" — 4b
      "by the conventions of",  # 4b convention frame
      "apparently",             # floor bearer
      "it seems",               # floor bearer
      "as if",                  # floor hedge
      "reads as",               # floor hedge
  )
  ```

  **Exemption scope (EXIT B — bounded; not an open class):** the exemption
  proof covers **exactly** (a) every member of `_INNER_EPISTEMIC_HEDGES` +
  `_INNER_BEARER_FRAMES` and (b) the **five published held-out frames** in
  proof 4b plus the trailing-frame negative in 4c. It does **not**
  generalise beyond that published set; extending it requires amending this
  plan. ATTRIB-01's lexicon license is broader in prose, but **this detector
  contract is the finite published set below**.

  **Exemption mechanism (locked):** the affect / will predicate is exempt
  when the linear-window test below recovers a frame from the closed
  reporting lexicon / source-frame patterns (not a membership test over the
  two floor tuples alone). Grammar + closed lexicon; no parser / voice tagger.

  **Surface recovery (locked algorithm):**

  1. **Closed floor + closed reporting lexicon** (tables above). Floor
     membership is the proof floor for item 4; 4b held-outs are additional
     published forms recovered via `_INNER_REPORTING_STEMS` /
     `_INNER_SOURCE_FRAME_PATTERNS` + the linear window — **not** by
     appending their full strings to the floor tuples.
  2. **Complementiser / frame-linker surface set** (closed):
     ` that `, zero-complementiser finite complement after a reporting
     stem, and sentence-initial / pre-subject source-frame PPs matching
     `_INNER_SOURCE_FRAME_PATTERNS`.
  3. **Linear "sits inside the complement" test** (tokenise on whitespace /
     punctuation into list `T`; ownership span = person subject + unmarked
     copula+affect or person subject + will stem as index range `[i, j]`):
     the span is **exempt** when **any** of:
     - **(a) Pre-subject frame adjunct**: a source-frame pattern from the
       closed set (floor or a 4b published form recovered via the reporting
       lexicon) occupies tokens before the person subject in the same clause
       segment, with no clause splitter between frame and subject;
     - **(b) Reporting-predicate + complementiser window**: a stem from
       `_INNER_REPORTING_STEMS` at index `r < i` such that between `r` and
       `i` there is a complementiser from the closed set (or
       zero-complementiser for finite-complement stems) **and** no clause
       splitter, and `i - r ≤ 12` tokens;
     - **(c) Post-predicate parenthetical / trailing frame**: a floor
       bearer/hedge **or** the published 4c trailing frame appears after
       `j` in the same clause segment within **8** tokens.
  4. **Named REDs**:
     - membership-only over the two exemption floor tuples → fails 4b;
     - whole-caption "any hedge token anywhere" → fails 11a / 11b / 11c;
     - unlimited forward scan past clause splitters → fails mixed-caption
       proofs;
     - stem-regex / alternation over only the five 4b stems with no window
       structure → fails position-axis 4c positives and/or mixed-caption
       proofs;
     - parser or voice-tagger → **out of scope**.

  Minimum detectable patterns:
  - person pronoun / common person noun subject + **unmarked** copula +
    interior adjective from `_INNER_COPULA_AFFECT` (`she is anxious`,
    `he is angry`, `the person is proud` — person as fact-owner of the mental
    predicate with no attributive / hedge frame);
  - person subject + will / intent verb from `_INNER_WILL_VERBS`
    (`she wants`, `he refuses`, `they refuse` as interior will — **not**
    physical-action or non-person-subject uses of those stems). Detector
    must match stem **and** 3sg (`want`/`wants`, `refuse`/`refuses`); proofs
    use both. Physical-refusal / non-interior carve-out is proved zero-hit
    in proof item 5 (not by table absence alone).
- **Must not fire** when an attributive / bearer frame or epistemic hedge owns
  the reading: `her expression reads as anxious`, `she looks anxious`,
  `appears anxious`, `he seems angry`, `as if anxious`, `read as anxious`,
  furrowed-brow **visible cue** inventory without mental-state ownership.
  `seems` is the same hedge class as `looks` / `appears` (ATTRIB-01 / Berger
  recipe); do **not** treat hedged readings as person-as-fact-owner. The
  listed forms are the floor; the five published 4b frames are additional
  bounded exemptions recovered via the closed reporting lexicon (not by
  appending their full strings to the floor tuples).
- Surface hits as an additive report-only field on `CaptionScores`
  (`inner_state_attribution_hits: list[str]`, parallel to
  `meta_framing_hits`) populated inside
  `score_caption`. Do **not** leave the surface shape open (no "or sibling
  pure function" fork for the hit list that report emits). A pure helper used
  internally by `score_caption` is fine; the report-facing field is the
  `CaptionScores` list. Do not touch `gated_score`.
- **Hit-list element semantics (locked; Slice 1)**: each element is the
  **matched surface text** of the ownership pattern, **lower-cased**, in
  **source order** of first match (same contract shape as
  `meta_framing_hits`). Examples: `"she is anxious"`, `"he wants"`,
  `"the woman is proud"`. Marker tokens are **not** legal elements.
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
     readings (`canon/lexicons/depiction.md#attrib-01`: "state visible
     cues only, or attribute the reading to viewer, convention,
     artefact, or named source") that a frame-blind adjacency matcher
     cannot silence.
   - **4b. Published held-out exemption set (bounded; exactly five frames).**
     Every negative above uses a member of `_INNER_EPISTEMIC_HEDGES` /
     `_INNER_BEARER_FRAMES`, so a suppression rule that is **only**
     membership over those two tuples passes item 4 while still flagging
     the five frames below. These five are the **entire** additional
     exemption proof set for Slice 1 — not an open class, not a sample of a
     larger class. Extending beyond them requires amending this plan.
     Each is person subject + copula + affect **adjacent** with a frame
     recovered via `_INNER_REPORTING_STEMS` / `_INNER_SOURCE_FRAME_PATTERNS`
     (not by appending the full frame string to the floor tuples), and each
     must return **zero** hits:
     - `"The catalogue records that she is proud by the doorway."`
     - `"Her granddaughter insists that he is angry in the courtyard."`
     - `"On the curator's reading, she is anxious near the window."`
     - `"By the conventions of the studio portrait, the woman is proud near
       the gate."`
     - `"Museum records suggest the man is anxious by the window."`
     - Assert each: **zero** hits. Named RED: membership-only over the two
       floor tuples. Named RED: fixing a failure by appending full frame
       strings (`"the catalogue records"`, etc.) to a floor table — the
       source-guard contract forbids those literals in implementation.
   - **4c. Position-axis lock — leading-adjunct POSITIVE that must hit**
     (`test_inner_state_leading_adjunct_still_hits` or equivalent; kills the
     position cheat left open by 4b **and** its successor whitelist of
     scaffold leading adjuncts). Every 4b held-out negative places the
     attributive frame **before** the subject. Cheat class that must fail:
     any exemption conditioned on a **closed set of leading-adjunct
     strings** (or on `not subject_is_sentence_initial(sent)` alone) —
     including a whitelist of only the three scaffold prefixes that recur
     in proofs 1–11 (`near the window` / `by the doorway` /
     `in the courtyard`). That class passes proofs 1–11 + 4b while
     exempting unmarked ownership under any **other** leading adjunct.
     - **Scaffold leading-adjunct positives** (assert ≥1 hit each; these
       adjuncts are **not** exemption frames — they are ordinary locatives;
       they also appear as trailing scaffolds elsewhere and are **not**
       held-out):
       - `"Near the window, she is anxious."`
       - `"By the doorway, he is angry."`
       - `"In the courtyard, the woman is proud."`
     - **Held-out leading-adjunct positives** (assert ≥1 hit each; these
       adjunct strings appear in **no other fixture** in this plan and
       MUST NOT be added to any implementation exemption / scaffold
       table — source guard below):
       - `"Outside the gate, she is anxious."`
       - `"Along the fence line, he is angry."`
     - Assert each (scaffold + held-out): ≥1 hit on the interior ownership
       span (`"she is anxious"` / `"he is angry"` / `"the woman is proud"`).
     - **Trivial cheating implementations that must fail**:
       1. any exemption that fires when the person subject is not
          sentence-initial (or when a leading comma-adjunct precedes the
          subject);
       2. any exemption / silence conditioned on membership in a closed
          set of leading-adjunct strings (the three scaffold prefixes, or
          those three plus any finite append of held-out prefixes).
       These captions have no ATTRIB-01 bearer frame and **must** hit.
     - **Held-out trailing-frame negative** (position on the exemption side;
       frame after the adjacent copula+adj, not only frame-initial):
       `"She is anxious near the window, on the curator's reading."`
       → **zero** hits. A cheat that only silences frame-**initial** held-out
       forms still fires here and fails.
     - **Source-level guard (mandatory; 4b frames + 4c held-out adjuncts +
       trailing frame)**: per **## Source-guard contract** — AST string
       constants over the owned implementation closed path set (not raw
       `read_text()`), article-stripped core match, import RED, and
       semantic arm (empty exemption floor tables → held-out 4b / trailing
       frame still zero-hit; held-out 4c leading adjuncts still hit with
       no adjunct whitelist append). Held-out literal set:
       - `"the catalogue records"` (core: `"catalogue records"`)
       - `"her granddaughter insists"`
       - `"on the curator's reading"` / `"on the curators reading"`
       - `"by the conventions of the studio portrait"`
         (core after article strip on the inner NP as matched)
       - `"museum records suggest"`
       - `"outside the gate"`
       - `"along the fence line"`
       Enumerating any of these (or their article-stripped cores) into an
       exemption table, a leading-adjunct whitelist, a frozen-frame
       membership set, a sibling constants module, or an external import
       therefore fails the guard even if every 4b/4c assertion would
       otherwise pass. Comments/doc WHY notes that avoid embedding these
       string constants remain legal (AST scope). Checklist claims of a
       source-level guard on 4b are satisfied **only** by this contract
       invocation (and the proof-12 pool guard below), not by prose alone.
5. **Discrimination — will branch non-hit** (physical action / no interior
   ownership, **and** physical-refusal / non-person will-stem carve-out):
   - Caption: `"She reaches for the gate."`
   - Assert: **zero** hits. A detector that flags any person-subject verb fails.
   - **Physical-action / non-person-subject will-stem zeros** (mandatory;
     the carve-out at the will-branch description is otherwise unproved —
     a stem matcher on `refuse` / `want` flags these and still passes every
     other will proof):
     - `"The gate refuses to open."` → **zero** hits (non-person subject;
       physical refusal, not interior will).
     - `"The poster wants for nothing."` → **zero** hits (non-person subject;
       non-interior `wants`).
     - `"She refuses the gate with both hands."` → **zero** hits when the
       implementation's will branch is locked to **interior** will /
       intent complements (infinitival / clausal), **not** a bare stem hit
       on any `refuse` token next to a person subject. If the detector's
       locked positive surface is `refuses to …` / `wants to …` only, this
       physical-transfer reading stays silent; a bare `\brefuse` stem fire
       fails this zero-hit.
     - **Trivial cheating implementation that must fail**:
       `if re.search(r"\b(want|refuse)s?\b", caption, re.I): flag` with no
       person-subject class **and** no interior-complement requirement —
       fires on `"The gate refuses to open."` / `"The poster wants for
       nothing."` and fails.
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
11. **Discrimination — mixed caption: hedged material + unhedged ownership**
    (kills whole-caption, per-sentence, coordinating-conjunction-clause,
    **and** intra-clause hedge suppression):
    - **11a. Cross-sentence** (kills whole-caption hedge short-circuit):
      Caption: `"He seems angry near the window. She is anxious by the doorway."`
      Assert: ≥1 hit covering the **unhedged** second clause
      (`She is anxious…`); the hedged first clause must not be the sole
      reason for silence.
      **Trivial cheating implementation that must fail**:
      `if any(h in caption.lower() for h in ("seems","looks","appears","as if")): return []`
      (caption-wide hedge short-circuit). This caption contains `seems` and
      still must hit on the unhedged clause — the cheat returns `[]` and fails.
    - **11b. Co-sentential / same-sentence across a coordinating ` and `**
      (kills per-sentence hedge blocklists that 11a does not catch; does
      **not** alone kill a splitter that also splits on bare `" and "` —
      that successor is 11c):
      Caption: `"He seems angry near the window and she is anxious by the doorway."`
      (one sentence under a `[.?!]`-only splitter; hedge token and unmarked
      ownership are co-sentential — no `.` / `?` / `!` between them).
      Assert: ≥1 hit covering the **unhedged** ownership span
      (`she is anxious…`).
      **Trivial cheating implementation that must fail**:
      ```
      for sent in sentences(caption):  # split only on [.?!]
          if any(tok in sent for tok in ("seems","looks","appears","as if")):
              continue  # per-sentence hedge suppression
          …detect ownership in sent…
      ```
      11a's two-sentence fixture still hits on the second sentence under
      this cheat, so 11a alone is green while genuine unmarked ownership
      co-sentential with a hedge is silenced. 11b turns **that** cheat red.
      **Does not claim** to kill a splitter that also severs on `" and "`
      (or any finer clause cut) — under that successor the unhedged second
      conjunct is its own segment and the ≥1-hit assert still passes while
      intra-clause co-occurrence is silenced. **11c** closes that class.
    - **11c. Intra-clause hedge co-occurrence** (kills per-clause / any
      segment-level hedge blocklist that 11a–11b leave open):
      Captions (assert ≥1 hit each on the **unmarked ownership span**; the
      hedge token sits in the **same clause segment** as the ownership under
      any reasonable splitter — including `[.?!]` + `" and "` — so no
      segment-level continue can reach a clean unhedged clause):
      - `"She is anxious in a scene that looks staged."`
        → ≥1 hit covering `"she is anxious"` (hedge `looks` is in a
        relative clause / adjunct of the same sentence; ownership is
        unmarked).
      - `"He is angry beside a poster that appears torn."`
        → ≥1 hit covering `"he is angry"` (hedge `appears` co-occurs
        intra-clausally with unmarked ownership).
      **Trivial cheating implementations that must fail**:
      ```
      for sent in re.split(r"[.?!]| and ", caption):
          if any(tok in sent for tok in ("seems","looks","appears","as if")):
              continue  # per-clause / and-split hedge suppression
          …detect ownership in sent…
      ```
      and any finer per-segment analogue. 11b's `" and "`-joined fixture
      still hits on the second conjunct under this cheat; 11c's fixtures
      have no clean unhedged segment and go red. Legitimate shapes that
      must still pass: a **separate** clause whose subject+predicate is
      fully under an ATTRIB-01 hedge (`"He seems angry near the window."`
      alone → 0 hits) remains zero-hit; only **unmarked** ownership that
      merely co-occurs with a hedge token elsewhere in the same clause
      must fire.
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
        in this plan or any other plan document).
    - **Pool quality bar (locked; members are not published — properties
      are)** — an implementer may **not** invent a trivial pool that
      overlaps frozen scaffolds and call the guard satisfied. The pool
      must satisfy **all** of:
      1. **Minimum size**: ≥3 distinct locative / prepositional adjuncts
         for the copula branch **and** ≥3 distinct infinitival complements
         for the will branch (≥6 strings total);
      2. **Named grammatical category**: copula-branch members are
         locative / prepositional adjuncts; will-branch members are
         infinitival complements — each syntactically parallel to the
         scaffolds in proofs 1–11 but using **novel surface strings**;
      3. **Provably disjoint from every frozen table and every published
         fixture**: pairwise empty intersection (case-insensitive) with
         every Slice 1 frozen table member, every adjunct / complement
         string appearing in proofs 1–11 fixture text, and every held-out
         string published under items 4b / 4c; **no** token sequence from
         the pool may appear in any other Slice 1 proof caption;
      4. **Authoring separation**: pool members are authored in the test
         module by a writer who has **not** read the implementation's
         adjunct / scaffold tables beyond the frozen grammar-member
         tables named in this plan (pronouns, nouns, affect adjs, will
         stems). Review checks the disjointness asserts; it does not
         require the plan to publish members.
      Concrete members **must not appear in any plan document** (this one
      included) — publishing them would let an implementer enumerate
      paraphrases into a lookup table and pass the generalisation proof
      without composing grammar.
    - **Unpredictability / no dual-site literal (locked)**: no caption
      literal **and no adjunct / complement literal from the held-out
      pool** may appear in both any owned implementation module in
      Source-guard contract scope and the test module. Grammar-member
      tables (pronouns, nouns, affect adjs, will stems) are the only
      shared closed sets. The concrete pool members exist **only** in the
      test module; this plan deliberately does not list them.
    - Minimum product size: ≥6 generated captions covering both copula and
      will branches and both pronoun and common-noun subjects.
    - Assert each generated caption: ≥1 hit (matched surface text,
      lower-cased, per hit-list semantics above).
    - **Source-level guard (mandatory; makes the pool held-out)**: per
      **## Source-guard contract** — AST string constants over the owned
      implementation closed path set, article-stripped core match, import
      RED, and semantic arm (floor tables only — no pool member appended —
      each generated caption still hits). Enumerating the test-module
      pool into an implementation lookup table, a sibling constants
      module, or an external import therefore fails the guard even if
      every generated caption would otherwise hit. **Companion guards**
      (same contract; same test-module helper): the 4b/4c frame +
      held-out leading-adjunct guard under item 4c, and the Slice-2
      held-out event-noun / by-agent / non-agentive-by / gap-pool guards
      — each invokes **## Source-guard contract**; none is prose-only.
    - **Trivial cheating implementation that must fail**:
      `return [caption.lower()] if caption in _PROOF_CAPTIONS else []`
      or any `frozenset` / dict membership over the finite closed list of
      proof 1–11 captions (scaffold variance enlarges that set; held-out
      adjuncts sit **outside** it). Also fails any implementation that
      embeds those held-out adjunct strings as caption literals (source
      guard goes red). Also fails a pool that reuses proof 1–11 adjunct
      strings (quality bar §3 disjointness assert goes red).
13. **Command**:
    `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -k inner_state -q`

### Slice 2: Agentless-passive / mutual-event / actorless-event-noun detector (report-only)

**Goal**: Pure-grammar detector for agentless passives, mutual-event nouns,
and actorless event nouns (ATTRIB-08 **three** disjuncts) in violence /
oppression prose; no model, no context, no aggregate, no gate.

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
      "was shot",    # violence-sense shot passive; NOT bare shot
      "were shot",
  )  # EVERY form must have a positive + same-clause by-agent negative
  # Floor exemplars for ATTRIB-08 disjuncts 2 mutual-event noun and
  # 3 event noun that carries no actor. Name is historical; do NOT read
  # membership as "mutual-event / symmetry only" — `"incident"` is the row's
  # actorless-event-noun exemplar. These two tokens are the closed floor.
  _MUTUAL_EVENT_NOUNS = (
      "clash",      # mutual-event noun exemplar — disjunct 2
      "incident",   # actorless event-noun exemplar — disjunct 3
  )
  # Gap-exemption proof floor (lexicon: "state the gap rather than invent an
  # agent"). Structural gap patterns below cover exactly the published closed
  # gap lexicon — not an open class (see gap-language exemption).
  _GAP_AGENT_PHRASES = (
      "agent not named in the record",
      "agent not in the record",
      "agent unknown",
  )
  # Violence / oppression context gate (TABLE MEMBERSHIP IS THE CONTRACT).
  # Scope: CAPTION-level (see violence-context scope lock below).
  # Membership via `_contains` (word-boundary), not raw `in`.
  # Bare `"shot"` INTENTIONALLY ABSENT (photographic dominant sense).
  _VIOLENCE_CONTEXT_TERMS = (
      "killed",
      "beaten",
      "enslaved",
      "arrested",
      "violence",
      "oppression",
  )
  # By-agent proof floor (exactly three). Held-out 4d covers exactly three
  # additional published PPs — not an open agent class (see proof 4d).
  _BY_AGENT_PPS = (
      "by the Ohio National Guard",
      "by soldiers",
      "by a campus patrol officer",
  )
  ```

  - **agentless passives** on the frozen violence/oppression forms **without**
    a same-clause `by`-agent PP and **without** a same-clause gap-statement
    (floor `_GAP_AGENT_PHRASES` or structural gap pattern);
  - **mutual-event nouns and actorless event nouns** from the floor +
    published held-out noun pools when the **caption** also contains ≥1
    member of `_VIOLENCE_CONTEXT_TERMS` via `_contains` (word-boundary;
    not raw `in`). Gate is independent of passive presence — ATTRIB-08
    (`canon/lexicons/depiction.md#attrib-08`) lists **three** Trigger-column
    disjuncts. Quote the lexicon row, not its `Src` distillation.

  **Violence-context scope (locked once; EXIT chosen = CAPTION):** the
  violence gate is **caption-level** — fire the mutual-event / actorless-
  event-noun branch when the **caption** (not merely the same clause as the
  event nominal) contains ≥1 `_VIOLENCE_CONTEXT_TERMS` member via
  `_contains`. Multi-clause captions where the violence term and the event
  nominal sit in different clauses still gate on. Straddling fixture
  (mandatory; makes the choice observable):
  - `"Four students were killed; an incident followed."` → `"incident"` ∈
    hits (and `"were killed"` ∈ hits). A clause-scoped gate that requires
    the violence term inside the event-nominal's clause returns no
    `"incident"` hit and fails.
  Do **not** restate the gate as "clause also carries" anywhere else in
  this plan — caption scope is the single contract.
- Surface as report-only hit list on `CaptionScores`
  (`agentless_passive_hits: list[str]`, parallel to `meta_framing_hits`).
  Same surface lock as Slice 1: report-facing field is the `CaptionScores`
  list, not an open "or sibling pure function" fork. No `gated_score` change.
- **Hit-list element semantics (locked; Slice 2)**: each element is the
  **matched surface text**, **lower-cased**, in **source order** of first
  match. Passive hits emit the matched form; mutual-event / actorless-event
  hits emit the matched noun (floor + published pool members under 2b/2c).
  Marker tokens are **not** legal elements.
- **Scope (ATTRIB-08-aligned grammar + gap exemption, locked)**: grammar +
  closed violence/oppression lexicon; no voice tagger. Canon ATTRIB-08
  (`canon/lexicons/depiction.md#attrib-08`) warrants the exemption as:
  *"when the record does not support naming who acted, state the gap rather
  than invent an agent"*. Distilled evidence is evidence only, never lexicon
  vocabulary.
  - A passive **without** a same-clause `by`-agent and **without** a
    same-clause gap-statement is a hit.
  - A same-clause gap-statement **does** exempt the passive — compliant
    ATTRIB-08 prose. Do **not** flag captions that correctly state the gap.
  - **Gap-language exemption — structural test (EXIT B: finite published
    lexicon; not an open class)**: a passive is gap-exempt when the **same
    clause segment** contains an **explicit gap-statement** about the agent.
    Covers **exactly** the patterns and closed sets below; does not
    generalise beyond them; extending requires amending this plan.
    1. **Floor fixtures** — every `_GAP_AGENT_PHRASES` member must zero-hit
       (proof 7).
    2. **Structural gap-statement patterns** (surface; no parser) — closed
       inventories:
       - parenthetical or same-clause phrase headed by `agent` + a
         gap-predicate from the closed set
         `{unknown, unnamed, not named, not in the record,
         not named in the record, unspecified, not identified}` with
         optional record/source complement; **or**
       - a **record-gap clause** in the same segment: subject head from
         closed set `{record, records, source, sources, archive}` +
         gap-predicate from closed set
         `{does not name, do not name, does not identify, do not identify,
         disagree on, omits, omit, unknown}` + optional
         `who` / `the agent` / `responsibility` complement
         (word-boundary, case-insensitive).
    3. **Published held-out gap pool** (test-module constants OK; **published
       here for reproducibility** — EXIT B, not invent-your-own):
       `("perpetrator unspecified", "responsible party not identified")`.
       Each in `"Four students were killed ({gap}) on campus."` → **zero
       agentless-passive hits** (scoped; the combined hit list must also
       contain **no** actorless-event-noun element — see evidentiary-gap
       exclusion below). Source-guard: these two full strings must not appear
       as implementation membership-table constants (structural recovery via
       the closed predicate set above). Semantic arm: with
       `_GAP_AGENT_PHRASES` emptied to `()`, each still zero-hits.
    4. **Named RED**: floor-membership-only exemption → fails held-out gap
       pool. Appending pool strings to the floor → fails source guard.

  - **Evidentiary-gap exclusion class for event-nominal detection (R-03;
    computed property — do NOT close the noun-head class)**: disjunct-3
    event-nominal matching **must not** flag gap-marking language the canon
    rewards. Property (not a gap-noun membership list):

    > A candidate event-nominal span is **suppressed** when its token span
    > **overlaps** any structural gap-statement span recovered in the same
    > clause segment (the patterns in (2) above, including floor
    > `_GAP_AGENT_PHRASES` matches).

    Consequences for published fixtures:
    - `"Four students were killed (agent not in the record) on campus."` —
      the PP `in the record` matches the event-locative slot shape
      (`in` + `the` + singular noun) but **overlaps** the gap-statement
      `agent not in the record` → **suppressed**. Assert: **zero entries**
      in `agentless_passive_hits` (scoped once for all proof-7 / gap
      fixtures: no passive element **and** no event-nominal element).
    - Same for every proof-7 floor gap and the published held-out gap pool.
    - Named RED: event-nominal slot matcher with only proper/temporal
      exclusions and **no** gap-span overlap exclusion → false-fires on
      `record` / `records` / `source` / `sources` / `archive` under
      `in the ___` and fails proof 7's zero-hit assert.
    - Do **not** fix this by adding `{record, records, …}` to a closed
      exclusion-noun table — that re-freezes heads. The computed overlap
      property is the contract.

  **Hit-scope wording (locked once):** every "zero hits" / "0 hits" assert
  under Slice 2 gap and by-agent exemptions means **zero entries in
  `agentless_passive_hits`** (the combined list). When a fixture can also
  trigger disjunct 2/3, the proof states which elements must be absent.
  Prefer the scoped phrase **"zero agentless-passive hits"** in new text.
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
    ` which `, ` who `, ` while `, ` when `, ` because `, ` although `
    (word-boundary match, case-insensitive), **plus** clausal ` that ` /
    ` as ` **only** when the **finite-clause surface test** below fires.
    **Bare `\bthat\b` / `\bas\b` are NOT unconditional splitters** —
    determiner `that` (`that day`, `that officer`) and prepositional `as`
    (`as teenagers`, `as witnesses`) must remain inside the current clause
    segment so a same-clause `by`-agent PP is not severed (proof 4e turns
    the unconditional-splitter cheat red).
  - **Finite-clause surface test for clausal `that` / `as` (locked; no
    POS tagger, no parser):** after a candidate complementiser token
    `that` / `as`, scan the next **N = 6** tokens (whitespace /
    punctuation tokenisation). The complementiser opens a **new clause
    segment** only when that window contains a **finite-verb signal** from
    the closed set:
    - finite auxiliaries / modals / copula forms:
      `is`, `are`, `was`, `were`, `has`, `have`, `had`, `do`, `does`,
      `did`, `will`, `would`, `can`, `could`, `may`, `might`, `shall`,
      `should`, `must`;
    - matching is word-boundary, case-insensitive.
    Examples that **do** split (finite signal in window — proof 6a
    still-hits): `"…killed on campus that the parade was led by…"`
    (`was` in window); `"…killed as the parade was led by…"`.
    Examples that **do not** split (no finite signal in window — proof 4e
    zeros): `"…killed that day by soldiers."` (`day` is a noun; no finite
    auxiliary before `by`); `"…killed as teenagers by…"`.
    **Named REDs**: bare unconditional `\bthat\b` / `\bas\b` split →
    fails 4e; "finite clause" decided by an external POS tagger /
    dependency parser → **out of scope** (Slice 2 forbids a voice tagger;
    the closed auxiliary window **is** the contract); always-split on
    capitalised next token alone → insufficient and not the test.
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
  **Determiner-`that` / prepositional-`as` resolution**: freezing bare
  `\bthat\b` / `\bas\b` as unconditional splitters false-flags
  ATTRIB-08-compliant same-clause named-agent passives such as
  `"Four students were killed that day by soldiers."` (determiner `that`
  before the by-PP) and `"Four students were killed as teenagers by the
  Ohio National Guard."` (prepositional `as` before the by-PP) — the
  splitter severs the agent PP into a later segment and the passive is
  wrongly reported as agentless. Proof 4e locks the zero-hit; proof 6a's
  clausal ` that ` / ` as ` still-hit rows keep genuine subordinator
  splits.
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
  - Mutual-event nouns fire **only** when the **caption** contains ≥1
    `_VIOLENCE_CONTEXT_TERMS` member; a benign `"clash of colors"` / `"incident of paint"`
    must not hit. The gate does **not** require an `_AGENTLESS_PASSIVE_FORMS`
    member (active-voice violence + mutual-event still hits the noun).

Proof (TEST-15, `canon/lexicons/engineering.md#test-15`):

1. **Red-first — agentless passives, parametrized over EVERY
   `_AGENTLESS_PASSIVE_FORMS` member**:
   - Template: `"Four students {passive_form} on campus."` for each form in
     `{was killed, were killed, were beaten, was enslaved, were arrested,
     was shot, were shot}`.
   - Assert each: ≥1 agentless-passive hit covering that form. Empty list fails.
   - **Trivial cheating implementation that must fail**: hardcode only
     `"were killed"` (or only the two phrases used by a multi-signal fixture).
     Every other form must still hit — including `"was shot"` / `"were shot"`
     (violence-sense shot; an unconditional exclude-`shot` cheat fails here
     while the photographic `"wide shot"` zero-hit in 8b still passes).
2. **Red-first — mutual-event / actorless-event floor exemplars, parametrized
   over EVERY `_MUTUAL_EVENT_NOUNS` member** (violence context via
   `_VIOLENCE_CONTEXT_TERMS`):
   - Captions: `"Four students were killed during a clash on campus."` and
     `"Four students were killed during an incident on campus."`
   - Assert each: hits include an agentless-passive element **and** a
     mutual-event / actorless-event element with exact lower-cased
     membership `"were killed"` ∈ hits and (`"clash"` ∈ hits or
     `"incident"` ∈ hits). A detector that only knows `clash` fails on
     `incident`.
2b. **Actorless-event-noun beyond floor (ATTRIB-08 disjunct 3)**
   (`test_agentless_passive_held_out_actorless_event_noun` or equivalent;
   kills a frozen two-token vocabulary for disjunct 3). Canon
   ATTRIB-08 (`canon/lexicons/depiction.md#attrib-08`) Trigger column
   names "an agentless passive, a mutual-event noun, **or** an event noun
   that carries no actor"; the parenthetical
   `("a clash", "an incident", "were killed")` is exemplification.
   `_MUTUAL_EVENT_NOUNS = ("clash", "incident")` is the closed floor.

   - **Event-nominal slots (EXIT B — finite published inventory)**:
     disjunct 3 fires on a singular common noun head in one of these
     **exactly-N** published slots when the **caption** carries ≥1
     `_VIOLENCE_CONTEXT_TERMS` member via `_contains`. Covers exactly
     these forms; does not generalise beyond them; extending requires
     amending this plan:
     1. object of event-locative preposition from closed set
        `{during, after, in, amid, following}` + determiner
        `{a, an, the}` + singular common noun head;
     2. subject of non-agentive event verb from closed set
        `{left, occurred, erupted, followed, began, ended}` with
        determiner + singular common noun head
        (template: `"An {n} of violence left four students dead on
        campus."`).
     Not "any determiner + singular noun anywhere".

   - **Noun heads**: floor `"incident"` (disjunct 3) is mandatory. Beyond
     the floor, proof uses the **published pool** below (reproducible;
     not invent-your-own). The head class is **not** closed by adding
     gap-nouns to an exclusion table — evidentiary-gap exclusion is the
     computed overlap property under Scope above.

   - **Closed exclusion classes (EXIT B — not "open-class
     disambiguators")**: the slot rule MUST NOT fire on:
     1. **Proper / organization NP**: internal capitalisation after the
        determiner, or multi-token proper name.
        `"Members of the Ohio National Guard killed four students on
        campus."` → **zero** actorless-event-noun hits (and zero passive
        hits).
     2. **Temporal NP**: head ∈ closed set
        `{day, night, morning, evening, noon, afternoon, week, month,
        year, hour, moment, time, season}` (word-boundary).
        `"Four students were killed that day by soldiers."` → `day`
        contributes **no** event-noun hit.
     3. **Slot discipline**: agent / patient participant NPs outside the
        two published slots are out by construction.
     4. **Evidentiary-gap overlap** (Scope): candidate spans overlapping
        a gap-statement are suppressed.
     **Named RED**: `determiner + singular noun + violence → flag` with
     no slot restriction / no proper/temporal/gap exclusion → fails the
     negatives above, proofs 3 / 4e, and/or proof 7.

   - **Published positive pool** (EXIT B; published here for
     reproducibility — M-17). `_HELD_OUT_ACTORLESS_EVENT_NOUNS` in the
     **test module** (not implementation), exact members:
     `("skirmish", "outbreak", "fracas")`.
     Disjoint from `_MUTUAL_EVENT_NOUNS` and every frozen Slice 2 table.
     For each pool noun `n`:
     - `"Four students were killed during a {n} on campus."` → `n` ∈ hits;
     - and at least one pool noun under
       `"An {n} of violence left four students dead on campus."`
       (adjust `A`/`An`).
     Load-bearing assert is the **actorless-event-noun** element.
     **Hold-out axis** (not invent-your-own nouns): the subject-slot
     template above must hit without template-specific hardcoding of only
     the `during a {n}` shape — a detector that only regex-matches
     `during (?:a|an|the) (?:skirmish|outbreak|fracas|incident|clash)`
     and ignores the subject-slot template fails the subject-slot row.

   - **Source-level guard**: per **## Source-guard contract** over every
     pool member (folded-AST + runtime positive-set arm + semantic arm:
     floor only, no pool member appended → each pool caption still hits).

   - **Named RED**: membership over `_MUTUAL_EVENT_NOUNS` alone (or floor
     + append of pool members into implementation constants).

   - **Legitimate shapes**: floor `"clash"` / `"incident"` remain
     mandatory under proof 2; benign non-violence uses stay zero-hit
     (proof 8); proper/temporal/gap negatives stay zero-hit.

2c. **Mutual-event-noun beyond floor (ATTRIB-08 disjunct 2)**
   (`test_agentless_passive_held_out_mutual_event_noun` or equivalent).
   Trigger column names "a mutual-event noun" as its own disjunct; floor
   token is `"clash"`.
   - **Slots + violence gate**: same finite published slots and
     caption-level violence gate as 2b, restricted to nouns that denote a
     **reciprocal / symmetric multi-party event**.
   - **Exclusions**: same closed proper/temporal/slot/gap exclusions as 2b.
   - **Published positive pool** (EXIT B; exact members):
     `_HELD_OUT_MUTUAL_EVENT_NOUNS = ("melee", "brawl")` in the test
     module only; disjoint from floor and from the 2b pool.
     Template: `"Four students were killed during a {n} on campus."` →
     `n` ∈ hits.
   - **Source-level guard**: per **## Source-guard contract**.
   - **Named RED**: single-token `"clash"` floor (or floor + append).
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
     (`canon/lexicons/depiction.md#attrib-08`).
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
   - Note: bare `"shot"` is **not** in `_VIOLENCE_CONTEXT_TERMS`
     (photographic false-positive class; see table freeze above). Do **not**
     add bare `shot` as a violence-context positive. Violence-sense shot is
     proved via the passive forms `"was shot"` / `"were shot"` in proof 1
     (and photographic zero-hit in 8b) — absence from the context table
     alone is not the disambiguation.
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
     (7 forms × 3 agents = 21 captions).
   - Assert each: **zero** agentless-passive hits (the clause names the actor
     via `by`). Mutual-event nouns are absent so the whole hit list is empty.
   - Red-first edit: strip the agent PP → the agentless-passive element must
     appear. A constant-empty implementation fails proof 1; a
     fire-on-any-passive implementation fails this case; a detector that
     special-cases only `"by the Ohio National Guard"` fails on
     `"by soldiers"` and `"by a campus patrol officer"`.
4d. **Held-out by-agent phrases — non-table agents MUST exempt (EXIT B:
   exactly three published PPs)**
   (`test_agentless_passive_held_out_by_agent_exempt` or equivalent; kills
   an exact agent-phrase whitelist over `_BY_AGENT_PPS` alone). Every
   exemption proof in 4 / 5 / 6a draws its agent from the three frozen
   `_BY_AGENT_PPS` strings, so floor-membership-only exemption greening
   those proofs does not cover the three held-outs below.
   - **Held-out agent phrases** (covers **exactly** these three; does not
     generalise beyond them; extending requires amending this plan; MUST
     NOT be added to `_BY_AGENT_PPS`):
     - `"by the mayor"`
     - `"by a journalist"`
     - `"by campus security staff"`
   - Templates (adjacent + one non-adjacent):
     - `"Four students were killed {held_out_pp} on campus."` for each
       held-out PP → **zero agentless-passive hits**.
     - `"Four students were killed on campus yesterday {held_out_pp}
       during roll call."` for at least one held-out PP → **zero
       agentless-passive hits**.
   - **Source-level guard**: per **## Source-guard contract** over the
     three PP literals (article-stripped forms e.g. `"by the mayor"` /
     `"by mayor"` — **not** bare `"mayor"` alone; semantic arm: with
     `_BY_AGENT_PPS` emptied to `()`, each still zero-hits via same-clause
     `by` + agentive-NP recovery for these published forms; see 4f).
   - **Named RED**: `if any(a in clause for a in _BY_AGENT_PPS): exempt
     else: hit` — fails the three held-outs.
   - **Interaction with proof 6a**: still-hit fixtures use **only**
     `_BY_AGENT_PPS` members (locality lock).
4e. **Determiner-`that` / prepositional-`as` before a same-clause by-PP MUST
   still exempt**
   (`test_agentless_passive_that_as_not_unconditional_splitters` or
   equivalent; kills bare `\bthat\b` / `\bas\b` as unconditional clause
   splitters — DPR12-H-04). Proof 6a's still-hit rows use clausal
   ` that ` / ` as ` and never place determiner `that` or prepositional
   `as` between the passive and a same-clause by-PP, so the suite stays
   green while compliant prose is false-flagged.
   - Captions (assert **zero** hits each):
     - `"Four students were killed that day by soldiers."`
       (determiner `that` in `that day` before the by-PP; agent =
       `_BY_AGENT_PPS` member `"by soldiers"`).
     - `"Four students were killed as teenagers by the Ohio National Guard."`
       (prepositional `as` in `as teenagers` before the by-PP; agent =
       `_BY_AGENT_PPS` member).
     - `"Four students were killed by that campus patrol officer on campus."`
       (determiner `that` **inside** the agent NP; if bare `\bthat\b`
       splits, the agent is severed from the passive segment).
   - Assert each: **zero** agentless-passive hits (same-clause named agent).
   - **Finite-clause surface test** (same locked algorithm as under
     Scope — closed finite auxiliary / modal / copula set in the next
     N=6 tokens; no POS tagger). Determiner `that day` and prepositional
     `as teenagers` have **no** finite signal in-window → no split.
     Clausal rows in proof 6a have `was` in-window → split → still-hit.
   - **Trivial cheating implementation that must fail**:
     split on bare `\bthat\b` / `\bas\b` unconditionally, then exempt only
     when a `by`-PP shares the passive's segment — each caption above
     severs or mis-segments the agent and wrongly hits. Clausal
     subordinators in proof 6a (`…killed on campus that the parade was
     led by soldiers to mark."`, `…killed as the parade was led by…`)
     remain still-hits because the finite-clause surface test fires.
4f. **Instrumental / temporal / manner `by` is NOT an agent**
   (`test_agentless_passive_non_agentive_by_still_hits` or equivalent;
   kills the generic `by` + token exemption that 4d leaves open, and
   closes the parent class DPR12-H-05 / successor of exact
   `_BY_AGENT_PPS` whitelists). Proof 4d forces the exemption path past
   the three frozen agent phrases, but every held-out agent there is an
   **agentive NP**, and still-hit fixtures pin agents back onto
   `_BY_AGENT_PPS` members — so
   `re.search(r"\bby\s+\w+", clause)` (or any "same-clause `by` + token
   → exempt" rule with no agent-NP test) passes 4d while silencing
   instrument / time / manner `by`-PPs.
   - **Agentivity class property (locked; the three fixtures below are
     not the contract)**: a same-clause `by`-PP **exempts** only when its
     complement is an **agentive NP** under a surface animacy /
     organisation-head test (no parser):
     - **Agentive** (exempts the passive): `by` + (proper NP with
       internal capitalisation | determiner `{the, a, an}` + common NP |
       bare plural / bare role common noun) whose **head** denotes a
       person, role, or organisation (accepts animate / institutional
       agency — e.g. `soldiers`, `mayor`, `officer`, `staff`, `Guard`).
     - **Non-agentive** (does **not** exempt; passive still hits): `by` +
       complement whose head **fails** the animacy / organisation test —
       typically a bare singular temporal, manner, or abstract
       instrumental head (no agentive determiner+person/org pattern).
       Closed **positive** exclusion cues for the non-agentive side
       (legal closed class; not an open event vocabulary): temporal heads
       from the 2b temporal set, plus manner / abstract heads from closed
       set `{mistake, chance, accident, force, design, default, degrees,
       rights}` and multi-word fixed forms whose head is non-agentive
       (`all accounts` under `by all accounts`). Unlisted non-agentive
       `by`-PPs with non-animate / non-org heads must still hit — the
       class property is the contract, not a three-string floor.
   - **Still-hit fixtures of the non-agentive class** (assert
     `"were killed"` ∈ hits for each; these three are **fixtures**, not
     an exhaustive non-agent table):
     - `"Four students were killed by noon on campus."`
       (temporal `by noon` — not an agent).
     - `"Four students were killed by mistake during the march."`
       (manner / error `by mistake` — not an agent).
     - `"Four students were killed by chance in the crossfire."`
       (manner / happenstance `by chance` — not an agent).
   - **Held-out non-agentive pool** (test-module only; ≥1 additional
     `by` + non-animate/non-org complement; members **not** published in
     this plan; disjoint from the three fixtures above and from every
     `_BY_AGENT_PPS` / 4d agent string): each
     `"Four students were killed {pp} on campus."` → `"were killed"` ∈
     hits. Closes the freeze-then-append cheat on the three fixtures.
   - Assert each fixture + pool member: ≥1 agentless-passive hit with
     `"were killed"` ∈ hits.
   - **Trivial cheating implementation that must fail**:
     `if re.search(r"\bby\s+\w+", clause, re.I): exempt` —
     each fixture has a same-clause `by` + token and still must hit;
     **and**
     `if any(p in clause for p in ("by noon", "by mistake", "by chance")):
     pass else: maybe_exempt` — a three-string non-agent blocklist fails
     the held-out non-agentive pool.
   - **Legitimate shapes that must still pass**: same-clause `by` +
     **agentive NP** (floor `_BY_AGENT_PPS` members **and** held-out
     agents from 4d) remains zero-hit. The cut is agentive vs
     non-agentive complement of `by`, not presence/absence of the token
     `by`.
   - **Source-level guard**: per **## Source-guard contract** over
     `"by noon"`, `"by mistake"`, `"by chance"`, **and** every held-out
     non-agentive pool member (semantic arm: no non-agent blocklist
     append required — agentivity test alone still hits each).
5. **Discrimination — non-adjacent same-clause by-agent MUST exempt,
   parametrized over EVERY `_AGENTLESS_PASSIVE_FORMS` member × EVERY
   `_BY_AGENT_PPS` member**
   (`test_agentless_passive_nonadjacent_by_agent_exempt` or equivalent;
   kills form-specific `"were killed by"`-substring-only cheats **and**
   single-agent-phrase cheats):
   - Template: `"Four students {passive_form} on campus yesterday {agent_pp}
     during roll call."` for each
     `passive_form ∈ _AGENTLESS_PASSIVE_FORMS` **and** each
     `agent_pp ∈ _BY_AGENT_PPS` (full product, 21 captions).
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
     | ` as ` (clausal: finite clause follows) | `"Four students were killed as the parade was led by the Ohio National Guard."` |
     | ` that ` (clausal: finite clause follows) | `"Four students were killed on campus that the parade was led by soldiers to mark."` |
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
   - **Clausal vs bare `that` / `as`**: the ` that ` / ` as ` rows above are
     **clausal** (finite clause follows). They do **not** license treating
     bare `\bthat\b` / `\bas\b` as unconditional splitters — proof 4e's
     determiner / prepositional zero-hits remain the lock on that cheat.
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
7. **Gap-language exemption (ATTRIB-08 compliant prose → zero combined
   hits), parametrized over EVERY `_GAP_AGENT_PHRASES` member + published
   held-out gap pool**
   (`test_agentless_passive_gap_language_exempt` or equivalent):
   - **Floor fixtures** for each
     `gap ∈ {agent not named in the record, agent not in the record,
     agent unknown}`:
     `"Four students were killed ({gap}) on campus."`
     Assert each: **zero entries in `agentless_passive_hits`** — no
     passive element **and** no event-nominal element (evidentiary-gap
     exclusion suppresses `in the record` as a false disjunct-3 hit).
     Canon ATTRIB-08 (`canon/lexicons/depiction.md#attrib-08`) warrants
     this as *"state the gap rather than invent an agent"*.
   - **Structural test**: see Scope (finite published gap lexicon +
     span-overlap exclusion for event-nominals).
   - **Published held-out gap pool**
     `("perpetrator unspecified", "responsible party not identified")`:
     each `"Four students were killed ({gap}) on campus."` → **zero
     entries in `agentless_passive_hits`**. Source-guard + semantic arm
     per Scope.
   - **Named REDs**: fire on every `were killed` regardless of gap;
     floor-membership-only exemption; event-nominal slot matcher without
     gap-span overlap exclusion (false-fires on `record`); append pool
     strings to floor.
   - Companion red-first: `"Four students were killed on campus."` still
     hits (proof 1).
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
     caption contains any `_VIOLENCE_CONTEXT_TERMS` member (caption-level
     gate; see Scope).
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
   - **Why no bare-`shot`/`snapshot` arm on the context table**: bare
     `"shot"` is **intentionally absent** from `_VIOLENCE_CONTEXT_TERMS`
     (photographic dominant sense; see table freeze). A `shot`⊂`snapshot`
     false-positive arm on the context gate is therefore **dead** — bare
     `"shot"` cannot fire as a context term. The word-boundary lock rests
     on the `killed`/`skilled` arm above (and the shared `_contains`
     dependency proof 8c). Do **not** reintroduce bare `"shot"` to the
     context table without a disambiguating rule.
   - **Photographic zero-hit (bare `shot` is not violence context)**:
     `"A clash of colors dominates this wide shot."`
     → assert **zero** hits. Confirms bare `"shot"` is not a violence-
     context term; does not substitute for the `skilled`/`killed` arm.
   - **Violence-sense `shot` POSITIVE (mandatory; kills unconditional
     exclude-`shot`)** — absence from the context table alone lets a cheat
     drop every `shot` token and still pass the photographic zero-hit:
     - `"Four students were shot on campus."` → `"were shot"` ∈ hits
       (passive form from `_AGENTLESS_PASSIVE_FORMS`; already in proof 1's
       product — keep as the permanent photographic/violence discrimination
       witness paired with the wide-shot zero-hit above).
     - `"The man was shot near the gate."` → `"was shot"` ∈ hits.
     - **Trivial cheating implementation that must fail**:
       `if "shot" in form: skip` (unconditional exclude). Wide-shot zero-hit
       still passes; violence-sense passives are silently missed and fail
       these positives / proof 1's `was shot` / `were shot` rows.
   - **Trivial cheating implementation that must fail** (word-boundary):
     `if any(t in caption.lower() for t in _VIOLENCE_CONTEXT_TERMS) and
          re.search(r"\b(clash|incident)\b", caption, re.I): flag`
     (raw substring membership). `"killed" in "skilled"` is True under raw
     `in`, so the cheat flags `"clash"` on the skilled-artist caption and
     fails. Using the shared `_contains` helper keeps that caption silent.
8c. **Shared `_contains` seam — violence-context gate verdict MUST DEPEND
   on `caption_metrics._contains` return value**
   (`test_violence_context_uses_shared_contains` or equivalent; locks
   **dependency**, not mere invocation — a discarded seam call plus a
   private duplicate boundary regex is the exact "behavioural equivalence
   is not seam ownership" cheat):
   - Caption under test (true violence-context + mutual-event; normally
     hits): `"Four students were killed during a clash on campus."`
   - **Dependency arm (load-bearing)**: monkeypatch
     `caption_metrics._contains` to a wrapper that **always returns
     `False`** (or returns `False` for every
     `_VIOLENCE_CONTEXT_TERMS` needle) while leaving other behaviour intact.
     Assert: **zero** mutual-event hits on that caption under the patch
     (and, if the passive form is detected independently, the mutual-event
     element `"clash"` / `"incident"` is **absent** from hits). Restore the
     real `_contains` and assert the mutual-event element **is** present.
     The verdict must **flip** with the return value — a spy that only
     records calls while the implementation ignores the return and uses a
     private duplicate regex still reports the mutual-event hit under the
     always-False patch and fails.
   - **Call arm (secondary)**: with the real `_contains` (or a
     call-recording wrapper around it), assert `_contains` is actually
     called at least once with a `needle` equal to a
     `_VIOLENCE_CONTEXT_TERMS` member (typically `"killed"`). Call-only is
     **not** sufficient without the dependency arm.
   - **Do not** allow "or an equivalent boundary match" as a substitute for
     routing membership through `_contains`. Behavioural equivalence is not
     seam ownership.
9. **Command**:
   `uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -k agentless_passive -q`

### Slice 3: Verified signal-density measurement + Williams/C5 resolution

**Goal**: Land **verified facts per 100 words** as a report measurement (not a
gate; ranking *sort* unowned — see **Objective**), with the EVAL-11 / card
guard that unverifiable specificity scores zero; write the Williams/C5
resolution into the module docstring.

**Canon**:

- EVAL-11 (`canon/lexicons/ml-systems.md#eval-11`
  → `canon/distilled/ml-systems/ai-engineering.md`, mechanism
  **functional-and-rubric scoring**: open-ended generation has no exact-match
  oracle; the scorer must measure task success, not wording flash).
- **Density numerator membership is operational, not a PROV-01 citation.**
  PROV-01 (`canon/lexicons/ml-systems.md#prov-01`, definition-anchor form;
  → `distilled/ml-systems/model-cards.md`) is the lexicon lineage rule:
  Failure *"A description or identity is emitted without model and input
  lineage"*; Fix *"**Every output walks back to its evidence**: the model
  revision, preprocessing, thresholds, and source observations are part of
  the result, or the output cannot be reproduced after the model changes"*
  (Verification: *"Can this output be reproduced after the model
  changes?"*). It does **not** govern gold-label membership for a density
  numerator. Do **not** cite PROV-01 as the warrant for true-polarity
  `ReferenceFact` filtering, and do **not** substitute the assessment §10f
  gloss or any `canon/public/reasoning/` paraphrase for the lexicon row.
  The verified set is defined operationally: true-polarity `ReferenceFact`
  rows whose `match_targets()` hit via `_contains`.
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
scorer for density as a measurement companion: checkable substance per listen cost, not
word count or rare nouns. Ranking *sort* remains unowned (see **Objective**).

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
        `(fact.text, fact.kind, frozenset(p.strip().lower() for p in fact.phrases if p.strip()))`.
        **Phrase multiset is order-insensitive and case-folded** — do **not**
        use raw `tuple(fact.phrases)` (order-sensitive and a different
        identity from `match_targets()`, which filters blanks but preserves
        author order). Two faithful implementations that differ only in
        phrase ordering or surface case must produce the same density
        number; proof 5e locks this.
     3. **Then count** how many of those distinct rows have a
        `match_targets()` hit via **`caption_metrics._contains`**
        (`caption_metrics.py:59-74`). Membership **must** route through
        `_contains` — a raw `needle in caption` substring test is forbidden
        (proof 5f forces dependency on `_contains` return value, not mere
        invocation).
     **Do not include `polarity` in the density identity key.** After the TRUE
     filter it is constant, so no fixture over `score_signal_density` alone
     can ever discriminate three-field from four-field identity (a prior
     four-field claim was structurally vacuous). Polarity observability for
     dedupe lives in `score_hallucination` at
     `caption_metrics.py:409-422` (`seen` keyed on
     `(text, kind, polarity, phrases)` and gates both trap and covered
     branches) — that function's contract is unchanged and is **not**
     re-proved as a density claim. Proofs 5a–5c force the three-field key
     shape; 5e forces order-insensitive phrases; 5f forces `_contains`
     dependency.
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
     (2) **then** dedupe survivors on `(text, kind, frozenset(normalised
     phrases))`, (3) **then** count matches via `_contains`. Proofs 5a–5c
     are all TRUE+TRUE (or
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

   - **5e. Phrase-order / normalisation identity — order-insensitive
     frozenset** (`test_signal_density_phrase_order_dedupe` or equivalent;
     kills `tuple(fact.phrases)` order-sensitive identity that lets two
     faithful implementations disagree on production density while both
     pass 5a–5c):
     - Facts: **two** true-polarity rows with the **same** text/kind and the
       **same phrase multiset in different order**:
       `ReferenceFact(text="vehicle", kind=OBJECT, polarity=TRUE,
       phrases=["bicycle", "bike"])` **and**
       `ReferenceFact(text="vehicle", kind=OBJECT, polarity=TRUE,
       phrases=["bike", "bicycle"])`.
     - Caption: `"A bicycle leans on a wall."` (both `match_targets()` hit
       via `bicycle`).
     - Assert: `verified_count == 1` (not 2). Identity must treat the phrase
       multiset as order-insensitive (`frozenset` of stripped lower-cased
       phrases, or an equivalent sorted normalised tuple) so the second row
       collapses as a duplicate of the first.
     - **Trivial cheating implementation that must fail**:
       `seen.add((fact.text, fact.kind, tuple(fact.phrases)))` — the two
       rows have different tuples and both count → `verified_count == 2`.
     - Companion case (case-fold): same text/kind with
       `phrases=["Bicycle"]` and `phrases=["bicycle"]` → still
       `verified_count == 1` under the normalised frozenset identity.

   - **5f. Density numerator MUST DEPEND on `caption_metrics._contains`
     return value** (`test_signal_density_numerator_uses_contains` or
     equivalent; same defect class as Slice 2 proof 8c — a raw `in`
     substring numerator passes every density arithmetic assert while
     disagreeing with `_contains` boundary match on real captions):
     - Facts: one true fact whose phrase is a **boundary-sensitive** needle
       that a raw substring test over-matches, e.g.
       `ReferenceFact(text="cat", kind=OBJECT, polarity=TRUE,
       phrases=["cat"])` (the documented `_contains` false-positive class
       at `caption_metrics.py:59-74`: object tag `cat` hits `scattered`).
     - Caption: `"A scattered pile leans on a wall."` (contains substring
       `cat`⊂`scattered`; **no** whole-token `cat`).
     - Assert under real `_contains`: `verified_count == 0` (boundary miss).
     - **Dependency arm**: monkeypatch `_contains` to always return `True`
       for needle `"cat"`; assert `verified_count == 1` under the patch.
       Restore real `_contains`; assert `verified_count == 0` again. The
       verdict must **flip** with the return value.
     - **Trivial cheating implementation that must fail**:
       `any(t in caption.lower() for t in fact.match_targets())` (raw
       substring) — returns `verified_count == 1` on the scattered caption
       without the patch and fails the real-`_contains` zero assert. A
       discarded seam call that still uses raw `in` for the count also
       fails the dependency arm (verdict does not flip when `_contains` is
       forced True/False if the implementation ignores the return).
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
keys **with live values**. This emit is the Lane C Carries report-emit
row in the **Objective** DoD table. Do **not** implement bake-off ranking
*sort* here (unowned and unmet).

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
- After `result` closes: L606–607 are the ALTQ-1 Slice 2 comment that
  explains the immediately following `short_failed_images` block at
  `report.py:608-610` (first post-literal statement that mutates
  `result["caption"]`). **Do not insert between the ALTQ-1 comment and
  its statement** — that orphans the comment (see quality-block placement
  below).
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
| `inner_state_attribution_hits` | `list[str]` (from `scores.inner_state_attribution_hits`) | `[]` (key always present; empty list, never omit, never `None`) |
| `agentless_passive_hits` | `list[str]` (from `scores.agentless_passive_hits`) | `[]` (key always present; empty list, never `None`) |
| `signal_density` | **nested object** (not flat keys): `{ "verified_count": int, "word_count": int, "density_per_100w": float \| null }` | `{ "verified_count": 0, "word_count": 0, "density_per_100w": null }` |

`signal_density` is **always** the nested object mirroring `SignalDensityScores`
field names. Density is computed by the **sibling pure function**
`score_signal_density` (Slice 3) — **not** a `CaptionScores` field.

**Empty-value convention vs neighbouring `meta_framing_hits` (locked):**
existing `meta_framing_hits` at `report.py:486` emits
`scores.meta_framing_hits if scores is not None else None` — i.e. **`None`**
on the unscored / `short_error` path. That historical convention is **not**
changed by this task (do not rewrite pre-existing consumers). The new
depiction hit-list keys deliberately lock **`[]`** on the same path so
typed consumers can treat them as always-present lists. The two conventions
**legitimately differ**: `meta_framing_hits` preserves the pre-DEPICT-2
`None`-means-unscored signal; new keys choose always-list for simpler
downstream typing. Do **not** "harmonise" by making new keys `None` or by
changing `meta_framing_hits` to `[]` in this task.


**Quality / corpus block — SHORT surface only** (additive keys on
`result["quality"]` assigned **after** the `result` dict literal closes at
`report.py:604` **and after** the entire `short_failed_images` block at
`report.py:608-610` (i.e. immediately after L610, before the next ALTQ-1
v3 / title block) — **not** between the ALTQ-1 Slice 2 comment at
L606–607 and the statement it explains at L608, **not** by extending
`_quality_block`, and **not** by inserting statements inside the open
`result` literal):

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
`report.py:604` **and after** the entire `short_failed_images` block at
`report.py:608-610` (not between the ALTQ-1 comment and its statement; not
inside the open literal; not inside `_quality_block`):

```
# Placement: AFTER `result: dict[str, Any] = { … }` closes at report.py:604,
# AFTER the short_failed_images block at report.py:608-610 (keep the ALTQ-1
# Slice 2 comment at L606-607 adjacent to the statement it explains at L608).
# Insert immediately after L610, before the next ALTQ-1 v3 / title block.
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
   closes at `report.py:604` **and after** the entire `short_failed_images`
   block at `report.py:608-610` (insert immediately after L610; keep the
   ALTQ-1 Slice 2 comment at L606–607 adjacent to the statement it explains
   at L608 — do **not** insert between them), **assign the three additive
   keys onto `result["quality"]`** per the locked schema and denominator
   above. `result["quality"]` already exists from the dict ENTRY at L575
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

**§3.1 land condition**: see **Objective** (measurement + emit landed;
ranking *sort* unowned/unmet). Playbook:
`### 3.1 Add a signal-density metric to the eval harness`.

## Consolidated Checklist

### Context and Ownership

- [ ] Loaded testing-python / backend-python / development-workflow rules.
- [ ] Owned paths only (see **Constraints**); no bakeoff ranking, schemas,
      prompts, `test_eval_harness_pipeline.py`, or `canon/` edits.
- [ ] Re-verified cited rule IDs:
      `grep -rE '^\| *\`?<ID><a name' canon/lexicons/`.
- [ ] Relative markdown links resolve from `docs/tasks/depiction/`. Playbook:
      `docs/runbooks/fir-captioning-orchestrator-playbook.md` (cite by heading).

### Checklist for Slice 1: Inner-state-attribution counter

- [ ] Freeze positive tables + exemption floor + `_INNER_REPORTING_STEMS` /
      `_INNER_SOURCE_FRAME_PATTERNS` exactly as Slice 1 lists (EXIT B
      exemption set: floor + five published 4b frames).
- [ ] Implement all Slice 1 Proof items 1–13 (parametrized positives,
      hedges, 4b/4c, will carve-outs, common-noun product, mixed 11a–11c,
      held-out adjunct pool, source-guard contract).
- [ ] `CaptionScores.inner_state_attribution_hits`; `gated_score` unchanged.
- [ ] `pytest … -k inner_state -q` green.

### Checklist for Slice 2: Agentless-passive / mutual-event / actorless-event-noun

- [ ] Freeze Slice 2 tables; caption-level violence gate via `_contains`;
      clause-splitting rule; gap structural lexicon + evidentiary-gap
      span-overlap exclusion; published pools 2b/2c/gap/4d as specified.
- [ ] Implement all Slice 2 Proof items 1–9 (including straddling fixture
      under violence-scope lock, proof 7 zero combined hits, 4d/4f/4e).
- [ ] `CaptionScores.agentless_passive_hits`; no gate side-effect.
- [ ] `pytest … -k agentless_passive -q` green.

### Checklist for Slice 3: Signal density + Williams/C5

- [ ] Implement `score_signal_density` → `SignalDensityScores` and all
      Slice 3 Proof items (incl. 5a–5f, empty caption, docstring).
- [ ] Do **not** cite PROV-01 as density-numerator warrant.
- [ ] `pytest … -k signal_density -q` and full metrics file green.

### Checklist for Slice 4: Report emit

- [ ] Wire `reference_facts` → `score_signal_density`; emit locked
      per-image + SHORT quality keys per Slice 4 schema (after `result`
      literal and `short_failed_images` block; do not extend
      `_quality_block`).
- [ ] Reserved `test_eval_harness_report_depiction.py` exact-value proofs.
- [ ] No ranking *sort*; DoD per **Objective**.
- [ ] `pytest scene/tests/test_eval_harness_report_depiction.py -q` green.

### Review Readiness

- [ ] No new hard gate or threshold on first land; every assertion has red
      input + discrimination in the same PR.
- [ ] Williams/C5 written in-module (Slice 3 item 8 mechanical proof).
- [ ] No colour IDs, no `FM-11`, no fabricated rule IDs; no PROV-01 on
      density numerator membership.
- [ ] Report emit via reserved `test_eval_harness_report_depiction.py`;
      bake-off ranking *sort* explicit non-scope (**Objective** DoD table).
- [ ] Every held-out proof invokes **## Source-guard contract** (folded-AST
      + runtime positive-set arm + semantic arm).

## Stretch Goals

- [ ] Corpus-level `mean_signal_density` helper mirroring `insertion_rate` (if not already landed in Slice 3/4).
- [ ] Report-only rate helpers (`inner_state_image_rate`, `agentless_passive_image_rate`) once per-image fields exist — still no gates.
- [ ] Future **register-compliance** metric arm that reads DEPICT-1
      `DescriptionRegister` (`FORENSIC | EDITORIAL | INTERPRETIVE`) from the
      contract envelope — separate from the attributive/bearer-frame grammar cut
      in Slice 1; not planned in DEPICT-2.

## Success Criteria

Acceptance is the union of the per-slice Proofs under **Slice Delivery**
(Slices 1–4) plus the **Objective** DoD table. Do **not** re-derive DoD,
ranking ownership, or proof fixtures here.

- [ ] Slice 1 proofs green (`-k inner_state`): every frozen person/predicate
      member hits on varied scaffolds; floor hedges/bearers + the five
      published 4b frames + 4c position lock are zero-hit / still-hit as
      specified; mixed-caption 11a–11c still fire on unmarked ownership;
      hit elements are lower-cased matched surface text; `gated_score`
      unchanged.
- [ ] Slice 2 proofs green (`-k agentless_passive`): every frozen passive
      form and floor mutual/actorless noun under caption-level
      `_VIOLENCE_CONTEXT_TERMS` via `_contains`; published 2b/2c pools hit;
      by-agent floor × product + three published 4d held-outs exempt;
      non-agentive `by` still hits (4f); clause-splitter / following-
      sentence locality locks; gap floor + published gap pool → **zero
      entries in `agentless_passive_hits`** (evidentiary-gap exclusion);
      straddling fixture `"Four students were killed; an incident
      followed."` hits `"incident"`; photographic bare `shot` silent,
      violence-sense shot passives hit.
- [ ] Slice 3 proofs green (`-k signal_density`): verified density fields;
      rare-ungrounded and padding controls; TRUE filter before three-field
      dedupe; `_contains` dependency; empty caption → `density_per_100w is
      None`; Williams/C5 docstring roles present.
- [ ] Slice 4 proofs green (`test_eval_harness_report_depiction.py`): locked
      per-image + SHORT quality keys and exact values; no ranking *sort*.
- [ ] Owned paths only; no PROV-01 citation on density numerator; no `FM-11`.
- [ ] DoD land conditions met per **Objective** (measurement + report emit
      landed; ranking *sort* unowned and unmet).

## Not-Doing

- Prompt text / emotion-bearer edits (Lane A; DEPICT-4).
- Contract, schema, enum, `voice`, `DescriptionRegister`, bound-term fields
  (Lane B). Future register-compliance metric that would read
  `DescriptionRegister` is named only (Stretch); not implemented here.
- Bake-off ranking *sort* — **unowned and unmet** (see **Objective**).
- Colour vocabulary of any kind; `FM-11` citations; Lane D trigger work.
- Race warrant / parity gate (ATTRIB-06) — pass-level property; harness is
  per-image only.
- Thresholding or hard-gating any new counter on first land.
- Dedicated CAL-02 abstain-rate metric (would restate fabrication or be
  vacuous without weak-evidence fixtures) — see scope decision above.
- Second fabrication metric that restates `score_hallucination` /
  `fabricated_fact_rate`. PROV-01 is **not** cited for density numerator
  membership (PROV-01 lexicon row = model/input lineage on outputs —
  Failure *"…without model and input lineage"*; not gold-label membership).
- Flagging ATTRIB-08-compliant **same-clause** gap-language passives as
  violations (Slice 2 exempts same-clause structural gap-statements
  including `_GAP_AGENT_PHRASES` floor + held-out gap pool; prior- **and**
  following-sentence / different-clause gap phrases still hit — see proofs
  7b and 7c).
- Edits to the existing shared `test_eval_harness_report.py` (deliberately
  unedited; DEPICT-2 owns only the reserved depiction report-emit file).
- LLM-judge scoring, model training, non-deterministic axes.
- A full voice tagger / dependency parser for exemption, clause, or
  event-noun recovery — surface tests named in this plan are the
  contract.
