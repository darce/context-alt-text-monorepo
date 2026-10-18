# Context-Fusion Caption Architecture (Anchor-Visual / Reconcile-Context / Synthesize) — Scope Note

> **Status:** Scope one-pager (decision input). Not an epic or task plan.
> **Date:** 2026-07-07
> **Proposed Task ID:** `E20-FUSION` (context-fusion caption architecture) · **Feeds:** E20 context-pack enrichment; sequenced **after E20-9 (context-pack contract)** and **E20-BRAND-A (`ContextPack.brands`)**; shares Stage 1 with **VLM-4**.
> **Source of truth:** [caption-context-enrichment-assessment-2026-07-05.md](../assessments/current/caption-context-enrichment-assessment-2026-07-05.md) §1–§3 (fusion contract) + §6 (gated eval); EVENTA / Hierarchical Multi-Modal Retrieval (arXiv 2606.18553); [identity-prose-merge-design-2026-06-15.md](../assessments/current/identity-prose-merge-design-2026-06-15.md) (E19-4a, shipped). Recommendations picked against [engineering-heuristics.md](../workbay/rules/engineering-heuristics.md).

---

## 1. Problem

Our describe pipeline has facts from two sources — **what the model sees** (VLM visual pass) and **what the tenant supplies** (`ContextPack`: identities, product, events/places, brands) — and today they are combined ad-hoc: context is injected and the identity-prose merge (E19-4a) reflows names into regions. The failure the assessment and EVENTA both name: **supplied text can "overpower" the pixels** — the model asserts context facts the image doesn't support (a name on the wrong person; an event/place stated as if visible), or the reverse, drops a supplied fact that *is* grounded. There is **no principled, staged, testable fusion contract** deciding *which* supplied facts attach to *which* visual evidence, and at what altitude (object-level vs caption-level). VLM-4 stops the model inventing facts; **this scope governs how *given* facts are faithfully woven in.**

## 2. MVP Scope

> **Heuristic cut (YAGNI):** formalize the **3-stage fusion control flow over the pieces we already have** (VLM visual pass, `ContextPack`, identity-prose merge) — **not** news RAG (we already have the tenant's facts; EVENTA's retrieval half is N/A) and **not** a trained fusion model. Smallest cut = a composition stage + a reconciliation rule, gated by the eval harness.

**The staged fusion contract (anchor-visual / inject-factual):**
1. **Stage 1 — Anchor (visual-in-isolation).** One VLM pass extracts **structured visual facts** (objects / attributes / spatial / legible-text) with **no `ContextPack` text applied**, so the visual prior is uncontaminated. *(This is the exact step VLM-4 borrows from EVENTA — factor it into one shared component; see §7 coupling.)*
2. **Stage 2 — Reconcile.** Match each `ContextPack` fact against the visual prior and assign an **attachment decision + altitude**: (a) *object-attachable* (a name whose face/region is detected → identity-prose merge places it; a brand whose logo is detected → names it there); (b) *caption-level* (an event/place fact with no direct visual anchor → weave as scene context, never asserted as visible); (c) *dropped/flagged* (a supplied fact that **conflicts** with the visual prior → pixels win, `review_reason` emitted). Policy gates (recognition-disabled, unconfirmed) still veto first.
3. **Stage 3 — Synthesize.** Compose the final description anchored to the visual prior, weaving only reconciled facts at their assigned altitude; run the existing identity-prose merge for name↔region reflow.

**Deliverables:**
1. A **fusion composition stage** behind the `DescriptionAdapter`/composition seam (ports & adapters — no per-adapter fusion logic), consuming visual facts + `ContextPack` → a described output with per-fact **attachment provenance** (object / caption / dropped + reason).
2. A **reconciliation rule** (deterministic first; the LLM-judge tier stays a stub) implementing pixels-win + altitude assignment.
3. A bake-off REPORT (acx-eval/v1): **staged fusion vs current ad-hoc injection** on the VLM-2B corpus — `Must-Right`, insertion rate, `Easy-Wrong`, plus a new **mis-attachment** count (fact placed on the wrong object / asserted-as-visible when not).
4. A decision memo: adopt / adopt-partial / reject, measured.

**Describe-eligibility input (WP 7.1):** honor WordPress 7.1's **"Mark as decorative"** flag — a decorative image is **skipped** by the fusion pipeline (no describe, no GPU spend); surface it as an explicit eligibility gate, not a silent empty caption.

## 3. Stated Assumptions

1. **Facts already arrive via `ContextPack`** — no external retrieval/RAG; Stage 2 reconciles supplied facts, it does not fetch new ones (heuristic: *YAGNI* — don't build retrieval we don't need).
2. **Deterministic reconciliation first** — the pixels-win + altitude rules are code, gated by the eval harness (heuristic: *measure, don't guess*); an LLM-judge reconciler is a later, separately-gated upgrade.
3. **Reconciliation (Stage 2/3) is cheap and runs on any tier**, but **Stage 1 as a *separate* visual-in-isolation pass ~doubles inference** (FUSION-PA-01, *tail-latency / capacity-multiplier*). So: on the **async GPU / Qwen tiers** Stage 1 is a dedicated pass; on the **fast Florence tier (~14 s interactive)** a second pass breaks the budget → derive visual facts from the **single existing caption** (or skip staged fusion on that tier). The tier decides Stage-1's form, not the contract.
4. **Stage 1 is shared with VLM-4** — the same visual-in-isolation pass; factor it once (heuristic: *coincidental vs real duplication* — real shared behavior). **Ownership (FUSION-PA-03):** whichever of VLM-4 / E20-FUSION ships first owns the shared visual-facts component; the other consumes it.
5. **Object-attachment is detector-backed only (FUSION-PA-02)** — Stage 2 can only attach a fact to an object that has a **detector**: identities via the identity-prose merge, brands via E20-BRAND-A. Arbitrary objects and events/places have **no visual anchor** → always caption-level. **No new grounding model is built here** (YAGNI).
6. **Depends on E20-9 landed** — Stage 2 consumes the E20-9 context-pack contract + `ContextPack.brands`; both must land first (FUSION-PA-03).
7. **Provenance is a contract field** — per-fact attachment (object/caption/dropped) is surfaced (mirrors `AdapterResult.context_sources`/`context_applied`), so WP + the eval harness can audit *why* each fact did/didn't land.

## 4. Not-Doing (explicit out-of-scope)

- **No external-document / news RAG** — EVENTA's retrieval + hierarchical article scoring; our facts are the `ContextPack` (heuristic: *YAGNI*).
- **No trained fusion model** — no Bridge, no LoRA synthesizer (EVENTA/CIAN/RE-VLM training paths are references only).
- **No LLM-judge reconciler in MVP** — deterministic rules first; judge stays a stub.
- **No generation-time faithfulness technique** — ensemble decoding / region proposals are **VLM-4**; this scope governs *supplied-fact* weaving, not model invention.
- **No new `ContextPack` fields** — consumes E20-9's contract + `ContextPack.brands` (E20-BRAND-A); does not define them.
- **No change to the identity-prose merge internals** (E19-4a shipped) — Stage 3 *calls* it.

## 5. Success Criteria

1. One committed acx-eval/v1 REPORT compares **staged fusion vs ad-hoc injection** on the VLM-2B corpus, re-score bit-identical.
2. Verdict is **measured**: staged fusion is adopted iff it lowers **mis-attachment** + `Easy-Wrong` **without** lowering `Must-Right`/insertion rate.
3. Every emitted description carries **per-fact attachment provenance** (object / caption / dropped + reason), auditable from the response.
4. A supplied fact that **conflicts** with the visual prior is dropped with a `review_reason` (pixels win) — proven by a corpus entry (e.g. the `mcm-planecrash` garden-picnic-vs-wreck case).
5. A **"Mark as decorative"** image is skipped (no describe), proven by a fixture.

## 6. Slice Outline (detail in the task plan)

1. **Stage 1 — shared visual-facts pass** (factored so VLM-4 reuses it) + its structured output.
2. **Stage 2 — reconciliation rule** (pixels-win + altitude + policy veto) with per-fact provenance.
3. **Stage 3 — synthesis** wiring to the identity-prose merge; describe-eligibility gate incl. "Mark as decorative".
4. **Mis-attachment labels + bake-off + decision memo** — author the corpus labels the mis-attachment metric needs (which supplied fact should attach to which object/altitude; extends VLM-2B's `present_identities`/`must_right` with event/place altitude labels — FUSION-PA-04), then bake-off staged fusion vs ad-hoc.

## 7. Heuristic-Driven Decisions (picked, not asked — veto any)

- **YAGNI** → control flow over existing pieces; no RAG, no trained model, no LLM-judge in MVP.
- **Coincidental vs real duplication** → Stage 1 visual-facts pass is **shared with VLM-4**, factored once (real shared behavior, not coincidental).
- **Ports & adapters + two hats** → fusion is a composition stage, not per-adapter logic; separate diff from VLM-4.
- **Measure, don't guess** → adoption gated on a new **mis-attachment** metric + the existing rubric.
- **Leaky abstraction / provenance** → per-fact attachment surfaced as a contract field, not hidden in prose.
- **Coupling-type triage** → sequences after E20-9 (`ContextPack` contract) + E20-BRAND-A (`ContextPack.brands`); developmental coupling to VLM-4 via the shared Stage-1 component.

## 8. Open Risks

- **Stage-1 sharing with VLM-4** creates a cross-scope component dependency — whichever lands first owns the shared visual-facts pass; the other consumes it (flag in both task plans).
- **Deterministic reconciliation may be too blunt** for event/place altitude decisions → the memo may recommend the LLM-judge reconciler as a fast-follow (separately gated).
- **Mis-attachment is a new metric** — needs corpus labels (which supplied fact *should* attach where); partly derivable from the VLM-2B `present_identities`/`must_right`, but event/place altitude labels may need authoring.
- **Applies across tiers** → must not regress the fast Florence path's latency (fusion is cheap, but Stage-1-as-a-second-pass on CPU is not free — measure).
