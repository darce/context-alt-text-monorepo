# ADR-ARCH-07: OpenCV pin for face-pipeline reference path

- **Status:** Superseded
- **Date:** 2026-07-18
- **Superseded:** 2026-07-30 by CVUP-1 (see [Supersession note](#supersession-note-2026-07-30-cvup-1))
- **Deciders:** FIR-3 implementers (lane fir-3-grok); product/architecture owner
- **Context task:** FIR-3 (YuNet + SFace adapters)
- **Related:** [commercial face-pipeline assessment §9-2 / §10.3](../assessments/current/commercial-face-pipeline-replacement-assessment-2026-07-15.md), [FIR-3 task plan](../tasks/fir/FIR-3-yunet-sface-adapters-task-plan.md), FIR-7 (GPU path, separate)
- **Heuristics:** ARCH-07 (write the ADR), ARCH-06 (trade-offs explicit), ARCH-08 (boring stack first), AGT-02 (cite verified evidence), YAGNI / REF speculative-generality (no migration without a concrete need)

## Supersession note (2026-07-30, CVUP-1)

This ADR's **KEEP 4.x** decision is superseded by **CVUP-1**. The live service pin is:

```text
opencv-python==5.0.0.93
opencv-python-headless==5.0.0.93   # bench extra
```

Both cv2 distributions unpack into the same top-level `cv2/` package, so they are pinned to one exact release rather than a shared major window — a resolver skew between them would decide which binaries import by install order. The original Decision / Alternatives / Consequences below remain the historical FIR-3 record; they no longer describe the shipped pin.

### Revisit triggers under CVUP-1

Evaluated against the triggers this ADR required:

1. **Stable OpenCV 5.x wheel line:** Met. `opencv-python` and `opencv-python-headless` both resolve to `5.0.0.93` in `uv.lock`.
2. **Concrete need:** Not recorded in the branch in this ADR's sense (no measured reference-path or CI-host performance gap closed only by 5.x/KleidiCV; no model/API that requires OpenCV 5 on the reference path; no documented security/support EOL of the 4.12–4.14 line). Migration performed under CVUP-1; the driving need is not recorded in the branch.
3. **Migration gate (S2 oracle + S3 parity):** Met. The S2 oracle suite and the S3 ORT parity suite are green at branch HEAD under OpenCV 5; the S3 budget was **tightened**, not relaxed — see the S3 parity-budget amendment in the [FIR-3 task plan](../tasks/fir/FIR-3-yunet-sface-adapters-task-plan.md#s3-parity-budget-amendment-2026-07-29-cvup-1).

### Migration cost (as this ADR predicted)

Goldens were re-minted under the new OpenCV 5 `FaceRecognizerSF` / `warpAffine` semantics. Measured cross-version embedding drift (4.13.0 → 5.0.0) is recorded in [opencv-5-embedding-drift.md](../tasks/fir/evidence/opencv-5-embedding-drift.md); re-measure before any further pin move.

### Waiver — trigger 2 not met (open item)

**Waiver (deliberate deviation from this ADR's own gate):** the CVUP-1 bump proceeded without trigger 2 (a concrete need) being met. The Triggers section still requires all conditions; this supersession records the deviation rather than rewriting the gate.

This note is **not** a completed waiver and **not** an operator signature. The bump is an unsigned, operator-reserved override of the gate this ADR exists to enforce. A valid ratification must name: (1) the acceptor, (2) why the bump proceeded without a measured reference-path/CI-host gap, a 5.x-required model/API, or a 4.12–4.14 EOL, and (3) whether the live pin stays on 5.0.0.93 or rolls back. Until that lands, treat the 5.x pin as **provisional relative to this ADR**, even though the S2/S3 migration gate (trigger 3) is met.

No operator decision is recorded in-branch — whether the deviation stands, is ratified, or is rolled back remains an **open item**.

### Accepted risk — incumbent InsightFace path unmeasured (CVUP1-GR-03)

**Accepted risk (named):** the committed 4.13→5.0 drift evidence covers the **SFace reference path only** (YuNet detector, SFace embedder, FIR-3 goldens under `opencv-sface+…` space tokens). Production default is `RECOGNITION_FACE_PIPELINE_PROFILE=insightface`, whose deployed embedding id is `insightface-buffalo_l@512d/l2/cosine`. That id carries **no** OpenCV space token, so it is byte-identical before and after the pin bump: the embedding-space partition alarm reports a match while the deployed 512d vectors re-baseline by an **unmeasured** amount, and old and new vectors are compared as co-spatial. The InsightFace path also routes alignment through `cv2.warpAffine` (via `norm_crop`) — the same function whose numeric move forced the SFace golden regeneration. SFace evidence does **not** transfer (different detector, different alignment call sites, different model). Incumbent-path drift under OpenCV 5 is **unquantified**.

## Context

FIR-3 ships two face-pipeline implementations with identical semantics:

1. **OpenCV reference** (`FaceDetectorYN` / `FaceRecognizerSF`) — CPU golden source-of-truth for landmarks, affine align-crop, and SFace embeddings.
2. **ONNX Runtime (ORT) CPU adapters** — production path; parity-tested against the OpenCV reference.

The service already pins `opencv-python>=4.12.0,<4.15.0` (`apps/prototype-description-service/pyproject.toml`). Assessment §10.3 had tipped toward **OpenCV 5** for the reference path (new DNN engine, dynamic shapes for YuNet 2026may, ARM KleidiCV) while keeping ORT primary. That tip assumed YuNet 2026may needed OpenCV 5 dynamic-input support on the reference path.

### Verified evidence on `feature/fir-3` (AGT-02 — do not re-derive)

| Fact | Evidence |
| --- | --- |
| Repo pin | `opencv-python>=4.12.0,<4.15.0` (service `pyproject.toml`); resolved **4.13.0** in the FIR-3 env |
| YuNet 2026may on 4.x | BR-05 spike: `cv2.FaceDetectorYN` loads + detects YuNet 2026may (dynamic-input re-export documented upstream for OpenCV 5.x) fine on **4.13.0**; cartoon golden score **0.9024** |
| Align-crop oracle | S2: `FivePointAligner` vs `FaceRecognizerSF.alignCrop` **bit-exact** (`test_five_point_aligner_matches_aligncrop_oracle_bitexact` in `recognition/tests/unit/test_face_pipeline_opencv_ref.py`) |
| ORT production parity | S3: ORT vs 4.13 reference near-exact — embedding cosine **0.99999988**, detector IoU **0.9999997**; multi-face / non-×32 / border-clipped cases committed (`recognition/tests/unit/test_face_pipeline_ort_parity.py`) |

The spike **removes the main motivation** for migrating the reference path to OpenCV 5 now: 2026may already works on the pinned 4.x line, and production does not depend on OpenCV for inference throughput.

### What breaks if the pin drifts

Goldens and the portable aligner are **oracle-locked to `FaceRecognizerSF` semantics** on the current pin. Regeneration and CI assert bit-exact (same-host) crop equality against `cv2.FaceRecognizerSF.alignCrop` and SHA-256 of committed `aligner_crop.npy`. An unconstrained OpenCV major/minor bump can change DNN post-processing, affine crop bytes, or embedding floats and:

- fail the S2 oracle suite without a deliberate re-golden,
- silently invalidate S3 ORT parity budgets (cosine / IoU),
- poison every downstream embedding if a drifted reference is used to re-mint goldens.

Pin drift is therefore an **architecture decision**, not a routine dependency bump (ARCH-07).

## Decision

**KEEP** the existing pin:

```text
opencv-python>=4.12.0,<4.15.0
```

for the **FIR-3 OpenCV reference path** (golden source-of-truth).

- **ORT CPU remains the production inference path.**
- **No `pyproject.toml` change** — the pin already matches this decision.
- **OpenCV 5 migration is deferred** until *both*:
  1. OpenCV 5 ships **stable** in `opencv-python`, and
  2. a **concrete need** appears (see Triggers below).

### Migration gate (when revisiting)

Re-run the S2 oracle suite and the S3 ORT parity suite as the mandatory acceptance gate — both must stay green on the candidate OpenCV version before any pin change lands:

```bash
cd apps/prototype-description-service && uv run pytest \
  recognition/tests/unit/test_face_pipeline_opencv_ref.py \
  recognition/tests/unit/test_face_pipeline_ort_parity.py -q
```

If oracle crops or embeddings diverge, re-golden only after an explicit decision that the new OpenCV semantics are the desired source of truth; then re-verify ORT parity against the new goldens.

## Alternatives considered

### 1. Pin OpenCV 5 now for the reference path (assessment §10.3 tip)

**Rejected for now.** Benefits (DNN rewrite, dynamic shapes, ARM KleidiCV) are real but **speed/compat**, not accuracy. Spike evidence shows YuNet 2026may already runs on 4.13.0; ORT is the production path (ARCH-08 boring baseline already satisfied). Migrating without a concrete need is YAGNI and risks re-locking goldens for no product gain (ARCH-06).

### 2. Widen or drop the upper bound (`<4.15`)

**Rejected.** Goldens are oracle-locked to `FaceRecognizerSF` behavior; an open upper bound invites silent semantic drift. Keep a tight major/minor window until a deliberate migration gate re-validates S2+S3.

### 3. Drop the OpenCV reference entirely; ORT-only goldens

**Rejected for FIR-3.** The task plan requires a semantic reference independent of our ORT post-processing so adapter regressions are detectable. OpenCV `FaceRecognizerSF.alignCrop` is the portable oracle for alignment.

## Consequences

### Positive

- Reference goldens stay stable on a known-good line (4.12–4.14.x; 4.13 verified).
- Production path (ORT CPU) is unblocked and already parity-proven against that reference.
- No dependency churn or API-migration cost in FIR-3.
- ARM KleidiCV / OpenCV 5 speed work remains a clean future slice when evidence warrants it.

### Negative / accepted debt

- Reference path forgoes OpenCV 5 DNN engine and **ARM KleidiCV** acceleration until a later migration (ACK: future work; **FIR-7 GPU is a separate track** and does not require this pin change).
- Operators must treat OpenCV bumps as gated releases, not casual `uv lock` upgrades.

### Triggers to revisit (all required unless noted)

1. `opencv-python` publishes a **stable OpenCV 5.x** wheel line suitable for our platforms, **and**
2. At least one concrete need:
   - measured reference-path or CI-host performance gap closed only by 5.x/KleidiCV, or
   - a model/API that **requires** OpenCV 5 on the reference path (2026may no longer qualifies), or
   - security/support EOL of the 4.12–4.14 line;
3. Migration gate above (S2 oracle + S3 parity) green, with re-golden only if intentionally adopting new semantics.

## Action items

1. **Done by this ADR (FIR-3):** record KEEP decision; leave `opencv-python>=4.12.0,<4.15.0` unchanged at that time.
2. **Done by CVUP-1 (2026-07-30):** migration gate re-run green under OpenCV 5; pin moved to ==5.0.0.93 for both cv2 distributions; this ADR status flipped to Superseded with supersession note above. Goldens re-minted; drift probe recorded under `docs/tasks/fir/evidence/opencv-5-embedding-drift.md`.
3. **FIR-7 / GPU:** do not couple GPU work to this OpenCV pin; ORT/CUDA/TensorRT paths are independent.
4. **Open (operator-reserved):** ratify or roll back the trigger-2 waiver in the supersession note. Unsigned. Not agent-closable.

## Sources

- Service pin (FIR-3-era, superseded by CVUP-1): `apps/prototype-description-service/pyproject.toml` then `opencv-python>=4.12.0,<4.15.0`; live pin is `opencv-python==5.0.0.93` / `opencv-python-headless==5.0.0.93` (see supersession note)
- S2 oracle: `recognition/tests/unit/test_face_pipeline_opencv_ref.py` → `test_five_point_aligner_matches_aligncrop_oracle_bitexact`
- S3 parity: `recognition/tests/unit/test_face_pipeline_ort_parity.py`
- Assessment §9-2, §10.3: `docs/assessments/current/commercial-face-pipeline-replacement-assessment-2026-07-15.md`
- Heuristics: ARCH-06/07/08 (engineering lexicon), AGT-02
