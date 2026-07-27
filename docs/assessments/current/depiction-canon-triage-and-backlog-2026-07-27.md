# Depiction-Canon Triage — Ranked Backlog

> **Metadata**
>
> - **Date**: 2026-07-27
> - **Input**: [`depiction-canon-fit-captioning-pipeline-2026-07-27.md`](depiction-canon-fit-captioning-pipeline-2026-07-27.md) (F1–F9)
> - **Canon**: `heuristics-canon-research` @ `v0.16.0-9-g1b1ddb8` — `lexicons/depiction.md`
>   (`ATTRIB-01..10`, `BOUND-01..05`), `lexicons/engineering.md`, `lexicons/ml-systems.md`,
>   `lexicons/accessibility.md`, `public/reasoning/` cards.
> - **Verified at**: `main` `41d9f591`, branch `feature/depiction-canon-eval-2026-07-27` `fbe90028`
> - **Status**: triage + proposal. No implementation. No gate decision.

---

## 1. Verification deltas — the eval's §6 ordering is wrong in one place

Three facts established by reading the code today. Each changes a priority.

### D1 — There are two prompt surfaces and nothing enforces their relationship

`scene/infrastructure/vlm/gpu_remote_adapter.py:28` `_SYSTEM_PROMPT` is textually
identical (whitespace-normalised) to `scripts/eval_harness/bakeoff.py:89`
`_PROMPT_V1_SYSTEM`. The v2 and v3 variants exist **only in the harness**.

The lockstep is a comment — `gpu_remote_adapter.py:23`, *"Keep in lockstep with
scripts/eval_harness/bakeoff.py (VLMRP-HARM-01)"* — and no test asserts it.
`scene/tests/test_eval_harness_pipeline.py:104-141` compares variants against
each other *inside* the harness; nothing compares the harness to production.

Consequences, in order of how much they move the plan:

- **F2 and F4 are candidate-prompt defects, not live production defects.** The
  production prompt contains no emotion instruction and no three-surface contract.
- **F1 *is* live.** The `"Weave the people's names and factual details it supplies
  into the description where they fit naturally"` clause is in the production
  `_SYSTEM_PROMPT`. It is the only tier-B finding with production exposure today.
- A prompt fix landed in `bakeoff.py` changes nothing that ships, and there is no
  mechanical path to promote a harness variant into production.

The eval's §6 opens with F2. It should open with the seam, then F1.

**Canon**: [PROV-09] prompt configuration is production lineage · [NAME-03] no lying
names · [REF-26] DRY is knowledge, not text · [TEST-15] prove the green can go red.

### D2 — The production prompt version label is wrong

`scene/config/settings.py:40` — `gpu_prompt_or_task_version` defaults to `"3"`
(`ACX_GPU_PROMPT_VERSION`) while the prompt text it labels is v1. That field is
stamped into `scene` rows and into the description cache key
(`scene/application/hashing.py`: `(tenant_id, image_hash, adapter, model_version,
prompt_or_task_version, context_hash)`).

Any cross-version quality comparison keyed on that field is mislabelled, and a real
promotion to v2/v3 cannot be distinguished from the current state by the stamp.

**Canon**: [PROV-09] · [NAME-03] · [PROV-01] every output walks back to its evidence.

### D3 — v3 has not shipped, so F4's window is open

No three-surface JSON path exists outside the harness; production returns
single-surface prose. The eval's *"do this before v3 ships to a tenant; afterwards it
is a contract break"* holds, and D1's fix is what makes that promotion mechanical
rather than a hand-copy.

---

## 2. Ranked backlog

Ranked by **impact × unblocking power ÷ cost**, not by canon tier. Tier is the canon's
severity and appears in the Canon column.

### P0 — do first; everything downstream is cheaper afterwards

| # | Task | Canon | Enforcement point | Cost | Mode |
|---|---|---|---|---|---|
| 1 | **DEPICT-0 — one prompt source, one parity test, an honest version stamp.** Extract the shared prompt text to a single module consumed by both `gpu_remote_adapter` and `bakeoff`; add a test that fails when they diverge; derive or assert `prompt_or_task_version` against the prompt actually shipped. | [PROV-09] [NAME-03] [REF-26] [REF-10] [TEST-15] | `system_prompt` | S–M | grok flock |
| 2 | **DEPICT-1 (F1) — `voice` on every context-pack entry** (`creator \| catalogue \| operator \| derived`); creator-tagged fields become quotable-only, never absorbed by the weave. Additive to a model that already sets `extra="forbid"`. | `ATTRIB-07` (B·d) `ATTRIB-02` (B·v) `BOUND-02` · [API-09] don't change it, add it | `context_pack_input` → `output_schema` | M | grok flock |

Rank 1 before rank 2 only because rank 2's prompt-side half has nowhere safe to land
until the seam is closed. The pack-side half of DEPICT-1 can start in parallel.

### P1 — cheap, deterministic, and they make P2 measurable

| # | Task | Canon | Enforcement point | Cost | Mode |
|---|---|---|---|---|---|
| 3 | **DEPICT-2 (F8) — inner-state-attribution counter** in `caption_metrics.py`. Report-only first. LIBSYN-1 §3.4 called this the highest-value safety signal; it is now canon-backed. | `ATTRIB-01` (B·d) · [EVAL-11] open-ended tasks need the right scorer · [EVAL-08] CACE · [TEST-15] | `eval_metric` | S | grok flock |
| 4 | **DEPICT-3 (F6) — agentless-passive / mutual-event detector.** Pure grammar, no model, no context, no aggregate. Same shape as the existing `_META_FRAMING_PHRASES` detector at `caption_metrics.py:39`. | `ATTRIB-08` (S·d) · [TEST-15] | `post_generation_check` | XS | grok flock |
| 5 | **DEPICT-4 (F2) — give emotion a bearer** in the v2/v3 prompt. *"her expression reads as anxious"* satisfies both `ATTRIB-01` and the ALTQ-1 *emotion legitimate* finding; *"she is anxious"* satisfies neither. Register, not silence. | `ATTRIB-01` `ATTRIB-03` · [EVAL-08] | `system_prompt` | XS | grok flock |

**Ordering correction.** The eval sequences F2 → F8. Reverse it. F2 is a prompt change
with no scored signal until F8 exists, which is exactly what [EVAL-08] forbids — and
F2 is not shipping today (D1), so nothing is bleeding while the counter lands first.

### P2 — land before the contract freezes

| # | Task | Canon | Enforcement point | Cost | Mode |
|---|---|---|---|---|---|
| 6 | **DEPICT-5 (F4) — split the v3 `caption`** into a grounded-inventory span and an attributed span. Cheap now, a contract break after v3 promotion (D3). | `ATTRIB-03` `ATTRIB-04` `BOUND-05` · [API-09] [API-10] interface is its own artifact | `output_schema` | M | grok flock |
| 7 | **DEPICT-6 — land `DescriptionRegister` in the contract** (`FORENSIC \| EDITORIAL \| INTERPRETIVE`), enforcement deferred. Canon's `attribute-claims-to-their-bearer` card is written in this vocabulary; retrofitting the enum later is a rewrite of every call site. | `ATTRIB-01` `ATTRIB-03` · card `attribute-claims-to-their-bearer` · [API-09] [REF-29] enum completeness | `output_schema` | M | grok flock |
| 8 | **DEPICT-7 (F9) — declared survival list for compression.** `_COMPRESS_SYSTEM_PROMPT` forbids new facts but never says what must survive; truncation is position-based and importance is not. The gist ≤125 bound and Must-Right presence gate are the attach points. | `A11Y-02` (B·w) · card `compression-is-selection-not-truncation` | `system_prompt` → `output_schema` | S | grok flock |

### P3 — needs a decision or a sizing, not an implementation

| # | Task | Canon | Why it is not a build task |
|---|---|---|---|
| 9 | **DEPICT-D1 (F3) — obligation class for the gravity flag** | `ATTRIB-05` `ATTRIB-04` `BOUND-03` · [RLSE-02] gates are not suggestions | Monotone-restrict is right for most sensitive classes and wrong for public atrocity imagery. Canon's distillation spec forbids averaging opposed instructions into a middle row — the pipeline carries **both**, partitioned by image class. Operator decision memo. |
| 10 | **DEPICT-D2 (F7) — roster withhold flag** | `ATTRIB-10` (S·e) `ATTRIB-05` | FIR confirmation answers *"is this who we think it is?"*, not *"may this person be named in public alt text?"*. The machine must not infer the second. Roster-entry flag honoured by the pack assembler; human sets it. |
| 11 | **DEPICT-S1 (F5) — size the race warrant/parity gate** | `ATTRIB-06` (S·v) · [EVAL-17] evaluate at the unit operations aggregates · [FAIR-01] [FAIR-02] | Parity is a property of a *pass*, not an image. The harness scores per-image only. Size the pass-level aggregate before promising the check. |

### P4 — program track (competes for the same slots; mostly operator-gated)

| # | Task | State |
|---|---|---|
| 12 | **VLM-6 Golden-150 curation** | Operator labor. Binding constraint on the FIR-6 gate *and* on every claim P1–P2 makes being measurable on a real corpus. Tenant `4ddf8f36` LIVE @ `:10018` — never dispose. |
| 13 | **FIR-5 merge-out** | `feature/fir-5` parks @ `9d8f5d13`; `check-remote` not yet run post-fix. Pre-merge gate + operator initiation. |
| 14 | **UXP-NET-2 merge-out** | Built + reviewed @ `7127e296`. Needs `make plan-accept`, LocalWP walkthrough, close-check. Packet `cont-20260723T002547Z-64302788`. |
| 15 | **FIR-6 S4–S6** | Blocked on 12 + 13 + operator gate decision. `feature/fir-6` parks green @ `c645a91c`. |
| 16 | **E21 epic-close gates** | `A11Y-22` per-page WCAG 2.2 AA scope declaration; `PROD-03`/`A11Y-23` scripted first-visitor + keyboard/SR walkthrough on the live demo. Unblocked. |
| 17 | **Housekeeping** | 11 stale `in_progress` rows make `get_handoff_state` ambiguous every session → `make task-reap`. Worktree teardown `feature/fbt-1` + `feature/gpu-lanes-scope` (~900MB). `stale_dev_temp_reap` degraded every `make context` (`ModuleNotFoundError: workbay_bootstrap`) — upstream REQUEST.md candidate. |
| 18 | **Deferred** | FIR-7 / FIR-8 / FIR-9 plans, FIR23-STACK, the 19-finding FIR tech-debt backlog, `_identity-cluster-list.scss` raw literals (sr-004). |

---

## 3. Execution protocol

Standing, for every task above.

1. **Implementation and mechanical work → remote grok flocks.** Parallel lanes, one
   slice per lane. Local Claude does judgment, triage, and final review only.
2. **Heuristics gate every phase.** Plan, implementation, and review passes each cite
   current canon rule IDs from `v0.16.0` and verify the ID exists before citing it.
   Depiction work additionally cites the `ATTRIB`/`BOUND` row it satisfies.
3. **Adversarial review by remote grok flock**, refute-by-default, per milestone.
4. **At least one local Claude adversarial review before any merge**, on top of the
   standard pre-merge gate (`handoff_close_check(enforce=True)`, zero open findings,
   fresh test evidence at HEAD).
5. **Every new check ships with a red-first proof** ([TEST-15]) — a vacuous assertion
   certifies nothing, and four of these tasks are detectors whose whole value is
   discrimination.

Known lane gotchas that apply here: copy the gitignored `scripts/remote_agent.sh` into
each lane worktree; `test_cmd` must be `uv run --extra dev pytest`; grok reviewers need
an inline-only preamble or they browse stale VM mirrors; verify every reviewer claim
against code before recording it as a finding.

---

## 4. Not doing

From the eval's `not_enforceable` set and its reject rationale. Recorded so none of it
is re-litigated.

- **`BOUND-04`** refuse restage / refuse erasure — tier-J judgment cut, both failure
  directions are harms. `human_gate` at most.
- **`ATTRIB-09`** enslaved person's name as primary entry — archival cataloguing; no
  archival tenant exists. Recorded so a future one does not rediscover it late.
- **The restraint/obligation tension** — carried whole and partitioned by image class,
  never averaged into a middle rule. This is why item 9 is a decision, not a default.
- **Institutional anti-racism work** — real, and outside per-record description
  mechanics.
- **Do not rebuild what exists**: the pipeline already enforces unconfirmed-faces-never-named,
  pixels-win-on-conflict, unaccounted-context-names-dropped, no-invented-specifics, the
  meta-framing detector, alt ≤125 chars, fabrication-rate-by-kind, context trigram
  overlap, the wrong-name trap, and two-arm context-obedience scoring
  (`name_ablation` + `distractor`) — which already satisfies the
  `context-obedience-is-a-separate-capability` card outright.

---

## 5. Re-evaluation after intake §10/§11 (2026-07-27, same day)

`docs/research/library-heuristics-intake-consolidation.md` — the complete intake
instruction surface — gained a §11 (Werner post-distillation findings and the
bound-term contract). Read together with §10 (proposed `depiction` lexicon) it
moves the top of §2's backlog. Canon re-checked at **v0.17.0** (was v0.16.0-9 at
first triage).

### 5a. §11e's canon-side claims are accurate — verified, not taken on trust

| Claim | Verified |
|---|---|
| `distilled/design/werner-nomenclature-of-colours.md` exists | yes, 22,677 bytes |
| Werner absent from `SOURCES.md` | yes — zero hits |
| Zero lexicon rows cite Werner | yes — zero hits across `lexicons/` |
| `FM-11` retired, never published | yes — `literature/HELD.md:69` |
| Colour stays in `design-aesthetics` `COL` | `COL-01..18` present; a normalisation row would be new |

### 5b. §10d's falsifiable test has resolved — and three families never shipped

§10d set the bar: *fewer than ~15 surviving rows ⇒ do not open the lexicon.*
`depiction.md` shipped with **exactly 15**: `ATTRIB-01..10` + `BOUND-01..05`.
It cleared the bar at the bar.

§10b proposed **five** families. Two exist. **`REG`, `ICON`, `FRAM`, `SEL` are
absent from every lexicon** (verified by prefix grep across `lexicons/`).

Consequence for this backlog — one item loses its canon warrant:

- **DEPICT-6 (`DescriptionRegister` enum)** was ranked as canon-adjacent. There
  is **no `REG` family**. Its warrant is this repo's own §3.3 of
  `cross-domain-bridges-and-caption-register.md`, an operator-reserved design
  call. It still ships — but it must not be reviewed as canon compliance, and no
  lane may cite a `REG-xx` rule. There is nothing to cite.
- **DEPICT-7 (F9)** keeps its warrant, but from `A11Y-02` (B·w) plus the
  `compression-is-selection-not-truncation` card — **not** from a `SEL` rule.
- F1–F8 are unaffected: every rule they cite (`ATTRIB-01..10`, `BOUND-02/03/05`)
  is shipped and real.

### 5c. The direction change — contract-first beats prompt-first

§3.4 of the bridges doc and §11c of the intake doc make the same argument
independently: **the parameter must exist in the contract from the start; the
behaviour lands later.** §3.4's "now, cheap, additive" tranche is *register enum
+ restrict-only gravity flag + inner-state-attribution counter*. §11c adds the
bound-term shape to the same tranche and gives the reason: *one contract change
now instead of a rewrite later.*

That merges four separately-ranked items into one slice:

| Was | Ranked | Now |
|---|---|---|
| DEPICT-1 (F1 `voice` on context-pack entries) | P0 | **DEPICT-C** |
| DEPICT-2 (F8 inner-state attribution counter) | P1 | **DEPICT-C** |
| DEPICT-6 (register enum + gravity flag) | P2 | **DEPICT-C** |
| §11c bound-term shape (`term`/`vocabulary`/`vocabulary_version`/`binding`/`delta`) | not ranked | **DEPICT-C** |

The merge is not bundling for convenience. F1's `voice` field and §11c's
`binding` field are **the same pattern** — non-visual assertions carry their
provenance in the data, not in prose. Shipped in separate slices they become two
incompatible provenance idioms inside one response body.

Revised P0, two independent lanes:

- **DEPICT-0** — prompt-lineage seam (single prompt source, parity test, honest
  `ACX_GPU_PROMPT_VERSION`). Unchanged by §10/§11. Nothing in the contract slice
  depends on it and vice versa, so the two run in parallel.
- **DEPICT-C** — the contract slice above. Carries the only tier-B finding with
  live production exposure (F1) and the only member of §3.4's "now" tranche with
  a canon rule behind it (F8 → `ATTRIB-01`).

### 5d. Two constraints that must be stated before DEPICT-C is built

- **Ship the shape with an empty provider registry.** §11c's own admission
  criterion — versioned **and** every term carries a public referent — is met by
  **none** of the named Phase-2 vocabularies today. Werner is `REFERENCE-ONLY`,
  absent from `SOURCES.md`, cited by zero rows; Iconclass and Getty are unwired.
  `binding: unbound` is the honest default at launch.
- **Do not build the `unbound must be zero in FORENSIC` check yet.** With no
  admissible provider it can never fire red. A green that cannot go red
  certifies nothing — [TEST-15]. Land the check in the same slice as the first
  admitted vocabulary, with a discrimination guard.

### 5e. Canon-side follow-ups this repo does not own

- §10 still reads as an open proposal; the lexicon shipped. The intake doc should
  record the outcome — opened at 15 rows, 2 of 5 families — so §10d stops
  reading as an undecided question.
- §11e's requested `COL` normalisation row in `design-aesthetics` needs a tooled
  ID (`tools/canon.py reserve`), a `SOURCES.md` entry, and `REFERENCE-ONLY`
  lifted for the positive half only. Canon-side work; not this backlog.
