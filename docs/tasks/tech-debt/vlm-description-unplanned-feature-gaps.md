# VLM / Description-Service: Unplanned Feature Gaps

> **Type**: Tech-debt backlog — features with **no owning task, epic, or branch**.
> **Date**: 2026-07-08
> **Captured under**: `MAINT-vlm-unplanned-gaps-20260708` (branch `feature/maint-vlm-unplanned-gaps`)
> **Sources**: [context-aware-image-description-roadmap-2026-06-13.md](../../roadmaps/context-aware-image-description-roadmap-2026-06-13.md), E20 epic (`docs/epics/v0.5.0/production-alt-text-workflow-and-governance-epic.md`), VLM-2A/2B/2C + E19/E20-9/10/11 plans.

## Purpose

Snapshot of description/captioning features **named in the roadmap or implied by table-stakes parity but with no plan**. Each was verified as unowned: no task doc under `docs/tasks/`, no epic row, no feature branch (checked `feature/{e20-brand-a,e20-fusion,vlm-3,vlm-4}` — all docs-only plans that explicitly exclude these). Not a task plan; a triage list to feed later `/scope` / planning.

## Already covered (excluded from this list)

For contrast — candidates that **are** owned, so not debt:
- Eval / test harness, detailed-tier model bake-off → **shipped** (VLM-2A/2B/2C on `main`).
- GPU detailed tier, async describe worker, `gpu_phi4`/`florence_large` → planned `feature/vlm-3`.
- Anti-hallucination generation → planned `feature/vlm-4`.
- Brand/logo (non-face) captioning → planned `feature/e20-brand-a` (`ContextPack.brands`).
- Context-fusion / fact-attachment output → planned `feature/e20-fusion`.
- Hosted-provider tier + governance → planned E20-11 (slice-1 adapter already on `main`).
- Write path, WP-CLI, bulk, review/history, refresh, usage/budget → E20-1..7.
- Context-pack contract, roster-identity guardrails → E20-9, E20-10.

## Unplanned gaps

### 1. Multilingual output (WPML / Polylang)
- **What**: per-language alt-text generation and storage; integration with WPML/Polylang so a translated attachment gets a translated draft.
- **Roadmap origin**: Phase 4 table / §"Table Stakes from AltText.ai" — flagged "Later beta; important for parity but not MVP."
- **Status**: no task/epic/branch. `grep` for `wpml|polylang|multilingual|language param` across `docs/tasks`, `docs/epics`, and code returns nothing.
- **Why it matters**: parity table-stake for the WordPress alt-text category; gates non-English sites.
- **Rough size**: M — plugin-side language resolution + a `language` request field + provider/prompt plumbing. Depends on the output contract being language-parameterized.

### 2. Configurable output modes (SEO draft / style / detail / length / prefix-suffix)
- **What**: user-facing controls for output style (accessibility vs SEO-aware draft), detail level, target length, and prefix/suffix — without exposing raw prompt plumbing.
- **Roadmap origin**: Phase 5 "Context-Aware Differentiation" deliverable ("Output modes: visual facts, accessibility alt draft, SEO-aware draft, and 'needs human review' reasons"; "Configurable style/detail/length/language").
- **Status**: no task/epic/branch. E20-9 (context-pack) and E20-FUSION (fact attachment) cover *inputs* and *weaving*, **not** user-facing output-style config. `grep` for `style.*detail|length param|prefix/suffix|seo keyphrase` returns nothing.
- **Why it matters**: a core Phase-5 differentiation claim ("visibly better than a generic caption") is partly unaddressed without selectable output altitudes.
- **Rough size**: M — request-schema fields + prompt/template variants + WP settings surface. Some overlap with E20-FUSION altitude logic; scope to avoid duplication.

### 3. Automatic generation on upload
- **What**: hook new WordPress media uploads to auto-enqueue a description (opt-in, missing-alt-only), vs today's manual/headless trigger.
- **Roadmap origin**: "Table Stakes" row "Automatic generation — New uploads can be processed without manual work" → marked "Post-MVP."
- **Status**: no task/epic/branch. `grep` for `auto.*generat.*upload|on-upload|attachment upload hook` returns nothing.
- **Why it matters**: table-stake convenience parity; the "install, upload, alt appears" expectation set by competitors.
- **Rough size**: S–M — a WP upload hook that enqueues through the existing describe path + bulk/retry ledger (E20-4). Should land after E20-7 usage/budget controls to avoid uncapped spend.

### 4. LLM-judge scoring tier (eval harness)
- **What**: implement the semantic LLM-as-judge scoring tier in the eval harness (§6c tiers 3–4) — currently a fail-fast stub.
- **Origin**: VLM-2A plan Not-Doing ("LLM-judge tier is a flag + interface stub"); enforced in code (`scripts/eval_harness/cli.py:363` `_reject_llm_judge`, exits on `--llm-judge`; `caption_metrics.py:108` easy_wrong traps deferred to this tier).
- **Status**: stub only; no task/epic owns implementing it. VLM-3 and E20-FUSION both explicitly defer it.
- **Why it matters**: deterministic metrics cannot catch semantic hallucination / easy-wrong traps; VLM-4's anti-hallucination bake-off leans on eval evidence that this tier would strengthen.
- **Rough size**: M — a judge adapter (likely reuses the hosted-provider seam) + prompt + ignore-list integration + cost controls. Consider sequencing before/with VLM-4 so its measure-gate is sharper.

### 5. BYOK (bring-your-own-key) provider mode
- **What**: tenant-supplied provider API keys with encrypted storage, budget controls, purge/export semantics, and third-party-terms disclosure.
- **Roadmap origin**: Phase 6 "BYOK decision memo after benchmark, not before."
- **Status**: **conditionally unplanned.** E20-11's disposition enum is `ship | benchmark_only | defer_byok | reject`; the decision memo currently states under `reject` "there is no BYOK follow-on task." So if E20-11 lands `reject`/`benchmark_only`, BYOK has **no successor plan**.
- **Why it matters**: BYOK is the usual path to shipping provider quality without the operator eating token cost; leaving it planless closes that door silently.
- **Rough size**: L — encrypted key vault, per-key budget/rate, subprocessor disclosure, retention semantics. Gate on E20-11 outcome; do not plan until the provider disposition is set.

## Recommended next step

Feed items 1–4 into `/scope` when the E20 workflow epic nears close (they are Phase 4/5 parity + eval depth). Hold item 5 until E20-11 records its disposition. None block the four in-flight branches.
