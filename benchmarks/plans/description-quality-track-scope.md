# Scope: description quality-measurement track + accurate-anatomy register

Date: 2026-07-16 · Intake: /scope · Prospective task: **DESCQUAL-1**
Follows: [`corpus-measurement-evaluation-2026-07-16.md`](../assessments/current/corpus-measurement-evaluation-2026-07-16.md)
(the corpus has no way to score description *quality* today — this track adds it).

## Objective

Give the harness a way to measure **description quality** (not just name-handling),
and make the description register **accurate by default** — faithful, plain
descriptions that match image content, with no euphemism and no fabrication —
because alt-text exists to put a clear, complete image in a blind user's mind.

Two coupled pieces: a **quality-scoring mechanism** (so "better" is measurable)
and an **accurate register** (the quality lever the user flagged), measured by
that same mechanism.

## Decisions (intake, 2026-07-16)

- **Scoring: both** — pairwise-human ("which is better, A or B?") for model
  selection + a calibrated LLM-judge (accuracy / completeness / no-euphemism /
  no-fabrication / WCAG-fit) as the scalable axis.
- **Register: accurate is the global default, not a toggle** — "captions match
  content; if a user doesn't want explicit descriptions, don't submit explicit
  pictures." No operator setting. The description faithfully represents whatever
  is in the image.
- **Start on the locked 10-image bake-off set** — fast signal during the
  multi-model bake-off; the durable stratified gold set (Golden-150) comes later.

## MVP scope

1. **Accurate-register prompt** — a description register that instructs direct,
   accurate anatomical/physical description (no euphemism, no coy obfuscation),
   bounded by the existing never-fabricate contract (describe what is visible;
   do not invent, do not eroticize beyond what the image shows). Built as a
   named prompt variant so it can be **A/B'd against the current register**
   during measurement; on a proven win it becomes the default (pass-2 register is
   the target — pass-1 already emits objective facts).
2. **LLM-judge rubric** — per-caption scores on: factual accuracy, completeness,
   **euphemism/obscuring (accuracy failure)**, fabrication (the other direction),
   WCAG alt-fitness, title/caption register. Judge model **≠ model under test**;
   the rubric explicitly defines euphemism as a failure so a coy judge can't rate
   obscured captions as "appropriate." Deterministic prompt, structured JSON out.
3. **Judge calibration** — a ~30–50-caption human-labeled seed (drawn from the 10
   bake-off images × candidate models), including intimate/anatomical items;
   report judge-vs-human agreement; judge numbers are untrusted until agreement
   clears a stated bar.
4. **Pairwise-human harness** — a tiny local UI/CLI that shows two captions for
   the same image and records the preference; produces a win-rate ranking across
   the bake-off models. Reuses the image-embedded report format.
5. **Wire into the bake-off** — the 10-image multi-model report gains a judge
   column + a "euphemism vs accurate" flag per caption, and the pairwise win-rate
   table. This is the first place the accurate register is measured against the
   current one.

## Success criteria

- Pairwise-human + LLM-judge produce a **ranked model comparison** on the 10
  images, including a euphemism/accuracy axis — so the bake-off is *scored*, not
  just eyeballed.
- The accurate register **measurably reduces euphemism** (judge + human) vs the
  current register **without raising fabrication** (never-fabricate gate holds).
- **Model compliance is quantified**: the report shows, per model, how often it
  followed the accurate-register instruction vs softened/refused — a real
  selection criterion (a model that won't describe accurately is disqualified for
  this product regardless of other quality).
- Judge calibration agreement with the human seed is reported and above the bar
  before any judge-only number is used as a gate.

## Explicit-content corpus (separate, tenant-gated) — deferred sub-track

Added 2026-07-16 per operator decision: explicit content is measured and tuned in
**isolation**, not mixed into the general corpus.

- **Separate corpus in a dedicated tenant.** Explicit content lives in its own
  recognition/curation tenant (reusing the multi-tenant pattern of the 10018
  curation tenant; keys via `docs/runbooks/key-management.md` /
  `make admin-oci-mint`). The tenant **gates results**: only holders of that
  tenant key can see, curate, or label them.
- **Never in the shareable tree.** Explicit-corpus outputs must NOT land in
  `benchmarks/` (which is committed to `main` and may be shared) — they stay
  tenant-scoped and access-gated. The quality harness is therefore built
  **tenant-aware from the start** (manifests carry a tenant; reports/dashboard
  exclude gated tenants from any shareable output), even though this sub-track's
  bake-off runs later.
- **Same global register, harder test.** The accurate register is still global
  ("captions match content"); this corpus is where it is **stress-tested and
  tuned**, because explicit content is exactly where VLMs euphemize or refuse.
  It is a tuning + compliance-measurement set, not a different register.
- **The decisive model-compliance gate.** A model that describes general content
  accurately but softens or refuses on explicit content fails full coverage — so
  this sub-track's bake-off is likely the **strongest single model discriminator**
  for the product. Self-hosted open weights are the only viable path (hosted APIs
  refuse and are off the table for privacy regardless).
- **Requirements before it runs.** Documented consent/provenance for every image;
  provenance private + `publishable=False` + tenant-scoped; pairwise labeling by
  **authorized reviewers only**; upload/consent policy is the operator's, the
  describer only describes what is submitted.
- **Also the test ground for COCO-marker + multilayered scene description
  (E22 / insightface replacement).** Beyond VLM prompting, the explicit corpus
  is where the detection-grounded, layered scene-description architecture gets
  exercised — because pose, region, and spatial grounding matter most there:
  - **COCO markers** = object/region/keypoint (pose) detections in COCO format
    from the rebuilt non-face detection layer (RF-DETR SOTA-COCO / OWLv2 open-
    vocab; `segmentation-vlm-pipeline-feasibility-2026-06-15.md`), grounding what
    the describer asserts. For explicit content, pose keypoints + region boxes
    give the accurate anatomical/spatial structure the register demands.
  - **Multilayered approach** = the tiered composition from
    `caption-context-enrichment-assessment-2026-07-05.md` §3: scene-level
    orientation first → regional groupings → fine detail, with **constrain-then-
    map** naming (detectors emit only roster-checkable tokens; names mapped
    deterministically at merge; never generated) and the CPU-cheap verification
    layer (ghosting probe / geometric consistency) as anti-fabrication gates.
  - So this corpus does double duty: it stress-tests the **accurate register**
    (VLM prompting) *and* the **detection-grounded layered synthesis** the E22
    face-pipeline replacement introduces — the two are complementary (markers
    ground the register's accuracy claims, the register turns markers into faithful
    prose). The insightface replacement supplies the marker layer; DESCQUAL-1's
    judge/pairwise measures whether the layered output is actually better.
- **Deferred**: separate bake-off, later. Scoped now so tenant-isolation **and
  marker/tier awareness** are designed in, not retrofitted.

## Constraints / risks

- **Compliance is empirical and model-dependent** — some VLMs soften or refuse
  regardless of prompt; self-hosted open models (Qwen3-VL etc.) are more
  steerable than hosted APIs (which are off the table for privacy anyway). The
  register is *intent + prompt*; adherence is *measured*, and it becomes a
  primary bake-off axis.
- **Judge euphemism bias** — an LLM-judge may itself be trained to be coy and
  mis-score; mitigated by the explicit rubric + human calibration on
  intimate-content items specifically, and by choosing/prompting the judge for
  faithfulness-to-image.
- **Content boundary** — "accurate, faithful, plain" is the target register, not
  gratuitous/eroticized embellishment (which the never-fabricate gate already
  forbids). The bound keeps the feature an accessibility feature.

## Not-doing (MVP)

- No operator/tenant register toggle (accurate is the global default — user
  decision).
- No Golden-150 build yet (start with the 10 bake-off images; the stratified
  frozen gold set is the follow-on from the corpus evaluation).
- No human-written reference captions (pairwise + judge instead — cheaper, and
  directly answers "better").
- No new adult-content classifier / moderation layer — the product describes what
  is submitted; upload policy is the user's, not the describer's.
- The **explicit-content bake-off does not run in the MVP** — only its
  tenant-aware isolation is designed in now; the corpus curation + separate
  bake-off are a deferred sub-track (own tenant, own review, later).

## Ownership / next

Spans two surfaces: the **accurate register** is an ALTQ prompt variant
(`bakeoff.py` PROMPT_VARIANTS, feature/altq-1); the **judge + pairwise + corpus**
are the quality harness (VLM-6 / benchmarks). Suggest a single **DESCQUAL-1** task
that lands the register variant + judge rubric + pairwise harness together and
runs them on the multi-model bake-off. Then planning-review before implementation.
