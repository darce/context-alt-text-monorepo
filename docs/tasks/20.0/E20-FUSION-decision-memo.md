# E20-FUSION — Staged Fusion vs Ad-Hoc Decision Memo

> **Metadata**
>
> - **Date**: 2026-07-10 EST
> - **Task**: E20-FUSION (`docs/tasks/20.0/E20-FUSION-context-fusion-caption-task-plan.md` Slice 4)
> - **Corpus**: `scene/tests/seed/bakeoff_golden.json` — 10 images, `expected_attachments` mis-attachment labels
> - **Protocol**: stub/seeded adapters only (no live VLM, no network); `scripts/eval_harness/fusion_runner.py` → acx-eval/v1 run records; scored by **unchanged** `report.build_reports`; re-score bit-identical
> - **Artifacts**: `E20-FUSION-{staged,adhoc}-{run-record,report}.{json,md}` + `*-misattachment.json` (this directory)

## Verdict

**Conditional adopt — adopt staged fusion as the describe composition path (already wired in Slices 1–3), pending non-stub evaluation of the caption-quality legs.**

The task-plan adoption gate requires: lower mis-attachment AND Easy-Wrong, without lowering Must-Right / insertion. At stub tier only ONE of those four legs is genuinely measured:

| Gate leg | Status at stub tier | What the number means |
| --- | --- | --- |
| **Mis-attachment** | **Measured** — staged **0/12** vs ad-hoc **4/12** | The only evidence-bearing comparison in this memo (mechanism-level; see limits below) |
| Easy-Wrong | **Vacuous** — `caption_metrics` stubs Easy-Wrong (LLM-judge tier); no score exists in either arm | Carries zero evidence weight |
| Must-Right (0/8 failed, both arms) | **Parity by construction** — the stub caption weaves fixture identity names into BOTH arms' captions | Carries zero evidence weight |
| Insertion rate (1.000, both arms) | **Parity by construction** — same stub-caption name weaving | Carries zero evidence weight |

So the gate as written is satisfiable only on the mis-attachment leg today. We adopt on that leg alone because (a) mis-attachment is the product risk this task exists to close, (b) the staged path is additive provenance — it cannot lower caption quality that is not yet being measured, and (c) the caption-quality legs must be re-run at a non-stub tier (live detailed-tier adapter + LLM-judge Easy-Wrong) before this adoption is considered final. If that non-stub eval shows staged fusion lowering Must-Right/insertion or failing Easy-Wrong, this decision must be revisited.

## Results (regenerated at final Slice-4 code state)

| Metric | **Staged fusion** | Ad-hoc injection baseline |
| --- | --- | --- |
| Items scored | 10/10 | 10/10 |
| **Mis-attachments** (labeled facts) | **0 / 12** | **4 / 12** |
| Insertion rate | 1.000 *(by construction)* | 1.000 *(by construction)* |
| Must-Right failures | 0 / 8 *(by construction)* | 0 / 8 *(by construction)* |
| Policy violations | 0 | 0 |
| Mean gated score | 0.900 | 0.900 |
| Easy-Wrong | *vacuous (unscored at stub tier)* | *vacuous (unscored at stub tier)* |

The 4 ad-hoc mis-attachments (see `E20-FUSION-adhoc-misattachment.json`): identity Linen Kestrel (`linen-kestrel-painting`, expected dropped/unconfirmed), identity Slate Willow, event Garden picnic, and place Summer garden (all `mcm-planecrash`, expected dropped/caption-level) — each asserted object-visible by the ad-hoc caption.

## How each arm is constructed (and its limits)

**Inputs derive from raw fixture data, not from expected labels.** Context-pack identities are the roster names mentioned in the entry's WP context text (site-confirmed `present_identities` carry recognition ids; mentioned-but-not-present names ship unconfirmed/name-only); taxonomy terms and the detector-miss scenario come from fixture fields (`context_pack.taxonomy_terms`, `context_pack.eval_scenario`); `expected_attachments` is read only by the scorer. A negative-control test (`test_scorer_negative_control_flipped_label_is_flagged`) proves flipped labels produce hits.

**Staged arm**: real `VisualFactsService.describe` + Stage-2 reconcile. Each detected identity gets a distinct, non-overlapping face box matched 1:1 against its own person phrase box via real `merge.py` containment — multi-identity images (`ccqw-candid`, `auburn-daniel-sunglasses`) genuinely exercise discrimination (identical geometry would drop both facts as `ambiguous_grounding`). Limit: the face *detector* is simulated — geometry is constructed to be resolvable, so 0/12 evidences the reconcile mechanism (altitude routing, unconfirmed/undetected/ambiguity guards), not detector performance.

**Ad-hoc arm**: the SAME `VisualFactsService.describe` path with the fusion stage disabled — legacy free-form context (title/caption/description) does not coerce to a typed ContextPack, so Stage-2 emits no provenance, exactly like today's ad-hoc WP flow (the runner raises if any Stage-2 fact leaks through). The stub caption parrots the injected context verbatim (today's prompt-injection behavior), and attachment claims are **derived from what that caption actually asserts** (`derivation: adhoc-caption-assertion` in the run record) — a fact label woven into the caption is presented as visual content. Limits: the parroting caption is a deterministic stub, not a live VLM (a real VLM may parrot less or more), and the claim parser is substring-based; 4/12 is a measured property of the generated caption text, not a hardcoded worst case.

## Success criterion: `mcm-planecrash`

Staged run-record (and `test_mcm_planecrash_success_criterion`): identity Slate Willow → `dropped` / `altitude=none` / `review_reason=face_not_detected` (detector-miss scenario from the fixture, not from the label); event Garden picnic and place Summer garden → `caption` / non-visible. Semantic event/place *drop* remains the LLM-judge stretch; MVP keeps unsupported event/place caption-level and non-asserted.

## Protocol notes

- Runner is **not** `bakeoff.py` (FUSION-PR-01): fusion_runner drives `VisualFactsService` + Stage-2 reconcile; bakeoff is raw single-VLM captions.
- Both reports carry the model-free `seeded` stub banner — neither arm is a caption-model baseline. Face detection/identification sections now partially derive from the simulated detector (Maria's scenario miss shows as detection recall 0.882 / identification recall 0.889); they remain stub-tier, not fusion discriminators.
- The brand-attachment arm of Stage-2 is inert in this eval until E20-BRAND-A lands brand detections (deferred finding HARM-04); the WP decorative primary-skip is WP-side follow-up (deferred finding HARM-03).
- Deterministic re-score: double runs produce byte-identical run-records/reports modulo the documented volatile provenance fields (`head_sha`, `started_at`).

## Follow-ons (out of this slice)

- **Non-stub eval required to finalize adoption**: live detailed-tier adapter bake-off + LLM-judge Easy-Wrong scoring (the two gate legs unmeasured here).
- LLM-judge reconciler for semantic event/place conflict-drop (stretch).
