# VLM-2A. Caption-Quality + Face-Recognition Eval Harness — Scope Note

> **Status:** Scope intake (question-first pass complete). Feeds the VLM-2A task plan.
> **Date:** 2026-07-05 · **Task:** `VLM-2` (branch `feature/vlm-2`)
> **Parent:** [caption-context-enrichment-assessment-2026-07-05.md](../assessments/current/caption-context-enrichment-assessment-2026-07-05.md) §6a–6c (harness MVP, golden taxonomy, metric stack) — this scope materializes that future work and extends it with face-recognition precision/recall.
> **Intake mode:** per operator instruction, open questions answered from engineering heuristics (`literature/extracted/refactoring/distilled/`, Apple face-recognition papers in `literature/extracted/recognition/apple/`) with assumptions recorded — not deferred to the user.

## Ask (verbatim intent)

Bare-functionality eval harness for the description service that measures caption quality (assessment §6c stack) **and face-recognition recall & precision** against labeled faces. Ground truth: the previous test bed — `/Volumes/Butter/archives/archived-recognition-service/scripts/mock_images/` (38 scene photos) + `scripts/mock_entities/` (18 face crops, person names encoded in filenames). Runs locally, no new auth, remote OCI A1 service does all inference (M1 8 GB laptop does no model work).

## Intake Q&A (heuristic-answered)

**Q1 — Smallest shippable cut?** One CLI (`scripts/eval_captions.py` or small package) + one golden manifest. Reads manifest → calls the *existing* remote endpoints (`POST /scene/describe/multipart`, recognition identify path) → computes deterministic metrics → emits E19-1-schema JSON + markdown report. No UI, no DB writes, no CI gate, no new server endpoints. *(Farley: smallest shippable cut, start with a real feature; YAGNI: judge tier is a stub flag in slice 1.)*

**Q2 — Face P/R: what exactly is counted?** Two stages reported separately, because the Apple pipeline and ArcFace-lineage papers treat detection and identification as distinct evaluations:
- **Detection level:** faces found vs. faces labeled present (per image).
- **Identification level:** identity assignments above the service's operating threshold vs. labeled identities. Precision = correct IDs / all IDs asserted; Recall = correct IDs / labeled identities present.
- **Aggregation:** micro (overall) **and macro per-identity** — Fair-SA's per-cohort sensitivity argument: one over-represented person must not mask another's failures.
- Fixed operating threshold only in MVP (the service's production threshold). No ROC/TAR@FAR sweeps — those need constructed verification pairs (ArcFace protocol) and are out of scope until the harness exists.
- A detected face that matches **no** roster entity and is labeled as a stranger = true rejection (counted, not penalized). Wrong-name-on-roster-person = the top-severity error class (ties to assessment Must-Right gate).

**Q3 — Completion signal?** `make eval-captions` (target name final at plan time) runs on the laptop with only network access + existing `.env` API key; completes the 38-image manifest; emits JSON + markdown with caption tier-1/2/5 metrics + face P/R (both levels, micro+macro); a committed baseline artifact; a re-run reproduces identical deterministic numbers. Full run ≤ ~30 min against the fast tier.

**Q4 — Edge cases?** Zero-face images (P undefined → `null`, never 1.0); person present but not in roster (true rejection); same person in multiple crops (dedupe by identity, not by face); `person_naming` policy-disabled fixtures excluded from insertion-recall denominator; remote timeout/unavailable → per-image failure recorded, run continues, non-zero exit after bounded consecutive failures (rg-007); cache-hit vs cold responses recorded as provenance (deterministic metrics must not depend on which).

**Q5 — Non-functional (question-bank triggers):**
- *Failure mode of remote dependency:* per-request timeout (config; default 120 s fast tier), fail-per-item + continue, circuit-break after N=3 consecutive failures (Nygard: timeouts, circuit breaker, fail fast).
- *Idempotency:* pure read path + local artifacts; safe to re-run (server side only populates its normal describe cache).
- *Load discipline:* concurrency = 1 against the shared A1 box — the live demo must not degrade (Nygard SLA inversion).
- *Staleness/provenance:* every artifact stamped with model/adapter version, manifest version, git HEAD SHA.
- *Auth interpretation:* "no auth needed" = no new auth flow, no interactive login — harness reads the existing dev API key from `.env`/env var. **Not** an unauthenticated endpoint (would breach tenant RLS posture).

**Q6 — Where do fixtures live?** 59 MB total (38 MB images + 21 MB crops) → **not vendored in git**. Manifest (small, in-repo at `scene/tests/seed/golden.json`) carries per-image `sha256` + relative path; images live in an operator-provided `GOLDEN_IMAGES_DIR` bootstrapped by a documented one-line `rsync` from the archive volume. Missing/mismatched hash → fail fast at load (rg-008: validate config/fixtures at load time).

**Q7 — Ground-truth labeling?** Roster = the 18 `entity-*` filenames (names parsed from filename). Presence labels per scene photo: draft generated from filename heuristics (`ccqw-candid.jpg` → candid…), then a **single human confirmation pass** over the 38 images recorded into the manifest. The celebrity-style dataset (names-in-filename convention) is the same convention; per operator instruction the 38-image test bed is the corpus — no external celebrity/LFW ingestion.

## MVP scope

1. Golden manifest schema + generator draft (filename heuristics) + operator confirmation pass → `golden.json` (labels, context-pack fixtures, Must-Right/Easy-Wrong rubrics for the caption tier, expected identities).
2. Remote-client harness CLI: manifest → OCI endpoints (describe + recognition), concurrency 1, timeouts, circuit breaker, per-item failure isolation.
3. Metrics: caption deterministic tier (insertion rate, Must-Right string/policy gates, FKRE, length error, repetition, tag coverage) + face detection-level and identification-level P/R (micro + per-identity macro).
4. Reports: JSON artifact (E19-1 schema extension) + markdown summary (regression-harness report-builder pattern; dedupe/ignore-list for triaged false positives).
5. Baseline run committed as evidence; `make` target + README.

## Success criteria

- One command, laptop-local, zero model weights downloaded locally, zero new auth surfaces.
- Deterministic metrics bit-identical across re-runs on unchanged manifest+service version.
- Face identification P/R reported at both levels, micro + macro, with wrong-name errors listed individually in the report (top product risk visibility).
- Insertion-rate and Must-Right results consumable by assessment §12 sequencing (bake-off gate).

## Not-doing

- ROC/threshold sweeps, TAR@FAR pair verification (needs pair protocol — future).
- LLM-judge tier implementation (flag + interface stub only).
- CI gating, dashboards, UI.
- New server endpoints or auth changes; any laptop-local inference.
- Celebrity/LFW or any external dataset ingestion.
- Fairness cohort analysis beyond per-identity macro (Fair-SA full treatment = future).
- Vendoring the 59 MB image corpus into git.

## Assumptions (explicit)

- The 38-image + 18-crop archive test bed is available at the documented `/Volumes/Butter` path on the operator machine; harness treats its absence as a clean, actionable failure.
- Existing recognition endpoints expose per-image identity results sufficient for identification-level scoring (verify at plan time; if only cluster-level exists, plan adds a thin read path — no new writes).
- The dev `.env` API key grants access to a non-production tenant safe for repeated eval traffic.
