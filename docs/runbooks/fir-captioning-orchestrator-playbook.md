# Orchestrator Playbook — FIR + Captioning Library-Informed Improvements

**Task**: LIBSYN-1 · **Date**: 2026-07-25 · **Audience**: the next orchestrator agent

Companion: [`docs/research/library-heuristics-intake-consolidation.md`](../research/library-heuristics-intake-consolidation.md)
(source registry, card mechanisms, exclusions). This file is the *what to do
next and in what order*; that file is the *why and on whose authority*.

## 0. Read this first

Three constraints shape every ordering decision below.

1. **Two of the highest-leverage changes are cheap only while their slice is
   still open.** VLM-6 Slice 1 (Golden-100 curation) and the bake-off registry
   are open now. After the GPU window is scripted and burned, the same changes
   cost a second window.
2. **The FIR-7 gate is the highest-risk surface in the epic, and it is a
   statistics surface, not a computer-vision surface.** The CV work is
   well-understood; the gate can pass wrongly in ways nothing downstream
   detects. Sequence statistics before models.
3. **The library is now nearly complete for CV and nearly empty for
   statistics.** 27 papers landed 2026-07-25 covering PEFT, diffusion identity
   generation, SAM, and compositing. The Tango/Newcombe/Nam/Fagerland primaries
   and the cluster-inference references are still missing and are paywalled.
   Treat their acquisition as a blocking dependency, not a nice-to-have.

## 1. Alignment check — do not skip

Before dispatching anything, confirm these still hold. Each was computed this
session; each is falsifiable in under five minutes.

| Claim | How to verify | If false |
|---|---|---|
| FIR-7 plan is at v6.2 on `feature/fir-7`, not on `main` | `git -C ../context-alt-text-monorepo-fir-7 log -1 -- docs/tasks/fir/FIR-7-occlusion-adapters-task-plan.md` | Re-read the plan; slice numbering below may have moved |
| VLM-6 Slice 1 is still open (Golden-100 not frozen) | `review_findings(list)` + plan checklist on `feature/vlm-6` | §3 changes become expensive; re-cost before proposing |
| Curation tenant `4ddf8f36…` still live at `localhost:10018` | LocalWP admin | Slice 1 coordination items in the VLM-6 plan are blocked |
| `acx-gpu-burst` still STOPPED | `oci-instance-state-and-cost.md` runbook | Billing is accruing — stop before anything else |
| Occlusion baselines unchanged: detection recall 0.504, masked `a_s` 0.321, sunglasses 0.226, 54/84 masked re-detect misses on Golden-150 | FIR-7 plan baseline table | Re-derive the margin; §2 ordering assumes these |

## 2. FIR occlusion track — ordered

### 2.1 Acquire the statistics primaries (BLOCKING)

Tango 1998 · Newcombe 1998 (×2) · Nam 1997 · Fagerland 2014 ·
Fagerland/Lydersen/Laake (CRC 2017) · Donner & Klar · Field & Welsh ·
Cameron/Gelbach/Miller.

The gate implements a **Tango/Newcombe paired score interval** and a
**margin-McNemar in Tango score form**. Both are being implemented from
secondary descriptions today. This is the single largest correctness exposure
in the epic: a subtly wrong interval produces numbers that look right, pass
review, and gate a merge.

Dispatch: operator task (purchase / institutional access), not an agent task.
While blocked, an agent *may* build the harness against a **published reference
implementation** and validate numerically — but the validation target must be a
citable implementation, not a re-derivation.

### 2.2 Seal the gate design before any model training

Per card **C4** (`margin-and-design-effect-before-the-run`):

- Margin, interval method, harm direction per floor, and α allocation over K=3
  candidates: sealed and committed **before** the first training run.
- `n_eff` computed from the measured cluster design effect (AUDIT-11), and
  `δ_floor = max(0.02, MDE_paired(n_eff, p_disc_prior=0.10))` derived from
  `n_eff`, not from row count.
- Evidence tier declared per claim: CONFIRMATORY / DIRECTIONAL / DIAGNOSTIC.
  Only CONFIRMATORY claims may gate a merge.

This is a plan-and-review task, not an implementation task. Route through
`/planning-review`.

### 2.3 `yunet-occ` — occlusion detection, with a control arm

Multi-task `L_det = L_occluded + λ·L_clean`.

**Add before training starts** (card **C2**, `synthetic-artifact-control-arm`):

- An **artifact-only control arm**: the same compositing pipeline applied with a
  non-occluding patch (underlying pixels re-pasted through the identical alpha
  and resample path). If the metric moves on the control arm, the model is
  detecting the compositing signature, not occlusion.
- **Premultiplied alpha** throughout the compositing path (Porter & Duff).
  Non-premultiplied `over` leaves a fringe that is exactly the shortcut signal.
- A **real-occlusion holdout** the synthetic pipeline never touched. Synthetic
  `a_s` = 0.321 is measured on synthetic today; that number cannot certify
  anything on its own.

Occluder masks: SAM-family. **Exclude FastSAM at registry level** — it is built
on Ultralytics YOLOv8 (AGPL-3.0), which the plan bans, and it appears in every
fast-segmentation comparison table. Encode the ban as a licence field in the
candidate registry with CI enforcement, not as a review checklist item (card
**C3**).

### 2.4 `sface-occ-adapter` — frozen-base residual head

128 → r=32 → 128, zero-init, clean-anchor + cosine angular-margin loss
(α=1.0, β=0.5, m=0.30).

Read **Rebuffi (residual adapters)** and **Houlsby** as primaries. This is a
*vision bottleneck adapter*, not LoRA — reading LoRA first yields rank/α
guidance that does not transfer. Side-Tuning is the closest analogue to the
deployment shape below. EWC names the failure the clean-anchor term prevents.

Required checks (card **C1**, `frozen-base-additive-delta`):

- A **zero-init identity test**: at initialisation the adapted path must be
  bit-identical to the frozen base. If it is not, the composition is wrong
  before any training question arises.
- **Trainable-fraction accounting** declared as a budget and asserted in test,
  satisfying `[C-PEFT]`.
- The un-adapted path retained as a live control arm and rollback, satisfying
  `[C-REEMBED]` — the base embedding space must remain reachable.

### 2.5 ONNX deployment — do not do graph surgery first

Card **C8**. Ship **two sequential ONNX Runtime sessions** (frozen SFace → 128-d
vector → adapter session → 128-d vector). Do **not** use
`onnx.compose.merge_models` for the first landing.

Rationale: the two-session form keeps a debuggable, independently-versionable
seam and costs one extra session invocation on a 128-d tensor — negligible
against the embedding forward pass. Graph merge buys latency that has not been
shown to matter and fails as silent numeric drift rather than as an error.

Defer the merge behind a **bit-parity test** against the two-session reference
on a fixed input set, and keep the two-session path as the reference
implementation permanently.

### 2.6 Synthetic identity generation (DCFace track)

Operator clearance exists (`dcface_operator_clearance_20260723`). Canon already
covers the three claims that matter most — synthetic substitution when
authentic galleries are unlawful, measured identity-linkage before a privacy
claim, and synthetic-train accuracy not certifying deployment. **Do not
re-litigate those.** What is missing is generation *operations*: identity/style
separation, intra-class diversity as an explicit knob, and uniqueness collapse
at scale. Read DCFace + SDFR + DigiFace-1M; DDPM / CFG / Latent Diffusion are
mechanism background, not decision sources.

Acquire Boutros 2308.04688 (the survey) before choosing between DCFace,
IDiff-Face, and Arc2Face — it is the only source that frames them against each
other.

## 3. Captioning / VLM-6 track — two cheap changes, now

Both are changes to work that is currently open. Both close risks the plan
itself names. Neither requires a GPU window.

### 3.1 Add a signal-density metric to the eval harness

The plan measures no signal density at all, and every quality metric it does
measure is length-correlated. Per card **C5**, the bake-off as written will
rank the most verbose candidate highest.

**Add**: verified facts per 100 words (equivalently, per second of synthesised
speech). Verified = checkable against the image or a trusted supplied source;
unverifiable specificity scores zero, not one. Land it in
`scripts/eval_harness/caption_metrics.py` alongside the existing metrics.

This is the direct operationalisation of the user's stated goal — *not longer,
but each descriptive word carrying higher signal*. Nothing currently in the
plan measures it.

### 3.2 Add a context block per candidate in `bakeoff_candidates.yaml`

Per card **C6**, caption quality and context obedience are different
capabilities and are not correlated. The plan's own §13 names "CapRL's
instruction obedience unknown" as an open risk — and as written, the bake-off
**cannot answer it**, because every candidate is run in a single no-context arm.

**Add**: a per-candidate context block and a two-arm run (no-context /
context-supplied). Score three things explicitly:

1. **Insertion** — supplied facts that appear in the output (assessment
   benchmark: 93.2%).
2. **Non-contradiction** — supplied facts the output contradicts. Any
   contradiction is a tier gate failure, not a score penalty.
3. **Non-invention** — facts in the output that were neither visible nor
   supplied. Mechanically checkable under a merge-only fusion contract
   (`units_out ⊆ units_in`, CoTalk).

Without this arm the bake-off selects on the wrong axis and the entire
context-assembly phase ships against an unvalidated assumption.

### 3.3 Ranking discipline (unchanged, restated because it is easy to lose)

Hallucination-first. **Latency is a tier gate, not a ranking axis** — GPU async
≤170 s p95 (derived from `ACX_GPU_READ_TIMEOUT_SECONDS=175`), CPU inline
≤20 s p95. A candidate either clears its tier or is out; among survivors,
latency contributes nothing to rank.

### 3.4 Context sourcing — sequence tenant-local before live web

The user's interest is live web search at inference time from the OCI VM. The
correct *first* increment is not that.

**First: tenant-local GraphRAG over existing WordPress content.** Zero external
dependency, zero prompt-injection surface, zero latency variance, private by
construction, and it exercises the entire Phase-2 provider port, fan-out,
timeout, and Special Case machinery. Sources already in canon:
`graphrag-local-to-global`, `chatpid-graphrag-engineering-diagrams`,
`building-knowledge-graphs`.

**Second, only once the port is proven:** live retrieval behind the same port,
with the STORM multi-perspective pattern for query formulation
(`storm-knowledge-curation-system`, `storm-multi-perspective-prewriting`).
Treat retrieved web text as untrusted input — it enters a prompt, so it is an
injection channel, and the source-precedence trust order (RE-VLM) must place it
below tenant-local and visual facts.

Entity linkage across the two (matching a WordPress person/place to a retrieved
entity) is a record-linkage problem, not a prompting problem — Christen,
*Data Matching*.

### 3.5 Controlled colour vocabulary (small, high return)

Card **C7**. Bind colour description to **ISCC–NBS** (`iscc-nbs`, pinned to NBS
SP 440, 1976) — a versioned standard whose every term carries a public referent:
Munsell-block membership plus a published centroid. Validate emitted colour
terms against the set deterministically; an out-of-set observation is *referred
in* to the nearest block and the difference recorded, **never refused**. That
distinction is load-bearing: the rejection half was retired as `FM-11` and is
not sourced. This raises signal per word, removes a hallucination surface, and
supplies the vocabulary source the caption assessment's informativeness metric
currently lacks. Feeds directly into §3.1's "verified" definition.

Emit at the depth the register calls for — ISCC–NBS nests 13 basic names / 29
intermediate hues / 267 blocks, so EDITORIAL takes a basic name and FORENSIC the
full block, from one vocabulary. Werner's *Nomenclature of Colours* is the
**warrant** for this rule, not the set to emit: it argues that free colour names
are unreliable between observers and that an unlisted shade must be referred
into a standard, but it is a single unversioned 1821 edition whose referents are
plates that do not survive as text. It stays available to the cataloguing and
specimen lane. See §11 of
[`library-heuristics-intake-consolidation.md`](../research/library-heuristics-intake-consolidation.md)
for the provider decision, the bound-term contract, and the reason the
`werner` colour list published with hex values must not be used as a numeric
layer.

### 3.6 Visual primitives / name-to-face binding

The DeepSeek-AI "thinking with visual primitives" paper is the principled form
of the standing rule: **never emit a flat name list — bind names to faces by
left-to-right face-box position**, or identities mis-swap on group shots. Worth
reading before the Phase-3 prose composer is written; not worth blocking on.

## 4. Do-not-do list

- Do not re-sweep the 27 papers already dispositioned in
  `caption-context-enrichment-assessment-2026-07-05.md` §9. Read the verdict
  table.
- Do not build a paper-retrieval stack. Explicit non-goal, assessment §12.
- Do not author the score-interval reasoning card, or implement the interval as
  canon-backed, from secondary descriptions.
- Do not merge the ONNX graphs on the first landing (§2.5).
- Do not admit FastSAM, Ultralytics, or any buffalo-derived weights **or
  outputs** (§2.3).
- Do not fine-tune the SFace trunk (§2.4). Additive delta only.
- Do not run the GPU window before §3.1 and §3.2 land.

## 5. Dispatch shape

Mechanical work — harness code, metric implementations, corpus plumbing,
sweeps, merges — goes to remote grok lanes. Local judgment work — the gate
design (§2.2), the ranking discipline, review — stays local.

Milestones take `/review-parallel` including a remote reviewer. Every plan
change routes through `/planning-review` before it is called done. Cite
heuristics-canon rule IDs in plan, implementation, and review text — verify each
ID exists in the pinned tag before citing it; the canon forbids invented IDs.

## 6. Suggested first three dispatches

1. **Operator**: acquire the statistics primaries (§2.1). Blocking; start now.
2. **Agent, `feature/vlm-6`**: land §3.1 (signal-density metric) and §3.2
   (context arm + obedience scoring). Both are pre-GPU-window and cheap only
   while Slice 1 is open.
3. **Agent, `feature/fir-7`**: land the artifact-only control arm and the
   premultiplied-alpha compositing path (§2.3) plus the zero-init identity test
   (§2.4) *as tests*, before any training run consumes a GPU hour.

Every report carries total cost and cost-per-image (A10 ≈ $2/GPU-hr,
A1.Flex ≈ $0.152/hr); stamp spend at batch start and end.
