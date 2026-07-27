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
before v3 promotion freezes the shape: (1) `voice` on every typed context-pack
entry with a pack-side partition that marks creator speech quotable-only,
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
  Do **not** edit Lane A paths (`gpu_remote_adapter.py`, `bakeoff.py`,
  `settings.py`, shared-prompt module) or Lane C paths (`caption_metrics.py`).
- **Greenfield, no shims.** No data migrations, no dual-write flags, no
  backward-compat adapters. Delete over flag. There are no production users —
  but [API-09] still governs: additions are optional with server defaults;
  never remove, rename, retype, or make-required an existing element.
- **`extra="forbid"` is already set** on every context and response model.
  Additive fields must have defaults (or be optional) so existing payloads that
  omit them still validate. Unknown keys still 422. Stated fully in
  Current State Analysis and Slice 1.
- **Prompt text is out of scope.** The weave-instruction half of F1 has nowhere
  safe to land until Lane A closes the DEPICT-0 prompt seam. Record as a
  cross-lane dependency; do not edit prompt strings here.
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
  (assessment §2 item 9; distillation-spec anti-average rule).
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
- Response contract: 17 core fields + additive optional preview/fusion/long
  surfaces (`VisualFactsResponse`). Pattern for additive optional fields is
  established (`alt_text_long`, `attachment_provenance`, …).
- Domain enums live in `scene/domain/description.py` with an explicit `sr-007`
  docstring. No `DescriptionRegister`, `ContextVoice`, or gravity enum exists
  (eval F8 verification still holds for register tokens).
- Production weave clause ("Weave the people's names and factual details…") is
  in `gpu_remote_adapter.py` — **Lane A owned**; not editable here.
- Tests that characterize the pack today:
  `scene/tests/test_context_pack.py`, `scene/tests/test_schemas.py`,
  `scene/tests/test_response_schema_parity.py` (parity against
  `packages/shared-contracts/...` when that package is present in the full
  monorepo).
- Fusion Stage-2 (`scene/application/fusion/reconcile.py`) already has
  `FactSource` / `AttachmentDecision` StrEnums and per-fact provenance on the
  response — a neighbour surface, not the voice field. Do not conflate
  `FactSource` (origin surface) with `ContextVoice` (speech authority).

## Target Outcome

1. Every typed context-pack entry carries a `voice: ContextVoice` with a
   fail-closed default; a pure, tested partition function returns disjoint
   absorbable vs quotable-only fact lists, and **creator never appears in
   absorbable**.
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
- Reasoning card: `canon/public/reasoning/attribute-claims-to-their-bearer.md`
- Owned code: `scene/interface_adapters/http/schemas/requests.py`,
  `scene/interface_adapters/http/schemas/responses.py`,
  `scene/domain/description.py`
- Characterization tests: `scene/tests/test_context_pack.py`,
  `scene/tests/test_schemas.py`

### Canon warrants (definition-anchor verified)

Every ID below was verified with
`grep -rE '^\| *`?<ID><a name' canon/lexicons/` (definition row, not
cross-reference).

| ID | Lexicon | Distilled evidence (Src) | Role in this task |
|---|---|---|---|
| `ATTRIB-07` | `canon/lexicons/depiction.md` | `canon/distilled/accessibility/anti-racist-description-resources.md` (§sec-creator) | Creator speech quotable-only; never unmarked system voice |
| `ATTRIB-02` | `depiction.md` | `canon/distilled/depiction/sontag-regarding-the-pain-of-others.md` | Uncited identity/guilt leaves FORENSIC; captions explain or falsify |
| `BOUND-02` | `depiction.md` | `canon/distilled/depiction/sontag-on-photography.md` (+ regarding-pain, azoulay) | Split unmarked inventory from labelled construction / other voice |
| `ATTRIB-01` | `depiction.md` | multi-source (berger / sontag / barthes / azoulay) | Bearer-not-depicted; register vocabulary consumer |
| `ATTRIB-03` | `depiction.md` | multi-source | Non-visible content → EDITORIAL/INTERPRETIVE with bearer |
| `ATTRIB-04` | `depiction.md` | `canon/distilled/depiction/sontag-on-photography.md` | Distress undercoding — inventory, not beauty/suppression |
| `ATTRIB-05` | `depiction.md` | `sontag-regarding-the-pain-of-others.md` + azoulay | Honor source name/withhold/singularity; no plight-type mint |
| `BOUND-03` | `depiction.md` | `canon/distilled/depiction/azoulay-civil-contract-of-photography.md` | Frame (force inventory) before institutional story |
| `API-09` | `canon/lexicons/engineering.md` | `canon/distilled/engineering/restful-web-api-patterns.md` (ch-2) | Don't change it, add it |
| `API-10` | `engineering.md` | same (ch-5) | Interface is its own artifact |
| `REF-29` | `engineering.md` | `canon/distilled/engineering/refactoring-fowler-beck.md` (ch-3/ch-10) | Enum completeness / exhaustiveness |
| `RLSE-02` | `engineering.md` | `canon/distilled/engineering/release-it.md` | Gates are not suggestions — disposition is real, not prose |
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

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
|---|---|---|---|---|---|
| `POST /scene/describe/multipart` request JSON (`context_pack`) | Lane B (this task) | `ContextPack` + nested models, `extra="forbid"` | Additive `voice` on each nested entry; defaults applied server-side | No — omit → default; invalid enum → 422 | `test_context_pack.py` + new voice tests |
| `DescribeImageEnvelope` | Lane B | tenant/media/context/context_pack/decorative/tier | Additive optional `description_register`, `gravity` | No — omit → defaults | schema unit tests |
| `VisualFactsResponse` | Lane B | 17 core + additive optionals | Additive optional `description_register` echo (never required) | No — absent stays valid | `test_schemas.py` field set + round-trip |
| Shared JSON schema `packages/shared-contracts/schemas/image-description-response.schema.json` | monorepo contract (full tree) | mirrors response model | Mirror additive optional `description_register` when package present | Yes — keep out of `required` | `test_response_schema_parity.py` (skip/adjust only if package absent in a sparse checkout) |
| Production system prompt / weave | Lane A (DEPICT-0) | unmarked weave of pack facts | Must honour quotable-only partition | Cross-lane | Not in this task |
| Eval harness metrics | Lane C | no register/voice axes | future register-compliance arm | Cross-lane | Not in this task |

## Proposed Solution

Three reviewable slices, each behaviour + proof:

1. **Voice vocabulary + pack partition** — `ContextVoice` StrEnum; `voice` on every
   nested context entry with fail-closed defaults; pure
   `partition_context_pack` that never places `creator` in absorbable; schema
   tests including extra-forbid and omit-still-valid.
2. **Register vocabulary** — `DescriptionRegister` StrEnum; request default
   `EDITORIAL`; optional response echo; exhaustiveness test; no behavioural gate.
3. **Gravity directive** — `GravityDisposition` + `GravityDirective` model;
   pure `effective_register` (monotone under `restrict`) and
   `inventory_obligation` (true under `obligate_inventory`); tests for both
   poles; operator memo for class partition recorded, not coded.

## Files and Surfaces to Change

| Surface | File | Change |
|---|---|---|
| domain enums | `scene/domain/description.py` | Add `ContextVoice`, `DescriptionRegister`, `GravityDisposition` StrEnums (`sr-007`) |
| request contract | `scene/interface_adapters/http/schemas/requests.py` | `voice` on nested pack models; `description_register` + `gravity` on `DescribeImageEnvelope` |
| schema helpers (new) | `scene/interface_adapters/http/schemas/context_contract.py` | Pure `partition_context_pack`, `effective_register`, `inventory_obligation` (+ small fact dataclass) |
| response contract | `scene/interface_adapters/http/schemas/responses.py` | Additive optional `description_register: DescriptionRegister \| None = None` |
| tests | `scene/tests/test_context_voice_contract.py` (new) | Voice partition + extra-forbid + defaults |
| tests | `scene/tests/test_description_register_contract.py` (new) | Register enum + exhaustiveness + response echo |
| tests | `scene/tests/test_gravity_contract.py` (new) | Monotone restrict + obligate_inventory discrimination |
| tests | `scene/tests/test_context_pack.py`, `scene/tests/test_schemas.py` | Update field-set / round-trip expectations for additive fields |
| shared schema (full monorepo) | `packages/shared-contracts/schemas/image-description-response.schema.json` | Optional property only; never `required` |

## Related Files

| File | Note |
|---|---|
| `scene/interface_adapters/http/routers/describe.py` | Already `model_dump`s `context_pack`; voice keys flow through without a router edit if dump includes defaults. Touch only if envelope field plumbing requires it — prefer zero router churn. |
| `scene/application/fusion/reconcile.py` | Neighbour provenance (`FactSource`). Do not overload with `ContextVoice`. Future fusion may *read* voice; not this slice. |
| `scene/infrastructure/vlm/gpu_remote_adapter.py` | Lane A — production weave. Cross-lane dependency. |
| `scripts/eval_harness/bakeoff.py` | Lane A — harness prompts. |
| `scripts/eval_harness/caption_metrics.py` | Lane C — scorers. |
| `scripts/eval_harness/manifest.py` | Separate harness `ContextPack` model; out of ownership. Note drift risk in cross-lane. |
| `canon/public/reasoning/attribute-claims-to-their-bearer.md` | Design warrant for register vocabulary |

## Cross-lane dependency

| Dependency | Exact file | Exact change needed | Lands first |
|---|---|---|---|
| Prompt-side F1 half | `scene/infrastructure/vlm/gpu_remote_adapter.py` (`_SYSTEM_PROMPT`, `_render_context` / `_user_text`) | Stop instructing unmarked weave of creator-tagged fields; render creator entries as quoted/voice-tagged only; consume pack `voice` from normalized context dict | **Lane A / DEPICT-0** must close the dual-prompt seam first so the edit has a single prompt source; then the voice-honouring prompt change lands on that source |
| Harness lockstep | `scripts/eval_harness/bakeoff.py` | Same voice-honouring behaviour in harness variants once shared prompt module exists | Lane A (parity test from DEPICT-0 keeps them aligned) |
| Harness manifest pack | `scripts/eval_harness/manifest.py` | Optional: mirror `voice` on harness-side ContextPack fixtures so bakeoff rows can set creator traps | After Slice 1 contract exists; not blocking contract merge |
| Register-compliance metric | `scripts/eval_harness/caption_metrics.py` | Future scored arm for register violations | Lane C — unblocked by Slice 2 vocabulary, not planned here |
| v3 caption split (DEPICT-5) | harness + future output schema | Split grounded inventory vs attributed span | Unblocked by Slice 2; **not planned** in DEPICT-1 |

## Verification Strategy

- Deterministic tests (from `apps/prototype-description-service/`):
  - `uv run --extra dev pytest scene/tests/test_context_voice_contract.py scene/tests/test_description_register_contract.py scene/tests/test_gravity_contract.py -q`
  - `uv run --extra dev pytest scene/tests/test_context_pack.py scene/tests/test_schemas.py -q`
  - If shared-contracts package present:
    `uv run --extra dev pytest scene/tests/test_response_schema_parity.py -q`
- Contract/fixture verification:
  - Old fixture payloads without `voice` / `description_register` / `gravity` still
    `model_validate` successfully.
  - Invalid enum values raise `ValidationError`.
  - `VisualFactsResponse` field set grows only by optional keys; core `required`
    count unchanged (17).
- Manual verification: none required for this contract-only task.

---

## Slice Delivery

### Slice 1: `ContextVoice` on every pack entry + quotable-only partition

**Goal**: Creator-tagged context is structurally partitioned out of the
absorbable set, with schema defaults that keep existing callers valid.

**Canon**: `ATTRIB-07`, `ATTRIB-02`, `BOUND-02`, `API-09`, `TEST-15`
(evidence: `anti-racist-description-resources.md` §sec-creator;
`sontag-regarding-the-pain-of-others.md`; `sontag-on-photography.md`;
`restful-web-api-patterns.md` ch-2; `modern-software-engineering.md`).

Changes:

- Add to `scene/domain/description.py`:
  ```python
  class ContextVoice(StrEnum):
      CREATOR = "creator"
      CATALOGUE = "catalogue"
      OPERATOR = "operator"
      DERIVED = "derived"
  ```
- On **each** nested pack model that carries caller-supplied text
  (`AttachmentContext`, `PostContext`, `TaxonomyTermContext`, `ProductContext`,
  `IdentityContextItem`, `IdentityPolicyContext`), add:
  ```python
  voice: ContextVoice = ContextVoice.CREATOR  # fail-closed default
  ```
  Exception: `IdentityContextItem` and `IdentityPolicyContext` default to
  `ContextVoice.OPERATOR` (roster / policy are operator-confirmed, not creator
  folder-title speech). `TaxonomyTermContext` defaults to
  `ContextVoice.CATALOGUE`.
- Add `scene/interface_adapters/http/schemas/context_contract.py`:
  - `@dataclass(frozen=True) class ContextFact` with
    `path: str`, `value: str`, `voice: ContextVoice`
  - `def iter_context_facts(pack: ContextPack) -> list[ContextFact]`
  - `def partition_context_pack(pack: ContextPack) -> tuple[list[ContextFact], list[ContextFact]]`
    returning `(absorbable, quotable_only)` where
    `voice is ContextVoice.CREATOR` ⇒ **only** quotable_only;
    `catalogue | operator | derived` ⇒ absorbable.
  - Invariant: the two lists are disjoint; union equals `iter_context_facts`.
- Do **not** edit `gpu_remote_adapter.py`. Document that runtime weave is the
  Lane A dependency above.
- Tests in `scene/tests/test_context_voice_contract.py` (and extend
  `test_context_pack.py` defaults).

Proof:

```bash
cd apps/prototype-description-service
uv run --extra dev pytest scene/tests/test_context_voice_contract.py scene/tests/test_context_pack.py -q
```

**[TEST-15] red-first proofs (Slice 1)**

| Check | Exact red input | Discrimination (non-vacuous green) |
|---|---|---|
| Creator never absorbable | Pack with `attachment.caption="the n-word folder title"` (use a realistic oppressive creator string in the fixture, not a sanitized placeholder) and `attachment.voice="creator"`. Assert: that string's path is **absent** from `partition_context_pack(pack)[0]` (absorbable). **Red if** the partition puts it in absorbable or if the function ignores `voice`. | Same caption with `voice="catalogue"` (or `operator`) **is** present in absorbable and absent from quotable_only. |
| Invalid voice rejected | Envelope with `context_pack.attachment.voice="archivist"` (unknown token). `DescribeImageEnvelope.model_validate(...)` raises `ValidationError` mentioning `voice`. | `voice="creator"` validates. |
| Additive under `extra="forbid"` | Payload **identical to today's** `_context_pack()` fixture (no `voice` keys anywhere). Must validate; filled defaults are `creator` / `catalogue` / `operator` per model rules above. **Red if** validation requires explicit `voice`. | Payload with an **extra** unknown key `context_pack.attachment.tone="warm"` still 422 (`extra="forbid"` preserved). |
| Default fail-closed | Omit `voice` on `attachment`; after validate, `partition_context_pack` places attachment strings in quotable_only. **Red if** omitted voice defaults into absorbable. | Explicit `voice="operator"` on attachment moves those strings to absorbable. |

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
- Exhaustiveness helper (same `context_contract.py` or adjacent):
  ```python
  def assert_register_exhaustive(handled: set[DescriptionRegister]) -> None:
      missing = set(DescriptionRegister) - handled
      if missing:
          raise AssertionError(f"unhandled DescriptionRegister values: {missing}")
  ```
  Production code in this slice does **not** branch on register for gates.
  The helper exists so future call sites and the permanent test share one check
  ([REF-29]).
- Update `test_schemas.py` `PREVIEW_FIELDS` / optional set to include
  `description_register`.
- Full monorepo: add optional property to
  `image-description-response.schema.json` (not in `required`).

Proof:

```bash
cd apps/prototype-description-service
uv run --extra dev pytest scene/tests/test_description_register_contract.py scene/tests/test_schemas.py -q
```

**[TEST-15] red-first proofs (Slice 2)**

| Check | Exact red input | Discrimination |
|---|---|---|
| Unknown register rejected | `description_register="LYRICAL"` on envelope → `ValidationError`. | Each of `FORENSIC`, `EDITORIAL`, `INTERPRETIVE` validates. |
| Exhaustiveness guard | Call `assert_register_exhaustive({DescriptionRegister.FORENSIC, DescriptionRegister.EDITORIAL})` (omit INTERPRETIVE) → raises `AssertionError` naming `INTERPRETIVE`. **Red if** the helper is a no-op. | `assert_register_exhaustive(set(DescriptionRegister))` passes. |
| Additive response | `_sample_response()` without `description_register` still validates; field is `None`. | Sample with `"description_register": "FORENSIC"` round-trips as enum. |
| Omit on request | Envelope without `description_register` validates as `EDITORIAL`. | Explicit `FORENSIC` overrides default. |

**Note (unblocked, not planned):** DEPICT-5 (v3 `caption` split into grounded
inventory span + attributed span) is cheaper once this enum exists. Do not
implement it in DEPICT-1.

### Slice 3: Restrict-only gravity + obligation disposition shape

**Goal**: Contract carries a testable monotone-restrict gravity path **and** a
separate obligation disposition so atrocity-class inventory is not averaged
into silent suppress. Class membership is operator-supplied, not inferred.

**Canon**: `ATTRIB-05`, `ATTRIB-04`, `BOUND-03`, `RLSE-02`, `API-09`, `TEST-15`
(evidence: `sontag-regarding-the-pain-of-others.md` tensions — obligation vs
restraint partition; `sontag-on-photography.md` ATTRIB-04; azoulay BOUND-03;
release-it gates).

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

  def effective_register(
      requested: DescriptionRegister,
      gravity: GravityDirective,
      *,
      restrict_ceiling: DescriptionRegister = DescriptionRegister.EDITORIAL,
  ) -> DescriptionRegister:
      """Under RESTRICT, return min(requested, ceiling) by rank — never higher
      than requested. Under OBLIGATE_INVENTORY, return requested unchanged
      (restriction must not silently rewrite the altitude of an obligation
      description; inventory duty is a separate flag)."""

  def inventory_obligation(gravity: GravityDirective) -> bool:
      return gravity.disposition is GravityDisposition.OBLIGATE_INVENTORY

  def assert_monotone_restrict(
      samples: Iterable[DescriptionRegister] = tuple(DescriptionRegister),
  ) -> None:
      """For all r in samples: rank(effective(r, RESTRICT)) <= rank(r).
      For all r1, r2 with rank(r1)<=rank(r2):
        rank(effective(r1)) <= rank(effective(r2))."""
  ```
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
| Restrict never expands | `effective_register(FORENSIC, GravityDirective(disposition=RESTRICT))` must not return `EDITORIAL` or `INTERPRETIVE`. Parametrize all three requested values; assert `rank(result) <= rank(requested)`. **Red if** restrict is a no-op that returns INTERPRETIVE when requested FORENSIC is inverted, or if any path upgrades rank. | `effective_register(INTERPRETIVE, RESTRICT)` returns a rank ≤ INTERPRETIVE and ≤ ceiling (`EDITORIAL`). |
| Monotone in requested rank | For `r1=FORENSIC`, `r2=INTERPRETIVE` under RESTRICT: `rank(effective(r1)) <= rank(effective(r2))`. **Red if** a higher request yields a lower effective than a lower request (non-monotone). | Full pairwise loop over the enum in `assert_monotone_restrict`. |
| Obligation not averaged away | `inventory_obligation(GravityDirective(disposition=OBLIGATE_INVENTORY, image_class="public_atrocity")) is True`, and `effective_register(EDITORIAL, that_directive) == EDITORIAL` (no silent demotion). **Red if** only `RESTRICT` exists or if OBLIGATE path reuses restrict clamping. | Same directive with `disposition=RESTRICT` → `inventory_obligation` is False and clamping applies. |
| Invalid disposition rejected | `gravity={"disposition": "expand"}` → `ValidationError`. | `restrict` and `obligate_inventory` both validate. |
| Additive envelope | Envelope without `gravity` validates; default disposition is `restrict`. | Envelope with only `gravity: {image_class: "public_atrocity"}` still defaults disposition to `restrict` (operator must set disposition explicitly for obligation — fail-closed). |

#### Operator decision memo (not a build task) — DEPICT-D1 pointer

Recorded so implementers and reviewers do not "helpfully" hardcode a class table:

- **Question:** which image classes take `restrict` vs `obligate_inventory`?
- **Why not code:** canon's distillation spec forbids averaging opposed
  instructions (restraint vs obligation) into a middle row; Sontag
  *Regarding the Pain of Others* partitions desensitization folklore (feed UX)
  from whether a single catalogue description may name and specify; Azoulay
  requires force inventory before institutional story for circulating emergency
  images. The membership of "public atrocity" vs "ordinary sensitive" is an
  **operator / policy** call (assessment §2 item 9), not a detector this lane
  ships.
- **Until the memo lands:** callers that need obligation set
  `gravity.disposition=obligate_inventory` explicitly; the default remains
  `restrict`.
- **Build task boundary:** shipping a silent auto-classifier from pixels or
  taxonomy → disposition is **out of scope** and would violate fail-closed
  labeling (`ATTRIB-02` risk).

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded assessment §2/§5c/§5d/§10g, eval F1/F3, reasoning card, and owned schemas.
- [ ] Confirmed no edits under Lane A or Lane C paths; cross-lane deps recorded.
- [ ] Every cited rule ID definition-anchor-verified; no `FM-11`, no `REG-*`, no `HARM-01`.
- [ ] Boundary table filled; additive-only under `extra="forbid"`.

### Checklist for Slice 1: ContextVoice + partition

- [ ] `ContextVoice` StrEnum in `scene/domain/description.py`.
- [ ] `voice` field on every nested context-pack entry with documented defaults
      (creator / catalogue / operator as specified).
- [ ] `partition_context_pack` pure function; creator ⊆ quotable_only only.
- [ ] Tests: red creator-in-absorbable, discrimination catalogue-absorbable,
      omit-still-valid, unknown-key still forbid, invalid enum 422.
- [ ] `uv run --extra dev pytest scene/tests/test_context_voice_contract.py scene/tests/test_context_pack.py -q` green.
- [ ] No prompt / adapter edits.

### Checklist for Slice 2: DescriptionRegister

- [ ] `DescriptionRegister` StrEnum (`FORENSIC|EDITORIAL|INTERPRETIVE`).
- [ ] Request field default `EDITORIAL`; response optional echo default `None`.
- [ ] Exhaustiveness helper + test that fails when a value is omitted from the handled set.
- [ ] `test_schemas.py` optional-field set updated; core required count unchanged.
- [ ] Shared JSON schema updated only if package present; property not required.
- [ ] `uv run --extra dev pytest scene/tests/test_description_register_contract.py scene/tests/test_schemas.py -q` green.
- [ ] No register behavioural gate (enforcement deferred).

### Checklist for Slice 3: Gravity directive

- [ ] `GravityDisposition` + `GravityDirective` on request envelope.
- [ ] `effective_register` monotone under `restrict`; never expands rank.
- [ ] `inventory_obligation` true only for `obligate_inventory`.
- [ ] Tests cover expand-attempt red, monotone pairwise, obligation discrimination,
      invalid disposition, additive default.
- [ ] No hardcoded image-class → disposition table; DEPICT-D1 memo left to operators.
- [ ] `uv run --extra dev pytest scene/tests/test_gravity_contract.py -q` green.

## Review Readiness

- [ ] Every new check has a [TEST-15] red input and discrimination case in this plan and in test names/docstrings.
- [ ] Reviewer attack surface pre-empted:
  1. voice without enforcement → partition function + creator-not-absorbable test
  2. register without exhaustiveness → `assert_register_exhaustive` red case
  3. restrict-only only in prose → `effective_register` / monotone tests
  4. atrocity tension averaged → two dispositions, discrimination test, memo not middle mode
  5. additive vs `extra="forbid"` → omit-still-valid + unknown-key-still-422 tests
- [ ] Cross-lane deps explicit; prompt half not silently planned here.
- [ ] Handoff decision will record contract field names, defaults, and verification commands (at implementation time).

## Stretch Goals

- [ ] Optional response echo of `gravity` / partition summary (`context_used.quotable_only_sources`) — only if it stays additive and does not require adapter rewrites beyond Lane B.
- [ ] Per-field voice (title vs caption) as a second additive pass — only after object-level voice ships; do not replace object-level field ([API-09]).

## Success Criteria

- [ ] Creator-tagged pack entry cannot appear in `partition_context_pack` absorbable list (proven red, then green).
- [ ] Payloads without new keys still validate; invalid enum values 422; `extra="forbid"` preserved.
- [ ] `DescriptionRegister` has exactly three values, default request `EDITORIAL`, optional response echo, exhaustiveness test red when a value is dropped.
- [ ] Gravity `restrict` is monotone-non-expanding under test; `obligate_inventory` is a distinct disposition with `inventory_obligation is True`; no averaged middle mode and no coded class table.
- [ ] No files under Lane A or Lane C ownership modified; no bound-term/colour fields; no prompt text changes.
- [ ] Scoped pytest commands above green at branch HEAD.

## Not-Doing

- Prompt / weave instruction edits (Lane A / DEPICT-0 dependency).
- Bound-term shape, colour vocabulary, Werner/ISCC–NBS, `FM-11` anything (assessment §10g; retired ID).
- `caption_metrics.py` or any scorer (Lane C).
- v3 three-surface caption split (DEPICT-5 / F4) — unblocked by register enum, not planned.
- Register behavioural gates ("reject INTERPRETIVE claims in FORENSIC output").
- Hardcoded image-class → gravity map (DEPICT-D1 operator memo).
- Roster withhold flag (DEPICT-D2 / F7).
- Race warrant/parity aggregate (DEPICT-S1 / F5).
- Inner-state attribution counter (DEPICT-2 / F8 — Lane C).
- Any edit under `repo/` during planning (this document only).
