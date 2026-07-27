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
`IdentityContext.review_reasons` is operator metadata outside the speech
partition) with a pack-side partition that marks creator speech quotable-only,
(2) `DescriptionRegister` (`FORENSIC | EDITORIAL | INTERPRETIVE`) as vocabulary
with enforcement deferred, and (3) a monotone **restrict-only** gravity
directive whose schema also carries the opposed **obligation** disposition so
atrocity-class inventory is not averaged into silent suppression. Each surface
ships with [TEST-15] red-first proof.

## Problem Statement

The typed `ContextPack` already forbids unknown keys (`extra="forbid"`) and
bounds every nested string, but it carries **no voice provenance**. CMS-authored
caption/title/taxonomy strings are rendered into the production prompt and the
shipping `_SYSTEM_PROMPT` instructs the model to *weave* names and factual
details in *where they fit naturally* — dissolving the seam between creator
speech and the system's unmarked descriptive voice. That is live production
exposure of eval finding F1 and a direct hit on `ATTRIB-07`.

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
  `scene/interface_adapters/http/schemas/requests.py`,
  `scene/interface_adapters/http/schemas/responses.py`, and co-located schema
  helpers under `scene/interface_adapters/http/schemas/`. Domain `StrEnum`
  vocabularies land in `scene/domain/description.py` (house pattern for
  `DescriptionAdapterKind` et al.; assessment §6e "scene/ contract models").
  Co-owned characterization tests under `scene/tests/`
  (`test_context_pack.py`, `test_schemas.py`, `test_response_schema_parity.py`,
  plus new contract test modules). Do **not** edit Lane A paths
  (`gpu_remote_adapter.py`, `bakeoff.py`, `settings.py`, shared-prompt module),
  Lane C paths (`caption_metrics.py`),
  `packages/shared-contracts/...` (unowned monorepo contract package), or
  `scripts/eval_harness/manifest.py` (unowned harness ContextPack).
- **Greenfield, no shims.** No data migrations, no dual-write flags, no
  backward-compat adapters. Delete over flag (repo Greenfield Policy — same
  formulation DEPICT-0 Constraints state; not a lexicon row). There are no
  production users — but [API-09] still governs: additions are optional with
  server defaults; never remove, rename, retype, or make-required an existing
  element.
- **`extra="forbid"` is already set** on every context and response model.
  Additive fields must have defaults (or be optional) so existing payloads that
  omit them still validate. Unknown keys still 422. Stated fully in
  Current State Analysis and Slice 1.
- **Prompt text is out of scope.** The weave-instruction half of F1 has nowhere
  safe to land until DEPICT-0 closes the prompt *seam* (move-only; DEPICT-0
  Not-Does wording). The actual voice-honouring weave rewrite is **DEPICT-1b**
  (Lane A, after DEPICT-0 + this contract). Do not edit prompt strings here;
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
- **Don't change it, add it.** Every new field is optional-or-defaulted.
  Existing callers that omit new keys keep validating ([API-09]).
- **Fail closed on unmarked creator speech.** Default `voice` for CMS-originated
  pack entries is `creator` so unset fields enter the quotable-only partition,
  never the absorbable set, until a caller deliberately marks them otherwise.
- **Carry opposed poles whole.** Monotone-restrict and atrocity-class obligation
  are both first-class dispositions. Do not average them into one middle mode
  (`STRAT-11`; assessment §2 item 9 / F3; depiction Tensions partitions are
  evidence of the same cut, not a separate lexicon family).
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
    inventory (force, body, injury marks) must be stateable; restriction must
    not silently demote a named singular record into a plight-type or suppress
    the force inventory (`ATTRIB-04`/`ATTRIB-05`/`BOUND-03`).
- **Image-class partition**: operator-owned mapping from content class →
  disposition. **Not built in this task** — recorded as DEPICT-D1 decision memo.

## Current State Analysis

- `ContextPack` and all nested models in
  `scene/interface_adapters/http/schemas/requests.py` set
  `model_config = ConfigDict(extra="forbid")` (verified at `ContextPack` L91 and
  every nested model). `DescribeImageEnvelope` and all response models in
  `responses.py` do the same.
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
  identity `name`, `review_reasons`).
- Response contract: 17 core fields + additive optional preview/fusion/long
  surfaces (`VisualFactsResponse`). Pattern for additive optional fields is
  established (`alt_text_long`, `attachment_provenance`, …).
- Domain enums live in `scene/domain/description.py` with an explicit `sr-007`
  docstring. No `DescriptionRegister`, `ContextVoice`, or gravity enum exists
  (eval F8 verification still holds for register tokens).
- Production weave clause ("Weave the people's names and factual details…") is
  in `gpu_remote_adapter.py` L33–34 — **Lane A owned**; not editable here, and
  **not** closed by DEPICT-0 (which Not-Does F1 weave wording).
- Route dump: `describe.py` L445–446 does
  `context_pack.model_dump(exclude_none=True)` (does **not** exclude defaults),
  so non-None `voice` defaults enter the adapter context dict and therefore
  `compute_context_hash` (`hashing.py` L22–37). One-time mass `context_hash`
  invalidation for otherwise-identical packs is expected under Greenfield
  Policy; no migration.
- Tests that characterize the pack today:
  `scene/tests/test_context_pack.py` (L43–64 `_context_pack()` fixture has no
  `voice` keys; L139 asserts `adapter.context == _context_pack()`),
  `scene/tests/test_schemas.py` (`PREVIEW_FIELDS` L13–21),
  `scene/tests/test_response_schema_parity.py` (`PREVIEW_FIELDS` L50–56;
  `set(schema["required"]) == set(VisualFactsResponse.model_fields) - PREVIEW_FIELDS`
  at L61 — adding an optional model field without extending this set turns
  required-set equality red). Shared-contracts package path is absent in this
  sparse tree; full monorepo may present it.
- Fusion Stage-2 (`scene/application/fusion/reconcile.py`) already has
  `FactSource` / `AttachmentDecision` StrEnums and per-fact provenance on the
  response — a neighbour surface, not the voice field. Do not conflate
  `FactSource` (origin surface) with `ContextVoice` (speech authority).
  Caption-fact inventory at `_reconcile_caption_facts` L459–522 enumerates
  `product.name`, `attachment.title`/`caption`, `post.title`, and each
  `taxonomy_terms[].name` — Slice 1's `iter_context_facts` must cover at least
  that set plus identity names.

## Target Outcome

1. Every nested context-pack model on the speech-field allowlist (Slice 1)
   carries a `voice: ContextVoice` with a fail-closed default; a pure, tested
   partition function over the fixed fact inventory returns disjoint
   absorbable vs quotable-only fact lists, and **creator never appears in
   absorbable**. `IdentityContext.review_reasons` is out of that inventory.
2. `DescriptionRegister` exists as a single `StrEnum`, is accepted on the
   request envelope (default `EDITORIAL`), is echoed optionally on the response,
   and has an exhaustiveness guard so a fourth value cannot land silently.
3. `GravityDirective` exists on the request envelope with
   `disposition ∈ {restrict, obligate_inventory}` and an optional operator
   `image_class` label; pure functions prove restrict is monotone-non-expanding
   and that `obligate_inventory` refuses inventory-suppression. The class→
   disposition table is **not** hardcoded — operator memo only.
4. Scoped pytest green; no prompt edits; no metrics edits; no bound-term fields.

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
  `scene/interface_adapters/http/schemas/responses.py`,
  `scene/domain/description.py`
- Characterization tests: `scene/tests/test_context_pack.py`,
  `scene/tests/test_schemas.py`,
  `scene/tests/test_response_schema_parity.py`

### Canon warrants (definition-anchor verified)

Every ID below was verified with
`grep -rE '^\| *`?<ID><a name' canon/lexicons/` (definition row, not
cross-reference).

| ID | Lexicon | Distilled evidence (Src) | Role in this task |
|---|---|---|---|
| `ATTRIB-07` | `canon/lexicons/depiction.md` | `canon/distilled/accessibility/anti-racist-description-resources.md` (§sec-creator) | **Primary voice warrant**: creator speech quotable-only; never unmarked system voice. Load-bearing for input pack `voice` + partition. |
| `ATTRIB-02` | `depiction.md` | `canon/distilled/depiction/sontag-regarding-the-pain-of-others.md` | **Output** who/by-whom/identity/guilt claims leave FORENSIC unless cited. Not a warrant for the input CMS-string voice field itself; cited only where register altitude of identity claims is discussed. |
| `ATTRIB-01` | `depiction.md` | multi-source (berger / sontag / barthes / azoulay) | Bearer-not-depicted; register vocabulary consumer |
| `ATTRIB-03` | `depiction.md` | multi-source | Non-visible content → EDITORIAL/INTERPRETIVE with bearer |
| `ATTRIB-04` | `depiction.md` | `canon/distilled/depiction/sontag-on-photography.md` | Distress undercoding — inventory, not beauty/suppression |
| `ATTRIB-05` | `depiction.md` | `sontag-regarding-the-pain-of-others.md` + azoulay | Honor source name/withhold/singularity; no plight-type mint |
| `BOUND-03` | `depiction.md` | `canon/distilled/depiction/azoulay-civil-contract-of-photography.md` | Frame (force inventory) before institutional story |
| `API-09` | `canon/lexicons/engineering.md` | `canon/distilled/engineering/restful-web-api-patterns.md` (ch-2) | Don't change it, add it |
| `API-10` | `engineering.md` | same (ch-5) | Interface is its own artifact |
| `REF-29` | `engineering.md` | `canon/distilled/engineering/refactoring-fowler-beck.md` (ch-3 only) | Enum completeness / exhaustiveness |
| `STRAT-11` | `business-marketing.md` | `never-split-the-difference` | Do not average opposed goods — dual-pole gravity (`restrict` vs `obligate_inventory`); depiction Tensions partitions evidence the same cut |
| `TEST-15` | `engineering.md` | `canon/distilled/engineering/modern-software-engineering.md` (ch-8 experimental / TDD red) | Prove the green can go red |

**No canon warrant (explicit):**

- There is **no `REG` family** in any lexicon (assessment §5b). `DescriptionRegister`
  is an operator-reserved design call (LIBSYN-1 / reasoning card vocabulary)
  backed by `ATTRIB-01`/`ATTRIB-03` and the card, **not** by a `REG-xx` row.
  Do not invent `REG-*` IDs.
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
  provenance tags. Voice partition rests on `ATTRIB-07`.
- **Delete over flag / no shims** is repo Greenfield Policy (shared formulation
  with DEPICT-0 Constraints), not a lexicon row.
- **Harness-side `ContextPack` voice mirror** (`scripts/eval_harness/manifest.py`)
  has no owner in this flock; F1 contract traps are service-unit-only until a
  named follow-on claims them.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
|---|---|---|---|---|---|
| `POST /scene/describe/multipart` request JSON (`context_pack`) | Lane B (this task) | `ContextPack` + nested models, `extra="forbid"` | Additive `voice` on speech-allowlist nested models (not on `IdentityContext`); defaults applied server-side | No — omit → default; invalid enum → 422 | `test_context_pack.py` + new voice tests |
| `DescribeImageEnvelope` | Lane B | tenant/media/context/context_pack/decorative/tier | Additive optional `description_register`, `gravity` | No — omit → defaults | schema unit tests |
| `VisualFactsResponse` | Lane B | 17 core + additive optionals | Additive optional `description_register` echo (never required) | No — absent stays valid | `test_schemas.py` field set + round-trip; `test_response_schema_parity.py` `PREVIEW_FIELDS` |
| Shared JSON schema `packages/shared-contracts/schemas/image-description-response.schema.json` | **Not this lane** — monorepo contract package owner (unowned in DEPICT-0/1/2 flock) | mirrors response model when package present | Optional `description_register` property; never in `required` — **cross-lane dependency**, not a DEPICT-1 file edit | Yes — keep out of `required` | Parity test skips/xfails until owner lands property (see Cross-lane) |
| Production system prompt / weave | **DEPICT-1b** (Lane A prompt owner; follow-on — **not** DEPICT-0) | unmarked weave of pack facts (`gpu_remote_adapter.py` L33–34) | Must honour quotable-only partition | Cross-lane follow-on | Not in this task; DEPICT-0 only moves prompts |
| Eval harness metrics | Lane C | no register/voice axes | future register-compliance arm | Cross-lane | Not in this task |

## Proposed Solution

Three reviewable slices, each behaviour + proof:

1. **Voice vocabulary + pack partition** — `ContextVoice` StrEnum; `voice` on
   speech-allowlist nested models with fail-closed defaults; fixed fact
   inventory; pure `partition_context_pack` that never places `creator` in
   absorbable; multi-path + content-blind schema tests; dump contract for
   default voices.
2. **Register vocabulary** — `DescriptionRegister` StrEnum; request default
   `EDITORIAL`; optional response echo; frozen contract-set exhaustiveness;
   both `PREVIEW_FIELDS` sets updated; no behavioural gate; shared JSON schema
   unowned.
3. **Gravity directive** — `GravityDisposition` + `GravityDirective` model;
   pure `effective_register` as exact `min(rank(requested), rank(ceiling))`
   under `restrict` and `inventory_obligation` under `obligate_inventory`;
   exact-table tests for both poles; operator memo for class partition
   recorded, not coded.

## Files and Surfaces to Change

| Surface | File | Change |
|---|---|---|
| domain enums | `scene/domain/description.py` | Add `ContextVoice`, `DescriptionRegister`, `GravityDisposition` StrEnums (`sr-007`) |
| request contract | `scene/interface_adapters/http/schemas/requests.py` | `voice` on nested pack models; `description_register` + `gravity` on `DescribeImageEnvelope` |
| schema helpers (new) | `scene/interface_adapters/http/schemas/context_contract.py` | Pure `partition_context_pack`, `effective_register`, `inventory_obligation` (+ small fact dataclass); fixed fact inventory |
| response contract | `scene/interface_adapters/http/schemas/responses.py` | Additive optional `description_register: DescriptionRegister \| None = None` |
| tests | `scene/tests/test_context_voice_contract.py` (new) | Voice partition + extra-forbid + defaults + multi-path inventory |
| tests | `scene/tests/test_description_register_contract.py` (new) | Register enum + frozen expected-set exhaustiveness + response echo |
| tests | `scene/tests/test_gravity_contract.py` (new) | Exact min(requested, ceiling) + obligate_inventory discrimination |
| tests | `scene/tests/test_context_pack.py` | Update `_context_pack()` / dump equality for default `voice` keys |
| tests | `scene/tests/test_schemas.py` | Add `description_register` to `PREVIEW_FIELDS` / optional set |
| tests | `scene/tests/test_response_schema_parity.py` | Add `description_register` to `PREVIEW_FIELDS` (L50–56); assert in `properties` and not in `required` (mirror `test_alt_text_long_never_required` L81–84); **introduce** package-absent skip (`SCHEMA_PATH.exists()` else `pytest.skip` — file currently has none and would `read_text()`-fail in this sparse tree); if package present but property not yet landed by contract owner → xfail/skip that property assertion only |

**Not edited by this lane (owned elsewhere or unowned):**

| Surface | File | Status |
|---|---|---|
| shared JSON schema | `packages/shared-contracts/schemas/image-description-response.schema.json` | **Unowned in this flock** — monorepo contract package owner. See Cross-lane. |
| production weave prompt | `scene/infrastructure/vlm/gpu_remote_adapter.py` | **DEPICT-1b** follow-on (Lane A). DEPICT-0 Not-Does wording. |
| harness ContextPack | `scripts/eval_harness/manifest.py` | **Unowned** — F1 traps are service-unit-only in DEPICT-1. |

## Related Files

| File | Note |
|---|---|
| `scene/interface_adapters/http/routers/describe.py` | L445–446 already `model_dump(exclude_none=True)` (defaults included). **Router churn stays zero.** Post-Slice-1 dump contract: dumped pack includes documented default `voice` keys; update `_context_pack()` in `test_context_pack.py` to expect those keys so L139 equality stays honest. Do **not** switch to `exclude_defaults=True` (would hide defaults from adapters/hash). |
| `scene/application/fusion/reconcile.py` | Neighbour provenance (`FactSource`). `_reconcile_caption_facts` L459–522 is the inventory alignment target for speech paths. Do not overload with `ContextVoice`. Future fusion may *read* voice; not this slice. |
| `scene/application/hashing.py` | `compute_context_hash` L22–37 — defaulted `voice` keys change the hash once for all packs. Acceptable under Greenfield Policy; no migration. |
| `scene/infrastructure/vlm/gpu_remote_adapter.py` | Production weave L33–34. **DEPICT-1b** (not DEPICT-0). |
| `scripts/eval_harness/bakeoff.py` | Lane A / DEPICT-0 — harness prompt seam only; voice-honouring wording is DEPICT-1b. |
| `scripts/eval_harness/caption_metrics.py` | Lane C — scorers. |
| `scripts/eval_harness/manifest.py` | Separate flat harness `ContextPack` (L165–176, `extra="allow"`, no `voice`). **Unowned** in this flock; not mirrored here. |
| Reasoning card `attribute-claims-to-their-bearer` (canon, not vendored) | Design warrant for register vocabulary — cite as plain text, do not markdown-link into `canon/`. |

## Cross-lane dependency

| Dependency | Exact file | Exact change needed | Owner / sequencing |
|---|---|---|---|
| Prompt seam (no wording) | `gpu_remote_adapter.py`, `bakeoff.py`, shared-prompt module | Single source for production system prompt text | **DEPICT-0 / Lane A** — lands first; explicitly **Not-Does** F1 weave rewrite (DEPICT-0 Not-Doing L653–655) |
| **Production voice-honouring weave (F1 prompt half)** | `scene/infrastructure/vlm/gpu_remote_adapter.py` (`_SYSTEM_PROMPT` L28–37, `_render_context` / `_user_text`) | Stop instructing unmarked weave of creator-tagged fields; render creator entries as quoted/voice-tagged only; consume pack `voice` from normalized context dict; call `partition_context_pack` (or honour its partition) | **DEPICT-1b** — named follow-on, Lane A prompt owner. Prerequisites: DEPICT-0 seam + DEPICT-1 Slice 1 contract. **Not owned by DEPICT-0 or DEPICT-1.** After DEPICT-0+1 merge alone, `partition_context_pack` is pure/unwired and production still weaves unmarked creator fields — **F1 is not closed**. |
| Harness voice-honouring lockstep | `scripts/eval_harness/bakeoff.py` | Same voice-honouring behaviour once DEPICT-1b edits the shared prompt source | **DEPICT-1b** (with DEPICT-0 parity tests keeping seam aligned) |
| Shared JSON schema mirror | `packages/shared-contracts/schemas/image-description-response.schema.json` | Add optional `description_register` property; **never** add to `required` | **Monorepo contract package owner** — unowned in DEPICT-0/1/2. DEPICT-1 updates `test_response_schema_parity.py` `PREVIEW_FIELDS` and mirrors `test_alt_text_long_never_required`; if package absent → skip; if package present without property → xfail/skip until owner lands it. |
| Register-compliance metric | `scripts/eval_harness/caption_metrics.py` | Future scored arm for register violations | Lane C — unblocked by Slice 2 vocabulary, not planned here |
| v3 caption split (DEPICT-5) | harness + future output schema | Split grounded inventory vs attributed span | Unblocked by Slice 2; **not planned** in DEPICT-1 |
| Harness ContextPack `voice` | `scripts/eval_harness/manifest.py` L165–176 | Would need a `voice` field + creator-trap fixtures for bakeoff-side F1 traps | **Explicitly unowned.** DEPICT-1 accepts F1 contract traps as **service-unit-only**; no optional row implying a silent mirror. |

## Verification Strategy

- Deterministic tests (from `apps/prototype-description-service/`):
  - `uv run --extra dev pytest scene/tests/test_context_voice_contract.py scene/tests/test_description_register_contract.py scene/tests/test_gravity_contract.py -q`
  - `uv run --extra dev pytest scene/tests/test_context_pack.py scene/tests/test_schemas.py -q`
  - Always (package-absent skip / property-absent xfail owned in the test):
    `uv run --extra dev pytest scene/tests/test_response_schema_parity.py -q`
- Contract/fixture verification:
  - Old fixture payloads without `voice` / `description_register` / `gravity` still
    `model_validate` successfully; post-validate dump of pack includes default
    `voice` keys (update `_context_pack()` expectations accordingly).
  - Invalid enum values raise `ValidationError`.
  - `VisualFactsResponse` field set grows only by optional keys; core `required`
    count unchanged (17); both `PREVIEW_FIELDS` sets include
    `description_register`.
  - Defaulted `voice` keys change `context_hash` once for all packs (Greenfield;
    no migration).
- Manual verification: none required for this contract-only task.
- **Out of verification for this task:** production weave still instructs
  unmarked weave until **DEPICT-1b**; F1 not closed by DEPICT-0+1 alone.

---

## Slice Delivery

### Slice 1: `ContextVoice` on speech-bearing pack models + quotable-only partition

**Goal**: Creator-tagged context is structurally partitioned out of the
absorbable set, with schema defaults that keep existing callers valid and a
fixed fact inventory so a caption-only implementation cannot pass.

**Canon**: `ATTRIB-07` (primary — input creator speech), `API-09`, `TEST-15`
(evidence: `anti-racist-description-resources.md` §sec-creator;
`restful-web-api-patterns.md` ch-2; `modern-software-engineering.md`).
`ATTRIB-02` is **not** a warrant for the input voice field (output who/by-whom
only). `BOUND-02` is **not** cited here (output craft/staging mix, not CMS
provenance).

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
  - `IdentityContextItem`, `IdentityPolicyContext` → `OPERATOR`
    (roster / policy are operator-confirmed, not creator folder-title speech).
- **`IdentityContext` itself does not get a `voice` field.** Its
  `review_reasons: list[str]` (`requests.py` L81) is **operator metadata
  outside the speech partition** — not creator/catalogue speech for weave.
  Objective / Success Criteria cover the allowlist, not "every string on the
  pack."
- Add `scene/interface_adapters/http/schemas/context_contract.py`:
  - `@dataclass(frozen=True) class ContextFact` with
    `path: str`, `value: str`, `voice: ContextVoice`
  - `def iter_context_facts(pack: ContextPack) -> list[ContextFact]`
  - `def partition_context_pack(pack: ContextPack) -> tuple[list[ContextFact], list[ContextFact]]`
    returning `(absorbable, quotable_only)` where
    `voice is ContextVoice.CREATOR` ⇒ **only** quotable_only;
    `catalogue | operator | derived` ⇒ absorbable.
  - Invariant: the two lists are disjoint by `path`; union of paths equals
    `iter_context_facts` paths. Assert in tests.

#### Fixed fact inventory for `iter_context_facts`

Only non-empty string values become `ContextFact`s. Path templates (dot /
index form) and inclusion:

| Path template | Source model field | In inventory? | Rationale |
|---|---|---|---|
| `attachment.title` | `AttachmentContext.title` | **IN** | `_reconcile_caption_facts` L478–484 |
| `attachment.caption` | `AttachmentContext.caption` | **IN** | reconcile L486–492 |
| `attachment.description` | `AttachmentContext.description` | **IN** | free-text prose speech |
| `attachment.alt_text` | `AttachmentContext.alt_text` | **IN** | free-text prose speech |
| `attachment.filename` | `AttachmentContext.filename` | **OUT** | opaque file token, not descriptive speech |
| `post.title` | `PostContext.title` | **IN** | reconcile L495–502 |
| `post.excerpt` | `PostContext.excerpt` | **IN** | free-text prose speech |
| `post.post_type` | `PostContext.post_type` | **OUT** | structural enum-like tag |
| `post.status` | `PostContext.status` | **OUT** | structural enum-like tag |
| `product.name` | `ProductContext.name` | **IN** | reconcile L467–474 |
| `product.short_description` | `ProductContext.short_description` | **IN** | free-text prose speech |
| `product.sku` | `ProductContext.sku` | **OUT** | identifier token |
| `product.price` | `ProductContext.price` | **OUT** | commerce token |
| `taxonomy_terms[{i}].name` | `TaxonomyTermContext.name` | **IN** | reconcile L505–522 |
| `taxonomy_terms[{i}].taxonomy` | `TaxonomyTermContext.taxonomy` | **OUT** | taxonomy id, not label speech |
| `taxonomy_terms[{i}].slug` | `TaxonomyTermContext.slug` | **OUT** | slug token |
| `identity.identities[{i}].name` | `IdentityContextItem.name` | **IN** | roster speech; align + extend reconcile inventory |
| `identity.identities[{i}].identity_id` / `cluster_id` / `source` | ids | **OUT** | opaque ids |
| `identity.policy.person_naming` | `IdentityPolicyContext.person_naming` | **OUT** | policy token, not free-text speech |
| `identity.review_reasons[{i}]` | `IdentityContext.review_reasons` | **OUT** | operator metadata; not speech partition |

Voice for each emitted fact is taken from the owning nested model’s `voice`
field (`IdentityContextItem.voice` for identity names; attachment/post/product/
taxonomy model `voice` for their fields). An implementation that iterates only
`attachment.caption` **fails** the multi-path red cases below.

- Do **not** edit `gpu_remote_adapter.py`. Runtime weave honouring is
  **DEPICT-1b**, not this slice.
- **Post-Slice-1 dump contract** (prescribed, not left to implementer choice):
  1. Router stays zero-churn (`describe.py` L445–446 unchanged).
  2. `model_dump(exclude_none=True)` continues to emit default `voice` keys
     (do not switch to `exclude_defaults`).
  3. Update `test_context_pack.py` `_context_pack()` **expected** dump to
     include the documented default voices on each nested object so
     `test_route_passes_normalized_context_pack_to_adapter` L139
     (`adapter.context == _context_pack()`) remains an exact equality.
  4. Distinguish from `test_seeded_adapter_applies_context_pack_sources`
     (L92–99): that test passes the **raw fixture dict** into
     `SeededDescriptionAdapter.describe` (no Pydantic validate → no default
     injection). It keeps working without `voice` keys; do not force voice into
     that raw-dict path.
- Tests in `scene/tests/test_context_voice_contract.py` (and extend
  `test_context_pack.py` defaults as above).

Proof:

```bash
cd apps/prototype-description-service
uv run --extra dev pytest scene/tests/test_context_voice_contract.py scene/tests/test_context_pack.py -q
```

**[TEST-15] red-first proofs (Slice 1)**

| Check | Exact red input | Discrimination (non-vacuous green) |
|---|---|---|
| Creator never absorbable (attachment) | Pack with `attachment.caption="folder title from donor notes"` and `attachment.voice="creator"`. Assert: path `attachment.caption` is **absent** from `partition_context_pack(pack)[0]` (absorbable). **Red if** the partition puts it in absorbable or if the function ignores `voice`. | Same caption with `voice="catalogue"` (or `operator`) **is** present in absorbable and absent from quotable_only. |
| Content-blind partition | Two packs identical except `attachment.caption` value (`"alpha"` vs `"beta"`), both `voice="creator"`. Assert: both yield the same absorbable/quotable path sets (only `value` differs). Proves discrimination is on `voice`, not content — no need for oppressive strings in fixtures. **Red if** partition keys on content. | Same two captions with `voice="operator"` both land in absorbable. |
| Non-attachment creator-default path | Pack with only `post.title="Creator post title"` (omit `post.voice` → default `creator`). Assert: `post.title` ∈ quotable_only, ∉ absorbable. **Red if** inventory skips `post.title` or default lands in absorbable. | Explicit `post.voice="operator"` moves `post.title` to absorbable. |
| Non-attachment catalogue path | Pack with `taxonomy_terms=[{"taxonomy":"product_cat","name":"Jackets","slug":"jackets"}]` (default `voice=catalogue`). Assert: `taxonomy_terms[0].name` ∈ absorbable. **Red if** taxonomy names are omitted from inventory or forced into quotable_only. | Override term `voice="creator"` → name moves to quotable_only only. |
| Disjoint / union invariant | Any pack with mixed voices across attachment + post + product + taxonomy + identity name. Assert: `paths(absorbable) ∩ paths(quotable_only) == ∅` and `paths(absorbable) ∪ paths(quotable_only) == paths(iter_context_facts(pack))`. **Red if** a path is duplicated, dropped, or invented. | Empty pack → both lists empty. |
| OUT fields never facted | Pack with only `attachment.filename="x.jpg"`, `identity.review_reasons=["person_naming_policy_disabled"]`, `product.sku="SKU-1"`. Assert: `iter_context_facts` is empty. **Red if** filename/sku/review_reasons enter the inventory. | Adding `attachment.title="t"` with default creator yields exactly one fact at `attachment.title`. |
| Invalid voice rejected | Envelope with `context_pack.attachment.voice="archivist"` (unknown token). `DescribeImageEnvelope.model_validate(...)` raises `ValidationError` mentioning `voice`. | `voice="creator"` validates. |
| Additive under `extra="forbid"` | Payload **identical to today's** `_context_pack()` fixture (no `voice` keys anywhere). Must validate; filled defaults are `creator` / `catalogue` / `operator` per model rules above. **Red if** validation requires explicit `voice`. | Payload with an **extra** unknown key `context_pack.attachment.tone="warm"` still 422 (`extra="forbid"` preserved). |
| Default fail-closed | Omit `voice` on `attachment`; after validate, `partition_context_pack` places attachment speech strings in quotable_only. **Red if** omitted voice defaults into absorbable. | Explicit `voice="operator"` on attachment moves those strings to absorbable. |
| Dump equality after defaults | Route test fixture updated to include default voices; `adapter.context == _context_pack()` still holds. **Red if** fixture omits `voice` while dump emits it (or vice versa). | Raw-dict seeded-adapter test still applies sources without requiring `voice` keys. |

### Slice 2: `DescriptionRegister` in the contract (enforcement deferred)

**Goal**: Land the FORENSIC / EDITORIAL / INTERPRETIVE vocabulary on request and
response so call sites and the reasoning card share one enum before v3 freezes.

**Canon**: `ATTRIB-01`, `ATTRIB-03`, card `attribute-claims-to-their-bearer`,
`API-09`, `API-10`, `REF-29`, `TEST-15`
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
- On `VisualFactsResponse` (responses.py), additive optional echo:
  ```python
  description_register: DescriptionRegister | None = None
  ```
  Never add to any "required core field" set; mirror `alt_text_long` pattern.
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
- Update **both** optional-field sets:
  - `test_schemas.py` `PREVIEW_FIELDS` (L13–21) → include `description_register`
  - `test_response_schema_parity.py` `PREVIEW_FIELDS` (L50–56) → include
    `description_register` (required: without this,
    `set(schema["required"]) == set(model_fields) - PREVIEW_FIELDS` goes red
    when the model gains the optional field)
  - Add a parity assertion mirroring `test_alt_text_long_never_required`:
    `description_register` ∈ `properties` and ∉ `required` **when** the shared
    schema package is present **and** already lists the property.
- **Shared JSON schema file is not edited in this lane** (unowned monorepo
  contract package). Sequencing: DEPICT-1 lands model + PREVIEW_FIELDS + skip/
  xfail path; contract package owner adds optional property (never `required`);
  then parity full-green.

Proof:

```bash
cd apps/prototype-description-service
uv run --extra dev pytest scene/tests/test_description_register_contract.py scene/tests/test_schemas.py scene/tests/test_response_schema_parity.py -q
```

**[TEST-15] red-first proofs (Slice 2)**

| Check | Exact red input | Discrimination |
|---|---|---|
| Unknown register rejected | `description_register="LYRICAL"` on envelope → `ValidationError`. | Each of `FORENSIC`, `EDITORIAL`, `INTERPRETIVE` validates. |
| Frozen contract set | Permanently assert `set(DescriptionRegister) == {FORENSIC, EDITORIAL, INTERPRETIVE}` via `_REGISTER_CONTRACT_VALUES`. **Red if** a fourth value is added to the enum without updating the freeze (or if a value is removed). | Hand-edit the freeze to drop `INTERPRETIVE` while enum still has three → `assert_register_contract` fails (proves non-tautology). |
| Exhaustiveness helper | Call `assert_register_exhaustive({FORENSIC, EDITORIAL})` (omit INTERPRETIVE) → raises `AssertionError` naming `INTERPRETIVE`. **Red if** the helper is a no-op. | `assert_register_exhaustive(set(_REGISTER_CONTRACT_VALUES))` passes; do **not** treat `assert_register_exhaustive(set(DescriptionRegister))` alone as the permanent green. |
| Additive response | `_sample_response()` without `description_register` still validates; field is `None`. | Sample with `"description_register": "FORENSIC"` round-trips as enum. |
| Omit on request | Envelope without `description_register` validates as `EDITORIAL`. | Explicit `FORENSIC` overrides default. |
| Parity PREVIEW_FIELDS | After model gains optional field, `test_schema_required_matches_model_fields` stays green only if `description_register ∈ PREVIEW_FIELDS`. **Red if** PREVIEW_FIELDS is not updated (required-set equality fails). | When package+property present: `description_register not in schema["required"]` and `in schema["properties"]`. Package absent → skip; property not yet landed → xfail/skip (unowned schema). |

**Note (unblocked, not planned):** DEPICT-5 (v3 `caption` split into grounded
inventory span + attributed span) is cheaper once this enum exists. Do not
implement it in DEPICT-1.

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
| Obligation not averaged away | `inventory_obligation(GravityDirective(disposition=OBLIGATE_INVENTORY, image_class="public_atrocity")) is True`, and `effective_register(EDITORIAL, that_directive) is EDITORIAL`; also `effective_register(INTERPRETIVE, that_directive) is INTERPRETIVE` (no silent demotion). **Red if** only `RESTRICT` exists or if OBLIGATE path reuses restrict clamping. | Same directive with `disposition=RESTRICT` → `inventory_obligation` is False and INTERPRETIVE clamps to EDITORIAL. |
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
      including **DEPICT-1b** (F1 weave) and unowned shared-schema / harness pack.
- [ ] Every cited rule ID definition-anchor-verified; no `FM-11`, no `REG-*`, no
      `HARM-01`, no `BOUND-02` for input voice, no `RLSE-02` for disposition prose.
- [ ] Boundary table filled; additive-only under `extra="forbid"`.

### Checklist for Slice 1: ContextVoice + partition

- [ ] `ContextVoice` StrEnum in `scene/domain/description.py`.
- [ ] `voice` field on voice-allowlist nested models with documented defaults
      (creator / catalogue / operator as specified); no `voice` on
      `IdentityContext`; `review_reasons` outside speech inventory.
- [ ] `iter_context_facts` implements the fixed path inventory (IN/OUT table);
      aligns with `_reconcile_caption_facts` plus identity names.
- [ ] `partition_context_pack` pure function; creator ⊆ quotable_only only;
      disjoint/union invariant asserted.
- [ ] Tests: creator-not-absorbable, content-blind, non-attachment creator path
      (`post.title`), non-attachment catalogue path (`taxonomy_terms[0].name`),
      OUT-fields-not-facted, omit-still-valid, unknown-key still forbid, invalid
      enum 422, dump-equality with default voices in `_context_pack()`.
- [ ] Router churn zero; seeded raw-dict path unchanged.
- [ ] `uv run --extra dev pytest scene/tests/test_context_voice_contract.py scene/tests/test_context_pack.py -q` green.
- [ ] No prompt / adapter edits (weave is DEPICT-1b).

### Checklist for Slice 2: DescriptionRegister

- [ ] `DescriptionRegister` StrEnum (`FORENSIC|EDITORIAL|INTERPRETIVE`).
- [ ] Request field default `EDITORIAL`; response optional echo default `None`.
- [ ] Frozen `_REGISTER_CONTRACT_VALUES` + `assert_register_contract()` permanent
      green; helper red when a handled value is omitted.
- [ ] `test_schemas.py` **and** `test_response_schema_parity.py` `PREVIEW_FIELDS`
      updated with `description_register`; core required count unchanged (17).
- [ ] Parity: property not required when present; skip if package absent; xfail/
      skip if property not yet landed by contract package owner.
- [ ] Shared JSON schema **not** edited in this lane (unowned cross-lane).
- [ ] `uv run --extra dev pytest scene/tests/test_description_register_contract.py scene/tests/test_schemas.py scene/tests/test_response_schema_parity.py -q` green (skips/xfails only as prescribed).
- [ ] No register behavioural gate (enforcement deferred).

### Checklist for Slice 3: Gravity directive

- [ ] `GravityDisposition` + `GravityDirective` on request envelope.
- [ ] `effective_register` under RESTRICT implements exact
      `min(rank(requested), rank(ceiling))` — table
      FORENSIC→FORENSIC, EDITORIAL→EDITORIAL, INTERPRETIVE→EDITORIAL at default
      ceiling; custom `restrict_ceiling=FORENSIC` forces EDITORIAL→FORENSIC.
- [ ] `inventory_obligation` true only for `obligate_inventory`; OBLIGATE does not
      clamp register.
- [ ] Tests cover exact-min (not one-sided inequality), full rank grid, obligation
      discrimination, invalid disposition, additive default.
- [ ] No hardcoded image-class → disposition table; DEPICT-D1 memo left to operators.
- [ ] `uv run --extra dev pytest scene/tests/test_gravity_contract.py -q` green.

## Review Readiness

- [ ] Every new check has a [TEST-15] red input and discrimination case in this plan and in test names/docstrings.
- [ ] Reviewer attack surface pre-empted:
  1. voice without enforcement → partition function + creator-not-absorbable + multi-path inventory tests
  2. register without real exhaustiveness → frozen `_REGISTER_CONTRACT_VALUES` (not tautological `set(enum)`)
  3. restrict-only only in prose or vacuous rank≤ → exact min table + always-FORENSIC fails
  4. atrocity tension averaged → two dispositions, discrimination test, memo not middle mode (`STRAT-11`)
  5. additive vs `extra="forbid"` → omit-still-valid + unknown-key-still-422 tests
  6. response field without parity PREVIEW_FIELDS → both PREVIEW_FIELDS sets + owned edit
  7. shared-schema / weave / harness pack not silently absorbed → named unowned or DEPICT-1b
- [ ] Cross-lane deps explicit; F1 weave is **DEPICT-1b**, not DEPICT-0.
- [ ] Handoff decision will record contract field names, defaults, and verification commands (at implementation time).

## Stretch Goals

- [ ] Optional response echo of `gravity` / partition summary (`context_used.quotable_only_sources`) — only if it stays additive and does not require adapter rewrites beyond Lane B.
- [ ] Per-field voice (title vs caption) as a second additive pass — only after object-level voice ships; do not replace object-level field ([API-09]).

## Success Criteria

- [ ] Creator-tagged speech-inventory path cannot appear in `partition_context_pack`
      absorbable list (proven red, then green) for attachment **and** at least one
      non-attachment creator-default path (`post.title`).
- [ ] Fact inventory matches the IN/OUT table; `review_reasons` / filename / slug /
      sku / person_naming are OUT; disjoint/union invariant holds.
- [ ] Payloads without new keys still validate; invalid enum values 422; `extra="forbid"` preserved;
      dump equality uses updated `_context_pack()` default voices; `context_hash`
      one-time change accepted under Greenfield.
- [ ] `DescriptionRegister` has exactly three values frozen in
      `_REGISTER_CONTRACT_VALUES`, default request `EDITORIAL`, optional response
      echo, permanent contract-set guard red when enum drifts.
- [ ] Gravity `restrict` equals exact min(requested, ceiling) under test (not mere
      rank≤); `obligate_inventory` is a distinct disposition with
      `inventory_obligation is True`; no averaged middle mode and no coded class table.
- [ ] No files under Lane A or Lane C ownership modified; no shared-schema file edit
      in this lane; no bound-term/colour fields; no prompt text changes.
- [ ] Scoped pytest commands above green at branch HEAD (parity skips/xfails only as prescribed).
- [ ] F1 production weave explicitly **not** claimed closed — owned by DEPICT-1b.

## Not-Doing

- Prompt / weave instruction edits — **DEPICT-1b** follow-on (Lane A). DEPICT-0
  closes the seam only and **Not-Does** F1 weave wording (DEPICT-0 L653–655).
  After DEPICT-0+1 alone, `partition_context_pack` is pure/unwired and production
  still weaves unmarked creator fields (`gpu_remote_adapter.py` L33–34).
- Shared JSON schema mirror (`packages/shared-contracts/...`) — unowned monorepo
  contract package owner; not DEPICT-1.
- Harness `ContextPack` voice mirror (`scripts/eval_harness/manifest.py`) —
  unowned; F1 contract traps are service-unit-only in this task.
- Bound-term shape, colour vocabulary, Werner/ISCC–NBS, `FM-11` anything (assessment §10g; retired ID).
- `caption_metrics.py` or any scorer (Lane C).
- v3 three-surface caption split (DEPICT-5 / F4) — unblocked by register enum, not planned.
- Register behavioural gates ("reject INTERPRETIVE claims in FORENSIC output").
- Hardcoded image-class → gravity map (DEPICT-D1 operator memo).
- Roster withhold flag (DEPICT-D2 / F7).
- Race warrant/parity aggregate (DEPICT-S1 / F5).
- Inner-state attribution counter (DEPICT-2 / F8 — Lane C).
- Putting `identity.review_reasons` into the speech partition (operator metadata).
- Any edit under `repo/` during planning (this document only).
