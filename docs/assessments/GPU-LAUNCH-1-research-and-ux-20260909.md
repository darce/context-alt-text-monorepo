# GPU-LAUNCH-1 — Qwen30B entity-aware burst descriptions: launch evidence and UX inventory

**Date:** 2026-09-09
**Task / lane:** `GPU-LAUNCH-1` / original `launch-research`; this correction pass is `gpu-launch-public-preview`
**Status:** evidence-led assessment. **Not a deployment approval. Not a claim that demo.altcontext.com currently returns GPU-named captions.** Public `description_tier` labels are OBSERVED-FEATURE on this branch (preview implementation complete; GREEN 2105 family); **deployment still unverified.**
**Audience:** orchestrator + later eval/ops slices. Live OCI, secrets, and production mutation are out of scope.

This document answers one product question: what evidence is required before a visitor at `demo.altcontext.com` can trigger a burst GPU description from Qwen3-VL-30B-A3B that correctly incorporates roster named entities, and what is missing today.

**2026-09-09 `gpu-launch-public-preview` correction:** Sections 5/6/8/9 and ASCII were stale versus SSOT `apps/prototype-wp-alt-context/docs/ux-maps/public-demo-describe.{uxmap.json,md,notes.md}`. Existing `pytest scripts/test_vlm3_gpu_bakeoff_artifacts.py` is **runner-admission smoke**, not factual proof of launch claims. Official ux-map schema / critique / renderer are **not** passes. Docs-only; no schema, validator, product, lock, or runner-policy edits.

Canon cited at use time: [heuristics-canon](https://github.com/darce/heuristics-canon) stable IDs `TEST-15`, `RES-02/03`, `DATA-13`, `API-02/04`, `RLSE-03`, `GRPH-31–34` (also `GRPH-01/06/09`, `AGT-06`), plus evidence-before-commitment, [DDIA](https://dataintensive.net/), Latency, Release It!, PRINCIPLES. FIR v11 (2026-09-04) takes precedence over conflicting historical FIR sections; no new training in this pass.

---

## 0. How to read this (evidence classes)

| Class | Meaning in this file |
| --- | --- |
| **Measured** | Number or behaviour from a named artifact or from source that was read in this pass. |
| **Proxy** | Related measurement that does **not** answer the launch question (wrong path, wrong split, circular GT, superseded report). |
| **Inference** | Mechanistic reading of source. Not a live observation. |
| **Prior-art (not re-verified)** | Semantic/handoff claims injected by the dispatcher. Used as leads. Not treated as live proof. |

Degradation disclosures [GRPH-01] [AGT-06]:

- **Graph MCP / `cli search_graph` unavailable.** Names-to-caption and demo-trigger traces used exact source files named by FIR v11, UX maps, and GPUOPS-1. No full-repo scan. Coverage of unopened files is not claimed.
- **No production probe.** No HTTPS describe, no OCI start/stop, no secrets read. Live image `sha256:b88a09d` and “stale UID 10001 GID 999” remain prior-art until an operator evidence bundle records them.
- **Handoff MCP Python API not importable** in this sandbox (`workbay_handoff_mcp` missing). Decision IDs from the brief are cited as dispatcher text, not re-queried rows.
- **Git history is stripped** (sandbox `HEAD` has no parent). `uv.lock` is **present**. This pass measured `git hash-object uv.lock` = `3547d91088c0d85e26505b67a08029b47e376441` and SHA-256 `20cf024791b227f025b7adf2f3c185c566ff64bee5354933b1c2259548533a58`. Restoration path is **uncertain**: stripped history cannot confirm `HEAD^`, `git show main:uv.lock`, or a coordinator reverse-delta (`ef9f..bc`). Do not claim the lockfile is both “restored” and “not restored.” No `uv lock` regeneration and no lock/dependency edits in this pass.
- **Lane pytest is runner-admission smoke, not factual proof [TEST-15].** `python3 -m pytest scripts/test_vlm3_gpu_bakeoff_artifacts.py -q -p no:cacheprovider` only checks that the VLM-3 candidate JSON is parseable and that placeholders stay `kind=pending_report`. A green run does **not** validate caption quality, demo.altcontext.com, `description_tier` deployment, or any other claim in this file. Factual SSOT comparison against the public UX map, plus `git diff --check`, are the doc-validation steps.

FIR HTML was read in full: `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html` **219586 bytes**, SHA-256 `e13cda3a5d8c6bc8dc4732d5128a9ef466e95adad220069e5b25fad32366895f`. Title is **v11 · 2026-09-04**; the July filename is retained. Linked JSON/manifest/run files were hashed; contents used where they bear on named descriptions.

---

## 1. Verdict

**Production Qwen30B image descriptions with correctly incorporated named entities are not launch-ready on evidence.** Live production/UI proof is missing [RLSE-03] [TEST-15]. Deterministic GPU-tier naming fusion **is** already covered; do not treat that pipeline as untested.

1. **`context=None` on `describe/run` is intentional architecture, not an automatic defect.** Identity reaches the worker as `naming_inputs` / post-hoc fusion (`describe_run.py`). The product requirement is roster entities in the **final caption**, not names in the VLM prompt. Source inspection of the empty-context prompt is inference, not measured runtime evidence.
2. **GPU-tier positional fusion is covered by a fake-GPU test; live Qwen30B quality is not.** `test_fake_final_gpu_adapter_fuses_positional_names_and_disabled_run_does_not` (`apps/prototype-description-service/scene/tests/test_naming_provenance_gpu_tier.py` L156–176, helper `_run_fake_gpu` L134–153) runs FakeGpuAdapter enabled/disabled, asserts `COMPLETED` + `FINAL_GPU`, enabled draft `GENERIC + "Pictured from left: Ada and Bob."` with `naming.realizer=positional_fallback`, and disabled generic output. Wire serialization in the same file L295–353. GPUOPS-1 decision 9293 landed this naming/GID path; do not confuse the epic problem statement with current tests. Phrase boxes remain empty on the GPU adapter (positional, not span-grounded). **Absent:** live Qwen30B mention-level quality and production UI end-to-end proof on demo.altcontext.com.
3. **There is no admissible end-to-end identity-correct score for the live path.** FIR OEC (identity-correct description rate at fixed abstention) is **undeclared** (T-12). M-07 is undefined. The 646-image Qwen run has `identities: []` on every item and its caption-quality report is marked **SUPERSEDED**. Current production image/config remains unproven.

Ops start/stop is a **separate** launch gate (load snapshots, UID/GID, four producers). This lane did not actuate GPU. It does not convert ops gaps into caption-quality numbers.

---

## 2. FIR ingest — what transfers to a Qwen30B named-caption launch

v11 reading precedence: the 2026-09-04 reconciliation supersedes conflicting scheduling/corpus claims in historical v8 sections. No recognition improvement was measured in that HTML pass.

### 2.1 Admissible vs withdrawn (preserve provenance)

| ID | Metric | Value | Admissible for launch? | Provenance / limitation |
| --- | --- | --- | --- | --- |
| **Proposed OEC** | Identity-correct description rate at fixed abstention | undeclared | **No** — operator-reserved; T-12 not landed | Needs enrolled roster, present-enrolled set per image, name mentions per description, abstention **rule** not only rate [EXP-03] [EVAL-16] |
| **M-07** | End-to-end identity-correct rate | undefined | **No** | Same as OEC |
| **M-09** | Cost per accepted description | never computed | **No**; listed as ship guardrail | Needs OEC to define “accepted” [COST-04] |
| **M-08** | Open Images occlusion attenuation | val **×4.31 [3.80, 4.57]**; test **×4.33 [4.24, 4.46]**; occlusion prevalence val 32.61% [30.60, 34.63], test 32.04% [30.88, 33.21], train 53.91% [53.66, 54.17] | **Yes** as occlusion-corpus fact, **not** as Qwen quality | Single-face images; seed 20260728; B=4000; author-run unreplicated; `benchmarks/tools/openimages_occlusion_measure.sh` |
| **M-05** | Golden-150 recall 0.504 vs 0.995 | withdrawn | **No** | Agreement with buffalo, not recall |
| **M-06** | Open-set ID | non-mated reject **0.986 (204/207)**; FNIR@FPIR unmeasured | Partial (one arm) | Detector path, not caption path |
| **M-11** | Hard-face embedding margin | EASY +0.202 · HARD +0.012 [−0.034, +0.057] | **Hypothesis only** | No artifact; alignment/embedder not separable; rank-1 arm inadmissible for open gallery; pre-CVUP-1 |
| **M-12** | Masked ID buffalo 0.865 vs v2 0.321 | inadmissible externally | **No** | Unpaired denominators; detection-coupled; UNDER-FLOOR |
| **M-01** | 2.73 faces/image | YuNet t=**0.30**, 646 img / 1763 boxes | **No** as prevalence | Detector positive rate, not human count |
| **Dims** | FIR embedder ceiling **512D** | research decision | Irrelevant to Qwen serving | 768/1024 culled for distance concentration + 2× index cost |
| **Detector default** | `insightface` still default; FIR profile is YuNet → 5-pt align → SFace | source at FIR snapshot `ee330e96…` | Runtime ≠ checkout | OpenCV pin `5.0.0.93` in-tree; “merge CVUP-1 first” is obsolete as a checkout task |

False-name rate is a **mention-level** guardrail, not an image-level duplicate of the OEC. A system can raise identity-correct images while emitting more wrong names. That is the product-ending failure [EVAL-18].

### 2.2 Description corpus already paid for (do not recaption first)

v11 mining + `fir-occlusion-caption-mining-20260904.json` (SHA-256 `791a3bab…`, schema `fir.caption-occlusion-shortlist.v1`, status `candidate_mining_only_not_ground_truth`):

| Field | Value |
| --- | --- |
| Inventory | `corpus-manifest-v3r-20260814.json` SHA-256 `0198531b…` |
| Images / identities | **646** images; **591** personal + **55** editorial; **130** identities; **116** unlabeled |
| Older v3 (do not mix) | 137 identities / 108 unlabeled; eight entries differ |
| Description run | `docs/tasks/altq/bakeoff-results/run-altq-646-interleave-v3.json` SHA-256 `ea377f2e…` |
| Success / fail | **640** descriptions; **6** failures (`87, 172, 212, 330, 584, 610`) |
| Keyword shortlist | sunglasses 39; mask/scarf/veil 15; other cover 29; head-context 22; **union 95**, not the sum |
| Pixel join | `pixel_identity_verified: false`; `images_root` missing |

Keyword hits are **review candidates**, not occluded-face GT. 13/13 sunglasses tag retrieval is **not** occlusion recall.

### 2.3 FIR naming contract (code, not a measured rate)

v11 table, confirmed in source this pass:

`scene/application/fusion/reconcile.py::_reconcile_one_identity` drops a name unless **all** of: roster-bound `cluster_id`/`identity_id`, a detected eligible face, `resolve_naming_allowed`, and a surviving 1:1 geometric association. Otherwise `UNCONFIRMED_IDENTITY` / `FACE_NOT_DETECTED` / `NO_ELIGIBLE_IDENTITIES` / `AMBIGUOUS_GROUNDING`. Policy vetoes first: `person_naming` not allowed, unset `NamingPolicy`, or `agreement_enabled=false`.

A new head/body match does **not** become a usable name without that contract [API-04].

---

## 3. Measured Qwen3-VL-30B-A3B evidence (and what it is not)

### 3.1 ALTQ 646 interleave v3 — measured

Artifact: `docs/tasks/altq/bakeoff-results/run-altq-646-interleave-v3.json` (`acx-eval/v1`).

| Field | Value |
| --- | --- |
| Model | `Qwen3-VL-30B-A3B-Instruct` |
| Precision / quant | `Q4_K_M` |
| Adapter | `bakeoff` (eval transport, **not** `gpu_qwen30b`) |
| Prompt | `v3`, `two_pass: true` (`describe_facts` then `ground_weave`) |
| Endpoint | `http://localhost:8000` |
| Code SHA | `5a67b070fe8e383ffd243a77029d2225b6f8d700` |
| Started | 2026-07-16T23:33:28Z |
| Fetch manifest SHA-256 | `08751e69bf4d6bb4d4303f0bc7c38758f1f6fdaa60253828b7101ce5c2306d97` |
| Items | 646 unique `media_id`; 6 errors |
| Latency | n=646; **p50 5.273 s; p95 17.198 s; max 20.265 s; mean 6.778 s** (this pass, from the JSON) |
| `identities` on items | **all empty** (`items_with_identities = 0`) |

This run proves: the 30B Q4 checkpoint **can** emit 2–4 sentence captions on this corpus at ~5–17 s/image **when already served**. It does **not** prove: production adapter parity, roster-name insertion, GPU cold-start, or demo.altcontext.com.

VLM-3 bakeoff slate (`docs/tasks/vlm/VLM-3-gpu-bakeoff-candidates-2026-07-08.json`, status `candidate_slate_ready_pending_live_gpu_bakeoff`) still lists Qwen3-VL-30B-A3B-Instruct Q4_K_M as A10-tight (~18 GB of 20 GB usable). Placeholders are `kind=pending_report`. **Pending ≠ scored** [TEST-15].

### 3.2 Caption-quality report — proxy, superseded

`run-altq-646-interleave-v3-report.md` banner: **SUPERSEDED**. Do not cite as current evidence. Historical (contaminated split / pre-PRIV-1 roster spelling):

- insertion rate 0.890; name precision 0.684; wrong-name images 204/640 (0.319)
- Must-Right failed 56 / 530 rubric-defined
- mean gated score 0.627
- title hallucinated-name images 25
- face identification rows **vacuous by design** (bakeoff stub `analyze` / `media_identities`)
- fetch vs score manifest mismatch (`08751e69` vs `13999d33`)

Those insertion/precision numbers score the **eval bakeoff weave** (context block in the prompt, two-pass v3), not `GpuRemoteDescriptionAdapter` + `naming_preview` on `describe/run`. Using them as launch proof is a proxy-outcome error.

### 3.3 Production GPU adapter — inferred from source, not timed live

`scene/infrastructure/vlm/gpu_remote_adapter.py`:

- System prompt: weave names **from the context block**; “Never name or guess about anyone the context does not name.”
- Context is a flat `key: json-string` fence (`<<<CONTEXT>>>` … `<<<END_CONTEXT>>>`).
- `temperature=0`, `max_tokens=512`, `/no_think` before untrusted context.
- `prompt_or_task_version` default `"3"`; lockstep comment with bakeoff (`VLMRP-HARM-01`).
- **No `phrase_boxes`.** `AdapterResult` is caption-only (`objects=()`, no grounding spans).
- Provenance: llama.cpp served id unadorned; wire identity is `hub_repo@pin` when a revision is supplied (rg-015).
- Timeouts: connect 5 s, read **175 s**, max 4 concurrent calls.

**Inference:** even if WP sent IdentityContext on `/describe`, `describe/run` currently does not. Demo burst captions are generic VLM prose plus optional positional name injection.

---

## 4. Names-to-caption path (source trace)

Graph MCP unavailable [GRPH-01]. Exact files read:

```
WP roster / person_naming
        │
        ▼
DescribeController::submit_describe_run
  JSON { media_ids } only — no caller-supplied names
        │  multipart: tenant_id, media_ids, recognition_enabled, image_<id>
        ▼
POST /scene/describe/run
        │
        ├─ naming_inputs = (confirmed_faces, NamingPolicy)   # DATA-19 snapshot
        └─ VisualFactsService.describe(context=None)         # explicit; see describe_run.py
                │
                ├─ GpuRemoteDescriptionAdapter.describe
                │     context empty → "No context is available"
                │     no phrase boxes
                │
                ├─ Stage-2 reconcile: skipped when context_pack is None
                │     (attachments empty)
                │
                └─ Stage-3 describe_run_worker._apply_naming_preview
                      merge_identities(generic_draft, phrase_boxes=[], faces, policy)
                      → PositionalFallbackRealizer if faces else generic draft
```

Anchors:

| Step | File:symbol | Observed behaviour |
| --- | --- | --- |
| Demo / guided submit | `class-describe-controller.php:DescribeController::submit_describe_run` | `{ media_ids }`. “The browser has no image bytes.” Names are not a request field. |
| Public submit | `class-public-demo-describe-controller.php:PublicDemoDescribeController` | Allowlisted attachment ID only; delegates to the same pipeline. |
| Run describe | `describe_run.py` ~L242–251 | `context=None` **on purpose** so `context_hash` stays the empty digest (rg-015). Comment: identity reaches the worker as `naming_inputs`, not as a synthesized context pack. |
| GPU generate | `gpu_remote_adapter.py:GpuRemoteDescriptionAdapter._describe` | Prompt-weave path is dead on this route. |
| Fuse names | `describe_run_worker.py` `_apply_naming_preview` (~L387) | Rewrites `alt_text_draft` from `naming_preview`. Timeout/error → generic draft. |
| Merge | `identity_merge/merge.py:merge_identities` | Grounded if phrase boxes + containment; else positional if faces and **no** boxes; else generic. |
| Preview | `naming_preview_service.py:naming_preview` | “Empty for adapters without grounding, where naming degrades to the positional fallback.” |
| Consent | `fusion/reconcile.py:_identity_policy_veto` + `NamingPolicy.agreement_enabled` | GPUOPS epic: tenant flag is the single authority. |

Guided live UI states this to the learner (`docs/ux-maps/guided-prototype-live-description.md`): names come from the **server roster**, not from on-screen confirmations. On-screen names are disclosure, not payload [HAI-15] [API-02].

**Concrete entity-aware gaps on the burst path:**

| Gap | Why it matters |
| --- | --- |
| G1 `context=None` on `describe/run` | Intentional: names fuse after the VLM via `naming_inputs`, not via prompt weave. Not a defect unless live captions omit roster entities. |
| G2 GPU adapter has no phrase boxes | Grounded span replacement cannot run. Positional fallback is left/right order, not evidence that the name matches the person-phrase. |
| G3 GPU positional fusion tested (fake GPU); live Qwen30B/UI unproven | Cite `test_fake_final_gpu_adapter_fuses_positional_names_and_disabled_run_does_not`. Deterministic pipeline coverage exists. Live Qwen30B quality and production UI e2e remain gaps. |
| G4 Bakeoff two-pass ≠ production one-pass | 646-run quality numbers are a different prompt contract. |
| G5 Eval items carry `identities: []` | Cannot compute FIR OEC on that run even as a proxy. |
| G6 Naming budget skip | `_apply_naming_preview` keeps generic draft on timeout (`SKIPPED_BUDGET`). A “GPU success” item can still be unnamed. |
| G7 Cache key ignores naming snapshot | Empty context_hash means a generic GPU caption can be reused across roster changes unless naming always rewrites after cache hit. |

---

## 5. Demo-trigger path (source trace)

Existing flow (also in `docs/assessments/current/demo-landing-plan-2026-09-04.md`):

```
Browser
  → WP REST (public or admin)
  → backend POST /scene/describe/run
  → durable queued work
  → describe_load.dump_load_snapshot
  → host start timer → reaper.run_start_cycle → OCI START
  → describe_run_worker._wait_for_gpu_ready (/health, warmup timeout)
  → GPU inference → persist draft + tier
  → drained load → reap timer → OCI STOP
  → WP poll → UI state
```

| Surface | Trigger | Auth / bulkhead |
| --- | --- | --- |
| Public `[acx_demo_describe]` | `js/public/demo-describe.js` → `acx/v1/public/demo/describe` | Flag off by default; nonce; allowlisted IDs; 3/min/IP; daily cap 50; one in-flight lock |
| Guided “Describe it live” | `POST acx/v1/recognition/describe/runs` `{ media_ids: [id] }` | Admin; gated on face decisions + `acx_guided_live_media_id` |
| Workbench bulk | `POST describe/run` | Authenticated; cost CTA |

Worker GPU wait: `describe_run_worker.py:_wait_for_gpu_ready` — bounded health poll, cancel-aware, remaining-deadline ([RES-02](https://github.com/darce/heuristics-canon)). Defaults: warmup **510 s** (`DEFAULT_GPU_WARMUP_TIMEOUT_SECONDS` / `ACX_GPU_WARMUP_TIMEOUT_SECONDS`); generation **180 s** (`DEFAULT_GENERATION_TIMEOUT_SECONDS` / `ACX_DESCRIPTION_TIMEOUT_SECONDS`). These are **timeout maxima**, not measured durations. This pass did not time a live cold start.

**Deadline contract (source, not live):**

| Client | Wait ceiling | Server timeout maxima |
| --- | --- | --- |
| Public demo JS | **120 s** (`PUBLIC_DEMO_CLIENT_DEADLINE_CEILING_SECONDS`) — **keep this ceiling** | warmup 510 + generation 180 = 690 s **maxima**, not a measured cold-start |
| Guided live | 510 s cold / 180 s if submit reports GPU ready | same maxima |
| SSOT UX map `apps/prototype-wp-alt-context/docs/ux-maps/public-demo-describe.md` | 120 s poll ceiling; do not raise | 510+180 named as timeout maxima |
| Older inventory `docs/ux-maps/public-demo-describe.md` | still describes polling to the server deadline and a single “Description complete.” | **stale vs JS and vs the apps map**; not SSOT for this correction |

Do **not** claim a cold GPU burst categorically cannot finish inside 120 s. 510+180 are fail-closed caps ([RES-02](https://github.com/darce/heuristics-canon)); live warmup+inference duration is unmeasured here. A 120 s client stop re-enables the form and keeps the in-memory idempotency key; `POLL_TIMEOUT_MESSAGE` currently tells the visitor to refresh, which drops that key. Backend work is not cancelled. PROPOSED follow-up is same-run resume via the existing inflight owner plus that idempotency key only — no second paid dispatch, no authorization weakening for terminal-run reads ([API-02](https://github.com/darce/heuristics-canon), [RLSE-03](https://github.com/darce/heuristics-canon), Release It! bulkhead). Do not raise the 120 s ceiling.

Public completed labels come from **`description_tier`**, never from `gpu_state` ([DATA-13](https://github.com/darce/heuristics-canon)). Envelope `gpu_state` is unused telemetry. OBSERVED-FEATURE on this branch (`demo-describe.js:statusPresentation`); **not deployed**:

| `description_tier` | Completed status copy |
| --- | --- |
| `final_gpu` | GPU description complete. |
| `provisional_cpu` | CPU fallback draft (not GPU final). |
| `null` / missing legacy | Description complete, processing tier unavailable. |

Workbench `describeApi.ts:DESCRIBE_RESULT_TIER` remains a separate admin surface ([GRPH-31](https://github.com/darce/heuristics-canon)–[GRPH-34](https://github.com/darce/heuristics-canon)). Production is deployed; these public feature changes have not been deployed. Do not treat branch labels as live demo.altcontext.com proof ([RLSE-03](https://github.com/darce/heuristics-canon) [TEST-15](https://github.com/darce/heuristics-canon)).

---

## 6. UX-map inventory (observed vs proposed)

| Map | Path | Role |
| --- | --- | --- |
| Public demo describe (**SSOT for this correction**) | `apps/prototype-wp-alt-context/docs/ux-maps/public-demo-describe.uxmap.json` + `.md` + `.notes.md` | Anonymous curated picker; typed `description_tier` labels |
| Older public inventory (stale vs JS) | `docs/ux-maps/public-demo-describe.md` | Still shows a single “Description complete.” and server-deadline polling |
| Guided live description | `docs/ux-maps/guided-prototype-live-description.md` | Additive live run on a saved draft |
| Describe GPU tier | `apps/prototype-wp-alt-context/docs/ux-maps/describe-gpu-tier.md` + `.notes.md` | Workbench bulk + dashboard provenance — do not graft onto public ([GRPH-31](https://github.com/darce/heuristics-canon)–[GRPH-34](https://github.com/darce/heuristics-canon)) |
| GPU operator control | `apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.md` | Proposed start/stop/auto (GPUOPS) |
| Guided QM ASCII | `docs/assessments/current/demo/altcontext_guided_demo_qm_v1/ascii-screens.md` | Teaching flow; live run is optional last step |

**OBSERVED-UI / OBSERVED-FEATURE** = states implemented in JS/PHP on this branch (not deployed).
**OBSERVED-PRODUCTION** = public demo is deployed; these feature changes have **not** been deployed.
**Proposed** = refresh-safe same-run resume (owner + idempotency only); not implemented.

Official ux-map schema / critique / renderer are **not** passes. Critique 10316 ran the 8-rule pack via Pydantic `model_validate(extra=allow)` and retained 4 local extras; official strict `extra=forbid` still fails those extras. `workbay_canvas_mcp` renderer is absent (`OptionalRendererUnavailable`). Consumer TypeScript extra=forbid is a local gate only. Document follow-up; **no schema, validator, or product edits in this pass.**

### 6.1 Required states — public demo (OBSERVED-FEATURE on this branch; not deployed)

Source: `class-public-demo-shortcode.php` + `js/public/demo-describe.js` + SSOT notes ASCII.

```
IDLE
+-- Describe an image ------------------------------------------------------+
| Illustrative example — not a live result                                  |
| Alex stands beside a bicycle outside a cafe.                              |
| ( ) Lake          ( ) Path                                                |
| [ Describe selected image ]                                               |
| ● Select an image, then choose Describe.                                  |
+--------------------------------------------------------------------------+

REQUESTED / QUEUED
| ◌ Your image is queued for description…                                   |

WARMING  (120 s client ceiling kept; 510+180 are server timeout maxima)
| ◌ The description service is warming up. A cold start can take            |
|   several minutes…                                                        |

DESCRIBING
| ◌ Describing the image… 50%                                               |
|   gpu_state may be on the JSON; it is not shown and is not a tier         |

COMPLETED  (labels from description_tier only — never gpu_state)
| ✓ GPU description complete.                         final_gpu             |
| or ✓ CPU fallback draft (not GPU final).            provisional_cpu       |
| or ✓ Description complete, processing tier          null / legacy         |
|      unavailable.                                                         |
|   | <alt_text_draft; focus moved here> |                                  |

STOP / ERROR / LIMITED
| ! Another description is already running… (429)            LIMITED        |
| × The image could not be described. …                      ERROR/FAILED   |
| × 120 s client stop: wait, then refresh (drops in-memory key)             |
```

Implemented on this branch, **not** a missing product slice: typed `final_gpu` / `provisional_cpu` / `null` labels via `description_tier`. Remaining vs launch: **deployment unverified**; no public Stop control; PROPOSED owner+idempotency resume after refresh is not implemented; 120 s ceiling stays. Do not raise the ceiling to 510+180.

### 6.2 Required states — guided live (observed in reducer + map)

`GUIDED_LIVE_STATUS`: idle, blocked, queued, warming, describing, ready, degraded, timed_out, unavailable, cancelled.

```
IDLE     • Ready when you are.  [ Describe it live ]
REQUESTED/QUEUED  … Queued. Waiting for the service to pick it up.
WARMING  … Starting the GPU. A cold start can take several minutes.
READY    ✓ Done. The GPU wrote this.          tier=final_gpu
CPU FALLBACK  ! Done, but the GPU was not available, so the CPU wrote this.
FINAL GPU     same as READY; item.tier is the only proof
STOP/ERROR    timed_out / unavailable / cancelled; saved draft untouched
```

Guided live remains a separate admin/learner surface. Public demo now has its own `description_tier` copy on this branch; do not claim the public widget still has a single untyped “Description complete.” Do not copy Workbench GPU chips onto the public map ([GRPH-31](https://github.com/darce/heuristics-canon)–[GRPH-34](https://github.com/darce/heuristics-canon)).

### 6.3 Workbench GPU tier (map; parity tests exist)

ASCII in `describe-gpu-tier.notes.md`: cold CTA with cost, warming countdown, provisional CPU then final GPU, degraded-keep-CPU. Open question: no plugin Start/Stop (HAI-04) vs GPUOPS Burst GPU card. Not the public demo.

### 6.4 Operator control (proposed, not a public-demo requirement)

Settings › Burst GPU: start / stop / auto with load-snapshot freshness. Launch of the **anonymous** describe does not need this card, but trusted start/stop does ([RES-02](https://github.com/darce/heuristics-canon) [DATA-13](https://github.com/darce/heuristics-canon)).

---

## 7. Ops / runtime leads (not live-verified this pass)

Prior-art from dispatcher + source that does **not** prove current VM state:

| Claim | This-pass status |
| --- | --- |
| Source Dockerfile pins `uid=10001 gid=10001` (`Dockerfile` L131–141). Drifting gid 999 breaks group-write on `root:10001 0775` load dir (EACCES). | **Source measured.** Prod image GID 999 is prior-art (VLMHEAL-1 / decision 9612). Reuse the source pin; do not invent a second user story. |
| Effective compose reads env-dir `.env` (`docker-compose.env.yml` `env_file: .env`), not `secrets/.env`. | **Source measured.** `docker-compose.prod.yml` is documented as **not** the deploy path (`recognition-service.sh` uses `env.yml` + `admin.yml`). |
| API is the compose writer of `ACX_DESCRIBE_LOAD_PATH=/run/acx-write/${ACX_ENV}/describe-load.json`. `worker` (`recognition.worker.scan_worker`) has **no** load mount/env. | **Source measured.** |
| “Missing all four declared load producers blocks trusted GPU start/stop.” | **Prior-art.** This checkout shows one API writer in env.yml. Sibling lane must name the four producers; this lane did not query production. |
| GPUOPS-1 decision 9293 / merge `73e3be0e2`: GPU tier provenance + naming toggles on main. | **Prior-art.** Code for `DESCRIBE_RESULT_TIER` and naming preview is in this tree. |
| Live recognition image `sha256:b88a09d`, ~two weeks old. | **Prior-art.** Not pulled. |

Without all load producers publishing fresh `{queue_depth,in_flight,written_at}`, start-on-work and idle STOP are not trustworthy [DATA-13] [Release It! bulkhead]. That is an ops acceptance item, not a caption metric.

---

## 8. Acceptance evidence for an actual production launch

Do not mark launch complete without a bundle that names SHA, image digest, run_id, and clock times ([TEST-15](https://github.com/darce/heuristics-canon) [RLSE-03](https://github.com/darce/heuristics-canon)). Pytest `scripts/test_vlm3_gpu_bakeoff_artifacts.py` is **runner-admission smoke on the candidate JSON**, not factual proof of these claims.

### 8.1 Identity-correct GPU caption (product)

| Evidence | Pass rule |
| --- | --- |
| Model/quant/prompt | Served `Qwen3-VL-30B-A3B-Instruct` Q4_K_M (or recorded incumbent); `prompt_or_task_version` and one-pass vs two-pass recorded |
| Path | The **same** `describe/run` route the demo uses, not bakeoff.py |
| Names | Roster-confirmed identities present in the image; `person_naming=allowed`; agreement enabled |
| Mentions | Every present enrolled person named correctly; **zero** false names (mention-level) |
| Grounding | Provenance `naming.realizer` is `grounded` or an explicitly accepted positional fallback with a scored error rate |
| Negative | Unenrolled / unnamed people remain unnamed (“Never name or guess”) |
| Tier | Item `tier=final_gpu`; CPU draft must not count |
| Split | Sealed images **not** the superseded 646 report; FIR OEC or a declared substitute with abstention **rule** |
| Latency | p50/p95 including queue + warmup + inference + poll [Latency ch.2]; cost per **accepted** description |

### 8.2 Browser trigger (demo.altcontext.com)

| Evidence | Pass rule |
| --- | --- |
| Flag | `acx_public_demo_enabled=1` and allowlisted IDs on the deployed WP |
| Anonymous | Logged-out browser: select curated image → Describe → status → text |
| Cold start | First request from STOPPED: UI stays honest through warming. **Keep the 120 s poll ceiling.** Do not raise it to 510+180 (those are timeout maxima, not measured duration). PROPOSED resume is the existing inflight owner plus the in-memory idempotency key only — no second paid dispatch |
| Warm start | Second request after GPU ready: completed label is `GPU description complete.` from `description_tier=final_gpu`, never from `gpu_state` |
| Honesty | Branch labels: `final_gpu` / `provisional_cpu` / `null` via `description_tier`. **Deployment still unverified.** Missing tier must not be claimed as GPU [HAI-12] |
| Bulkhead | Rate / daily / one-run limits hold under double-click and refresh. Refresh drops the in-memory key; do not weaken `403 run_not_available` after inflight release ([API-02](https://github.com/darce/heuristics-canon)) |
| Cancel | Public: no silent second spend; guided: Stop cancels wait and best-effort run |

### 8.3 Start/stop / metering (ops, operator-run)

| Evidence | Pass rule |
| --- | --- |
| STOPPED idle | Viewing the page does not START |
| START | One accepted describe → load snapshot `has_work` → START → `/health` 200 |
| STOP | After drain + idle interval, OCI instance **STOPPED** (not merely STOP API 200) |
| UID/GID | Running API uid/gid can write the load path (10001:10001 source pin) |
| Producers | Every declared load producer actually publishes; missing producer = fail |
| Lease | Max-lease STOP still wins over operator `start` [RES-10] |
| Repeat | Cold burst twice; second cycle after idle |

### 8.4 Explicit non-evidence

- Green `pytest scripts/test_vlm3_gpu_bakeoff_artifacts.py` (runner-admission smoke only; not factual proof)
- Critique 10316 `extra=allow` (retained 4 local extras)
- Official strict ux-map schema `extra=forbid` (still 4 extras FAIL)
- Absent `workbay_canvas_mcp` renderer (`OptionalRendererUnavailable`)
- Consumer TypeScript extra=forbid / `uxmap-parity` (local gate, not official RULE_PACK)
- Insertion rate 0.890 on the superseded ALTQ report
- FIR M-05 / M-11 / M-12
- Seeded or CPU drafts
- Keyword occlusion mining counts
- Branch `description_tier` labels as if they were deployed to demo.altcontext.com
- This assessment file

---

## 9. Gaps that later slices must close (Qwen30B entity-aware burst)

1. **Do not manufacture a prompt-weave slice from `context=None`.** Names are designed to land via post-hoc `naming_inputs` fusion. Remaining launch work is live proof that the fused caption on demo.altcontext.com names present enrolled people with zero false names (G1). Existing fake-GPU positional fusion tests stay; no prompt-weaving repair.
2. **Score positional fallback as a first-class live error rate** (false-name / wrong-person) on demo images, or add phrase boxes if grounded spans are required. Fake-GPU fusion is already tested (`test_fake_final_gpu_adapter_fuses_positional_names_and_disabled_run_does_not`); live Qwen30B quality is not (G2, G3).
3. **Adopt or replace the FIR OEC and instrument T-12** on the production path (G5). FIR v11 precedence; no new training in this pass. Until then M-07 stays undefined.
4. **Keep the public 120 s poll ceiling.** 510+180 are timeout maxima, not measured duration; do not treat “cannot finish in 120 s” as a fact. PROPOSED follow-up is same-run resume via existing inflight owner plus idempotency only — no second paid dispatch, no authorization weakening, no ceiling raise ([RES-02](https://github.com/darce/heuristics-canon)/[RES-03](https://github.com/darce/heuristics-canon), [API-02](https://github.com/darce/heuristics-canon), [RLSE-03](https://github.com/darce/heuristics-canon)).
5. **Do not re-implement public tier labels.** This branch already labels `final_gpu` / `provisional_cpu` / `null` from `description_tier` (never `gpu_state`). Remaining gap is **deployment verification**, not a new product slice from this lane.
6. **Do not recaption 646 as the first action.** 640 descriptions exist; they are the wrong path for naming proof, but they are paid. Mine / review; new GPU captions only for the sealed demo set.
7. **Ops: restore UID/GID + load producers + compose env** before trusting start/stop. Caption work cannot greenwash a GPU that will not stop.
8. **Record a live evidence bundle** (EVID-1 / GPUSMOKE) on the deployed SHA. This lane produced none.
9. **Official ux-map schema / critique / renderer remain follow-up only.** Strict extra=forbid still fails 4 extras; critique 10316 extra=allow is not an official pass; renderer is absent. No schema or validator edits here.

---

## 10. Prior-art reuse (do not re-dispatch)

Already retrieved / in-tree; treat as leads:

- GPUSMOKE-1, GPUUX-1, DEMOLAND-1, EVID-1, FEBT-1
- GPUOPS-1 (naming + GPU tier provenance + intent journal); epic E23 exit includes named GPU captions
- VLMHEAL-1 Dockerfile 10001:10001
- FIR v11 work register R0 completed as documentation/mining, not a recognition benchmark

No review fan-out, no merge, no OCI from this lane.

---

## 11. Input completeness receipt

| Input | Bytes | SHA-256 | Used for |
| --- | --- | --- | --- |
| `fir-embeddings-dims-detectors-qa-20260723.html` | 219586 | `e13cda3a…fad32366895f` | Full read; OEC, M-*, v11 naming/mining |
| `fir-occlusion-caption-mining-20260904.json` | 127054 | `791a3bab…440aea59` | 640/6, keyword union 95 |
| `corpus-manifest-v3r-20260814.json` | 1974663 | `0198531b…a8b88b6` | 646 / 130 / 116 |
| `run-altq-646-interleave-v3.json` | 1470393 | `ea377f2e…c1d291ba` | Model/quant/latency; empty identities |
| `VLM-3-gpu-bakeoff-candidates-2026-07-08.json` | 5511 | `165c2256…54f631a` | Pending live bakeoff slate |
| FIR lane JSONs (dims/gtm/licensing/projects/umap) | hashed | see §0 command | Linked; not re-quoted into launch metrics |

Deliverable nonempty: this file.

`uv.lock`: **present**; this pass measured `git hash-object` `3547d91088c0d85e26505b67a08029b47e376441` (SHA-256 `20cf0247…533a58`). Restoration method is uncertain in this history-stripped sandbox (cannot confirm `HEAD^` / `main:uv.lock` / reverse-delta). No relock, no env mutation, no lock/dependency edits.
