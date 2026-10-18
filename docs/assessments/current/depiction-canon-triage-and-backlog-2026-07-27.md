# Depiction-Canon Triage — Ranked Backlog

> **Metadata**
>
> - **Date**: 2026-07-27
> - **Input**: [`depiction-canon-fit-captioning-pipeline-2026-07-27.md`](depiction-canon-fit-captioning-pipeline-2026-07-27.md) (F1–F9)
> - **Canon**: pin **`v0.17.2`** / `4e099ded65ee33bc4db85dfd4c65409a0087a752`
>   (`canon/lexicons/`, `canon/literature/`, `canon/distilled/`).
>   §§1–9 were authored against earlier pins; §10a is the governing delta against
>   **`v0.17.2`**. Surfaces: `lexicons/depiction.md`
>   (`ATTRIB-01..10`, `BOUND-01..05` — **exactly 15 rule rows at v0.17.2**),
>   `lexicons/engineering.md`, `lexicons/ml-systems.md`, `lexicons/writing.md`,
>   `lexicons/accessibility.md`, `literature/HELD.md`. **No**
>   `canon/PROVENANCE.txt` — do not cite one.
> - **Verified at**: `main` `41d9f591`, branch `feature/depiction-canon-eval-2026-07-27` `fbe90028`
> - **Status**: triage + proposal. No implementation. No gate decision.
> - **Reading order caution**: §10 supersedes §9 on scope and §8b on the `FM-11`
>   citation. Read §10 before acting on §§8–9.

---

## 1. Verification deltas — the eval's §6 ordering is wrong in one place

Three facts established by reading the code today. Each changes a priority.

### D1 — There are two prompt surfaces and nothing enforces their relationship

`scene/infrastructure/vlm/gpu_remote_adapter.py:28` `_SYSTEM_PROMPT` is textually
identical (whitespace-normalised) to `scripts/eval_harness/bakeoff.py:89`
`_PROMPT_V1_SYSTEM`. The v2 and v3 variants exist **only in the harness**.

The lockstep is a comment — `gpu_remote_adapter.py:23`, *"Keep in lockstep with
scripts/eval_harness/bakeoff.py (VLMRP-HARM-01)"* — and no test asserts it.
`scene/tests/test_eval_harness_pipeline.py:104-145` compares variants against
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

**Canon**: [PROV-09] prompt configuration is production lineage · [TEST-15] prove
the green can go red · [REF-10] extract only what must change together.
([NAME-03] and [REF-26] are **not** load-bearing for DEPICT-0: the dishonest
stamp is a provenance/value defect, not a naming defect; REF-26's multi-format
trigger does not fire on same-format Python string copies — see
`DEPICT-0-prompt-lineage-seam-task-plan.md` Workflow Principles and Not-Doing.)

### D2 — The production prompt version label is wrong

`scene/config/settings.py:40` — `gpu_prompt_or_task_version` defaults to `"3"`
(`ACX_GPU_PROMPT_VERSION`) while the prompt text it labels is v1. That field is
stamped into `scene` rows and into the description cache key
(`scene/application/hashing.py`: `(tenant_id, image_hash, adapter, model_version,
prompt_or_task_version, context_hash)`).

Any cross-version quality comparison keyed on that field is mislabelled, and a real
promotion to v2/v3 cannot be distinguished from the current state by the stamp.

**Canon**: [PROV-09] · [PROV-01] every output walks back to its evidence · [TEST-15].
([NAME-03] not load-bearing — stamp lie is provenance/value, not a naming defect;
matches DEPICT-0.)

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
| 1 | **DEPICT-0 — one prompt source, one parity test, an honest version stamp.** Extract the shared prompt text to a single module consumed by both `gpu_remote_adapter` and `bakeoff`; add a test that fails when they diverge; stamp = selected `ProductionPrompt.lineage_version` only. **Deletes** `DescriptionSettings.gpu_prompt_or_task_version` and the `ACX_GPU_PROMPT_VERSION` env control outright (does **not** "make the env stamp honest" or repoint it as a settings mirror — DEPICT-0 Constraints / Slice 2 settings delete). | [PROV-09] [TEST-15] [REF-10] (load-bearing; matches DEPICT-0). **Not** [NAME-03] / [REF-26] — plan refuses both (stamp = provenance/value; REF-26 multi-format trigger does not fire). | `system_prompt` | S–M | grok flock |
| 2 | **F1 split — do not treat a single DEPICT-1 row as "F1 closed".** **(a) Service/contract half (this wave, DEPICT-1):** `voice` on speech-allowlist context-pack entries (`creator \| catalogue \| operator \| derived`); pure `partition_context_pack` so creator-tagged fields are quotable-only, never absorbable; boundary→partition voice-value proofs (including `ProductContext` / `IdentityContextItem`). Additive under `extra="forbid"`. **Does not** change production weave wording or wire partition into the adapter. **(b) Production-weave half (OUT of this wave, unowned — no plan file):** stop unmarked weave of creator-tagged fields in the shared production system prompt; render creator entries quoted/voice-tagged on the service pack path; REBIND-ONLY of post-DEPICT-0 `PRODUCTION_PROMPT` (never mutate frozen `.body`). Production consumer binding of the selected config follows DEPICT-0 section **Consumers:** (character-exact extract from DEPICT-0 Constructor / temporal-invariant / binding-form clauses under `Consumers:`; re-verify against DEPICT-0 after concurrent DEPICT-0 edits): Constructor **removes the free-string `prompt_or_task_version` parameter entirely** (today `gpu_remote_adapter.py:133` / assigned at `:143`) and **snapshots once**: `self._production_prompt = production_prompt()` then `self.prompt_or_task_version = self._production_prompt.lineage_version`. Payload system message at the site of today's `_SYSTEM_PROMPT` (`gpu_remote_adapter.py:182`) posts **`self._production_prompt.body`** — not a second call to `production_system_prompt()` / `production_prompt()` at describe time, and not a live re-read of module-level `PRODUCTION_PROMPT`. **Temporal invariant (load-bearing):** body and stamp are taken from the same snapshot object at the same instant (`__init__`), so rebinding `caption_system.PRODUCTION_PROMPT` after construction cannot produce a v2 body under a v1 stamp (or the reverse) on that instance. **Only permitted binding form for production consumers of the selected config:** the accessor functions (`production_prompt()` / `production_system_prompt()` / `production_prompt_or_task_version()`). Do **not** read `PRODUCTION_PROMPT.body` / `.lineage_version` at the call site via `from … import PRODUCTION_PROMPT`, and do **not** introduce a dedicated frozen body export. **Acceptance for (b):** rebind lands voice-honouring body + lineage together; service-path test proves creator speech is not absorbed unmarked; DEPICT-0 seam + DEPICT-1 (a) are prerequisites. **Harness `ContextPack.voice`** (`scripts/eval_harness/manifest.py`) is **also OUT / unowned** — neither (a) nor (b). | `ATTRIB-07` (B·d, oppressive-string subset only) · [API-09] shape only · [TEST-15]. **Not** `ATTRIB-02` / `BOUND-02` as F1 (a) warrants — both are *output* rules (who/by-whom; craft/staging mix); DEPICT-1 explicitly refuses them for input CMS provenance (`DEPICT-1` Slice 1 Canon + "No canon warrant"). | (a) `context_pack_input` (service unit) · (b) `system_prompt` + service render (unowned) | (a) M · (b) unowned | (a) grok flock this wave · (b) no owner |

Rank 1 before rank 2 only because rank 2's **(b) prompt-side half** has nowhere
safe to land until the seam is closed. The **(a) pack-side / contract half** of
DEPICT-1 can start in parallel. **Merging DEPICT-0 + DEPICT-1 + DEPICT-2 does
not close F1** — only F1 (a) is delivered in this wave; F1 (b) and harness
`ContextPack.voice` remain OUT and unowned until a future plan claims them.

### P1 — cheap, deterministic, and they make P2 measurable

| # | Task | Canon | Enforcement point | Cost | Mode |
|---|---|---|---|---|---|
| 3 | **DEPICT-2 (F8 + F6 + §3.1 density) — full Lane C gate, not counter-only.** **Slice 1:** inner-state-attribution counter (`ATTRIB-01`) in `caption_metrics.py`. **Slice 2:** agentless-passive / mutual-event / actorless-event-noun detector (`ATTRIB-08`, absorbs row 4 / DEPICT-3). **Slice 3:** verified signal-density ranking axis (playbook §3.1 / assessment §6b GPU-window gate) **and** Williams/C5 companion-axis resolution written into the module docstring (§6c). **Slice 4:** thin additive JSON emit of density + depiction hit lists from `report.py` (+ reserved `test_eval_harness_report_depiction.py`) so pure APIs are not orphaned — Lane C Carries / DEPICT-2 DoD. Report-only first (no hard gate on `gated_score`). LIBSYN-1 §3.4 called the safety signal highest-value; it is now canon-backed. | `ATTRIB-01` (B·d) · `ATTRIB-08` (S·d, v0.17.2 row text including "an incident") · [EVAL-11] open-ended tasks need the right scorer · [EVAL-08] CACE · [TEST-15] | `eval_metric` (+ Slice 4 `report.py` emit) | S–M | grok flock |
| 4 | **DEPICT-3 (F6) — agentless-passive / mutual-event detector.** **ABSORBED into DEPICT-2 Slice 2** — do not dispatch as a separate lane. Delivered by `DEPICT-2-depiction-metrics-task-plan.md` § Slice 2 (heading `### Slice 2: Agentless-passive / mutual-event detector (report-only)` — cite by heading; line range moves under concurrent DEPICT-2 edits), sole owner of `caption_metrics.py`. Same shape as the existing `_META_FRAMING_PHRASES` detector. Dual-lane collision with §6e Lane C if re-opened. | `ATTRIB-08` (S·d) · [TEST-15] | `post_generation_check` (via DEPICT-2 / Lane C) | — | **absorbed → DEPICT-2 Slice 2 / Lane C** |
| 5 | **DEPICT-4 (F2) — give emotion a bearer** in the v2/v3 prompt. *"her expression reads as anxious"* satisfies both `ATTRIB-01` and the ALTQ-1 *emotion legitimate* finding; *"she is anxious"* satisfies neither. Register, not silence. | `ATTRIB-01` `ATTRIB-03` · [EVAL-08] | `system_prompt` | XS | grok flock |

**Ordering correction.** The eval sequences F2 → F8. Reverse it. F2 is a prompt change
with no scored signal until F8 exists, which is exactly what [EVAL-08] forbids — and
F2 is not shipping today (D1), so nothing is bleeding while the counter lands first.

### P2 — land before the contract freezes

| # | Task | Canon | Enforcement point | Cost | Mode |
|---|---|---|---|---|---|
| 6 | **DEPICT-5 (F4) — split the v3 `caption`** into a grounded-inventory span and an attributed span. Cheap now, a contract break after v3 promotion (D3). | `ATTRIB-03` `ATTRIB-04` `BOUND-05` · [API-09] [API-10] interface is its own artifact | `output_schema` | M | grok flock |
| 7 | **DEPICT-6 — land `DescriptionRegister` in the contract** (`FORENSIC \| EDITORIAL \| INTERPRETIVE`), enforcement deferred. **ABSORBED into DEPICT-1 / Lane B** — do not dispatch as a separate lane. Delivered by `DEPICT-1-context-voice-and-register-contract-task-plan.md` Slice 2 (heading text: ``### Slice 2: `DescriptionRegister` on the **request** contract (enforcement deferred; no response echo)``) plus restrict-only gravity (DEPICT-1 Slice 3 / assessment §5c merge of DEPICT-6 into **DEPICT-C**). No `REG` family in canon (§5b); warrant is contract-shape + [API-09]/[REF-29], not a lexicon `REG-xx`. Retrofitting the enum later is a rewrite of every call site — that is why §5c pulled it forward. | `ATTRIB-01` `ATTRIB-03` · card `attribute-claims-to-their-bearer` · [API-09] [REF-29] enum completeness | `output_schema` (via DEPICT-1 request contract; no `responses.py` echo) | — | **absorbed → DEPICT-1 Slice 2–3 / Lane B** |
| 8 | **DEPICT-7 (F9) — declared survival list for compression.** `_COMPRESS_SYSTEM_PROMPT` forbids new facts but never names what must survive. **OUT of this wave / unowned** (zero hits in DEPICT-0/1/2). **Successor:** standalone **DEPICT-7** under `docs/tasks/depiction/`. **Trigger:** operator schedules compression/gist after DEPICT-0 merges. | `A11Y-02` (B·w) · card `compression-is-selection-not-truncation` | `system_prompt` → `output_schema` | S | **OUT of wave — unowned** |

### P3 — needs a decision or a sizing, not an implementation

| # | Task | Canon | Why it is not a build task |
|---|---|---|---|
| 9 | **DEPICT-D1 (F3) — obligation class for the gravity flag** | `ATTRIB-04` only among depiction co-cites (distress → literal inventory → *obligate_inventory* pole) · [STRAT-11] partition opposed goods. **Not** `BOUND-03` (frame-before-institution ordering) · **not** `ATTRIB-05` (source name/withhold). | Monotone-restrict fits most sensitive classes; wrong for public atrocity imagery — carry **both** poles by image class, never average. Operator decision memo. **OUT of this wave / unowned** (DEPICT-1 ships gravity *shape* only). **Successor:** DEPICT-D1 memo. **Trigger:** callers need class→disposition defaults beyond fail-closed `restrict`. |
| 10 | **DEPICT-D2 (F7) — roster withhold flag** | `ATTRIB-10` (S·e) `ATTRIB-05` | FIR confirmation ≠ public-naming permission. Human sets roster withhold; pack assembler honours it. **OUT of this wave / unowned** (no DEPICT-0/1/2 delivery). **Successor:** **DEPICT-D2** plan. **Trigger:** identity-pack work must distinguish public-naming withhold from FIR confirmation. |
| 11 | **DEPICT-S1 (F5) — size the race warrant/parity gate** | `ATTRIB-06` (S·v) only — warrant **and** white/BIPOC parity when race is used. **Not** [FAIR-01]/[FAIR-02] (ML cohort/intersectional *error* tables, not caption race-descriptor parity). | Parity is a property of a *pass*, not an image. Harness scores per-image only — size the pass-level aggregate first. (Not [EVAL-17]: multi-observation pooling for identification matchers.) |

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
moves the top of §2's backlog. Canon re-checked at **v0.17.2** @ `4e099ded65ee33bc4db85dfd4c65409a0087a752`
(commit pin verified via git rev-parse; no `canon/PROVENANCE.txt` — see §10; was v0.16.0-9 at first triage).

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
- **DEPICT-7 (F9)** keeps warrant from `A11Y-02` + `compression-is-selection-not-truncation` (not a `SEL` rule) but is **OUT of this wave / unowned** — see §2 row 8 successor/trigger.
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

- **DEPICT-0** — prompt-lineage seam (single prompt source, parity test, stamp =
  selected `ProductionPrompt.lineage_version`). **Deletes**
  `DescriptionSettings.gpu_prompt_or_task_version` and the
  `ACX_GPU_PROMPT_VERSION` env control outright — does **not** make that env
  stamp "honest" or retain it as a settings mirror (DEPICT-0
  `## Constraints` hard-boundary delete of `settings.py` field; Slice 2
  settings delete bullets under the plan's adapter/settings work). Unchanged
  by §10/§11 as a parallel lane. Nothing in the contract slice depends on it
  and vice versa, so the two run in parallel.
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

## 6. Re-evaluation against the orchestrator playbook (same day)

`docs/runbooks/fir-captioning-orchestrator-playbook.md` governs the FIR and
captioning tracks and was not in scope at first triage. It carries a do-not-do
list that gates work this backlog assumed was free, and a C7 card that §11c
generalises. Both checked against code.

### 6a. Playbook status is half-stale — verify before dispatching §6's list

| Playbook item | Claimed | Actual |
|---|---|---|
| §3.2 context arm + obedience scoring | open, "cheap only while Slice 1 is open" | **LANDED.** `bakeoff.py:574` `name_ablation`, `:582` `context_distractor`, `:251` `_inject_distractor`. Shipped by ALTQ-1. |
| §3.1 signal-density metric | open | **NOT LANDED.** `caption_metrics.py` has `score_caption`, `insertion_rate`, `name_precision`, `wrong_name_image_rate`, `score_hallucination`, `fabricated_fact_rate`, `fabrication_by_kind`. No facts-per-100-words, no density axis. |

#### §6a claim — do not re-commission §3.2

§6's suggested dispatch #2 would re-commission built work. Fix the playbook
before it is handed to a lane.

### 6b. The GPU window has a second, cheaper gate than curation

#### §6b claim — §3.1 is the last unlanded GPU-window gate

The do-not-do list says: *"Do not run the GPU window before §3.1 and §3.2
land."* §3.2 has landed. **§3.1 is the last unlanded gate**, and it is CPU-only,
local, and small. §2 of this doc ranked VLM-6 Golden-150 curation as the binding
constraint on the eval-metric items; it is not the only one, and it is not the
cheapest. Signal density promotes out of the P4 program track.

### 6c. A live contradiction the bake-off ranking depends on

#### §6c problem — Williams length policy vs C5 verbosity risk

`caption_metrics.py:8-10` states the harness's chosen policy: *"No hard length
cap — Williams et al.: longer descriptions score higher; penalize missing
content."* Playbook §3.1 states the opposite risk from card **C5**: *"every
quality metric it does measure is length-correlated ... the bake-off as written
will rank the most verbose candidate highest."*

#### §6c claim — Williams/C5 resolution (companion axes)

They are reconcilable, but only if someone writes down how: **Williams governs
the gate (do not cap length, do not penalise a long description for being long);
C5 governs the axis (do not reward verbosity — score facts per word).** Both
hold simultaneously if density is added as a *separate* report axis rather than
as a length penalty. Nothing currently records that. Until it does, two
governing documents point the ranking in opposite directions and whichever lane
implements §3.1 will pick one by accident.

### 6d. C7 extends §3.1 — it does not gate it

Playbook §3.5 says C7 *"feeds directly into §3.1's 'verified' definition."* §11c
generalises C7's binding into the bound-term shape; §11e confirms C7's
normalisation half is sourceable and its rejection half is not.

#### §6d claim — C7 extends §3.1; it does not gate the GPU window

Chain: **bound-term shape → C7 → §3.1's verified set → GPU window.** But the
coupling is *extension*, not blocking — §3.1's "verified" means checkable
against the image or a trusted source, and controlled colour is one class of
such term. §3.1 must therefore land with an **extensible** verified-term
predicate, or it is reworked when C7 arrives. That is the only design constraint
the chain imposes.

Per §11d, C7 splits by register when it is built: Werner names in `FORENSIC`
(reproducibility is the point), a common-language colour set in `EDITORIAL` (the
consumer is a screen-reader user, not a mineralogist), same `binding` semantics
both sides. And per §11a the wording is **refer-in, not refuse** — the playbook's
":219 out-of-set terms degrade to the nearest in-set term" is already correct and
needs no rewrite, only that label.

### 6e. Dispatch shape — file ownership, not just task ownership

Playbook §5 already states the operator's standing protocol (mechanical work to
remote grok lanes, judgment and review local, `/review-parallel` with a remote
reviewer at milestones, cite only verified canon IDs). §3 of this doc restates
it; the playbook is its source.

What §5 does not state is **file ownership**, and this backlog needs it: the F8
inner-state counter and the §3.1 density metric both land in
`caption_metrics.py`. Two concurrent lanes mutating one file will conflict and
raise phantom review alarms. Revised fan-out, no file collisions.

**Partition falsifiability (load-bearing):** each lane's Owns column is an
**enumerated production/test code-path set** (not a directory prefix), re-derived
from DEPICT-0/1/2 `## Constraints` (see rows below). **When this table and a
plan disagree, the owning plan's `## Constraints` is normative for that lane's
implementers** — this table is a wave-level collision summary and must not be
looser than the plan; any extension amends the plan Constraints **and** this
table in the same change. **Scope:** code paths only; planning docs sit outside
the collision oracle.

#### §6e ownership table

| Lane | Owns (**enumerated** hard path set — re-derived from that plan's `## Constraints`; plan wins on conflict) | Carries |
|---|---|---|
| **A — DEPICT-0** | **Closed set** = DEPICT-0 `## Constraints` "Lane A file ownership" bullet (paths under `apps/prototype-description-service/`; table lists the service-relative form): `scene/infrastructure/vlm/gpu_remote_adapter.py`; `scripts/eval_harness/bakeoff.py`; `scene/config/settings.py` (**delete** `gpu_prompt_or_task_version` / `ACX_GPU_PROMPT_VERSION` — not "make honest"); `scene/interface_adapters/http/deps.py` (**only** the one-line drop of free-string `prompt_or_task_version=` once the adapter rejects free-string stamp kwargs); **exactly one** new shared-prompt module `scene/prompts/caption_system.py` (plus package `__init__.py` only if the package does not already exist); **exactly these five test surfaces** — `scene/tests/test_prompt_lineage_seam.py` (new), `scene/tests/test_gpu_remote_adapter.py`, `scene/tests/test_description_profiles.py`, `scene/tests/test_settings.py`, and — for `scene/tests/test_eval_harness_pipeline.py` — **only these named test functions** (closed set over **function names**, not an open assertion filter over the file path): `test_v1_variant_is_the_unchanged_baseline_prompt`, `test_selected_variant_reaches_system_message`. Edits to any other function in that file are out of scope; adding a new test function there for lineage/lockstep requires naming it in DEPICT-0 Constraints **and** this row first. **Collision rule (matches DEPICT-0):** any additional production or test path **or** any additional named test function in a shared file requires amending DEPICT-0 `## Constraints` **and** this row before edit. | prompt-lineage seam; stamp = selected `ProductionPrompt.lineage_version`; **delete** free-string env stamp ([PROV-09] [TEST-15] [REF-10]) |
| **B — DEPICT-C / DEPICT-1** | **Closed set** from DEPICT-1 `## Constraints` "File ownership" (exact files named by plan's "including only"; residual "co-located under schemas/" open prose is DEPICT-1's to close): `scene/interface_adapters/http/schemas/requests.py`; `scene/interface_adapters/http/schemas/context_contract.py` (new; sole new schema helper); domain `StrEnum`s in `scene/domain/description.py`; **exactly four tests** under `scene/tests/`: `test_context_pack.py` (sole editor this wave for DEPICT-1 voice edits), `test_context_voice_contract.py`, `test_description_register_contract.py`, `test_gravity_contract.py` (last three new, Lane B sole). **Does not own** Lane A paths, `caption_metrics.py`, `responses.py`, `schemas/__init__.py`, `visual_facts_service.py`, `packages/shared-contracts/…`, or `manifest.py`. **Collision rule:** fifth test or extra schema file → amend DEPICT-1 Constraints **and** this row first. | F1 (a) `voice` + partition, register enum (**absorbs DEPICT-6**), restrict-only gravity. **Contract only.** (Bound-term withdrawn §10g.) |
| **C — METRICS / DEPICT-2** | **Closed set** = DEPICT-2 `## Constraints` "Owned paths only" exact set: `scripts/eval_harness/caption_metrics.py` (**sole owner**); `scene/tests/test_eval_harness_caption_metrics.py`; and (Slice 4 only) `scripts/eval_harness/report.py` plus the **reserved** report-emit test `scene/tests/test_eval_harness_report_depiction.py`. No edits under any other path (including no `test_eval_harness_pipeline.py`). **Collision rule:** no fifth path without amending DEPICT-2 Constraints **and** this row. Paths relative to `apps/prototype-description-service/`. | **F8** inner-state attribution counter (`ATTRIB-01`); **F6** agentless-passive / mutual-event / actorless-event-noun detector (`ATTRIB-08` three disjuncts, DEPICT-2 Slice 2 — absorbs former P1 item 4 / DEPICT-3); §3.1 signal density; §6c's Williams/C5 resolution in the module docstring; **Slice 4 report emit** of new fields (Lane C Carries / DoD; GPU-window *gate* remains §6b §3.1 density + Williams/C5 from Slice 3) |

#### §6e claim — Lane C unblocks the GPU window

Lane C is the one that unblocks the GPU window. Lane B is the one that must not
be deferred, because its cost grows with every call site. Lane A is independent
of both.

> **`responses.py` unowned this wave** in DEPICT-0 and DEPICT-1 (heading cites
> only: each plan's `## Constraints` unowned / do-not-edit bullets, DEPICT-0
> `## Contract and Boundary Impact` / `## Related Files` response rows, DEPICT-1
> **Not edited by this lane** response-contract row). Lane B disclaims it above.
> Any lane that needs it must claim it in its Constraints **and** this table first.

## 7. Reflow after intake §11c-i (FCA) — same day

§11c-i replaces "what does `nearest` mean" with a derivation from the source's
own component-part table, read as a formal context (Wille 1982). It changes two
of §5d's guard rails and adds a lane. Checked against
`distilled/design/werner-nomenclature-of-colours.md` and the corpus.

### 7a. The blocking objection dissolves — partially, and for a sourced reason

§5d said: ship an empty provider registry, and do not build the
`unbound must be zero in FORENSIC` check, because no vocabulary is admissible and
the check could never fire red ([TEST-15]). §11c-i removes half of that — Werner
now has a computable `nearest`/`delta` needing no second source.

But **Werner is admissible per-term, not wholesale**, and §11c's own bar is why.
The bar is *versioned **and** every term carries a public referent*. §11d states
the hand-coloured plate does not survive as text, so the surviving public
referent is the tri-kingdom annex — and those are filled in only "as far as the
author has been able to fill them up" (L00113, quoted in the distillation §
*Tri-kingdom annexes*). Partial by the author's own note.

⇒ The provider registry ships as a **per-term admissibility table**, not a
boolean per vocabulary. Forced by the source, and better than either option §5d
offered.

### 7b. Two overstatements in §11c-i that are implementation-relevant

Neither breaks the derivation. Both break it if quoted as a spec.

- **"a complete binary object × attribute table, present in the text, requiring
  no encoding decisions."** The distillation's catalogue verdict reads: *"Each
  entry **typically**: number, name, composition from other named colours"*
  (`ch-1-catalog`). *Typically*, not universally — and it is prose, not a table.
  Turning "snow white with a little crimson red" into a binary incidence row
  requires stated rules: are quantity qualifiers dropped, does "a little" set
  membership, what happens to an entry with no composition clause. **Those are
  encoding decisions.** Made silently, they are precisely the unattributed layer
  §11d exists to prevent — the hazard arrives by a different door than sRGB.
- **"110 objects against roughly 20 attributes."** The attributes are
  *"composition from other named colours"* (`ch-1-catalog`) plus the five
  modifiers and the tingeing set (L00111). The attribute set is therefore closer
  to the standards themselves than to 20. Immaterial to feasibility — 110 × ~115
  binary is still milliseconds — but the sizing figure should not be written
  into a plan as a spec.

⇒ **Version-pin the formal context, not just the lattice.** `vocabulary_version`
must cover a per-tint provenance table — composition present y/n, parse rule
applied, annex referent present y/n. Only then is the "deterministic and
diffable" claim in §11c-i true of the thing that actually varies.

### 7c. The empty intent is the discrimination guard

A tint with no recorded composition has an empty intent. It can bind `exact`
when the observed term matches its name, but it can **never** be a `nearest`
target carrying a meaningful delta.

That is the guard §5d said was missing. The check becomes:
`unbound` is zero **over the admissible subset**, and a term outside that subset
is flagged, never silently emitted. It can now fire red — an inadmissible term
reaching a FORENSIC caption is a real, reachable failure. **§5d's "do not build
it yet" relaxes to "build it scoped to the admissible subset."**

### 7d. FCA has no canon warrant — treat it exactly like `REG-xx`

`formal concept`, `concept lattice`, `Duquenne`, `Guigues`, `Wille` return
**zero hits** across `lexicons/`, `SOURCES.md`, and `distilled/`.

No lane may cite an FCA rule ID; there is none. The derivation is justified from
the source text and from Wille directly, in-plan. If it becomes load-bearing,
that is a canon-side intake request for a distilled FCA source — the mirror of
§11c-i being a request back to this repo.

### 7e. The literal catalogue is in neither repo

The distillation summarises the catalogue; it does not contain it. Per the §7a
egress rules the literal extract was not retained. The source is
`/Volumes/Chimay/___Books/400-Design-and-Visual-Arts/Colour/Werner's
Nomenclature of Colours - Adapted to Zoology, - Patrick Syme.epub`; the
`_graph/books/` sibling `.md` is a 27-line metadata card, not text.

**Lane D step 0 is re-extracting the 110-entry catalogue with per-entry
composition, under the same egress rules.** Not free, and not currently on
anyone's list.

### 7f. Lane D — WERNER-FCA. Unblocked, not promoted.

| Lane | Owns | Status |
|---|---|---|
| **D — WERNER-FCA** | new provider module + generated static table + its provenance record | **Ready when a slot frees.** No file overlap with A, B, or C. |

It stays behind Lane B on §11c's own argument — *shape now, behaviour later*.
What changed is that it moved from *blocked pending an admissible vocabulary* to
*buildable*. Do not read that as a promotion.

### 7g. Two doors §11c-i closes — keep them closed

- **Duquenne-Guigues implication basis over eval output.** §11c-i's own verdict:
  *"Worth one afternoon as a post-hoc diagnostic against a real eval run; not
  worth a component."* It does not enter the lane structure. The caveat is
  self-stated — implications are exceptionless, so noisy eval data yields few or
  none, and the relaxed version is ordinary itemset mining with FCA as framing.
- **FCA does not apply to FIR.** Detection, embedding and matching are
  continuous and compared by cosine (FIR-3's gate is `≥ 0.999`); a formal context
  is binary, so applying FCA means thresholding away the metric that does the
  work. Roster record linkage is a genuine formal context but is already assigned
  to `christen-data-matching` (§2d). Both recorded here so neither is reopened.

## 8. Colour-name APIs assessed; §7e corrected

### 8a. Correction to §7e — re-extraction is pinned and verified, not open-ended

§7e claimed the literal catalogue "is in neither repo" and that re-extraction was
"not free, and not currently on anyone's list." The first half is true only in
the trivial sense; the framing was wrong.

- The books in `/Volumes/Chimay/___Books/` **are the complete originals**.
  `_graph/` is a derivative metadata artifact, not the book.
- `literature/extraction-manifest.json[124]` pins the extraction completely:
  `source_sha256: 2790d75d…b57631`, `source_bytes: 7508006`,
  `extracted_chars: 32233`, `extractor: "stdlib-epub"`, `extracted: 2026-07-26`,
  3 chapters.
- **The epub's SHA-256 was recomputed and matches the manifest exactly.**

⇒ Re-extraction is *deterministic, provenance-verified, and small* — 32,233
characters for the entire book. The `L00109`/`L00115` line references throughout
§11 are stable against that pinned extract. **Lane D step 0 is re-running a
named extractor against a SHA-matched file**, not a research task. Revise the
cost accordingly.

### 8b. `meodai/color-name-api` — yes for one specific slot, no for the one it looks like it fills

MIT, self-hostable (Dockerfile + compose), CIEDE2000 ΔE in LAB with a VP-tree
index, serving several lists including a **`basic` list of 21 colours**.

**It cannot supply `binding` for FORENSIC.** Its mechanism is nearest-by-numeric-
distance. Amended §11d: a numeric mapping, if added, is *"for rendering or
clustering, **never for `binding`**."* Adopting ΔE as the binding mechanism walks
straight into the constraint that hazard names. *(Corrected per §10b: `FM-11`
is retired canon and carries no warrant — the hazard is real, the ID is not
citable. See §10c.)*

**It fails §11c's admission bar — on the versioning half, not the referent
half.** The bar is *versioned **and** every term carries a public referent*.

- *Referent*: **it beats Werner here.** Every term carries a hex — public,
  exactly reproducible, and it survives as text, which §11d says Werner's
  hand-coloured plate does not. Worth stating plainly.
- *Versioned*: the endpoint is `/v1/`; the **source data carries no published
  version**. §11c's own justification for `vocabulary_version` is that an
  unversionable vocabulary "cannot be diffed or re-scored." Self-hosting and
  pinning a dataset commit manufactures a usable version, but pinning a
  dependency is not the publisher versioning the vocabulary. Honest label:
  **pin-able, not published-versioned.**

**No structured attributes** — name↔hex plus computed colour values, "no
hierarchical relations or categorical metadata." So there is no `delta` except a
float. §11c-i's achievement is a delta that reads as Werner's own *incline
towards* / *intermediate* / *fall or pass into* — auditable in kind, not just in
magnitude. A ΔE number tells you *how far*, never *in what respect*, and §11c's
second bullet ("makes degradation observable") wants the latter.

### 8c. What it does solve: the slot §11d left empty

§11d requires *"a common-language colour set in `EDITORIAL`"* and names none.
**The 21-colour `basic` list is that set.** Right size for a screen-reader
consumer, close to the Berlin & Kay basic terms, and it ends the open question.

The large lists (NTC, XKCD, Wikipedia, ~30k names) are **worse than useless
here**: "Fuzzy Wuzzy Brown" is no more readable than "Skimmed-milk White", and
crowd-aggregated names carry no per-term provenance. Size is the feature, and
only the small list has it.

**Do not import the API's algorithm along with its list.** §11d requires *"same
structure, same `binding` semantics, two emission vocabularies."* A readable
attribute-set delta on the FORENSIC side and an opaque float on the EDITORIAL
side is two semantics, not one.

The resolution is already licensed by §11d: use CIEDE2000 **offline, at build
time**, to cluster observations onto the 21 basic terms; emit an attribute-set
delta at runtime. That is *clustering*, which §11d permits, not *binding*, which
it forbids. With 21 terms the component-part context is small enough to author
and source directly.

### 8d. `joshbeckman/thecolorapi` — skip

Dominated by the above on every axis that matters (maintenance, self-hosting,
metric transparency, list granularity). No reason to evaluate further.

### 8e. Net effect on the lanes

| Lane | Change |
|---|---|
| **D — WERNER-FCA** | Step 0 re-costed *down* (§8a: pinned 32k-char extraction, SHA verified). FORENSIC binding unchanged — Werner + FCA. |
| **D′ — EDITORIAL colour set** | New, small, and now *specified*: vendor the 21-term `basic` list self-hosted, pin the dataset commit, author its component-part context, use ΔE at build time only. Closes §11d's open question. |

Neither promotes above Lane C or B. Both are behaviour; §11c's shape-now argument
still orders them last.

## 9. Lane D and the description pipeline — retire the vocabulary, keep the method, swap the source

Question put directly: does Lane D work for captioning and scene description, or
should it be retired from the description pipeline?

**Answer: retire *Werner* from the description pipeline. Keep the *method*.
Rebuild Lane D on ISCC–NBS, which the same API already serves.**

### 9a. Nothing in the pipeline consumes a colour term today

Verified across `apps/prototype-description-service/scripts/eval_harness/` and
`scene/`: 63 matches for `colou?r`, **all** of them either report-builder CSS or
`corpus_inventory.py`'s `flat_color_coverage` — top-N pixel share after 5-bit
quantization, a chart/screenshot detector that never names a colour.

- **No VLM prompt asks for colour.** Not in `_PROMPT_V1/V2/V3`, not in
  `gpu_remote_adapter.py:28`.
- **No metric scores colour.** `caption_metrics.py` has no colour axis.

Lane D currently has **zero consumers**, built or wired.

### 9b. Its specified consumer is real but two gates away

The register table gives `FORENSIC` — and only `FORENSIC` — *"controlled-
vocabulary colour and object terms."* §3.4 phasing puts *"controlled colour
vocabulary (Werner) … wired as Phase-2 providers"* in the **Next phase**, behind
the contract that Lane B has not landed.

So Lane D is correctly specified and correctly sequenced *last*. That is not a
reason to retire it. The reasons below are.

### 9c. Werner is wrong for the registers users actually receive

`EDITORIAL` is the default; `INTERPRETIVE` sits above it. Werner's terms are
*Skimmed-milk White*, *Arterial Blood Red*, *Gamboge Yellow*, *Ash Grey*. As
emitted alt text these are **less** accessible than plain language — the same
objection §8c raised against the 30k crowd-sourced lists applies with full force
to a 205-year-old naturalist's vocabulary.

⇒ **Werner must never be an emission vocabulary in `EDITORIAL` or
`INTERPRETIVE`.** Record this as a boundary, not a preference.

Werner is a *specimen* vocabulary — built for describing minerals, plants and
animals against a hand-coloured plate. That is the photography/cataloguing lane
moved off accessibility in `41d9f591`, and it is where Werner belongs.

### 9d. ISCC–NBS dominates Werner on every axis §11c cares about

`api.color.pizza` ships `nbsIscc` — **267 terms, CC0**, "the ISCC–NBS system of
color designation based on 12 basic color terms." Live-verified: `Vivid Pink`,
`Strong Pink`, each with hex + LAB.

| §11c requirement | Werner | ISCC–NBS |
|---|---|---|
| **Versioned** | none | **NBS Special Publication 440 (1976)**, consolidating the 1955 and 1965 editions — a standards-body publication with editions |
| **Public referent per term** | 1821 hand-coloured plate; does not survive as text | **Munsell blocks** (published, reproducible) + hex/LAB per term |
| **Attributes without encoding decisions** | overstated — composition appears *"typically"*, in prose (§7b) | **attributes are in the name**: 20 documented modifiers × 29 hue terms, compositional by construction |
| **Readable `delta`** | *incline towards / intermediate / fall or pass into* | modifier steps — "one lightness step", "adds a grayish component" |
| **Register split** | none; unrelated to any common-language set | **nested levels: 13 / 29 / 267** |

The modifier set is published and closed: *vivid, brilliant, strong, deep, very
deep, very light, light, moderate, dark, very dark, very pale, pale/light
grayish, grayish, dark grayish, blackish*, plus the `-ish white / -ish gray /
-ish black` neutral forms.

Two consequences worth stating plainly:

1. **It repairs §11c-i rather than retiring it.** §11c-i claimed Werner supplies
   *"a complete binary object × attribute table, present in the text, requiring
   no encoding decisions."* §7b showed that is false of Werner. **It is true of
   ISCC–NBS** — parsing *"Dark Grayish Yellowish Brown"* into attributes is a
   lookup, not a judgement. The claim was right about what was needed and wrong
   about where to get it.
2. **It may make the lattice derivation unnecessary.** If names are compositional
   by construction, the system *is* already a structured vocabulary; FCA becomes
   a **validation** tool ("does the lattice match the published blocks?") rather
   than the derivation mechanism. Simplification, not loss. Note the naming is
   *constraint-based* — there is no *brilliant brown*, no *very deep pink* — so
   the 267 are **not** a naive cross-product and the attribute table has real
   gaps. Those gaps are what make the lattice informative.

### 9e. This supersedes §8c's `basic`-21 recommendation

§8c proposed meodai's 21-term `basic` list for the `EDITORIAL` slot. **Withdraw
that as the primary option.** `basic`-21 and Werner-110 are unrelated
vocabularies with no shared structure, so `delta` would mean something different
in each register — the exact failure §11d forbids (*"same structure, same
`binding` semantics, two emission vocabularies"*).

**ISCC–NBS Level 1 (13 terms) for `EDITORIAL`, Level 3 (267) for `FORENSIC`**
gives one vocabulary, one attribute decomposition, one `binding` semantics, two
emission granularities. `basic`-21 remains a fallback if the Level-1 set proves
too coarse in practice.

The §8b findings stand unchanged: ΔE stays out of `binding`, permitted at build
time for clustering only; and cite **SP 440** as `vocabulary` — the API is a
convenience carrier of 267 centroids, not the authority. Pin the dataset commit.

### 9f. Revised Lane D

| | Before | After |
|---|---|---|
| **Vocabulary** | Werner 110, re-extracted from epub | **ISCC–NBS 267**, CC0, already machine-readable |
| **Step 0** | re-run pinned extractor (§8a) | **none** — fetch and pin |
| **Registers** | FORENSIC only, no EDITORIAL answer | **both**, via nested levels |
| **FCA role** | derive the lattice | **validate** it against published blocks |
| **Werner** | the deliverable | **out of the description pipeline**; belongs to the photography/cataloguing lane |

Still last in priority — it is behaviour, and §11c's shape-now argument still
orders Lane B and Lane C ahead of it. But it is now **cheaper, better sourced,
and answers both registers instead of one.**

§8a's re-extraction finding stays valid and stays useful — for the photography
lane, not for captioning.

## 10. Reflow against re-ingested canon (bundle pin `v0.17.2`)

Canon pin **`v0.17.2`** @ `4e099ded65ee33bc4db85dfd4c65409a0087a752`. Earlier triage text that
named intermediate describe-strings (`v0.17.0-8-g0264a38`,
`v0.17.0-11-ga238620`) is superseded by this pin. `canon/PROVENANCE.txt` does
**not** exist in the bundle — plans that cite it are citing a non-existent file.

### 10a. What actually moved through `v0.17.2` (depiction surface)

Verified by opening `canon/lexicons/depiction.md` at the bundle pin (not by
restating an intermediate commit note):

- **`ATTRIB-08` rule row was rewritten — not "prose only".** Definition anchor
  remains `canon/lexicons/depiction.md:80` (`ATTRIB-08<a name="attrib-08"></a>`).
  The **row text** at v0.17.2 reads: an agentless passive, a mutual-event noun,
  **or an event noun that carries no actor** ("a clash", **"an incident"**,
  "were killed"). This is the load-bearing F6 warrant Lane C / DEPICT-2 Slice 2
  dispatches on. A section-2 or §10a reader that treats depiction.md as
  preamble-only drift will under-specify the agentless / mutual-event /
  actorless-event-noun detector.
- **Preamble is a source-provenance paragraph**, not a route-only note. Lines
  26–32 name Sontag (*On Photography*, *Regarding the Pain of Others*), Berger
  (*Ways of Seeing*), Azoulay (*The Civil Contract of Photography*), A4BLiP
  (*Anti-Racist Description Resources*), and Barthes (*Image Music Text*) as the
  rows' held sources.
- **Rule-row count is still exactly 15** (`ATTRIB-01..10`, `BOUND-01..05`) —
  §5b's "exactly 15 rows" conclusion is unchanged. Families `REG`, `ICON`,
  `FRAM`, `SEL` remain absent.
- Intermediate pin label `v0.17.0-11-ga238620` (commit `a238620`) is a pre-tag
  describe string; `git describe --tags a238620` resolves to **v0.17.1**. Do not
  treat that string as a release label for F6 warrant text — implement against
  **v0.17.2** row wording above.

All 15 depiction IDs verified present at the bundle pin by definition-anchor
grep (`^\| *\`?<ID><a name`). Non-depiction: **`API-08` also moved** across the
intermediate-to-v0.17.2 range (`engineering.md` API-08 definition row: backoff,
bounded, 5xx-only; never retry an unmodified 4xx). Other cited IDs (TEST-15, PROV-09, PROV-01, EVAL-11, CAL-02, FM-04, FM-11 retired in literature/HELD.md:69) re-checked as before.

### 10b. Citation audit of this document

| ID | Status | Action |
|---|---|---|
| `HARM-01` | **false alarm** — it is `VLMRP-HARM-01`, a project finding ref, not a canon ID | none |
| `FM-11` in §5a verification table | correct — already verified retired at `literature/HELD.md:69` | none |
| `FM-11` formerly cited as a live constraint (see §8b correction note near the colour-thread close) | **defect** — was cited as live | fixed in place (re-cite hazard to `FM-04` / `CAL-02` per §10c–§10h) |

Also corrected: `PROV-01` lives in **`ml-systems.md`**, not `engineering.md`. A
first-match sweep hit a cross-reference rather than the definition.

### 10c. The adjudication I had not read: `FM-11` was retired *on this exact question*

§5a recorded *that* `FM-11` is retired. It did not record **why**, and the why
governs everything downstream. From `literature/HELD.md:69`:

> **`FM-11` *Closed colour identity* — retired 2026-07-26, never published.**
> The rule said: when colour is emitted as if it had fixed system identity, bind
> it to a named colour vocabulary with fixed referents **and reject membership
> pretence for out-of-set strings.**

It was withdrawn because its only source (Wada) is *"an **instance** of a bound
colour vocabulary — not an argument that free-text colour must not pass as
system identity. **A rule may not rest on an exhibit mistaken for an argument.**"*

**Werner was then acquired specifically to re-source it, and asked directly.
The answer was no (2026-07-26).** The corpus check is recorded: `reject`,
`refuse`, `must not`, `forbid`, `invalid`, `improper`, `inadmissible`, `ought
not` → **zero hits across the whole extract**. Syme teaches the opposite move —
tints *"differing in shade or tint from any of the colours given in this series"* still
*"partake of, or pass into, some one of them."*

> *"re-sourcing `FM-11` from it would repeat the exact error that retired it …
> must **not** be cited as rejection-half authority."*

**This retires the rejection half generally, not Werner specifically.** §9's
swap to ISCC–NBS does not restore the warrant — ISCC–NBS is the *same kind of
witness*, a bound catalogue. Swapping the exhibit cannot manufacture the
argument.

What §9 proposed is **not** damaged by this: `binding: exact|nearest` with a
`delta` is *mapping in*, which is precisely what Syme argues for and what the
reasoning card permits (*"degraded to the nearest in-set term by an explicit
mapping rule"*). **The mechanism survives; any hard gate built on it does not.**

### 10d. What canon actually says about colour in alt text

The reasoning card `controlled-vocabulary-caps-hallucination` now rests on
**`FM-04`** (live, `ml-systems.md`). Its Tensions table settles the register
question outright:

| Partition | Side A | Side B | **Cut** |
|---|---|---|---|
| surface | ordinary colour words in narrative alt text (`FM-11` retired at `literature/HELD.md:69` — no closed-colour gate on prose; ISCC–NBS binds only when colour is machine-consumed) | machine-consumed or identity-bearing colour must be catalog-bound (`FM-04`; ISCC–NBS per §10e) | **"If the string is a token, filter, recipe, or validated label, Side B; if it is narrative only, Side A"** |

Card **Scope** excludes *"open literary description with no claim of catalog
identity"*; **Exemptions** exclude *"open prose that does not claim catalog
membership (mood, scene, metaphor)"*.

**Alt text is narrative only.** A caption is prose read aloud — not a token, not
a filter key, not a stored label. ⇒ **Side A. Ordinary colour words. No catalog
gate.** This is canon, not preference, and it is a stronger and cheaper answer
than §9's.

### 10e. Consequence: Lane D is trigger-gated, not last-in-queue

§9f left Lane D "still last in priority." **Correct that to out of scope with a
named trigger.** Priority ordering implies it eventually comes up; a trigger
says it does not exist until a condition fires.

> **Trigger.** The moment a colour term becomes machine-consumed — a stored tag,
> a search facet, a filter key, a recipe field, or any validated label — `FM-04`
> fires and the catalog work becomes **required**, not optional.

Until then no colour vocabulary ships. When it fires, §9's findings are the
answer already in hand: **ISCC–NBS 267, CC0, `nbsIscc`**, cite SP 440, nested
levels 13/29/267, ΔE at build time only. §8a's pinned re-extraction stays valid
for the photography/cataloguing lane, which is outside this pipeline.

### 10f. What survives — and it lands in Lane C

The card's Verification list contains one line that binds work already scheduled:

> *"Metric definition for attribute quality **does not reward lexical rarity
> without membership or grounding**."*

Playbook §3.1 adds *"verified facts per 100 words … **unverifiable specificity
scores zero, not one**."* **That clause is the canon guard**, and §3.1 as
specified already satisfies it. Implemented as naive density — facts per 100
words without the verified filter — it trips the card directly.

Verified: `caption_metrics.py` today has **no** rarity, specificity, density, or
informativeness signal (the only `distinct*` helpers are name-token matchers).
So the guard is not currently needed and becomes needed the moment Lane C lands.

⇒ **Density zero-score is playbook §3.1 / the card Verification line**, not
`EVAL-11` as a zero-score licence. EVAL-11 (ml-systems.md: open-ended tasks need
the right scorer) is a **mechanism sibling** only. Load-bearing: unverifiable
specificity scores zero; [TEST-15] test that a rare ungrounded noun does not raise density.

Two more cheap, warranted items, both prompt-and-metric only:

- **`CAL-02`** — when evidence supports no in-set term, **abstain**; do not emit
  a precise invented label. Directly targets the fabrication axis
  `score_hallucination` already measures.
- **`PROV-01`** — every output walks back to its evidence: model revision,
  preprocessing, thresholds, source observations (lineage/reproducibility — not anti-invention; fabrication stays `score_hallucination` / `CAL-02`).

### 10g. Reflowed scope

| Lane | Before | **After** | Warrant |
|---|---|---|---|
| **C — METRICS / DEPICT-2** | first; F8 counter + §3.1 density + Williams/C5 | **first; + F6 agentless-passive / mutual-event / actorless-event-noun (`ATTRIB-08` three disjuncts, absorbs P1 item 4 / DEPICT-3 into Slice 2) + §3.1 density zero-score guard (EVAL-11 mechanism sibling) and its discrimination test** | `ATTRIB-01` (F8), `ATTRIB-08` (F6), playbook §3.1, [TEST-15] |
| **B — CONTRACT** | F1 `voice` + register enum + gravity + bound-term shape | **unchanged, minus the bound-term shape** — no colour field until §10e's trigger | `ATTRIB-07`, `API-09`, `API-10`, [TEST-15] (no `ATTRIB-02`/`BOUND-02` for input voice) |
| **A — DEPICT-0** | prompt-lineage seam | unchanged | `PROV-09`, [TEST-15], [REF-10] (not `NAME-03` / `REF-26`) |
| **D — WERNER-FCA** | rebuilt on ISCC–NBS, last | **out of scope; trigger-gated (§10e)** | `FM-04` when it fires |
| **new — abstain** | — | **OUT of this wave; unowned.** `CAL-02` abstain + `PROV-01` evidence-walkback, prompt+metric only | `CAL-02`, `PROV-01` |

**Abstain lane is OUT and unowned.** No plan file in this wave delivers it:
DEPICT-2 scopes it out under heading
``### `CAL-02` and density numerator — metric side only (scope decision)``
— cite that heading only (no numeric line pin into DEPICT-2). The disposition
row carrying **Scoped out of DEPICT-2.** lives in the CAL-02 scope-decision
table under that heading, **not** in `## Target Outcome` prose about assessment
§10f / Williams collapse. DEPICT-0 / DEPICT-1 never touch `CAL-02`. Merging
DEPICT-0 + DEPICT-1 + DEPICT-2 does **not** land abstain behaviour. Named
acceptance criteria for whoever authors it later: (1) the production prompt
instructs abstention when evidence supports no in-set term, rather than forcing
the nearest one (`CAL-02`); (2) a metric counts forced-precision emissions so
the abstain rate is observable, not asserted; (3) an evidence-walkback path lets
a claim be traced to the context field that warranted it (`PROV-01`,
`canon/lexicons/ml-systems.md`); (4) each of the three ships with a red-first
discrimination guard [TEST-15]. Do not absorb this into Lane C.

**Net: the colour thread leaves the critical path entirely, and Lane C gains one
guard plus one test.** Lane C was already the recommendation; it is now the
recommendation with a canon-cited acceptance criterion.

### 10h. One defect in the governing document

`docs/research/library-heuristics-intake-consolidation.md` §11d states *"The
`FM-11` warning is retained."* **`FM-11` is retired canon and cannot be cited.**
The hazard it names is real; the warrant must be re-cited to `FM-04` (structured
output is a contract) and `CAL-02` (abstain over forced precision).

That file is uncommitted on `main` and is the operator's to edit — flagged, not
touched.
