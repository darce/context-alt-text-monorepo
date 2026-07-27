# DEPICT-0. Prompt-lineage seam (one source, parity test, honest version stamp)

Task: DEPICT-0 · Branch: `feature/depict-0` · Status: planned
Date: 2026-07-27 · Author: grok-4.5 (remote flock lane A) · Project: prototype-description-service
Review Coverage Target: 2

> **DEPICT task family**: depiction-canon backlog item 1 (P0) from
> [`docs/assessments/current/depiction-canon-triage-and-backlog-2026-07-27.md`](../../docs/assessments/current/depiction-canon-triage-and-backlog-2026-07-27.md)
> §2 / §10g. Plans for this flock lane live under `docs/tasks/` once accepted;
> this file is the implementation task plan only.

## Objective

Close the production↔harness prompt-lineage seam: one module owns the caption
system-prompt text, both the GPU production adapter and the eval harness
consume it, a parity test fails when they diverge, and
`prompt_or_task_version` / `ACX_GPU_PROMPT_VERSION` honestly labels the prompt
text that actually ships.

## Problem Statement

Three code facts (governing assessment §1, D1–D3) make every later prompt
upgrade unsafe or untraceable today:

1. **D1 — two surfaces, comment-only lockstep.**
   `scene/infrastructure/vlm/gpu_remote_adapter.py:28` `_SYSTEM_PROMPT` is
   textually identical (whitespace-normalised) to
   `scripts/eval_harness/bakeoff.py:89` `_PROMPT_V1_SYSTEM`. The lockstep is a
   comment at `gpu_remote_adapter.py:23` ("Keep in lockstep with … bakeoff.py
   (VLMRP-HARM-01)") and nothing else.
   `scene/tests/test_eval_harness_pipeline.py:104-141` compares harness
   variants to each other; **nothing compares harness to production**. A
   prompt fix landed only in `bakeoff.py` changes nothing that ships, and
   there is no mechanical path to promote a harness variant into production.
2. **D2 — lying version stamp.**
   `scene/config/settings.py:40` `gpu_prompt_or_task_version` defaults to
   `"3"` (`ACX_GPU_PROMPT_VERSION`) while the prompt text it labels is v1.
   The same default is hard-coded on
   `GpuRemoteDescriptionAdapter.__init__` (`prompt_or_task_version: str = "3"`).
   The field is stamped into `scene` rows **and into the description cache key**
   (`scene/application/hashing.py`:
   `(tenant_id, image_hash, adapter, model_version, prompt_or_task_version,
   context_hash)`). Cross-version quality comparisons keyed on that field are
   mislabelled; a real v2/v3 promotion cannot be distinguished from today by
   the stamp.
3. **D3 — v3 promotion window still open.**
   No three-surface JSON path exists outside the harness; production returns
   single-surface prose. Closing D1 is what makes a later v2/v3 promotion a
   registry/config change rather than a hand-copy.

Inventory of the production v1 system-prompt body (unique clause
`"Weave the people's names and factual details it supplies"`): **exactly two
Python call sites** — `gpu_remote_adapter.py` and `bakeoff.py`. No third
live copy. Harness-only v2/v3 bodies live only in `bakeoff.py` and are
intentionally different text (not production defects; see Out of Scope).

## Constraints

- **Lane A file ownership (hard boundary).** This plan may edit only:
  - `apps/prototype-description-service/scene/infrastructure/vlm/gpu_remote_adapter.py`
  - `apps/prototype-description-service/scripts/eval_harness/bakeoff.py`
  - `apps/prototype-description-service/scene/config/settings.py`
  - any **new** shared-prompt module under `scene/` introduced by this task
  - tests that prove those surfaces (new + existing assertions that encode the
    old lying default `"3"`)
- **Do not edit** Lane B surfaces (`scene/interface_adapters/http/schemas/…`)
  or Lane C surfaces (`scripts/eval_harness/caption_metrics.py` and its tests).
- **Do not change prompt wording.** This lane *moves* prompt text; it does not
  edit F2 (emotion bearer) or F4 (three-surface split) content. Those stay
  harness-only until a later promotion.
- **Greenfield policy.** No production users. No data migrations. No
  backward-compat shims. Delete over flag. Correcting the version stamp
  **changes description cache keys** — acceptable; call it out, do not design
  a dual-key reader or a migration.
- **Test command.** From `apps/prototype-description-service/`:
  `uv run --extra dev pytest <path>`. Every slice states a real runnable path.
- **[TEST-15] red-first is mandatory** for every new check. State (a) the exact
  input/edit that makes it red and (b) a discrimination case proving the check
  is not vacuous.

## Workflow Principles

- **One authority for the production caption system prompt**
  [[REF-26](canon/lexicons/engineering.md#ref-26)]
  (`canon/lexicons/engineering.md` →
  `canon/distilled/engineering/pragmatic-programmer.md`): DRY is knowledge,
  not text. The acid test is one fact needing a multi-place edit — here, any
  production prompt fix must today be hand-copied between adapter and harness.
- **Extract only what must change together**
  [[REF-10](canon/lexicons/engineering.md#ref-10)]
  (`canon/lexicons/engineering.md` →
  `canon/distilled/engineering/refactoring-fowler-beck.md` +
  `canon/distilled/engineering/modern-software-engineering.md`): production v1
  and harness `PROMPT_VARIANTS["v1"]` are the same intent and ship together.
  Harness-only pass-1 / weave / compress prompts are **different facts** and
  stay in `bakeoff.py`. DRY stops at the deployable unit (this service), not
  across unrelated pipeline stages.
- **Prove the green can go red**
  [[TEST-15](canon/lexicons/engineering.md#test-15)]
  (`canon/lexicons/engineering.md` →
  `canon/distilled/engineering/modern-software-engineering.md`): a parity test
  that only re-reads the same constant twice certifies nothing.
- **Prompt configuration is production lineage**
  [[PROV-09](canon/lexicons/ml-systems.md#prov-09)]
  (`canon/lexicons/ml-systems.md` →
  `canon/distilled/ml-systems/ai-engineering.md`): the version stamp on each
  output must identify the prompt text that produced it.
- **No lying names**
  [[NAME-03](canon/lexicons/engineering.md#name-03)]
  (`canon/lexicons/engineering.md` →
  `canon/distilled/engineering/programmers-brain.md`): a field named
  `prompt_or_task_version` defaulting to `"3"` while shipping v1 text is a
  linguistic antipattern (name promises a version the body does not hold).
- **Every output walks back to its evidence**
  [[PROV-01](canon/lexicons/ml-systems.md#prov-01)]
  (`canon/lexicons/ml-systems.md` →
  `canon/distilled/ml-systems/model-cards.md`): the stamp is part of the
  result's lineage graph (and of the cache key); a mislabelled stamp makes
  reproduction and comparison impossible.

## Terminology

- **Production system prompt**: the system-role string
  `GpuRemoteDescriptionAdapter` posts on `/v1/chat/completions` today — the
  v1 body currently stored as `_SYSTEM_PROMPT`.
- **Harness v1 / v2 / v3**: named entries in `bakeoff.PROMPT_VARIANTS`. Only v1
  is textually identical to production today. v2 encodes ALTQ-1 style rules;
  v3 reuses v2's system text with `three_surface=True` and a weave addendum.
- **Shared-prompt module**: new single authority under `scene/` for caption
  system-prompt text, context markers used by that text, the named variant
  registry, and the production-selected variant + its version stamp.
- **Honest version stamp**: the default
  `gpu_prompt_or_task_version` / adapter `prompt_or_task_version` value that
  names the production-selected variant's lineage id (today: `"1"` for v1
  text), not a free-floating `"3"`.
- **Parity surface**: the two *consumer binding sites* the runtime actually
  uses — the string the production adapter puts in `messages[0].content`, and
  `PROMPT_VARIANTS["v1"].system` as used by `BakeoffClient` — not a double
  import of the shared constant alone.

## Current State Analysis

- Production GPU adapter builds chat payloads with module-level `_SYSTEM_PROMPT`
  and fenced `<<<CONTEXT>>>` / `<<<END_CONTEXT>>>` markers
  (`gpu_remote_adapter.py:25-37`, `:182`).
- Harness owns a full `PROMPT_VARIANTS` registry (`bakeoff.py:89-154`) with
  v1/v2/v3, plus harness-only `_PASS1_SYSTEM_PROMPT`, `_WEAVE_INSTRUCTIONS`,
  `_V3_THREE_SURFACE_INSTRUCTIONS`, `_COMPRESS_SYSTEM_PROMPT`.
- `DescriptionSettings.gpu_prompt_or_task_version` default `"3"`
  (`settings.py:40`); `deps.get_gpu_description_adapter` passes
  `settings.gpu_prompt_or_task_version` through (no edit needed if settings
  becomes honest).
- Adapter constructor default also `"3"` (`gpu_remote_adapter.py:133`).
- Existing tests encode the lie:
  - `scene/tests/test_gpu_remote_adapter.py` constructs with
    `prompt_or_task_version="3"` and asserts `== "3"`.
  - `scene/tests/test_description_profiles.py` asserts resolved GPU adapters
    expose `prompt_or_task_version == "3"`.
  - `scene/tests/test_ensemble_decode.py` stub uses `"3"`.
  - `scene/tests/test_settings.py` checks non-GPU
    `prompt_or_task_version == "1"` but never asserts the GPU default.
- Harness tests compare variants to each other only
  (`test_eval_harness_pipeline.py:104-141`); no production cross-check.
- Whitespace-normalised identity of the two v1 bodies verified in this planning
  pass (length 528, equal).

## Target Outcome

- Exactly one Python definition of the production caption system-prompt text
  (and of the context-marker pair the system prompt interpolates).
- Production adapter and harness v1 both import that definition; no local
  re-declaration of the v1 body remains in either consumer file.
- The named variant registry (v1/v2/v3 text, unchanged) lives in the shared
  module so a later promotion is "select a different production variant +
  version" rather than hand-copying strings into the adapter.
- A deterministic parity test fails if the production runtime system string and
  harness `PROMPT_VARIANTS["v1"].system` diverge (whitespace-normalised).
- Default `gpu_prompt_or_task_version` is derived from the production-selected
  variant (today `"1"`), co-located with that selection in the shared module —
  not a hand-maintained `"3"` under a new name.
- Cache-key consequence of the stamp correction is stated in-plan and accepted
  under greenfield policy; no migration/shim code.

## Context Loading

- Governing assessment:
  `docs/assessments/current/depiction-canon-triage-and-backlog-2026-07-27.md`
  (§1 D1–D3, §2 item 1, §10g Lane A — §10 supersedes §9 on scope).
- Upstream eval (background only):
  `docs/assessments/current/depiction-canon-fit-captioning-pipeline-2026-07-27.md`.
- Production surfaces:
  `scene/infrastructure/vlm/gpu_remote_adapter.py`,
  `scene/config/settings.py`,
  `scene/application/hashing.py` (cache-key shape; read-only),
  `scene/interface_adapters/http/deps.py` (wiring; read-only unless settings
  alone is insufficient — prefer no edit).
- Harness surface: `scripts/eval_harness/bakeoff.py` (prompt registry region
  ~L75–L154 and `PROMPT_VARIANTS` consumers).
- Existing tests to extend/correct:
  `scene/tests/test_gpu_remote_adapter.py`,
  `scene/tests/test_description_profiles.py`,
  `scene/tests/test_eval_harness_pipeline.py`,
  `scene/tests/test_settings.py`.
- Rules: `docs/workbay/rules/testing-python.md`,
  `docs/workbay/rules/backend-python-guidelines.md`,
  `docs/workbay/rules/development-workflow.md`.
- Canon (verified definition anchors, `grep -rE '^\| *\`?<ID><a name' canon/lexicons/`):
  - [REF-26] `canon/lexicons/engineering.md` → distilled
    `canon/distilled/engineering/pragmatic-programmer.md` (Topic 9 DRY-as-knowledge;
    acid test: multi-place multi-format edit for one fact).
  - [REF-10] `canon/lexicons/engineering.md` → distilled
    `canon/distilled/engineering/refactoring-fowler-beck.md` (change-together /
    Extract) + `canon/distilled/engineering/modern-software-engineering.md`
    (ch-13: DRY scope = one deployment pipeline).
  - [TEST-15] `canon/lexicons/engineering.md` → distilled
    `canon/distilled/engineering/modern-software-engineering.md` (ch-8: predict
    the exact failure message; a test never seen failing is unverified;
    assertion-free / vacuous tests are defects).
  - [PROV-09] `canon/lexicons/ml-systems.md` → distilled
    `canon/distilled/ml-systems/ai-engineering.md` (named mechanism **prompt
    configuration is production lineage**).
  - [NAME-03] `canon/lexicons/engineering.md` → distilled
    `canon/distilled/engineering/programmers-brain.md` (ch-9 linguistic
    antipatterns; lying names raise measured cognitive load).
  - [PROV-01] `canon/lexicons/ml-systems.md` (**not** `engineering.md`) →
    distilled `canon/distilled/ml-systems/model-cards.md` (versioned model
    reporting; every output walks back to evidence).

### Known non-citable traps (do not cite)

- `FM-11` — retired (`canon/literature/HELD.md`).
- `HARM-01` / `VLMRP-HARM-01` — project finding ref, not a canon ID (the
  existing adapter comment may keep the historical ticket name; do not treat
  it as canon warrant).
- Families `REG`, `ICON`, `FRAM`, `SEL` — do not exist.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Describe response schema (`prompt_or_task_version` field) | Lane B | optional/required string already present on response models | **none** — field shape unchanged; only the default *value* for the GPU profile changes from `"3"` → honest `"1"` | no schema compat work; greenfield accepts value change | existing schema/parity tests still pass; GPU profile tests updated to expect `"1"` |
| Description cache key | this service | includes `prompt_or_task_version` | default GPU stamp changes ⇒ new keys for previously `"3"`-labelled rows | **no** — greenfield, no migration, no dual-read | document in plan; unit tests of hashing unchanged (they take the stamp as input) |
| Eval harness run-record provenance | harness | `prompt_variant` already stamped | registry import path may change; provenance field names unchanged | no | `pytest scene/tests/ -k eval_harness` green |

Strictly local to the description service. No WP contract change. No bulk/async
surface change.

## Proposed Solution

Introduce a new shared-prompt module under `scene/` that is the single
authority for:

1. Context fence markers used by the caption system prompt
   (`<<<CONTEXT>>>` / `<<<END_CONTEXT>>>`).
2. The named caption system-prompt registry currently in `bakeoff.py`
   (`v1`, `v2`, `v3` — **text moved byte-for-byte**, including
   `system` / `system_long` / `three_surface`).
3. Production selection constants co-located with that registry:
   - `PRODUCTION_PROMPT_VARIANT = "v1"` (what the GPU adapter ships today)
   - `PRODUCTION_PROMPT_OR_TASK_VERSION` **derived** from that selection
     (map `v1→"1"`, `v2→"2"`, `v3→"3"`), never a free-floating default
     independent of the selected text.

Consumers:

- `gpu_remote_adapter.py` imports production system prompt + markers; deletes
  local `_SYSTEM_PROMPT` / local marker constants used only for that prompt;
  constructor default for `prompt_or_task_version` imports
  `PRODUCTION_PROMPT_OR_TASK_VERSION`.
- `bakeoff.py` imports the registry (and markers as needed); deletes local
  `_PROMPT_V1_SYSTEM` / `_PROMPT_V2_SYSTEM` / local `PROMPT_VARIANTS`
  definition; re-exports `PROMPT_VARIANTS` / `DEFAULT_PROMPT_VARIANT` so
  existing `from scripts.eval_harness.bakeoff import PROMPT_VARIANTS` tests
  keep working.
- `settings.py` default for `gpu_prompt_or_task_version` becomes
  `os.environ.get("ACX_GPU_PROMPT_VERSION", PRODUCTION_PROMPT_OR_TASK_VERSION)`
  so the env override remains, but the **unconfigured** default is honest.

Tests (same slices as the behaviour they load-bear):

- **Parity** between production consumer binding and harness v1 consumer
  binding, with explicit red-first and discrimination cases ([TEST-15]).
- **Honest stamp** between production-selected variant text and default
  version, with red-first and discrimination cases ([PROV-09], [NAME-03],
  [PROV-01]).
- Update existing assertions that hard-code GPU `"3"`.

### Cache-key hazard (explicit)

`prompt_or_task_version` is one of six dimensions of the description cache key
(`scene/application/hashing.py` docstring;
`description_repository` lookup equality). Changing the GPU default from
`"3"` to `"1"` means:

- New describe calls under the honest default miss any rows previously written
  under `"3"` for the same image/context/model.
- Under this repo's **greenfield policy** (no production users, no data to
  preserve) that is **acceptable**. Do **not** implement a dual-key read, a
  migration, a compatibility shim, or a feature flag. Delete the lie; do not
  paper over it.

### Cross-lane dependency

**None for landing this task.**

| Need | File | Exact change | Lane | Ordering |
| --- | --- | --- | --- | --- |
| — | — | No Lane B schema/enum edit required; field already exists as a free string. | B | n/a |
| — | — | No Lane C metrics edit required. | C | n/a |

`deps.py` already threads `settings.gpu_prompt_or_task_version`; once settings
defaults honestly, resolvers pick up the fix without an owned-file edit. If a
future promotion wants production to ship v2 text, that is a later DEPICT
slice (prompt content / promotion), not this seam.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| new shared-prompt module | `apps/prototype-description-service/scene/prompts/caption_system.py` (new; `__init__.py` as needed) | Own markers, `PromptVariant` dataclass (or import-shared equivalent), `PROMPT_VARIANTS` registry with v1/v2/v3 text moved unchanged from `bakeoff.py`, `PRODUCTION_PROMPT_VARIANT`, derived `PRODUCTION_PROMPT_OR_TASK_VERSION`, helpers if needed (`system_prompt_for(variant)`, whitespace normaliser used by tests) |
| production adapter | `…/scene/infrastructure/vlm/gpu_remote_adapter.py` | Delete local `_SYSTEM_PROMPT` and the lockstep comment's "nothing else enforces this" gap; import production system prompt + markers from shared module; default `prompt_or_task_version` from `PRODUCTION_PROMPT_OR_TASK_VERSION`; keep describe payload behaviour identical |
| harness | `…/scripts/eval_harness/bakeoff.py` | Delete local `_PROMPT_V1_SYSTEM`, `_PROMPT_V2_SYSTEM`, and the inline `PROMPT_VARIANTS` construction; import registry + markers from shared module; re-export names tests already import; leave pass-1 / weave / compress / face-gate logic in place |
| settings | `…/scene/config/settings.py` | Default `gpu_prompt_or_task_version` from shared `PRODUCTION_PROMPT_OR_TASK_VERSION` (env override preserved) |
| tests (new) | `…/scene/tests/test_prompt_lineage_seam.py` (new) | Parity + honest-stamp tests with red-first documentation in docstrings |
| tests (correct) | `…/scene/tests/test_gpu_remote_adapter.py`, `test_description_profiles.py`, `test_settings.py`, and any other GPU `"3"` assertions that encode the old default | Expect honest `"1"` (or import the shared constant) |

## Related Files

| File | Note |
| --- | --- |
| `scene/application/hashing.py` | Cache-key composition — read for hazard; **do not edit** |
| `scene/interface_adapters/http/deps.py` | Passes `settings.gpu_prompt_or_task_version` — prefer no edit |
| `scene/interface_adapters/http/schemas/responses.py` | Lane B — field already present; **do not edit** |
| `scripts/eval_harness/caption_metrics.py` | Lane C — **do not edit** |
| `scene/tests/test_eval_harness_pipeline.py` | Keeps importing `PROMPT_VARIANTS` from bakeoff re-export; no forced edit if re-export is clean |
| `scene/infrastructure/vlm/ensemble_decode.py` | Proxies wrapped adapter's `prompt_or_task_version`; no edit if wrapper stays pass-through |

## Verification Strategy

- Deterministic tests (from `apps/prototype-description-service/`):
  - Slice 1:
    `uv run --extra dev pytest scene/tests/test_prompt_lineage_seam.py -q`
    plus
    `uv run --extra dev pytest scene/tests/test_gpu_remote_adapter.py scene/tests/test_eval_harness_pipeline.py -q`
  - Slice 2:
    `uv run --extra dev pytest scene/tests/test_prompt_lineage_seam.py scene/tests/test_settings.py scene/tests/test_description_profiles.py scene/tests/test_gpu_remote_adapter.py -q`
  - Branch-complete scoped regression:
    `uv run --extra dev pytest scene/tests/ -k "prompt_lineage or gpu_remote or eval_harness_pipeline or description_profiles or settings" -q`
- Runtime-parity / environment checks: none required (no live GPU; transport
  stays stubbed).
- Contract/fixture verification: none — schema unchanged.
- Manual verification: none.

## Slice Delivery

### Slice 1: Single prompt source + non-vacuous parity test

**Goal**: One module owns caption system-prompt text; production and harness v1
consume it; a parity test fails when the two consumer bindings diverge.

**Canon**: [REF-26]
(`canon/lexicons/engineering.md` →
`canon/distilled/engineering/pragmatic-programmer.md`);
[REF-10]
(`canon/lexicons/engineering.md` →
`canon/distilled/engineering/refactoring-fowler-beck.md` +
`canon/distilled/engineering/modern-software-engineering.md`);
[TEST-15]
(`canon/lexicons/engineering.md` →
`canon/distilled/engineering/modern-software-engineering.md`).

Changes:

- Add `scene/prompts/caption_system.py` (and package init) containing:
  - `CONTEXT_BEGIN` / `CONTEXT_END` (same string values as today).
  - `PromptVariant` dataclass (same fields as today's bakeoff dataclass:
    `name`, `system`, `system_long`, `three_surface=False`).
  - `PROMPT_VARIANTS` with v1/v2/v3 entries moved **without wording changes**
    from `bakeoff.py` (including the v1 long-band replace
    `"2-4 plain sentences" → "4-8 plain sentences"` and the v2 long-band
    replace `"Write 2-4 sentences." → "Write 4-8 sentences."`).
  - `PRODUCTION_PROMPT_VARIANT = "v1"`.
  - `production_system_prompt()` / module-level
    `PRODUCTION_SYSTEM_PROMPT` bound to
    `PROMPT_VARIANTS[PRODUCTION_PROMPT_VARIANT].system`.
- Rewire `gpu_remote_adapter.py`:
  - Import `PRODUCTION_SYSTEM_PROMPT` (or equivalent) and markers.
  - Use that string in the chat payload system message (same place as today's
    `_SYSTEM_PROMPT`).
  - Delete the local duplicated v1 body. Replace the "Keep in lockstep…"
    comment with a pointer to the shared module and the parity test path.
- Rewire `bakeoff.py`:
  - Import `PROMPT_VARIANTS`, `DEFAULT_PROMPT_VARIANT` (harness default remains
    `"v1"`), and markers from the shared module.
  - Delete local `_PROMPT_V1_SYSTEM` / `_PROMPT_V2_SYSTEM` / local registry
    construction.
  - Re-export `PROMPT_VARIANTS`, `DEFAULT_PROMPT_VARIANT`, and `PromptVariant`
    so `from scripts.eval_harness.bakeoff import PROMPT_VARIANTS` keeps working.
  - Leave `_PASS1_SYSTEM_PROMPT`, `_WEAVE_INSTRUCTIONS`,
    `_V3_THREE_SURFACE_INSTRUCTIONS`, `_COMPRESS_SYSTEM_PROMPT` in bakeoff
    ([REF-10]: different pipeline-stage knowledge).
- Add `scene/tests/test_prompt_lineage_seam.py` with the parity test below.

Proof:

```bash
cd apps/prototype-description-service
uv run --extra dev pytest scene/tests/test_prompt_lineage_seam.py scene/tests/test_gpu_remote_adapter.py scene/tests/test_eval_harness_pipeline.py -q
```

#### [TEST-15] red-first proof — parity test

**Test name (proposed):**
`test_production_system_prompt_matches_harness_v1`

**What it asserts (non-vacuous binding sites):**

1. Import the production consumer binding actually used at describe time —
   e.g. the module attribute `gpu_remote_adapter` uses when building
   `messages[0]["content"]` (after Slice 1 this is the imported production
   system prompt, **not** a second import of the shared constant under a
   different alias in the test alone).
2. Import the harness consumer binding —
   `scripts.eval_harness.bakeoff.PROMPT_VARIANTS["v1"].system` (the object
   `BakeoffClient` selects for `--prompt-variant v1`).
3. Assert whitespace-normalised equality:
   `re.sub(r"\s+", " ", prod.strip()) == re.sub(r"\s+", " ", harness_v1.strip())`.
4. Optionally assert a live transport-stubbed production `describe()` posts
   that exact system string (extends the existing bakeoff-aligned prompt test
   in `test_gpu_remote_adapter.py`).

**(a) Exact edit that makes it go red**

- In `gpu_remote_adapter.py`, re-introduce a local system-prompt string that
  differs by any non-whitespace character (e.g. append `" RED."`) and wire the
  describe payload to that local string instead of the shared production
  binding → parity test **must fail**.
- Symmetric red: in `bakeoff.py`, re-bind
  `PROMPT_VARIANTS["v1"]` to a `PromptVariant` whose `system` differs from the
  shared production text → parity test **must fail**.

**(b) Discrimination case (proves the check is not vacuous)**

- A vacuous alternative would be:
  `assert caption_system.PRODUCTION_SYSTEM_PROMPT == caption_system.PRODUCTION_SYSTEM_PROMPT`
  or comparing two imports of the same shared symbol only. That stays green
  even when the adapter has been re-wired to a divergent local string.
- The shipped test **must** read through the two consumer modules' runtime
  binding sites listed above. Document this in the test docstring so a later
  "simplify the imports" refactor cannot silently vacate the assertion.
- Permanent discrimination guard (recommended): also assert that the production
  system string equals
  `PROMPT_VARIANTS[PRODUCTION_PROMPT_VARIANT].system` **and** that
  `PRODUCTION_PROMPT_VARIANT == "v1"` today — so selecting a different
  production variant without updating the parity expectation is a deliberate,
  visible edit.

**Inventory guard (pre-empts "second copy still alive"):**

- After extraction, `grep -rn 'You write alt text for images on a personal website' apps/prototype-description-service --include='*.py'`
  must hit **only** the shared module (plus any test that quotes a snippet).
  Zero hits in `gpu_remote_adapter.py` or as a string literal body in
  `bakeoff.py`.
- Same for the unique weave clause
  `"Weave the people's names and factual details it supplies"`.

### Slice 2: Honest `prompt_or_task_version` derived from shipped text

**Goal**: The GPU version stamp names the prompt text that actually ships;
defaults and tests stop lying `"3"` over v1 text; cache-key consequence is
accepted without a shim.

**Canon**: [PROV-09]
(`canon/lexicons/ml-systems.md` →
`canon/distilled/ml-systems/ai-engineering.md`);
[NAME-03]
(`canon/lexicons/engineering.md` →
`canon/distilled/engineering/programmers-brain.md`);
[PROV-01]
(`canon/lexicons/ml-systems.md` →
`canon/distilled/ml-systems/model-cards.md`);
[TEST-15]
(`canon/lexicons/engineering.md` →
`canon/distilled/engineering/modern-software-engineering.md`).

Changes:

- In the shared module, co-locate production selection with version derivation:
  ```text
  PRODUCTION_PROMPT_VARIANT = "v1"
  _VARIANT_TO_TASK_VERSION = {"v1": "1", "v2": "2", "v3": "3"}
  PRODUCTION_PROMPT_OR_TASK_VERSION = _VARIANT_TO_TASK_VERSION[PRODUCTION_PROMPT_VARIANT]
  ```
  The stamp is **derived** from the selected variant key. It is not a second
  independently maintained string that can drift to `"3"` while the variant
  remains `"v1"`. A future promotion edits `PRODUCTION_PROMPT_VARIANT` (and
  thus the derived stamp) in the same module as the text being shipped.
- `settings.py`:
  `gpu_prompt_or_task_version` default_factory uses
  `os.environ.get("ACX_GPU_PROMPT_VERSION", PRODUCTION_PROMPT_OR_TASK_VERSION)`.
- `gpu_remote_adapter.py`:
  constructor default `prompt_or_task_version=PRODUCTION_PROMPT_OR_TASK_VERSION`
  (not `"3"`).
- Correct tests that encoded the lie:
  - `test_gpu_remote_adapter.py` — stop asserting `"3"`; assert the shared
    constant / `"1"`.
  - `test_description_profiles.py` — resolved GPU adapters expose `"1"` under
    default env.
  - `test_settings.py` — add assertion that default
    `gpu_prompt_or_task_version == PRODUCTION_PROMPT_OR_TASK_VERSION == "1"`.
  - Any other hard-coded GPU `"3"` expectations that break under the honest
    default (stubs that *intentionally* pass an explicit version remain free
    to pass `"3"` as a caller-supplied override — only **defaults** must be
    honest).
- Do **not** add migration code, dual-key cache reads, or a compatibility
  alias from `"3"` → v1 text.

Proof:

```bash
cd apps/prototype-description-service
uv run --extra dev pytest scene/tests/test_prompt_lineage_seam.py scene/tests/test_settings.py scene/tests/test_description_profiles.py scene/tests/test_gpu_remote_adapter.py -q
```

#### [TEST-15] red-first proof — honest version stamp

**Test names (proposed):**

- `test_gpu_prompt_version_default_matches_production_variant`
- `test_production_prompt_version_is_derived_not_free_floating`

**What they assert:**

1. With `ACX_GPU_PROMPT_VERSION` unset,
   `DescriptionSettings().gpu_prompt_or_task_version == "1"`.
2. `GpuRemoteDescriptionAdapter(... default ...).prompt_or_task_version == "1"`.
3. `PRODUCTION_PROMPT_OR_TASK_VERSION == _VARIANT_TO_TASK_VERSION[PRODUCTION_PROMPT_VARIANT]`.
4. The production system prompt text equals
   `PROMPT_VARIANTS[PRODUCTION_PROMPT_VARIANT].system` (ties stamp lineage to
   text identity — [PROV-01] / [PROV-09]).
5. Negative honesty check: production-selected variant is `"v1"` **and**
   default stamp is **not** `"3"` (names the bug class this slice kills —
   [NAME-03]).

**(a) Exact edit that makes it go red**

- Change `_VARIANT_TO_TASK_VERSION["v1"]` to `"3"` while
  `PRODUCTION_PROMPT_VARIANT` stays `"v1"` → test (5) / derived-honesty
  assertions fail (or, if the map is the sole derivation, change the test's
  expected pairing by forcing `PRODUCTION_PROMPT_VARIANT = "v1"` and expecting
  stamp `"1"` — the red is: any code path that restores default `"3"` for
  production v1 text).
- Concrete production-path red: restore
  `settings.py` default to literal `"3"` →
  `test_gpu_prompt_version_default_matches_production_variant` fails.

**(b) Discrimination case**

- Prove the stamp tracks selection, not a frozen constant under a new name:
  temporarily point `PRODUCTION_PROMPT_VARIANT` at `"v2"` in a unit test
  (monkeypatch the shared module attribute) and assert the **derived**
  version becomes `"2"` while `PROMPT_VARIANTS["v2"].system` is the production
  system prompt under that patch. A hand-maintained
  `PRODUCTION_PROMPT_OR_TASK_VERSION = "1"` that ignores the variant key would
  fail this discrimination case — that is the point.
- Env override discrimination: with
  `monkeypatch.setenv("ACX_GPU_PROMPT_VERSION", "9")`, settings surface `"9"`
  (operator override still works) while the module's derived production
  constant remains `"1"`. The default-honesty test only applies when the env
  var is unset.

## Consolidated Checklist

### Context and Ownership

- [ ] Loaded governing assessment §1 D1–D3 and §10g Lane A scope before editing.
- [ ] Verified every cited rule ID via definition-anchor grep under
      `canon/lexicons/`; read distilled evidence for each load-bearing rule.
- [ ] Confirmed file ownership: only Lane A paths + new shared-prompt module +
      proving tests; no Lane B schema edits; no Lane C metrics edits.
- [ ] Confirmed prompt-body inventory: exactly two live v1 copies before the
      change; zero local copies after.

### Checklist for Slice 1: Single prompt source + parity test

- [ ] Create `scene/prompts/caption_system.py` with markers, registry (v1/v2/v3
      text unchanged), `PRODUCTION_PROMPT_VARIANT`, production system prompt
      binding.
- [ ] Rewire `gpu_remote_adapter.py` to import production system prompt; delete
      local `_SYSTEM_PROMPT` body.
- [ ] Rewire `bakeoff.py` to import/re-export registry; delete local v1/v2
      string bodies and local registry construction; keep pass-1/weave/compress
      local.
- [ ] Add `test_prompt_lineage_seam.py` parity test reading **consumer**
      binding sites (not a double import of the shared symbol alone).
- [ ] Document red-first edit (a) and discrimination case (b) in the test
      docstring.
- [ ] Grep guard: no residual full v1 body outside the shared module.
- [ ] Verification:
      `uv run --extra dev pytest scene/tests/test_prompt_lineage_seam.py scene/tests/test_gpu_remote_adapter.py scene/tests/test_eval_harness_pipeline.py -q`

### Checklist for Slice 2: Honest version stamp

- [ ] Derive `PRODUCTION_PROMPT_OR_TASK_VERSION` from
      `PRODUCTION_PROMPT_VARIANT` in the shared module (no free-floating
      default).
- [ ] Point `settings.gpu_prompt_or_task_version` default at that derived
      constant (env override preserved).
- [ ] Point `GpuRemoteDescriptionAdapter` constructor default at the same
      constant.
- [ ] Update tests that asserted GPU default `"3"`; add default-honesty +
      derivation discrimination tests.
- [ ] State cache-key consequence in the PR/handoff note: greenfield accept;
      no migration/shim.
- [ ] Verification:
      `uv run --extra dev pytest scene/tests/test_prompt_lineage_seam.py scene/tests/test_settings.py scene/tests/test_description_profiles.py scene/tests/test_gpu_remote_adapter.py -q`

### Review Readiness

- [ ] No boundary-touching schema change left undocumented (expected: none).
- [ ] Parity test cannot pass by reading the same constant twice.
- [ ] Version stamp cannot sit at `"3"` for production v1 text under default env.
- [ ] No second full copy of the production system-prompt body remains under
      `apps/prototype-description-service/`.
- [ ] Cache-key hazard acknowledged; no compatibility shim introduced.
- [ ] F2 / F4 / colour work not smuggled into this branch.

## Stretch Goals

- [ ] Optional module-level `__all__` and a one-line README note under
      `scene/prompts/` pointing promoters at `PRODUCTION_PROMPT_VARIANT`.
- [ ] Optional AST/grep unit test that fails if a string literal starting with
      `"You write alt text for images on a personal website"` appears outside
      `caption_system.py` (stronger than a manual grep; only if cheap).

## Success Criteria

- [ ] Exactly one definition of the production caption system-prompt text;
      production adapter and harness v1 both consume it.
- [ ] `test_production_system_prompt_matches_harness_v1` (or equivalent) is red
      under the documented divergent-local-string edit and green at HEAD.
- [ ] Default `gpu_prompt_or_task_version` is `"1"` when
      `ACX_GPU_PROMPT_VERSION` is unset, matching production v1 text; derived
      from `PRODUCTION_PROMPT_VARIANT`, not hand-maintained beside it.
- [ ] Existing GPU adapter + harness pipeline tests green under
      `uv run --extra dev pytest` with the paths above.
- [ ] No edits to Lane B schema files or Lane C `caption_metrics.py`.
- [ ] No prompt wording changes; no colour vocabulary; no metrics; no
      three-surface production promotion.

## Not-Doing

- Changing what any prompt **says** (F2 emotion-bearer wording, F4
  three-surface production promotion, F1 weave clause rewrite). Unblocked by
  this seam; not shipping in DEPICT-0.
- Metrics, scorers, or any edit to `caption_metrics.py` (Lane C).
- Contract, schema, or enum changes (Lane B).
- Colour vocabulary of any kind (assessment §10e trigger-gated).
- Cache migration, dual-key reads, or `"3"` compatibility shims.
- Moving harness-only pass-1 / weave / compress prompts into the shared module
  ([REF-10]: different knowledge).
- Citing `FM-11`, `HARM-01`, or non-existent `REG`/`ICON`/`FRAM`/`SEL` IDs.

## No canon warrant

- **Mechanical promotion UX** (e.g. an operator CLI flag that flips production
  to v2 without a code edit) is not required by cited canon; the seam only
  needs the registry and production selection to share one module so a
  promotion is a small deliberate edit rather than a hand-copy. No fabricated
  rule ID for "promotability."
- **Whitespace-normalised comparison** as the parity predicate is an
  engineering choice matching the assessment's D1 measurement method, not a
  separate canon row.
