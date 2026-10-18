# DEPICT-0. Prompt-lineage seam (one source, parity test, honest version stamp)

Task: DEPICT-0 · Branch: `feature/depict-0` · Status: planned
Date: 2026-07-27 · Author: grok-4.5 (remote flock lane A) · Project: prototype-description-service
Review Coverage Target: 2

> **DEPICT task family**: depiction-canon backlog item 1 (P0) from
> [`docs/assessments/current/depiction-canon-triage-and-backlog-2026-07-27.md`](../../assessments/current/depiction-canon-triage-and-backlog-2026-07-27.md)
> §2 / §10g. Plans for this flock lane live under `docs/tasks/` once accepted;
> this file is the implementation task plan only.

## Objective

Close the production↔harness **duplicated-v1** prompt-lineage seam: one module
owns the production caption system-prompt text, both the GPU production
adapter and the eval harness v1 entry consume it, a parity test fails when
they diverge, and `prompt_or_task_version` honestly labels the prompt text
that actually ships (stamp = selected `ProductionPrompt.lineage_version` only
— see **N1** under Constraints).

**Promotion scope (N9):** this plan closes today's duplicated-v1 seam and makes
body + lineage one selected object. It does **not** add a mechanical
promotion path for harness v2/v3 into production — those bodies stay in
`bakeoff.py` `PROMPT_VARIANTS` only; production continues to post the single
selected `ProductionPrompt`. A later follow-up task owns mechanical promotion.
Atomic body+stamp is a **prerequisite** for that follow-up, not the promotion
itself. Do not read this Objective as "v2/v3 can now reach production."

## Problem Statement

Three code facts (governing assessment §1, D1–D3) make every later prompt
upgrade unsafe or untraceable today:

1. **D1 — two surfaces, comment-only lockstep.**
   `scene/infrastructure/vlm/gpu_remote_adapter.py:28` `_SYSTEM_PROMPT` is
   textually identical (whitespace-normalised) to
   `scripts/eval_harness/bakeoff.py:89` `_PROMPT_V1_SYSTEM`. The lockstep is a
   comment at `gpu_remote_adapter.py:23` ("Keep in lockstep with … bakeoff.py
   (VLMRP-HARM-01)") and nothing else.
   `scene/tests/test_eval_harness_pipeline.py:104-145` compares harness
   variants to each other (including the v1 system-message equality at
   `:145`); **nothing compares harness to production**. A prompt fix
   landed only in `bakeoff.py` changes nothing that ships. There is also no
   mechanical path to promote a harness variant into production — **and this
   plan does not create one** (N9); it only closes the v1 dual-surface seam.
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
3. **D3 — v3 promotion window still open (out of this plan's delivery).**
   No three-surface JSON path exists outside the harness; production returns
   single-surface prose. Closing D1 (one production v1 source + parity +
   atomic `ProductionPrompt`) is the **prerequisite** so a later follow-up
   can replace the selected config without hand-copying strings while the
   stamp drifts. That follow-up is **not** DEPICT-0 (N9).

Inventory of the production v1 system-prompt body (assembled value today
from the multi-line / f-string construction at `gpu_remote_adapter.py:28-37`
and `bakeoff.py:89-98`; v1-unique token `"2-4 plain sentences"` appears at
`gpu_remote_adapter.py:30` and `bakeoff.py:91` but is **not** the inventory
key — see Slice 1 foldable-constant definition-site inventory): **exactly two live v1 body
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
    (**delete** `gpu_prompt_or_task_version` — zero readers after deps drop)
  - `apps/prototype-description-service/scene/interface_adapters/http/deps.py`
    (**only** the one-line drop of
    `prompt_or_task_version=settings.gpu_prompt_or_task_version` at
    `deps.py:98` once the adapter no longer accepts a free-string stamp
    kwarg — no other deps edits)
  - **exactly one** new shared-prompt module: `scene/prompts/caption_system.py`
    (plus package `__init__.py` only if the package does not already exist;
    closed set — same collision rule as the test-set bullet below)
  - **exactly these five test surfaces** (closed set; the assessment's
    `#### §6e ownership table` Lane A row is the collision oracle for the
    wave and supersedes any open wording here):
    `scene/tests/test_prompt_lineage_seam.py` (new),
    `scene/tests/test_gpu_remote_adapter.py`,
    `scene/tests/test_description_profiles.py`,
    `scene/tests/test_settings.py`,
    and — for `scene/tests/test_eval_harness_pipeline.py` — **only** these
    **named test functions** (closed set over function names, not an open
    assertion filter over the file path; two lanes editing disjoint
    assertions in the same file with only a path partition has no oracle):
    `test_v1_variant_is_the_unchanged_baseline_prompt`,
    `test_selected_variant_reaches_system_message`
    (the production↔harness v1 lockstep surfaces today at
    `test_eval_harness_pipeline.py` under those names; verified — the file
    currently has no free-string `"3"` / constructor-override assertions;
    those live in `test_gpu_remote_adapter.py` / `test_description_profiles.py`
    which this plan owns wholesale). Edits to any other function in
    `test_eval_harness_pipeline.py` are out of scope. Adding a **new**
    test function in that file for lineage/lockstep requires naming it in
    this bullet **before** the edit (same collision rule as paths).
    **Collision rule:** any additional production or test path **or** any
    additional named test function in a shared file requires
    amending DEPICT-0 `## Constraints` **and** the assessment's
    `#### §6e ownership table` Lane A row before the edit.
- **Do not edit** Lane B surfaces owned by DEPICT-1
  (`scene/interface_adapters/http/schemas/requests.py` and co-located schema
  helpers / domain enums that DEPICT-1 claims) or Lane C surfaces
  (`scripts/eval_harness/caption_metrics.py` and its tests).
  `scene/interface_adapters/http/schemas/responses.py` is **unowned in this
  wave** (DEPICT-1 explicitly disclaims it; this plan also does not edit it —
  the `prompt_or_task_version` response field already exists and needs no
  schema change).
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

### Normative claims (canonical — state once; all later sections reference)

Proofs, checklists, and slice notes **must not restate** these; cite the id
(`N1` … `N10`).

- **N1 — Stamp binding.** Adapter stamp is only
  `self._production_prompt.lineage_version` from a single
  `production_prompt()` snapshot at `__init__`. Forbidden escape hatches:
  free-string env `ACX_GPU_PROMPT_VERSION`, free-string constructor kwarg
  `prompt_or_task_version`, differently-named free-string stamp formals,
  settings field `gpu_prompt_or_task_version`, post-init env rewrite of the
  stamp. DPR3-M-02 preserve-the-override is **wontfix / superseded**.

- **N2 — Import-time env silence (EFFECT class proof; EXIT A).** Computed
  property: *no environment read occurs during import of
  `scene.prompts.caption_system`*. Proof: replace `os.environ` with a mapping
  whose `__getitem__` and `get` **raise on any key**, then
  `importlib.reload` the module; reload must succeed (no exception). This is
  not a name filter and not a constant-node filter — it closes split-key
  (`os.environ["ACX_GPU_" + "PROMPT_VERSION"]`), `.replace()` / `"".join`
  key assembly, and any spelling that still performs a runtime lookup.
  Held-out exemplar (must not appear as a contiguous literal in the
  implementation under test as the sole defence — the effect proof is what
  holds): key assembled as `"ACX" + "_GPU_PROMPT_VERSION"`. Scope: import of
  `caption_system` only. Post-import adapter/DI paths are N3.

- **N3 — Post-import stamp honesty (EXIT B — bounded probes).** Covers
  **exactly** residual `"3"` and junk `"9"` env values for
  `ACX_GPU_PROMPT_VERSION` on direct-constructor and DI-resolver adapter
  construction: stamp equals `production_prompt().lineage_version` / `"1"`
  under default selection. Does **not** generalise to an open set of probe
  values; extending the probe set requires amending this plan. Companion to
  N2, not a substitute for it.

- **N4 — Source-guard contract (AST-scoped; wave-aligned with DEPICT-2).**
  Guarded files (create-or-edit set only — not repo-wide):
  `scene/config/settings.py`,
  `scene/interface_adapters/http/deps.py`,
  `scene/infrastructure/vlm/gpu_remote_adapter.py`,
  `scene/prompts/caption_system.py`.
  Extract **decoded string constant values** from each file's AST (not raw
  `Path.read_text()` substrings):

  ```python
  import ast
  from pathlib import Path

  def _strip_docstrings(tree: ast.AST) -> ast.AST:
      for node in ast.walk(tree):
          if isinstance(node, (ast.Module, ast.FunctionDef,
                               ast.AsyncFunctionDef, ast.ClassDef)):
              if (node.body
                  and isinstance(node.body[0], ast.Expr)
                  and isinstance(node.body[0].value, ast.Constant)
                  and isinstance(node.body[0].value.value, str)):
                  node.body = node.body[1:]
      return tree

  def module_string_constants(path: Path) -> set[str]:
      tree = _strip_docstrings(ast.parse(path.read_text(encoding="utf-8")))
      out: set[str] = set()
      for node in ast.walk(tree):
          if isinstance(node, ast.Constant) and isinstance(node.value, str):
              out.add(node.value.lower())
          if isinstance(node, ast.JoinedStr):
              for v in node.values:
                  if isinstance(v, ast.Constant) and isinstance(v.value, str):
                      out.add(v.value.lower())
      return out
  ```

  Guard fails if any collected constant `c` has
  `"acx_gpu_prompt_version" in c` (single-token held-out; article-strip is
  a no-op). **Comments stay legal** (not `ast.Constant`). **Docstrings are
  stripped** before the walk so a WHY docstring that *names* the forbidden
  env key does not false-RED (aligns with the AST env pin, which never saw
  docstring text as an environ read — L-01). Held-out literal protected:
  `ACX_GPU_PROMPT_VERSION`. Claim is EXIT B for this one name over these
  four files; the extraction method (AST constants, not raw text) is the
  DEPICT-2 form so the wave does not ship two definitions of "source guard."

- **N5 — Construction-site lineage pin.** Module-level
  `PRODUCTION_PROMPT = ProductionPrompt(...)` has keyword `lineage_version=`
  whose value node is `ast.Constant(value="1")` (not Call/Name/BinOp/IfExp/
  JoinedStr). Import-time env silence for the rest of the module is **N2**,
  not a second constant-key AST walk.

- **N6 — Wire E2E lineage (body + stamp together).** After
  transport-stubbed `describe()` on a production-path adapter (direct
  constructor **and** DI `deps.get_gpu_description_adapter`):
  `adapter.prompt_or_task_version == production_prompt().lineage_version`
  **and** whitespace-normalised posted `messages[0]["content"]` equals both
  `production_prompt().body` and `adapter._production_prompt.body`. Closes
  "source shape honest, value on the wire lying."

- **N7 — `__init__` formals (superset + forbidden set).** Collect formal
  names on `GpuRemoteDescriptionAdapter.__init__` excluding `self`. Assert:
  (a) `REQUIRED ⊆ formals` where
  `REQUIRED = {endpoint_url, model_id, model_version, connect_timeout_s,
  read_timeout_s, api_key, max_concurrent_calls, transport}`;
  (b) `formals ∩ FORBIDDEN == ∅` where
  `FORBIDDEN = {prompt_or_task_version, stamp_version, task_version,
  version_stamp, gpu_prompt_or_task_version}` — **exactly these five names**;
  extending FORBIDDEN requires amending this plan (EXIT B);
  (c) `args.vararg is None` and `args.kwarg is None`.
  Legitimate additive optional non-lineage formals (e.g. `retry_count: int = 0`)
  stay GREEN under (a)–(c). Exact set equality is **forbidden** as the
  assertion form (false-REDs additive extension).

- **N8 — Stamp assignment provenance.** Load-bearing form is **runtime** N6
  (and free-string rejection positive control stamp equality). An optional
  AST companion over `__init__` may inspect writes to
  `self.prompt_or_task_version` / `setattr(self, "prompt_or_task_version", …)`
  but **must accept** pure reaching definitions from
  `production_prompt()` / `self._production_prompt` culminating in
  `.lineage_version`, **including intermediate locals of any depth**
  (e.g. `snap = production_prompt(); lv = snap.lineage_version;
  self.prompt_or_task_version = lv`). Reject free-string parameter `Name`s
  and env `Call`s when present. Do **not** false-RED intermediate locals.

- **N9 — Promotion scope.** See Objective. Harness v2/v3 remain bakeoff-only.
  No mechanical promotion path ships in DEPICT-0.

- **N10 — Slice 1 lands full atomic `ProductionPrompt`.** Slice 1 **must**
  land body + `lineage_version` on one `ProductionPrompt` object in
  `caption_system.py`. Staged "body + markers first, bind in Slice 2" is
  **not** permitted — Slice 1 inventory proof requires the body already
  bound into `ProductionPrompt` there.

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
- **Shared-prompt module**: `scene/prompts/caption_system.py` — single authority for the
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
  instance with the v1 body and `lineage_version="1"`. The primary accessor
  is `production_prompt() -> ProductionPrompt`, which returns that **same**
  selected instance. Thin field accessors
  `production_system_prompt()` / `production_prompt_or_task_version()` are
  defined as `return production_prompt().body` /
  `return production_prompt().lineage_version` — they are not independent
  globals that can desync from each other or from the selected instance.
- **Adapter prompt snapshot**: `GpuRemoteDescriptionAdapter.__init__` calls
  `production_prompt()` **once**, stores the returned object on the instance
  (e.g. `self._production_prompt`), and derives **both** the posted body
  (`self._production_prompt.body` at describe/payload time) and the lineage
  stamp (`self.prompt_or_task_version = self._production_prompt.lineage_version`
  at init) from that snapshot. **Temporal invariant:** body and stamp are
  read from the same object at the same instant, so no interleaving (including
  a later rebind of module-level `PRODUCTION_PROMPT`) can separate them on an
  already-constructed adapter.
- **Honest version stamp**: the adapter `prompt_or_task_version` value that
  names the production-selected prompt's lineage id (today: `"1"` for v1
  text), obtained from the adapter's init-time `production_prompt()` snapshot
  (`.lineage_version`) — not a free-floating `"3"`, not a separate map keyed
  independently of the posted body, not an import-time-frozen constant that
  ignores the selected config, **not** a free-string env
  (`ACX_GPU_PROMPT_VERSION="9"`) that can stamp a lineage the posted body does
  not carry, **not** a free-string constructor kwarg
  (`GpuRemoteDescriptionAdapter(prompt_or_task_version="9")` at today's
  `gpu_remote_adapter.py:133` / `:143`) that stamps independently of the
  selected `ProductionPrompt`, and **not** a settings field
  (`DescriptionSettings.gpu_prompt_or_task_version`) with no production
  reader after the free-string constructor path is removed.
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
  (`settings.py:40`); today `deps.get_gpu_description_adapter` passes
  `settings.gpu_prompt_or_task_version` at `deps.py:98`. After this plan
  removes the free-string constructor kwarg, that settings field has
  **zero production readers** (exhaustive: only the definition at
  `settings.py:40` and the `deps.py:98` call site). **Delete the field**
  from `DescriptionSettings` in this slice (greenfield delete-over-flag).
  **`deps.py:98` MUST drop**
  `prompt_or_task_version=settings.gpu_prompt_or_task_version` once the
  constructor parameter is removed (owned one-line delete — same mandate
  restated under Proposed Solution → Consumers → `deps.py:98`). Do **not**
  leave the field or the deps argument "because settings became honest" —
  honesty of a field with no reader cannot discriminate a production
  lineage lie.
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
  - `scene/tests/test_settings.py:8-14`
    (`test_description_settings_defaults`) checks non-GPU
    `prompt_or_task_version == "1"` but **never mentions**
    `gpu_prompt_or_task_version` (verified). Under this plan the GPU field
    is **deleted** (not repointed), and an **unconditional**
    `not hasattr(…, "gpu_prompt_or_task_version")` +
    `"gpu_prompt_or_task_version" not in DescriptionSettings.model_fields` +
    absent from `DescriptionSettings().model_dump()` +
    `ACX_GPU_PROMPT_VERSION` env-no-effect proof must ship — a conditional
    "if a settings test previously mentioned the field" rewrite never fires.
- Harness tests compare variants to each other only
  (`test_eval_harness_pipeline.py:104-145`, including the v1 system-message
  equality at `:145`); no production cross-check.
- Whitespace-normalised identity of the two v1 bodies verified in this planning
  pass (length 528, equal).

## Target Outcome

- Exactly one Python definition of the production caption system-prompt text
  (and of the context-marker pair the system prompt interpolates).
- Production adapter and harness v1 both import that definition; no local
  re-declaration of the v1 body remains in either consumer file.
- Harness-only `PromptVariant`, v2/v3 bodies, and `PROMPT_VARIANTS` remain in
  `bakeoff.py` (different knowledge — [REF-10]); a later follow-up (not this
  plan — N9) may replace the selected `ProductionPrompt` as a deliberate
  change. This seam does not promote v2/v3.
- A deterministic parity test fails if the production runtime system string
  (the string `describe()` actually POSTs as `messages[0]["content"]`) and
  harness `PROMPT_VARIANTS["v1"].system` diverge (whitespace-normalised)
  under the **same-construction-epoch** temporal scope (option (a): a live
  rebind does not rewrite an already-built harness registry; rebind-before-
  construction proof calls `build_prompt_variants()` after rebind and covers
  the helper-time accessor bind).
- Adapter stamp is the selected `ProductionPrompt.lineage_version` (today
  `"1"`) — body and stamp live on **one snapshot object** taken at
  `__init__` via `production_prompt()`, so they cannot desync on that
  instance (temporal invariant). `DescriptionSettings.gpu_prompt_or_task_version`
  is **deleted** (zero readers after `deps.py:98` drop). The adapter
  constructor binds stamp **and** posted body from the same
  `production_prompt()` snapshot with **no** free-string
  `prompt_or_task_version` kwarg at all. There is no independent version
  map, free-floating `"1"`/`"3"` constant beside a separate body global,
  free-string `ACX_GPU_PROMPT_VERSION` override, free-string constructor
  path that stamps without carrying the body, or settings field that
  asserts the accessor against itself.
- Cache-key consequence of the stamp correction is stated in-plan and accepted
  under greenfield policy; no migration/shim code.

## Context Loading

Repo-root-relative paths only (service root =
`apps/prototype-description-service/` in the real monorepo). Dropped any
entry that does not resolve in-checkout (no workbay rules tree is present).

- Governing assessment:
  `docs/assessments/current/depiction-canon-triage-and-backlog-2026-07-27.md`
  (§1 D1–D3, §2 item 1, §10g Lane A — §10 supersedes §9 on scope).
- Upstream eval (background only):
  `docs/assessments/current/depiction-canon-fit-captioning-pipeline-2026-07-27.md`.
- Production surfaces (under service root):
  `scene/infrastructure/vlm/gpu_remote_adapter.py`,
  `scene/config/settings.py`,
  `scene/application/hashing.py` (cache-key shape; read-only),
  `scene/interface_adapters/http/deps.py` (wiring; **owned one-line edit** at
  `deps.py:98` to drop free-string `prompt_or_task_version=` — N1; no other
  deps edits).
- Harness surface: `scripts/eval_harness/bakeoff.py` (prompt registry and
  `PROMPT_VARIANTS` consumers).
- Existing tests to extend/correct:
  `scene/tests/test_gpu_remote_adapter.py` (rewrite free-string override at
  `:51-65`; add free-string rejection proof — N1/N7),
  `scene/tests/test_description_profiles.py`,
  `scene/tests/test_eval_harness_pipeline.py`,
  `scene/tests/test_settings.py`.
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
| Describe response schema (`prompt_or_task_version` field) | unowned this wave (`responses.py` disclaimed by DEPICT-1; field already present) | optional/required string already present on response models | **none** — field shape unchanged; only the default *value* for the GPU profile changes from `"3"` → honest `"1"` (adapter snapshot of `ProductionPrompt.lineage_version`) | no schema compat work; greenfield accepts value change | existing schema/parity tests still pass; GPU profile tests updated to expect `"1"` |
| Description cache key | this service | includes `prompt_or_task_version` | default GPU stamp changes ⇒ new keys for previously `"3"`-labelled rows | **no** — greenfield, no migration, no dual-read | document in plan; unit tests of hashing unchanged (they take the stamp as input) |
| `DescriptionSettings.gpu_prompt_or_task_version` | this plan | free-string env-backed default `"3"` (`settings.py:40`); only production reader is `deps.py:98` | **deleted** with the free-string constructor path (zero readers; delete-over-flag) | **no** | field absent; free-string rejection + adapter stamp proofs |
| Eval harness run-record provenance | harness | `prompt_variant` already stamped | v1 body import path may change; `PROMPT_VARIANTS` still built in bakeoff; provenance field names unchanged | no | `pytest scene/tests/ -k eval_harness` green |

Strictly local to the description service. No WP contract change. No bulk/async
surface change.

## Proposed Solution

Introduce exactly one shared-prompt module — `scene/prompts/caption_system.py` — that is the single
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

   def production_prompt() -> ProductionPrompt:
       return PRODUCTION_PROMPT

   def production_system_prompt() -> str:
       return production_prompt().body

   def production_prompt_or_task_version() -> str:
       return production_prompt().lineage_version
   ```
   **`lineage_version` pin:** construction-site Constant `"1"` (**N5**) plus
   import-time env silence EFFECT (**N2**) plus wire E2E stamp/body (**N6**).
   Do not restate the proofs here — implement under Slice 2 lineage proof.
   A runtime-only `production_prompt_or_task_version() == "1"` after import
   is **not** a substitute for N2 (import-epoch blindness under pytest).
   **Primary accessor:** `production_prompt()` returns the selected instance.
   Field accessors always re-read through it. There is **no** separate
   `PRODUCTION_SYSTEM_PROMPT` string global that can stay on v1 while a
   version map / `PRODUCTION_PROMPT_VARIANT` key independently stamps `"2"`.
   There is **no** free-floating `_VARIANT_TO_TASK_VERSION` map that stamps
   without the body. A future **follow-up** (N9, not this plan) may replace
   `PRODUCTION_PROMPT` with a new `ProductionPrompt(body=…,
   lineage_version=…)` so body and stamp move as one for **new** consumers.

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

- `gpu_remote_adapter.py` imports `production_prompt` + markers (field
  accessors may be used by other surfaces; the adapter's load-bearing bind
  is the object accessor); deletes local `_SYSTEM_PROMPT` / local marker
  constants used only for that prompt. Constructor removes free-string stamp
  kwarg (**N1**; today `gpu_remote_adapter.py:133`/`:143`) and **snapshots
  once**: `self._production_prompt = production_prompt()` then
  `self.prompt_or_task_version = self._production_prompt.lineage_version`.
  Payload system message at the site of today's `_SYSTEM_PROMPT`
  (`gpu_remote_adapter.py:182`) posts **`self._production_prompt.body`** —
  not a second call to `production_system_prompt()` / `production_prompt()`
  at describe time, and not a live re-read of module-level
  `PRODUCTION_PROMPT`. **Temporal invariant (load-bearing):** body and stamp
  are taken from the same snapshot object at the same instant (`__init__`),
  so rebinding `caption_system.PRODUCTION_PROMPT` after construction cannot
  produce a v2 body under a v1 stamp (or the reverse) on that instance.
  **Only permitted binding form for production consumers of the selected
  config:** the accessor functions (`production_prompt()` /
  `production_system_prompt()` / `production_prompt_or_task_version()`). Do
  **not** read `PRODUCTION_PROMPT.body` / `.lineage_version` at the call
  site via `from … import PRODUCTION_PROMPT`, and do **not** introduce a
  dedicated frozen body export. Reason: accessors re-read the module global
  `caption_system.PRODUCTION_PROMPT` at **call time**, so
  `monkeypatch.setattr(caption_system, "PRODUCTION_PROMPT", synthetic)` in
  Slice 2 reaches **fresh** `production_prompt()` calls (and therefore fresh
  adapters that snapshot after the rebind); `from scene.prompts.caption_system
  import PRODUCTION_PROMPT` binds the object at import time (rebind never
  reaches the local name), and `DEDICATED = PRODUCTION_PROMPT.body` freezes
  the body string at import the same way. **Delete** the stale
  `ACX_GPU_PROMPT_VERSION` bump instruction in the module comment at
  `gpu_remote_adapter.py:23-24` (exact text: "Bump ACX_GPU_PROMPT_VERSION /
  default prompt_or_task_version when this contract changes.") and replace
  the "Keep in lockstep…" block with a pointer to the shared module +
  parity / inventory test path.
- `bakeoff.py` imports the shared v1 body **only** via the accessor functions
  (same FROZEN CONTRACT A rule; preferred form
  `production_system_prompt()` or `production_prompt().body` — no
  `from … import PRODUCTION_PROMPT`, no dedicated body export) and markers;
  **keeps local `PromptVariant`**; deletes local `_PROMPT_V1_SYSTEM`; keeps
  local `_PROMPT_V2_SYSTEM`. **Factor registry creation into a production
  helper (mandatory):** introduce `build_prompt_variants() -> dict[str,
  PromptVariant]` in `bakeoff.py`; module-level becomes
  `PROMPT_VARIANTS = build_prompt_variants()` (still built once at import;
  consumer read remains `bakeoff.py:595`
  `variant = PROMPT_VARIANTS[self.prompt_variant]`). **v1 body bind at
  helper-construction time (mandatory):** inside `build_prompt_variants`,
  the v1 `PromptVariant(... system=..., ...)` argument is resolved through
  `production_system_prompt()` (or `production_prompt().body`) **at the
  moment the helper runs** — not via a leftover local full-body literal
  and **not** via a module-level
  `_FROZEN_V1 = production_system_prompt()` import-time bind that the helper
  merely reuses. Today that construction is import-time
  (`bakeoff.py:138-141` constructs `PromptVariant("v1", …)` once; `:595`
  reads the stored `variant` from the module-level dict). After rewire the
  helper body is the sole construction site and calls the accessor instead
  of `_PROMPT_V1_SYSTEM`. v2/v3 remain unchanged local text. Keeps
  `DEFAULT_PROMPT_VARIANT = "v1"` locally; re-exports `PROMPT_VARIANTS` /
  `DEFAULT_PROMPT_VARIANT` / `PromptVariant` / `build_prompt_variants` so
  existing `from scripts.eval_harness.bakeoff import PROMPT_VARIANTS` tests
  keep working and the rebind proof can call the real helper.
  **Parity temporal scope (load-bearing — pick (a), committed):** production
  ↔ harness-v1 parity is guaranteed for a given selected-config state when
  **both** consumers are constructed **after** that state is set. A live
  `PRODUCTION_PROMPT` rebind updates **freshly constructed** adapters
  (they snapshot at `__init__`) but does **not** mutate an already-built
  `PROMPT_VARIANTS["v1"].system` string held on the frozen
  `PromptVariant` from an earlier construction (including the import-time
  `PROMPT_VARIANTS = build_prompt_variants()` result). Parity is therefore
  **not** a live cross-process-global guarantee after rebind; it is a
  same-construction-epoch guarantee. The mandated rebind-before-construction
  proof (Slice 1) **must call `build_prompt_variants()` after the rebind**
  (not hand-build a `PromptVariant`) and fails if bakeoff freezes the body
  via `from … import PRODUCTION_PROMPT` / a dedicated body export / a
  leftover local literal / a module-level `_FROZEN_V1` that ignores a
  pre-construction rebind.
- `settings.py` — **delete** `DescriptionSettings.gpu_prompt_or_task_version`
  entirely (today `settings.py:40`, including the free-string
  `os.environ.get("ACX_GPU_PROMPT_VERSION", "3")` default_factory). After
  the free-string constructor kwarg is removed and `deps.py:98` drops the
  only other reader, the field has **zero production readers** and cannot
  discriminate a production lineage lie; retaining it violates greenfield
  delete-over-flag. Do **not** repoint it at
  `production_prompt_or_task_version()` as a dead settings mirror of the
  accessor.
- `deps.py:98` **must** drop
  `prompt_or_task_version=settings.gpu_prompt_or_task_version` once the
  adapter constructor no longer accepts that kwarg (owned one-line delete;
  adapter self-binds stamp **and** body from the `production_prompt()`
  snapshot). This drop is mandatory regardless of any settings honesty
  edit — see Current State Analysis.

Tests (same slices as the behaviour they load-bear):

- **Parity** between production consumer binding (posted system message) and
  harness v1 consumer binding under **same-construction-epoch** temporal
  scope (option (a)), with default-path red-first + discrimination
  ([TEST-15]) **and** rebind-before-construction proof that bakeoff v1
  resolves through the accessor inside `build_prompt_variants()` (proof
  calls that helper after rebind; does not hand-build a `PromptVariant`).
- **Registry provenance (mandatory — CLASS pin, same shape as the
  lineage-version AST proof)** — the registry the harness actually
  reads at `bakeoff.py:595` must have exactly one construction site, and that
  site must be the helper. Source-level assertion over `bakeoff.py`'s AST
  (CWD-independent parse of the module, e.g.
  `Path(scripts.eval_harness.bakeoff.__file__).read_text()` or
  `Path(__file__).resolve().parents[…]` reaching
  `scripts/eval_harness/bakeoff.py`):
  1. **Site pin:** there is a module-level `Assign`/`AnnAssign` whose
     target is the name `PROMPT_VARIANTS` and whose value node is a
     `Call` whose func is the `Name` `build_prompt_variants`, with no
     arguments and no keywords.
  2. **Module-wide class pin (mandatory generalisation):** walk **every**
     `Assign`/`AnnAssign` in the module at **any scope** (module top,
     function body, class body, nested function). Every target named
     `PROMPT_VARIANTS` must have a value node matching the same no-arg
     `Call` to `Name(id="build_prompt_variants")`. A module-top helper
     call that is later overwritten inside a function with a hand-built
     dict (or any non-matching value) fails this pin — a single-site pin
     on only the module-level assignment stays green under that cheat.
  Permanent discrimination guard ([TEST-15]): swapping the module-level
  RHS for a hand-built dict literal — **even one whose v1 body is
  correct** — turns it red; so does any secondary assignment to
  `PROMPT_VARIANTS` whose value is not the helper call. A runtime
  equality check cannot stand in here: in the unrebound import epoch a
  hand-built dict built from `_FROZEN_V1 = production_system_prompt()` and the
  helper's product hold the same string, so only the source shape
  discriminates ([REF-10]: the registry and its construction must change
  together — two construction sites for one registry leave the untested
  site free to drift under the rebind proof as mandated).
- **Single-source inventory (mandatory)** — inventory of **source-level
  foldable-constant definition sites** (any scope; assignment, call-argument,
  **and** `FunctionDef`/`AsyncFunctionDef` `args.defaults`/`args.kw_defaults`)
  whose folded value equals the canonical assembled body equals 1 at exactly
  `caption_system.py`; red-first mutation injects a second full-body
  definition, including a split-literal form, a function-local form, and a
  **default-argument** form ([TEST-15]).
- **Honest atomic stamp** — inject a synthetic `ProductionPrompt`, construct
  a **fresh** adapter after the rebind, and assert posted body and adapter
  stamp both reflect the injected config together; pin
  `adapter._production_prompt is caption_system.PRODUCTION_PROMPT` and
  stamp == snapshot `.lineage_version` ([PROV-09], [PROV-01], [TEST-15]).
  **No** settings-field surface (field deleted with unconditional proof).
- **Temporal body+stamp snapshot (mandatory)** — construct an adapter under
  v1, **then** rebind `PRODUCTION_PROMPT` to synthetic v2, then assert the
  existing adapter is wholly old (body **and** stamp) while a freshly
  constructed adapter is wholly new ([PROV-09], [TEST-15]).
- **Resolver no-divergence (mandatory)** — N1 + N3 + N4 + N6 on both
  direct constructor and DI `deps.get_gpu_description_adapter`
  ([PROV-09], [TEST-15]). Named REDs: post-init env stamp in deps
  (DPR13-H-03); factory body rewrite with honest stamp (DPR15-H-02).
- **Settings GPU-stamp deletion (mandatory, unconditional)** —
  `not hasattr(DescriptionSettings(), "gpu_prompt_or_task_version")` **and**
  `"gpu_prompt_or_task_version" not in DescriptionSettings.model_fields`
  **and** `"gpu_prompt_or_task_version" not in DescriptionSettings().model_dump()`
  plus N3 on adapter construction ([TEST-15]).
- **Lineage-version provenance (mandatory)** — N5 + N2 + N6 over
  `caption_system.py` / production path ([TEST-15]). Not a constant-key
  AST walk (that class is closed by N2's effect proof).
- **Free-string constructor rejection (mandatory)** — `TypeError` match
  unexpected-keyword on full construction with `prompt_or_task_version=`;
  positive control; N7 formals; N8/N6 stamp ([TEST-15]).
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
plan owns the one-line drop of that argument so production wiring matches,
and owns deletion of the now-unread settings field. Shipping production v2
text is a later follow-up (N9), not this seam.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| new shared-prompt module | `apps/prototype-description-service/scene/prompts/caption_system.py` (new; package `__init__.py` only if the package does not already exist) | Own markers, production v1 system body, selected `ProductionPrompt` (body + `lineage_version`), accessors `production_prompt()` / `production_system_prompt()` / `production_prompt_or_task_version()`; **not** `PromptVariant`, v2/v3 bodies, or full `PROMPT_VARIANTS` |
| production adapter | `…/scene/infrastructure/vlm/gpu_remote_adapter.py` | Delete local `_SYSTEM_PROMPT`; **delete** the `ACX_GPU_PROMPT_VERSION` bump instruction at lines **23-24** and replace the "Keep in lockstep…" comment with a pointer to the shared module + parity/inventory tests; import `production_prompt` + markers; **remove free-string `prompt_or_task_version` constructor kwarg** (today `:133`/`:143`); snapshot `self._production_prompt = production_prompt()` once at `__init__`; bind stamp from `self._production_prompt.lineage_version` and post `self._production_prompt.body` at the payload site; keep describe behaviour identical otherwise |
| harness | `…/scripts/eval_harness/bakeoff.py` | Delete local `_PROMPT_V1_SYSTEM` only; import shared v1 body + markers via accessors; **keep local `PromptVariant`** and `_PROMPT_V2_SYSTEM`; introduce **`build_prompt_variants() -> dict[str, PromptVariant]`** and set module-level `PROMPT_VARIANTS = build_prompt_variants()` (**v1 `system=` resolved through `production_system_prompt()` / `production_prompt().body` inside the helper when it runs** — construction site today `bakeoff.py:138-141`; consumer read at `:595`); keep `DEFAULT_PROMPT_VARIANT = "v1"` defined here; re-export names tests already import **plus `build_prompt_variants`**; leave pass-1 / weave / compress / face-gate logic in place. **Parity temporal scope:** same-construction-epoch only (option (a)); already-built `PROMPT_VARIANTS` does not track a later rebind; rebind proof must call `build_prompt_variants()` after rebind |
| settings | `…/scene/config/settings.py` | **Delete** `gpu_prompt_or_task_version` field entirely (today `settings.py:40`) — zero production readers after `deps.py:98` drop; drop free-string `ACX_GPU_PROMPT_VERSION` with it |
| deps (one-line) | `…/scene/interface_adapters/http/deps.py:98` | Drop `prompt_or_task_version=settings.gpu_prompt_or_task_version` once the adapter no longer accepts that kwarg; no other deps edits |
| tests (new) | `…/scene/tests/test_prompt_lineage_seam.py` (new) | Parity + rebind-before-construction (`build_prompt_variants()` after rebind) + foldable-constant inventory + atomic/temporal/resolver (DI leg + N3/N4/N6) + free-string rejection (N7/N8/N6) + lineage provenance (N5/N2/N6) + registry-provenance AST over `PROMPT_VARIANTS` + settings-field-deleted schema triple + N4 source guard; red-first in docstrings |
| tests (correct) | `…/scene/tests/test_description_profiles.py:214`/`:263`, `test_settings.py`; **rewrite** `test_gpu_remote_adapter.py:51-65` (N1); **add** free-string rejection (N7) + settings deletion + N3 | Honest `"1"` stamp; free-string override gone (N1) |

## Related Files

| File | Note |
| --- | --- |
| `scene/application/hashing.py` | Cache-key composition — read for hazard; **do not edit** |
| `scene/interface_adapters/http/deps.py` | Today passes `settings.gpu_prompt_or_task_version` at `:98`; **owned one-line drop** of that kwarg when free-string constructor is removed |
| `scene/interface_adapters/http/schemas/responses.py` | **Unowned in this wave** (DEPICT-1 Constraints and Related Files explicitly disclaim it; field already present; **do not edit**) |
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
**mandatory** single-source inventory test (keyed on **foldable-constant
definition sites at any scope**, not a source-text substring grep and not a
runtime import-and-compare) fails when a second foldable full-body definition
of the v1 text appears under the scanned roots — including a split-literal
assembly and a function-local constant that would evade weaker inventories.

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
    `ProductionPrompt` **in Slice 1** (N10 — full atomic config required now;
    staged "body first, bind in Slice 2" is not permitted).
  - Accessors: primary `production_prompt() -> ProductionPrompt`, plus
    `production_system_prompt() -> production_prompt().body` and
    `production_prompt_or_task_version() -> production_prompt().lineage_version`.
  - **Do not** move `PromptVariant` here — it stays in `bakeoff.py:124-135`
    (harness-only fields `system_long` / `three_surface`; production unused).
  - **Do not** move v2/v3 bodies or the full `PROMPT_VARIANTS` registry here
    ([REF-10]; harness-only text stays in `bakeoff.py`; v2 body lives only at
    `bakeoff.py:104-121`).
  - **Do not** define `DEFAULT_PROMPT_VARIANT` here — that harness default
    remains in `bakeoff.py` (see rewire below).
- Rewire `gpu_remote_adapter.py`:
  - Import `production_prompt` and markers (accessor functions only — not
    `from … import PRODUCTION_PROMPT`).
  - In `__init__`, snapshot once:
    `self._production_prompt = production_prompt()` then
    `self.prompt_or_task_version = self._production_prompt.lineage_version`
    (free-string kwarg removal may complete in Slice 2 — N1; body is already
    on `ProductionPrompt` per N10).
  - Post `self._production_prompt.body` in the chat payload system message at
    the same site as today's `_SYSTEM_PROMPT` (`gpu_remote_adapter.py:182`
    `messages[0]["content"]`) — not a describe-time re-call of
    `production_system_prompt()`, and not a direct module-global
    `PRODUCTION_PROMPT.body` read.
  - Delete the local duplicated v1 body.
  - **Delete the stale operator guidance at lines 23-24** (exact current
    text spanning those lines: "Keep in lockstep with
    scripts/eval_harness/bakeoff.py (VLMRP-HARM-01). Bump
    ACX_GPU_PROMPT_VERSION / default prompt_or_task_version when this
    contract changes."). Replace with a short pointer to
    `scene/prompts/caption_system.py` and the parity / foldable-constant
    inventory tests. Do **not** leave any instruction to bump
    `ACX_GPU_PROMPT_VERSION` or a free-string constructor default.
- Rewire `bakeoff.py`:
  - Import shared v1 body via accessor functions only
    (`production_system_prompt()` or `production_prompt().body` — no
    `from … import PRODUCTION_PROMPT`, no dedicated body export) and markers.
  - **Keep local `PromptVariant` dataclass** (do not import it from
    `caption_system`).
  - Delete local `_PROMPT_V1_SYSTEM` only. Keep local `_PROMPT_V2_SYSTEM`.
  - **Introduce `build_prompt_variants() -> dict[str, PromptVariant]`** and
    set module-level `PROMPT_VARIANTS = build_prompt_variants()`. The helper
    is the **sole** registry construction site (today's inline dict at
    `bakeoff.py:138-141` moves into the helper body). **v1 entry resolves
    the body through `production_system_prompt()` (or
    `production_prompt().body`) when the helper runs** — the argument is the
    accessor result, not a local full-body literal and **not** a module-level
    `_FROZEN_V1 = production_system_prompt()` import-time bind. Apply the
    same long-band replace
    `"2-4 plain sentences" → "4-8 plain sentences"` on that resolved body for
    `system_long`. v2/v3 entries keep today's local text and long-band
    replace unchanged. (Inventory: the v1 `system=` argument is a `Call` /
    `Name` / attribute load of the imported body — a **permitted
    non-definition hit**, not a second foldable full-body literal; see
    inventory permitted-hit list.) Consumer read at `bakeoff.py:595`
    (`variant = PROMPT_VARIANTS[self.prompt_variant]`) stays on the
    module-level dict; the rebind proof calls the helper directly after a
    rebind so it exercises the real construction path, not a hand-built
    `PromptVariant`.
  - Keep `DEFAULT_PROMPT_VARIANT = "v1"` **defined and exported in bakeoff.py**
    (today at `bakeoff.py:154`; still imported by
    `test_eval_harness_pipeline.py:22`). Do **not** import it from the shared
    module (it is not defined there).
  - Re-export `PROMPT_VARIANTS`, `DEFAULT_PROMPT_VARIANT`, `PromptVariant`
    (local class), and **`build_prompt_variants`** so
    `from scripts.eval_harness.bakeoff import PROMPT_VARIANTS` keeps working
    and the rebind proof can import the real helper.
  - Leave `_PASS1_SYSTEM_PROMPT`, `_WEAVE_INSTRUCTIONS`,
    `_V3_THREE_SURFACE_INSTRUCTIONS`, `_COMPRESS_SYSTEM_PROMPT` in bakeoff
    ([REF-10]: different pipeline-stage knowledge).
  - **Parity temporal scope (committed option (a)):** bakeoff holds the
    resolved v1 string on the frozen `PromptVariant` from construction time
    (today consumed at `bakeoff.py:595` via stored
    `PROMPT_VARIANTS[self.prompt_variant]`). A rebind of `PRODUCTION_PROMPT`
    **after** that construction does not update the stored string; parity
    with a fresh adapter is only guaranteed when both were constructed under
    the same selected-config state (fresh adapter + fresh
    `build_prompt_variants()` call).
- Add `scene/tests/test_prompt_lineage_seam.py` with the parity test and the
  **mandatory** single-source inventory test below.

Proof:

```bash
cd apps/prototype-description-service
uv run --extra dev pytest scene/tests/test_prompt_lineage_seam.py scene/tests/test_gpu_remote_adapter.py scene/tests/test_eval_harness_pipeline.py -q
```

#### [TEST-15] red-first proof — parity test

**Test names (proposed):**
`test_production_system_prompt_matches_harness_v1`
`test_bakeoff_v1_body_reflects_rebind_before_variant_construction`

**Parity temporal scope (committed option (a) — state in both test
docstrings):** production ↔ harness-v1 parity holds for a given
selected-config state when **both** consumers are constructed **after** that
state is set. A live `PRODUCTION_PROMPT` rebind updates freshly constructed
adapters (init snapshot) but does **not** rewrite an already-built
`PROMPT_VARIANTS["v1"].system` string (verify today: `bakeoff.py:138-141`
constructs once at import; `:595` reads
`PROMPT_VARIANTS[self.prompt_variant]`). After rewire the construction site
is `build_prompt_variants()` and module-level is
`PROMPT_VARIANTS = build_prompt_variants()`; the rebind proof re-calls that
helper rather than mutating the import-time dict. Nobody may read the
default-path parity assertion as a live post-rebind guarantee for a
pre-built harness registry.

**What default-path parity asserts (mandatory non-vacuous binding sites):**

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

**What the rebind-before-construction proof asserts (mandatory — temporal
scope of option (a)):**

1. Rebind `caption_system.PRODUCTION_PROMPT` to a synthetic
   `ProductionPrompt(body="SYNTHETIC_V2_SYSTEM_PROMPT_FOR_LINEAGE_TEST.",
   lineage_version="2")` **before** constructing any harness v1 registry
   under test.
2. Call the **production registry helper**
   `scripts.eval_harness.bakeoff.build_prompt_variants()` **after** the
   rebind — the same function that builds the module-level
   `PROMPT_VARIANTS` registry (`PROMPT_VARIANTS = build_prompt_variants()`
   at import; consumer read at `bakeoff.py:595`). Read the returned
   dict's `"v1"` entry. **Do not** hand-build a
   `PromptVariant(system=production_system_prompt(), …)` inside the test:
   that constructs a private variant the real harness never uses and lets
   an import-time `_FROZEN_V1` freeze of the real registry pass silently.
3. Construct a **fresh** `GpuRemoteDescriptionAdapter` after the same rebind
   (transport-stubbed) and assert whitespace-normalised equality of
   `registry["v1"].system` against the adapter's posted
   `messages[0]["content"]` **and** against `synthetic.body` /
   `production_system_prompt()`. That is the same-construction-epoch
   parity the contract actually promises. Do **not** claim that a
   pre-rebind module-level `PROMPT_VARIANTS` dict tracks the rebind.
4. A leftover local full-body literal inside `build_prompt_variants`, an
   import-time `from … import PRODUCTION_PROMPT` freeze, a dedicated body
   export that ignores the pre-construction rebind, **or** a module-level
   `_FROZEN_V1 = production_system_prompt()` import-time bind that the
   helper (or module-level registry) reads instead of calling the
   accessor at helper-run time, makes this assertion fail.

**(a) Exact edit that makes default-path parity go red**

- Change **only** the string inserted into the describe payload's
  `messages[0]["content"]` in `gpu_remote_adapter.py` so it differs by any
  non-whitespace character from the shared/harness v1 body (e.g. append
  `" RED."` at the payload site, or re-bind the payload to a local divergent
  literal). Do **not** redefine a module attribute that the test never reads.
  Under that edit the transport-captured equality assertion **must fail**.
- Symmetric red: in `bakeoff.py`, re-bind
  `PROMPT_VARIANTS["v1"]` to a `PromptVariant` whose `system` differs from the
  string the adapter POSTs → parity test **must fail**.

**(a′) Exact edit that makes the rebind-before-construction proof go red**

- **Named RED (mandatory — kills the hand-built-`PromptVariant` cheat):**
  keep a module-level
  `_FROZEN_V1 = production_system_prompt()` import-time bind and read it
  **inside `build_prompt_variants()`**. After rebind-then-
  `build_prompt_variants()`, `registry["v1"].system` stays on the old body
  while a freshly constructed adapter posts the synthetic body →
  assertion (3) fails. **Keeping that in-helper `_FROZEN_V1` read must turn
  this proof RED.**
- **Siting matters — this proof does not cover the module-level site.** If
  `_FROZEN_V1` is read at the `PROMPT_VARIANTS = …` site while
  `build_prompt_variants()` itself correctly calls the accessor, this proof
  calls the correct helper, sees the synthetic body, and stays **green** — it
  never reads module-level `PROMPT_VARIANTS`. Do **not** document that edit as
  a red for this test: a mutation named as red that comes out green is not a
  discrimination guard, it is an unrun mutation ([TEST-15] — "would this exact
  assertion turn red; have I seen it?"). That siting is covered by the
  **registry-provenance** assertion, and its named RED lives there.
- Equivalent reds: rewire bakeoff v1 to freeze the body via
  `from scene.prompts.caption_system import PRODUCTION_PROMPT` then
  `system=PRODUCTION_PROMPT.body` at a site that does not re-read after a
  pre-construction rebind, **or** leave a local full-body
  `_PROMPT_V1_SYSTEM` literal in the v1 `PromptVariant` argument inside
  `build_prompt_variants` → after rebind-then-call-helper,
  `registry["v1"].system` stays on the old body while
  `production_system_prompt()` returns the synthetic body → assertion (3)
  fails.

**(b) Discrimination case (proves the check is not vacuous)**

- **Trivial cheating implementations default-path parity must kill:**
  1. Attribute-only: `assert production_system_prompt() == production_system_prompt()`
     (or two imports of the same shared symbol). Stays green when the adapter
     payload is re-wired to a divergent local literal.
  2. Always-constant / no-op: `assert True`, or assert two hard-coded identical
     string literals inside the test body. Stays green under red edit (a).
  3. Substring-only (today's adapter test pattern): `"Never name or guess" in
     posted_system` — stays green when the posted body is otherwise divergent
     from harness v1.
- The shipped default-path test kills all three because it reads the
  **transport-captured posted** system string and the harness registry entry
  and requires full whitespace-normalised equality.
- **Cheating shapes the rebind-before-construction proof kills:**
  1. **Import-time freeze inside the helper (the DPR10-H-01 cheat):**
     `_FROZEN_V1 = production_system_prompt()` (or
     `from … import PRODUCTION_PROMPT`) at module import, read by
     `build_prompt_variants()` itself. Default-path parity and AST inventory
     stay green at import-time state. A hand-built
     `PromptVariant(system=production_system_prompt())` inside the test
     would still see the rebind and pass while the real harness at
     `bakeoff.py:595` stays frozen forever — that is why the proof **must**
     call `build_prompt_variants()` and compare its `"v1"` entry against a
     freshly constructed adapter, not construct its own variant.
     **Scope limit (DPR12-H-01):** calling the helper closes this cheat only
     when the freeze is *in* the helper. A correct helper plus a separately
     hand-built module-level `PROMPT_VARIANTS` is invisible to this proof
     (never read), to the AST inventory (`Call` node, not a foldable
     constant — see the permitted-non-definition-hit list), and to
     default-path parity (in the import epoch both hold the same string). The
     **registry-provenance** assertion is what closes it; the two proofs are
     not redundant and neither substitutes for the other.
  2. Leftover local full-body literal / copy-paste "share" inside the
     helper while adapters correctly call `production_prompt()`.
  Without calling the real helper after rebind, those cheats ship.
- Permanent discrimination guard (recommended on default path): also assert
  that under the default selected config,
  `production_prompt_or_task_version() == "1"` and the posted system string
  equals `production_system_prompt()` — so a future promotion that rebinds
  `PRODUCTION_PROMPT` without updating the default-path parity expectation is
  a deliberate, visible edit.

#### [TEST-15] red-first proof — single-source body inventory (MANDATORY)

**Test name (proposed):**
`test_production_v1_body_has_exactly_one_definition`

**Why mandatory (not optional / not stretch):** consumer-parity alone is
vacuous against a third unused full v1 body. A dead second assignment
anywhere under the package roots still lets both consumers import the shared
body, so every required pytest command and both consumer-equality assertions
stay green. The inventory test is what enforces the plan's central guarantee
of **exactly one foldable-constant definition** of the production v1 body.

**Why foldable-constant definition sites, not runtime import-and-compare and
not source-text marker grep:**

- A raw source inventory keyed on the substring `"2-4 plain sentences"` is
  evadeable by a split literal (`"2-" + "4 plain sentences"`). Aggravating
  evidence: today's v1 body at `gpu_remote_adapter.py:28-37` (and
  `bakeoff.py:89-98`) is **already** an implicit multi-line adjacent-string
  concatenation with an f-string on `gpu_remote_adapter.py:32` /
  `bakeoff.py:93` — so the evasion is nearly accidental, not only
  adversarial.
- A runtime **import-and-compare** of module-level `str` attributes /
  dataclass field values is **not** an acceptable inventory mechanism for
  this plan. After the mandated rewire, `PROMPT_VARIANTS["v1"].system`
  (verify: `bakeoff.py:124-141` today; post-rewire the v1 entry holds the
  canonical body **by reference** from `production_system_prompt()` / the
  selected config) would count as a second full-body hit under that approach
  while a correct single-source implementation is in place — the guard's
  verdict would be implementer coin-flip. The inventory unit is therefore
  **source-level definition sites**, not live object identity.

**What it asserts (foldable-constant definition count AND location):**

1. **Canonical assembled body.** Import the shared module and take
   `canonical = re.sub(r"\s+", " ", production_system_prompt().strip())`
   (via the accessor — not a direct `PRODUCTION_PROMPT.body` import in the
   production code under test). This is the only authority for "what the
   production v1 body is."
2. **Inventory helper (named, implementable — DPR15-M-18).** Ship exactly
   this symbol (path:symbol):
   `scene/tests/test_prompt_lineage_seam.py:count_foldable_v1_body_definitions`
   (a module-private helper in the new test module is fine; do not leave
   the name free). Signature:
   ```text
   def count_foldable_v1_body_definitions(
       roots: Sequence[Path],
       *,
       canonical: str,
   ) -> list[tuple[Path, int, str]]:
       """Return one hit per foldable full-body definition site.

       Each hit is (file_path, lineno, kind) where kind is one of
       "assign" | "call_arg" | "default" | "kw_default".
       """
   ```
   A thin wrapper `def count(...) -> int: return len(count_foldable_…(...))`
   is permitted for the `== 1` assertion; the hit-list form is the one the
   discrimination fixtures inspect.

   **Folding surface — accepted node types (exhaustive for this helper):**

   | AST node | When it folds | Folded value |
   | --- | --- | --- |
   | `ast.Constant` with `value: str` | always | `value` |
   | `ast.JoinedStr` (f-string) | every `ast.FormattedValue` interpolates a `Name` bound in the same module to a foldable string constant (including the shared marker constants this plan owns), and every plain `Constant` str part is included | concatenation of folded parts |
   | `ast.BinOp` with `op = ast.Add` | both `left` and `right` fold to `str` | `left + right` |
   | Nested `BinOp(Add, …)` chains | recursive fold of both sides | full concatenation |
   | Implicit adjacent-string constants | CPython already collapses `"a" "b"` into one `Constant("ab")` in the AST — no extra case | as `Constant` |

   **Not folded (out of surface — do not claim to detect):**
   `"".join(...)`, `%` formatting, `str.format`, `str` calls, reads from
   disk, `Name` / `Attribute` / `Call` that merely *reference* an already-
   defined body, `Subscript`, non-string constants. Guarantee wording below
   matches this surface.

   **Walk targets (every scope: module, class, function/method, nested):**
   - `Assign` / `AnnAssign` / `AugAssign` **value** nodes that fold to
     whitespace-normalised `canonical` → kind `"assign"`;
   - call / construct **argument** nodes (positional `Call.args` and
     keyword `Call.keywords[*].value`) that fold to `canonical` → kind
     `"call_arg"`;
   - `FunctionDef` / `AsyncFunctionDef` **`args.defaults`** → kind
     `"default"` and **`args.kw_defaults`** (skip `None` slots) → kind
     `"kw_default"`.

   A full-body duplicate parked as a default-argument value
   (`def f(body: str = ("…full v1 text…")): …`) **must** count as a
   definition site; walking only assignment and call-argument nodes leaves
   that hole open.

   **Does not** count a `Name` / attribute load / function call that merely
   *references* an already-defined body (e.g. `production_system_prompt()`,
   `PROMPT_VARIANTS["v1"].system` holding the imported body by reference /
   via accessor call at variant-construction time, or
   `ProductionPrompt(body=imported_name, …)` when `imported_name` is
   not itself a foldable full-body literal at that node).

   **Worked example (split-literal fold — junior agent must be able to
   implement from this alone):**
   ```text
   # on-disk fixture written by the test into tmp_path / "dup.py":
   BODY = "2-" + "4 plain sentences"   # plus the rest of the canonical
                                       # body assembled the same way so the
                                       # file has NO contiguous substring
                                       # "2-4 plain sentences"

   # AST value of BODY is BinOp(Add, Constant("2-"), Constant("4 plain…"))
   # fold_string(BinOp):
   #   fold_string(Constant("2-")) -> "2-"
   #   fold_string(Constant("4 plain sentences")) -> "4 plain sentences"
   #   return "2-" + "4 plain sentences"
   # whitespace-normalise; if equal to canonical -> one hit
   #   (Path("…/dup.py"), <lineno of Assign>, "assign")
   ```
   The inventory over `roots=(caption_system_root, tmp_path)` therefore
   returns count 2 under this injection while
   `"2-4 plain sentences" not in (tmp_path / "dup.py").read_text()` stays
   true — proving a substring grep would stay green.
3. **Sole permitted inventory mechanism.** The shipped inventory is this
   AST foldable-constant walk via
   `count_foldable_v1_body_definitions`. Do **not** ship a second
   alternative that import-and-compares live module attributes / dataclass
   fields (that alternative disagrees with the AST walk on
   `PROMPT_VARIANTS["v1"].system` after rewire — see above). **Forbidden
   as the sole check:** `source_text.count("2-4 plain sentences")` /
   grepping the raw file for that substring alone.
4. Assert **exactly one** foldable-constant full-body definition site under
   the real package roots
   (`scene/` and `scripts/eval_harness/` under
   `apps/prototype-description-service/`), at exactly this location: the
   production v1 body bound into `ProductionPrompt` in
   `scene/prompts/caption_system.py` (the selected config's body field
   literal / assignment). **Required at Slice 1 exit** (N10) — not deferred.
5. **Permitted non-definition hits** (must not count as foldable full-body
   definition sites):
   - bakeoff's long-band
     `.replace("2-4 plain sentences", "4-8 plain sentences")` on the imported
     v1 body (token as replace *argument* / derived string, not a second
     independent full-body foldable literal);
   - `PROMPT_VARIANTS["v1"].system` (and any dataclass field) holding the
     imported body **by reference** / via `production_system_prompt()` /
     `production_prompt().body` call at variant-construction time
     — a `Name` / `Call` / attribute-load node, not a foldable full-body
     literal at that site (verify post-rewire shape against
     `bakeoff.py:138-141` today; this exemption is the DPR6-H-02 /
     option-(a) rebind-before-construction path — re-verified);
   - tests that quote fragments of the body;
   - the accessors `production_prompt()` / `production_system_prompt()` /
     `production_prompt_or_task_version()` themselves (they *read* the one
     definition).
6. **Forbidden:** a second foldable-constant full-body definition of the
   canonical value anywhere under the scanned roots — including
   module-level, class-body, **or function/method-local** assignments;
   including **default-argument** / **kw-default** values on
   `FunctionDef` / `AsyncFunctionDef`; including split-literal assemblies
   (`"2-" + "4 plain sentences"` style); including a full v1 body still
   defined in `gpu_remote_adapter.py` or a second `_PROMPT_V1_SYSTEM`-style
   body assignment in `bakeoff.py`.
7. **Guarantee wording (scope of the mechanism):** the inventory guarantees
   **exactly one foldable-constant definition** of the canonical body under
   the scanned roots. It does **not** claim to detect every possible runtime
   assembly of the same text via non-foldable means (`"".join(...)`, `%`
   formatting, `str.format`, reading from disk, etc.). Those shapes are out
   of the folding surface; do not write a broader guarantee the mechanism
   cannot enforce.
8. **Do not use as the sole inventory key:** the weave clause
   `"Weave the people's names and factual details it supplies"` (also in
   harness v2 at `bakeoff.py:116-118`), the shared opener
   `"You write alt text for images on a personal website"` (also in v2), or
   a raw substring grep for `"2-4 plain sentences"` alone (v1-unique today
   at `gpu_remote_adapter.py:30` / `bakeoff.py:91` vs v2's
   `"Write 2-4 sentences."` at `bakeoff.py:113`, but still split-evadeable).

**(a) Exact edit that makes it go red**

- Inject a **second foldable-constant full-body definition** whose folded
  value equals the canonical production body, anywhere outside the permitted
  definition site — e.g. re-add `_SYSTEM_PROMPT = ("…full v1 text…")` in
  `gpu_remote_adapter.py`, re-add `_PROMPT_V1_SYSTEM = ("…full v1 text…")` in
  `bakeoff.py`, or add a dummy module-level string assignment under `scene/`
  that assembles to the same body. Under that mutation the inventory test
  **must fail** (definition count ≠ 1, and/or location not exclusively
  `caption_system.py`).

**(a′) Permanent split-literal discrimination guard (must ship in the test —
no comment-only escape)**

- The inventory function **must** take `roots: Sequence[Path]`. The test
  **must** write a real split-literal module into `tmp_path` (a `.py` file
  whose source builds the canonical body via `"2-" + "4 plain sentences"`
  or equivalent adjacent-literal / explicit-concat split of any unique
  span, so the file does **not** contain the contiguous substring
  `"2-4 plain sentences"`), then call the inventory over
  `roots=(real_package_root_or_caption_system_only, tmp_path)` (or
  `roots=(tmp_path,)` plus a separate assertion that the real roots still
  count exactly 1 — either arrangement is fine so long as the injected
  module is actually scanned).
- Assert the inventory **count goes to 2** (or real_count + 1) under that
  injection.
- Assert a **substring scan of that same injected file** finds nothing
  matching the contiguous marker `"2-4 plain sentences"` — so a
  substring-grep inventory would stay green while the foldable-constant
  inventory goes red.
- **Delete any "documented second red path" / comment-only escape.** A
  documented red path is a comment; it cannot fail a suite. The split-
  literal module must be a real on-disk file the test writes and the
  inventory function must accept `roots` so the scan can see it.

**(a″) Permanent function-local discrimination guard (must ship in the test)**

- Also write (into `tmp_path`, same `roots=` injection seam) a module whose
  **function-local** (or method-local) assignment is a foldable-constant
  full-body duplicate of `canonical` — e.g.
  `def _hidden():\n    body = ("…full v1 text…")\n    return body`.
- Assert the inventory count goes to 2 (or real_count + 1). A
  module-level-only inventory stays green under this shape; the any-scope
  walk **must go red**.

**(a‴) Permanent default-argument discrimination guard (must ship in the
test — second permanent red path alongside (a″))**

- Also write (into `tmp_path`, same `roots=` injection seam) a real on-disk
  module whose source parks a foldable-constant full-body duplicate of
  `canonical` as a **default argument value** — e.g.
  `def _hidden(body: str = ("…full v1 text…")):\n    return body`
  (and/or a keyword-only default via `args.kw_defaults`, e.g.
  `def _hidden(*, body: str = ("…full v1 text…")):\n    return body`).
  This is an **actual fixture the test writes**, not a documented path.
- Assert the inventory count goes to 2 (or real_count + 1) when that module
  is scanned. An inventory that walks assignment and call-argument nodes
  but never `FunctionDef.args.defaults` / `args.kw_defaults` stays green
  under this shape; the defaults walk **must go red**.

**(b) Discrimination case (proves the check is not vacuous)**

- **Cheating shapes this test kills:**
  1. Leave both consumers on the shared accessor (parity stays green) while
     a third unused foldable full v1 body sits elsewhere in the tree.
     Consumer-equality and transport-parity alone pass; only the inventory
     count/location assertion goes red under (a).
  2. Split-literal third body (`"2-" + "4 plain sentences"` style) that
     evades a source-text marker grep. Only the foldable-constant inventory
     goes red under (a′); the substring-scan control on the injected file
     stays empty.
  3. Function-local / method-local full-body constant that a module-level-
     only inventory misses. Only the any-scope walk goes red under (a″).
  4. Default-argument / kw-default full-body constant that an
     assignment-and-call-argument-only inventory misses. Only the
     `args.defaults` / `args.kw_defaults` walk goes red under (a‴).
  5. Runtime import-and-compare that would RED a correct rewire because
     `PROMPT_VARIANTS["v1"].system` holds the body by reference / via
     accessor call at variant-construction time — **not** an acceptable
     implementation; the AST definition-site unit stays GREEN under the
     correct rewire.
- Attribute-only / always-constant cheats are already killed by the parity
  test; this test's load-bearing jobs are the unused-third-body hole, the
  split-literal evasion hole, the function-local hole, the default-argument
  hole, and the import-and-compare false-positive hole.

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

  def production_prompt() -> ProductionPrompt:
      return PRODUCTION_PROMPT

  def production_system_prompt() -> str:
      return production_prompt().body

  def production_prompt_or_task_version() -> str:
      return production_prompt().lineage_version
  ```
  **Lineage honesty:** N5 (Constant `"1"` at construction site) + N2
  (import-time env silence EFFECT) + N6 (wire E2E). Runtime-only
  `production_prompt_or_task_version() == "1"` is not a substitute for N2.
  **Forbidden shapes (these re-introduce the lineage lie):**
  - Independent `PRODUCTION_SYSTEM_PROMPT = "…v1…"` plus a separate
    `production_prompt_or_task_version()` that subscripts
    `_VARIANT_TO_TASK_VERSION[PRODUCTION_PROMPT_VARIANT]` — monkeypatching the
    variant key to `"v2"` stamps `"2"` while a fresh adapter may still post
    the v1 body (production has one prompt binding at
    `gpu_remote_adapter.py:182`; the v2 body exists only in
    `bakeoff.py:104-121`).
  - Free-floating `PRODUCTION_PROMPT_OR_TASK_VERSION = "1"` beside a body
    global that can change independently.
  - Import-time-frozen default-arg of a version string that ignores a later
    rebind of `PRODUCTION_PROMPT`.
  - **Import-time env-backed lineage anywhere in `caption_system.py`**
    (keyword env read, module-top capture, or split-key
    `os.environ["ACX_GPU_" + "PROMPT_VERSION"]`) — closed by **N2** (and
    N5 when the keyword is non-Constant). Runtime residual probes cannot
    see import-time reads under pytest.
  - Consumer binding via `from … import PRODUCTION_PROMPT` then
    `.body` / `.lineage_version`, or a dedicated import-time
    `DEDICATED = PRODUCTION_PROMPT.body` export — both miss the Slice-2
    module-attribute monkeypatch on **fresh** `production_prompt()` calls
    (see Consumers above).
  - **Describe-time re-read of the body separate from the init-time stamp
    snapshot** — e.g. freeze
    `self.prompt_or_task_version = production_prompt_or_task_version()` at
    `__init__` while posting `production_system_prompt()` (live) at
    `describe()` time. Construct under v1, rebind `PRODUCTION_PROMPT` to v2,
    call `describe()` on the existing adapter → posts v2 body under frozen
    v1 stamp. That is the body/stamp divergence this plan exists to make
    impossible. **Fix:** snapshot `production_prompt()` once; derive both
    body and stamp from the snapshot.
  - Free-string env stamp override via a retained
    `DescriptionSettings.gpu_prompt_or_task_version` field (or
    `os.environ.get("ACX_GPU_PROMPT_VERSION", …)`) with no production reader
    after `deps.py:98` drop — a field that only asserts the accessor against
    itself cannot discriminate a production lineage lie; delete it.
  - Free-string constructor override
    (`prompt_or_task_version: str = "3"` assigned to
    `self.prompt_or_task_version` at `gpu_remote_adapter.py:133`/`:143`)
    that lets `GpuRemoteDescriptionAdapter(prompt_or_task_version="9")`
    stamp `"9"` over the v1 body posted at `:182`.
  - **Differently-named free-string stamp parameter** (e.g.
    `stamp_version`) after the old name is removed — closed by **N7**.
  - **Post-init env stamp inside `deps.get_gpu_description_adapter`** —
    closed by DI-resolver leg (N3 + N6 on `get_gpu_description_adapter`).
  - **DI factory body rewrite with honest stamp** — e.g. after
    constructing the adapter, replace
    `adapter._production_prompt` with a `ProductionPrompt` whose
    `lineage_version` is still `"1"` but whose `body` is not the selected
    config. Stamp-only DI assertions stay green; mandatory posted-body
    equality on the DI leg goes red (DPR15-H-02).
- `settings.py` — **delete**
  `DescriptionSettings.gpu_prompt_or_task_version` entirely (today
  `settings.py:40` including
  `os.environ.get("ACX_GPU_PROMPT_VERSION", "3")`). After constructor
  removal + `deps.py:98` drop the field has zero production readers
  (greenfield delete-over-flag). Do **not** repoint it at
  `production_prompt_or_task_version()` as a dead mirror, and do **not**
  assert it as a discrimination surface.
- `gpu_remote_adapter.py` constructor — **remove free-string override
  entirely (preferred; closed lineage enum is the only alternative, and
  this plan chooses removal):**
  - **Delete** the `prompt_or_task_version` parameter from
    `GpuRemoteDescriptionAdapter.__init__` (today
    `prompt_or_task_version: str = "3"` at `gpu_remote_adapter.py:133` and
    `self.prompt_or_task_version = prompt_or_task_version` at `:143`).
  - **Snapshot once** inside `__init__`:
    `self._production_prompt = production_prompt()` then
    `self.prompt_or_task_version = self._production_prompt.lineage_version`
    (not a separate free-string, not an import-time frozen `"1"`
    default-arg, and not a stamp-only call to
    `production_prompt_or_task_version()` decoupled from the body source).
    A monkeypatched `PRODUCTION_PROMPT` must be visible on **new** instances
    that call `production_prompt()` after the rebind.
  - **Do not** keep `prompt_or_task_version: str | None = None` as a
    caller-supplied free string that is honored when not None — that is
    still the free-string override hole (DPR4-H-01). DPR3-M-02's
    preserve-the-override requirement is **wontfix / superseded**; do not
    reinstate it.
  - Payload system message must post **`self._production_prompt.body`** at
    the site of today's `_SYSTEM_PROMPT` (`gpu_remote_adapter.py:182`) —
    the same snapshot object that supplied the stamp. **Do not** call
    `production_system_prompt()` (or re-call `production_prompt()`) at
    describe time for the posted body: that re-opens the time-axis split
    (stamp frozen at init, body live at describe). **Do not**
    `from … import PRODUCTION_PROMPT` then post `.body` (misses fresh
    snapshot after rebind on new adapters).
  - **Delete** the stale `ACX_GPU_PROMPT_VERSION` bump instruction at
    `gpu_remote_adapter.py:23-24` (see Slice 1 rewire / DPR4-L-13).
- `deps.py:98` — **drop**
  `prompt_or_task_version=settings.gpu_prompt_or_task_version` (owned
  one-line edit). After the free-string constructor kwarg is removed,
  passing it is a TypeError; production wiring must construct the adapter
  without a stamp argument. The settings field is deleted in the same slice
  (see above) — do not keep a no-reader settings surface for discrimination.
- Correct tests that encoded the **resolved-default** lie and the
  free-string constructor override:
  - `test_description_profiles.py:214` and `:263` — resolved GPU adapters
    (deps path) assert `prompt_or_task_version == "3"` today; change both
    to expect `"1"` / `production_prompt_or_task_version()` under default
    construction.
  - `test_settings.py` — **unconditional deletion proof (mandatory; not
    conditional on a prior mention of the field).** VERIFY today:
    `scene/tests/test_settings.py:8-14` (`test_description_settings_defaults`)
    never mentions `gpu_prompt_or_task_version`, so a "if a settings test
    previously mentioned the GPU stamp field…" branch never fires. Ship an
    **unconditional** proof (new test or extended defaults test) that always
    runs:
    1. Schema-surface deletion (all three mandatory — `hasattr` alone is
       not enough; a Pydantic field can remain in `model_fields` while
       instance attribute access is overridden to raise `AttributeError`):
       - `assert not hasattr(DescriptionSettings(), "gpu_prompt_or_task_version")`
       - `assert "gpu_prompt_or_task_version" not in DescriptionSettings.model_fields`
       - `assert "gpu_prompt_or_task_version" not in DescriptionSettings().model_dump()`
       Each fails while the field is still present at `settings.py:40`.
    2. **Post-import stamp honesty (N3):** with env residual `"3"` and junk
       `"9"`, construct `GpuRemoteDescriptionAdapter` with full required
       kwargs and **no** free-string stamp kwarg; assert stamp ==
       `production_prompt_or_task_version()` / `"1"`. Import-time silence
       is N2 (lineage proof), not re-implemented here as a name-filtered
       spy. Red-first: schema triple (1) fails while field present;
       residual probe fails if stamp becomes `"3"`.
    Non-GPU `prompt_or_task_version == "1"` may remain.
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
  - **Add** free-string constructor rejection proof (below) with **full**
    construction kwargs + positive control.
  - **Add** temporal snapshot proof (below).
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

- `test_gpu_adapter_stamp_matches_production_prompt`
- `test_production_prompt_body_and_lineage_change_together`
- `test_adapter_snapshot_body_and_stamp_are_temporal_pair` (see dedicated
  temporal block below)
- `test_gpu_adapter_rejects_free_string_prompt_version_kwarg` (constructor
  free-string removal — see dedicated block below)

**What they assert (default selection) — four load-bearing surfaces, no
settings field:**

1. `GpuRemoteDescriptionAdapter(...).prompt_or_task_version == "1"`
   (construct **without** a `prompt_or_task_version` kwarg — the parameter
   no longer exists; this is the no-arg stamp path, **not** a preserved
   free-string override at `test_gpu_remote_adapter.py:51-65`). Required
   constructor kwargs remain
   `endpoint_url` / `model_id` / `model_version` (see
   `gpu_remote_adapter.py:127-133`).
2. Under today's selection, `production_prompt_or_task_version() == "1"` and
   `production_system_prompt()` equals the v1 system text, and
   `production_prompt()` is the same object both field accessors read.
   **Do not** assert
   `production_prompt_or_task_version() == PRODUCTION_PROMPT.lineage_version`
   as a standalone check — that equality is tautological because the
   prescribed field-accessor body is
   `return production_prompt().lineage_version` (see shared-module shape
   above). Only the coupled `== "1"` half plus the transport/adapter
   surfaces are load-bearing.
3. **Single-snapshot shape (mandatory — pins object identity, not two
   adjacent accessor calls).** On a freshly constructed default adapter
   (no rebind yet), assert **all** of:
   - `adapter._production_prompt is caption_system.PRODUCTION_PROMPT`
     (identity — the snapshot is the selected instance, not a copy and not
     a re-derived pair of field values from two separate accessor calls),
   - `adapter.prompt_or_task_version == adapter._production_prompt.lineage_version`
     (stamp derived from that same object),
   - transport-stubbed `describe()` posts `messages[0]["content"]` equal
     (whitespace-normalised) to `adapter._production_prompt.body` **and**
     equal to `production_system_prompt()` under default selection.
   Do **not** soften the body assertion with an "or the body that was
   current when `production_prompt()` was snapshotted at init" alternative
   that makes the snapshot attribute unobservable. An `__init__` that calls
   `production_system_prompt()` and `production_prompt_or_task_version()` as
   two adjacent statements (no held `ProductionPrompt` object) fails the
   identity assertion even if stamp and body strings match under default
   selection.
4. Negative honesty check: default stamp is **not** `"3"` while the selected
   body is the v1 text (names the bug class this slice kills — dishonest value
   over v1 text; warrant is [PROV-09]).
5. **Unconditional settings-deletion surface** (see dedicated proof below /
   `test_settings.py` rewrite): `not hasattr(DescriptionSettings(),
   "gpu_prompt_or_task_version")` **and**
   `"gpu_prompt_or_task_version" not in DescriptionSettings.model_fields`
   **and** `"gpu_prompt_or_task_version" not in DescriptionSettings().model_dump()`
   and N3 residual/junk probes keep stamp `"1"`; N4 source guard over the
   four create-or-edit files; N2 covers import-time. **No** positive
   assertion *reading* the deleted field.

**(a) Exact edit that makes it go red**

- Change `PRODUCTION_PROMPT.lineage_version` to `"3"` while leaving
  `body` as the v1 text (e.g. rebind
  `PRODUCTION_PROMPT = ProductionPrompt(body=<same v1>, lineage_version="3")`)
  → default stamp assertions fail on a **fresh** adapter.
- Body/stamp desync red: restore the **forbidden** independent-globals shape
  (body global fixed at v1; version function returns `"2"` under a patched
  variant key) → discrimination case (b) fails on the posted-body assertion
  even if the stamp-only assertions pass.
- Time-axis desync red: freeze stamp at init from
  `production_prompt_or_task_version()` but post body via live
  `production_system_prompt()` at describe time → temporal proof (below)
  fails.
- Free-string constructor red: restore
  `prompt_or_task_version: str = "3"` (or any free string default) assigned
  to `self.prompt_or_task_version` → free-string rejection proof (below)
  fails (`TypeError` with `match="unexpected keyword argument"` expected on
  full construction with `prompt_or_task_version="9"`, or stamp equals `"9"`
  over v1 body). Renaming the free-string formal (e.g. `stamp_version=`)
  instead of restoring the old name → TypeError stays green; N7 **must**
  go red.

**(b) Discrimination case — synthetic v2 config on a FRESH adapter
(kills body/stamp desync)**

Inject one synthetic selected config **before** constructing the adapter under
test, and assert the **four** surfaces move together (accessors + fresh
adapter stamp + posted body):

```text
synthetic = ProductionPrompt(
    body="SYNTHETIC_V2_SYSTEM_PROMPT_FOR_LINEAGE_TEST.",
    lineage_version="2",
)
monkeypatch.setattr(caption_system, "PRODUCTION_PROMPT", synthetic)
```

Then assert **all** of:

1. `production_prompt() is synthetic` (or equals by value) /
   `production_system_prompt() == synthetic.body`
2. `production_prompt_or_task_version() == "2"`
3. **Fresh** `GpuRemoteDescriptionAdapter` (no stamp kwarg — parameter
   removed; full required kwargs present) has
   `.prompt_or_task_version == "2"`
4. Transport-stubbed `describe()` on **that fresh** adapter posts
   `messages[0]["content"]` equal to `synthetic.body` (not the v1 body) —
   requires the adapter to snapshot `production_prompt()` at init and post
   the snapshot's `.body`; an import-time
   `from … import PRODUCTION_PROMPT` / `DEDICATED = PRODUCTION_PROMPT.body`
   binding makes (b).4 go red with no further diagnosis. (An already-
   constructed pre-rebind adapter staying on v1 is correct — see temporal
   proof below; do **not** use a pre-rebind instance for this discrimination.)

**Trivial cheating implementations this discrimination kills:**

| Cheating shape | Why it looked green under weaker tests | How (b) kills it |
| --- | --- | --- |
| Independent globals: `PRODUCTION_SYSTEM_PROMPT` (v1 body) + `production_prompt_or_task_version()` from `_VARIANT_TO_TASK_VERSION[PRODUCTION_PROMPT_VARIANT]` | Monkeypatch variant → `"v2"`; stamp becomes `"2"`; body assertions never read the posted payload | (b).4 fails — posted content still v1 body |
| Stamp function always returns `"1"` | Default adapter assertions stay green | (b).2 / (b).3 fail under synthetic `"2"` |
| Adapter constructor freezes import-time `"1"`; body snapshot is live/other | Stamp stuck at `"1"` while body can change | (b).3 fails (or (b).4 if body is frozen and stamp live) |
| Import-time body bind: `from … import PRODUCTION_PROMPT` then post `.body`, or `DEDICATED = PRODUCTION_PROMPT.body` | Accessor-only unit checks may still pass if they call the functions | (b).4 fails — rebind of module attribute never reaches the frozen import-time name on a fresh adapter |
| Free-string constructor: `GpuRemoteDescriptionAdapter(prompt_or_task_version="9")` while body stays v1 | Posts v1 under stamp `"9"`; no env needed; today's `test_gpu_remote_adapter.py:51-65` shape even certifies the override | Free-string constructor rejection proof fails; plan removes the kwarg (DPR3-M-02 preserve-override **wontfix**) |
| Settings-field "discrimination" of a no-reader field | Asserts accessor against itself after `deps.py:98` drop | Field deleted; unconditional `not hasattr` + `not in model_fields` + absent from `model_dump()` + env-no-effect proof is the surface |
| Two adjacent accessor calls at `__init__` with no held snapshot: `self.prompt_or_task_version = production_prompt_or_task_version()` then later post `production_system_prompt()` / store body string only | Stamp and body strings match under default selection and under synthetic rebind on a **fresh** adapter; temporal/resolver proofs may still pass if both come from the same rebind epoch | Identity assertion `adapter._production_prompt is caption_system.PRODUCTION_PROMPT` fails — single-object shape is unobservable without the held snapshot |

#### [TEST-15] red-first proof — temporal body+stamp snapshot (MANDATORY)

**Test name (proposed):**
`test_adapter_snapshot_body_and_stamp_are_temporal_pair`

**Why mandatory:** Even with atomic `ProductionPrompt` and accessor-only
consumers, freezing the stamp at `__init__` via
`production_prompt_or_task_version()` while reading the body via
`production_system_prompt()` at `describe()` time still permits body/stamp
divergence on the **time** axis. DEPICT-1 explicitly permits REBINDING
module-level `PRODUCTION_PROMPT` as the only mutation path. Sequence:
construct an adapter under v1 → rebind `caption_system.PRODUCTION_PROMPT` to
v2 → call `describe()` on the existing adapter → posts the v2 body under the
frozen v1 stamp. Every synthetic-rebind proof that constructs a **fresh**
adapter after the rebind misses this hole.

**Temporal invariant (state in the test docstring):** body and stamp are
read from the same `ProductionPrompt` object at the same instant
(`production_prompt()` snapshot in `__init__`), so no interleaving —
including a later rebind of the module global — can separate them on an
already-constructed adapter.

**What it asserts:**

```text
# 1. Construct under default (v1) selection — full required kwargs.
old = GpuRemoteDescriptionAdapter(
    endpoint_url="http://gpu.test:8000",
    model_id="test-model",
    model_version="test-version",
    transport=...,  # MockTransport capturing payload
)
assert old.prompt_or_task_version == "1"
# capture old posted body via describe() → must equal v1 / production_system_prompt()
# under default selection at construction time

# 2. THEN rebind module global (DEPICT-1 mutation path).
synthetic = ProductionPrompt(
    body="SYNTHETIC_V2_SYSTEM_PROMPT_FOR_LINEAGE_TEST.",
    lineage_version="2",
)
monkeypatch.setattr(caption_system, "PRODUCTION_PROMPT", synthetic)

# 3. Existing adapter is wholly OLD (body AND stamp).
assert old.prompt_or_task_version == "1"
# describe() on old → messages[0]["content"] still equals the v1 body
# (not synthetic.body)

# 4. Fresh adapter is wholly NEW (body AND stamp).
new = GpuRemoteDescriptionAdapter(
    endpoint_url="http://gpu.test:8000",
    model_id="test-model",
    model_version="test-version",
    transport=...,
)
assert new.prompt_or_task_version == "2"
# describe() on new → messages[0]["content"] equals synthetic.body
```

**(a) Exact edit that makes it go red**

- Implement the forbidden time-axis split: at `__init__` set
  `self.prompt_or_task_version = production_prompt_or_task_version()` but at
  describe/payload time post `production_system_prompt()` (live re-read).
  Under the construct → rebind → describe sequence above, assertion (3)
  fails (old adapter posts synthetic body under stamp `"1"`).

**(b) Discrimination**

- Snapshot both body and stamp from `self._production_prompt` taken once at
  init → (3) and (4) both pass.
- Cheating shape killed: "fresh-adapter-only" synthetic tests that rebind
  first and only then construct (the pattern in atomic discrimination (b)
  above) stay green under the time-axis split; only this construct-then-
  rebind proof goes red.

#### [TEST-15] red-first proof — resolver no stamp/body divergence (MANDATORY)

**Test name (proposed):**
`test_no_configured_path_stamps_lineage_without_matching_body`

**Why:** Production today stamps from settings via `deps.py:98`
(`prompt_or_task_version=settings.gpu_prompt_or_task_version`) while
`gpu_remote_adapter.py:182` posts the system body independently. Any path
that can set the stamp without carrying the body re-introduces the lineage
lie. After this plan, the adapter snapshots `production_prompt()` once at
`__init__` (stamp + body from the same object) and deps no longer passes a
free-string stamp kwarg; the settings field is deleted. Slice-2 atomic
discrimination covers selected-config rebind on a **fresh** adapter; the
temporal proof covers construct-then-rebind; this test covers the
**configured production path** — both the direct constructor shape **and**
the real DI resolver `deps.get_gpu_description_adapter` (verified today at
`deps.py:84-109`; construction site `:94-103`) — plus the absence of
free-string escape hatches. Naming deps in prose while only constructing
the adapter directly leaves a post-init env stamp inside the factory
invisible to every assertion ([TEST-15] unrun mutation).

**What it asserts:**

1. **Direct constructor leg.** Build a GPU adapter with
   `GpuRemoteDescriptionAdapter` **without** a `prompt_or_task_version`
   kwarg (matching post-edit `deps.py`, which no longer passes it) with the
   **full** remaining required kwargs
   (`endpoint_url` / `model_id` / `model_version` — see
   `gpu_remote_adapter.py:127-132`) plus transport-stubbed `describe()`.
2. Assert stamped `adapter.prompt_or_task_version` equals
   `production_prompt_or_task_version()` and the posted
   `messages[0]["content"]` equals the adapter snapshot body /
   `production_system_prompt()` (whitespace-normalised) under the default
   selected config.
3. Rebind `PRODUCTION_PROMPT` to the synthetic v2 config, then construct a
   **fresh** adapter and repeat: stamp and posted body both reflect the
   synthetic values together (same as atomic (b); not a pre-rebind
   instance).
4. **Negative env path — direct constructor (unconditional; always
   fires).** Implements **N2** (import-time effect), **N3** (bounded
   residual/junk probes), and **N4** (AST source guard). These three are
   **not** three copies of one name filter:

   1. **Import-time silence (structural EFFECT — N2; load-bearing).**
      Before any adapter construction that depends on `caption_system`,
      replace `os.environ` with a mapping whose `__getitem__` and `get`
      raise on **any** key; `importlib.reload(scene.prompts.caption_system)`
      must succeed. Computed property: no environment read during module
      import. Closes split-key assembly, join/replace key construction, and
      constant-node AST blind spots in one shot. **Not** a membership test
      against the string `ACX_GPU_PROMPT_VERSION`.

   2. **Residual `"3"` / junk `"9"` value probes (N3; EXIT B — exactly
      these two values).** With the env set to residual `"3"` and
      (separately) junk `"9"`, construct a fresh adapter with full required
      kwargs and **no** free-string stamp kwarg; assert
      `adapter.prompt_or_task_version == production_prompt_or_task_version()`
      / `"1"` and posted body matches selected config body (N6). These
      catch post-import value-filtered honour. A junk-only suite is **not**
      sufficient; N2 alone is **not** sufficient for post-import honour.

   3. **AST source guard (N4; co-equal).** Over the four create-or-edit
      files, `module_string_constants` (docstrings stripped) must not hide
      `ACX_GPU_PROMPT_VERSION`. Comments legal; WHY docstrings legal after
      strip. Anchor paths via `Path(__file__).resolve().parents[1]` (the
      `scene/` package root) so the guard is CWD-independent:
      ```text
      _SCENE = Path(__file__).resolve().parents[1]
      for rel in (
          "config/settings.py",
          "interface_adapters/http/deps.py",
          "infrastructure/vlm/gpu_remote_adapter.py",
          "prompts/caption_system.py",
      ):
          consts = module_string_constants(_SCENE / rel)
          assert not any("acx_gpu_prompt_version" in c for c in consts)
      ```
      Claim scope: those four files only, not repo-wide.

   Implementation: `DescriptionSettings.gpu_prompt_or_task_version` is
   **deleted** (N1) and the adapter stamp binds only from the
   `production_prompt()` snapshot. Pair with the unconditional
   settings-deletion proof (`not hasattr` **and**
   `"gpu_prompt_or_task_version" not in DescriptionSettings.model_fields`
   **and** absent from `DescriptionSettings().model_dump()`).

5. **Negative constructor path:** constructing with
   `prompt_or_task_version="9"` must be impossible / rejected (see free-
   string constructor rejection proof below) — not a supported stamp
   escape hatch.
6. **DI-resolver leg (mandatory — kills post-init-in-deps stamp rewrite
   AND production-path body rewrite; DPR13-H-03 + DPR15-H-02).**
   Construct the adapter **through** production DI only — call
   `deps.get_gpu_description_adapter` (verified today at `deps.py:84-109`;
   construction site `:94-103`). **Do not** substitute a direct
   `GpuRemoteDescriptionAdapter(...)` call for this leg.

   **What is reused from existing tests (and what is not):**
   - From `test_description_profiles.py:173-184` (verified): **only** the
     private-endpoint env fixture that makes the resolver return
     `GpuRemoteDescriptionAdapter` rather than
     `UnavailableDescriptionAdapter` —
     `monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", "http://10.0.1.42:8000")`
     (literal private IP accepted by `_is_private_gpu_endpoint` at
     `deps.py:58-81`). That span calls `get_description_adapter` under
     `ACX_DESCRIPTION_ADAPTER=gpu_qwen30b`; **this leg does not** — it
     calls `get_gpu_description_adapter` directly (no profile-switch env).
   - From `test_description_profiles.py:249-263` (verified): only the fact
     that a deps-resolved GPU adapter exposes `.prompt_or_task_version`
     (today dishonest `"3"`; this plan corrects those sites to `"1"`).
     Do **not** copy that span's DNS monkeypatch or hostname endpoint.

   **Mandatory steps (all of them; stamp-only is insufficient):**
   ```text
   monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", "http://10.0.1.42:8000")
   # N3 residual probe (repeat with "9" in a second case)
   monkeypatch.setenv("ACX_GPU_PROMPT_VERSION", "3")
   from scene.interface_adapters.http.deps import get_gpu_description_adapter
   from scene.infrastructure.vlm.gpu_remote_adapter import (
       GpuRemoteDescriptionAdapter,
   )
   from scene.prompts.caption_system import (
       production_prompt,
       production_prompt_or_task_version,
   )
   adapter = get_gpu_description_adapter()
   assert isinstance(adapter, GpuRemoteDescriptionAdapter)
   assert adapter.prompt_or_task_version == production_prompt_or_task_version()
   assert adapter.prompt_or_task_version == production_prompt().lineage_version
   assert adapter.prompt_or_task_version == "1"
   # Transport-stubbed describe() is MANDATORY — N6 wire E2E.
   # deps construction site today: get_gpu_description_adapter body
   # (settings at deps.py:86; GpuRemoteDescriptionAdapter kwargs near :94-103).
   # gpu_remote_adapter.py:148 binds self._transport; :229-231 _post uses it.
   captured: list[dict] = []
   def handler(request: httpx.Request) -> httpx.Response:
       captured.append(json.loads(request.content))
       return httpx.Response(
           200,
           json={"choices": [{"message": {"content": "ok"}}]},
       )
   adapter._transport = httpx.MockTransport(handler)
   adapter.describe(image_bytes=b"jpeg", context=None)
   posted = captured[0]["messages"][0]["content"]
   assert re.sub(r"\s+", " ", posted.strip()) == re.sub(
       r"\s+", " ", production_prompt().body.strip()
   )
   assert re.sub(r"\s+", " ", posted.strip()) == re.sub(
       r"\s+", " ", adapter._production_prompt.body.strip()
   )
   # N4 source guard over the four create-or-edit files (see Constraints).
   ```
   Stamp equality alone leaves a factory that rewrites the snapshot body
   while keeping stamp `"1"` green (DPR15-H-02). N6 posted-body equality
   is load-bearing on this leg.

**(a) Exact edit that makes it go red**

- Restore free-string constructor kwarg that assigns to
  `self.prompt_or_task_version` → assertion (5) / free-string rejection
  proof fails.
- Restore a free-string stamp path that production wiring can feed (e.g.
  reintroduce constructor kwarg + `deps.py:98` threading of an env-backed
  settings field) → N3 residual/junk and/or N6 stamp/body fail; N4 if the
  literal returns to a guarded file.
- **Named RED (value-filtered env honour — DPR15-H-01):** drop the settings
  field as instructed, then reintroduce an env read that honours only the
  historical residual (or any closed residual set), e.g.
  `v = os.environ.get("ACX_GPU_PROMPT_VERSION"); stamp = v if v in {"3"}
  else "1"` (or whitelist `{3, 9}`). A junk-only `=9` probe stays **green**.
  Residual `"3"` probe **must** go red (stamp becomes `"3"`). N4 also goes
  red if the string constant returns to any of the four guarded files.
  (N2 catches the same cheat when the read is moved to import time.)
- **Named RED (DI post-init stamp — DPR13-H-03):** drop the settings field
  and the `deps.py:98` kwarg as instructed, then re-introduce a post-init
  env stamp inside `get_gpu_description_adapter` itself — e.g. after the
  `GpuRemoteDescriptionAdapter(...)` call,
  `adapter.prompt_or_task_version = os.environ.get("ACX_GPU_PROMPT_VERSION",
  adapter.prompt_or_task_version)`. Direct-constructor legs stay **green**.
  DI leg N3/N6 **must fail** under residual `"3"`. A mutation named as red
  that only runs on the direct-constructor leg is an unrun mutation
  ([TEST-15]).
- **Named RED (DI body rewrite, stamp honest — DPR15-H-02):** factory
  keeps stamp `"1"` but rewrites the snapshot body after construction,
  e.g. `adapter._production_prompt = ProductionPrompt(body="LYING BODY",
  lineage_version="1")` (or mutates `.body` / replaces the object the
  payload site reads) before return. Stamp assertions stay **green**.
  Assertion (6) posted-body equality to `production_prompt().body`
  **must** go red. Stamp-only DI legs are an unrun mutation for this
  cheat ([TEST-15]).

**(b) Discrimination**

- Always-`"1"` stamp hardcode passes (2) under default selection but fails
  (3) under synthetic rebind on a fresh adapter.
- Independent body+version globals pass stamp-only checks but fail posted-
  body equality under synthetic rebind.
- Time-axis split (stamp frozen, body live) passes (2)/(3) when the adapter
  is constructed **after** rebind, but fails the temporal proof; this
  resolver test still requires stamp and body to match on the instance
  under test.
- Direct-constructor-only env-no-effect (assertions (1)–(5)) stays green
  under the Named RED post-init-in-deps stamp rewrite and under the Named
  RED DI body rewrite; only assertion (6) goes red for those sitings.
- Value-filtered residual honour (Named RED DPR15-H-01) stays green under
  a junk-only `=9` behavioral probe; residual `"3"` probe goes red (N3).

**Operator promotion path (explicit):** promoting lineage is a deliberate
code rebind of `PRODUCTION_PROMPT` (body + `lineage_version` together),
observed by **new** adapters that snapshot after the rebind — not an env
flip of a version number alone and not a free-string constructor override.
No free-string `ACX_GPU_PROMPT_VERSION` escape hatch, no
`gpu_prompt_or_task_version` settings field, and no free-string constructor
stamp kwarg ship in this plan (see also No canon warrant — mechanical
promotion UX is out of scope).

#### [TEST-15] red-first proof — settings GPU-stamp field deleted (MANDATORY, unconditional)

**Test name (proposed):**
`test_gpu_prompt_or_task_version_field_deleted_and_env_has_no_stamp_effect`

**Why unconditional (not "if a settings test previously mentioned…"):**
VERIFY: `scene/tests/test_settings.py:8-14`
(`test_description_settings_defaults`) asserts profile / max bytes / mime
types / non-GPU `prompt_or_task_version == "1"` and **never mentions**
`gpu_prompt_or_task_version`. A conditional "if a settings test previously
mentioned the GPU stamp field, rewrite it" never fires, so the deletion
would ship with no red-first evidence. The proof below **always runs**.

**What it asserts:**

1. Schema-surface deletion — **all three mandatory** (`hasattr` alone is
   vacuous against a Pydantic field kept in `model_fields` while instance
   attribute access is overridden to raise `AttributeError`; validation /
   serialization would still expose the setting FROZEN CONTRACT B deletes):
   - `assert not hasattr(DescriptionSettings(), "gpu_prompt_or_task_version")`
   - `assert "gpu_prompt_or_task_version" not in DescriptionSettings.model_fields`
   - `assert "gpu_prompt_or_task_version" not in DescriptionSettings().model_dump()`
   Each fails while the field still exists at `settings.py:40`.
2. **Post-import stamp honesty on direct constructor (N3 + optional N6).**
   Construct `GpuRemoteDescriptionAdapter` with full required kwargs
   (`endpoint_url` / `model_id` / `model_version`) and **no** stamp kwarg.
   With env residual `"3"` and junk `"9"`, assert
   `adapter.prompt_or_task_version == production_prompt_or_task_version()`
   / `"1"`. Optional: transport-stubbed `describe()` still posts the
   selected v1 body (N6). **Do not** treat a junk-only `=9` probe as the
   closed surface alone (DPR15-H-01). Import-time silence is N2 (lineage
   proof), not re-implemented here as a name-filtered spy.
3. **DI-resolver leg (mandatory body + stamp — N3/N6).** Construct via
   `deps.get_gpu_description_adapter` under
   `ACX_GPU_ENDPOINT_URL=http://10.0.1.42:8000` (private-endpoint fixture
   only — see resolver assertion (6) vs
   `test_description_profiles.py:173-184`). Assert stamp `"1"` **and**
   transport-stub `describe()` posted system message equals
   `production_prompt().body` (whitespace-normalised). Same DI leg as
   resolver assertion (6); ship **once**. Direct-constructor assertion (2)
   alone does **not** cover post-init-in-deps stamp rewrite or factory body
   rewrite. Under a retained settings field, DI construction reads the key
   at settings construction (`deps.py:86` — `settings = DescriptionSettings()`;
   `spec = get_profile_spec(...)` is `:87`) via the field factory at
   `settings.py:40` — assertion (1) schema triple is the primary RED for
   retention; N3 residual `"3"` also fails if the field still stamps.

**(a) Exact edit / red-first state that makes it go red**

- Field still present (today `settings.py:40`
  `gpu_prompt_or_task_version: str = Field(default_factory=lambda:
  os.environ.get("ACX_GPU_PROMPT_VERSION", "3"))`) → assertion (1) fails
  on `hasattr`, `model_fields`, and `model_dump()`. Direct-constructor
  assertion (2) does **not** construct settings today
  (`gpu_remote_adapter.py:127-154` takes kwargs only; `DescriptionSettings`
  has no module-level singleton at `settings.py:26`), so N3 on the direct
  path may stay green under field retention alone. DI assertion (3)
  constructs settings at `deps.py:86` (`settings = DescriptionSettings()`;
  next line `spec = get_profile_spec(...)` is `:87`) → field factory at
  `settings.py:40` still runs; if deps still threads the field into a
  free-string stamp kwarg, N3 residual `"3"` goes red. Assertion (1)'s
  schema triple is the unconditional settings-deletion RED. A named RED
  that comes out green is not a guard ([TEST-15]).
- **Named RED (hasattr-only cheat):** keep the field in
  `DescriptionSettings.model_fields` (env-backed factory intact) but
  override instance attribute access so `hasattr` is false → `model_fields`
  and/or `model_dump()` assertions still fail. That is why both schema
  checks are mandatory.
- Field (or any **post-import** free-string env stamp path) honours
  residual into the stamp → assertion (2)/(3) N3 residual `"3"` fails.
- **Named RED (value-filtered env — DPR15-H-01):** honour only residual
  `"3"` (or whitelist `{3, 9}`) into the stamp while ignoring other
  values. Junk-only `=9` stays green; residual `"3"` **must** go red (N3).
- **Scope limit (DPR13-H-02) — this runtime proof does not cover
  import-time env reads inside `caption_system.py`.** That siting is
  covered by **N2** (import-time silence EFFECT) in the lineage proof
  below — do not document import-time cheats as reds for this settings
  test ([TEST-15] unrun mutation).

**(b) Discrimination**

- A no-op settings test that only checks non-GPU `prompt_or_task_version`
  stays green under both red states; only the unconditional schema-surface
  triple (`not hasattr` + `not in model_fields` + absent from `model_dump()`)
  + N3 goes red. Do **not** reintroduce a positive read of the deleted
  field as the discrimination surface.
- Direct-constructor assertion (2) alone stays green under a post-init
  stamp rewrite inside `get_gpu_description_adapter` and under a factory
  body rewrite that keeps stamp `"1"`; DI assertion (3) is what goes red
  for those sitings (see resolver Named REDs DPR13-H-03 and DPR15-H-02).

#### [TEST-15] red-first proof — lineage-version provenance (MANDATORY)

**Test name (proposed):**
`test_production_prompt_lineage_version_is_literal_not_env`

**Why mandatory:** Post-import N3 residual/junk probes and free-string
rejection cannot see an **import-time** env read inside `caption_system.py`
(pytest env unset at import → snapshot holds `"1"`;
`monkeypatch.setenv` after import never reaches it). Production can boot
with `ACX_GPU_PROMPT_VERSION=9` and stamp `"9"` over a v1 body. Closed by
**N2 + N5 + N6** together — not by a constant-key AST walk (split-key
`os.environ["ACX_GPU_" + "PROMPT_VERSION"]` defeats constant-key pins and
raw-substring guards simultaneously).

**What it asserts:**

1. **N5 — construction-site pin.** Parse `scene/prompts/caption_system.py`
   (CWD-independent anchor via `Path(__file__).resolve().parents[1] /
   "prompts/caption_system.py"` or `Path(scene.prompts.caption_system.__file__)`).
   Module-level `PRODUCTION_PROMPT = ProductionPrompt(...)` has keyword
   `lineage_version=` whose value node is `ast.Constant(value="1")`.
2. **N2 — import-time env silence (EFFECT; EXIT A).** Replace `os.environ`
   with a mapping whose `__getitem__` and `get` raise on **any** key;
   `importlib.reload(scene.prompts.caption_system)` must succeed. Computed
   property: no environment read during module import. Closes Cheat A
   (env at `lineage_version=` keyword), Cheat B (module-top capture later
   applied to stamp), and split-key / join / replace key assembly.
   Held-out exemplar for the class (must not be the sole defence as a
   contiguous source literal): `"ACX" + "_GPU_PROMPT_VERSION"`.
3. **N6 — wire E2E.** On a normally constructed adapter with
   transport-stubbed `describe()`:
   `adapter.prompt_or_task_version == production_prompt().lineage_version`
   and posted system body equals `production_prompt().body` (and snapshot
   body). Source shape alone is not enough — the value that labels the
   shipped body must match.
4. Runtime `production_prompt().lineage_version == "1"` alone is
   **forbidden** as the sole form of this proof (import-epoch blindness).

**(a) Exact edit that makes it go red**

- **Named RED (import-time env at keyword):**
  `lineage_version=os.environ.get("ACX_GPU_PROMPT_VERSION", "1")` (or
  `os.getenv` / `os.environ[...]`) → N5 red (non-Constant) **and** N2 red
  (reload under raising environ fails).
- **Named RED (import-time capture elsewhere / split-key):** keep
  `lineage_version="1"` so N5 stays green; add
  `_OVERRIDE = os.environ["ACX_GPU_" + "PROMPT_VERSION"]` (or `.get` /
  `os.getenv` / join/replace assembly) applied later to the stamp → N2
  **must** go red. A constant-key AST pin that only matches
  `Constant("ACX_GPU_PROMPT_VERSION")` stays green under split-key — that
  is why N2 is the class proof.
- **Named RED (wire lie):** construction site honest, but adapter stamp
  diverges from `production_prompt().lineage_version` on the describe path
  → N6 red.
- Equivalent N5 reds: `lineage_version=_VERSION` (Name alias),
  `lineage_version="3"` (dishonest literal).

**(b) Discrimination**

- Permanent guard = N5 ∧ N2 ∧ N6. Runtime equality of the resolved stamp
  string is not a substitute for N2.
- **Scope:** pins selected-config lineage honesty and import-time env
  silence for `caption_system.py`. Does not pin body text (inventory) or
  post-construction rebind (intentional DEPICT-1 mutation path). N4 covers
  the four create-or-edit files' string constants; N2 covers effect at
  import.

#### [TEST-15] red-first proof — free-string constructor override rejected (MANDATORY)

**Test name (proposed):**
`test_gpu_adapter_rejects_free_string_prompt_version_kwarg`
(pair with
`test_gpu_adapter_init_has_no_free_string_stamp_parameter` or fold both
into one test module — both surfaces are mandatory).

**Why mandatory:** Dropping only the env stamp path still leaves
`GpuRemoteDescriptionAdapter(prompt_or_task_version="9")` as a supported
way to post the v1 body under a lying stamp (today's assignment at
`gpu_remote_adapter.py:133`/`:143` + post at `:182`). Round-3 finding
DPR3-M-02 asked to **preserve** the explicit-override test at
`test_gpu_remote_adapter.py:51-65`; that requirement is **closed wontfix,
superseded by DPR4-H-01**. Do not reinstate a preserve-the-override
checklist item.

**Why a partial call is vacuous (do not write the elided form):**
`GpuRemoteDescriptionAdapter.__init__` is keyword-only
(`gpu_remote_adapter.py:127-133`) with **three** parameters that have no
defaults today: `endpoint_url`, `model_id`, `model_version`. So
`GpuRemoteDescriptionAdapter(prompt_or_task_version="9")` raises
`TypeError` **today** — for **missing required arguments** — with the
kwarg still present and still honoured. A test that elides the required
kwargs, specifies no `match=`, and has no positive control stays green
under the current free-string hole and under the prescribed red-first
mutation. The proof must pin the *unexpected keyword* failure mode.

**Why a keyword-name-only `TypeError` is also insufficient (DPR13-H-04):**
Removing `prompt_or_task_version` from the signature and adding a
differently-named free-string stamp parameter (e.g.
`stamp_version: str | None = None` that, when passed, overrides the
snapshot-derived stamp) keeps the `TypeError` on
`prompt_or_task_version=` **green** (the old name genuinely is unexpected)
while fully restoring constructor-level stamp/body desync — the defect
DPR3-M-02 was closed wontfix to prevent. The Named RED for that cheat
is a **source-level parameter-set allowlist** over `__init__`, not another
runtime `TypeError` on a second guessed name.

**What it asserts:**

1. **Parameter absent — full construction (required shape).**
   ```text
   with pytest.raises(TypeError, match="unexpected keyword argument"):
       GpuRemoteDescriptionAdapter(
           endpoint_url="http://gpu.test:8000",
           model_id="test-model",
           model_version="test-version",
           prompt_or_task_version="9",
       )
   ```
   The free-string kwarg does not exist on the constructor. The `match=`
   must require the unexpected-keyword failure mode (not a missing-
   required-argument `TypeError`).
2. **Positive control (required).** The same full construction **without**
   the free-string kwarg succeeds:
   ```text
   adapter = GpuRemoteDescriptionAdapter(
       endpoint_url="http://gpu.test:8000",
       model_id="test-model",
       model_version="test-version",
   )
   assert adapter.prompt_or_task_version == production_prompt_or_task_version()
   ```
   (Transport may be omitted if the constructor does not require it — today
   `transport` defaults to `None` at `gpu_remote_adapter.py:138`; include it
   when the test also exercises `describe()`.)
3. **Stamp always from selected-config snapshot.** A normally constructed
   adapter (no stamp kwarg) has
   `.prompt_or_task_version == production_prompt_or_task_version()` under
   default selection **and**, after synthetic `PRODUCTION_PROMPT` rebind, a
   **fresh** adapter has stamp `"2"` (same atomic path as above).
4. **Owned-test rewrite.** `test_gpu_remote_adapter.py:51-65` no longer
   passes `prompt_or_task_version="3"` or asserts `== "3"`; it omits the
   kwarg and asserts the honest stamp (or the free-string-rejection test
   owns the negative path exclusively). Payload/transport assertions in
   that file may remain.
5. **`__init__` formals — N7 (superset + forbidden set; not exact equality).**
   Parse `gpu_remote_adapter.py`. Locate `GpuRemoteDescriptionAdapter.__init__`.
   Collect formals excluding `self`. Assert **N7**:
   - `REQUIRED ⊆ formals` with
     `REQUIRED = {endpoint_url, model_id, model_version, connect_timeout_s,
     read_timeout_s, api_key, max_concurrent_calls, transport}`
     (today's signature at `gpu_remote_adapter.py:127-140` minus deleted
     `prompt_or_task_version`);
   - `formals ∩ FORBIDDEN == ∅` with
     `FORBIDDEN = {prompt_or_task_version, stamp_version, task_version,
     version_stamp, gpu_prompt_or_task_version}` — **exactly these five**;
     extending FORBIDDEN requires amending this plan (EXIT B);
   - `args.vararg is None` and `args.kwarg is None`.
   Legitimate additive optional non-lineage formals (e.g. `retry_count`)
   stay GREEN. Exact set equality is **forbidden** (false-REDs additive
   extension — DPR19-M-03). Runtime `TypeError` on one keyword name is
   **not** a substitute for N7.
6. **Stamp assignment — N8 (runtime load-bearing; AST optional).**
   Load-bearing: N6 / assertion (7) runtime stamp equality. An optional
   AST companion over `__init__` writes to `self.prompt_or_task_version`
   (Assign/AnnAssign/setattr) **must accept** pure reaching definitions
   from `production_prompt()` / `self._production_prompt` culminating in
   `.lineage_version`, **including intermediate locals of any depth**
   (`snap = production_prompt(); lv = snap.lineage_version;
   self.prompt_or_task_version = lv` stays GREEN). Reject free-string
   parameter Names and env Calls. Do not ship an over-literal matcher that
   accepts only `self._production_prompt.lineage_version` as a direct
   Attribute chain (DPR19-M-02 false-RED).
7. **Runtime stamp equality (mandatory — N6 companion, shape-independent).**
   After normal construction (positive control kwargs, no free-string stamp):
   ```text
   assert adapter.prompt_or_task_version == production_prompt().lineage_version
   assert adapter.prompt_or_task_version == production_prompt_or_task_version()
   assert adapter.prompt_or_task_version == "1"  # under default selection
   ```
   After synthetic `PRODUCTION_PROMPT` rebind to `lineage_version="2"`, a
   **fresh** adapter must stamp `"2"`. Prefer pairing with transport-stubbed
   `describe()` so N6 body equality ships on the same instance.

**(a) Exact edit that makes it go red**

- Reintroduce a free-string constructor parameter named
  `prompt_or_task_version` that is assigned to
  `self.prompt_or_task_version` (today's shape at
  `gpu_remote_adapter.py:133`/`:143`, any default including
  `str | None = None` that is honored when provided) → assertion (1)
  fails: the full construction with `prompt_or_task_version="9"` no longer
  raises `TypeError` matching `unexpected keyword argument`, **and/or** a
  constructed instance stamps `"9"` while `describe()` still posts the v1
  body at the payload site. (A missing-arg-only `TypeError` from an elided
  call is **not** a valid red signal.) N7 fails (`prompt_or_task_version ∈
  FORBIDDEN`); assertion (7)/N6 fails on stamp `"9"`.
- **Named RED (differently-named free-string stamp — DPR13-H-04):** remove
  `prompt_or_task_version` from the signature exactly as mandated, then add
  `stamp_version: str | None = None` (or any other FORBIDDEN name) which,
  when passed, overrides the snapshot-derived stamp. Assertion (1) stays
  **green**. Assertion (2) stays green when the new kwarg is omitted.
  Assertion (5) / N7 **must** fail (`stamp_version ∈ FORBIDDEN`). Runtime
  assertion (7) fails if the override is exercised. A mutation named as
  red that only reintroduces the old keyword is an unrun mutation for this
  cheat ([TEST-15]).
- **Named RED (non-literal stamp write — DPR15-M-07):** keep a snapshot
  assign, then overwrite via `setattr(self, "prompt_or_task_version", "3")`
  or `self.__dict__["prompt_or_task_version"] = "3"`. Assertion (7) / N6
  **must** go red (resolved stamp ≠ `production_prompt().lineage_version`).

**(b) Discrimination / permanent guard**

- **Cheating shape killed (name-pinned):** keep production honest but
  re-add the free-string constructor kwarg so direct construction (and any
  future caller) can lie about lineage without touching
  `PRODUCTION_PROMPT`. Assertion (1) goes red.
- **Cheating shape killed (renamed free-string — DPR13-H-04):** remove the
  old name, add `stamp_version` (FORBIDDEN). Assertion (1) stays green;
  N7 goes red; N6 goes red if exercised.
- **Cheating shape killed (non-literal write — DPR15-M-07):** snapshot
  assign plus later `setattr` / `__dict__` overwrite → N6/assertion (7) red.
- **Legitimate shapes kept green:** intermediate locals binding
  `.lineage_version` (N8); additive non-lineage formals outside FORBIDDEN
  (N7 superset).
- Permanent guard: assertions (1)+(2)+(3)+N7+N6. Preferred shape is **no
  caller-supplied version at all**. Elided-only call with no `match=` is
  **forbidden** as the form of this test.
- Enum fallback is **not** the planned path (removal is). If ever taken,
  amend FORBIDDEN/REQUIRED in the same change.

## Consolidated Checklist

### Context and Ownership

- [ ] Loaded governing assessment §1 D1–D3 and §10g Lane A scope before editing.
- [ ] Verified every cited rule ID via definition-anchor grep under
      `canon/lexicons/`; read distilled evidence for each load-bearing rule.
- [ ] Confirmed file ownership: only Lane A paths + `scene/prompts/caption_system.py` +
      the five test surfaces named in `## Constraints` + owned one-line `deps.py:98` drop of free-string stamp
      kwarg; no Lane B schema edits; no Lane C metrics edits.
- [ ] Confirmed prompt-body copies: exactly two live v1 copies before the
      change; zero local copies after.
- [ ] Register / fact-inventory / voice-partition work is DEPICT-1 — not
      absorbed here. Weave rewrite is F1 (b) — unowned, not absorbed here.

### Checklist for Slice 1: Single prompt source + parity test

- [ ] Create `scene/prompts/caption_system.py` with markers, production v1
      body, selected `ProductionPrompt` (or body landing that Slice 2 binds),
      `production_prompt()` / `production_system_prompt()` /
      `production_prompt_or_task_version()` — **not** `PromptVariant`, v2/v3
      bodies, or full `PROMPT_VARIANTS`.
- [ ] Rewire `gpu_remote_adapter.py` to import `production_prompt`; delete
      local `_SYSTEM_PROMPT` body; snapshot once at `__init__`; post
      `self._production_prompt.body` at the payload site
      (`messages[0]["content"]` — today `gpu_remote_adapter.py:182`).
- [ ] **Delete** the stale `ACX_GPU_PROMPT_VERSION` bump instruction at
      `gpu_remote_adapter.py:23-24` (exact text: "Bump ACX_GPU_PROMPT_VERSION
      / default prompt_or_task_version when this contract changes.") and
      replace the "Keep in lockstep…" block with a pointer to
      `scene/prompts/caption_system.py` + parity/inventory tests. Do not leave
      any operator instruction to bump `ACX_GPU_PROMPT_VERSION`.
- [ ] Rewire `bakeoff.py`: import shared v1 body + markers via accessors;
      **keep local `PromptVariant`**; delete local `_PROMPT_V1_SYSTEM` only;
      keep `_PROMPT_V2_SYSTEM`; introduce **`build_prompt_variants()`** and
      set `PROMPT_VARIANTS = build_prompt_variants()` (v1 entry resolves body
      through accessor **inside the helper when it runs** — not via
      `_FROZEN_V1 = production_system_prompt()`); keep
      `DEFAULT_PROMPT_VARIANT = "v1"` defined in bakeoff; re-export
      `build_prompt_variants`; keep pass-1/weave/compress local.
- [ ] Add `test_prompt_lineage_seam.py` **default-path** parity test that
      **transport-stubs** `describe()`, captures `messages[0]["content"]`,
      and asserts whitespace-normalised equality to
      `bakeoff.PROMPT_VARIANTS["v1"].system` (attribute-only comparison
      forbidden in the docstring). Docstring states **parity temporal scope
      option (a)**: same-construction-epoch only — not a live post-rebind
      guarantee for a pre-built harness registry.
- [ ] Add **rebind-before-construction** proof
      (`test_bakeoff_v1_body_reflects_rebind_before_variant_construction`):
      rebind `PRODUCTION_PROMPT` to synthetic, then call
      **`build_prompt_variants()`** (the real registry helper — **not** a
      hand-built `PromptVariant`) and construct a fresh adapter; assert
      `registry["v1"].system == synthetic.body` and equals the adapter's
      posted body. **Named RED:** keeping module-level
      `_FROZEN_V1 = production_system_prompt()` and reading it **inside
      `build_prompt_variants()`** must turn this proof RED. Also red if
      bakeoff freezes via `from … import PRODUCTION_PROMPT` / leftover local
      full-body literal inside the helper. **Not** red — and not to be
      documented as red — if the freeze sits at the module-level
      `PROMPT_VARIANTS = …` site with a correct helper; that is the
      registry-provenance test's job.
- [ ] Add **registry-provenance** assertion (`test_prompt_variants_is_built_by_the_helper`
      or equivalent) — **CLASS pin**, same shape as the lineage-version AST
      proof: (1) module-level `PROMPT_VARIANTS` assignment's value node is a
      no-argument `Call` to `Name(id="build_prompt_variants")`; **and** (2)
      every `Assign`/`AnnAssign` targeting `PROMPT_VARIANTS` at **any scope**
      in `bakeoff.py` matches that same call shape (a later function-local
      rebind to a hand-built dict fails (2) while (1) stays green). **Named
      RED:** replace the module-level RHS with a hand-built dict literal whose
      v1 body is still correct → must turn red; secondary assignment of a
      non-helper value anywhere in the module → must turn red ([TEST-15]
      permanent discrimination guard; [REF-10] one registry, one construction
      site — knowledge that must change together). Runtime equality is **not**
      an acceptable substitute — it cannot discriminate in the import epoch.
      Parse path is CWD-independent (`Path(scripts.eval_harness.bakeoff.__file__)`
      or equivalent).
- [ ] Document red-first edit (a) — change only the payload-inserted string —
      rebind-before-construction red (a′) including the named `_FROZEN_V1`
      edit, and discrimination case (b) (including the three default-path
      cheating shapes + the hand-built-`PromptVariant` / `_FROZEN_V1` freeze
      cheat) in the test docstrings.
- [ ] **MANDATORY** single-source **foldable-constant definition-site**
      inventory test
      (`test_production_v1_body_has_exactly_one_definition` or equivalent) —
      **not** optional / not stretch. Inventory unit = AST assignment /
      call-argument nodes **and** `FunctionDef` / `AsyncFunctionDef`
      `args.defaults` / `args.kw_defaults` at **any scope** whose folded
      constant value equals `canonical` from `production_system_prompt()`
      (whitespace-normalised). Inventory function takes explicit
      `roots: Sequence[Path]`. **Not** a raw source-text grep for
      `"2-4 plain sentences"`; **not** a runtime import-and-compare of module
      attributes / dataclass fields (would false-RED
      `PROMPT_VARIANTS["v1"].system` after rewire). Assert **exactly one**
      foldable-constant definition at exactly
      `scene/prompts/caption_system.py`. Permitted non-definition hits:
      1. bakeoff long-band
         `.replace("2-4 plain sentences", "4-8 plain sentences")` on the
         imported v1 body,
      2. `PROMPT_VARIANTS["v1"].system` holding the imported body by reference
         / via accessor call at variant-construction time (`Name`/`Call`, not
         a foldable full-body literal),
      3. tests that quote fragments,
      4. the accessors themselves.
      Guarantee wording: **exactly one foldable-constant definition** (not
      "any third full assignment" via non-foldable assembly).
      Red-first (a): inject a second foldable full-body definition → count
      fails.
      Permanent split-literal guard (a′): write a real split-literal module
      into `tmp_path`, scan with `roots=` including that path, assert count
      goes to 2, assert substring scan of that file finds no contiguous
      `"2-4 plain sentences"` — **no** comment-only / "documented red path"
      escape.
      Permanent function-local guard (a″): write a function-local full-body
      constant into `tmp_path`, assert count goes to 2.
      Permanent default-argument guard (a‴): write a module with a full-body
      duplicate as a **default argument** / kw-default into `tmp_path`,
      assert count goes to 2 (fixture the test writes — not a documented
      path).
      Discrimination (b): consumer-parity alone stays green under
      (a)/(a′)/(a″)/(a‴); only the inventory test catches the unused third
      body.
- [ ] Verification:
      `uv run --extra dev pytest scene/tests/test_prompt_lineage_seam.py scene/tests/test_gpu_remote_adapter.py scene/tests/test_eval_harness_pipeline.py -q`

### Checklist for Slice 2: Honest atomic version stamp

- [ ] Selected `ProductionPrompt` carries `body` + `lineage_version` together;
      primary accessor `production_prompt()` returns that one instance; field
      accessors read through it (no independent body global + version map /
      variant key).
- [ ] **Delete** `DescriptionSettings.gpu_prompt_or_task_version` (today
      `settings.py:40`) — zero production readers after `deps.py:98` drop;
      drop free-string `ACX_GPU_PROMPT_VERSION` with it. Do not repoint as a
      dead mirror.
- [ ] **Remove** free-string `prompt_or_task_version` constructor kwarg from
      `GpuRemoteDescriptionAdapter.__init__` (today `gpu_remote_adapter.py:133`
      / assigned at `:143`); snapshot
      `self._production_prompt = production_prompt()` once at init; bind
      `self.prompt_or_task_version = self._production_prompt.lineage_version`;
      post `self._production_prompt.body` at the payload site. **Do not**
      freeze stamp at init while re-reading body via
      `production_system_prompt()` at describe time (time-axis split).
      **Do not** keep `str | None = None` as an honored free-string override.
- [ ] **Owned one-line** `deps.py:98`: drop
      `prompt_or_task_version=settings.gpu_prompt_or_task_version` so
      production wiring matches the constructor with no stamp kwarg
      (mandatory after constructor removal — not "optional if settings
      honest").
- [ ] Update **resolved-default** dishonest sites:
      `test_description_profiles.py:214` and `:263` → expect `"1"`.
- [ ] **Unconditional** settings-deletion proof (always runs; today
      `test_settings.py:8-14` never mentions the GPU field so a conditional
      rewrite never fires):
      `assert not hasattr(DescriptionSettings(), "gpu_prompt_or_task_version")`
      **and**
      `assert "gpu_prompt_or_task_version" not in DescriptionSettings.model_fields`
      **and**
      `assert "gpu_prompt_or_task_version" not in DescriptionSettings().model_dump()`
      **and** N3 residual/junk probes **and** N4 AST source guard
      (CWD-independent paths). Red-first: field still present at
      `settings.py:40` (including hasattr-only cheat) fails schema triple.
      Import-time env reads are N2's job, not this checklist item.
- [ ] **Add** lineage-version proof
      (`test_production_prompt_lineage_version_is_literal_not_env`) —
      **N5 + N2 + N6** (see Constraints). Named REDs: env at keyword;
      split-key / module-top capture (N2); wire stamp/body lie (N6).
      Runtime `== "1"` alone is **not** a substitute for N2.
- [ ] **Rewrite** `test_gpu_remote_adapter.py:51-65`: remove
      `prompt_or_task_version="3"` and `assert == "3"`; omit the kwarg;
      assert stamp equals `production_prompt_or_task_version()` / `"1"`.
      Keep payload/transport assertions. DPR3-M-02 preserve-override is
      **wontfix / superseded** — do not reinstate it.
- [ ] **Add** no-arg constructor default test expecting `"1"` /
      `production_prompt_or_task_version()` (full required kwargs present).
- [ ] **Add** free-string constructor rejection proof
      (`test_gpu_adapter_rejects_free_string_prompt_version_kwarg`):
      full construction + `prompt_or_task_version="9"` raises
      `pytest.raises(TypeError, match="unexpected keyword argument")`;
      positive control succeeds; **N7** (REQUIRED ⊆ formals, FORBIDDEN ∩
      formals = ∅, no `*args`/`**kwargs`); **N6/N8** runtime stamp equality
      (intermediate locals legal). Named RED DPR13-H-04: `stamp_version`
      → N7 red. Named RED DPR15-M-07: setattr overwrite → N6 red.
- [ ] Add default-honesty + **synthetic-v2** discrimination on a **fresh**
      adapter: inject `ProductionPrompt(body="SYNTHETIC…",
      lineage_version="2")` **then** construct; assert posted
      `messages[0]["content"]` and adapter stamp both equal the injected
      values (via snapshot). Pin single-snapshot shape:
      `adapter._production_prompt is caption_system.PRODUCTION_PROMPT` and
      `adapter.prompt_or_task_version == adapter._production_prompt.lineage_version`
      (kills two-adjacent-accessor `__init__` with no held object).
- [ ] Add **temporal snapshot** proof: construct under v1, **then** rebind to
      synthetic v2, assert existing adapter wholly old (body **and** stamp)
      and fresh adapter wholly new.
- [ ] Add **resolver no-divergence** test: N1 + N3 + N4 + N6 on direct
      constructor **and** DI `deps.get_gpu_description_adapter` under
      `ACX_GPU_ENDPOINT_URL=http://10.0.1.42:8000` (private-endpoint
      fixture from `test_description_profiles.py:173-184`). Named REDs:
      DPR13-H-03 post-init env stamp in factory; DPR15-H-02 body rewrite
      with honest stamp; DPR15-H-01 residual honour (N3 residual red).
- [ ] State cache-key consequence in the PR/handoff note: greenfield accept;
      no migration/shim.
- [ ] Verification:
      `uv run --extra dev pytest scene/tests/test_prompt_lineage_seam.py scene/tests/test_settings.py scene/tests/test_description_profiles.py scene/tests/test_gpu_remote_adapter.py -q`

### Review Readiness

- [ ] No boundary-touching schema change left undocumented (expected: none).
- [ ] Default-path parity test cannot pass by reading the same constant twice
      or by attribute-only comparison; it reads the posted system string.
      Docstring states parity temporal scope option (a)
      (same-construction-epoch only).
- [ ] Rebind-before-construction bakeoff proof calls `build_prompt_variants()`
      after rebind (not a hand-built `PromptVariant`) and is red if v1 freezes
      via module-level `_FROZEN_V1 = production_system_prompt()` /
      `from … import PRODUCTION_PROMPT` / leftover local full-body literal.
- [ ] **Mandatory** single-source inventory test via
      `scene/tests/test_prompt_lineage_seam.py:count_foldable_v1_body_definitions(roots, *, canonical)`
      asserts foldable-constant definition count == 1 at exactly
      `caption_system.py`; folds `Constant` / `BinOp(Add)` /
      `JoinedStr` (known-constant interpolations only); walks assignment,
      call-argument, **and** `FunctionDef`/`AsyncFunctionDef`
      `args.defaults`/`args.kw_defaults`; red under a second foldable
      full-body definition, under a split-literal duplicate written into
      `tmp_path` via `roots=` (worked example: `"2-" + "4 plain…"`), under
      a function-local duplicate, and under a **default-argument**
      duplicate fixture; no import-and-compare alternative; no
      comment-only red path.
- [ ] Version stamp cannot sit at `"3"` for production v1 text under default
      construction (N1). Closed by settings-deletion schema triple + N2 +
      N3 + N4 + N5 + N6 + N7 (see Constraints — do not restate mechanisms).
- [ ] Atomic discrimination reaches red under: independent body+version
      globals, always-`"1"` stamp function, import-time-frozen adapter
      default, import-time body binding that misses the module-attribute
      monkeypatch, free-string constructor override, and two-adjacent-
      accessor `__init__` with no held snapshot
      (`_production_prompt is PRODUCTION_PROMPT` identity required).
- [ ] Temporal snapshot proof reaches red under stamp-at-init +
      body-at-describe live re-read after rebind.
- [ ] Resolver no-divergence covers stamp + posted body (N3/N6) on direct
      and DI paths (DPR13-H-03 / DPR15-H-02 Named REDs reachable).
- [ ] No second foldable-constant definition of the production system-prompt
      body remains under `apps/prototype-description-service/`; inventory
      keys on foldable-constant sites equal to
      `production_system_prompt()` value (not a source-text marker grep
      alone; not the weave clause; not live field identity).
- [ ] Stale `ACX_GPU_PROMPT_VERSION` bump instruction deleted from
      `gpu_remote_adapter.py:23-24`.
- [ ] `PromptVariant` and harness-only v2/v3 bodies remain in `bakeoff.py`
      (not shipped into the production shared module).
- [ ] Cache-key hazard acknowledged; no compatibility shim introduced.
- [ ] Weave-side F1 consumption (F1 (b)) explicitly unowned / Not-Done; no
      lane in this wave delivers it and no plan file owns it.
- [ ] `responses.py` explicitly **unowned in this wave** (DEPICT-1 disclaims
      it; this plan does not edit it; field already present).
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

- [ ] Exactly one foldable-constant definition of the production caption
      system-prompt text; production adapter snapshots it via
      `production_prompt()` once at `__init__`; harness v1 resolves it via
      `production_system_prompt()` / `production_prompt().body` inside
      `build_prompt_variants()` when the helper runs (parity temporal scope
      option (a); module-level `PROMPT_VARIANTS = build_prompt_variants()`).
- [ ] `test_production_system_prompt_matches_harness_v1` (or equivalent) is red
      under the documented payload-string edit and green at HEAD; it compares
      the transport-captured posted system string to
      `bakeoff.PROMPT_VARIANTS["v1"].system` under same-construction-epoch
      parity (not a live post-rebind guarantee for a pre-built registry).
- [ ] `test_bakeoff_v1_body_reflects_rebind_before_variant_construction` (or
      equivalent) calls **`build_prompt_variants()` after rebind** (not a
      hand-built `PromptVariant`), compares `registry["v1"]` to a freshly
      constructed adapter, is red if the helper reads a frozen v1 body via
      an in-helper `_FROZEN_V1 = production_system_prompt()` / `from …
      import PRODUCTION_PROMPT` / leftover local full-body literal, and green
      when helper-time accessor resolution reflects a pre-construction rebind.
- [ ] Registry-provenance assertion is red when module-level
      `PROMPT_VARIANTS` is a hand-built dict rather than
      `build_prompt_variants()`, including when its v1 body is correct — the
      one cheat the rebind proof structurally cannot see (DPR12-H-01).
- [ ] `test_production_v1_body_has_exactly_one_definition` (or equivalent)
      is **mandatory**, keys on **foldable-constant definition sites** equal
      to whitespace-normalised `production_system_prompt()` (not source-text
      marker grep; not runtime import-and-compare), walks assignment,
      call-argument, **and** `args.defaults`/`args.kw_defaults`, takes
      `roots: Sequence[Path]`, red under a second foldable full-body
      definition **and** under a split-literal duplicate written into
      `tmp_path` **and** under a function-local duplicate **and** under a
      default-argument duplicate fixture, and green at HEAD with count == 1
      at `caption_system.py` only.
- [ ] Adapter default stamp is `"1"`, matching production v1 text; same
      `production_prompt()` snapshot supplies stamp and posted body (N1).
      Settings field deleted (schema triple) + N2 + N3 + N4 + N5 + N6.
- [ ] `GpuRemoteDescriptionAdapter` has no free-string stamp formal (N1/N7);
      stamp and body from one `__init__` snapshot (N8/N6). Free-string
      rejection (TypeError + N7 + N6) red on old kwarg, renamed FORBIDDEN
      formal, or setattr/`__dict__` overwrite.
- [ ] Atomic discrimination: injecting
      `ProductionPrompt(body="SYNTHETIC…", lineage_version="2")` **then**
      constructing a fresh adapter makes the posted system content and the
      adapter stamp both reflect the synthetic values together.
- [ ] Temporal snapshot: construct under v1, rebind to synthetic v2, existing
      adapter stays wholly old (body **and** stamp), fresh adapter is wholly
      new.
- [ ] Resolver no-divergence: N1 + N3 + N6 on direct and DI
      `deps.get_gpu_description_adapter` paths (Named REDs DPR13-H-03,
      DPR15-H-02, DPR15-H-01).
- [ ] Existing GPU adapter + harness pipeline tests green under
      `uv run --extra dev pytest` with the paths above;
      `test_gpu_remote_adapter.py:51-65` rewritten (no free-string `"3"`
      override; honest stamp assertion).
- [ ] Stale `ACX_GPU_PROMPT_VERSION` bump instruction removed from
      `gpu_remote_adapter.py:23-24`.
- [ ] No edits to DEPICT-1-owned schema files or Lane C `caption_metrics.py`;
      `responses.py` left unowned / unedited this wave.
- [ ] No prompt wording changes; no colour vocabulary; no metrics; no
      three-surface production promotion.
- [ ] `PromptVariant` remains defined only in `bakeoff.py`.

## Not-Doing

- Changing what any prompt **says** (F2 emotion-bearer wording, F4
  three-surface production promotion, F1 weave clause rewrite). Not shipping
  in DEPICT-0. Atomic body+stamp is a **prerequisite** for later promotion
  work (N9); this plan does **not** deliver a mechanical promotion path for
  harness v2/v3 into production.
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
- Preserving free-string `ACX_GPU_PROMPT_VERSION` or a
  `DescriptionSettings.gpu_prompt_or_task_version` field with no production
  reader as an independent stamp source (would re-certify stamp/body
  divergence or assert the accessor against itself).
- Preserving free-string constructor
  `prompt_or_task_version: str = …` on `GpuRemoteDescriptionAdapter`
  (today `gpu_remote_adapter.py:133`/`:143`) — would re-certify stamp/body
  divergence via `GpuRemoteDescriptionAdapter(prompt_or_task_version="9")`
  over the v1 body at `:182`. DPR3-M-02 preserve-the-override is
  **wontfix / superseded**; do not reinstate it.
- Freezing the stamp at `__init__` while re-reading the body at describe
  time via a separate accessor call (time-axis body/stamp split under
  `PRODUCTION_PROMPT` rebind).
- Keying the single-source inventory solely on a source-text substring grep
  for `"2-4 plain sentences"` (split-literal evadeable; today's body is
  already multi-line concat + f-string at `gpu_remote_adapter.py:28-37`).
- Shipping a runtime import-and-compare inventory that false-REDs
  `PROMPT_VARIANTS["v1"].system` holding the imported body by reference.
- Leaving the stale "Bump ACX_GPU_PROMPT_VERSION …" operator instruction at
  `gpu_remote_adapter.py:23-24` after this plan drops that control.
- Consumer binding via direct `PRODUCTION_PROMPT.body` reads or dedicated
  import-time body exports (misses Slice-2 module-attribute monkeypatch on
  fresh `production_prompt()` calls). The prohibition scopes to
  `from … import PRODUCTION_PROMPT` at the call site for the selected
  config; instance-held snapshot reads (`self._production_prompt.body`)
  remain required.
- Claiming production↔harness parity as a **live** post-rebind guarantee for
  an already-built `PROMPT_VARIANTS` registry (parity temporal scope is
  option (a): same-construction-epoch only; rebind-before-construction
  proof is mandatory).
- Softening the single-snapshot assertion with an unobservable "or the body
  that was current when `production_prompt()` was snapshotted" alternative
  that lets two adjacent accessor calls pass as a snapshot.
- Comment-only / "documented second red path" substitutes for a real
  `tmp_path` + `roots=` inventory discrimination (including the
  default-argument duplicate fixture).
- Assigning `responses.py` to Lane B / DEPICT-1 when DEPICT-1 disclaims it;
  leave it **unowned in this wave** (field already present; no edit).

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
