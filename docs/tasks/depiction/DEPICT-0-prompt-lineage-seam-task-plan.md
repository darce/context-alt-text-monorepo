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
`prompt_or_task_version` honestly labels the prompt text that actually ships
(stamp = selected `ProductionPrompt.lineage_version` only — no free-string
env override **and no free-string constructor kwarg** that can stamp a
different lineage than the posted body).

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
2. **D2 — lying version stamp (default + free-string constructor hole).**
   `scene/config/settings.py:40` `gpu_prompt_or_task_version` defaults to
   `"3"` (`ACX_GPU_PROMPT_VERSION`) while the prompt text it labels is v1.
   The same default is hard-coded on
   `GpuRemoteDescriptionAdapter.__init__` (`prompt_or_task_version: str = "3"`
   at `gpu_remote_adapter.py:133`) and assigned straight to
   `self.prompt_or_task_version` at `gpu_remote_adapter.py:143`. That free-
   string kwarg is itself a lineage hole: `GpuRemoteDescriptionAdapter(
   prompt_or_task_version="9")` posts the v1 body (`gpu_remote_adapter.py:182`)
   under stamp `"9"` with no mandated proof going red. Production wiring
   stamps via `deps.py:98`
   (`prompt_or_task_version=settings.gpu_prompt_or_task_version`). The field
   is stamped into `scene` rows **and into the description cache key**
   (`scene/application/hashing.py`:
   `(tenant_id, image_hash, adapter, model_version, prompt_or_task_version,
   context_hash)`). Cross-version quality comparisons keyed on that field are
   mislabelled; a real v2/v3 promotion cannot be distinguished from today by
   the stamp. **This plan removes the free-string constructor override**
   (stamp binds only from the selected `ProductionPrompt`); DPR3-M-02's
   preserve-the-override requirement is **wontfix / superseded** by this
   resolution — do not reinstate it.
3. **D3 — v3 promotion window still open.**
   No three-surface JSON path exists outside the harness; production returns
   single-surface prose. Closing D1 (one production v1 source + parity) is the
   prerequisite so a later v2/v3 promotion can replace the selected
   `ProductionPrompt` (body + lineage version as one object) rather than
   hand-copying strings into the adapter while the stamp drifts separately.

Inventory of the production v1 system-prompt body (assembled value today
from the multi-line / f-string construction at `gpu_remote_adapter.py:28-37`
and `bakeoff.py:89-98`; v1-unique token `"2-4 plain sentences"` appears at
`gpu_remote_adapter.py:30` and `bakeoff.py:91` but is **not** the inventory
key — see Slice 1 assembled-value inventory): **exactly two live v1 body
definitions** — `gpu_remote_adapter.py` and `bakeoff.py` `_PROMPT_V1_SYSTEM`.
No third live copy. Harness-only v2/v3 bodies live only in `bakeoff.py` and
are intentionally different text (not production defects; see Out of Scope /
Not-Doing — they stay in bakeoff). Aggravating for inventory design: the v1
body is **already** an implicit adjacent-string concatenation with an
f-string on `gpu_remote_adapter.py:32` / `bakeoff.py:93`, so a source-text
grep for a single substring marker is nearly-accidentally evadeable by a
split literal (`"2-" + "4 plain sentences"`).

## Constraints

- **Lane A file ownership (hard boundary).** This plan may edit only:
  - `apps/prototype-description-service/scene/infrastructure/vlm/gpu_remote_adapter.py`
  - `apps/prototype-description-service/scripts/eval_harness/bakeoff.py`
  - `apps/prototype-description-service/scene/config/settings.py`
  - `apps/prototype-description-service/scene/interface_adapters/http/deps.py`
    (**only** the one-line drop of
    `prompt_or_task_version=settings.gpu_prompt_or_task_version` at
    `deps.py:98` once the adapter no longer accepts a free-string stamp
    kwarg — no other deps edits)
  - any **new** shared-prompt module under `scene/` introduced by this task
  - tests that prove those surfaces (new + existing assertions that encode the
    old lying default `"3"` or the free-string constructor override)
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
  **Concrete warrant for this extract (not [REF-26]):** the two live v1 bodies
  are already declared lockstep by a comment-only obligation at
  `gpu_remote_adapter.py:23-24` ("Keep in lockstep with … bakeoff.py") with
  nothing mechanical enforcing it — that is the defect. REF-10's change-together
  test is the extract criterion: production adapter payload site and harness
  `PROMPT_VARIANTS["v1"]` must move as one; harness-only v2/v3 must not be
  pulled in. [REF-26] is **not** cited: its acid test requires multi-place
  *and multi-format* intent change (`canon/lexicons/engineering.md` REF-26
  definition anchor); both live copies are same-format Python strings, so the
  multi-format trigger does not fire.
- **Prove the green can go red**
  [TEST-15]
  (`canon/lexicons/engineering.md` →
  `canon/distilled/engineering/modern-software-engineering.md`): a parity test
  that only re-reads the same constant twice certifies nothing; a stamp test
  that only checks a version string while the posted body stays fixed certifies
  a lineage lie.
- **Prompt configuration is production lineage**
  [PROV-09]
  (`canon/lexicons/ml-systems.md` →
  `canon/distilled/ml-systems/ai-engineering.md`): the version stamp on each
  output must identify the prompt text that produced it. This is the
  load-bearing warrant for correcting the dishonest `"3"` default over v1 text
  and for binding body + lineage version into one selected config (with
  [TEST-15] proving the binding is enforceable).
- **Every output walks back to its evidence**
  [PROV-01]
  (`canon/lexicons/ml-systems.md` →
  `canon/distilled/ml-systems/model-cards.md`): the stamp is part of the
  result's lineage graph (and of the cache key); a mislabelled stamp makes
  reproduction and comparison impossible.
- **Honest stamp vs identifier (explanatory note only — no rule citation).**
  The identifier `prompt_or_task_version` *does* hold a version string; only
  the default *value* (`"3"` over v1 text) lies. That is a provenance/value
  defect, not a naming defect. PROV-09 (+ TEST-15) carry the work.

## Terminology

- **Production system prompt**: the system-role string
  `GpuRemoteDescriptionAdapter` posts on `/v1/chat/completions` today — the
  v1 body currently stored as `_SYSTEM_PROMPT`.
- **Harness v1 / v2 / v3**: named entries in `bakeoff.PROMPT_VARIANTS`. Only v1
  is textually identical to production today. v2 encodes ALTQ-1 style rules;
  v3 reuses v2's system text with `three_surface=True` and a weave addendum.
- **Shared-prompt module**: new single authority under `scene/` for the
  **production** caption system-prompt text (today: v1 body), the context
  markers used by that text, and one selected **`ProductionPrompt`** config
  that carries **body + lineage version together**. Harness-only surfaces stay
  in `bakeoff.py`: `PromptVariant` dataclass (fields `name`/`system`/
  `system_long`/`three_surface`; docstring notes three-surface variants are
  only valid with `two_pass` — `bakeoff.py:124-135`), v2/v3 bodies, and the
  full `PROMPT_VARIANTS` registry. Production consumes none of
  `system_long` / `three_surface`.
- **`ProductionPrompt`**: frozen dataclass `{body: str, lineage_version: str}`
  — the atomic production configuration. Today's selection is one module-level
  instance with the v1 body and `lineage_version="1"`. Accessors
  `production_system_prompt()` / `production_prompt_or_task_version()` read
  fields of that **same** selected instance; they are not independent globals
  that can desync.
- **Honest version stamp**: the default
  `gpu_prompt_or_task_version` / adapter `prompt_or_task_version` value that
  names the production-selected prompt's lineage id (today: `"1"` for v1
  text), obtained via `production_prompt_or_task_version()` which returns
  `PRODUCTION_PROMPT.lineage_version` — not a free-floating `"3"`, not a
  separate map keyed independently of the posted body, not an
  import-time-frozen constant that ignores the selected config, **not** a
  free-string env (`ACX_GPU_PROMPT_VERSION="9"`) that can stamp a lineage
  the posted body does not carry, and **not** a free-string constructor
  kwarg (`GpuRemoteDescriptionAdapter(prompt_or_task_version="9")` at
  today's `gpu_remote_adapter.py:133` / `:143`) that stamps independently of
  the selected `ProductionPrompt`.
- **Parity surface**: the two *consumer binding sites* the runtime actually
  uses — the system string the production adapter **POSTs** as
  `messages[0]["content"]` (captured via transport stub on `describe()`;
  today `gpu_remote_adapter.py:182`), and
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
- Adapter constructor default also `"3"` (`gpu_remote_adapter.py:133`) and
  free-string assignment to `self.prompt_or_task_version`
  (`gpu_remote_adapter.py:143`). **This free-string constructor override is
  a defect to remove** (not a feature to preserve). Round-3 finding
  DPR3-M-02 that demanded preserving the explicit-override test is
  **closed wontfix, superseded** by DPR4-H-01 — do not reinstate a
  preserve-the-override requirement anywhere in this plan.
- Stale module comment at `gpu_remote_adapter.py:23-24` still says
  "Bump ACX_GPU_PROMPT_VERSION / default prompt_or_task_version when this
  contract changes" even though this plan drops that free-string env
  control; exhaustive consumers of the env name today are `settings.py:40`,
  that comment, and assessment prose only.
- Existing tests and the dishonest-default / free-string-override sites:
  - `scene/tests/test_gpu_remote_adapter.py:51-65` constructs with
    **explicit** `prompt_or_task_version="3"` and asserts `== "3"`. Under
    this plan that free-string kwarg **goes away**: rewrite the
    construction to omit `prompt_or_task_version`, assert the stamp equals
    `production_prompt_or_task_version()` / `"1"`, and add a dedicated
    free-string-rejection proof (see Slice 2). **Do not** preserve the
    `prompt_or_task_version="3"` / assert `"3"` override shape.
  - `scene/tests/test_description_profiles.py:214` and `:263` assert
    resolved GPU adapters (via deps/settings path) expose
    `prompt_or_task_version == "3"` — **these are the dishonest-default
    sites to edit** to `"1"` / `production_prompt_or_task_version()`.
  - `scene/tests/test_ensemble_decode.py` stub uses `"3"` on a **non-
    GpuRemote** test double (intentional stub field — free to keep; not
    the production free-string constructor path).
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
- Harness-only `PromptVariant`, v2/v3 bodies, and `PROMPT_VARIANTS` remain in
  `bakeoff.py` (different knowledge — [REF-10]); a later v2/v3 production
  promotion replaces the selected `ProductionPrompt` (body + lineage version
  as one object) as its own deliberate change, not as part of this seam.
- A deterministic parity test fails if the production runtime system string
  (the string `describe()` actually POSTs as `messages[0]["content"]`) and
  harness `PROMPT_VARIANTS["v1"].system` diverge (whitespace-normalised).
- Default `gpu_prompt_or_task_version` is the selected
  `ProductionPrompt.lineage_version` (today `"1"`) — body and stamp live on
  one object so they cannot desync. Settings reads that field via the thin
  accessor; the adapter constructor **binds the stamp only from**
  `production_prompt_or_task_version()` with **no** free-string
  `prompt_or_task_version` kwarg at all. There is no independent version
  map, free-floating `"1"`/`"3"` constant beside a separate body global,
  free-string `ACX_GPU_PROMPT_VERSION` override, or free-string constructor
  path that stamps without carrying the body.
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
  `scene/interface_adapters/http/deps.py` (wiring; **owned one-line edit** at
  `deps.py:98` to drop free-string `prompt_or_task_version=` once the adapter
  constructor no longer accepts it — no other deps edits).
- Harness surface: `scripts/eval_harness/bakeoff.py` (prompt registry region
  ~L75–L154 and `PROMPT_VARIANTS` consumers).
- Existing tests to extend/correct:
  `scene/tests/test_gpu_remote_adapter.py` (rewrite free-string override at
  `:51-65`; add free-string rejection proof),
  `scene/tests/test_description_profiles.py`,
  `scene/tests/test_eval_harness_pipeline.py`,
  `scene/tests/test_settings.py`.
- Rules: `docs/workbay/rules/testing-python.md`,
  `docs/workbay/rules/backend-python-guidelines.md`,
  `docs/workbay/rules/development-workflow.md`.
- Canon (verified definition anchors, `grep -rE '^\| *\`?<ID><a name' canon/lexicons/`):
  - [REF-10] `canon/lexicons/engineering.md` → distilled
    `canon/distilled/engineering/refactoring-fowler-beck.md` (change-together /
    Extract) + `canon/distilled/engineering/modern-software-engineering.md`
    (ch-13: DRY within one deployment pipeline / deployable unit is in bounds;
    do not share code *between* independently deployed services). Load-bearing
    extract warrant together with the concrete comment-only lockstep at
    `gpu_remote_adapter.py:23-24`.
  - [TEST-15] `canon/lexicons/engineering.md` → distilled
    `canon/distilled/engineering/modern-software-engineering.md` (ch-8: predict
    the exact failure message; a test never seen failing is unverified;
    assertion-free / vacuous tests are defects).
  - [PROV-09] `canon/lexicons/ml-systems.md` → distilled
    `canon/distilled/ml-systems/ai-engineering.md` (named mechanism **prompt
    configuration is production lineage** — load-bearing for honest stamp and
    atomic body+version config).
  - [PROV-01] `canon/lexicons/ml-systems.md` (**not** `engineering.md`) →
    distilled `canon/distilled/ml-systems/model-cards.md` (versioned model
    reporting; every output walks back to evidence).
  - **Not cited:** [REF-26] (`canon/lexicons/engineering.md`) — acid test is
    multi-place *and multi-format*; both live v1 copies are same-format Python
    strings, so the trigger does not fire. Do not use REF-26 as decorative
    warrant.
  - **Not cited:** naming-rule IDs for the dishonest stamp — the identifier
    holds a version string; the default *value* is the lie; PROV-09 +
    TEST-15 carry the warrant (explanatory note in Workflow Principles).

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
   `gpu_remote_adapter.py:28-37` / bakeoff `_PROMPT_V1_SYSTEM` at
   `bakeoff.py:89-98`).
3. One selected **`ProductionPrompt`** config carrying body + lineage version
   **together** (atomic — not two independent globals):
   ```text
   @dataclass(frozen=True)
   class ProductionPrompt:
       body: str
       lineage_version: str

   PRODUCTION_PROMPT = ProductionPrompt(
       body=<moved v1 system text>,
       lineage_version="1",
   )

   def production_system_prompt() -> str:
       return PRODUCTION_PROMPT.body

   def production_prompt_or_task_version() -> str:
       return PRODUCTION_PROMPT.lineage_version
   ```
   Accessors always read the **same** selected instance. There is **no**
   separate `PRODUCTION_SYSTEM_PROMPT` string global that can stay on v1 while
   a version map / `PRODUCTION_PROMPT_VARIANT` key independently stamps `"2"`.
   There is **no** free-floating `_VARIANT_TO_TASK_VERSION` map that stamps
   without the body. A future promotion replaces `PRODUCTION_PROMPT` (or
   rebinds the selected instance) with a new `ProductionPrompt(body=…,
   lineage_version=…)` so body and stamp move as one.

**Not moved into the shared module (harness-only; [REF-10]):**

- **`PromptVariant` dataclass stays in `bakeoff.py`** (`bakeoff.py:124-135`
  today). It carries `system_long` and `three_surface` (docstring: three-
  surface variants "are only valid with two_pass"); production consumes none
  of those fields. Exporting it from the production package would ship harness-
  only shape into a surface that never uses it.
- v2 / v3 system-prompt bodies and the full `PROMPT_VARIANTS` registry
  construction remain in `bakeoff.py`. Production does not execute those paths
  today; shipping them in the production package would put harness-only text
  on a surface it never runs (plan's own harness-only-stays-put criterion).
  Verified: v2 body exists only in `bakeoff.py:104-121`; production has one
  prompt binding at `gpu_remote_adapter.py:182`.
- `DEFAULT_PROMPT_VARIANT = "v1"` stays defined and exported in `bakeoff.py`
  (harness CLI default at `bakeoff.py:154` today). Importers such as
  `test_eval_harness_pipeline.py:22` keep
  `from scripts.eval_harness.bakeoff import DEFAULT_PROMPT_VARIANT`.
- Pass-1 / weave / compress prompts stay in `bakeoff.py`.

Consumers:

- `gpu_remote_adapter.py` imports `production_system_prompt` +
  `production_prompt_or_task_version` + markers; deletes local
  `_SYSTEM_PROMPT` / local marker constants used only for that prompt;
  payload system message calls **`production_system_prompt()` only** at the
  site of today's `_SYSTEM_PROMPT` (`gpu_remote_adapter.py:182`); constructor
  **removes the free-string `prompt_or_task_version` parameter entirely**
  (today `gpu_remote_adapter.py:133` / assigned at `:143`) and always sets
  `self.prompt_or_task_version = production_prompt_or_task_version()` at
  init time so no caller-supplied version string exists. **Only permitted
  binding form for production consumers:** the accessor functions. Do **not**
  read `PRODUCTION_PROMPT.body` / `.lineage_version` at the call site, and do
  **not** introduce a dedicated frozen body export. Reason: accessors re-read
  the module global `caption_system.PRODUCTION_PROMPT` at **call time**, so
  `monkeypatch.setattr(caption_system, "PRODUCTION_PROMPT", synthetic)` in
  Slice 2 reaches them; `from scene.prompts.caption_system import
  PRODUCTION_PROMPT` binds the object at import time (rebind never reaches
  the local name), and `DEDICATED = PRODUCTION_PROMPT.body` freezes the body
  string at import the same way. **Delete** the stale
  `ACX_GPU_PROMPT_VERSION` bump instruction in the module comment at
  `gpu_remote_adapter.py:23-24` (exact text: "Bump ACX_GPU_PROMPT_VERSION /
  default prompt_or_task_version when this contract changes.") and replace
  the "Keep in lockstep…" block with a pointer to the shared module +
  parity / inventory test path.
- `bakeoff.py` imports the shared v1 body **only** via
  `production_system_prompt()` (same accessor-only rule; no direct
  `.body` read, no dedicated body export) and markers; **keeps local
  `PromptVariant`**; deletes local `_PROMPT_V1_SYSTEM`; keeps local
  `_PROMPT_V2_SYSTEM` and builds `PROMPT_VARIANTS` in place (v1 entry bound
  to the shared v1 body; v2/v3 unchanged local text); keeps
  `DEFAULT_PROMPT_VARIANT = "v1"` locally; re-exports `PROMPT_VARIANTS` /
  `DEFAULT_PROMPT_VARIANT` / `PromptVariant` so existing
  `from scripts.eval_harness.bakeoff import PROMPT_VARIANTS` tests keep
  working.
- `settings.py` default for `gpu_prompt_or_task_version` becomes
  **only** `production_prompt_or_task_version()` (default_factory that calls
  the accessor). **Do not** preserve
  `os.environ.get("ACX_GPU_PROMPT_VERSION", …)` as a free-string stamp
  override: a version-only env override emits stamp `"9"` over v1 text —
  the lineage lie this plan exists to prevent.
- `deps.py:98` **must** drop
  `prompt_or_task_version=settings.gpu_prompt_or_task_version` once the
  adapter constructor no longer accepts that kwarg (owned one-line delete;
  adapter self-binds from `production_prompt_or_task_version()`). Settings
  honesty remains load-bearing for the settings surface of the atomic-
  stamp discrimination; production adapter stamp no longer flows through
  that free-string constructor argument.

Tests (same slices as the behaviour they load-bear):

- **Parity** between production consumer binding (posted system message) and
  harness v1 consumer binding, with explicit red-first and discrimination
  cases ([TEST-15]).
- **Single-source inventory (mandatory)** — inventory of **assembled** prompt
  values (import + normalise the constructed body; not a source-text grep
  for a substring marker) equals 1 at exactly `caption_system.py`; red-first
  mutation injects a second full-body assignment, including a split-literal
  form (`"2-" + "4 plain sentences"` style) that still assembles to the
  production body ([TEST-15]).
- **Honest atomic stamp** — inject a synthetic `ProductionPrompt` and assert
  posted body, adapter stamp, **and**
  `DescriptionSettings().gpu_prompt_or_task_version` all reflect the injected
  config together ([PROV-09], [PROV-01], [TEST-15]).
- **Resolver no-divergence (mandatory)** — production path cannot stamp one
  lineage while posting another body; free-string env stamp path is absent;
  free-string constructor override path is absent ([PROV-09], [TEST-15]).
- **Free-string constructor rejection (mandatory)** — constructing
  `GpuRemoteDescriptionAdapter` with an arbitrary `prompt_or_task_version=`
  string is impossible / rejected; red if the free-string kwarg is
  reintroduced and honored ([TEST-15]).
- Update existing **resolved-default** assertions that hard-code GPU `"3"`
  (`test_description_profiles.py:214`/`:263`); **rewrite/delete** the
  free-string explicit-override shape at
  `test_gpu_remote_adapter.py:51-65` (do not preserve it); add no-arg
  constructor default test.

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

**Downstream (explicitly unowned by this plan and by this wave):** the F1
voice-honouring weave rewrite — F1 (b) in DEPICT-1's ownership-split table —
is **unowned**. No plan file delivers it; `DEPICT-1b` is an optional future
label only, to be used when such a plan is actually authored. DEPICT-1 itself
is the contract lane (voice / register / gravity schema only); it Not-Does
prompt wording and scopes the weave half OUT (see DEPICT-1 §Constraints /
§Cross-lane dependency F1 ownership split). That unowned follow-on's
exact change target is the **post-DEPICT-0** shared module
(`scene/prompts/caption_system.py` — the selected `ProductionPrompt.body`),
not the pre-seam local `_SYSTEM_PROMPT` this plan deletes from
`gpu_remote_adapter.py`. This plan **Not-Does** F1 weave-instruction rewrite
and does **not** deliver weave-side context consumption. **No lane in this
wave** (DEPICT-0 / DEPICT-1 / DEPICT-2) delivers weave-side context
consumption; after all three current depiction lanes merge, the F1 weave half
remains **open and unowned**. Merging DEPICT-0 + DEPICT-1 + DEPICT-2 does not
close assessment P0 F1. Do not silently absorb that work here.

Register / fact-inventory / voice-partition contract work is **DEPICT-1**
scope — not this plan (see DEPICT-1 fixed fact inventory and
`partition_context_pack`). Do not add inventory-guard or register prose here.

`deps.py:98` today threads `settings.gpu_prompt_or_task_version` into the
adapter constructor; once the free-string constructor kwarg is removed this
plan owns the one-line drop of that argument so production wiring matches.
If a future promotion wants production to ship v2 text, that is a later
DEPICT slice (replace the selected `ProductionPrompt` with body + lineage
version for that text), not this seam.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| new shared-prompt module | `apps/prototype-description-service/scene/prompts/caption_system.py` (new; `__init__.py` as needed) | Own markers, production v1 system body, selected `ProductionPrompt` (body + `lineage_version`), accessors `production_system_prompt()` / `production_prompt_or_task_version()`; **not** `PromptVariant`, v2/v3 bodies, or full `PROMPT_VARIANTS` |
| production adapter | `…/scene/infrastructure/vlm/gpu_remote_adapter.py` | Delete local `_SYSTEM_PROMPT`; **delete** the `ACX_GPU_PROMPT_VERSION` bump instruction at lines **23-24** and replace the "Keep in lockstep…" comment with a pointer to the shared module + parity/inventory tests; import production system prompt + markers from shared module; **remove free-string `prompt_or_task_version` constructor kwarg** (today `:133`/`:143`); always bind `self.prompt_or_task_version = production_prompt_or_task_version()`; keep describe payload behaviour identical |
| harness | `…/scripts/eval_harness/bakeoff.py` | Delete local `_PROMPT_V1_SYSTEM` only; import shared v1 body + markers; **keep local `PromptVariant`** and `_PROMPT_V2_SYSTEM`; build `PROMPT_VARIANTS` locally (v1 entry uses shared body); keep `DEFAULT_PROMPT_VARIANT = "v1"` defined here; re-export names tests already import; leave pass-1 / weave / compress / face-gate logic in place |
| settings | `…/scene/config/settings.py` | Default `gpu_prompt_or_task_version` from `production_prompt_or_task_version()` only — **drop** free-string `ACX_GPU_PROMPT_VERSION` stamp override |
| deps (one-line) | `…/scene/interface_adapters/http/deps.py:98` | Drop `prompt_or_task_version=settings.gpu_prompt_or_task_version` once the adapter no longer accepts that kwarg; no other deps edits |
| tests (new) | `…/scene/tests/test_prompt_lineage_seam.py` (new) | Parity (transport-stubbed posted system string) + **mandatory** assembled-value single-source inventory (incl. split-literal discrimination) + atomic body+stamp discrimination + resolver no-divergence + free-string constructor rejection, all with red-first documentation in docstrings |
| tests (correct) | `…/scene/tests/test_description_profiles.py:214`/`:263`, `test_settings.py`; **rewrite** `test_gpu_remote_adapter.py:51-65` (delete free-string `"3"` override; omit kwarg; assert stamp = `production_prompt_or_task_version()` / `"1"`); **add** no-arg default + free-string rejection proofs | Resolved-default sites expect honest `"1"`; free-string constructor override is gone (DPR3-M-02 preserve-override **wontfix**) |

## Related Files

| File | Note |
| --- | --- |
| `scene/application/hashing.py` | Cache-key composition — read for hazard; **do not edit** |
| `scene/interface_adapters/http/deps.py` | Today passes `settings.gpu_prompt_or_task_version` at `:98`; **owned one-line drop** of that kwarg when free-string constructor is removed |
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
consume it; a parity test fails when the two consumer bindings diverge; a
**mandatory** single-source inventory test (keyed on the **assembled** prompt
value, not a source-text substring grep) fails when a second full-body
definition of the v1 text appears anywhere under the package roots —
including a split-literal assembly that would evade a marker grep.

**Canon**: [REF-10]
(`canon/lexicons/engineering.md` →
`canon/distilled/engineering/refactoring-fowler-beck.md` +
`canon/distilled/engineering/modern-software-engineering.md`);
[TEST-15]
(`canon/lexicons/engineering.md` →
`canon/distilled/engineering/modern-software-engineering.md`).
Concrete extract warrant: comment-only lockstep at
`gpu_remote_adapter.py:23-24` plus REF-10 change-together (production v1 body
and harness `PROMPT_VARIANTS["v1"]`). **Not** [REF-26] (multi-format trigger
does not fire — both copies are same-format Python strings).

Changes:

- Add `scene/prompts/caption_system.py` (and package init) containing:
  - `CONTEXT_BEGIN` / `CONTEXT_END` (same string values as today:
    `<<<CONTEXT>>>` / `<<<END_CONTEXT>>>`).
  - Production v1 system body moved **without wording changes** from
    `gpu_remote_adapter.py:28-37` / `bakeoff.py:89-98`, held on the selected
    `ProductionPrompt` (see Slice 2 for the atomic config shape; Slice 1 may
    land body + markers first and bind them into `ProductionPrompt` in Slice 2,
    or land the full atomic config in one step — either order is fine so long
    as HEAD ends with body+version on one object).
  - Accessors that read the selected config's body (e.g.
    `production_system_prompt() -> PRODUCTION_PROMPT.body`).
  - **Do not** move `PromptVariant` here — it stays in `bakeoff.py:124-135`
    (harness-only fields `system_long` / `three_surface`; production unused).
  - **Do not** move v2/v3 bodies or the full `PROMPT_VARIANTS` registry here
    ([REF-10]; harness-only text stays in `bakeoff.py`; v2 body lives only at
    `bakeoff.py:104-121`).
  - **Do not** define `DEFAULT_PROMPT_VARIANT` here — that harness default
    remains in `bakeoff.py` (see rewire below).
- Rewire `gpu_remote_adapter.py`:
  - Import `production_system_prompt` / `production_prompt_or_task_version`
    and markers (accessor functions only).
  - Call `production_system_prompt()` in the chat payload system message at
    the same site as today's `_SYSTEM_PROMPT` (`gpu_remote_adapter.py:182`
    `messages[0]["content"]`) — not a direct `PRODUCTION_PROMPT.body` read.
  - Delete the local duplicated v1 body.
  - **Delete the stale operator guidance at lines 23-24** (exact current
    text spanning those lines: "Keep in lockstep with
    scripts/eval_harness/bakeoff.py (VLMRP-HARM-01). Bump
    ACX_GPU_PROMPT_VERSION / default prompt_or_task_version when this
    contract changes."). Replace with a short pointer to
    `scene/prompts/caption_system.py` and the parity / assembled-value
    inventory tests. Do **not** leave any instruction to bump
    `ACX_GPU_PROMPT_VERSION` or a free-string constructor default.
- Rewire `bakeoff.py`:
  - Import shared v1 body via `production_system_prompt()` only (no direct
    `.body` read, no dedicated body export) and markers.
  - **Keep local `PromptVariant` dataclass** (do not import it from
    `caption_system`).
  - Delete local `_PROMPT_V1_SYSTEM` only. Keep local `_PROMPT_V2_SYSTEM`.
  - Build `PROMPT_VARIANTS` locally: v1 entry uses the shared v1 body (and the
    same long-band replace `"2-4 plain sentences" → "4-8 plain sentences"`);
    v2/v3 entries keep today's local text and long-band replace unchanged.
  - Keep `DEFAULT_PROMPT_VARIANT = "v1"` **defined and exported in bakeoff.py**
    (today at `bakeoff.py:154`; still imported by
    `test_eval_harness_pipeline.py:22`). Do **not** import it from the shared
    module (it is not defined there).
  - Re-export `PROMPT_VARIANTS`, `DEFAULT_PROMPT_VARIANT`, and `PromptVariant`
    (local class) so `from scripts.eval_harness.bakeoff import PROMPT_VARIANTS`
    keeps working.
  - Leave `_PASS1_SYSTEM_PROMPT`, `_WEAVE_INSTRUCTIONS`,
    `_V3_THREE_SURFACE_INSTRUCTIONS`, `_COMPRESS_SYSTEM_PROMPT` in bakeoff
    ([REF-10]: different pipeline-stage knowledge).
- Add `scene/tests/test_prompt_lineage_seam.py` with the parity test and the
  **mandatory** single-source inventory test below.

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
   (e.g. two imports of `production_system_prompt()` result, or two aliases of
   the same shared symbol) is **not** a valid form of this test. Existing
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

- **Trivial cheating implementations this test must kill:**
  1. Attribute-only: `assert production_system_prompt() == production_system_prompt()`
     (or two imports of the same shared symbol). Stays green when the adapter
     payload is re-wired to a divergent local literal.
  2. Always-constant / no-op: `assert True`, or assert two hard-coded identical
     string literals inside the test body. Stays green under red edit (a).
  3. Substring-only (today's adapter test pattern): `"Never name or guess" in
     posted_system` — stays green when the posted body is otherwise divergent
     from harness v1.
- The shipped test kills all three because it reads the **transport-captured
  posted** system string and the harness registry entry and requires full
  whitespace-normalised equality.
- Permanent discrimination guard (recommended): also assert that under the
  default selected config, `production_prompt_or_task_version() == "1"` and the
  posted system string equals `production_system_prompt()` — so a future
  promotion that rebinds `PRODUCTION_PROMPT` without updating the parity
  expectation is a deliberate, visible edit.

#### [TEST-15] red-first proof — single-source body inventory (MANDATORY)

**Test name (proposed):**
`test_production_v1_body_has_exactly_one_definition`

**Why mandatory (not optional / not stretch):** consumer-parity alone is
vacuous against a third unused full v1 body. A dead second assignment
anywhere under the package roots still lets both consumers import the shared
body, so every required pytest command and both consumer-equality assertions
stay green. The inventory test is what enforces the plan's central "exactly
one prompt definition" guarantee.

**Why assembled-value, not source-text marker grep:** a raw source inventory
keyed on the substring `"2-4 plain sentences"` is evadeable by a split
literal (`"2-" + "4 plain sentences"`). Aggravating evidence: today's v1
body at `gpu_remote_adapter.py:28-37` (and `bakeoff.py:89-98`) is **already**
an implicit multi-line adjacent-string concatenation with an f-string on
`gpu_remote_adapter.py:32` / `bakeoff.py:93` — so the evasion is nearly
accidental, not only adversarial. The inventory **must** key on the
**assembled** prompt value.

**What it asserts (assembled body equality, definition count AND location):**

1. **Canonical assembled body.** Import the shared module and take
   `canonical = re.sub(r"\s+", " ", production_system_prompt().strip())`
   (or whitespace-normalise `PRODUCTION_PROMPT.body` via the same accessor).
   This is the only authority for "what the production v1 body is."
2. **Inventory mechanism (assembled value, not substring grep).** Over the
   service package roots (`scene/` and `scripts/eval_harness/` under
   `apps/prototype-description-service/`), discover every module-level
   full-body **definition** whose **assembled runtime value** (after
   constant-folding adjacent string literals, explicit `+` concatenations,
   and f-strings whose interpolated names resolve to the shared marker
   constants / known string constants) is whitespace-normalised-equal to
   `canonical`. Acceptable implementations: (i) import candidate modules and
   compare module-level `str` attributes / dataclass field values to
   `canonical`, and/or (ii) AST walk that assembles constant string
   expressions (including `"a" "b"`, `"a" + "b"`, and f-strings with
   constant parts) before comparing. **Forbidden as the sole check:**
   `source_text.count("2-4 plain sentences")` / grepping the raw file for
   that substring alone.
3. Assert **exactly one** such full-body definition, at exactly this
   location: the production v1 body bound into `ProductionPrompt` in
   `scene/prompts/caption_system.py` (the selected config's body field).
4. **Permitted non-definition hits** (must not count as full-body
   definitions): bakeoff's long-band
   `.replace("2-4 plain sentences", "4-8 plain sentences")` on the imported
   v1 body (token as replace *argument* / derived string, not a second
   independent full body definition); tests that quote fragments of the
   body; the accessor `production_system_prompt()` itself (it *reads* the
   one definition, it is not a second definition).
5. **Forbidden:** full v1 body still defined in `gpu_remote_adapter.py`; a
   second `_PROMPT_V1_SYSTEM`-style body assignment in `bakeoff.py`; any
   third full assignment anywhere under the package roots — including one
   assembled via split literals.
6. **Do not use as the sole inventory key:** the weave clause
   `"Weave the people's names and factual details it supplies"` (also in
   harness v2 at `bakeoff.py:116-118`), the shared opener
   `"You write alt text for images on a personal website"` (also in v2), or
   a raw substring grep for `"2-4 plain sentences"` alone (v1-unique today
   at `gpu_remote_adapter.py:30` / `bakeoff.py:91` vs v2's
   `"Write 2-4 sentences."` at `bakeoff.py:113`, but still split-evadeable).

**(a) Exact edit that makes it go red**

- Inject a **second full-body assignment** whose assembled value equals the
  canonical production body, anywhere outside the permitted definition site
  — e.g. re-add `_SYSTEM_PROMPT = ("…full v1 text…")` in
  `gpu_remote_adapter.py`, re-add `_PROMPT_V1_SYSTEM = ("…full v1 text…")` in
  `bakeoff.py`, or add a dummy module-level string assignment under `scene/`
  that assembles to the same body. Under that mutation the inventory test
  **must fail** (definition count ≠ 1, and/or location not exclusively
  `caption_system.py`).

**(a′) Permanent split-literal discrimination guard (must ship in the test)**

- Also inject (as a permanent fixture mutation the test itself performs, or
  as a documented second red path the test would catch) a **split-literal**
  full-body duplicate whose source does **not** contain the contiguous
  substring `"2-4 plain sentences"` but whose assembled value still equals
  `canonical` — e.g. a module-level assignment that builds the same body
  with `"2-" + "4 plain sentences"` (or equivalent adjacent-literal /
  explicit-concat split of any unique span). A substring-grep inventory
  stays green under this shape; the assembled-value inventory **must go
  red** (count ≥ 2). Ship this as a permanent discrimination assertion so
  a future "simplify to source grep" regression fails the suite.

**(b) Discrimination case (proves the check is not vacuous)**

- **Cheating shapes this test kills:**
  1. Leave both consumers on the shared accessor (parity stays green) while
     a third unused full v1 body sits elsewhere in the tree. Consumer-
     equality and transport-parity alone pass; only the inventory
     count/location assertion goes red under (a).
  2. Split-literal third body (`"2-" + "4 plain sentences"` style) that
     evades a source-text marker grep. Only the assembled-value inventory
     goes red under (a′).
- Attribute-only / always-constant cheats are already killed by the parity
  test; this test's load-bearing jobs are the unused-third-body hole **and**
  the split-literal evasion hole.

### Slice 2: Honest `prompt_or_task_version` bound to shipped text (atomic config)

**Goal**: The GPU version stamp names the prompt text that actually ships;
body and stamp cannot desync; defaults and tests stop lying `"3"` over v1
text; cache-key consequence is accepted without a shim.

**Canon**: [PROV-09]
(`canon/lexicons/ml-systems.md` →
`canon/distilled/ml-systems/ai-engineering.md`);
[PROV-01]
(`canon/lexicons/ml-systems.md` →
`canon/distilled/ml-systems/model-cards.md`);
[TEST-15]
(`canon/lexicons/engineering.md` →
`canon/distilled/engineering/modern-software-engineering.md`).
(No naming-rule citation for the dishonest stamp — see Workflow Principles
explanatory note; PROV-09 + TEST-15 are load-bearing.)

Changes:

- In the shared module, select **one** `ProductionPrompt` that carries body +
  lineage version together (not two independent globals):
  ```text
  @dataclass(frozen=True)
  class ProductionPrompt:
      body: str
      lineage_version: str

  PRODUCTION_PROMPT = ProductionPrompt(
      body=<v1 system text moved from gpu_remote_adapter / bakeoff>,
      lineage_version="1",
  )

  def production_system_prompt() -> str:
      return PRODUCTION_PROMPT.body

  def production_prompt_or_task_version() -> str:
      return PRODUCTION_PROMPT.lineage_version
  ```
  **Forbidden shapes (these re-introduce the lineage lie):**
  - Independent `PRODUCTION_SYSTEM_PROMPT = "…v1…"` plus a separate
    `production_prompt_or_task_version()` that subscripts
    `_VARIANT_TO_TASK_VERSION[PRODUCTION_PROMPT_VARIANT]` — monkeypatching the
    variant key to `"v2"` stamps `"2"` while the posted payload still carries
    the v1 body (production has one prompt binding at
    `gpu_remote_adapter.py:182`; the v2 body exists only in
    `bakeoff.py:104-121`).
  - Free-floating `PRODUCTION_PROMPT_OR_TASK_VERSION = "1"` beside a body
    global that can change independently.
  - Import-time-frozen default-arg of a version string that ignores a later
    rebind of `PRODUCTION_PROMPT`.
  - Consumer binding via `from … import PRODUCTION_PROMPT` then
    `.body` / `.lineage_version`, or a dedicated import-time
    `DEDICATED = PRODUCTION_PROMPT.body` export — both miss the Slice-2
    module-attribute monkeypatch (see Consumers above).
  - Free-string env stamp override
    (`os.environ.get("ACX_GPU_PROMPT_VERSION", …)`) that can set settings
    stamp independently of the body posted at `gpu_remote_adapter.py:182`.
  - Free-string constructor override
    (`prompt_or_task_version: str = "3"` assigned to
    `self.prompt_or_task_version` at `gpu_remote_adapter.py:133`/`:143`)
    that lets `GpuRemoteDescriptionAdapter(prompt_or_task_version="9")`
    stamp `"9"` over the v1 body posted at `:182`.
- `settings.py`:
  `gpu_prompt_or_task_version` default_factory is **only**
  `production_prompt_or_task_version()` so each settings construction
  re-evaluates the selected config's `lineage_version`. **Drop** the
  free-string `ACX_GPU_PROMPT_VERSION` path (today at `settings.py:40`
  `os.environ.get("ACX_GPU_PROMPT_VERSION", "3")`). Keeping a version-only
  env override would re-certify stamp/body divergence on a supported
  operator path.
- `gpu_remote_adapter.py` constructor — **remove free-string override
  entirely (preferred; closed lineage enum is the only alternative, and
  this plan chooses removal):**
  - **Delete** the `prompt_or_task_version` parameter from
    `GpuRemoteDescriptionAdapter.__init__` (today
    `prompt_or_task_version: str = "3"` at `gpu_remote_adapter.py:133` and
    `self.prompt_or_task_version = prompt_or_task_version` at `:143`).
  - Always bind
    `self.prompt_or_task_version = production_prompt_or_task_version()`
    inside `__init__` (call-time read of the selected config — not an
    import-time frozen `"1"` default-arg). A monkeypatched
    `PRODUCTION_PROMPT` must be visible on new instances.
  - **Do not** keep `prompt_or_task_version: str | None = None` as a
    caller-supplied free string that is honored when not None — that is
    still the free-string override hole (DPR4-H-01). DPR3-M-02's
    preserve-the-override requirement is **wontfix / superseded**; do not
    reinstate it.
  - Payload system message must call **`production_system_prompt()` only**
    at describe time — not `PRODUCTION_PROMPT.body` direct attribute
    access, and not a frozen import-time copy of the body string — so the
    Slice-2 `monkeypatch.setattr(caption_system, "PRODUCTION_PROMPT",
    synthetic)` rebind reaches the posted content.
  - **Delete** the stale `ACX_GPU_PROMPT_VERSION` bump instruction at
    `gpu_remote_adapter.py:23-24` (see Slice 1 rewire / DPR4-L-13).
- `deps.py:98` — **drop**
  `prompt_or_task_version=settings.gpu_prompt_or_task_version` (owned
  one-line edit). After the free-string constructor kwarg is removed,
  passing it is a TypeError; production wiring must construct the adapter
  without a stamp argument. Settings honesty remains for the settings
  surface of discrimination tests.
- Correct tests that encoded the **resolved-default** lie and the
  free-string constructor override:
  - `test_description_profiles.py:214` and `:263` — resolved GPU adapters
    (deps path) assert `prompt_or_task_version == "3"` today; change both
    to expect `"1"` / `production_prompt_or_task_version()` under default
    construction.
  - `test_settings.py` — add assertion that default
    `DescriptionSettings().gpu_prompt_or_task_version == "1"` (and equals
    `production_prompt_or_task_version()`).
  - `test_gpu_remote_adapter.py:51-65` — **rewrite**: remove
    `prompt_or_task_version="3"` from construction and change
    `assert adapter.prompt_or_task_version == "3"` to assert
    `production_prompt_or_task_version()` / `"1"`. Keep the rest of the
    transport/payload assertions (they prove describe behaviour, not the
    free-string override). **Do not** preserve the free-string override
    shape (DPR3-M-02 **wontfix**).
  - **Add** a no-arg constructor default test that builds
    `GpuRemoteDescriptionAdapter` without any stamp kwarg and asserts
    `.prompt_or_task_version == production_prompt_or_task_version()` /
    `"1"`.
  - **Add** free-string constructor rejection proof (below).
  - Any other hard-coded GPU **default** `"3"` expectations that break
    under the honest default. Non-GpuRemote stubs that set a stub field to
    `"3"` (e.g. ensemble test doubles) are out of this constructor path
    and free to keep their stub values.
- Do **not** add migration code, dual-key cache reads, or a compatibility
  alias from `"3"` → v1 text.

Proof:

```bash
cd apps/prototype-description-service
uv run --extra dev pytest scene/tests/test_prompt_lineage_seam.py scene/tests/test_settings.py scene/tests/test_description_profiles.py scene/tests/test_gpu_remote_adapter.py -q
```

#### [TEST-15] red-first proof — honest atomic version stamp

**Test names (proposed):**

- `test_gpu_prompt_version_default_matches_production_prompt`
- `test_production_prompt_body_and_lineage_change_together`
- `test_gpu_adapter_rejects_free_string_prompt_version_kwarg` (constructor
  free-string removal — see dedicated block below)

**What they assert (default selection):**

1. `DescriptionSettings().gpu_prompt_or_task_version == "1"` (settings reads
   only `production_prompt_or_task_version()` — no free-string env stamp).
2. `GpuRemoteDescriptionAdapter(...).prompt_or_task_version == "1"`
   (construct **without** a `prompt_or_task_version` kwarg — the parameter
   no longer exists; this is the no-arg stamp path, **not** a preserved
   free-string override at `test_gpu_remote_adapter.py:51-65`).
3. Under today's selection, `production_prompt_or_task_version() == "1"` and
   `production_system_prompt()` equals the v1 system text.
   **Do not** assert
   `production_prompt_or_task_version() == PRODUCTION_PROMPT.lineage_version`
   as a standalone check — that equality is tautological because the
   prescribed accessor body is `return PRODUCTION_PROMPT.lineage_version`
   (see shared-module shape above). Only the coupled `== "1"` half plus the
   transport/settings/adapter surfaces are load-bearing.
4. Transport-stubbed `describe()` posts
   `messages[0]["content"]` equal (whitespace-normalised) to
   `production_system_prompt()` — ties stamp lineage to the body that
   actually ships ([PROV-01] / [PROV-09]). Compare against the accessor
   return value (call-time read), not a direct `PRODUCTION_PROMPT.body`
   attribute grab in production code paths.
5. Negative honesty check: default stamp is **not** `"3"` while the selected
   body is the v1 text (names the bug class this slice kills — dishonest value
   over v1 text; warrant is [PROV-09]).

**(a) Exact edit that makes it go red**

- Change `PRODUCTION_PROMPT.lineage_version` to `"3"` while leaving
  `body` as the v1 text (e.g. rebind
  `PRODUCTION_PROMPT = ProductionPrompt(body=<same v1>, lineage_version="3")`)
  → assertions (1)/(2)/(3)/(5) fail.
- Concrete production-path red: restore `settings.py` default to literal `"3"`
  → `test_gpu_prompt_version_default_matches_production_prompt` fails.
- Body/stamp desync red: restore the **forbidden** independent-globals shape
  (body global fixed at v1; version function returns `"2"` under a patched
  variant key) → discrimination case (b) fails on the posted-body assertion
  even if the stamp-only assertions pass.
- Free-string env stamp red: restore
  `os.environ.get("ACX_GPU_PROMPT_VERSION", production_prompt_or_task_version())`
  and set `ACX_GPU_PROMPT_VERSION=9` → resolver no-divergence test (below)
  fails (stamp `"9"`, posted body still v1).
- Free-string constructor red: restore
  `prompt_or_task_version: str = "3"` (or any free string default) assigned
  to `self.prompt_or_task_version` → free-string rejection proof (below)
  fails (`TypeError` expected on `prompt_or_task_version="9"`, or stamp
  equals `"9"` over v1 body).

**(b) Discrimination case — synthetic v2 config (kills body/stamp desync)**

Inject one synthetic selected config and assert **all three surfaces** move
together:

```text
synthetic = ProductionPrompt(
    body="SYNTHETIC_V2_SYSTEM_PROMPT_FOR_LINEAGE_TEST.",
    lineage_version="2",
)
monkeypatch.setattr(caption_system, "PRODUCTION_PROMPT", synthetic)
```

Then assert **all** of:

1. `production_system_prompt() == synthetic.body`
2. `production_prompt_or_task_version() == "2"`
3. Fresh `GpuRemoteDescriptionAdapter` (no stamp kwarg — parameter removed)
   has `.prompt_or_task_version == "2"`
4. Transport-stubbed `describe()` on that adapter posts
   `messages[0]["content"]` equal to `synthetic.body` (not the v1 body) —
   requires the payload path to call `production_system_prompt()` (call-time
   module-global read); an import-time
   `from … import PRODUCTION_PROMPT` / `DEDICATED = PRODUCTION_PROMPT.body`
   binding makes (b).4 go red with no further diagnosis.
5. Fresh `DescriptionSettings().gpu_prompt_or_task_version == "2"`
   (settings default_factory calls `production_prompt_or_task_version()` only).

**Trivial cheating implementations this discrimination kills:**

| Cheating shape | Why it looked green under weaker tests | How (b) kills it |
| --- | --- | --- |
| Independent globals: `PRODUCTION_SYSTEM_PROMPT` (v1 body) + `production_prompt_or_task_version()` from `_VARIANT_TO_TASK_VERSION[PRODUCTION_PROMPT_VARIANT]` | Monkeypatch variant → `"v2"`; stamp becomes `"2"`; body assertions never read the posted payload | (b).4 fails — posted content still v1 body |
| Settings hardcode `"1"`; stamp function always returns `"1"` | Default settings/adapter assertions stay green | (b).2 / (b).3 / (b).5 fail under synthetic `"2"` |
| Adapter constructor freezes import-time `"1"`; body accessor is live | Stamp stuck at `"1"` while body can change | (b).3 fails (or (b).4 if body is frozen and stamp live) |
| Import-time body bind: `from … import PRODUCTION_PROMPT` then post `.body`, or `DEDICATED = PRODUCTION_PROMPT.body` | Accessor-only unit checks may still pass if they call the functions | (b).4 fails — rebind of module attribute never reaches the frozen import-time name |
| Test asserts only `DescriptionSettings().gpu_prompt_or_task_version == "1"` under default selection | Passes with settings hardcode of `"1"` even when body/stamp desync | (b) injects `"2"` and requires settings + posted body |
| Free-string env stamp: `ACX_GPU_PROMPT_VERSION=9` while body stays v1 | Settings stamp `"9"`; posted body still v1 — looks like a supported operator escape hatch | Resolver no-divergence test (below) fails; plan drops the free-string env path |
| Free-string constructor: `GpuRemoteDescriptionAdapter(prompt_or_task_version="9")` while body stays v1 | Posts v1 under stamp `"9"`; no env needed; today's `test_gpu_remote_adapter.py:51-65` shape even certifies the override | Free-string constructor rejection proof fails; plan removes the kwarg (DPR3-M-02 preserve-override **wontfix**) |

#### [TEST-15] red-first proof — resolver no stamp/body divergence (MANDATORY)

**Test name (proposed):**
`test_no_configured_path_stamps_lineage_without_matching_body`

**Why:** Production today stamps from settings via `deps.py:98`
(`prompt_or_task_version=settings.gpu_prompt_or_task_version`) while
`gpu_remote_adapter.py:182` posts the system body independently. Any path
that can set the stamp without carrying the body re-introduces the lineage
lie. After this plan, the adapter self-binds the stamp from
`production_prompt_or_task_version()` and deps no longer passes a free-
string stamp kwarg. Slice-2 five-surface discrimination covers the
selected-config rebind; this test covers the **configured production path**
(adapter construction as production does + posted body).

**What it asserts:**

1. Build a GPU adapter the way production will after this plan: construct
   `GpuRemoteDescriptionAdapter` **without** a `prompt_or_task_version`
   kwarg (matching post-edit `deps.py`, which no longer passes it) plus
   transport-stubbed `describe()`.
2. Assert stamped `adapter.prompt_or_task_version` equals
   `production_prompt_or_task_version()` and the posted
   `messages[0]["content"]` equals `production_system_prompt()`
   (whitespace-normalised) under the default selected config.
3. Rebind `PRODUCTION_PROMPT` to the synthetic v2 config (same as (b)
   above) and repeat: stamp and posted body both reflect the synthetic
   values together.
4. **Negative env path:** with `ACX_GPU_PROMPT_VERSION=9` in the
   environment (if the process still inherits it), settings stamp must
   **not** become `"9"` while the posted body remains v1 — preferred
   implementation: settings never consults that env var, so
   `DescriptionSettings().gpu_prompt_or_task_version` stays
   `production_prompt_or_task_version()`, and the adapter stamp (bound
   only from the selected config) matches.
5. **Negative constructor path:** constructing with
   `prompt_or_task_version="9"` must be impossible / rejected (see free-
   string constructor rejection proof below) — not a supported stamp
   escape hatch.

**(a) Exact edit that makes it go red**

- Restore free-string env stamp in `settings.py`:
  `os.environ.get("ACX_GPU_PROMPT_VERSION", production_prompt_or_task_version())`
  and run with `ACX_GPU_PROMPT_VERSION=9` → assertion (4) fails (settings
  stamp `"9"` while body stays v1 / synthetic).
- Restore free-string constructor kwarg that assigns to
  `self.prompt_or_task_version` → assertion (5) / free-string rejection
  proof fails.

**(b) Discrimination**

- Always-`"1"` settings hardcode passes (2) under default selection but fails
  (3) under synthetic rebind.
- Independent body+version globals pass stamp-only checks but fail posted-
  body equality under synthetic rebind.

**Operator promotion path (explicit):** promoting lineage is a deliberate
code rebind of `PRODUCTION_PROMPT` (body + `lineage_version` together), not
an env flip of a version number alone and not a free-string constructor
override. No free-string `ACX_GPU_PROMPT_VERSION` escape hatch and no free-
string constructor stamp kwarg ship in this plan (see also No canon warrant
— mechanical promotion UX is out of scope).

#### [TEST-15] red-first proof — free-string constructor override rejected (MANDATORY)

**Test name (proposed):**
`test_gpu_adapter_rejects_free_string_prompt_version_kwarg`

**Why mandatory:** Dropping only the env stamp path still leaves
`GpuRemoteDescriptionAdapter(prompt_or_task_version="9")` as a supported
way to post the v1 body under a lying stamp (today's assignment at
`gpu_remote_adapter.py:133`/`:143` + post at `:182`). Round-3 finding
DPR3-M-02 asked to **preserve** the explicit-override test at
`test_gpu_remote_adapter.py:51-65`; that requirement is **closed wontfix,
superseded by DPR4-H-01**. Do not reinstate a preserve-the-override
checklist item.

**What it asserts:**

1. **Parameter absent (preferred shape).** Constructing
   `GpuRemoteDescriptionAdapter(..., prompt_or_task_version="9")` raises
   `TypeError` (unexpected keyword argument) — the free-string kwarg does
   not exist on the constructor.
2. **Stamp always from selected config.** A normally constructed adapter
   (no stamp kwarg) has
   `.prompt_or_task_version == production_prompt_or_task_version()` under
   default selection **and** after synthetic `PRODUCTION_PROMPT` rebind
   (same five-surface path as above).
3. **Owned-test rewrite.** `test_gpu_remote_adapter.py:51-65` no longer
   passes `prompt_or_task_version="3"` or asserts `== "3"`; it omits the
   kwarg and asserts the honest stamp (or the free-string-rejection test
   owns the negative path exclusively). Payload/transport assertions in
   that file may remain.

**(a) Exact edit that makes it go red**

- Reintroduce a free-string constructor parameter that is assigned to
  `self.prompt_or_task_version` (today's shape at
  `gpu_remote_adapter.py:133`/`:143`, any default including
  `str | None = None` that is honored when provided) → assertion (1)
  fails: `GpuRemoteDescriptionAdapter(..., prompt_or_task_version="9")`
  no longer raises `TypeError`, **and/or** a constructed instance stamps
  `"9"` while `describe()` still posts the v1 body at the payload site.

**(b) Discrimination / permanent guard**

- **Cheating shape killed:** keep settings/env honest but re-add the
  free-string constructor kwarg so direct construction (and any future
  caller) can lie about lineage without touching `PRODUCTION_PROMPT`.
- Permanent guard ships as assertion (1) (`TypeError` on free-string
  kwarg) plus assertion (2) (stamp == selected config). A "silent ignore
  of the kwarg" implementation (parameter still present, value discarded)
  fails assertion (1) — the preferred shape is **no caller-supplied
  version exists at all**, not a no-op parameter.
- Alternative closed-lineage-enum shape (only if removal is blocked by an
  unforeseen interface constraint — **not** the planned path): kwarg type
  is a closed enum of selected lineage ids and any free string is
  rejected; red-first then is accepting an arbitrary string again. This
  plan's prescribed implementation is **removal**, not the enum fallback.

## Consolidated Checklist

### Context and Ownership

- [ ] Loaded governing assessment §1 D1–D3 and §10g Lane A scope before editing.
- [ ] Verified every cited rule ID via definition-anchor grep under
      `canon/lexicons/`; read distilled evidence for each load-bearing rule.
- [ ] Confirmed file ownership: only Lane A paths + new shared-prompt module +
      proving tests + owned one-line `deps.py:98` drop of free-string stamp
      kwarg; no Lane B schema edits; no Lane C metrics edits.
- [ ] Confirmed prompt-body copies: exactly two live v1 copies before the
      change; zero local copies after.
- [ ] Register / fact-inventory / voice-partition work is DEPICT-1 — not
      absorbed here. Weave rewrite is F1 (b) — unowned, not absorbed here.

### Checklist for Slice 1: Single prompt source + parity test

- [ ] Create `scene/prompts/caption_system.py` with markers, production v1
      body, selected `ProductionPrompt` (or body landing that Slice 2 binds),
      `production_system_prompt()` — **not** `PromptVariant`, v2/v3 bodies, or
      full `PROMPT_VARIANTS`.
- [ ] Rewire `gpu_remote_adapter.py` to import production system prompt; delete
      local `_SYSTEM_PROMPT` body; use shared string at the payload site
      (`messages[0]["content"]` — today `gpu_remote_adapter.py:182`).
- [ ] **Delete** the stale `ACX_GPU_PROMPT_VERSION` bump instruction at
      `gpu_remote_adapter.py:23-24` (exact text: "Bump ACX_GPU_PROMPT_VERSION
      / default prompt_or_task_version when this contract changes.") and
      replace the "Keep in lockstep…" block with a pointer to
      `scene/prompts/caption_system.py` + parity/inventory tests. Do not leave
      any operator instruction to bump `ACX_GPU_PROMPT_VERSION`.
- [ ] Rewire `bakeoff.py`: import shared v1 body + markers; **keep local
      `PromptVariant`**; delete local `_PROMPT_V1_SYSTEM` only; keep
      `_PROMPT_V2_SYSTEM` and local `PROMPT_VARIANTS` construction; keep
      `DEFAULT_PROMPT_VARIANT = "v1"` defined in bakeoff; keep
      pass-1/weave/compress local.
- [ ] Add `test_prompt_lineage_seam.py` parity test that **transport-stubs**
      `describe()`, captures `messages[0]["content"]`, and asserts
      whitespace-normalised equality to
      `bakeoff.PROMPT_VARIANTS["v1"].system` (attribute-only comparison
      forbidden in the docstring).
- [ ] Document red-first edit (a) — change only the payload-inserted string —
      and discrimination case (b) (including the three cheating shapes) in the
      test docstring.
- [ ] **MANDATORY** single-source **assembled-value** inventory test
      (`test_production_v1_body_has_exactly_one_definition` or equivalent) —
      **not** optional / not stretch. Key on the **assembled** body from
      `production_system_prompt()` (import + whitespace-normalise), **not** a
      raw source-text grep for `"2-4 plain sentences"` (that marker is
      split-evadeable; today's body is already multi-line concat + f-string at
      `gpu_remote_adapter.py:28-37` / `bakeoff.py:89-98`). Assert **exactly
      one** full-body definition whose assembled value equals the canonical
      body, at exactly `scene/prompts/caption_system.py`. Permitted non-
      definition hits only:
      1. bakeoff long-band
         `.replace("2-4 plain sentences", "4-8 plain sentences")` on the
         imported v1 body (derived string / replace argument, not a second
         independent full body),
      2. tests that quote fragments,
      3. the accessor itself (reads the one definition).
      **Forbidden:** full v1 body still in `gpu_remote_adapter.py`, a second
      `_PROMPT_V1_SYSTEM`-style body in `bakeoff.py`, any third full
      assignment under `scene/` / `scripts/eval_harness/`, including
      split-literal assemblies.
      Red-first mutation (a): inject a second full-body assignment whose
      assembled value equals the canonical body → count/location fails.
      Permanent split-literal guard (a′): inject a duplicate assembled via
      `"2-" + "4 plain sentences"` (or equivalent) that lacks the contiguous
      substring → assembled inventory fails; substring-grep would stay green.
      Discrimination (b): consumer-parity alone stays green under (a)/(a′);
      only the inventory test catches the unused third body.
      **Do not use as the sole inventory key:** the weave clause
      `"Weave the people's names and factual details it supplies"` (also in
      harness v2 at `bakeoff.py:116-118`), the shared opener
      `"You write alt text for images on a personal website"` (also in v2),
      or a source-text substring grep alone.
- [ ] Verification:
      `uv run --extra dev pytest scene/tests/test_prompt_lineage_seam.py scene/tests/test_gpu_remote_adapter.py scene/tests/test_eval_harness_pipeline.py -q`

### Checklist for Slice 2: Honest atomic version stamp

- [ ] Selected `ProductionPrompt` carries `body` + `lineage_version` together;
      accessors read that one instance (no independent body global + version
      map / variant key).
- [ ] Point `settings.gpu_prompt_or_task_version` default_factory at
      **only** `production_prompt_or_task_version()`; **drop** free-string
      `ACX_GPU_PROMPT_VERSION` stamp override (today `settings.py:40`).
- [ ] **Remove** free-string `prompt_or_task_version` constructor kwarg from
      `GpuRemoteDescriptionAdapter.__init__` (today `gpu_remote_adapter.py:133`
      / assigned at `:143`); always bind
      `self.prompt_or_task_version = production_prompt_or_task_version()` at
      init (call-time read). Payload system message through
      **`production_system_prompt()` only** at describe time (not
      `PRODUCTION_PROMPT.body` direct read, not frozen default-arg /
      import-time copies, not a dedicated body export). **Do not** keep
      `str | None = None` as an honored free-string override.
- [ ] **Owned one-line** `deps.py:98`: drop
      `prompt_or_task_version=settings.gpu_prompt_or_task_version` so
      production wiring matches the constructor with no stamp kwarg.
- [ ] Update **resolved-default** dishonest sites:
      `test_description_profiles.py:214` and `:263` → expect `"1"`;
      `test_settings.py` → assert GPU default `"1"`.
- [ ] **Rewrite** `test_gpu_remote_adapter.py:51-65`: remove
      `prompt_or_task_version="3"` and `assert == "3"`; omit the kwarg;
      assert stamp equals `production_prompt_or_task_version()` / `"1"`.
      Keep payload/transport assertions. DPR3-M-02 preserve-override is
      **wontfix / superseded** — do not reinstate it.
- [ ] **Add** no-arg constructor default test expecting `"1"` /
      `production_prompt_or_task_version()`.
- [ ] **Add** free-string constructor rejection proof
      (`test_gpu_adapter_rejects_free_string_prompt_version_kwarg`):
      `GpuRemoteDescriptionAdapter(..., prompt_or_task_version="9")` raises
      `TypeError`; red-first mutation reintroduces an honored free-string
      kwarg.
- [ ] Add default-honesty + **synthetic-v2** five-surface discrimination:
      inject `ProductionPrompt(body="SYNTHETIC…", lineage_version="2")` and
      assert posted `messages[0]["content"]`, adapter stamp, **and**
      `DescriptionSettings().gpu_prompt_or_task_version` all equal the injected
      values (via accessors / call-time reads).
- [ ] Add **resolver no-divergence** test: production path cannot stamp one
      lineage while posting another body; `ACX_GPU_PROMPT_VERSION=9` must not
      create that divergence; free-string constructor path must not either.
- [ ] State cache-key consequence in the PR/handoff note: greenfield accept;
      no migration/shim.
- [ ] Verification:
      `uv run --extra dev pytest scene/tests/test_prompt_lineage_seam.py scene/tests/test_settings.py scene/tests/test_description_profiles.py scene/tests/test_gpu_remote_adapter.py -q`

### Review Readiness

- [ ] No boundary-touching schema change left undocumented (expected: none).
- [ ] Parity test cannot pass by reading the same constant twice or by
      attribute-only comparison; it reads the posted system string.
- [ ] **Mandatory** single-source inventory test asserts definition count == 1
      at exactly `caption_system.py` by **assembled-value** equality (import +
      normalise); red under a second full-body assignment **and** under a
      split-literal duplicate that would evade a source-text substring grep.
- [ ] Version stamp cannot sit at `"3"` for production v1 text under default
      construction; free-string `ACX_GPU_PROMPT_VERSION` cannot stamp a
      lineage the posted body does not carry; free-string constructor
      `prompt_or_task_version="9"` is impossible / rejected (parameter
      removed).
- [ ] Atomic discrimination reaches red under: independent body+version
      globals, always-`"1"` stamp function, settings hardcode of `"1"`,
      import-time-frozen adapter default, import-time body binding that
      misses the module-attribute monkeypatch, free-string env stamp, or
      free-string constructor override.
- [ ] Resolver no-divergence test covers production adapter stamp + posted
      body together (including negative env-stamp and free-string constructor
      paths).
- [ ] No second full copy of the production system-prompt body remains under
      `apps/prototype-description-service/`; inventory keys on assembled
      `production_system_prompt()` value (not a source-text marker grep alone;
      not the weave clause).
- [ ] Stale `ACX_GPU_PROMPT_VERSION` bump instruction deleted from
      `gpu_remote_adapter.py:23-24`.
- [ ] `PromptVariant` and harness-only v2/v3 bodies remain in `bakeoff.py`
      (not shipped into the production shared module).
- [ ] Cache-key hazard acknowledged; no compatibility shim introduced.
- [ ] Weave-side F1 consumption (F1 (b)) explicitly unowned / Not-Done; no
      lane in this wave delivers it and no plan file owns it.
- [ ] DEPICT-1 register / fact-inventory contract not absorbed here.
- [ ] F2 / F4 / colour work not smuggled into this branch.
- [ ] [REF-26] not cited as warrant; extract justified by comment-only lockstep
      + [REF-10].
- [ ] DPR3-M-02 preserve-the-override requirement not reinstated (wontfix /
      superseded by free-string constructor removal).

## Stretch Goals

- [ ] Optional module-level `__all__` and a one-line README note under
      `scene/prompts/` pointing promoters at the selected `PRODUCTION_PROMPT`
      (rebind body + `lineage_version` together).

## Success Criteria

- [ ] Exactly one definition of the production caption system-prompt text;
      production adapter and harness v1 both consume it via
      `production_system_prompt()` / `production_prompt_or_task_version()`
      only.
- [ ] `test_production_system_prompt_matches_harness_v1` (or equivalent) is red
      under the documented payload-string edit and green at HEAD; it compares
      the transport-captured posted system string to
      `bakeoff.PROMPT_VARIANTS["v1"].system`.
- [ ] `test_production_v1_body_has_exactly_one_definition` (or equivalent)
      is **mandatory**, keys on **assembled** `production_system_prompt()`
      value (not source-text marker grep), red under a second full-body
      assignment **and** under a split-literal duplicate
      (`"2-" + "4 plain sentences"` style), and green at HEAD with count == 1
      at `caption_system.py` only.
- [ ] Default `gpu_prompt_or_task_version` is `"1"`, matching production v1
      text; returned by `production_prompt_or_task_version()` from the same
      selected `ProductionPrompt` that holds the posted body — not hand-
      maintained beside a separate body global, **not** overridable by a
      free-string `ACX_GPU_PROMPT_VERSION` that leaves the body unchanged, and
      **not** overridable by a free-string constructor
      `prompt_or_task_version=` kwarg.
- [ ] `GpuRemoteDescriptionAdapter` has **no** free-string
      `prompt_or_task_version` constructor parameter; stamp always binds from
      `production_prompt_or_task_version()`. Free-string rejection proof is
      red if the kwarg is reintroduced and honored.
- [ ] Atomic discrimination: injecting
      `ProductionPrompt(body="SYNTHETIC…", lineage_version="2")` makes the
      posted system content, a fresh adapter stamp, **and**
      `DescriptionSettings().gpu_prompt_or_task_version` all reflect the
      synthetic values together.
- [ ] Resolver no-divergence: no configured production path stamps one
      lineage while posting another body.
- [ ] Existing GPU adapter + harness pipeline tests green under
      `uv run --extra dev pytest` with the paths above;
      `test_gpu_remote_adapter.py:51-65` rewritten (no free-string `"3"`
      override; honest stamp assertion).
- [ ] Stale `ACX_GPU_PROMPT_VERSION` bump instruction removed from
      `gpu_remote_adapter.py:23-24`.
- [ ] No edits to Lane B schema files or Lane C `caption_metrics.py`.
- [ ] No prompt wording changes; no colour vocabulary; no metrics; no
      three-surface production promotion.
- [ ] `PromptVariant` remains defined only in `bakeoff.py`.

## Not-Doing

- Changing what any prompt **says** (F2 emotion-bearer wording, F4
  three-surface production promotion, F1 weave clause rewrite). Unblocked by
  this seam; not shipping in DEPICT-0.
- **Weave-side context consumption / F1 voice-honouring prompt behaviour**
  is **unowned** — F1 (b) in DEPICT-1's ownership-split table, not DEPICT-1.
  This plan closes the dual-prompt *seam* only; **no lane in this wave**
  (DEPICT-0 / DEPICT-1 / DEPICT-2) delivers the weave rewrite, and no plan
  file owns it. Leave it explicitly open and unowned.
- **Register / fact-inventory / voice-partition contract** — DEPICT-1 owns
  those surfaces; do not add inventory-guard or partition prose here.
- Moving harness-only `PromptVariant`, v2/v3 prompt bodies, or the full
  `PROMPT_VARIANTS` registry into the production shared module ([REF-10]:
  different knowledge; production does not execute those paths today).
- Metrics, scorers, or any edit to `caption_metrics.py` (Lane C).
- Contract, schema, or enum changes (Lane B).
- Colour vocabulary of any kind (assessment §10e trigger-gated).
- Cache migration, dual-key reads, or `"3"` compatibility shims.
- Moving harness-only pass-1 / weave / compress prompts into the shared module
  ([REF-10]: different knowledge).
- Citing `FM-11`, `HARM-01`, or non-existent `REG`/`ICON`/`FRAM`/`SEL` IDs.
- Citing [REF-26] as extract warrant (multi-format trigger does not fire;
  use comment-only lockstep + [REF-10] instead).
- Preserving free-string `ACX_GPU_PROMPT_VERSION` as an independent stamp
  source (would re-certify stamp/body divergence via settings stamp +
  `gpu_remote_adapter.py:182` body post).
- Preserving free-string constructor
  `prompt_or_task_version: str = …` on `GpuRemoteDescriptionAdapter`
  (today `gpu_remote_adapter.py:133`/`:143`) — would re-certify stamp/body
  divergence via `GpuRemoteDescriptionAdapter(prompt_or_task_version="9")`
  over the v1 body at `:182`. DPR3-M-02 preserve-the-override is
  **wontfix / superseded**; do not reinstate it.
- Keying the single-source inventory solely on a source-text substring grep
  for `"2-4 plain sentences"` (split-literal evadeable; today's body is
  already multi-line concat + f-string at `gpu_remote_adapter.py:28-37`).
- Leaving the stale "Bump ACX_GPU_PROMPT_VERSION …" operator instruction at
  `gpu_remote_adapter.py:23-24` after this plan drops that control.
- Consumer binding via direct `PRODUCTION_PROMPT.body` reads or dedicated
  import-time body exports (misses Slice-2 module-attribute monkeypatch).

## No canon warrant

- **Mechanical promotion UX** (e.g. an operator CLI flag, free-string env, or
  free-string constructor kwarg that flips production lineage without
  carrying the body) is not required by cited canon and is **actively
  forbidden** as a stamp-only escape hatch; the seam needs body + lineage
  version to share one selected `ProductionPrompt` so a promotion is a small
  deliberate rebind rather than a hand-copy, env flip, or constructor
  override that can desync stamp from body. No fabricated rule ID for
  "promotability."
- **Whitespace-normalised comparison** as the parity predicate is an
  engineering choice matching the assessment's D1 measurement method, not a
  separate canon row.
