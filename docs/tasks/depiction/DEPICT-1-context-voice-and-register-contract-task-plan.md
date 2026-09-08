# DEPICT-1. Context voice, description register, and restrict-only gravity (contract)

> **Metadata**
>
> - **Date**: 2026-07-27
> - **Author**: grok-4.5 (remote flock lane B)
> - **Project**: `prototype-description-service`
> - **Task ID**: `DEPICT-1`
> - **Target Branch**: `feature/depict-1`
> - **Review Coverage Target**: 2
>
> Governing assessment: `docs/assessments/current/depiction-canon-triage-and-backlog-2026-07-27.md`
> (§2 items 2/7/9, §5c–§5d, §10g). Upstream eval findings F1/F3/F4:
> `docs/assessments/current/depiction-canon-fit-captioning-pipeline-2026-07-27.md`.
> Canon under review: heuristics-canon-research **v0.17.2**, commit
> `4e099ded65ee33bc4db85dfd4c65409a0087a752`. Load-bearing IDs
> (`ATTRIB-07`, `ATTRIB-01`/`03`/`05`, `API-09`/`10`, `TEST-15`, `REF-29`,
> `STRAT-11`) re-verified against `canon/lexicons/` definition anchors.

## Objective

Land three **additive, closed** contract surfaces on the describe HTTP boundary
before v3 promotion freezes the shape:

1. **`ContextVoice` provenance on each allowlisted nested context-pack model**
   (explicit allowlist in Slice 1; `IdentityContext.review_reasons` and
   `IdentityPolicyContext` are outside the speech-voice allowlist), with a
   pack-side partition that marks creator-tagged speech quotable-only by
   **operator policy** (see Workflow Principles; `ATTRIB-07` warrants only the
   oppressive-string subset).

   **Voice grain (intentional narrowing).** Upstream fit F1 recommends voice as
   a *typed property of each context field*. This task delivers **one `voice`
   per nested speech-bearing object** (the owning model), not per leaf string.
   Mixed-provenance objects (e.g. `attachment.caption` creator +
   `attachment.title` operator) are **out of scope and unrepresentable** on this
   contract. A later per-field voice shape is a **breaking re-grain**, not an
   additive extension of the object-level field ([API-09] shape). See Stretch
   Goals.

   **Term:** In this plan, **voice** means `ContextVoice` provenance of a
   context-pack entry. It is **not** DEPICT-2 narrative/grammatical caption
   register, and **not** `DescriptionRegister` altitude.

2. **`DescriptionRegister`** (`FORENSIC | EDITORIAL | INTERPRETIVE`) as
   request-side vocabulary with enforcement deferred (no response echo in this
   task).

3. **Restrict-only gravity directive** with a separate **obligation**
   disposition as schema + pure report helpers. The helper
   `inventory_obligation` returns a **bool the caller may ignore**; this wave
   does **not** prevent silent inventory suppression operationally, and does
   **not** close assessment §2 item 9 / DEPICT-D1 (see Slice 3). Each surface
   ships with [TEST-15] red-first proof.

## Problem Statement

The typed `ContextPack` already forbids unknown keys (`extra="forbid"`) and
bounds every nested string, but it carries **no voice provenance**. CMS-authored
caption/title/taxonomy strings are rendered into the production prompt and the
shipping system prompt (today
`scene/infrastructure/vlm/gpu_remote_adapter.py` `_SYSTEM_PROMPT` L28–37;
post-DEPICT-0 the same v1 body lives in the selected `ProductionPrompt` in
`scene/prompts/caption_system.py`). **Production consumer binding** follows
DEPICT-0 section **Consumers:** and FROZEN CONTRACT A — see **Norm C1** under
`## Constraints` (stated once; rest of this plan cites Norm C1). That prompt
body instructs the model to *weave* names and factual details *where they fit
naturally* — dissolving the seam between creator speech and the system's
unmarked descriptive voice (eval finding F1). When the dissolved speech is
**oppressive creator wording**, it is a direct `ATTRIB-07` hit; the operator
also defaults **all** creator-tagged CMS speech to quotable-only as a
conservative policy beyond that canon trigger.

Separately, the FORENSIC / EDITORIAL / INTERPRETIVE vocabulary is already the
spine of canon's `attribute-claims-to-their-bearer` reasoning card and of every
`ATTRIB`/`BOUND` row that splits register altitude, but **zero** of those tokens
exist in `scene/` or the describe contract. Retrofitting the enum after call
sites proliferate is a rewrite. A restrict-only gravity flag is the right
default for most sensitive classes and the **wrong** default for public
atrocity imagery (`ATTRIB-05`; opposed poles also under `STRAT-11`); the
contract must carry both poles partitioned, not a blended middle — **as shape
only** in this wave (item 9 / DEPICT-D1 remains unaddressed).

## Constraints

- **Norm C0 — File ownership (hard boundary; closed set, no directory prefix).**
  This lane edits **exactly** these paths (assessment heading
  `### 6e. Dispatch shape — file ownership, not just task ownership` →
  `#### §6e ownership table` Lane B row is the collision oracle and must match):

  | Path | Role |
  |---|---|
  | `scene/interface_adapters/http/schemas/requests.py` | Request / pack models |
  | `scene/interface_adapters/http/schemas/context_contract.py` (**new**) | Pure helpers + fact dataclass; sole new schema module this wave |
  | `scene/domain/description.py` | Domain `StrEnum` vocabularies |
  | `scene/tests/test_context_pack.py` | **Sole editor this wave** for DEPICT-1 voice-related edits ("co-owned" = shared pre-existing coverage, not dual-lane concurrent edit) |
  | `scene/tests/test_context_voice_contract.py` (**new**, Lane B sole) | Voice partition proofs |
  | `scene/tests/test_description_register_contract.py` (**new**, Lane B sole) | Register proofs |
  | `scene/tests/test_gravity_contract.py` (**new**, Lane B sole) | Gravity proofs |

  **No other file.** A fifth test module, any extra schema module under
  `schemas/`, or any path not in this table requires amending this bullet
  **and** the assessment Lane B row before the edit. Do **not** edit Lane A
  paths (`gpu_remote_adapter.py`, `bakeoff.py`, `settings.py`,
  `scene/prompts/caption_system.py`), Lane C (`caption_metrics.py`),
  `scene/interface_adapters/http/schemas/responses.py`,
  `packages/shared-contracts/...`,
  `scene/application/visual_facts_service.py`, or
  `scripts/eval_harness/manifest.py`.

- **Norm C1 — Production selected-config consumer bind (DEPICT-0 section
  `Consumers:` + rebind rule).** Consumers of the **selected config** obtain it
  only through `production_prompt()` / `production_system_prompt()` /
  `production_prompt_or_task_version()`. Do **not** bind via
  `from … import PRODUCTION_PROMPT`, and do **not** introduce a dedicated
  frozen body export. The production adapter **snapshots once** at construction
  (`self._production_prompt = production_prompt()`;
  `self.prompt_or_task_version = self._production_prompt.lineage_version`) and
  posts **`self._production_prompt.body`** at describe/payload time — not a
  second describe-time accessor call, and not a live re-read of module-level
  `PRODUCTION_PROMPT`. DEPICT-0 forbids a separate `PRODUCTION_SYSTEM_PROMPT`
  string global. **Mutation / F1 (b) when later owned:** **REBIND-ONLY** —
  DEPICT-0 states *"A future promotion replaces `PRODUCTION_PROMPT` (or rebinds
  the selected instance) with a new `ProductionPrompt(body=…,
  lineage_version=…)` so body and stamp move as one for **new** consumers /
  adapters that call `production_prompt()` after the rebind."* Never mutate
  `.body` on the frozen dataclass (`FrozenInstanceError`). A module-level
  REBIND does **not** rewrite an already-constructed adapter. Cite **Norm C1**
  elsewhere; do not restate.

- **Greenfield, no shims.** No data migrations, no dual-write flags, no
  backward-compat adapters. Delete over flag (repo Greenfield Policy — same
  formulation DEPICT-0 Constraints state; not a lexicon row). There are no
  production users. **[API-09] governs the HTTP field *shape* only**: new
  request fields are optional-or-defaulted; never remove, rename, retype, or
  make-required an existing element. **Observable default injection and the
  one-time `context_hash` change are *not* warranted by API-09** — API-09
  states that changed defaults count as breaking (Hyrum's Law;
  `canon/lexicons/engineering.md` API-09 definition). Those observable changes
  are authorized by **repo Greenfield Policy** despite API-09, not by API-09.
- **`extra="forbid"` is already set** on every context and request model.
  Additive fields must have defaults (or be optional) so existing payloads that
  omit them still validate. Unknown keys still 422.
- **Prompt text is out of scope.** The weave-instruction half of F1 has nowhere
  safe to land until DEPICT-0 closes the prompt *seam* (DEPICT-0 Not-Doing:
  "Changing what any prompt **says**" / "Weave-side context consumption / F1
  voice-honouring prompt behaviour"). The actual voice-honouring weave rewrite
  is **F1 (b) production-weave** — **OUT of this wave, unowned** (no plan file
  delivers it). When owned later, mutation follows **Norm C1**. Do not edit
  prompt strings here; do not attribute the weave edit to DEPICT-0.
- **Bound-term / colour field shape is out of scope.** Assessment §10g removed
  it. `FM-11` is retired canon and must not be cited.
- **Enforcement of register gates is deferred.** Land the enum; do not build
  "FORENSIC forbids X" rejection logic beyond vocabulary + exhaustiveness.
- **v3 three-surface `caption` split (F4 / DEPICT-5) is not this task.** F4
  changes harness v3 output in `bakeoff.py` (three-surface instructions); this
  task changes request schemas and domain enums — owned path sets do not
  intersect. Do not claim DescriptionRegister "unblocks" F4.
- **No scorer / `caption_metrics.py` work** (Lane C).
- Tests run from `apps/prototype-description-service/` via
  `uv run --extra dev pytest <path>`.

## Workflow Principles

- **Contract before behaviour.** Shape lands now; weave behaviour and register
  gates land when their enforcement owners exist ([API-10], assessment §5c).
- **Don't change it, add it (shape).** Every new HTTP field is
  optional-or-defaulted so omit-still-validates ([API-09] shape half). The
  Greenfield Policy — not API-09 — authorizes that omit-path callers observe
  new default `voice` keys in dumps/`context_hash` after this lands.
- **Fail closed on unmarked creator speech (operator policy + ATTRIB-07).**
  Default `voice` for CMS-originated pack entries is `creator` so unset fields
  enter the quotable-only partition, never the absorbable set, until a caller
  deliberately marks them otherwise. **Canon hit:** `ATTRIB-07` obliges
  voice-tagging only for *racist or otherwise oppressive* creator wording
  (`canon/lexicons/depiction.md` ATTRIB-07 definition). **Operator policy (no
  canon warrant):** treating *every* default creator entry as quotable-only is
  a conservative product choice.
- **Carry opposed poles whole (shape).** Monotone-restrict and atrocity-class
  obligation are both first-class dispositions (`STRAT-11`).
  `inventory_obligation` **reports** that inventory is obligated (returns
  `bool`); the **caller** is responsible for honouring it — the function has
  no refusal authority. Schema default stays `restrict` (fail-closed). This
  wave does **not** assign DEPICT-D1 ownership or close assessment item 9.
- **Red-first for every new check.** Each assertion names the exact failing
  input and a discrimination case that proves non-vacuity ([TEST-15]).
- **One canonical `StrEnum` per vocabulary** (repo `sr-007`). No scattered magic
  strings; exhaustive matching where the code branches on the enum ([REF-29]).

## Terminology

- **`ContextVoice` / pack `voice` (this plan):** `creator | catalogue |
  operator | derived` — **provenance** of a context-pack object's speech fields
  (who authored the CMS surface). Creator-tagged entries are **quotable-only**.
  **Disambiguation (DEPICT-1 vs DEPICT-2):** here *voice* = `ContextVoice`
  provenance. DEPICT-2 uses *voice* for **narrative/grammatical caption
  register** (active/passive, event-nominal inventory). `DescriptionRegister`
  is a third concept (`FORENSIC | EDITORIAL | INTERPRETIVE` altitude). Cite the
  enum name when integrating.
- **Quotable-only**: the partition may *cite* the string (quoted / voice-tagged);
  it must never hand it to the absorbable weave set as unmarked system speech.
- **Absorbable**: catalogue / operator / derived entries eligible for unmarked
  factual weave (subject to existing pixels-win and unaccounted-name rules).
- **`DescriptionRegister`**: `FORENSIC | EDITORIAL | INTERPRETIVE` — assertable
  altitude of the description.
- **Register rank** (for monotone gravity): `FORENSIC < EDITORIAL < INTERPRETIVE`.
- **`GravityDisposition`**: `restrict | obligate_inventory`.
  - `restrict` — may only **narrow** effective register rank (never expand).
  - `obligate_inventory` — public-atrocity / high-salience force class: visible
    inventory **ought** to remain stateable; restriction must not mint a
    plight-type in place of a named singular record (`ATTRIB-05`). The pure
    helper `inventory_obligation` **reports** this disposition as a bool.
- **Image-class partition**: operator-owned mapping from content class →
  disposition. **OUT of this wave / unowned** (DEPICT-D1) — not a DEPICT-1
  DoD artifact; assessment §2 item 9 remains unaddressed.

## Current State Analysis

- `ContextPack` and all nested models in
  `scene/interface_adapters/http/schemas/requests.py` set
  `model_config = ConfigDict(extra="forbid")` (verified at `ContextPack` L91 and
  every nested model, including `DescribeImageEnvelope` L108).
- Nested pack models today: `AttachmentContext`, `PostContext`,
  `TaxonomyTermContext`, `ProductContext`, `IdentityPolicyContext`,
  `IdentityContextItem`, `IdentityContext`. No voice field anywhere.
  Caller-supplied text fields live on those models at
  `requests.py` L11–81. **`IdentityPolicyContext` has exactly one field** —
  `person_naming: str` (`requests.py` L55–60) — OUT of inventory. Do **not**
  add `voice` to `IdentityPolicyContext` or to `IdentityContext` (its
  `review_reasons` is operator metadata, not speech partition).
- Response contract: 17 core fields + additive optionals on
  `VisualFactsResponse`. Shared JSON schema path expected by
  `test_response_schema_parity.py:SCHEMA_PATH` (L11–17):
  `packages/shared-contracts/schemas/image-description-response.schema.json`
  (**present**; ~8413 bytes). This task does **not** add
  `description_register` to the response (`build_visual_facts_envelope` at
  `visual_facts_service.py` L71–83 takes no register parameter).
- Domain enums live in `scene/domain/description.py` (`sr-007` docstring). No
  `DescriptionRegister`, `ContextVoice`, or gravity enum exists.
- Production weave clause is in `gpu_remote_adapter.py` L33–34 today — **Lane A
  owned**. Post-DEPICT-0 the body moves to `scene/prompts/caption_system.py`
  under Norm C1. **F1 (b)** (OUT/unowned) later REBINDs per Norm C1.
- Defaulted `voice` keys change `context_hash` once under **Greenfield Policy**
  (not API-09); no migration.
- Pack characterization at `scene/tests/test_context_pack.py`: `_context_pack`
  at L43; used at L69 / L94 / L108 / L134; route dump-equality at **L139**
  (`assert adapter.context == _context_pack()` — the assertion default `voice`
  keys break). Slice 1 owns the fixture split. Response parity properties
  equality is in `test_schema_required_matches_model_fields` (asserts
  `set(schema["properties"]) == set(VisualFactsResponse.model_fields)`).
- Caption-fact inventory alignment floor (fusion neighbour): `product.name`,
  `attachment.title`/`caption`, `post.title`, `taxonomy_terms[].name`. Slice 1
  inventory covers that set **plus** additional IN rows in the inventory table.

## Target Outcome

1. Every nested context-pack model on the speech-field allowlist (Slice 1)
   carries a `voice: ContextVoice` with a fail-closed default; a pure, tested
   partition function over the fixed fact inventory returns disjoint
   absorbable vs quotable-only fact lists, and **creator never appears in
   absorbable**. Object-level grain only (Objective voice-grain narrowing).
2. `DescriptionRegister` exists as a single `StrEnum` and is accepted on the
   **request** envelope (default `EDITORIAL`), with an exhaustiveness guard.
   **No response echo** in this task.
3. `GravityDirective` exists on the request envelope with
   `disposition ∈ {restrict, obligate_inventory}` and optional `image_class`;
   pure functions prove restrict is monotone-non-expanding and that
   `inventory_obligation` **reports** obligation. Class→disposition table is
   **not** shipped; assessment item 9 remains unaddressed.
4. Scoped pytest green; no prompt edits; no metrics edits; no bound-term fields;
   no shared-schema edit; no `responses.py` edit.

## Context Loading

- Rules: `docs/workbay/rules/backend-python-guidelines.md`,
  `docs/workbay/rules/testing-python.md`,
  `docs/workbay/rules/development-workflow.md`
- Template / exemplar: `docs/workbay/templates/TASK_PLAN.template.md`,
  `docs/tasks/altq/ALTQ-1-alt-text-quality-task-plan.md`
- Assessment: `docs/assessments/current/depiction-canon-triage-and-backlog-2026-07-27.md`
  (§1 D3, §2 items 2/7/9, §5b–§5d, §10g)
- Eval: `docs/assessments/current/depiction-canon-fit-captioning-pipeline-2026-07-27.md`
  (F1, F3)
- Reasoning card: `attribute-claims-to-their-bearer` (canon public reasoning;
  plain-text cite only)
- Owned code: the closed path set in **Norm C0**

### Canon warrants (definition-anchor verified)

Every ID below was verified with
`grep -rE '^\| *`?<ID><a name' canon/lexicons/` (definition row, not
cross-reference). Retired IDs checked against `canon/literature/HELD.md`.

| ID | Lexicon | Role in this task |
|---|---|---|
| `ATTRIB-07` | `canon/lexicons/depiction.md` | **Oppressive creator-string subset only**: racist/oppressive creator wording must be voice-tagged, never unmarked system speech. Does **not** by itself obligate quotable-only for all CMS strings. |
| `ATTRIB-02` | `depiction.md` | **Output** who/by-whom/identity claims leave FORENSIC unless cited. Not a warrant for the input CMS-string voice field. |
| `ATTRIB-01` | `depiction.md` | Bearer-not-depicted; register vocabulary consumer. |
| `ATTRIB-03` | `depiction.md` | Non-visible content → EDITORIAL/INTERPRETIVE with bearer. |
| `ATTRIB-05` | `depiction.md` | **F3 / gravity obligation warrant:** honor source name/withhold/singularity; never mint a plight-type — the specific move a restrict-only default produces on singular atrocity records. Definition: *"never mint a plight-type to replace a missing name, invent a name when withheld, or write an interchangeable illustration line"*. |
| `API-09` | `canon/lexicons/engineering.md` | **Shape only**: don't remove/rename/retype/make-required; additions optional. **Not** a warrant for observable default/hash changes. |
| `API-10` | `engineering.md` | Interface is its own artifact. |
| `REF-29` | `engineering.md` | Enum completeness / exhaustiveness. |
| `STRAT-11` | `business-marketing.md` | Do not average opposed goods — dual-pole gravity shape (`restrict` vs `obligate_inventory`). Definition: *"the middle can be worse than either pole"*. |
| `TEST-15` | `engineering.md` | Prove the green can go red. |

**Not cited for F3 / gravity (decorative co-citation removed):**

- `ATTRIB-04` (*"Distress undercoding, not beautify"*) — governs beauty/affect
  co-voiced with harm inventory in **output** access text; does not warrant the
  input gravity disposition dual-pole.
- `BOUND-03` (*"Frame before institutional story"*) — governs event/purpose
  language ordering force inventory in **output** captions; does not warrant
  the request-side gravity disposition enum.

**No canon warrant (explicit):**

- No `REG` family; `DescriptionRegister` is operator-reserved design vocabulary
  backed by `ATTRIB-01`/`ATTRIB-03` and the reasoning card — not a `REG-xx` row.
  `FM-11` is retired; do not invent `REG-*` / `HARM-01`.
- **Blanket quotable-only default** for all creator-tagged CMS speech is
  **operator policy**, not ATTRIB-07 alone.
- Image-class → disposition mapping is DEPICT-D1 (assessment §2 item 9) —
  **OUT/unowned**; item 9 **unaddressed** by this plan.
- Bound-term / colour shape: out of scope (§10g).
- `BOUND-02` is **not** cited for the input voice partition (output craft/staging).
- Delete-over-flag / one-time `context_hash` change = repo Greenfield Policy,
  despite API-09 Hyrum note.
- Harness `ContextPack` voice mirror (`scripts/eval_harness/manifest.py`
  L165–176) is **OUT/unowned**. F1 (a) traps are service-unit-only.
- Response-side `description_register` echo is not in this task.

## Contract and Boundary Impact

| Boundary | Owner | Expected Change | Verification |
|---|---|---|---|
| `POST /scene/describe/multipart` request JSON (`context_pack`) | Lane B | Additive `voice` on speech-allowlist nested models (object-level grain); defaults applied server-side | `test_context_pack.py` + `test_context_voice_contract.py` |
| `DescribeImageEnvelope` | Lane B | Additive defaulted `description_register`, `gravity` | `test_description_register_contract.py` + `test_gravity_contract.py` |
| `VisualFactsResponse` / shared JSON schema | **Unchanged** | No `description_register` field | Existing `test_response_schema_parity.py` stays green without edit |
| Production system prompt / weave | **F1 (b) — OUT/unowned** | Must honour quotable-only on service pack path when owned (Norm C1) | Not this task; DEPICT-0+1+2 merge does **not** close F1 |
| Eval harness metrics | Lane C | Future register-compliance arm | Not this task |

## Proposed Solution

Three reviewable slices (detail in Slice Delivery):

1. **Voice vocabulary + pack partition** — `ContextVoice` StrEnum; object-level
   `voice` on speech-allowlist nested models with per-model defaults; fixed fact
   inventory with model-field completeness guard; pure `partition_context_pack`;
   independent string freezes in tests; boundary-voice proof uses **dump-field
   equality + independent expected render line** (Norm S1 under Slice 1 — not
   `ast.literal_eval` re-parse of the L85 line).
2. **Register vocabulary (request only)** — `DescriptionRegister` StrEnum;
   request default `EDITORIAL`; independent freeze; no response field.
3. **Gravity directive** — `GravityDisposition` + `GravityDirective` **in
   `requests.py`**; pure helpers in `context_contract.py`; independent freeze;
   report-only `inventory_obligation`; DEPICT-D1 memo OUT; item 9 unaddressed.

## Files and Surfaces to Change

| Surface | File | Change |
|---|---|---|
| domain enums | `scene/domain/description.py` | Add `ContextVoice`, `DescriptionRegister`, `GravityDisposition` |
| request contract | `scene/interface_adapters/http/schemas/requests.py` | `voice` on allowlist models; `description_register` + `gravity`; **`GravityDirective` model lives here** |
| schema helpers (new) | `scene/interface_adapters/http/schemas/context_contract.py` | Pure `partition_context_pack`, `effective_register`, `inventory_obligation`, `ContextFact`; inventory + production freezes used by partition |
| tests | four files named in Norm C0 | Voice / register / gravity proofs + fixture split |

**Not edited:** `responses.py`, shared JSON schema, `test_response_schema_parity.py`,
`caption_system.py`, `gpu_remote_adapter.py` (tests may *call*
`_render_context` / `_user_text`), `visual_facts_service.py`,
`scripts/eval_harness/manifest.py`.

## Related Files

| File | Note |
|---|---|
| `scene/interface_adapters/http/routers/describe.py` | Pack dump at L446: `model_dump(exclude_none=True)` only. Router churn stays zero. |
| `scene/application/visual_facts_service.py` | `build_visual_facts_envelope` L71–83 — no register parameter; not edited. |
| `scene/application/fusion/reconcile.py` | Caption-fact paths are inventory alignment floor only. |
| `scene/application/hashing.py` | Defaulted `voice` keys change hash once (Greenfield). |
| `scene/infrastructure/vlm/gpu_remote_adapter.py` | `_render_context` L73–87 / `_user_text` L90–101. Norm C1 post-DEPICT-0. F1 (b) OUT. |
| `scene/prompts/caption_system.py` | DEPICT-0 home of `PRODUCTION_PROMPT` + accessors. Norm C1. |
| `scripts/eval_harness/bakeoff.py` | Lane A. Post-DEPICT-0: `build_prompt_variants()` sole construction helper. |
| `scripts/eval_harness/manifest.py` | Harness `ContextPack` — no `voice`; OUT/unowned. |
| Reasoning card `attribute-claims-to-their-bearer` | Design warrant for register vocabulary — plain-text cite only. |

## Cross-lane dependency

### F1 ownership split (this wave vs OUT)

Eval finding F1 has **two halves**. Merging DEPICT-0 + DEPICT-1 + DEPICT-2
**does not close F1**.

| Half | Scope | In this wave? | Owner | Acceptance (named) |
|---|---|---|---|---|
| **F1 (a) — service/contract** | Object-level `voice` on allowlist models; inventory + partition; register + gravity contract | **Yes** | **DEPICT-1** | Slice 1–3 success criteria green; no prompt wording change |
| **F1 (b) — production-weave** | Stop unmarked weave of creator-tagged fields; honour partition in render | **No** | **Unowned** | Norm C1 REBIND + service-path creator-not-absorbed proof; DEPICT-0 seam + DEPICT-1 Slice 1 are prerequisites **for F1 (b) only** |
| **Harness `ContextPack.voice`** | `scripts/eval_harness/manifest.py` | **No** | **Unowned** | Future lane adds `voice` + creator-trap fixtures |

**Prerequisite ordering:**

1. **DEPICT-0** and **DEPICT-1 implement and merge independently** — Owns sets
   are disjoint (assessment `#### §6e ownership table`). Rank-1-before-rank-2
   applies only to F1 **(b)**; pack-side DEPICT-1 can start in parallel.
2. **DEPICT-0** creates `caption_system.py`, moves body, **Not-Does** F1 weave
   wording (DEPICT-0 section **Not-Doing**).
3. **DEPICT-1** lands **F1 (a)** only. No DEPICT-0 artifact is a merge gate for
   this plan's green.
4. **F1 (b)** remains OUT/unowned. When owned: Norm C1. Harness pack `voice`
   remains separately unowned.

| Dependency | Owner / sequencing |
|---|---|
| Prompt seam (no wording) — Norm C1 bind form | **DEPICT-0 / Lane A** — parallel with DEPICT-1 |
| F1 (a) voice partition | **DEPICT-1** — this wave |
| F1 (b) weave | **OUT/unowned** — Norm C1 when owned |
| Shared JSON schema mirror | n/a this task (response register withdrawn) |
| Register-compliance metric | Lane C future option once vocabulary exists; **not** a DEPICT-1 DoD; path sets do not intersect F4 |
| Harness ContextPack `voice` | **OUT/unowned** |

## Verification Strategy

From `apps/prototype-description-service/`:

```bash
uv run --extra dev pytest scene/tests/test_context_voice_contract.py \
  scene/tests/test_description_register_contract.py \
  scene/tests/test_gravity_contract.py -q
uv run --extra dev pytest scene/tests/test_context_pack.py -q
uv run --extra dev pytest scene/tests/test_response_schema_parity.py -q
```

- Old payloads without new keys still `model_validate`; post-validate dump
  includes default `voice` on allowlist models only.
- Invalid enum values → `ValidationError`.
- Response model / shared schema / `PREVIEW_FIELDS` **unchanged**.
- Defaulted `voice` keys change `context_hash` once (Greenfield).
- **Out of verification:** production weave still unmarked until F1 (b) is
  owned; request register not on any response; harness `voice` remains OUT;
  assessment item 9 / DEPICT-D1 remains unaddressed.

---

## Slice Delivery

### Slice 1: `ContextVoice` on speech-bearing pack models + quotable-only partition

**Goal**: Creator-tagged context is structurally partitioned out of the
absorbable set, with schema defaults that keep existing callers valid and a
fixed fact inventory so a caption-only implementation cannot pass.
**Object-level grain only** (Objective voice-grain narrowing).

**Canon**: `ATTRIB-07` (oppressive subset only), `API-09` (shape), `TEST-15`.
`ATTRIB-02` / `BOUND-02` are **not** warrants for the input voice field.
**Operator policy:** blanket default `voice=creator` → quotable-only.

Changes:

- Add to `scene/domain/description.py`:
  ```python
  class ContextVoice(StrEnum):
      CREATOR = "creator"
      CATALOGUE = "catalogue"
      OPERATOR = "operator"
      DERIVED = "derived"
  ```
- On each allowlist nested model, add `voice` with that model's own default
  (**no** universal-CREATOR snippet):
  ```python
  # AttachmentContext / PostContext / ProductContext:
  voice: ContextVoice = ContextVoice.CREATOR
  # TaxonomyTermContext:
  voice: ContextVoice = ContextVoice.CATALOGUE
  # IdentityContextItem:
  voice: ContextVoice = ContextVoice.OPERATOR
  ```
- **No `voice` on `IdentityPolicyContext` or `IdentityContext`.**
- Add `scene/interface_adapters/http/schemas/context_contract.py`:
  - `@dataclass(frozen=True) class ContextFact` with
    `path: str`, `value: str`, `voice: ContextVoice`
  - `def iter_context_facts(pack: ContextPack) -> list[ContextFact]`
  - Production-side freezes used by partition (enum members for membership
    tests at runtime — **not** the permanent contract green; that lives in
    the **test** module as independent string literals — see M-07 below):
    ```python
    _QUOTABLE_ONLY_VOICES: frozenset[ContextVoice] = frozenset({
        ContextVoice.CREATOR,
    })
    _ABSORBABLE_VOICES: frozenset[ContextVoice] = frozenset({
        ContextVoice.CATALOGUE,
        ContextVoice.OPERATOR,
        ContextVoice.DERIVED,
    })
    ```
  - `partition_context_pack` — no silent default branch:
    ```python
    def partition_context_pack(
        pack: ContextPack,
    ) -> tuple[list[ContextFact], list[ContextFact]]:
        absorbable: list[ContextFact] = []
        quotable_only: list[ContextFact] = []
        for fact in iter_context_facts(pack):
            if fact.voice in _QUOTABLE_ONLY_VOICES:
                quotable_only.append(fact)
            elif fact.voice in _ABSORBABLE_VOICES:
                absorbable.append(fact)
            else:
                raise ValueError(f"unhandled ContextVoice: {fact.voice!r}")
        return absorbable, quotable_only
    ```
    Membership: `CREATOR` → quotable_only only; `catalogue|operator|derived` →
    absorbable.
  - **`else: raise` seam:** `monkeypatch.setattr` on
    `context_contract.iter_context_facts` to return a one-element list with an
    unhandled `ContextVoice`-shaped member; assert `ValueError` message
    contains the offending value.
  - Inventory proof: for every fixture,
    `set(f.path for f in iter_context_facts(pack)) == EXPECTED_PATHS` where
    `EXPECTED_PATHS` is explicit from fixture inputs — never against itself.

#### Fixed fact inventory for `iter_context_facts`

Only non-empty string values become `ContextFact`s.

| Path template | Source model field | In inventory? | Rationale |
|---|---|---|---|
| `attachment.title` | `AttachmentContext.title` | **IN** | free-text speech |
| `attachment.caption` | `AttachmentContext.caption` | **IN** | free-text speech |
| `attachment.description` | `AttachmentContext.description` | **IN** | free-text prose |
| `attachment.alt_text` | `AttachmentContext.alt_text` | **IN** | free-text prose |
| `attachment.filename` | `AttachmentContext.filename` | **OUT** | opaque file token |
| `post.title` | `PostContext.title` | **IN** | free-text speech |
| `post.excerpt` | `PostContext.excerpt` | **IN** | free-text prose |
| `post.post_type` | `PostContext.post_type` | **OUT** | structural tag |
| `post.status` | `PostContext.status` | **OUT** | structural tag |
| `product.name` | `ProductContext.name` | **IN** | free-text speech |
| `product.short_description` | `ProductContext.short_description` | **IN** | free-text prose |
| `product.sku` | `ProductContext.sku` | **OUT** | identifier |
| `product.price` | `ProductContext.price` | **OUT** | commerce token |
| `taxonomy_terms[{i}].name` | `TaxonomyTermContext.name` | **IN** | label speech |
| `taxonomy_terms[{i}].taxonomy` | `TaxonomyTermContext.taxonomy` | **OUT** | taxonomy id |
| `taxonomy_terms[{i}].slug` | `TaxonomyTermContext.slug` | **OUT** | slug token |
| `identity.identities[{i}].name` | `IdentityContextItem.name` | **IN** | roster speech |
| `identity.identities[{i}].identity_id` / `cluster_id` / `source` | ids | **OUT** | opaque ids |
| `identity.policy.person_naming` | `IdentityPolicyContext.person_naming` | **OUT** | policy token |
| `identity.review_reasons[{i}]` | `IdentityContext.review_reasons` | **OUT** | operator metadata |

Voice for each emitted fact is taken from the owning nested model's `voice`.

**Model-field completeness guard (M-08).** Freeze the full field set of every
inventoried nested model as independent string literals in the **test** module
and assert equality against live `model_fields` (covers exactly these published
models; extending requires amending this plan — EXIT B on model set):

```python
# test_context_voice_contract.py — independent of walker implementation
_FROZEN_MODEL_FIELDS: dict[str, frozenset[str]] = {
    "AttachmentContext": frozenset(
        {"title", "caption", "description", "alt_text", "filename", "voice"}
    ),
    "PostContext": frozenset(
        {"title", "excerpt", "post_type", "status", "voice"}
    ),
    "ProductContext": frozenset(
        {"name", "sku", "price", "short_description", "voice"}
    ),
    "TaxonomyTermContext": frozenset(
        {"taxonomy", "name", "slug", "voice"}
    ),
    "IdentityContextItem": frozenset(
        {"name", "identity_id", "cluster_id", "source", "voice"}
    ),
    "IdentityPolicyContext": frozenset({"person_naming"}),  # no voice
    "IdentityContext": frozenset(
        {"policy", "identities", "review_reasons"}
    ),  # no voice
}
for name, expected in _FROZEN_MODEL_FIELDS.items():
    model = getattr(requests_mod, name)
    assert set(model.model_fields) == expected, name
```

**Red if** a new contract field is added to any of those models without updating
both the inventory table (IN or OUT) **and** this freeze. Pair with the
parametrized IN/OUT path cases so the walker cannot silently ignore a new IN
field that was added to the freeze as OUT by mistake without a table amendment
review.

**Independent voice-value freeze in tests (M-07 — EXIT A property: string-value
membership of the enum equals a test-owned literal set; freeze must not live in
the implementation module):**

```python
# test_context_voice_contract.py ONLY
_EXPECTED_VOICE_VALUES: frozenset[str] = frozenset(
    {"creator", "catalogue", "operator", "derived"}
)
assert {m.value for m in ContextVoice} == _EXPECTED_VOICE_VALUES
# Independence source guard (constant-fold before match):
_impl = Path("scene/interface_adapters/http/schemas/context_contract.py").read_text()
_domain = Path("scene/domain/description.py").read_text()
assert "_EXPECTED_VOICE_VALUES" not in _impl
assert "_EXPECTED_VOICE_VALUES" not in _domain
# Survive concat/.replace/.join/data-file: the guard matches the *identifier*
# the test defines, not a foldable string token the production code can rebuild.
```

**Partition coverage freeze** (test-owned string sets; not `frozenset(ContextVoice)`):

```python
_EXPECTED_QUOTABLE = frozenset({"creator"})
_EXPECTED_ABSORBABLE = frozenset({"catalogue", "operator", "derived"})
assert _EXPECTED_QUOTABLE | _EXPECTED_ABSORBABLE == _EXPECTED_VOICE_VALUES
assert not (_EXPECTED_QUOTABLE & _EXPECTED_ABSORBABLE)
assert {v.value for v in _QUOTABLE_ONLY_VOICES} == _EXPECTED_QUOTABLE
assert {v.value for v in _ABSORBABLE_VOICES} == _EXPECTED_ABSORBABLE
```

Hand-edit the enum to add a fifth value without updating `_EXPECTED_VOICE_VALUES`
→ permanent green goes red. Deriving expected via `set(ContextVoice)` is
**forbidden** as the permanent green.

- Do **not** edit `gpu_remote_adapter.py` or `caption_system.py`. Runtime weave
  honouring is F1 (b) (OUT). Tests **may import and call**
  `_render_context` / `_user_text` without editing them.
- **Post-Slice-1 dump contract:**
  1. Router stays zero-churn. Production route dump is exactly
     `envelope.context_pack.model_dump(exclude_none=True)` at
     `describe.py:446` — only `exclude_none=True`.
  2. Keep `test_context_pack._context_pack()` as the **raw / no-voice** input
     fixture (L43–64; uses L69 / L94 / L108 / L134).
  3. Add `test_context_pack._context_pack_dump()` with default voice strings on
     allowlist models only — expected dump at **L139**.

**Norm S1 — Boundary voice survives adapter serialization (F1(a)).**

Build the render input **only** from the production dump path:

```python
dump = DescribeImageEnvelope.model_validate({
    ...,
    "context_pack": {
        "attachment": {
            "caption": "probe-caption-xyz",
            "voice": "creator",
        },
    },
}).context_pack.model_dump(exclude_none=True)
# PYTHON mode only: no mode="json"; production does not set use_enum_values.
```

Do **not** hand-build a dump matching `_context_pack_dump`.

**Why dump equality, not `ast.literal_eval`:** under PYTHON-mode
`model_dump(exclude_none=True)`, a surviving `ContextVoice` StrEnum compares
equal to its value (`StrEnum` value-equality: `ContextVoice.CREATOR == "creator"`
is True). Requiring `ast.literal_eval` of the L85 render line false-REDs a
correct implementation because `str(mapping)` emits
`<ContextVoice.CREATOR: 'creator'>`, which is not a Python literal
(DPR17-H-01 / DPR19-H-06). Use dump-field equality; never re-parse the L85 line
as the permanent green.

**Permanent green 1 — structured dump field:**

```python
assert dump["attachment"]["voice"] == "creator"
# holds for plain-str dump values and surviving StrEnum members;
# do not require isinstance(..., str)
```

**Permanent green 2 — independent expected render line (not the production
formula applied to the dump under test — that is `x == x` / DPR19-R-04):**

For this **fixed fixture only**, pin the expected attachment line as a frozen
literal. Live L85 shape for a nested mapping with surviving StrEnum is:

```text
attachment: "{'caption': 'probe-caption-xyz', 'voice': <ContextVoice.CREATOR: 'creator'>}"
```

```python
_EXPECTED_ATTACHMENT_LINE = (
    "attachment: \"{'caption': 'probe-caption-xyz', "
    "'voice': <ContextVoice.CREATOR: 'creator'>}\""
)
rendered, sources = gpu_remote_adapter._render_context(dump)
attachment_line = next(
    line for line in rendered.split("\n") if line.startswith("attachment:")
)
assert attachment_line == _EXPECTED_ATTACHMENT_LINE
```

The expected string is **independent of** `json.dumps(str(dump['attachment']),
…)` applied to the dump under test. A correct dump with this fixture greens; a
dump whose voice is wrong (or stripped) reds.

**Reachable RED (mandatory — paste in test docstring):** same fixture with
`voice="operator"` (or dump with voice key deleted) →
`attachment_line == _EXPECTED_ATTACHMENT_LINE` fails because the line carries
`ContextVoice.OPERATOR` (or omits voice). Green 1 also fails if voice is
stripped or wrong.

**Discrimination (legitimate shape that must still green):** caption may contain
the substring `creator` while `voice="operator"` — green 1 sees `"operator"`;
green 2 for the creator fixture is a separate case (do not use a raw
`"creator" in rendered` oracle).

**Forbidden weak oracles (not permanent greens):** `"'creator'" in rendered`,
`"creator" in rendered`, `ast.literal_eval` of the L85 line, or
`attachment_line == f"attachment: {json.dumps(str(dump['attachment']), ensure_ascii=False)}"`
(tautology over the dump under test).

Proof:

```bash
cd apps/prototype-description-service
uv run --extra dev pytest scene/tests/test_context_voice_contract.py scene/tests/test_context_pack.py -q
```

**[TEST-15] red-first proofs (Slice 1)**

| Check | Exact red input | Discrimination / cheating impl killed |
|---|---|---|
| Creator never absorbable | `attachment.caption=…`, `voice="creator"` → path absent from absorbable | Same caption with `voice="catalogue"` ∈ absorbable |
| DERIVED only absorbable | `voice="derived"` → ∈ absorbable, ∉ quotable | `voice="creator"` → only quotable. Kills `{CREATOR, DERIVED}`→quotable |
| Independent voice freeze | `{m.value for m in ContextVoice} == _EXPECTED_VOICE_VALUES` in **test** module; identifier absent from impl/domain sources | Hand-add fifth enum member without updating test freeze → red. `set(ContextVoice)` as permanent green is forbidden |
| Partition coverage freeze | test-owned `_EXPECTED_QUOTABLE` / `_EXPECTED_ABSORBABLE` match production membership freezes by **value** | Drop DERIVED from absorbable freeze → red |
| Model-field completeness | `set(Model.model_fields) == _FROZEN_MODEL_FIELDS[name]` for every inventoried model | New field on `AttachmentContext` without freeze/table update → red |
| Content-blind partition | Two creator captions differ only in value → same path sets | Both with `voice="operator"` → absorbable |
| Parametrized IN-row inventory | One case per IN path; expected set is the literal path — never derived from `iter_context_facts` | Caption-only walker fails description/alt_text/excerpt/… |
| Parametrized OUT-row exclusion | **(i) Independent OUT** → expected `set()`; named: filename, post_type, status, sku, price, person_naming, review_reasons. **(ii) Dependent OUT** → expected `{required_IN_path}` and OUT path absent. Five dependent: taxonomy, slug → `{….name}`; identity_id, cluster_id, source → `{….name}` | Emit-every-string walker fails |
| Mixed-pack explicit expected set | All ten IN paths; hand-written frozenset; partitions partition that set | Empty pack → empty |
| Non-attachment creator-default | omit `post.voice` → `post.title` ∈ quotable | Explicit `operator` → absorbable |
| Non-attachment catalogue | default taxonomy → name ∈ absorbable | Override `creator` → quotable |
| ProductContext voice propagates | `fact.voice is pack.product.voice` and partition membership matches | Mapper hardcodes CREATOR while request says catalogue → red |
| IdentityContextItem voice propagates | same boundary equality on item.voice | Mapper forces OPERATOR → red |
| Invalid voice rejected | `voice="archivist"` → ValidationError | `voice="creator"` validates |
| Additive under `extra="forbid"` | Today's pack shape validates; defaults per allowlist; no voice on IdentityPolicyContext | Unknown key still 422 |
| Default fail-closed | omit attachment voice → quotable | Explicit operator → absorbable |
| Dump equality (fixture split) | L139: `adapter.context == _context_pack_dump()`; `_context_pack()` stays voice-free | L94/L108 still use raw fixture |
| Per-model field defaults | `_EXPECTED_VOICE_DEFAULTS` freeze on `model_fields["voice"].default` | Universal CREATOR snippet fails Taxonomy/Identity entries |
| Omit-voice route dump | POST with `_context_pack()`; capture equals `_context_pack_dump()` under real `describe.py:446` flags | `exclude_defaults=True` cheat fails |
| **Boundary voice / Norm S1** | green 1 + green 2 with **independent** `_EXPECTED_ATTACHMENT_LINE` for the probe fixture; reachable RED on wrong/stripped voice | Tautological L85-formula-on-same-dump is forbidden; `ast.literal_eval` forbidden; raw substring co-occurrence forbidden |
| No voice on IdentityPolicyContext | policy dump keys exactly `{person_naming}` | IdentityContextItem dumps voice |

### Slice 2: `DescriptionRegister` on the **request** contract (enforcement deferred; no response echo)

**Goal**: Land FORENSIC / EDITORIAL / INTERPRETIVE on the **request** envelope.
**Do not** add a response field or claim request→response echo.

**Canon**: `ATTRIB-01`, `ATTRIB-03`, card `attribute-claims-to-their-bearer`,
`API-09` (request shape), `API-10`, `REF-29`, `TEST-15`. No `REG-*`.

Changes:

- Add to `scene/domain/description.py`:
  ```python
  class DescriptionRegister(StrEnum):
      FORENSIC = "FORENSIC"
      EDITORIAL = "EDITORIAL"
      INTERPRETIVE = "INTERPRETIVE"
  ```
- On `DescribeImageEnvelope`:
  ```python
  description_register: DescriptionRegister = DescriptionRegister.EDITORIAL
  ```
- **Do not** edit `responses.py`, shared JSON schema, or
  `test_response_schema_parity.py`. Adding a response model field without a
  matching schema property turns
  `test_schema_required_matches_model_fields` red (properties equality).
  Package-absent skip / property-missing xfail are dead code here (schema file
  exists) and must not be introduced.
- **Independent register freeze in tests** (same M-07 pattern; covers exactly
  these three published values — EXIT B on the vocabulary):
  ```python
  _EXPECTED_REGISTER_VALUES: frozenset[str] = frozenset(
      {"FORENSIC", "EDITORIAL", "INTERPRETIVE"}
  )
  assert {m.value for m in DescriptionRegister} == _EXPECTED_REGISTER_VALUES
  assert "_EXPECTED_REGISTER_VALUES" not in Path(
      "scene/domain/description.py"
  ).read_text()
  ```

Proof:

```bash
cd apps/prototype-description-service
uv run --extra dev pytest scene/tests/test_description_register_contract.py -q
uv run --extra dev pytest scene/tests/test_response_schema_parity.py -q
```

**[TEST-15] red-first proofs (Slice 2)**

| Check | Exact red input | Discrimination |
|---|---|---|
| Unknown register rejected | `description_register="LYRICAL"` → ValidationError | Each of three tokens validates |
| Independent freeze | test-owned `_EXPECTED_REGISTER_VALUES` vs enum values | Fourth enum member without freeze update → red |
| Exhaustiveness helper | `assert_register_exhaustive({FORENSIC, EDITORIAL})` raises naming INTERPRETIVE | Full freeze set passes; `set(DescriptionRegister)` alone is not the permanent green |
| Omit on request | default `EDITORIAL` | Explicit FORENSIC overrides |
| No response field claimed | `description_register` not on `VisualFactsResponse` | Request envelope still carries the enum |

### Slice 3: Restrict-only gravity + obligation disposition shape

**Goal**: Contract carries a testable monotone-restrict path **and** a separate
obligation disposition as **schema + report helpers**. Class membership is
operator-supplied, not inferred. **Does not** prevent callers from ignoring the
bool; **does not** close assessment item 9.

**Canon**: `ATTRIB-05` (plight-type / singularity — F3 warrant), `STRAT-11`
(opposed poles; no middle), `API-09`, `TEST-15`. **Not cited:** `ATTRIB-04`,
`BOUND-03` (see Canon warrants). No `RLSE-02`.

Changes:

- Add to `scene/domain/description.py`:
  ```python
  class GravityDisposition(StrEnum):
      RESTRICT = "restrict"
      OBLIGATE_INVENTORY = "obligate_inventory"
  ```
- **`GravityDirective` lives in `requests.py` only** (closed ownership — no
  "or" fork with `context_contract.py`):
  ```python
  class GravityDirective(BaseModel):
      model_config = ConfigDict(extra="forbid")
      disposition: GravityDisposition = GravityDisposition.RESTRICT
      image_class: str | None = Field(default=None, max_length=64)
  ```
- On `DescribeImageEnvelope`:
  ```python
  gravity: GravityDirective = Field(default_factory=GravityDirective)
  ```
- Pure functions in `context_contract.py` only:
  ```python
  _REGISTER_RANK = {
      DescriptionRegister.FORENSIC: 0,
      DescriptionRegister.EDITORIAL: 1,
      DescriptionRegister.INTERPRETIVE: 2,
  }

  def effective_register(
      requested: DescriptionRegister,
      gravity: GravityDirective,
      *,
      restrict_ceiling: DescriptionRegister = DescriptionRegister.EDITORIAL,
  ) -> DescriptionRegister:
      if gravity.disposition is GravityDisposition.OBLIGATE_INVENTORY:
          return requested
      if gravity.disposition is GravityDisposition.RESTRICT:
          return _by_rank(min(_rank(requested), _rank(restrict_ceiling)))
      raise ValueError(f"unhandled GravityDisposition: {gravity.disposition!r}")

  def inventory_obligation(gravity: GravityDirective) -> bool:
      """Report-only bool. No refusal authority over a caller that ignores it."""
      if gravity.disposition is GravityDisposition.OBLIGATE_INVENTORY:
          return True
      if gravity.disposition is GravityDisposition.RESTRICT:
          return False
      raise ValueError(f"unhandled GravityDisposition: {gravity.disposition!r}")
  ```
  Spec under RESTRICT (default ceiling EDITORIAL): exact
  `min(rank(requested), rank(ceiling))` —
  FORENSIC→FORENSIC, EDITORIAL→EDITORIAL, INTERPRETIVE→EDITORIAL.
- **Independent gravity freeze in tests** (exactly two published values —
  EXIT B):
  ```python
  _EXPECTED_GRAVITY_VALUES: frozenset[str] = frozenset(
      {"restrict", "obligate_inventory"}
  )
  assert {m.value for m in GravityDisposition} == _EXPECTED_GRAVITY_VALUES
  ```
- **Do not** ship a hardcoded image-class → disposition map. That map is the
  DEPICT-D1 operator decision memo (**OUT/unowned**). Assessment §2 item 9
  remains **unaddressed**. Callers that need obligation set
  `gravity.disposition=obligate_inventory` **explicitly**; default stays
  `restrict`.

Proof:

```bash
cd apps/prototype-description-service
uv run --extra dev pytest scene/tests/test_gravity_contract.py -q
```

**[TEST-15] red-first proofs (Slice 3)**

| Check | Exact red input | Discrimination |
|---|---|---|
| Exact min under default ceiling | Parametrize (FORENSIC→FORENSIC), (EDITORIAL→EDITORIAL), (INTERPRETIVE→EDITORIAL) under RESTRICT | Custom `restrict_ceiling=FORENSIC` forces EDITORIAL→FORENSIC |
| Rank equality property | Full enum×enum grid under RESTRICT: rank result == min | OBLIGATE excluded |
| Obligation flag reports (not enforces) | `inventory_obligation(OBLIGATE) is True`; register unchanged | RESTRICT → False + INTERPRETIVE clamps. Always-True/False cheats die |
| Independent gravity freeze | test-owned `_EXPECTED_GRAVITY_VALUES` | Third enum member without freeze update → red |
| Exhaustive disposition branches | inject unhandled disposition → both helpers raise with value in message | No silent RESTRICT fall-through / no `is OBLIGATE else False` |
| Invalid disposition rejected | `disposition: "expand"` → ValidationError | Both known tokens validate |
| Additive envelope | omit gravity → default `restrict` | `{image_class: "public_atrocity"}` alone still defaults `restrict` |

#### DEPICT-D1 (F3) — OUT of this wave; assessment item 9 unaddressed

| Item | In this wave? | Owner | Status |
|---|---|---|---|
| Operator memo: which image classes take `restrict` vs `obligate_inventory` | **No** | **Unowned** (no DEPICT-D1 plan; no DEPICT-1 DoD artifact) | Assessment §2 item 9 **unaddressed**. Schema default remains `restrict`. No silent auto-classifier. |

This plan ships dual-pole **shape** and report helpers only. It does **not**
claim to prevent atrocity inventory being silently suppressed in production.

---

## Consolidated Checklist

### Context and Ownership

- [ ] Loaded assessment §2/§5c/§5d/§10g, eval F1/F3, card, owned schemas.
- [ ] Edits limited to Norm C0 closed path set; F1 (a) = this plan; F1 (b) and
      harness voice = OUT/unowned (Norm C1 when F1 (b) owned). DEPICT-0+1+2
      merge does **not** close F1.
- [ ] Cited IDs definition-anchor-verified; no `FM-11`, no `REG-*`, no
      `ATTRIB-04`/`BOUND-03` for F3, no `BOUND-02` for input voice, no
      `RLSE-02` for disposition prose.
- [ ] Additive-only under `extra="forbid"`; API-09 = shape; Greenfield =
      hash/default observability; voice grain = object-level (Objective).

### Slice 1

- [ ] `ContextVoice` + per-model defaults; no voice on IdentityPolicy/IdentityContext.
- [ ] Inventory table + model-field completeness freeze; parametrized IN/OUT.
- [ ] Partition: creator ⊆ quotable; catalogue/operator/derived ⊆ absorbable;
      no silent default; independent test freezes (M-07).
- [ ] Product/Identity boundary→partition voice equality.
- [ ] Fixture split (`_context_pack` / `_context_pack_dump`); Norm S1 greens
      (independent expected line; reachable RED).
- [ ] Pytest: voice + context_pack green; no prompt/adapter source edits.

### Slice 2

- [ ] `DescriptionRegister` request-only default EDITORIAL; independent freeze.
- [ ] No response field; parity file unedited; no register behavioural gate.
- [ ] Pytest: register + baseline parity green.

### Slice 3

- [ ] `GravityDisposition` + `GravityDirective` **in `requests.py`**; helpers in
      `context_contract.py`.
- [ ] Exact min under RESTRICT; report-only `inventory_obligation`; independent
      freeze; exhaustive `else: raise`.
- [ ] No class→disposition map; DEPICT-D1 OUT; item 9 unaddressed.
- [ ] Pytest: gravity green.

## Review Readiness

- [ ] Every new check has [TEST-15] red input + discrimination in this plan.
- [ ] Attack surface pre-empted by Slice tables + Norm C0/C1/S1 (not restated
      here): voice without enforcement; register without freeze; vacuous rank≤;
      atrocity poles averaged in schema; additive vs forbid; response echo
      without wiring; F1 (b) falsely claimed closed; dump-contract fixture split;
      tautological L85 formula (R-04); universal-CREATOR snippet; ATTRIB-07
      overclaim; API-09 used for hash churn; voice on IdentityPolicyContext;
      directory-prefix ownership; field-level voice smuggled as object-level.
- [ ] Cross-lane F1 split recorded; item 9 unaddressed.

## Stretch Goals

- [ ] Optional response echo of register/gravity — only as a future task that
      owns request → service → persistence → response for fresh **and** cached
      paths and updates the shared JSON schema in the same change set.
- [ ] **Per-field voice** (title vs caption) — a **breaking re-grain** relative
      to this task's object-level `voice` (Objective). Do not treat as additive
      under [API-09]. Only after a plan owns the migration of mixed-provenance
      objects.

## Success Criteria

- [ ] Creator-tagged speech-inventory path cannot appear in absorbable
      (attachment + at least `post.title`).
- [ ] DERIVED only absorbable; independent voice freeze covers exactly four
      published values; no silent partition default.
- [ ] ProductContext and IdentityContextItem: boundary `voice` == `fact.voice`.
- [ ] Inventory matches IN/OUT table with one parametrized case per row +
      model-field completeness freeze.
- [ ] Payloads without new keys validate; invalid enum 422; `extra="forbid"`
      preserved; dump equality via `_context_pack_dump` (L139);
      Norm S1 greens with independent expected line and reachable RED;
      per-model defaults; `context_hash` one-time change under Greenfield.
- [ ] `DescriptionRegister` exactly three frozen values; default EDITORIAL; no
      response echo.
- [ ] Gravity restrict = exact min; `inventory_obligation` report-only; no coded
      class table; item 9 unaddressed.
- [ ] No Lane A/C files modified; no `responses.py` / shared-schema / prompt text
      edits; no bound-term fields.
- [ ] Scoped pytest green.
- [ ] F1 (b) not claimed closed (Norm C1 when owned). Harness voice OUT.
      DEPICT-0+1+2 merge does not close F1.

## Not-Doing

- Prompt / weave instruction edits — **F1 (b)**, OUT/unowned. DEPICT-0
  Not-Does F1 weave wording (DEPICT-0 section **Not-Doing**). When F1 (b) is
  later owned: Norm C1 only.
- Response `description_register` field / request→response echo / service or
  cache propagation.
- Shared JSON schema mirror for a response register property.
- Harness `ContextPack` voice mirror and harness F1 voice-honouring —
  OUT/unowned.
- `voice` on `IdentityPolicyContext`.
- Per-field (leaf-string) voice — out of scope; object-level grain only
  (Objective). Mixed-provenance objects unrepresentable until a future
  breaking re-grain.
- Bound-term shape, colour vocabulary, Werner/ISCC–NBS, `FM-11` anything.
- `caption_metrics.py` or any scorer (Lane C).
- v3 three-surface caption split (DEPICT-5 / F4) — **not** claimed unblocked;
  owned paths do not intersect.
- Register behavioural gates.
- Hardcoded image-class → gravity map; DEPICT-D1 operator memo (OUT/unowned;
  assessment item 9 **unaddressed**).
- Roster withhold flag (DEPICT-D2 / F7).
- Race warrant/parity aggregate (DEPICT-S1 / F5).
- Inner-state attribution counter (DEPICT-2 / F8 — Lane C).
- Putting `identity.review_reasons` into the speech partition.
