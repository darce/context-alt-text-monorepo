# DEPICT-0. Prompt-lineage seam (one source, parity test, honest version stamp)

Task: DEPICT-0 · Branch: `feature/depict-0` · Status: planned
Date: 2026-07-27 · Author: grok-4.5 (remote flock lane A) · Project: prototype-description-service
Review Coverage Target: 2

> **DEPICT task family**: depiction-canon backlog item 1 (P0) from
> [`docs/assessments/current/depiction-canon-triage-and-backlog-2026-07-27.md`](../../assessments/current/depiction-canon-triage-and-backlog-2026-07-27.md)
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
   single-surface prose. Closing D1 (one production v1 source + parity) is the
   prerequisite so a later v2/v3 promotion can move that variant's text into
   the shared module and flip `PRODUCTION_PROMPT_VARIANT` rather than
   hand-copying strings into the adapter.

Inventory of the production v1 system-prompt body (v1-unique greppable token
`"2-4 plain sentences"` at `gpu_remote_adapter.py:30` and `bakeoff.py:91`):
**exactly two live v1 body literals** — `gpu_remote_adapter.py` and
`bakeoff.py` `_PROMPT_V1_SYSTEM`. No third live copy. Harness-only v2/v3
bodies live only in `bakeoff.py` and are intentionally different text (not
production defects; see Out of Scope / Not-Doing — they stay in bakeoff).

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
  [REF-26]
  (`canon/lexicons/engineering.md` →
  `canon/distilled/engineering/pragmatic-programmer.md`): DRY is knowledge,
  not text. Here the same production-v1 intent is scattered across two consumer
  modules (`gpu_remote_adapter.py` and `bakeoff.py`) — multi-place knowledge
  scatter warrants extraction. REF-26's full acid test is multi-place *and*
  multi-format (code + docs, schema + struct); both live copies are Python
  string constants (same format), so the multi-format half is **not**
  applicable — the extract is warranted by intent duplication alone.
- **Extract only what must change together**
  [REF-10]
  (`canon/lexicons/engineering.md` →
  `canon/distilled/engineering/refactoring-fowler-beck.md` +
  `canon/distilled/engineering/modern-software-engineering.md`): **Fowler** —
  do not merge bodies that will not change together (production v1 and harness
  `PROMPT_VARIANTS["v1"]` *do* change together; harness-only v2/v3 text,
  pass-1 / weave / compress do **not** and stay in `bakeoff.py`). **Farley** —
  DRY within this deployable unit (this service / one deployment pipeline) is
  in bounds; do not invent a cross-service share. Farley's ch-13 rule is a
  cross-*service* boundary (do not share code between independently deployed
  services), not a ban on within-service extraction.
- **Prove the green can go red**
  [TEST-15]
  (`canon/lexicons/engineering.md` →
  `canon/distilled/engineering/modern-software-engineering.md`): a parity test
  that only re-reads the same constant twice certifies nothing.
- **Prompt configuration is production lineage**
  [PROV-09]
  (`canon/lexicons/ml-systems.md` →
  `canon/distilled/ml-systems/ai-engineering.md`): the version stamp on each
  output must identify the prompt text that produced it. This is the
  load-bearing warrant for correcting the dishonest `"3"` default over v1 text
  (with [TEST-15] proving the correction is enforceable).
- **Every output walks back to its evidence**
  [PROV-01]
  (`canon/lexicons/ml-systems.md` →
  `canon/distilled/ml-systems/model-cards.md`): the stamp is part of the
  result's lineage graph (and of the cache key); a mislabelled stamp makes
  reproduction and comparison impossible.
- **NAME-03 note (weak analogy, not a rule hit).**
  [NAME-03] (`canon/lexicons/engineering.md` →
  `canon/distilled/engineering/programmers-brain.md`) is about identifier
  linguistic antipatterns — a name promising a type/behaviour the code lacks.
  The identifier `prompt_or_task_version` *does* hold a version string; only
  the default *value* (`"3"` over v1 text) lies. PROV-09 (+ TEST-15) carry the
  work; do not treat NAME-03 as a load-bearing warrant for this slice.

## Terminology

- **Production system prompt**: the system-role string
  `GpuRemoteDescriptionAdapter` posts on `/v1/chat/completions` today — the
  v1 body currently stored as `_SYSTEM_PROMPT`.
- **Harness v1 / v2 / v3**: named entries in `bakeoff.PROMPT_VARIANTS`. Only v1
  is textually identical to production today. v2 encodes ALTQ-1 style rules;
  v3 reuses v2's system text with `three_surface=True` and a weave addendum.
- **Shared-prompt module**: new single authority under `scene/` for the
  **production** caption system-prompt text (today: v1 body), context markers
  used by that text, the `PromptVariant` dataclass shape, and the
  production-selected variant key + its derived version stamp. Harness-only
  v2/v3 bodies and the full `PROMPT_VARIANTS` registry stay in `bakeoff.py`.
- **Honest version stamp**: the default
  `gpu_prompt_or_task_version` / adapter `prompt_or_task_version` value that
  names the production-selected variant's lineage id (today: `"1"` for v1
  text), obtained via live `production_prompt_or_task_version()` lookup — not
  a free-floating `"3"` and not an import-time-frozen constant that ignores
  `PRODUCTION_PROMPT_VARIANT`.
- **Parity surface**: the two *consumer binding sites* the runtime actually
  uses — the system string the production adapter **POSTs** as
  `messages[0]["content"]` (captured via transport stub on `describe()`), and
  `PROMPT_VARIANTS["v1"].system` as used by `BakeoffClient` — not a double
  import of the shared constant alone, and not an attribute-only comparison.

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
- Harness-only v2/v3 bodies remain in `bakeoff.py` (different knowledge —
  [REF-10]); a later v2/v3 production promotion moves that variant's text into
  the shared module as its own deliberate change, not as part of this seam.
- A deterministic parity test fails if the production runtime system string
  (the string `describe()` actually POSTs as `messages[0]["content"]`) and
  harness `PROMPT_VARIANTS["v1"].system` diverge (whitespace-normalised).
- Default `gpu_prompt_or_task_version` is derived from the production-selected
  variant (today `"1"`) via a live lookup co-located with that selection in the
  shared module — not a free-floating module constant that can ignore the
  selected key.
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
    multi-place knowledge scatter across two consumer modules; multi-format
    half of the acid test not applicable — both copies are Python strings).
  - [REF-10] `canon/lexicons/engineering.md` → distilled
    `canon/distilled/engineering/refactoring-fowler-beck.md` (change-together /
    Extract) + `canon/distilled/engineering/modern-software-engineering.md`
    (ch-13: DRY within one deployment pipeline / deployable unit is in bounds;
    do not share code *between* independently deployed services).
  - [TEST-15] `canon/lexicons/engineering.md` → distilled
    `canon/distilled/engineering/modern-software-engineering.md` (ch-8: predict
    the exact failure message; a test never seen failing is unverified;
    assertion-free / vacuous tests are defects).
  - [PROV-09] `canon/lexicons/ml-systems.md` → distilled
    `canon/distilled/ml-systems/ai-engineering.md` (named mechanism **prompt
    configuration is production lineage** — load-bearing for honest stamp).
  - [PROV-01] `canon/lexicons/ml-systems.md` (**not** `engineering.md`) →
    distilled `canon/distilled/ml-systems/model-cards.md` (versioned model
    reporting; every output walks back to evidence).
  - [NAME-03] `canon/lexicons/engineering.md` → distilled
    `canon/distilled/engineering/programmers-brain.md` (ch-9 linguistic
    antipatterns) — **weak analogy only** for this task; not load-bearing
    (the identifier holds a version string; the default *value* is the lie;
    PROV-09 + TEST-15 carry the warrant).

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
| Eval harness run-record provenance | harness | `prompt_variant` already stamped | v1 body import path may change; `PROMPT_VARIANTS` still built in bakeoff; provenance field names unchanged | no | `pytest scene/tests/ -k eval_harness` green |

Strictly local to the description service. No WP contract change. No bulk/async
surface change.

## Proposed Solution

Introduce a new shared-prompt module under `scene/` that is the single
authority for:

1. Context fence markers used by the caption system prompt
   (`<<<CONTEXT>>>` / `<<<END_CONTEXT>>>`).
2. The **production v1** caption system-prompt body (moved byte-for-byte from
   `gpu_remote_adapter.py` / bakeoff `_PROMPT_V1_SYSTEM`) and the
   `PromptVariant` dataclass shape (same fields as today's bakeoff dataclass).
3. Production selection + **live** version derivation co-located with that body:
   - `PRODUCTION_PROMPT_VARIANT = "v1"` (what the GPU adapter ships today)
   - `_VARIANT_TO_TASK_VERSION = {"v1": "1", "v2": "2", "v3": "3"}` (naming
     scheme for the stamp; v2/v3 keys reserved for a later promotion)
   - `def production_prompt_or_task_version() -> str:` returns
     `_VARIANT_TO_TASK_VERSION[PRODUCTION_PROMPT_VARIANT]` — a **live lookup**,
     not a module-level constant bound once at import.

**Not moved into the shared module (harness-only; [REF-10]):**

- v2 / v3 system-prompt bodies and the full `PROMPT_VARIANTS` registry
  construction remain in `bakeoff.py`. Production does not execute those paths
  today; shipping them in the production package would put harness-only text
  on a surface it never runs (plan's own harness-only-stays-put criterion).
- `DEFAULT_PROMPT_VARIANT = "v1"` stays defined and exported in `bakeoff.py`
  (harness CLI default at `bakeoff.py:154` today; distinct from
  `PRODUCTION_PROMPT_VARIANT`). Importers such as
  `test_eval_harness_pipeline.py:22` keep
  `from scripts.eval_harness.bakeoff import DEFAULT_PROMPT_VARIANT`.
- Pass-1 / weave / compress prompts stay in `bakeoff.py`.

Consumers:

- `gpu_remote_adapter.py` imports production system prompt + markers; deletes
  local `_SYSTEM_PROMPT` / local marker constants used only for that prompt;
  constructor default for `prompt_or_task_version` calls
  `production_prompt_or_task_version()` at init time (not a frozen import-time
  constant).
- `bakeoff.py` imports the shared v1 body, markers, and `PromptVariant`;
  deletes local `_PROMPT_V1_SYSTEM`; keeps local `_PROMPT_V2_SYSTEM` and builds
  `PROMPT_VARIANTS` in place (v1 entry bound to the shared v1 body; v2/v3
  unchanged local text); keeps `DEFAULT_PROMPT_VARIANT = "v1"` locally;
  re-exports `PROMPT_VARIANTS` / `DEFAULT_PROMPT_VARIANT` / `PromptVariant` so
  existing `from scripts.eval_harness.bakeoff import PROMPT_VARIANTS` tests
  keep working.
- `settings.py` default for `gpu_prompt_or_task_version` becomes
  `os.environ.get("ACX_GPU_PROMPT_VERSION", production_prompt_or_task_version())`
  so the env override remains, but the **unconfigured** default is a live
  honest lookup.

Tests (same slices as the behaviour they load-bear):

- **Parity** between production consumer binding (posted system message) and
  harness v1 consumer binding, with explicit red-first and discrimination
  cases ([TEST-15]).
- **Honest stamp** between production-selected variant key and default
  version, with red-first and discrimination cases ([PROV-09], [PROV-01],
  [TEST-15]).
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

**No inbound dependency blocks landing this task.** Lane B / Lane C need no
edits for DEPICT-0 to merge.

| Need | File | Exact change | Lane | Ordering |
| --- | --- | --- | --- | --- |
| — | — | No Lane B schema/enum edit required; field already exists as a free string. | B | n/a |
| — | — | No Lane C metrics edit required. | C | n/a |

**Downstream (explicitly unowned by this plan):** DEPICT-1 declares a weave-
integration dependency on DEPICT-0 (DEPICT-1 §Cross-lane dependency,
`gpu_remote_adapter.py` / bakeoff voice-honouring prompt change after the seam
closes). This plan **Not-Does** F1 weave-instruction rewrite and does **not**
deliver weave-side context consumption. After all three current depiction lanes
merge, the F1 weave half remains open — no lane in this wave owns weave-side
context consumption. Do not silently absorb that work here.

`deps.py` already threads `settings.gpu_prompt_or_task_version`; once settings
defaults honestly, resolvers pick up the fix without an owned-file edit. If a
future promotion wants production to ship v2 text, that is a later DEPICT
slice (move v2 body into the shared module + flip
`PRODUCTION_PROMPT_VARIANT`), not this seam.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| new shared-prompt module | `apps/prototype-description-service/scene/prompts/caption_system.py` (new; `__init__.py` as needed) | Own markers, `PromptVariant` dataclass, production v1 system body, `PRODUCTION_PROMPT_VARIANT`, `_VARIANT_TO_TASK_VERSION`, live `production_prompt_or_task_version()`, `PRODUCTION_SYSTEM_PROMPT` bound to the v1 body; **not** the v2/v3 bodies or full `PROMPT_VARIANTS` registry |
| production adapter | `…/scene/infrastructure/vlm/gpu_remote_adapter.py` | Delete local `_SYSTEM_PROMPT` and the lockstep comment's "nothing else enforces this" gap; import production system prompt + markers from shared module; default `prompt_or_task_version` via live `production_prompt_or_task_version()`; keep describe payload behaviour identical |
| harness | `…/scripts/eval_harness/bakeoff.py` | Delete local `_PROMPT_V1_SYSTEM` only; import shared v1 body + markers + `PromptVariant`; keep `_PROMPT_V2_SYSTEM` and build `PROMPT_VARIANTS` locally (v1 entry uses shared body); keep `DEFAULT_PROMPT_VARIANT = "v1"` defined here; re-export names tests already import; leave pass-1 / weave / compress / face-gate logic in place |
| settings | `…/scene/config/settings.py` | Default `gpu_prompt_or_task_version` from live `production_prompt_or_task_version()` (env override preserved) |
| tests (new) | `…/scene/tests/test_prompt_lineage_seam.py` (new) | Parity (transport-stubbed posted system string) + honest-stamp tests with red-first documentation in docstrings |
| tests (correct) | `…/scene/tests/test_gpu_remote_adapter.py`, `test_description_profiles.py`, `test_settings.py`, and any other GPU `"3"` assertions that encode the old default | Expect honest `"1"` (or call the shared live lookup) |

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
  - `CONTEXT_BEGIN` / `CONTEXT_END` (same string values as today:
    `<<<CONTEXT>>>` / `<<<END_CONTEXT>>>`).
  - `PromptVariant` dataclass (same fields as today's bakeoff dataclass at
    `bakeoff.py:124-136`: `name`, `system`, `system_long`,
    `three_surface=False`).
  - Production v1 system body moved **without wording changes** from
    `gpu_remote_adapter.py:28-37` / `bakeoff.py:89-98` (the shared
    `PRODUCTION_SYSTEM_PROMPT` / `V1_SYSTEM_PROMPT`).
  - `PRODUCTION_PROMPT_VARIANT = "v1"`.
  - **Do not** move v2/v3 bodies or the full `PROMPT_VARIANTS` registry here
    ([REF-10]; harness-only text stays in `bakeoff.py`).
  - **Do not** define `DEFAULT_PROMPT_VARIANT` here — that harness default
    remains in `bakeoff.py` (see rewire below).
- Rewire `gpu_remote_adapter.py`:
  - Import `PRODUCTION_SYSTEM_PROMPT` (or equivalent) and markers.
  - Use that string in the chat payload system message at the same site as
    today's `_SYSTEM_PROMPT` (`gpu_remote_adapter.py:182`
    `messages[0]["content"]`).
  - Delete the local duplicated v1 body. Replace the "Keep in lockstep…"
    comment with a pointer to the shared module and the parity test path.
- Rewire `bakeoff.py`:
  - Import shared v1 body, markers, and `PromptVariant` from the shared
    module.
  - Delete local `_PROMPT_V1_SYSTEM` only. Keep local `_PROMPT_V2_SYSTEM`.
  - Build `PROMPT_VARIANTS` locally: v1 entry uses the shared v1 body (and the
    same long-band replace `"2-4 plain sentences" → "4-8 plain sentences"`);
    v2/v3 entries keep today's local text and long-band replace unchanged.
  - Keep `DEFAULT_PROMPT_VARIANT = "v1"` **defined and exported in bakeoff.py**
    (today at `bakeoff.py:154`; still imported by
    `test_eval_harness_pipeline.py:22`). Do **not** import it from the shared
    module (it is not defined there).
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

**What it asserts (mandatory non-vacuous binding sites):**

1. **Transport-stubbed production path (mandatory, not optional).** Construct
   `GpuRemoteDescriptionAdapter` with `httpx.MockTransport` (same pattern as
   `test_gpu_remote_adapter.py:35-86`
   `test_gpu_remote_adapter_posts_bakeoff_aligned_prompt_and_returns_adapter_result`).
   Call `describe(...)`. Capture the posted JSON payload and read
   `messages[0]["content"]` (the system role string actually POSTed — today
   wired at `gpu_remote_adapter.py:182`).
2. Import the harness consumer binding —
   `scripts.eval_harness.bakeoff.PROMPT_VARIANTS["v1"].system` (the object
   `BakeoffClient` selects for `--prompt-variant v1`).
3. Assert **whitespace-normalised equality** of the two strings:
   `re.sub(r"\s+", " ", posted_system.strip()) == re.sub(r"\s+", " ", harness_v1.strip())`
   where `posted_system = captured_payload["messages"][0]["content"]` and
   `harness_v1 = bakeoff.PROMPT_VARIANTS["v1"].system`.
4. **Forbid attribute-only comparison.** The test docstring **must** state that
   comparing module attributes / shared-constant imports alone
   (e.g. `gpu_remote_adapter.PRODUCTION_SYSTEM_PROMPT` vs
   `caption_system.PRODUCTION_SYSTEM_PROMPT`, or two aliases of the same
   shared symbol) is **not** a valid form of this test. Existing
   `test_gpu_remote_adapter.py` only substring-checks the posted system
   message (`"Never name or guess" in …`); that does **not** close this hole —
   the new test owns full whitespace-normalised equality against harness v1.

**(a) Exact edit that makes it go red**

- Change **only** the string inserted into the describe payload's
  `messages[0]["content"]` in `gpu_remote_adapter.py` so it differs by any
  non-whitespace character from the shared/harness v1 body (e.g. append
  `" RED."` at the payload site, or re-bind the payload to a local divergent
  literal). Do **not** redefine a module attribute that the test never reads.
  Under that edit the transport-captured equality assertion **must fail**.
- Symmetric red: in `bakeoff.py`, re-bind
  `PROMPT_VARIANTS["v1"]` to a `PromptVariant` whose `system` differs from the
  string the adapter POSTs → parity test **must fail**.

**(b) Discrimination case (proves the check is not vacuous)**

- A vacuous alternative would be:
  `assert caption_system.PRODUCTION_SYSTEM_PROMPT == caption_system.PRODUCTION_SYSTEM_PROMPT`
  or comparing two imports of the same shared symbol only, or comparing a
  module attribute the adapter no longer uses in the payload. Those stay green
  even when the adapter has been re-wired to a divergent local payload string
  — which is exactly why attribute-only comparison is forbidden.
- An always-constant / no-op implementation (e.g. assert `True`, or assert two
  hard-coded identical literals in the test) also stays green under the red
  edit in (a). The shipped test fails that discrimination because it reads the
  **posted** system string and the harness registry entry.
- Permanent discrimination guard (recommended): also assert
  `PRODUCTION_PROMPT_VARIANT == "v1"` today and that the posted system string
  equals the shared `PRODUCTION_SYSTEM_PROMPT` — so a future promotion that
  flips production selection without updating the parity expectation is a
  deliberate, visible edit.

**Inventory guard (pre-empts "second copy still alive"):**

- After extraction, grep the **v1-unique, source-greppable** sentence-band
  token `"2-4 plain sentences"` (present in production/harness v1 body at
  `gpu_remote_adapter.py:30` / `bakeoff.py:91` today; **not** in the v2 body,
  which uses `"Write 2-4 sentences."` — verified against
  `bakeoff.py:105-121`). Allowed post-extraction hits:
  - the shared module (the v1 body literal),
  - bakeoff's long-band `.replace("2-4 plain sentences", "4-8 plain sentences")`
    on the imported v1 body (string appears as the replace argument, not a
    second full body),
  - tests that quote the token (e.g. `test_eval_harness_pipeline.py:113-117`).
  **Forbidden:** a full v1 body literal still in `gpu_remote_adapter.py` or a
  second `_PROMPT_V1_SYSTEM`-style body in `bakeoff.py`.
- Do **not** use as the single-source grep:
  - `"You write alt text for images on a personal website"` — shared opener
    with local v2 text.
  - `"Weave the people's names and factual details it supplies"` — also in
    the v2 body (`bakeoff.py:116-118` when lines are joined).

### Slice 2: Honest `prompt_or_task_version` derived from shipped text

**Goal**: The GPU version stamp names the prompt text that actually ships;
defaults and tests stop lying `"3"` over v1 text; cache-key consequence is
accepted without a shim.

**Canon**: [PROV-09]
(`canon/lexicons/ml-systems.md` →
`canon/distilled/ml-systems/ai-engineering.md`);
[PROV-01]
(`canon/lexicons/ml-systems.md` →
`canon/distilled/ml-systems/model-cards.md`);
[TEST-15]
(`canon/lexicons/engineering.md` →
`canon/distilled/engineering/modern-software-engineering.md`).
([NAME-03] is a weak analogy only — see Workflow Principles; not load-bearing.)

Changes:

- In the shared module, co-locate production selection with **live** version
  derivation (not an import-time constant):
  ```text
  PRODUCTION_PROMPT_VARIANT = "v1"
  _VARIANT_TO_TASK_VERSION = {"v1": "1", "v2": "2", "v3": "3"}

  def production_prompt_or_task_version() -> str:
      return _VARIANT_TO_TASK_VERSION[PRODUCTION_PROMPT_VARIANT]
  ```
  The stamp is **looked up** from the selected variant key on each call. It is
  not a free-floating module-level
  `PRODUCTION_PROMPT_OR_TASK_VERSION = "1"` that can ignore
  `PRODUCTION_PROMPT_VARIANT`, and it is not a once-bound
  `PRODUCTION_PROMPT_OR_TASK_VERSION = _VARIANT_TO_TASK_VERSION[PRODUCTION_PROMPT_VARIANT]`
  constant that freezes the value at import (monkeypatching the variant key
  after import would not update such a constant). A future promotion that
  moves v2 text into this module also flips `PRODUCTION_PROMPT_VARIANT` so the
  live lookup yields `"2"`.
- `settings.py`:
  `gpu_prompt_or_task_version` default_factory uses
  `os.environ.get("ACX_GPU_PROMPT_VERSION", production_prompt_or_task_version())`
  so each settings construction re-evaluates the live lookup when the env var
  is unset.
- `gpu_remote_adapter.py`:
  constructor must not bake an import-time default of a frozen string.
  Preferred shape: default parameter `prompt_or_task_version: str | None = None`
  and inside `__init__` assign
  `self.prompt_or_task_version = prompt_or_task_version if prompt_or_task_version is not None else production_prompt_or_task_version()`
  so a monkeypatched `PRODUCTION_PROMPT_VARIANT` is visible on new instances.
  (A bare default-arg call evaluated at `def` time would re-freeze the value.)
- Correct tests that encoded the lie:
  - `test_gpu_remote_adapter.py` — stop asserting `"3"`; assert
    `production_prompt_or_task_version()` / `"1"` under default env.
  - `test_description_profiles.py` — resolved GPU adapters expose `"1"` under
    default env.
  - `test_settings.py` — add assertion that default
    `gpu_prompt_or_task_version == production_prompt_or_task_version() == "1"`.
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
2. `GpuRemoteDescriptionAdapter(... default ...).prompt_or_task_version == "1"`
   (construct without passing `prompt_or_task_version`, so the live default
   path runs).
3. `production_prompt_or_task_version() == _VARIANT_TO_TASK_VERSION[PRODUCTION_PROMPT_VARIANT]`
   and, under today's selection,
   `PRODUCTION_PROMPT_VARIANT == "v1"` and the function returns `"1"`.
4. The production system prompt text equals the shared v1 body
   (`PRODUCTION_SYSTEM_PROMPT`) that the adapter POSTs (ties stamp lineage to
   text identity — [PROV-01] / [PROV-09]). Do **not** require
   `PROMPT_VARIANTS` to live in the shared module for this assertion; harness
   `bakeoff.PROMPT_VARIANTS["v1"].system` is already locked to that body by the
   Slice 1 parity test.
5. Negative honesty check: production-selected variant is `"v1"` **and**
   default stamp is **not** `"3"` (names the bug class this slice kills —
   dishonest value over v1 text; warrant is [PROV-09], not NAME-03).

**(a) Exact edit that makes it go red**

- Change `_VARIANT_TO_TASK_VERSION["v1"]` to `"3"` while
  `PRODUCTION_PROMPT_VARIANT` stays `"v1"` → assertions (1)/(2)/(3)/(5) fail
  (function now returns `"3"` for production v1).
- Concrete production-path red: restore
  `settings.py` default to literal `"3"` →
  `test_gpu_prompt_version_default_matches_production_variant` fails.
- Free-floating regression red: replace the live function body with
  `return "1"` (ignore the map / variant key) → discrimination case (b) fails
  even though assertions (1)–(2) stay green under the default selection.

**(b) Discrimination case**

- Prove the stamp tracks selection via **live lookup**, not a frozen
  import-time constant under a new name:
  1. `monkeypatch.setattr(caption_system, "PRODUCTION_PROMPT_VARIANT", "v2")`
     (or patch the attribute on the module under test).
  2. Assert `production_prompt_or_task_version() == "2"`.
  3. Construct a fresh `GpuRemoteDescriptionAdapter` without an explicit
     `prompt_or_task_version` and assert
     `.prompt_or_task_version == "2"`.
  A hand-maintained `PRODUCTION_PROMPT_OR_TASK_VERSION = "1"` module constant
  (or a once-bound import-time constant, or a function that always returns
  `"1"`) fails this discrimination case — that is the point. Because the plan
  uses a live function, monkeypatching the variant key is reachable; a module
  constant would make this case dead.
- Env override discrimination: with
  `monkeypatch.setenv("ACX_GPU_PROMPT_VERSION", "9")`, settings surface `"9"`
  (operator override still works) while
  `production_prompt_or_task_version()` remains `"1"` under the default
  variant key. The default-honesty test only applies when the env var is
  unset.

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

- [ ] Create `scene/prompts/caption_system.py` with markers, `PromptVariant`,
      production v1 body, `PRODUCTION_PROMPT_VARIANT`, production system prompt
      binding — **not** v2/v3 bodies or full `PROMPT_VARIANTS`.
- [ ] Rewire `gpu_remote_adapter.py` to import production system prompt; delete
      local `_SYSTEM_PROMPT` body; use shared string at the payload site
      (`messages[0]["content"]`).
- [ ] Rewire `bakeoff.py`: import shared v1 body + `PromptVariant`; delete local
      `_PROMPT_V1_SYSTEM` only; keep `_PROMPT_V2_SYSTEM` and local
      `PROMPT_VARIANTS` construction; keep `DEFAULT_PROMPT_VARIANT = "v1"`
      defined in bakeoff; keep pass-1/weave/compress local.
- [ ] Add `test_prompt_lineage_seam.py` parity test that **transport-stubs**
      `describe()`, captures `messages[0]["content"]`, and asserts
      whitespace-normalised equality to
      `bakeoff.PROMPT_VARIANTS["v1"].system` (attribute-only comparison
      forbidden in the docstring).
- [ ] Document red-first edit (a) — change only the payload-inserted string —
      and discrimination case (b) in the test docstring.
- [ ] Grep guard: no residual full v1 body outside the shared module (unique
      weave clause is the hard single-source check).
- [ ] Verification:
      `uv run --extra dev pytest scene/tests/test_prompt_lineage_seam.py scene/tests/test_gpu_remote_adapter.py scene/tests/test_eval_harness_pipeline.py -q`

### Checklist for Slice 2: Honest version stamp

- [ ] Add live `production_prompt_or_task_version()` that subscripts
      `_VARIANT_TO_TASK_VERSION[PRODUCTION_PROMPT_VARIANT]` (no free-floating
      or import-time-frozen default).
- [ ] Point `settings.gpu_prompt_or_task_version` default_factory at that live
      lookup (env override preserved).
- [ ] Point `GpuRemoteDescriptionAdapter` constructor default through the live
      lookup at init time (not a frozen default-arg constant).
- [ ] Update tests that asserted GPU default `"3"`; add default-honesty +
      derivation discrimination tests (monkeypatch
      `PRODUCTION_PROMPT_VARIANT` → `"v2"`, expect `"2"` from the live
      function and a fresh adapter instance).
- [ ] State cache-key consequence in the PR/handoff note: greenfield accept;
      no migration/shim.
- [ ] Verification:
      `uv run --extra dev pytest scene/tests/test_prompt_lineage_seam.py scene/tests/test_settings.py scene/tests/test_description_profiles.py scene/tests/test_gpu_remote_adapter.py -q`

### Review Readiness

- [ ] No boundary-touching schema change left undocumented (expected: none).
- [ ] Parity test cannot pass by reading the same constant twice or by
      attribute-only comparison; it reads the posted system string.
- [ ] Version stamp cannot sit at `"3"` for production v1 text under default env.
- [ ] Live derivation discrimination reaches red under a free-floating
      always-`"1"` implementation.
- [ ] No second full copy of the production system-prompt body remains under
      `apps/prototype-description-service/`.
- [ ] Harness-only v2/v3 bodies remain in `bakeoff.py` (not shipped as unused
      production registry entries).
- [ ] Cache-key hazard acknowledged; no compatibility shim introduced.
- [ ] DEPICT-1 weave-side F1 consumption explicitly unowned / Not-Done.
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
      under the documented payload-string edit and green at HEAD; it compares
      the transport-captured posted system string to
      `bakeoff.PROMPT_VARIANTS["v1"].system`.
- [ ] Default `gpu_prompt_or_task_version` is `"1"` when
      `ACX_GPU_PROMPT_VERSION` is unset, matching production v1 text; returned
      by live `production_prompt_or_task_version()` from
      `PRODUCTION_PROMPT_VARIANT`, not hand-maintained beside it.
- [ ] Derivation discrimination: monkeypatching `PRODUCTION_PROMPT_VARIANT` to
      `"v2"` makes the live lookup (and a fresh adapter default) return `"2"`.
- [ ] Existing GPU adapter + harness pipeline tests green under
      `uv run --extra dev pytest` with the paths above.
- [ ] No edits to Lane B schema files or Lane C `caption_metrics.py`.
- [ ] No prompt wording changes; no colour vocabulary; no metrics; no
      three-surface production promotion.

## Not-Doing

- Changing what any prompt **says** (F2 emotion-bearer wording, F4
  three-surface production promotion, F1 weave clause rewrite). Unblocked by
  this seam; not shipping in DEPICT-0.
- **Weave-side context consumption / F1 voice-honouring prompt behaviour**
  that DEPICT-1 declares as a downstream dependency on DEPICT-0. This plan
  closes the dual-prompt *seam* only; no lane in this wave owns the weave
  rewrite. Leave it explicitly open.
- Moving harness-only v2/v3 prompt bodies or the full `PROMPT_VARIANTS`
  registry into the production shared module ([REF-10]: different knowledge;
  production does not execute those paths today).
- Metrics, scorers, or any edit to `caption_metrics.py` (Lane C).
- Contract, schema, or enum changes (Lane B).
- Colour vocabulary of any kind (assessment §10e trigger-gated).
- Cache migration, dual-key reads, or `"3"` compatibility shims.
- Moving harness-only pass-1 / weave / compress prompts into the shared module
  ([REF-10]: different knowledge).
- Citing `FM-11`, `HARM-01`, or non-existent `REG`/`ICON`/`FRAM`/`SEL` IDs.
- Treating [NAME-03] as a load-bearing warrant for the dishonest stamp (weak
  analogy only; PROV-09 + TEST-15 carry the work).

## No canon warrant

- **Mechanical promotion UX** (e.g. an operator CLI flag that flips production
  to v2 without a code edit) is not required by cited canon; the seam only
  needs the registry and production selection to share one module so a
  promotion is a small deliberate edit rather than a hand-copy. No fabricated
  rule ID for "promotability."
- **Whitespace-normalised comparison** as the parity predicate is an
  engineering choice matching the assessment's D1 measurement method, not a
  separate canon row.
