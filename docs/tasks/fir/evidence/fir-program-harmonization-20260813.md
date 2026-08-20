# FIR program harmonization — binding sequence ↔ task map (2026-08-13)

**Purpose:** map every step of the binding sequence in `benchmarks/reports/fir-executive-summary-20260728.md` (§4) to its owning task in `docs/tasks/fir/`, with the live status verified against `main`, the handoff DB, and the filesystem on 2026-08-13. This is a status snapshot, not a plan; the exec summary's sequence stays authoritative. Finding status is queried live from handoff, never mirrored here.

**Binding reference:** `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html` (QA v8 — gitignored, uncommitted by design; the sole on-disk copy lives in the root worktree).

## Verified state (2026-08-13)

| Sequence step | Owner | Verified status | What moves it |
|---|---|---|---|
| **0 — CVUP-1 merge** | CVUP-1 | **Half done.** Merge landed: `main` pins `opencv-python==5.0.0.93` (see pyproject comment citing CVUP1-LC-06 and `docs/tasks/fir/evidence/opencv-5-embedding-drift.md`); CVUP-1 open findings = 0. **The regeneration half did NOT ship:** `benchmarks/results/golden150-fir7-baseline-v7.0-cv5/` does not exist, and none of the six 4.x surfaces (landmarks, gallery embeddings, adapter tensors, τ calibration, comparison run records, determinism/twin goldens) have recorded 5.x artifacts. Per FIR-7 plan Edge 1, "if CVUP-1 ships without them, that is a CVUP-1 defect and FIR-7 is blocked, not expanded." | Open a follow-up task (CVUP-1 is closed) that owns the SFace baseline re-run + six-surface regeneration. Until it lands, every downstream measurement stays provisional and the FIR-7 Slice 0a preflight refuses to freeze. |
| **0a — T-18 anchor validation** | unowned | Not started. `benchmarks/protocols/` still does not exist. | ~2 eng-h, $0, no dependencies. Assign and run; it gates the credibility of every cost cell below. |
| **1 — T-12a OEC decision + T-13 D3 criterion** | unowned | Not started. D2 remains suspended; D-08 never declared. | ~1 eng-h each, $0, unblocked today. |
| **2 — T-09 face-label rule** | unowned | Not started. | ~1 eng-h, $0. Prerequisite for all adjudication (T-14/T-04). |
| **2a — FIR-11 Slices 0–2** | FIR-11 | **Not landed.** Zero FIR-11 commits on `main`; `feature/fir-11` exists; 35 findings open on the task. The plan's "Done" status is not evidence — this row is satisfied only by merged code plus a recorded baseline. | Close the FIR-11 findings, land Slices 0–2 on `main`. Hard gate on all bulk labeling, the T-03-derived sealed split, and FIR-7 Slice 0a. |
| **2b — T-05c post-5.x FNIR@FPIR baseline** | unowned | Blocked on step 0's regeneration half. Harness exists (`face_metrics.py` `face_unknown_rejection()`); only the mated arm is missing. | ~0.5–1 day once step 0 completes. Dependency of T-01 (step 3). |
| **2c — FIR-7 Slice 0a hold** | FIR-7 | **Held, correctly.** Plan v6.2 Edges 1–3 encode the two-part release condition (step 0 with regenerated baselines AND FIR-11 Slices 1–2), the `cv2.__version__` major==5 preflight assertion, and the one-shot K=3 budget. The enforcement surface the exec summary said FIR-7 lacked now exists in the plan. | Nothing — the hold releases itself when steps 0 and 2a complete. Do not start Slice 0a's freeze early. |
| 3 — T-01 attribution spike | unowned | No charter, no anchor, on the critical path. | Write the charter (intervention, apportionment, interval, hour cap) before starting. |
| 3a — T-14 dead-zone signature | **operator** | Unsigned. | Operator-reserved, ~0 cost; gates T-14 (20–34 person-h). |
| 4 — T-03 646-image A10 pass | **operator** | Not run. Authorised, ≤$12 hard stop. | Operator starts the A10 burst. Output quarantined from the sealed split until step 0's regeneration completes. |
| — InsightFace quote email | **operator** | Not sent. | $0; include the distillation-rights question. |

## FIR-7 branch scope vs. the hold

The work on `feature/fir-7` right now — `scripts/train/occlusion/license_policy.py` + mutation guard + tests — is the **license-policy portion** of Slice 0a (plan: "Slice 0a … lands `license_policy.py` constants + fixtures"). It is **not** gated by the 2c hold, which binds Slice 0a's baseline freeze and sealed touches. It is **not** the whole Slice 0a deliverable: the plan's other Slice 0a artifacts (frozen baseline, identity-split, gate spec) are absent from the tree. The branch lands through the ordinary pre-merge gate (round-15 adversarial review pass, zero open findings, close-check) independently of CVUP-1 regeneration and FIR-11. Landing it advances only the license-policy slice of 0a.

## Sibling tasks outside the critical path

| Task | Verified status | Unblocks when |
|---|---|---|
| FIR-2 / FIR-3 / FIR-4 / FIR-5 | Merged. | — |
| FIR-6 (calibration switchover) | 0 open findings; awaiting the operator gate decision, and its quality claims are ceiled DIRECTIONAL until FIR-11 Slice 3 publishes the bias bound. | Operator decision + FIR-11 Slice 3. |
| FIR-8 (bake-off toggle) | Blocked: `acx-dev-fir` isolated stack absent on the VM (512d and 128d cannot share a DB). | FIR23-STACK Slice 1 lands the per-model stack. |
| FIR-9 (curation atlas) | Plan on `main`; projections DIAGNOSTIC-only. | Sealed split (T-08) for anything gate-adjacent. |
| MAINT-fir-training-feasibility-20260727 | 20 findings open (FIRTRAIN-01, 06–12; GT2-01..12), no owner, no date — exec summary item 9 names this as the program's genuine live work. | Assign an owner; decide the migration into the v8 D-\*/T-\* register so the same questions aren't tracked in two places. |

## The three actions that move docs/tasks/fir/ forward this week

1. **Land `feature/fir-7`** (round-15 pass → pre-merge gate → merge). Ships the **license-policy** Slice 0a artifact only. The plan's Slice 0a list is four artifacts; `ls` on 2026-08-16 shows one present and three still open (the 2c hold still binds the freeze / sealed-touch pair):

| Artifact | Present? | Path |
|---|---|---|
| Frozen OpenCV 5.x Golden-150 baseline (FIR7PLR-04) | no | `benchmarks/results/golden150-fir7-baseline-v7.0-cv5/` |
| Train/eval identity-split manifest + content hash | no | `benchmarks/manifests/golden150-fir7-identity-split.json` |
| Pre-registered gate spec (K=3, provisional δ, harm-direction) | no | `benchmarks/gates/fir-7-regate.json` |
| `license_policy.py` constants + fixtures | yes | `scripts/train/occlusion/license_policy.py` (fixtures in `scripts/train/occlusion/test_license_policy.py`) |

2. **Open the CVUP-1 regeneration follow-up task** and run the SFace baseline re-run + six-surface regeneration on the 5.x stack. This is the single cheapest unblock of the entire measurement surface (~1 eng-day, $0) and nobody owns it.
3. **Drive FIR-11 Slices 0–2 to `main`** (35 findings open). Everything adjudication- and split-shaped queues behind it.

The $0 decision rows (T-18, T-12a, T-13, T-09, T-01 charter, T-14 signature) are collectively under a day of effort and all unowned; they can run in parallel with all three.
