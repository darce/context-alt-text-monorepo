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
> Canon: heuristics-canon @ `v0.17.0-11-ga238620` (`canon/PROVENANCE.txt`).

## Objective

Land three **additive, closed** contract surfaces on the describe HTTP boundary
before v3 promotion freezes the shape: (1) `voice` on each nested context-pack
model that owns caller-supplied speech fields (explicit allowlist in Slice 1;
`IdentityContext.review_reasons` and `IdentityPolicyContext` are outside the
speech-voice allowlist) with a pack-side partition that marks creator-tagged
speech quotable-only by **operator policy** (see Workflow Principles;
`ATTRIB-07` warrants only the oppressive-string subset), (2)
`DescriptionRegister` (`FORENSIC | EDITORIAL | INTERPRETIVE`) as request-side
vocabulary with enforcement deferred (no response echo in this task), and (3)
a monotone **restrict-only** gravity directive whose schema also carries the
opposed **obligation** disposition so atrocity-class inventory is not averaged
into silent suppression. Each surface ships with [TEST-15] red-first proof.

## Problem Statement

The typed `ContextPack` already forbids unknown keys (`extra="forbid"`) and
bounds every nested string, but it carries **no voice provenance**. CMS-authored
caption/title/taxonomy strings are rendered into the production prompt and the
shipping system prompt (today
`scene/infrastructure/vlm/gpu_remote_adapter.py` `_SYSTEM_PROMPT` L28–37;
post-DEPICT-0 the same v1 body lives in the selected `ProductionPrompt` in
`scene/prompts/caption_system.py`. **Production consumer binding** follows
DEPICT-0 section **Consumers:** (`:457-548`; re-verify after concurrent
DEPICT-0 edits) and FROZEN CONTRACT A: consumers of the **selected config**
obtain it only through the accessor functions (`production_prompt()` /
`production_system_prompt()` / `production_prompt_or_task_version()`); do
**not** bind via `from … import PRODUCTION_PROMPT`, and do **not** introduce a
dedicated frozen body export. The production adapter **snapshots once** at
construction (`self._production_prompt = production_prompt()`;
`self.prompt_or_task_version = self._production_prompt.lineage_version`) and
posts **`self._production_prompt.body`** at describe/payload time — **not** a
second call to `production_system_prompt()` / `production_prompt()` at describe
time, and not a live re-read of module-level `PRODUCTION_PROMPT`. (Temporal
invariant: body and stamp come from the same snapshot object at `__init__`.)
DEPICT-0 also forbids a separate `PRODUCTION_SYSTEM_PROMPT` string global.
That prompt body instructs the model to *weave* names and factual details
*where they fit naturally* — dissolving the seam between creator speech and
the system's unmarked descriptive voice. That is live production exposure of
eval finding F1. When the dissolved speech is **oppressive creator wording**,
it is a direct `ATTRIB-07` hit; the operator also defaults **all**
creator-tagged CMS speech to quotable-only as a conservative policy beyond
that canon trigger (see Workflow Principles).

Separately, the FORENSIC / EDITORIAL / INTERPRETIVE vocabulary is already the
spine of canon's `attribute-claims-to-their-bearer` reasoning card and of every
`ATTRIB`/`BOUND` row that splits voice, but **zero** of those tokens exist in
`scene/` or the describe contract. Retrofitting the enum after call sites
proliferate is a rewrite. A restrict-only gravity flag is the right default for
most sensitive classes and the **wrong** default for public atrocity imagery
(`ATTRIB-04` / `BOUND-03` / `ATTRIB-05`); the contract must carry both poles
partitioned, not a blended middle.

## Constraints

- **File ownership (hard boundary).** This lane edits
  `scene/interface_adapters/http/schemas/requests.py` and co-located schema
  helpers under `scene/interface_adapters/http/schemas/`. Domain `StrEnum`
  vocabularies land in `scene/domain/description.py` (house pattern for
  `DescriptionAdapterKind` et al.; assessment heading
  `### 6e. Dispatch shape — file ownership, not just task ownership` at
  `:351`, Lane B row of `#### §6e ownership table` at `:368` — real path
  ownership of `scene/domain/description.py`).
  Co-owned characterization tests under `scene/tests/`
  (`test_context_pack.py` plus new contract test modules). Do **not** edit
  Lane A paths (`gpu_remote_adapter.py`, `bakeoff.py`, `settings.py`,
  `scene/prompts/caption_system.py`), Lane C paths (`caption_metrics.py`),
  `scene/interface_adapters/http/schemas/responses.py` (no response register
  field in this task — see Target Outcome / Slice 2),
  `packages/shared-contracts/...` (unchanged; verified present at
  `packages/shared-contracts/schemas/image-description-response.schema.json`
  — no response register property to mirror),
  `scene/application/visual_facts_service.py` (no register propagation path
  in this task), or `scripts/eval_harness/manifest.py` (unowned harness
  ContextPack).
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
  omit them still validate. Unknown keys still 422. Stated fully in
  Current State Analysis and Slice 1.
- **Prompt text is out of scope.** The weave-instruction half of F1 has nowhere
  safe to land until DEPICT-0 closes the prompt *seam* (move-only; DEPICT-0
  Not-Doing: "Changing what any prompt **says**" / "Weave-side context
  consumption / F1 voice-honouring prompt behaviour"). The actual
  voice-honouring weave rewrite is **F1 (b) production-weave** — **OUT of this
  wave, unowned** (no plan file delivers it; optional future label "DEPICT-1b"
  only when a plan is authored). Post-DEPICT-0, that future work **REBINDS**
  the module-level `PRODUCTION_PROMPT` to a new
  `ProductionPrompt(body=…, lineage_version=…)` in
  `scene/prompts/caption_system.py` (DEPICT-0: *"A future promotion replaces
  `PRODUCTION_PROMPT` (or rebinds the selected instance)"*). **Never** mutate
  `.body` on the frozen dataclass (`@dataclass(frozen=True)` →
  `FrozenInstanceError`). Production consumers of the selected config still
  obtain it through the accessors (`production_prompt()` /
  `production_system_prompt()` / `production_prompt_or_task_version()`) —
  never via `from … import PRODUCTION_PROMPT`, never via a dedicated frozen
  body export (DEPICT-0 section **Consumers:**, `:457-548`). The
  production adapter continues to post **`self._production_prompt.body`**
  from its construction-time snapshot (no describe-time accessor re-read).
  A module-level REBIND does **not** retroactively change an
  already-constructed adapter that already bound body/stamp at init; only
  **new** adapters that call `production_prompt()` after the rebind observe
  the new `PRODUCTION_PROMPT`. Not the deleted
  `gpu_remote_adapter._SYSTEM_PROMPT` constant and not a separate
  `PRODUCTION_SYSTEM_PROMPT` string global. Do not edit prompt strings here;
  do not attribute the weave edit to DEPICT-0.
- **Bound-term / colour field shape is out of scope.** Assessment §10g removed
  it. `FM-11` is retired canon and must not be cited. Trigger for any colour
  vocabulary is §10e (machine-consumed colour token) — not this task.
- **Enforcement of register gates is deferred.** Land the enum; do not build
  "FORENSIC forbids X" rejection logic beyond vocabulary + exhaustiveness.
- **v3 three-surface `caption` split (F4 / DEPICT-5) is not this task.** The
  register enum unblocks it; note only.
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
  (`canon/lexicons/depiction.md` ATTRIB-07 definition). **No canon warrant —
  operator policy:** treating *every* default creator entry as quotable-only is
  a conservative operator policy chosen for this product; it is defensible but
  is not what ATTRIB-07 alone obliges.
- **Carry opposed poles whole.** Monotone-restrict and atrocity-class obligation
  are both first-class dispositions. Do not average them into one middle mode
  (`STRAT-11`; assessment §2 item 9 / F3; depiction Tensions partitions are
  evidence of the same cut, not a separate lexicon family).
  `inventory_obligation` **reports** that inventory is obligated (returns
  `bool`); the **caller** is responsible for honouring it — the function has
  no refusal authority over a caller that ignores the flag.
- **Red-first for every new check.** Each assertion names the exact failing
  input and a discrimination case that proves non-vacuity ([TEST-15]).
- **One canonical `StrEnum` per vocabulary** (repo `sr-007`). No scattered magic
  strings; exhaustive matching where the code branches on the enum ([REF-29]).

## Terminology

- **`ContextVoice`**: `creator | catalogue | operator | derived` — provenance of
  a context-pack entry's text. Creator-tagged entries are **quotable-only**.
- **Quotable-only**: the partition may *cite* the string (quoted / voice-tagged);
  it must never hand it to the absorbable weave set as unmarked system speech.
- **Absorbable**: catalogue / operator / derived entries eligible for unmarked
  factual weave (subject to existing pixels-win and unaccounted-name rules).
- **`DescriptionRegister`**: `FORENSIC | EDITORIAL | INTERPRETIVE` — assertable
  altitude of the description. FORENSIC = in-frame visibles only; EDITORIAL =
  attributed non-visual / institutional; INTERPRETIVE = explicit bearer reading.
- **Register rank** (for monotone gravity): `FORENSIC < EDITORIAL < INTERPRETIVE`.
  Higher rank asserts more beyond the frame.
- **`GravityDisposition`**: `restrict | obligate_inventory`.
  - `restrict` — may only **narrow** effective register rank (never expand).
  - `obligate_inventory` — public-atrocity / high-salience force class: visible
    inventory (force, body, injury marks) **ought** to remain stateable;
    restriction must not silently demote a named singular record into a
    plight-type or suppress the force inventory (`ATTRIB-04`/`ATTRIB-05`/
    `BOUND-03`). The pure helper `inventory_obligation` **reports** this
    disposition as a bool; the **caller** is responsible for honouring it.
- **Image-class partition**: operator-owned mapping from content class →
  disposition. **Not built in this task** — recorded as DEPICT-D1 decision memo.

## Current State Analysis

- `ContextPack` and all nested models in
  `scene/interface_adapters/http/schemas/requests.py` set
  `model_config = ConfigDict(extra="forbid")` (verified at `ContextPack` L91 and
  every nested model, including `DescribeImageEnvelope` L108).
- **What `extra="forbid"` means for additive fields:**
  - New fields with a default (or `T | None = None`) are accepted when omitted —
    existing callers that send today's payload shape keep validating.
  - New fields that are required *without* a default **break** existing callers
    (ValidationError on missing key). This plan never does that.
  - Callers that send an **unknown** key still 422. Adding fields does not relax
    that. Callers that send an invalid enum value 422.
  - Under greenfield there are no production users, but the regression suite and
    WP fixtures are "existing callers" for test purposes — they must keep green
    without mandatory new keys.
- Nested pack models today: `AttachmentContext`, `PostContext`,
  `TaxonomyTermContext`, `ProductContext`, `IdentityPolicyContext`,
  `IdentityContextItem`, `IdentityContext`. No voice field anywhere.
  Caller-supplied text fields live on those models at
  `requests.py` L11–81 (`title`/`caption`/`description`/`alt_text`/`filename`,
  `post.title`/`excerpt`, `product.name`/`short_description`, taxonomy `name`,
  identity `name`, `review_reasons`). **`IdentityPolicyContext` has exactly one
  field** — `person_naming: str` (`requests.py` L55–60) — which the fact
  inventory marks **OUT**. Do **not** add `voice` to `IdentityPolicyContext`
  (no included-speech field to tag; a voice key there would only churn
  `context_hash`).
- Response contract today: 17 core fields + additive optional preview/fusion/
  long surfaces on `VisualFactsResponse` (see
  `scene/interface_adapters/http/schemas/responses.py` and the shared JSON
  schema path expected by `test_response_schema_parity.py:SCHEMA_PATH` at
  L11–17: monorepo
  `packages/shared-contracts/schemas/image-description-response.schema.json`).
  **That schema file is present in this checkout** (`SCHEMA_PATH.exists()` is
  true; verified ~8413 bytes). **This task does not add
  `description_register` to the response** (no request→response propagation
  path is owned here — verified: `build_visual_facts_envelope` at
  `visual_facts_service.py` L71–83 takes no register parameter and constructs
  `VisualFactsResponse` without one; grep for `description_register` across
  `apps/` returns zero hits).
- Domain enums live in `scene/domain/description.py` with an explicit `sr-007`
  docstring. No `DescriptionRegister`, `ContextVoice`, or gravity enum exists
  (eval F8 verification still holds for register tokens).
- Production weave clause ("Weave the people's names and factual details…") is
  in `gpu_remote_adapter.py` L33–34 today — **Lane A owned**; not editable
  here. DEPICT-0 **moves** that body into
  `scene/prompts/caption_system.py` as the selected `ProductionPrompt.body`
  field on frozen `PRODUCTION_PROMPT` (DEPICT-0 section **Consumers:**, today
  `:457-548`: selected-config consumers bind via the accessor functions; the
  adapter snapshots once at `__init__` and posts `self._production_prompt.body`
  — no describe-time accessor re-read; no `from … import PRODUCTION_PROMPT`
  bind; no dedicated frozen body export; no separate
  `PRODUCTION_SYSTEM_PROMPT` string global — DEPICT-0 Slice 2 / Terminology)
  and deletes the local constant; DEPICT-0 **Not-Does** F1 weave *wording*
  (DEPICT-0 Not-Doing section). **F1 (b) production-weave** (OUT of this wave,
  unowned) later **rebinds** `PRODUCTION_PROMPT` to a new
  `ProductionPrompt(body=<rewritten weave>, lineage_version=…)` — never edits
  `.body` in place on the frozen instance; consumers keep the DEPICT-0
  **Consumers:** bind form (accessors + adapter instance snapshot body).
  A REBIND does **not** rewrite body/stamp already captured on a live adapter
  instance at construction time.
- Defaulted `voice` keys on speech-allowlist nested models enter the normalized
  pack dump (callers that omit `voice` still validate; dumps include defaults)
  and therefore change `context_hash` for otherwise-identical packs. That
  one-time mass invalidation is expected under **Greenfield Policy** (not
  under API-09); no migration.
- Tests present in this checkout that constrain the response contract:
  `scene/tests/test_response_schema_parity.py` (`PREVIEW_FIELDS` L50–56;
  `set(schema["required"]) == set(VisualFactsResponse.model_fields) - PREVIEW_FIELDS`
  at L61; **`set(schema["properties"]) == set(VisualFactsResponse.model_fields)`
  at L63** — adding any model field without a matching shared-schema property
  turns that assertion red). Shared JSON schema path is **present** (see
  SCHEMA_PATH above; verified exists); it currently has **no**
  `description_register` property and DEPICT-1 still does not edit it. Pack
  characterization **is present** at `scene/tests/test_context_pack.py`
  (`_context_pack` defined at L43; used at L69 / L94 / L108 / L134; route
  dump-equality assertion at **L139**:
  `assert adapter.context == _context_pack()` — L137 is blank —
  **the specific assertion default `voice` keys break** when the expected
  dump omits them while the route emits them). Slice 1 owns the fixture split
  for that dump (see Post-Slice-1 dump contract).
- Caption-fact inventory alignment target (fusion neighbour): fusion Stage-2
  `_reconcile_caption_facts` enumerates `product.name`,
  `attachment.title`/`caption`, `post.title`, and each
  `taxonomy_terms[].name`. Slice 1's `iter_context_facts` fixed inventory
  covers that set **plus** the additional IN rows in the inventory table
  (`attachment.description`/`alt_text`, `post.excerpt`,
  `product.short_description`, `identity.identities[i].name`).

## Target Outcome

1. Every nested context-pack model on the speech-field allowlist (Slice 1)
   carries a `voice: ContextVoice` with a fail-closed default; a pure, tested
   partition function over the fixed fact inventory returns disjoint
   absorbable vs quotable-only fact lists, and **creator never appears in
   absorbable**. `IdentityContext.review_reasons` and all OUT inventory rows
   are out of that inventory. **`IdentityPolicyContext` does not get `voice`.**
2. `DescriptionRegister` exists as a single `StrEnum` and is accepted on the
   **request** envelope (default `EDITORIAL`), with an exhaustiveness guard so
   a fourth value cannot land silently. **No response echo and no response
   field** in this task: `build_visual_facts_envelope` /
   cache-row reconstruction are not edited; a request register value is not
   claimed to appear on any response.
3. `GravityDirective` exists on the request envelope with
   `disposition ∈ {restrict, obligate_inventory}` and an optional operator
   `image_class` label; pure functions prove restrict is monotone-non-expanding
   and that `inventory_obligation` **reports** obligation (`True` only for
   `obligate_inventory`) so a caller *can* refuse inventory-suppression —
   the pure function itself only returns a bool; the caller must honour it.
   The class→disposition table is **not** hardcoded — operator memo only.
4. Scoped pytest green; no prompt edits; no metrics edits; no bound-term fields;
   no shared-schema edit; no `responses.py` edit.

## Context Loading

Load before implementing any slice:

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
  plain-text cite only — not vendored in this monorepo)
- Owned code: `scene/interface_adapters/http/schemas/requests.py`,
  `scene/interface_adapters/http/schemas/context_contract.py` (new),
  `scene/domain/description.py`
- Characterization tests: `scene/tests/test_context_pack.py` (present in this
  checkout; dump-equality assert L139), new contract modules under `scene/tests/`

### Canon warrants (definition-anchor verified)

Every ID below was verified with
`grep -rE '^\| *`?<ID><a name' canon/lexicons/` (definition row, not
cross-reference).

| ID | Lexicon | Distilled evidence (Src) | Role in this task |
|---|---|---|---|
| `ATTRIB-07` | `canon/lexicons/depiction.md` (definition L79) | `canon/distilled/accessibility/anti-racist-description-resources.md` (§sec-creator) | **Canon voice warrant for the oppressive-string subset only**: racist/oppressive creator wording must be voice-tagged, never unmarked system speech. Does **not** by itself obligate quotable-only for all CMS strings. |
| `ATTRIB-02` | `depiction.md` | `canon/distilled/depiction/sontag-regarding-the-pain-of-others.md` | **Output** who/by-whom/identity/guilt claims leave FORENSIC unless cited. Not a warrant for the input CMS-string voice field itself; cited only where register altitude of identity claims is discussed. |
| `ATTRIB-01` | `depiction.md` | multi-source (berger / sontag / barthes / azoulay) | Bearer-not-depicted; register vocabulary consumer |
| `ATTRIB-03` | `depiction.md` | multi-source | Non-visible content → EDITORIAL/INTERPRETIVE with bearer |
| `ATTRIB-04` | `depiction.md` | `canon/distilled/depiction/sontag-on-photography.md` | Distress undercoding — inventory, not beauty/suppression |
| `ATTRIB-05` | `depiction.md` | `sontag-regarding-the-pain-of-others.md` + azoulay | Honor source name/withhold/singularity; no plight-type mint |
| `BOUND-03` | `depiction.md` | `canon/distilled/depiction/azoulay-civil-contract-of-photography.md` | Frame (force inventory) before institutional story |
| `API-09` | `canon/lexicons/engineering.md` (definition L497) | `canon/distilled/engineering/restful-web-api-patterns.md` (ch-2) | **Shape only**: don't remove/rename/retype/make-required; additions optional. Explicitly **not** a warrant for observable default/hash changes (changed defaults = breaking under Hyrum's Law). |
| `API-10` | `engineering.md` | same (ch-5) | Interface is its own artifact |
| `REF-29` | `engineering.md` | `canon/distilled/engineering/refactoring-fowler-beck.md` (ch-3 only) | Enum completeness / exhaustiveness |
| `STRAT-11` | `business-marketing.md` | `never-split-the-difference` | Do not average opposed goods — dual-pole gravity (`restrict` vs `obligate_inventory`); depiction Tensions partitions evidence the same cut |
| `TEST-15` | `engineering.md` | `canon/distilled/engineering/modern-software-engineering.md` (ch-8 experimental / TDD red) | Prove the green can go red |

**No canon warrant (explicit):**

- There is **no `REG` family** in any lexicon (assessment §5b). `DescriptionRegister`
  is an operator-reserved design call (LIBSYN-1 / reasoning card vocabulary)
  backed by `ATTRIB-01`/`ATTRIB-03` and the card, **not** by a `REG-xx` row.
  Do not invent `REG-*` IDs. Families `ICON`/`FRAM`/`SEL` also do not exist;
  `HARM-01` does not exist; `FM-11` is retired; `PROV-01` lives in
  `ml-systems.md` (not cited as a load-bearing row for this task).
- **Blanket quotable-only default for all creator-tagged CMS speech** is
  **operator policy**, not an ATTRIB-07 obligation. ATTRIB-07 fires only on
  oppressive creator wording. The product still defaults every CMS-originated
  speech field to `voice=creator` → quotable-only as a conservative fail-closed
  choice; implementers and reviewers must not present that blanket as a canon hit.
- Image-class → disposition mapping has no canon row that lists product classes;
  it is DEPICT-D1 (assessment §2 item 9) — operator decision memo.
- Bound-term / colour shape: deliberately unwarranted for alt text under
  `controlled-vocabulary-caps-hallucination` Side A until §10e fires. Out of scope.
- **"Disposition is real, not prose"** for `GravityDisposition` is assessment
  §2 item 9 / F3 operator design, not a release-gate lexicon row. `RLSE-02`
  (ship past an unresolved gate verdict) is **not** cited — Slice 3 ships a
  pure boolean/schema disposition with no gate.
- **`BOUND-02` is not cited** for the input voice partition. Its definition
  governs *output* that mixes in-frame inventory with craft/motive/staging in
  one unmarked voice (`sontag-on-photography`); it does not warrant CMS input
  provenance tags.
- **Delete over flag / no shims / one-time context_hash change** is repo
  Greenfield Policy (shared formulation with DEPICT-0 Constraints), not a
  lexicon row, and is the warrant for the observable default injection —
  **despite** API-09's Hyrum note, not under API-09.
- **Harness-side `ContextPack` voice mirror** (`scripts/eval_harness/manifest.py`
  `ContextPack` L165–176: `title` / `caption` / `description` only — no
  `voice`) is **OUT of this wave and unowned** — not part of F1 (a) or F1 (b).
  F1 (a) contract traps are **service-unit-only**. F1 (b) production-weave
  (OUT of this wave, unowned) rebinds the shared selected `PRODUCTION_PROMPT`
  (consumers of the selected config still obtain it via accessors; adapters
  post `self._production_prompt.body` from the construction-time snapshot);
  it does **not** deliver harness voice-honouring lockstep. A future named
  lane must claim `manifest.py` voice + fixtures before harness F1 traps exist.
- **Response-side `description_register` echo** is not in this task (no owned
  path from request → `build_visual_facts_envelope` → cache row → response).

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
|---|---|---|---|---|---|
| `POST /scene/describe/multipart` request JSON (`context_pack`) | Lane B (this task) | `ContextPack` + nested models, `extra="forbid"` | Additive `voice` on speech-allowlist nested models (not on `IdentityContext` or `IdentityPolicyContext`); defaults applied server-side | Shape: omit → default; invalid enum → 422 ([API-09]). Observable default keys + `context_hash` change: Greenfield Policy | `test_context_pack.py` + new voice tests (param IN/OUT inventory) |
| `DescribeImageEnvelope` | Lane B | tenant/media/context/context_pack/decorative/tier | Additive defaulted `description_register`, `gravity` | Shape: omit → defaults ([API-09]) | schema unit tests |
| `VisualFactsResponse` | **Unchanged this task** | 17 core + additive optionals | **No** `description_register` field; no echo | n/a — response contract frozen for this lane | Existing `test_response_schema_parity.py` stays green without edit |
| Shared JSON schema `packages/shared-contracts/schemas/image-description-response.schema.json` | **Unchanged this task** (path expected by `test_response_schema_parity.py:SCHEMA_PATH` L11–17; **verified present**; no `description_register` property) | mirrors response model | **No edit** — response field not in DEPICT-1 scope | n/a | Parity baseline not a DEPICT-1 deliverable; do **not** add package-absent skip or property-missing xfail for a field we are not introducing |
| Production system prompt / weave | **F1 (b) — OUT of this wave, unowned** (not DEPICT-0/1/2) | unmarked weave (today `gpu_remote_adapter.py` L33–34; post-DEPICT-0 body lives on frozen selected `PRODUCTION_PROMPT` in `scene/prompts/caption_system.py`; consumers of the selected config bind via accessors; adapter snapshots once and posts `self._production_prompt.body` — DEPICT-0 section **Consumers:** `:457-548`) | Must honour quotable-only partition on the **service** pack path (REBIND `PRODUCTION_PROMPT`; never mutate frozen `.body`; rebind does not rewrite already-constructed adapters) | Cross-lane / future | Not in this task; DEPICT-0 only moves prompts; harness pack `voice` remains OUT/unowned; merging DEPICT-0+1+2 does **not** close F1 |
| Eval harness metrics | Lane C | no register/voice axes | future register-compliance arm | Cross-lane | Not in this task |

## Proposed Solution

Three reviewable slices, each behaviour + proof:

1. **Voice vocabulary + pack partition** — `ContextVoice` StrEnum; `voice` on
   speech-allowlist nested models with fail-closed defaults (**not** on
   `IdentityPolicyContext` or `IdentityContext`); fixed fact inventory; pure
   `partition_context_pack` that never places `creator` in absorbable and
   places `derived` only in absorbable; frozen `_VOICE_CONTRACT_VALUES` /
   `_ABSORBABLE_VOICES` / `_QUOTABLE_ONLY_VOICES` with no silent default
   branch; **parametrized one-case-per-IN-row and one-case-per-OUT-row** tests
   against an explicit expected path set (never against `iter_context_facts`
   output); content-blind + dump contract for default voices.
2. **Register vocabulary (request only)** — `DescriptionRegister` StrEnum;
   request default `EDITORIAL`; frozen contract-set exhaustiveness; **no**
   response field, **no** shared-schema edit, **no** PREVIEW_FIELDS change,
   **no** behavioural gate.
3. **Gravity directive** — `GravityDisposition` + `GravityDirective` model;
   pure `effective_register` as exact `min(rank(requested), rank(ceiling))`
   under `restrict` and `inventory_obligation` (bool report) under
   `obligate_inventory`; exact-table tests for both poles; operator memo for
   class partition recorded, not coded.

## Files and Surfaces to Change

| Surface | File | Change |
|---|---|---|
| domain enums | `scene/domain/description.py` | Add `ContextVoice`, `DescriptionRegister`, `GravityDisposition` StrEnums (`sr-007`) |
| request contract | `scene/interface_adapters/http/schemas/requests.py` | `voice` on speech-allowlist nested models only; `description_register` + `gravity` on `DescribeImageEnvelope` |
| schema helpers (new) | `scene/interface_adapters/http/schemas/context_contract.py` | Pure `partition_context_pack`, `effective_register`, `inventory_obligation` (+ small fact dataclass); fixed fact inventory |
| tests | `scene/tests/test_context_voice_contract.py` (new) | Voice partition + extra-forbid + defaults + **parametrized IN/OUT inventory against explicit expected paths** |
| tests | `scene/tests/test_description_register_contract.py` (new) | Register enum + frozen expected-set exhaustiveness + request default/reject (no response echo) |
| tests | `scene/tests/test_gravity_contract.py` (new) | Exact min(requested, ceiling) + obligate_inventory discrimination |
| tests | `scene/tests/test_context_pack.py` | Keep `_context_pack()` voice-free for raw-dict paths; add `_context_pack_dump()` with default `voice` keys for L139 dump-equality only |

**Not edited by this lane (owned elsewhere, unowned, or withdrawn from scope):**

| Surface | File | Status |
|---|---|---|
| response contract | `scene/interface_adapters/http/schemas/responses.py` | **No edit** — response `description_register` / echo withdrawn (no owned propagation path). |
| shared JSON schema | `packages/shared-contracts/schemas/image-description-response.schema.json` | **No edit** — no response property to mirror; path **verified present** (see `SCHEMA_PATH` L11–17); leave unchanged. |
| response parity tests | `scene/tests/test_response_schema_parity.py` | **No edit** — `PREVIEW_FIELDS` / properties equality stay as-is without a new model field. Do **not** introduce package-absent skip or property-missing xfail as a DEPICT-1 deliverable (DEPICT-1 adds no response field; schema file exists — those skip/xfail branches would be dead code). |
| production weave prompt body (post-DEPICT-0) | `scene/prompts/caption_system.py` | **F1 (b) production-weave — OUT of this wave, unowned.** Prerequisites when owned later: DEPICT-0 then DEPICT-1. Mutation is REBIND-ONLY of `PRODUCTION_PROMPT`. |
| production adapter render helpers | `scene/infrastructure/vlm/gpu_remote_adapter.py` (`_render_context` / `_user_text`) | **F1 (b) — unowned future work** may still edit render helpers to voice-tag creator entries; system *wording* lives in caption_system after DEPICT-0. |
| visual facts service | `scene/application/visual_facts_service.py` | **No edit** — no register threading into envelope / cache. |
| harness ContextPack | `scripts/eval_harness/manifest.py` | **Unowned** — F1 traps are service-unit-only in DEPICT-1. |

## Related Files

| File | Note |
|---|---|
| `scene/interface_adapters/http/routers/describe.py` | Pack dump already includes non-None defaults. **Router churn stays zero** for voice defaults. Do **not** switch to `exclude_defaults=True`. No register echo wiring. |
| `scene/application/visual_facts_service.py` | `build_visual_facts_envelope` L71–83 — no register parameter today; **not edited**. Confirms why response echo is out of scope. |
| `scene/application/fusion/reconcile.py` | Neighbour provenance (`FactSource`). Caption-fact paths are the inventory alignment *floor*; Slice 1 inventory is the full IN/OUT table. Do not overload with `ContextVoice`. |
| `scene/application/hashing.py` | Defaulted `voice` keys change the hash once for all packs. Acceptable under **Greenfield Policy** (not under API-09); no migration. |
| `scene/infrastructure/vlm/gpu_remote_adapter.py` | Today: `_SYSTEM_PROMPT` L28–37 + weave L33–34; production serialization path `_render_context` L73–87 / `_user_text` L90–101 / `_describe` L176–182. Post-DEPICT-0: local constant deleted; body lives in `caption_system.py`; adapter **snapshots once** at `__init__` via `production_prompt()` and posts `self._production_prompt.body` (DEPICT-0 section **Consumers:** `:457-548` — not a describe-time `production_system_prompt()` re-read; not the accessor-definition block at DEPICT-0 `:406-436`, which itself reads `.body` inside the accessor). F1 (b) weave is OUT of this wave / unowned. |
| `scene/prompts/caption_system.py` | **Created by DEPICT-0.** Post-seam home of selected frozen `PRODUCTION_PROMPT` (`body` + `lineage_version`) and accessors `production_prompt()` / `production_system_prompt()` / `production_prompt_or_task_version()`. **Consumer bind rule** (DEPICT-0 section **Consumers:** `:457-548`): only permitted binding form for production consumers **of the selected config** is the accessor functions; do **not** read `PRODUCTION_PROMPT.body` / `.lineage_version` at the call site **via `from … import PRODUCTION_PROMPT`**, and do **not** introduce a dedicated frozen body export. The adapter posts `self._production_prompt.body` off its construction-time snapshot (required; not a call-site module bind). **Mutation rule:** REBIND-ONLY — replace `PRODUCTION_PROMPT` with a new `ProductionPrompt(body=…, lineage_version=…)`; never assign to `.body` on the frozen instance (`FrozenInstanceError`). A rebind is **not** retroactive on already-constructed adapters that bound body/stamp earlier. No separate `PRODUCTION_SYSTEM_PROMPT` string global. |
| `scripts/eval_harness/bakeoff.py` | Lane A / DEPICT-0 — harness prompt seam. After DEPICT-0, bakeoff v1 system text is resolved through `production_system_prompt()` (or `production_prompt().body`) **at `PROMPT_VARIANTS` construction time** (`bakeoff.py:138-141`; read-back at `:595` is `variant = PROMPT_VARIANTS[...]` then the stored `variant.system` / `variant.system_long` — **not** a live use-site accessor re-read). Not `from … import PRODUCTION_PROMPT` (DEPICT-0 `## Proposed Solution` → **Consumers:** `:457-548`, and **Parity temporal scope (committed option (a))** under that Consumers block + under `### Slice 1: Single prompt source + non-vacuous parity test`). A future F1 (b) rebind of `PRODUCTION_PROMPT` is visible to bakeoff v1 **only** via a rebuilt registry or a fresh process import — it does **not** rewrite an already-built / already-imported `PROMPT_VARIANTS["v1"].system` string. Full harness F1 voice-honouring is **OUT / unowned** (no harness pack `voice`). |
| `scripts/eval_harness/caption_metrics.py` | Lane C — scorers. |
| `scripts/eval_harness/manifest.py` | Separate flat harness `ContextPack` (`extra="allow"`; fields `title`/`caption`/`description` only at L165–176 — **no** `voice`). **OUT of this wave and unowned** — not F1 (a), not F1 (b); not mirrored here. |
| Reasoning card `attribute-claims-to-their-bearer` (canon, not vendored) | Design warrant for register vocabulary — cite as plain text, do not markdown-link into `canon/`. |

## Cross-lane dependency

### F1 ownership split (this wave vs OUT)

Eval finding F1 has **two halves**. Merging DEPICT-0 + DEPICT-1 + DEPICT-2
**does not close F1**. There is no `DEPICT-1b` plan file under
`docs/tasks/depiction/` in this wave.

| Half | Scope | In this wave? | Owner | Acceptance criteria (named) |
|---|---|---|---|---|
| **F1 (a) — service/contract** | `voice` on speech-allowlist nested pack models; `iter_context_facts` + `partition_context_pack`; creator never absorbable; Product/Identity voice value propagates boundary→partition; register + gravity contract | **Yes** | **DEPICT-1** (this plan) | Slice 1–3 success criteria green; scoped pytest green; no prompt wording change required |
| **F1 (b) — production-weave** | Stop unmarked weave of creator-tagged fields in the **shared** production system prompt; render creator entries as quoted/voice-tagged on the **service** pack path; wire partition (or honour it) into adapter render | **No — OUT of this wave** | **Unowned** (no plan file; optional future label "DEPICT-1b" only when authored) | (1) Module-level `PRODUCTION_PROMPT` is **rebound** to a new `ProductionPrompt(body=<voice-honouring text>, lineage_version=…)` — **never** in-place `.body = …` on the frozen dataclass (rebind is not retroactive on already-constructed adapters); (2) production adapter still **snapshots once** at `__init__` via `production_prompt()` and posts **`self._production_prompt.body`** at describe/payload time — **no** describe-time call to `production_system_prompt()` / `production_prompt()`, and no `from … import PRODUCTION_PROMPT` bind (DEPICT-0 section **Consumers:** / temporal invariant, `:457-548`); (3) a service-path test with `voice=creator` proves the model is not instructed to absorb creator speech unmarked; (4) DEPICT-0 seam + DEPICT-1 Slice 1 are prerequisites |
| **Harness `ContextPack.voice`** | `scripts/eval_harness/manifest.py` `ContextPack` (L165–176: `title`/`caption`/`description` only today) | **No — OUT of this wave** | **Unowned** (neither F1 (a) nor F1 (b)) | Future lane adds `voice` + creator-trap fixtures; not delivered by DEPICT-0/1/2 or by F1 (b) wording rebind alone |

**Prerequisite ordering (explicit):**

1. **DEPICT-0** lands first — creates `scene/prompts/caption_system.py`, moves
   production v1 system body out of `gpu_remote_adapter._SYSTEM_PROMPT`, keeps
   wording identical. DEPICT-0 **Not-Does** F1 weave rewrite (section
   **Not-Doing**: "Changing what any prompt **says**" and "Weave-side context
   consumption / F1 voice-honouring prompt behaviour").
2. **DEPICT-1** (this plan) lands **F1 (a)** only — request-side
   voice/register/gravity contract and pure partition helpers. Does **not**
   edit prompt text or wire partition into production.
3. **F1 (b) production-weave** remains **OUT of this wave and unowned** after
   DEPICT-0 + DEPICT-1. When a future plan owns it, mutation is **REBIND-ONLY**
   of `PRODUCTION_PROMPT` (DEPICT-0: *"A future promotion replaces
   `PRODUCTION_PROMPT` (or rebinds the selected instance) with a new
   `ProductionPrompt(body=…, lineage_version=…)"`*) — **not**
   `PRODUCTION_PROMPT.body = …` (`@dataclass(frozen=True)` raises
   `FrozenInstanceError`), **not** a freestanding `PRODUCTION_SYSTEM_PROMPT`
   string global, and **not** an import-time `from … import PRODUCTION_PROMPT`
   bind at the consumer call site. Adapters continue to post
   `self._production_prompt.body` from the construction-time snapshot
   (DEPICT-0 section **Consumers:** / temporal invariant). Harness pack
   `voice` / bakeoff F1 traps remain separately **unowned**.

| Dependency | Exact file | Exact change needed | Owner / sequencing |
|---|---|---|---|
| Prompt seam (no wording) | `gpu_remote_adapter.py`, `bakeoff.py`, `scene/prompts/caption_system.py` (new) | Single source for production system prompt text; delete local `_SYSTEM_PROMPT`; consumers of the selected config bind via the accessor functions; adapter snapshots once at `__init__` and posts `self._production_prompt.body` (DEPICT-0 section **Consumers:** `:457-548` — no describe-time accessor re-read; no `from … import PRODUCTION_PROMPT` bind; DEPICT-0 `:406-436` is the accessor *definition* that itself reads `.body`, not the consumer prohibition) | **DEPICT-0 / Lane A** — lands **first**; Not-Does F1 weave rewrite (DEPICT-0 §Not-Doing) |
| **F1 (a) — service/contract voice partition** | `requests.py`, `context_contract.py`, `description.py`, voice contract tests | `voice` field + partition; boundary→partition value proofs for Product and Identity | **DEPICT-1** (this plan) — **this wave** |
| **F1 (b) — production voice-honouring weave** | **Primary:** `scene/prompts/caption_system.py` — **REBIND** module-level `PRODUCTION_PROMPT` to a new `ProductionPrompt(body=…, lineage_version=…)` (DEPICT-0 atomic config; frozen dataclass — **never** mutate `.body` in place; rebind does **not** rewrite already-constructed adapters). Consumers of the selected config keep the DEPICT-0 **Consumers:** form (accessors at call time; adapter posts `self._production_prompt.body` from its construction-time snapshot — no describe-time `production_system_prompt()` re-read; no `from … import PRODUCTION_PROMPT`). **Secondary (if render must voice-tag):** `scene/infrastructure/vlm/gpu_remote_adapter.py` (`_render_context` L73–87 / `_user_text` L90–101) | Stop instructing unmarked weave of creator-tagged fields in the **shared** system prompt body; render creator entries as quoted/voice-tagged only; consume pack `voice` from the **service** normalized context dict; call `partition_context_pack` (or honour its partition). **Do not** retarget at `gpu_remote_adapter._SYSTEM_PROMPT` — DEPICT-0 deletes that constant. **Do not** invent a freestanding `PRODUCTION_SYSTEM_PROMPT` body global. **Do not** `PRODUCTION_PROMPT.body = …` (FrozenInstanceError). | **OUT of this wave — unowned.** Prerequisites when owned later: (1) DEPICT-0 seam merged, (2) DEPICT-1 Slice 1 contract merged. After DEPICT-0+1+2 alone, `partition_context_pack` is pure/unwired and production still weaves unmarked creator fields — **F1 is not closed**. |
| Shared prompt body consumed by bakeoff v1 | `scripts/eval_harness/bakeoff.py` (`PROMPT_VARIANTS["v1"].system` after DEPICT-0 parity; construction at `bakeoff.py:138-141`, read-back at `:595`) | After DEPICT-0, bakeoff v1 system text is resolved via `production_system_prompt()` (or `production_prompt().body`) **when `PROMPT_VARIANTS` is built** — not a use-site accessor call inside `_system_prompt` (DEPICT-0 `## Proposed Solution` → **Consumers:** `:457-548` and **Parity temporal scope (committed option (a))** — no `from … import PRODUCTION_PROMPT`). A future F1 (b) rebind of `PRODUCTION_PROMPT` changes bakeoff system wording **only for a rebuilt registry or a fresh process import**; it does **not** mutate an already-imported harness's stored `PROMPT_VARIANTS["v1"].system`. That is **same-construction-epoch wording lockstep only** — not full harness F1 voice-honouring (no pack `voice`, no creator-trap fixtures). | **Wording side-effect of a future F1 (b) rebind** under same-construction-epoch (via DEPICT-0 seam). **Not** harness voice-honouring; harness half remains unowned. |
| Shared JSON schema mirror | `packages/shared-contracts/schemas/image-description-response.schema.json` | **No change required by DEPICT-1** (response register field withdrawn) | n/a this task |
| Register-compliance metric | `scripts/eval_harness/caption_metrics.py` | Future scored arm for register violations | Lane C — unblocked by Slice 2 vocabulary, not planned here |
| v3 caption split (DEPICT-5) | harness + future output schema | Split grounded inventory vs attributed span | Unblocked by Slice 2; **not planned** in DEPICT-1 |
| Harness ContextPack `voice` + bakeoff F1 traps | `scripts/eval_harness/manifest.py` (`ContextPack` L165–176: `title` / `caption` / `description` only; no `voice`) | Would need a `voice` field + creator-trap fixtures for bakeoff-side F1 traps; render helpers would need to consume it | **OUT of this wave — unowned.** Not F1 (a); not F1 (b). DEPICT-1 F1 (a) traps are **service-unit-only**. A future F1 (b) rebind may change bakeoff's system string without a harness `voice` mirror — that is **not** harness F1 voice-honouring. |

## Verification Strategy

- Deterministic tests (from `apps/prototype-description-service/`):
  - `uv run --extra dev pytest scene/tests/test_context_voice_contract.py scene/tests/test_description_register_contract.py scene/tests/test_gravity_contract.py -q`
  - `uv run --extra dev pytest scene/tests/test_context_pack.py -q`
  - Unchanged baseline (no DEPICT-1 edit expected):
    `uv run --extra dev pytest scene/tests/test_response_schema_parity.py -q`
- Contract/fixture verification:
  - Old fixture payloads without `voice` / `description_register` / `gravity` still
    `model_validate` successfully; post-validate dump of pack includes default
    `voice` keys on allowlist models only (keep `test_context_pack._context_pack`
    voice-free; add `test_context_pack._context_pack_dump` for expected dumps).
  - Invalid enum values raise `ValidationError`.
  - Response model / shared schema path / `PREVIEW_FIELDS` **unchanged** (schema
    file verified present; do not invent package-absent skips — they would be
    dead code).
  - Defaulted `voice` keys change `context_hash` once for all packs
    (**Greenfield Policy**, not API-09; no migration).
- Manual verification: none required for this contract-only task.
- **Out of verification for this task:** production weave still instructs
  unmarked weave until **F1 (b)** is owned and lands (OUT of this wave);
  F1 is **not** closed by DEPICT-0+1+2 alone; request `description_register`
  is not present on any response; harness `ContextPack.voice` remains OUT.

---

## Slice Delivery

### Slice 1: `ContextVoice` on speech-bearing pack models + quotable-only partition

**Goal**: Creator-tagged context is structurally partitioned out of the
absorbable set, with schema defaults that keep existing callers valid and a
fixed fact inventory so a caption-only implementation cannot pass.

**Canon**: `ATTRIB-07` (oppressive creator-string subset only), `API-09`
(shape only), `TEST-15`
(evidence: `anti-racist-description-resources.md` §sec-creator;
`restful-web-api-patterns.md` ch-2; `modern-software-engineering.md`).
**Operator policy (no canon warrant):** blanket default `voice=creator` →
quotable-only for all CMS speech fields. `ATTRIB-02` is **not** a warrant for
the input voice field (output who/by-whom only). `BOUND-02` is **not** cited
here (output craft/staging mix, not CMS provenance).

Changes:

- Add to `scene/domain/description.py`:
  ```python
  class ContextVoice(StrEnum):
      CREATOR = "creator"
      CATALOGUE = "catalogue"
      OPERATOR = "operator"
      DERIVED = "derived"
  ```
- On each nested pack model in the **voice-field allowlist** below, add:
  ```python
  voice: ContextVoice = ContextVoice.CREATOR  # fail-closed default
  ```
  Defaults by model:
  - `AttachmentContext`, `PostContext`, `ProductContext` → `CREATOR`
  - `TaxonomyTermContext` → `CATALOGUE`
  - `IdentityContextItem` → `OPERATOR`
    (roster names are operator-confirmed, not creator folder-title speech).
- **`IdentityPolicyContext` does not get a `voice` field.** Its only field is
  `person_naming` (`requests.py` L55–60), which is **OUT** of the fact
  inventory. Adding `voice` there cannot influence any partition and would
  only churn the normalized payload / `context_hash`. Add voice to this model
  only if it later gains an included-speech field.
- **`IdentityContext` itself does not get a `voice` field.** Its
  `review_reasons: list[str]` (`requests.py` L81) is **operator metadata
  outside the speech partition** — not creator/catalogue speech for weave.
  Objective / Success Criteria cover the allowlist, not "every string on the
  pack."
- Add `scene/interface_adapters/http/schemas/context_contract.py`:
  - `@dataclass(frozen=True) class ContextFact` with
    `path: str`, `value: str`, `voice: ContextVoice`
  - `def iter_context_facts(pack: ContextPack) -> list[ContextFact]`
  - **Frozen voice contract + absorbable set** (same freeze pattern as
    `_REGISTER_CONTRACT_VALUES` — **literal enumeration, NOT**
    `set(ContextVoice)` / not derived from the enum at call time):
    ```python
    # Permanent freeze — not derived from the enum at call time.
    _VOICE_CONTRACT_VALUES: frozenset[ContextVoice] = frozenset({
        ContextVoice.CREATOR,
        ContextVoice.CATALOGUE,
        ContextVoice.OPERATOR,
        ContextVoice.DERIVED,
    })
    # Partition membership freezes — literal, not set(ContextVoice) - {CREATOR}.
    _QUOTABLE_ONLY_VOICES: frozenset[ContextVoice] = frozenset({
        ContextVoice.CREATOR,
    })
    _ABSORBABLE_VOICES: frozenset[ContextVoice] = frozenset({
        ContextVoice.CATALOGUE,
        ContextVoice.OPERATOR,
        ContextVoice.DERIVED,
    })

    def assert_voice_contract() -> None:
        """REF-29 permanent guard: enum membership equals the frozen contract set;
        quotable ∪ absorbable partitions the contract with no overlap."""
        actual = set(ContextVoice)
        if actual != set(_VOICE_CONTRACT_VALUES):
            raise AssertionError(
                f"ContextVoice drifted from contract: "
                f"extra={actual - set(_VOICE_CONTRACT_VALUES)} "
                f"missing={set(_VOICE_CONTRACT_VALUES) - actual}"
            )
        if _QUOTABLE_ONLY_VOICES & _ABSORBABLE_VOICES:
            raise AssertionError("voice partition overlap")
        if _QUOTABLE_ONLY_VOICES | _ABSORBABLE_VOICES != _VOICE_CONTRACT_VALUES:
            raise AssertionError("voice partition does not cover contract")
    ```
  - `def partition_context_pack(pack: ContextPack) -> tuple[list[ContextFact], list[ContextFact]]`
    returning `(absorbable, quotable_only)` with **no silent default branch**:
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
                # Future ContextVoice values cannot silently take a default.
                raise ValueError(f"unhandled ContextVoice: {fact.voice!r}")
        return absorbable, quotable_only
    ```
    Membership rules (must match the freezes above):
    `voice is ContextVoice.CREATOR` ⇒ **only** quotable_only;
    `catalogue | operator | derived` ⇒ absorbable.
    **Forbidden cheating shapes:**
    `return quotable if voice in {CREATOR, DERIVED} else absorbable` (mishandles
    DERIVED; killed by the DERIVED fixture below);
    `return quotable if voice is CREATOR else absorbable` with no freeze (future
    enum values silently absorb; killed by `assert_voice_contract` + the
    explicit `else: raise` arm exercised via the named seam below).
    **`else: raise` exercise seam (named — not a free `SimpleNamespace`):**
    use `monkeypatch.setattr` on `context_contract.iter_context_facts` to return
    a one-element list whose `ContextFact.voice` is a **locally-defined
    unhandled `ContextVoice`-shaped member** (e.g. a test-local `StrEnum`
    member or `enum.Enum` value whose `value` is a string outside
    `_VOICE_CONTRACT_VALUES`, assigned onto a real `ContextFact` path/value so
    the IN-path inventory shape is preserved). Call
    `partition_context_pack` on any valid pack; assert it raises `ValueError`
    whose **message contains the offending voice value** (the plan's
    `f"unhandled ContextVoice: {fact.voice!r}"` form, or equivalent that
    includes `repr`/`str` of the synthetic member). **Red if** a bare
    `raise ValueError` / `raise AssertionError` without the offending value
    can be swapped in later, or if the proof only constructs a freestanding
    object that never flows through `iter_context_facts` → partition.
  - Partition invariant (tests): the two lists are disjoint by `path`.
  - **Inventory proof invariant (tests — non-tautological):** for every
    fixture, assert
    `set(f.path for f in iter_context_facts(pack)) == EXPECTED_PATHS`
    where `EXPECTED_PATHS` is an **explicit set derived from the fixture
    inputs** (the IN rows that were populated with non-empty strings) —
    **never** `== set(f.path for f in iter_context_facts(pack))` against
    itself, and never "union of partitions equals `iter_context_facts`" as the
    sole inventory proof (that holds for any implementation of partition over
    whatever `iter_context_facts` emits).

#### Fixed fact inventory for `iter_context_facts`

Only non-empty string values become `ContextFact`s. Path templates (dot /
index form) and inclusion:

| Path template | Source model field | In inventory? | Rationale |
|---|---|---|---|
| `attachment.title` | `AttachmentContext.title` | **IN** | free-text speech; reconcile caption-facts floor |
| `attachment.caption` | `AttachmentContext.caption` | **IN** | free-text speech; reconcile floor |
| `attachment.description` | `AttachmentContext.description` | **IN** | free-text prose speech (`requests.py` L18) |
| `attachment.alt_text` | `AttachmentContext.alt_text` | **IN** | free-text prose speech (`requests.py` L19) |
| `attachment.filename` | `AttachmentContext.filename` | **OUT** | opaque file token, not descriptive speech |
| `post.title` | `PostContext.title` | **IN** | free-text speech; reconcile floor |
| `post.excerpt` | `PostContext.excerpt` | **IN** | free-text prose speech (`requests.py` L29) |
| `post.post_type` | `PostContext.post_type` | **OUT** | structural enum-like tag |
| `post.status` | `PostContext.status` | **OUT** | structural enum-like tag |
| `product.name` | `ProductContext.name` | **IN** | free-text speech; reconcile floor |
| `product.short_description` | `ProductContext.short_description` | **IN** | free-text prose speech (`requests.py` L52) |
| `product.sku` | `ProductContext.sku` | **OUT** | identifier token |
| `product.price` | `ProductContext.price` | **OUT** | commerce token |
| `taxonomy_terms[{i}].name` | `TaxonomyTermContext.name` | **IN** | free-text label speech; reconcile floor |
| `taxonomy_terms[{i}].taxonomy` | `TaxonomyTermContext.taxonomy` | **OUT** | taxonomy id, not label speech |
| `taxonomy_terms[{i}].slug` | `TaxonomyTermContext.slug` | **OUT** | slug token |
| `identity.identities[{i}].name` | `IdentityContextItem.name` | **IN** | roster speech (`requests.py` L68) |
| `identity.identities[{i}].identity_id` / `cluster_id` / `source` | ids | **OUT** | opaque ids |
| `identity.policy.person_naming` | `IdentityPolicyContext.person_naming` | **OUT** | policy token only field on that model (`requests.py` L55–60); not free-text speech |
| `identity.review_reasons[{i}]` | `IdentityContext.review_reasons` | **OUT** | operator metadata; not speech partition |

Voice for each emitted fact is taken from the owning nested model’s `voice`
field (`IdentityContextItem.voice` for identity names; attachment/post/product/
taxonomy model `voice` for their fields). An implementation that iterates only
a subset of IN paths **fails** the parametrized IN-row cases below.

- Do **not** edit `gpu_remote_adapter.py` or `scene/prompts/caption_system.py`.
  Runtime weave honouring is **F1 (b)** (OUT of this wave, unowned), not this
  slice. Tests **may import and call** production pure helpers
  (`gpu_remote_adapter._render_context` / `_user_text`) without editing them.
- **Post-Slice-1 dump contract** (prescribed fixture split — not left to
  implementer choice; `_context_pack` today is defined at
  `test_context_pack.py` L43 and used at L69 / L94 / L108 / **L134**):
  1. Router stays zero-churn (no new dump flags). Production route dump is
     exactly `envelope.context_pack.model_dump(exclude_none=True)` at
     `scene/interface_adapters/http/routers/describe.py:446` — **only**
     `exclude_none=True`; **do not** switch to `exclude_defaults=True` or
     `exclude_unset=True`.
  2. Pack dump continues to emit default `voice` keys on allowlist models
     under those real route flags.
  3. **Fixture split (mandatory symbols):**
     - Keep `test_context_pack._context_pack()` as the **raw / no-voice**
       input fixture (today's body at L43–64). Used by validate input (L69),
       seeded-adapter raw-dict (L94), service raw-dict (L108), and the route
       POST body (L134). **Do not** add default `voice` keys to this helper.
     - Add `test_context_pack._context_pack_dump()` as a separate helper
       carrying the documented default voices on each **allowlist** nested
       object (`AttachmentContext`/`PostContext`/`ProductContext` →
       `"creator"`; `TaxonomyTermContext` → `"catalogue"`;
       `IdentityContextItem` when present → `"operator"` — **not** on
       `IdentityPolicyContext` / `IdentityContext`). Used **only** as the
       expected dump at **L139**
       (`assert adapter.context == _context_pack_dump()`; L137 is blank)
       and any other dump-equality site. **Item 3 and item 4 are no longer
       mutually unprovable:** after this split, L139 compares against
       `_context_pack_dump`, while raw-dict paths still receive
       `_context_pack` without voice keys.
  4. Raw-dict seeded-adapter / service paths (no Pydantic validate → no
     default injection) keep working without `voice` keys because they still
     call `_context_pack()` — proved by L94 / L108 remaining on that
     symbol. Do not force voice into that raw-dict path.
- Tests in `scene/tests/test_context_voice_contract.py` (and extend
  `test_context_pack.py` with the fixture split above).

Proof:

```bash
cd apps/prototype-description-service
uv run --extra dev pytest scene/tests/test_context_voice_contract.py scene/tests/test_context_pack.py -q
```

**[TEST-15] red-first proofs (Slice 1)**

| Check | Exact red input | Discrimination (non-vacuous green) / cheating impl killed |
|---|---|---|
| Creator never absorbable (attachment) | Pack with `attachment.caption="folder title from donor notes"` and `attachment.voice="creator"`. Assert: path `attachment.caption` is **absent** from `partition_context_pack(pack)[0]` (absorbable). **Red if** the partition puts it in absorbable or if the function ignores `voice`. | Same caption with `voice="catalogue"` (or `operator`) **is** present in absorbable and absent from quotable_only. |
| **DERIVED only absorbable** | Pack with `attachment.caption="derived catalogue expansion"` and `attachment.voice="derived"`. Assert: path `attachment.caption` is **present** in absorbable and **absent** from quotable_only. **Red if** DERIVED is treated as quotable-only (e.g. `voice in {CREATOR, DERIVED}` → quotable) or ignored / dropped. | Same caption with `voice="creator"` is present only in quotable_only. **Cheating impl killed:** `def partition(...): return quotable if voice in {CREATOR, DERIVED} else absorbable` fails this case while still passing creator/catalogue/operator-only fixtures. |
| **Frozen voice contract + exhaustive partition** | Permanently assert `set(ContextVoice) == set(_VOICE_CONTRACT_VALUES)` and `_QUOTABLE_ONLY_VOICES \| _ABSORBABLE_VOICES == _VOICE_CONTRACT_VALUES` with empty intersection (via `assert_voice_contract()`). **Red if** a fifth `ContextVoice` lands without updating the freezes, or if DERIVED is dropped from `_ABSORBABLE_VOICES`. | Hand-edit `_ABSORBABLE_VOICES` to drop `DERIVED` while enum still has four → `assert_voice_contract` fails (partition no longer covers contract). **`else: raise` arm seam:** `monkeypatch.setattr(context_contract, "iter_context_facts", lambda pack: [ContextFact(path="attachment.caption", value="x", voice=<locally-defined unhandled ContextVoice-shaped member>)])` then call `partition_context_pack(pack)` → `ValueError` whose **message contains the offending value** (no silent default branch; a bare `raise` without the value fails the message assertion). |
| Content-blind partition | Two packs identical except `attachment.caption` value (`"alpha"` vs `"beta"`), both `voice="creator"`. Assert: both yield the same absorbable/quotable path sets (only `value` differs). Proves discrimination is on `voice`, not content — no need for oppressive strings in fixtures. **Red if** partition keys on content. | Same two captions with `voice="operator"` both land in absorbable. |
| **Parametrized IN-row inventory (one case per IN path)** | `@pytest.mark.parametrize` over every **IN** row in the inventory table. For each path template, build a pack that populates **only** that speech field (plus any structural keys required for model validity, e.g. `taxonomy` when testing `taxonomy_terms[0].name`, `policy.person_naming` when testing an identity name) with a distinctive non-empty string; leave all other IN fields empty/absent. Assert: `set(f.path for f in iter_context_facts(pack)) == {expected_path}` where `expected_path` is the **literal** path string for that row (e.g. `"attachment.description"`, `"post.excerpt"`, `"product.short_description"`, `"identity.identities[0].name"`). **Never** derive the expected set from `iter_context_facts` itself. **Red if** any IN path is omitted from the implementation. | **Cheating impl killed:** `iter_context_facts` that only emits `attachment.caption` / `attachment.title` / `post.title` / `taxonomy_terms[i].name` (the previously tested subset) fails the cases for `attachment.description`, `attachment.alt_text`, `post.excerpt`, `product.name`, `product.short_description`, and `identity.identities[0].name`. A no-op `return []` fails every IN case. |
| **Parametrized OUT-row exclusion (one case per OUT path)** | `@pytest.mark.parametrize` over every **OUT** row. Split into **two assertion forms** (do **not** weaken either form to "OUT path not in the set" alone): **(i) Independent OUT rows** (no required IN sibling forced by the pydantic model) — build a pack that populates **only** that OUT field (plus minimum structural keys that are themselves OUT or non-inventoried) and assert `set(f.path for f in iter_context_facts(pack)) == set()` — the explicit empty expected set. Named independent OUT paths: `attachment.filename`, `post.post_type`, `post.status`, `product.sku`, `product.price`, `identity.policy.person_naming`, `identity.review_reasons[{i}]`. **(ii) Dependent OUT rows** (model has a required IN field that must be present for validity) — assert `set(f.path for f in iter_context_facts(pack)) == {required_IN_path}` **and** that the OUT path under test is **absent** from that set. **Named five dependent OUT rows** (required IN sibling in parentheses; verified in `requests.py`): (1) `taxonomy_terms[{i}].taxonomy` → expected `{"taxonomy_terms[{i}].name"}` (`TaxonomyTermContext.name` required L40; `taxonomy` required L39 but OUT); (2) `taxonomy_terms[{i}].slug` → expected `{"taxonomy_terms[{i}].name"}` (`name` + `taxonomy` required for model validity; only `name` is IN); (3) `identity.identities[{i}].identity_id` → expected `{"identity.identities[{i}].name"}` (`IdentityContextItem.name` required L68); (4) `identity.identities[{i}].cluster_id` → expected `{"identity.identities[{i}].name"}`; (5) `identity.identities[{i}].source` → expected `{"identity.identities[{i}].name"}`. For identity item rows also supply `identity.policy.person_naming` (OUT, structural). **Never** derive the expected set from `iter_context_facts` itself. **Red if** filename / post_type / status / sku / price / taxonomy / slug / identity ids / `person_naming` / `review_reasons` enter inventory. | **Cheating impl killed:** an always-`True` "emit every non-empty string under the pack" walker fails every independent OUT case (non-empty set) and every dependent OUT case (expected set is exactly the required IN path, not the OUT path). Pairing: independent fixture plus one IN field (e.g. `attachment.title="t"`) yields exactly `{attachment.title}` against the explicit expected set. **Why the split is mandatory:** a single `== set()` assertion is **unsatisfiable** for the five dependent rows — constructing a valid `TaxonomyTermContext` / `IdentityContextItem` always injects an IN path (`name`), so an implementer would silently weaken to "OUT path absent" (forbidden). |
| Mixed-pack explicit expected set | One fixture that populates **all ten IN paths** with known values and mixed voices. Assert emitted path set equals the **hand-written** frozenset of those ten path strings (and values match). Also assert `paths(absorbable) ∩ paths(quotable_only) == ∅` and `paths(absorbable) ∪ paths(quotable_only) == <that same hand-written frozenset>` — **not** `== paths(iter_context_facts(pack))` as the only check. **Red if** a path is duplicated, dropped, or invented. | Empty pack → both lists empty; expected path set `frozenset()`. **Cheating impl killed:** partition that re-wraps `iter_context_facts` into one side only still fails the hand-written expected set if inventory is partial; a hardcoded `return ( [], [])` fails the ten-path fixture. |
| Non-attachment creator-default path | Pack with only `post.title="Creator post title"` (omit `post.voice` → default `creator`). Assert: `post.title` ∈ quotable_only, ∉ absorbable. **Red if** inventory skips `post.title` or default lands in absorbable. | Explicit `post.voice="operator"` moves `post.title` to absorbable. |
| Non-attachment catalogue path | Pack with `taxonomy_terms=[{"taxonomy":"product_cat","name":"Jackets","slug":"jackets"}]` (default `voice=catalogue`). Assert: `taxonomy_terms[0].name` ∈ absorbable. **Red if** taxonomy names are omitted from inventory or forced into quotable_only. | Override term `voice="creator"` → name moves to quotable_only only. |
| **ProductContext voice value propagates (boundary → partition)** | Validate a pack with `product={"name":"Widget X","voice":"creator"}` (today `ProductContext` at `requests.py` L44–52 has `name`/`sku`/`price`/`short_description` only — **no** `voice`; Slice 1 adds it). From the validated pack, take the `ContextFact` for path `product.name` emitted by `iter_context_facts` / present in `partition_context_pack`. Assert: `fact.voice is ContextVoice.CREATOR` **and** `product.name` ∈ quotable_only, ∉ absorbable. Repeat with explicit `voice="catalogue"` on the same product name: assert `fact.voice is ContextVoice.CATALOGUE` **and** path ∈ absorbable, ∉ quotable_only. **Permanent discrimination guard:** assert the observed `fact.voice` equals the request-boundary value (`pack.product.voice` after validate) — not merely that the path is inventoried. **Red if** schema accepts `voice` but `iter_context_facts` hardcodes `CREATOR` / drops the field / reads a different model's voice (IN-row path test still green). **Red-first mutation:** drop `voice=` when constructing `ContextFact` for product fields (mapper always uses default `CREATOR`) while request still carries `voice="catalogue"` → equality `fact.voice is pack.product.voice` fails and catalogue absorbable assertion fails. | Same product name with `voice="operator"` lands in absorbable with `fact.voice is OPERATOR`. Omit `voice` → default `CREATOR` propagates to fact.voice and quotable_only. **Cheating impl killed:** accept `voice` on `ProductContext` but ignore it in `iter_context_facts` (path-only inventory tests still pass). |
| **IdentityContextItem voice value propagates (boundary → partition)** | Validate a pack with `identity={"policy":{"person_naming":"allow"},"identities":[{"name":"Ada Lovelace","voice":"creator"}]}` (today `IdentityContextItem` at `requests.py` L63–71 has `name`/`identity_id`/`cluster_id`/`source` only — **no** `voice`; Slice 1 adds it with default `OPERATOR`). Assert the `ContextFact` for `identity.identities[0].name` has `fact.voice is ContextVoice.CREATOR` **and** path ∈ quotable_only, ∉ absorbable. Repeat with `voice="operator"` (and with omit → default `operator`): `fact.voice is OPERATOR` **and** path ∈ absorbable. **Permanent discrimination guard:** `fact.voice is pack.identity.identities[0].voice` (boundary value == partition-observed value). **Red if** schema accepts item `voice` but mapper drops it or forces the model default regardless of request. **Red-first mutation:** drop the field in the mapper (`ContextFact(..., voice=ContextVoice.OPERATOR)` always, ignoring item.voice) while request sends `voice="creator"` → boundary equality fails and creator-not-absorbable for identity name fails. | Override to `voice="catalogue"` → absorbable with matching fact.voice. **Cheating impl killed:** inventory emits `identity.identities[0].name` with a hardcoded default while accepting `voice` on the pydantic model. |
| Invalid voice rejected | Envelope with `context_pack.attachment.voice="archivist"` (unknown token). `DescribeImageEnvelope.model_validate(...)` raises `ValidationError` mentioning `voice`. | `voice="creator"` validates. |
| Additive under `extra="forbid"` | Payload **identical to today's** pack fixture shape (no `voice` keys anywhere). Must validate; filled defaults are `creator` / `catalogue` / `operator` per **allowlist** model rules above (`IdentityPolicyContext` has no `voice` key after validate). **Red if** validation requires explicit `voice`, or if `IdentityPolicyContext` gains a serialized `voice`. | Payload with an **extra** unknown key `context_pack.attachment.tone="warm"` still 422 (`extra="forbid"` preserved). |
| Default fail-closed | Omit `voice` on `attachment`; after validate, `partition_context_pack` places attachment speech strings in quotable_only. **Red if** omitted voice defaults into absorbable. | Explicit `voice="operator"` on attachment moves those strings to absorbable. |
| Dump equality after defaults (fixture split) | `test_route_passes_normalized_context_pack_to_adapter` posts `_context_pack()` (**no** voice keys; body uses `_context_pack()` at L134) and asserts `adapter.context == _context_pack_dump()` (**L139** retarget; L137 is blank). `_context_pack_dump` carries default voices on allowlist models only. **Red if** expected dump omits `voice` while route emits it (or vice versa), or if expected dump puts `voice` on `IdentityPolicyContext`. | Raw-dict seeded-adapter / service tests still call `_context_pack()` without voice keys (L94 / L108) and still apply sources (item 4 still proved). |
| **Omit-voice route dump under REAL route flags (F1(a))** | POST `/scene/describe/multipart` with a request whose `context_pack` is `_context_pack()` (omits `voice` entirely; L134). Capture the dict the route hands the adapter (`CapturingAdapter.context` in `test_context_pack.py`). Assert it equals `_context_pack_dump()` and that allowlist nested objects carry the documented default voice strings (**L139**). **Real route flags named:** production dump is `ContextPack.model_dump(exclude_none=True)` at `describe.py:446` — **not** `exclude_defaults=True`, **not** `exclude_unset=True`. **Red if** defaults are dropped by those flags, if the test only validates a pure `model_dump` with different flags, or if the request fixture itself injects voice (would hide `exclude_defaults` / `exclude_unset` cheating). | Pure unit: `DescribeImageEnvelope.model_validate({..., "context_pack": _context_pack()}).context_pack.model_dump(exclude_none=True) == _context_pack_dump()` — same flags as `describe.py:446`. **Cheating impl killed:** router switched to `exclude_defaults=True` or `exclude_unset=True` fails L139 / this proof while pure partition tests stay green. |
| **Boundary voice survives adapter serialization path (F1(a))** | Build the render input **only** from the production dump path under test: `dump = DescribeImageEnvelope.model_validate({..., "context_pack": <pack with explicit boundary voice, e.g. attachment.voice="creator">}).context_pack.model_dump(exclude_none=True)` — same flags as `describe.py:446`. **Do not** hand-build a dump matching `_context_pack_dump` (that makes the assertion a tautology over a literal the test itself wrote: `_render_context` at L73–87 stringifies top-level values via `json.dumps(str(value))`, so `"creator" in str({..."voice":"creator"...})` is true by construction with no pydantic model, no route, and no F1(a) code in the path). Call production helpers **without editing the adapter**: `scene.infrastructure.vlm.gpu_remote_adapter._render_context(dump)` (L73–87) and/or `_user_text(dump)` (L90–101; invoked by `_describe` at L176). Assert the returned render / user-text string contains the boundary voice value (e.g. the substring `"creator"` inside the attachment mapping serialization). **Red if** voice is stripped before render (validate accepts it but dump/`_render_context` lose it), or if the proof only checks pure partition / a hand-built dict and never touches validate→`model_dump(exclude_none=True)`→`_render_context` / `_user_text`. | Same validate+dump path with `attachment.voice="operator"` produces render text containing `"operator"` and not only the speech strings. **Cheating impl killed:** F1(a) that injects voice into pydantic dumps/`context_hash` but loses it before the adapter serialization surface still fails this proof; a hand-built dump no longer greens the test before any DEPICT-1 code lands. |
| No voice on IdentityPolicyContext | After validate of a pack with `identity.policy.person_naming="allow"`, `model_dump(exclude_none=True)` of policy has keys exactly `{"person_naming": ...}` — no `voice`. **Red if** voice was added to that model. | `IdentityContextItem` with a name **does** dump `voice` (operator default). |

### Slice 2: `DescriptionRegister` on the **request** contract (enforcement deferred; no response echo)

**Goal**: Land the FORENSIC / EDITORIAL / INTERPRETIVE vocabulary on the
**request** envelope so call sites and the reasoning card share one enum before
v3 freezes. **Do not** add a response field or claim request→response echo —
`build_visual_facts_envelope` (`visual_facts_service.py` L71–83) takes no
register parameter, cached-row reconstruction has no register source, and this
lane does not own service/persistence propagation. Adding a model field with
only a direct round-trip test would pass while the echo stayed permanently
unwired.

**Canon**: `ATTRIB-01`, `ATTRIB-03`, card `attribute-claims-to-their-bearer`,
`API-09` (request field shape only), `API-10`, `REF-29`, `TEST-15`
(evidence: multi-source depiction distillations; card; restful-web-api-patterns;
refactoring-fowler-beck).

**No `REG-*` citation** — family does not exist (§5b).

Changes:

- Add to `scene/domain/description.py`:
  ```python
  class DescriptionRegister(StrEnum):
      FORENSIC = "FORENSIC"
      EDITORIAL = "EDITORIAL"
      INTERPRETIVE = "INTERPRETIVE"
  ```
- On `DescribeImageEnvelope` (requests.py), additive:
  ```python
  description_register: DescriptionRegister = DescriptionRegister.EDITORIAL
  ```
  Default `EDITORIAL` matches assessment/product default (not FORENSIC).
- **Do not** edit `scene/interface_adapters/http/schemas/responses.py`.
- **Do not** edit
  `packages/shared-contracts/schemas/image-description-response.schema.json`
  (verified present; no `description_register` property; none required while
  response field is out of scope).
- **Do not** edit `scene/tests/test_response_schema_parity.py` /
  `test_schemas.py` `PREVIEW_FIELDS`. Adding a response model field without a
  matching schema property turns
  `set(schema["properties"]) == set(VisualFactsResponse.model_fields)`
  (`test_response_schema_parity.py` L63) red; `PREVIEW_FIELDS` (L50–56) only
  rescues the *required* assertion (L61), not the properties equality.
  Package-absent skip and property-missing xfail branches are **dead code**
  in this checkout (schema file exists; verified present) and must not be
  introduced.
- **Frozen contract set + exhaustiveness** (same `context_contract.py` or
  adjacent). Do **not** use `set(DescriptionRegister)` as the permanent green —
  that is tautological after any enum extension:
  ```python
  # Permanent freeze — not derived from the enum at call time.
  _REGISTER_CONTRACT_VALUES: frozenset[DescriptionRegister] = frozenset({
      DescriptionRegister.FORENSIC,
      DescriptionRegister.EDITORIAL,
      DescriptionRegister.INTERPRETIVE,
  })

  def assert_register_contract() -> None:
      """REF-29 permanent guard: enum membership equals the frozen contract set."""
      actual = set(DescriptionRegister)
      if actual != set(_REGISTER_CONTRACT_VALUES):
          raise AssertionError(
              f"DescriptionRegister drifted from contract: "
              f"extra={actual - set(_REGISTER_CONTRACT_VALUES)} "
              f"missing={set(_REGISTER_CONTRACT_VALUES) - actual}"
          )

  def assert_register_exhaustive(handled: set[DescriptionRegister]) -> None:
      missing = set(_REGISTER_CONTRACT_VALUES) - handled
      if missing:
          raise AssertionError(f"unhandled DescriptionRegister values: {missing}")
  ```
  Production code in this slice does **not** branch on register for gates.
  The permanent green is `assert_register_contract()` (and/or
  `assert set(DescriptionRegister) == set(_REGISTER_CONTRACT_VALUES)` in the
  test module). A fourth enum value fails that guard even if a junior also
  ships a tautological `assert_register_exhaustive(set(DescriptionRegister))`.

Proof:

```bash
cd apps/prototype-description-service
uv run --extra dev pytest scene/tests/test_description_register_contract.py -q
# Baseline unchanged (no DEPICT-1 response edit):
uv run --extra dev pytest scene/tests/test_response_schema_parity.py -q
```

**[TEST-15] red-first proofs (Slice 2)**

| Check | Exact red input | Discrimination / cheating impl killed |
|---|---|---|
| Unknown register rejected | `description_register="LYRICAL"` on envelope → `ValidationError`. | Each of `FORENSIC`, `EDITORIAL`, `INTERPRETIVE` validates. |
| Frozen contract set | Permanently assert `set(DescriptionRegister) == {FORENSIC, EDITORIAL, INTERPRETIVE}` via `_REGISTER_CONTRACT_VALUES`. **Red if** a fourth value is added to the enum without updating the freeze (or if a value is removed). | Hand-edit the freeze to drop `INTERPRETIVE` while enum still has three → `assert_register_contract` fails (proves non-tautology). |
| Exhaustiveness helper | Call `assert_register_exhaustive({FORENSIC, EDITORIAL})` (omit INTERPRETIVE) → raises `AssertionError` naming `INTERPRETIVE`. **Red if** the helper is a no-op. | `assert_register_exhaustive(set(_REGISTER_CONTRACT_VALUES))` passes; do **not** treat `assert_register_exhaustive(set(DescriptionRegister))` alone as the permanent green. |
| Omit on request | Envelope without `description_register` validates as `EDITORIAL`. | Explicit `FORENSIC` overrides default. |
| No response field claimed | Assert `description_register` is **not** a field on `VisualFactsResponse` (or is not added by this branch). **Red if** Slice 2 re-introduces an echo field without owning propagation. | Request envelope still carries the enum; service/envelope builders remain unedited. **Cheating impl killed:** adding only `VisualFactsResponse.description_register` + a model round-trip test without route/service wiring is **out of scope and fails this check** — that is the defect this slice deliberately refuses. |

**Note (unblocked, not planned):** DEPICT-5 (v3 `caption` split into grounded
inventory span + attributed span) is cheaper once this enum exists. Do not
implement it in DEPICT-1. A future task that wants response echo must own
request → service → persistence → response for both fresh and cached paths
and update the shared JSON schema in the same change set — not DEPICT-1.

### Slice 3: Restrict-only gravity + obligation disposition shape

**Goal**: Contract carries a testable monotone-restrict gravity path **and** a
separate obligation disposition so atrocity-class inventory is not averaged
into silent suppress. Class membership is operator-supplied, not inferred.

**Canon**: `ATTRIB-05`, `ATTRIB-04`, `BOUND-03`, `STRAT-11`, `API-09`, `TEST-15`
(evidence: `sontag-regarding-the-pain-of-others.md` tensions — obligation vs
restraint partition; `sontag-on-photography.md` ATTRIB-04; azoulay BOUND-03;
`never-split-the-difference` STRAT-11). No `RLSE-02` — disposition shape is
assessment §2 item 9 / F3 operator design, not a release gate.

Changes:

- Add to `scene/domain/description.py`:
  ```python
  class GravityDisposition(StrEnum):
      RESTRICT = "restrict"
      OBLIGATE_INVENTORY = "obligate_inventory"
  ```
- Add request model (in `requests.py` or imported from schemas):
  ```python
  class GravityDirective(BaseModel):
      model_config = ConfigDict(extra="forbid")
      disposition: GravityDisposition = GravityDisposition.RESTRICT
      # Operator label only — no in-process class table in this task.
      image_class: str | None = Field(default=None, max_length=64)
  ```
- On `DescribeImageEnvelope`:
  ```python
  gravity: GravityDirective = Field(default_factory=GravityDirective)
  ```
- Pure functions in `context_contract.py`:
  ```python
  _REGISTER_RANK = {
      DescriptionRegister.FORENSIC: 0,
      DescriptionRegister.EDITORIAL: 1,
      DescriptionRegister.INTERPRETIVE: 2,
  }

  def _rank(reg: DescriptionRegister) -> int:
      return _REGISTER_RANK[reg]

  def _by_rank(rank: int) -> DescriptionRegister:
      for reg, r in _REGISTER_RANK.items():
          if r == rank:
              return reg
      raise ValueError(rank)

  def effective_register(
      requested: DescriptionRegister,
      gravity: GravityDirective,
      *,
      restrict_ceiling: DescriptionRegister = DescriptionRegister.EDITORIAL,
  ) -> DescriptionRegister:
      """Under RESTRICT, return the register at
      min(rank(requested), rank(ceiling)) — exact min, not a one-sided
      inequality. Under OBLIGATE_INVENTORY, return requested unchanged
      (restriction must not silently rewrite the altitude of an obligation
      description; inventory duty is a separate flag)."""
      if gravity.disposition is GravityDisposition.OBLIGATE_INVENTORY:
          return requested
      return _by_rank(min(_rank(requested), _rank(restrict_ceiling)))

  def inventory_obligation(gravity: GravityDirective) -> bool:
      """Report-only: True when disposition is obligate_inventory.

      This function does **not** refuse, raise, or rewrite caller behaviour.
      Callers that need to block inventory-suppression must read this flag and
      act; a caller that ignores it is outside this helper's authority.
      """
      return gravity.disposition is GravityDisposition.OBLIGATE_INVENTORY
  ```
  Spec property under RESTRICT (default ceiling `EDITORIAL`):
  `rank(result) == min(rank(requested), rank(ceiling))`.
  Exact table (default ceiling):
  `(FORENSIC→FORENSIC)`, `(EDITORIAL→EDITORIAL)`,
  `(INTERPRETIVE→EDITORIAL)`.
- **Do not** ship a hardcoded map
  `{"atrocity": OBLIGATE_INVENTORY, "product": RESTRICT, ...}`.
  That map is the DEPICT-D1 operator decision memo (below). The schema only
  holds `image_class` as an opaque operator label for later wiring.
- No prompt or adapter behaviour change in this slice.

Proof:

```bash
cd apps/prototype-description-service
uv run --extra dev pytest scene/tests/test_gravity_contract.py -q
```

**[TEST-15] red-first proofs (Slice 3)**

| Check | Exact red input | Discrimination |
|---|---|---|
| Exact min under default ceiling | Parametrize `(requested, expected)`: `(FORENSIC, FORENSIC)`, `(EDITORIAL, EDITORIAL)`, `(INTERPRETIVE, EDITORIAL)` with `GravityDirective(disposition=RESTRICT)` and default `restrict_ceiling=EDITORIAL`. Assert `effective_register(...) is expected` (identity, not mere `rank <=`). **Red if** implementation always returns `FORENSIC` under RESTRICT (passes `rank(result) <= rank(requested)` vacuously) or `return requested` (leaves INTERPRETIVE unclamped). | Custom ceiling: `restrict_ceiling=FORENSIC` forces `effective_register(EDITORIAL, RESTRICT, restrict_ceiling=FORENSIC) is FORENSIC` and `effective_register(INTERPRETIVE, …) is FORENSIC`. |
| Rank equality property | For every `(requested, ceiling)` pair in the enum × enum grid under RESTRICT: assert `_rank(effective_register(...)) == min(_rank(requested), _rank(ceiling))`. **Red if** any pair violates exact min. | OBLIGATE path is excluded from this grid (separate check). |
| Obligation flag reports (not enforces) | `inventory_obligation(GravityDirective(disposition=OBLIGATE_INVENTORY, image_class="public_atrocity")) is True`, and `effective_register(EDITORIAL, that_directive) is EDITORIAL`; also `effective_register(INTERPRETIVE, that_directive) is INTERPRETIVE` (no silent demotion by the pure helper). **Red if** only `RESTRICT` exists or if OBLIGATE path reuses restrict clamping. **Note:** this proves the *report*; it does not grant the helper refusal authority over a caller that ignores the bool. | Same directive with `disposition=RESTRICT` → `inventory_obligation` is False and INTERPRETIVE clamps to EDITORIAL. **Cheating impl killed:** `def inventory_obligation(...): return True` fails the RESTRICT discrimination; `return False` always fails the OBLIGATE case. |
| Invalid disposition rejected | `gravity={"disposition": "expand"}` → `ValidationError`. | `restrict` and `obligate_inventory` both validate. |
| Additive envelope | Envelope without `gravity` validates; default disposition is `restrict`. | Envelope with only `gravity: {image_class: "public_atrocity"}` still defaults disposition to `restrict` (operator must set disposition explicitly for obligation — fail-closed). |

#### Operator decision memo (not a build task) — DEPICT-D1 pointer

Recorded so implementers and reviewers do not "helpfully" hardcode a class table:

- **Question:** which image classes take `restrict` vs `obligate_inventory`?
- **Why not code:** `STRAT-11` forbids averaging opposed goods into a middle
  option; Sontag *Regarding the Pain of Others* partitions desensitization
  folklore (feed UX) from whether a single catalogue description may name and
  specify; Azoulay requires force inventory before institutional story for
  circulating emergency images (depiction Tensions evidence the same cut).
  The membership of "public atrocity" vs "ordinary sensitive" is an
  **operator / policy** call (assessment §2 item 9 / F3), not a detector this
  lane ships.
- **Until the memo lands:** callers that need obligation set
  `gravity.disposition=obligate_inventory` explicitly; the default remains
  `restrict`.
- **Build task boundary:** shipping a silent auto-classifier from pixels or
  taxonomy → disposition is **out of scope** and would violate fail-closed
  labeling (`ATTRIB-02` risk on *output* who/by-whom claims).

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded assessment §2/§5c/§5d/§10g, eval F1/F3, reasoning card, and owned schemas.
- [ ] Confirmed no edits under Lane A or Lane C paths; cross-lane deps recorded
      with **F1 ownership split**: F1 (a) service/contract = this plan; F1 (b)
      production-weave = **OUT of this wave, unowned** (REBIND-ONLY of
      `PRODUCTION_PROMPT`; consumers of the selected config bind via accessors;
      adapter posts `self._production_prompt.body` from construction-time
      snapshot — no describe-time accessor re-read; no
      `from … import PRODUCTION_PROMPT` — DEPICT-0 section **Consumers:** today
      `:457-548`; never mutate frozen `.body`; rebind not retroactive on
      already-constructed adapters); harness pack `voice` **OUT/unowned**
      (not F1 a/b). Merging DEPICT-0+1+2 does **not** close F1.
- [ ] Every cited rule ID definition-anchor-verified; no `FM-11`, no `REG-*`, no
      `HARM-01`, no `BOUND-02` for input voice, no `RLSE-02` for disposition prose.
- [ ] Boundary table filled; additive-only under `extra="forbid"`; API-09 limited
      to field shape; Greenfield authorizes hash/default observability.

### Checklist for Slice 1: ContextVoice + partition

- [ ] `ContextVoice` StrEnum in `scene/domain/description.py`.
- [ ] `voice` field on voice-allowlist nested models with documented defaults
      (creator / catalogue / operator as specified); **no** `voice` on
      `IdentityContext` or **`IdentityPolicyContext`**; `review_reasons` and
      `person_naming` outside speech inventory.
- [ ] `iter_context_facts` implements the fixed path inventory (IN/OUT table).
- [ ] `partition_context_pack` pure function; creator ⊆ quotable_only only;
      catalogue/operator/**derived** ⊆ absorbable; disjoint invariant asserted
      against **hand-written expected path sets**; **no silent default branch**
      (unhandled voice → raise; seam = `monkeypatch.setattr` on
      `iter_context_facts` with unhandled `ContextVoice`-shaped member;
      message contains offending value).
- [ ] Frozen `_VOICE_CONTRACT_VALUES` / `_QUOTABLE_ONLY_VOICES` /
      `_ABSORBABLE_VOICES` literal frozensets (NOT derived from
      `set(ContextVoice)`); `assert_voice_contract()` permanent green.
- [ ] Tests: creator-not-absorbable, **DERIVED-only-absorbable**, frozen voice
      contract exhaustiveness, content-blind, **parametrized one case per
      IN row**, **parametrized one case per OUT row**, mixed-pack explicit
      expected frozenset, non-attachment creator/catalogue paths,
      **ProductContext voice value propagates boundary→partition**,
      **IdentityContextItem voice value propagates boundary→partition**,
      omit-still-valid, unknown-key still forbid, invalid enum 422,
      dump-equality via `_context_pack_dump` (L139) while `_context_pack`
      stays voice-free (uses L69 / L94 / L108 / L134), **omit-voice route dump
      under `model_dump(exclude_none=True)` (`describe.py:446`)**, **boundary
      voice survives `_render_context` / `_user_text` via validate+dump only
      (no hand-built dump)**, no voice on `IdentityPolicyContext`.
- [ ] Router churn zero; seeded raw-dict path still uses `_context_pack()`
      (no voice keys).
- [ ] `uv run --extra dev pytest scene/tests/test_context_voice_contract.py scene/tests/test_context_pack.py -q` green.
- [ ] No prompt / adapter source edits (F1 (b) weave is OUT of this wave /
      unowned; tests may call `_render_context` / `_user_text`; when F1 (b)
      owned later: REBIND `PRODUCTION_PROMPT`; consumers keep DEPICT-0
      **Consumers:** bind form — snapshot body, no describe-time re-read).

### Checklist for Slice 2: DescriptionRegister (request only)

- [ ] `DescriptionRegister` StrEnum (`FORENSIC|EDITORIAL|INTERPRETIVE`).
- [ ] Request field default `EDITORIAL`; **no** response field; **no** echo claim.
- [ ] Frozen `_REGISTER_CONTRACT_VALUES` + `assert_register_contract()` permanent
      green; helper red when a handled value is omitted.
- [ ] `responses.py`, shared JSON schema, `test_response_schema_parity.py`, and
      `PREVIEW_FIELDS` sets **unchanged** (no package-absent skip; no
      property-missing xfail).
- [ ] `uv run --extra dev pytest scene/tests/test_description_register_contract.py -q` green;
      baseline `test_response_schema_parity.py` still green without DEPICT-1 edit.
- [ ] No register behavioural gate (enforcement deferred).

### Checklist for Slice 3: Gravity directive

- [ ] `GravityDisposition` + `GravityDirective` on request envelope.
- [ ] `effective_register` under RESTRICT implements exact
      `min(rank(requested), rank(ceiling))` — table
      FORENSIC→FORENSIC, EDITORIAL→EDITORIAL, INTERPRETIVE→EDITORIAL at default
      ceiling; custom `restrict_ceiling=FORENSIC` forces EDITORIAL→FORENSIC.
- [ ] `inventory_obligation` is a **report-only bool** (true only for
      `obligate_inventory`); OBLIGATE does not clamp register; caller honours.
- [ ] Tests cover exact-min (not one-sided inequality), full rank grid, obligation
      report discrimination, invalid disposition, additive default.
- [ ] No hardcoded image-class → disposition table; DEPICT-D1 memo left to operators.
- [ ] `uv run --extra dev pytest scene/tests/test_gravity_contract.py -q` green.

## Review Readiness

- [ ] Every new check has a [TEST-15] red input and discrimination case in this plan and in test names/docstrings.
- [ ] Reviewer attack surface pre-empted:
  1. voice without enforcement → partition function + creator-not-absorbable + **DERIVED-only-absorbable** + frozen `_VOICE_CONTRACT_VALUES` / exhaustive no-default partition + **parametrized full IN/OUT inventory against explicit expected sets** + **Product/Identity boundary→partition voice value proofs**
  2. register without real exhaustiveness → frozen `_REGISTER_CONTRACT_VALUES` (not tautological `set(enum)`)
  3. restrict-only only in prose or vacuous rank≤ → exact min table + always-FORENSIC fails
  4. atrocity tension averaged → two dispositions, report-bool discrimination test, memo not middle mode (`STRAT-11`)
  5. additive vs `extra="forbid"` → omit-still-valid + unknown-key-still-422 tests
  6. response echo without wiring → **deleted from scope** (no response field; no PREVIEW_FIELDS / schema xfail trap)
  7. weave retargeted post-DEPICT-0 → F1 (b) is **OUT/unowned**; when owned: **REBIND-ONLY** `PRODUCTION_PROMPT` (never mutate frozen `.body`; rebind not retroactive on already-constructed adapters); consumers of the selected config bind via accessors; adapter posts `self._production_prompt.body` from construction-time snapshot (DEPICT-0 section **Consumers:** `:457-548`; no describe-time re-read; no `from … import PRODUCTION_PROMPT`; no `PRODUCTION_SYSTEM_PROMPT` global); harness pack `voice` still OUT/unowned
  11. dump-contract fixture split → `_context_pack` remains raw/no-voice (item 4; uses L69/L94/L108/L134); `_context_pack_dump` only at L139; omit-voice route proof uses real `describe.py:446` flags; adapter-path voice proof requires validate+`model_dump(exclude_none=True)` dump into `_render_context` / `_user_text` (no hand-built dump)
  12. `else: raise` arm → monkeypatch `iter_context_facts` seam + message contains offending value (not freestanding SimpleNamespace)
  8. ATTRIB-07 not overclaimed → oppressive subset only; blanket quotable-only = operator policy
  9. API-09 not used to warrant hash churn → shape only; Greenfield authorizes observability
  10. no pure-hash voice on IdentityPolicyContext
- [ ] Cross-lane deps explicit; F1 split recorded: **(a)** service/contract = DEPICT-1 this wave; **(b)** production-weave = OUT/unowned; harness `voice` = OUT/unowned; DEPICT-0+1+2 merge does **not** close F1.
- [ ] Handoff decision will record contract field names, defaults, and verification commands (at implementation time).

## Stretch Goals

- [ ] Optional response echo of `description_register` / `gravity` / partition
      summary — **only** as a future task that owns request → service →
      persistence → response for fresh **and** cached paths and updates the
      shared JSON schema in the same change set (not DEPICT-1).
- [ ] Per-field voice (title vs caption) as a second additive pass — only after object-level voice ships; do not replace object-level field ([API-09] shape).

## Success Criteria

- [ ] Creator-tagged speech-inventory path cannot appear in `partition_context_pack`
      absorbable list (proven red, then green) for attachment **and** at least one
      non-attachment creator-default path (`post.title`).
- [ ] DERIVED-tagged speech appears **only** in absorbable (explicit fixture);
      frozen `_VOICE_CONTRACT_VALUES` / `_ABSORBABLE_VOICES` cover all four
      `ContextVoice` members; partition has no silent default branch.
- [ ] **ProductContext** and **IdentityContextItem** each prove request-boundary
      `voice` equals partition-observed `fact.voice` (permanent discrimination
      guard); red-first mutation drops the field in the mapper.
- [ ] Fact inventory matches the IN/OUT table with **one parametrized test per
      IN row and per OUT row** against **explicit expected path sets** (not
      against `iter_context_facts` output); `review_reasons` / filename / slug /
      sku / person_naming are OUT; mixed-pack expected frozenset holds.
- [ ] Payloads without new keys still validate; invalid enum values 422; `extra="forbid"` preserved;
      dump equality uses `_context_pack_dump()` default voices on allowlist
      models only (L139) while `_context_pack()` stays voice-free for raw-dict
      paths (uses L69 / L94 / L108 / L134; no voice on `IdentityPolicyContext`);
      omit-voice route dump under real `model_dump(exclude_none=True)`
      (`describe.py:446`) carries defaults; boundary voice survives
      `gpu_remote_adapter._render_context` / `_user_text` only when the dump
      is produced by validate+`model_dump(exclude_none=True)` (no hand-built
      dump); `context_hash` one-time change accepted under **Greenfield
      Policy** (despite API-09 Hyrum note on changed defaults).
- [ ] `DescriptionRegister` has exactly three values frozen in
      `_REGISTER_CONTRACT_VALUES`, default request `EDITORIAL`, **no response
      echo**, permanent contract-set guard red when enum drifts.
- [ ] Gravity `restrict` equals exact min(requested, ceiling) under test (not mere
      rank≤); `obligate_inventory` is a distinct disposition with
      `inventory_obligation is True` as a **report**; no averaged middle mode and
      no coded class table.
- [ ] No files under Lane A or Lane C ownership modified; no `responses.py` edit;
      no shared-schema file edit; no bound-term/colour fields; no prompt text
      changes.
- [ ] Scoped pytest commands above green at branch HEAD (no parity skips/xfails).
- [ ] F1 production weave explicitly **not** claimed closed — F1 (b) is **OUT
      of this wave and unowned** (REBIND-ONLY of post-DEPICT-0
      `PRODUCTION_PROMPT`; consumers of the selected config bind via accessors;
      adapter posts `self._production_prompt.body` from construction-time
      snapshot — DEPICT-0 section **Consumers:** `:457-548`; no
      describe-time re-read; no `from … import PRODUCTION_PROMPT`; no
      `PRODUCTION_SYSTEM_PROMPT` string global; never mutate frozen `.body`;
      rebind not retroactive on already-constructed adapters). Harness
      voice-honouring lockstep is **OUT/unowned**. Merging DEPICT-0+1+2 does
      **not** close F1.
- [ ] ProductContext and IdentityContextItem each have a permanent proof that
      request-boundary `voice` equals partition-observed `fact.voice` (red-first
      mutation: drop field in mapper).

## Not-Doing

- Prompt / weave instruction edits — **F1 (b) production-weave**, **OUT of this
  wave and unowned** (no plan file in `docs/tasks/depiction/` delivers it).
  DEPICT-0 closes the seam only and **Not-Does** F1 weave wording (DEPICT-0
  section **Not-Doing**: "Changing what any prompt **says**" / "Weave-side
  context consumption / F1 voice-honouring prompt behaviour"). After
  DEPICT-0+1+2 alone, `partition_context_pack` is pure/unwired and production
  still weaves unmarked creator fields (today `gpu_remote_adapter.py` L33–34;
  post-DEPICT-0 the same wording lives on frozen selected `PRODUCTION_PROMPT`
  in `scene/prompts/caption_system.py`; consumers of the selected config bind
  via the accessor functions; the adapter snapshots once and posts
  `self._production_prompt.body` — DEPICT-0 section **Consumers:** today
  `:457-548` forbids `from … import PRODUCTION_PROMPT` and a dedicated frozen
  body export, and forbids describe-time accessor re-read of the body; do
  **not** cite the accessor-definition block at DEPICT-0 `:406-436` as that
  prohibition). When F1 (b) is later owned, mutation is **REBIND-ONLY**
  (`PRODUCTION_PROMPT = ProductionPrompt(body=…, lineage_version=…)`) —
  never `PRODUCTION_PROMPT.body = …` (`@dataclass(frozen=True)` →
  `FrozenInstanceError`), never a separate `PRODUCTION_SYSTEM_PROMPT`
  string global, and a rebind does **not** rewrite body/stamp already bound
  on a live adapter instance.
- Response `description_register` field / request→response echo / service or
  cache propagation — withdrawn from this task (no owned path; see Slice 2).
- Shared JSON schema mirror for a response register property — not required
  while response field is out of scope; schema path expected by
  `test_response_schema_parity.py:SCHEMA_PATH` is **verified present** and
  is not edited by DEPICT-1.
- Harness `ContextPack` voice mirror (`scripts/eval_harness/manifest.py`
  L165–176) and harness F1 voice-honouring lockstep — **OUT of this wave and
  unowned** (neither F1 (a) nor F1 (b)). F1 (a) contract traps are
  service-unit-only in this task. A future F1 (b) rebind may change bakeoff
  system wording without delivering harness pack-voice honour.
- `voice` on `IdentityPolicyContext` (only field is OUT `person_naming`).
- Bound-term shape, colour vocabulary, Werner/ISCC–NBS, `FM-11` anything (assessment §10g; retired ID).
- `caption_metrics.py` or any scorer (Lane C).
- v3 three-surface caption split (DEPICT-5 / F4) — unblocked by register enum, not planned.
- Register behavioural gates ("reject INTERPRETIVE claims in FORENSIC output").
- Hardcoded image-class → gravity map (DEPICT-D1 operator memo).
- Roster withhold flag (DEPICT-D2 / F7).
- Race warrant/parity aggregate (DEPICT-S1 / F5).
- Inner-state attribution counter (DEPICT-2 / F8 — Lane C).
- Putting `identity.review_reasons` into the speech partition (operator metadata).
- Any edit under `repo/` source trees during planning (this document only;
  sibling DEPICT-0/2 plans are read-only for this fix pass).
