# Rounds 2026-10-17: operator reference and measurement receipt

This packet is submitted for independent **operator-artifact merge review**. The filename does not confer acceptance: research quality is **NOT_READY**, and no model is qualified, ranked, selected as a winner, or promoted by this packet. Existing software and bounded diagnostics can be used within their stated contracts; GPU fit, caption quality, retrieval quality, detection recall and clustering quality remain unestablished.

Source: `444d9cd4dbec96da1c63eec5143cc62af714ce44`, tree `7a7cf64e1579296deafaa090b67468a8f846d9dc`. The native remote worker verified the history-stripped transport by tree/provenance, without asserting unavailable ancestry. [accepted-packet.json](accepted-packet.json) contains full model revisions, machine-readable prerequisites, metric units, command templates, evidence digests and current validation receipts.

The six original experimental packets are rejected review subjects. Their old experimental protocols are retired as operator instructions; unreviewed alternatives confer no authority. This reference incorporates the independently sourced corrections without modifying or publishing those parents. All earlier attempts remain immutable in the source snapshot. Evidence is attributed to its original attempt; historical checks below were not rerun here. Canon v0.26.2 informs the boundaries: PROV-01/GRPH-14 and Principles 9/13 require traceable evidence before commitment; CARD-03 keeps unknowns explicit.

## Models and runtime identity

The sealed authority is `apps/prototype-description-service/scripts/eval_harness/bakeoff_candidates.yaml`; research intake is adjacent `bakeoff_intake.json`. The following is qualification scope, not a performance order. JSON includes revision-specific public model URLs and exact registry component names.

| Registry/intake ID | Artifact treatment | Operator status |
| --- | --- | --- |
| `minicpm-v-45` | MiniCPM-V-4.5 Q5_K_M | Sealed; runtime qualification pending |
| `gemma-4-12b` | Gemma 4 12B QAT q4_0 | Sealed; runtime qualification pending |
| `qwen38-27b`, `qwen36-27b` | UD-Q4_K_XL generation pair | Sealed; matched-recipe qualification pending |
| `minicpm-v-46` | Q4_K_M | Conditional: complete component inventory and whole-model bytes UNKNOWN |
| `qwen3-vl-8b` | BF16 | Separate vLLM qualification; unsupported by generic llama.cpp planner |
| `mimo-v2.6-distill-qwen-9b-gguf` | MiMo V2.6 Distill Qwen 9B Q4_K_M first; Q5_K_M optional follow-up | Observed intake revision only; no sealed row or serving qualification |
| `qwen3.8-27b-gsq-rco-gguf` | ISTA GSQ-RCO IQ3_S | Conditional numerical-change comparison; observed intake only |
| `qwen3-vl-30b-a3b` | Q4_K_M | Frozen GPU incumbent anchor; actual comparable record required |
| `florence-2-base-ft` | BF16, CPU | Frozen CPU incumbent anchor; actual comparable record required |
| `florence-2-large-ft` | BF16 | Optional family comparator; separate Transformers qualification |

Preserve all sealed revisions. MiniCPM 4.6's 529,101,504-byte listed weight is not a whole-model budget; required backbone/shards/projector completeness is unresolved. Declared GB and listed disk bytes establish neither VRAM fit nor KV headroom. Qwen incumbent preflight accepts build ≥b6887; Qwen 3.8/3.6 require >b6887 numerically, with their exact supported requirement unproven. These are bounds, not actual runtime pins. MiMo's b10964 identifies quantizer provenance, not a serving minimum. Record actual runtime build/digest, complete weight/projector identities, precision, context and vision recipe before measuring. Upstream declared terms, absent quantizer metadata and unresolved applicable terms remain separate; omission establishes neither licence clearance nor prohibition (CARD-26/29).

## Images, labels and report scope

The fixture namespace has `scene/tests/seed/bakeoff_golden.json` (selection10), `held_out_golden.json` (report20) and `golden.json` (regression37), relative to `apps/prototype-description-service`. Regression containment is intentional. Fixture selection/report IDs and recorded hashes are disjoint; that alone does not prove subject disjointness or satisfy the report's subject-evidence guard. Do not join their numeric IDs to the separate benchmark selection10 or corpus646 namespace.

Verified historical content inventory: heldout20 has 20 contents found, 11 renamed; regression37 has 36 found, 16 renamed, one absent. Individual selection10 physical coverage is UNKNOWN here. Names do not establish content identity. Keep the hash-resolution map private and qualify the actual loader/path mapping before a run; content availability alone is not loader qualification. Use `scripts/eval_harness/manifest.py:resolve_verified_image` and `load_manifest` under their actual contracts.

The source catalog `benchmarks/manifests/corpus-catalog-v1.json` resolves corpus646-originals: 643 matched, three missing, zero mismatched/unsafe, **incomplete**. It checks original `sha256_source`, without derived-hash fallback. The accepted 640 frame excludes three duplicate-source entries and three already-declared missing originals; no silent replacement. The correction's 11 original-hash joins/629 remainder is diagnostic only, not an approved new pool. Transformation lineage and actual set usage still need resolution.

Preserve existing operator-confirmed identity/count labels. This packet establishes no independently boxed or full-caption-fact report gold. Audit and reuse qualified portions of `benchmarks/manifests/golden150-draft-20260723.json` and `golden150-selection-v1.json`; their existence does not establish qualified Golden-100 report coverage, nor permit substitution. Do not redraw frozen fixtures from filename misses or cross-namespace collisions.

Coverage should include genuine groups, unknown people, no-face images, pose, occlusion, eyewear, low light, spatial relations, text and non-person scenes. Keep synthetic controls separate. Freeze the appropriate identity/event/source/session or group partition before calibration and reporting; retain subject-evidence refusals. Accepted `docs/scopes/descqual-2-fact-annotation-pilot.md` uses the whole-IMAGE estimand: n198 at assumed ICC .20 for planning, n239 at .30 for sensitivity, and B_eyewear's own precision floor (48/80 after its clustering allowance). The ~30-image pilot measures annotation cost/instrument behavior, not ICC. No new universal slice/cohort precision gate is adopted (EVAL-04, Principles 15/20).

## Existing tools and a correctly bound run

Commands run from `apps/prototype-description-service` with a qualified interpreter. JSON provides argv templates with explicit preconditions and full expected rosters. Private values are supplied at execution; output directories must be new, unique and outside the evictable cache. Templates were checked only as recorded in JSON; none is a live execution receipt.

```bash
python -B -m scripts.eval_harness.bakeoff_runner --json
python -B -m scripts.eval_harness.bakeoff_runner --only qwen3-vl-8b --json
```

These are dry planning calls: historically six llama.cpp plans (including `kimi-vl-a3b`, outside this focused shortlist); the second call refuses unsupported vLLM with exit 2. Across all 16 sealed rows: six planned, seven unsupported-stack refusals, three noncompeting/reference refusals. Planning proves neither component completeness nor runtime fit. Other stacks and intake arms require their own qualification; registry eligibility is not changed here.

After separately admitted target/runtime and residency prerequisites, use the existing chain: `bakeoff` raw run → `cli score` → `build_bakeoff_report`. Source anchors are `scripts/eval_harness/bakeoff.py:build_parser/main`, `cli.py:main`, and `build_bakeoff_report.py:build_parser/_gate_evaluation`. Freeze v3 plus `--two-pass`, context treatment, caption length, per-pass token limits, image preprocessing/token budget, seed/sampling, precision, complete model/projector and actual runtime identity. Retain raw outputs, per-image attempts/errors, pass timings and explicit denominators. Compare paired no-context/context-supplied treatment under a frozen human-validated contract; bare-image fluency cannot stand in for context use (CARD-19/23).

```bash
python -B -m scripts.eval_harness.bakeoff --endpoint "$QUALIFIED_ENDPOINT" --model-id "$MODEL_ID" --model-version "$QUANT" --model-revision "$VERIFIED_REVISION" --manifest "$REPORT_MANIFEST" --prompt-variant v3 --two-pass --caption-length standard --out "$NEW_PRIVATE_OUT/run.json"
python -B -m scripts.eval_harness.cli score --manifest "$REPORT_MANIFEST" --run-record "$NEW_PRIVATE_OUT/run.json" --rubric-gate enforce --allow-refused detection --allow-refused identification
```

These are conditional interface templates, not a complete serving protocol. `--model-revision` stamps a supplied value only: verify expected components and actually served runtime first. Apply the frozen per-arm recipe, including reasoning controls where required; JSON names settings omitted from this compact template. `--limit 0` is invalid. Live runs also require the existing environment admission gate. No API was called here.

Keep selection diagnostics separate from the final report. Bind every candidate, actual incumbent and all four baseline records to the SAME intended report manifest. Supply the complete sealed expected competing roster and both incumbent IDs, plus the actual selection manifest in its resolved namespace. `--run ID=PATH`, `--baseline-run LABEL=PATH`, `--expected-candidate`, `--expected-incumbent`, `--selection-manifest`, `--score-ok ID=PATH` and `--bakeoff-gate` are existing report flags. The JSON template expands all sealed competitors; focusing this guide does not narrow the report contract.

Baseline labels are `zero_rule_context_echo`, `context_only_heuristic`, `current_production`, `blinded_human`. Current-production baseline and incumbent records must reflect real execution. Write score markers only through successful-score control flow, as in `bakeoff_runner.py:_emit_ready_run_lines`; never manually touch them. The gate checks candidate-marker existence, so retain the actual scorer exit/report for every comparison arm. Missing records, qualified gold, subject evidence or comparability leave NOT_READY. Do not use foreign-run/relabel bypasses to make mismatched splits pass.

## Description and name-binding measurement

`scripts/eval_harness/caption_metrics.py:insertion_rate/name_precision/wrong_name_image_rate/fabricated_fact_rate` emits different units; retain their numerators, denominators and exclusions separately:

| Surface | Correct interpretation |
| --- | --- |
| Insertion | Inserted / (inserted + missing identities), policy-eligible rows only: pooled identity coverage; null with zero eligible identity trials |
| Name precision | Correct eligible insertions / all asserted name entries across all rows; disabled-policy naming does not become correct; null if no assertions |
| Wrong-name image rate | Images naming anyone absent / all scored images; present-name policy violations are a separate count |
| Trap-caught fabrication | Images triggering authored traps / declared image exposure (`all` or `trapped`); no authored traps → null; incomplete hallucination coverage |
| Phrase binding | Separate identity-to-phrase/geometry ledger: wrong person, omission, unbound phrase and abstention; name presence alone cannot prove binding |

Use `scripts/eval_harness/name_binding_eval.py:evaluate_bytes/main` with a qualified v2 phrase ledger. General supported visual facts, omissions, fabrication, spatial and role correctness require independent judgments. FactKind is OBJECT/ATTRIBUTE/COUNT/RELATION/SCENE/TEXT; TRUE/FALSE is polarity and LEFT_OF/RIGHT_OF is spatial relation. There is no dedicated role metric established by these enums.

Use blinded, randomized paired human fact review with position counterbalancing and length matching/reporting. Define claim units, critical strata, missingness, per-stratum denominators and dependency-aware uncertainty before comparison. Intervals for the proposed richer review are not implemented scorer outputs; pooled identity trials cannot inherit image-independent Wilson assumptions. Listening time is a cost; a facts-per-time composite requires validation before gating (EVAL-11/14, CARD-24/30). Seeded anchor regeneration/positive-negative controls and 219 historical tests establish determinism/contracts, not caption quality. Zero-rule 20/20 is an unvalidated proxy, with no authored traps and null fabrication rate; its zero latency is not inference timing.

## Detection, AuraFace and clustering

AuraFace is an ArcFace R100 recognizer/embedder; YuNet is the separately pinned detector. The 18-fixture runtime smoke fed raw fixture photos: finite unit-L2 512-d AuraFace and 128-d SFace outputs in distinct fingerprinted spaces. Five-point alignment and per-crop label qualification were not established. Repeatability is runtime evidence, not recognition quality; never reuse vectors/centroids across spaces (EMB-01).

The original three-arm detection smoke completed 19/37 scenes before the 3,500,000 kB RSS watchdog under a 4 GiB cap. ORT/OpenCV count agreement is not truth. Source .9 is not deployment parity with the historical .85 override; .3 is sensitivity-only, not threshold selection. The first 2 GiB OOM receipt's ordinal alignment remains walltime-inferred, and the run-2 executed runner's byte identity remains UNVERIFIED.

Latest resource receipt: D4 DETECT-REPRO admitted zero calls because swap0 and the private output mount failed preflight. D5 DETECT-MATRIX verified its own native unit, kept 4 GiB, changed only its own transient swap limit to zero, checked child inheritance/private writes, and sealed the new protocol/runner before calls. This is the closest documented recipe with verified image order, not a byte-proven original replay.

| D5 variant | Calls and observation |
| --- | --- |
| A: two default ORT sessions + resident OpenCV | 58 completed + one interrupted; RSS 3,504,484 kB at ordinal 19, second ORT arm |
| B: same ORT sessions, no OpenCV object | 40/40; no trip; maximum per-call VmHWM 2,350,708 kB |
| C: two arena-off ORT sessions + OpenCV | 60/60; no trip; maximum per-call VmHWM 2,088,212 kB |

In this recipe both resident OpenCV and default-arena ORT retention are necessary for the trip; neither is shown sufficient alone. First OpenCV inference retained about 1.21 GB, accounting for the earlier unexplained footprint. No production repair or arena-toggle recommendation follows (DBG-01/02/11). D5 full unrounded returned-record digests (bbox/score/landmarks, declared encoding/order/dtype) match A/C 58/58 common cases and A/B 39/39; two C-only cases lack A counterparts. This is not raw tensor parity or recall. Earlier DIAG parity remains two-image, three-decimal rounded-box digest equality only.

D5 used 159/160 reservations, 158 completed calls, 160.87 recorded inference seconds plus ≤5.94 interrupted seconds (≤166.81/180). Corrupt-manifest control refused before load with exit 7 and zero calls; valid blank control was NOT RUN. A valid blank should process successfully and be assessed for false proposals; corrupt provenance should refuse. They are separate controls.

Detection P/R and truth IoU require independently annotated all-visible-face boxes, negative scenes and frozen truth/matching rules. For recognition/clustering, separate qualified oracle aligned crops from end-to-end fixed detections; upstream missed faces remain misses in the operational denominator (EVAL-16/17/20). Audit/reuse confirmed labels where applicable; obtain the additional annotation each claim needs.

Report pair false merges, pair precision/recall/F1, B-cubed, purity/completeness, splits/merges, noise and unknown/assignment coverage under a frozen partition with appropriate intervals. These are measurement requirements for future qualification, not new implemented metrics. Raw similarity connected components remains diagnostic until independent entity-boundary and residual-bridge pair verification exists; no replacement production algorithm is adopted (GRPH-18/22/23, CARD-12). Ceiling baselines are descriptive, with feasible metric-specific directions/comparators and prospectively accepted margins. A proposed nonnegative split definition is Σ max(0,n_t−1); zero assignments remain recall/coverage losses. Undefined denominators are null and cannot pass dependent gates. All 16 historical FIRBENCH findings remain OPEN, including frozen .063>.060 and .5565<.77 failures.

## Approved-context retrieval

EmbeddingGemma2 text+image loading is 440M per retained pinned primary material. The real encoder did not run: precomputed v2 fixture top1=1/3, MRR=4/9 and 75 historical tests are arithmetic/contract diagnostics. The card recipe uses bf16/fp32, not fp16; full model revision, exact task prompts, pooling including prompt, dimension, image preprocessing, precision and L2 normalization define a space. Leading-dimension MRL truncation plus renormalization is permitted under a new matched space identity; the chosen encoder-call route is reproducibility policy, not an operation-history constraint enforced by v2.

`scripts/eval_harness/semantic_selection_eval.py:EncoderContract/_evaluate/main` accepts `approved_context` only and ranks every approved candidate in one document for every query. `source_id` is not an eligibility filter. A request/tenant/eligible-pool exporter and real encoder integration are **new work pending**, not implemented APIs. Default to separate documents; combine queries only with proof of identical eligibility. Enforce approval upstream; preserve query-specific policy/review/identity applicability. Global protected scope requires actual all-query applicability. Mandatory/protected retention is independent of cosine; neither similarity nor retention authorizes identity, names or phrase binding. Confirmation, geometry and naming permission are separate.

Media search needs a separate versioned task/corpus/query/relevance/eligibility/space contract; never relabel it into approved_context. Real qrels and deterministic/full-approved-context/random baselines precede quality claims. Current v2 emits top1/MRR; recall@k is only available if separately implemented, and nDCG cannot be claimed without graded gold. Judged no-relevant queries stay in denominators with RR zero; unjudged is different. EVAL-18 concerns face identification, creating no retrieval-threshold/API obligation. No duplicate evaluator is requested (EVAL-24, GRPH-36, CARD-18/23).

## Residency, measurement windows and readiness

The existing `bakeoff_runner.py:emit_shell` stops/waits for its server. It neither downloads weights automatically nor evicts them, and it removes a fixed prior run/score marker on rerun. Use immutable unique output directories outside cache; module-level output pruning is another reason to isolate each execution. The former fill commands are non-executable pending an owned cache procedure/executor; that executor and concurrent owned-memory collector are **new work pending**.

The authorized procedure has one loaded vision generator per measured GPU slot and one dedicated owned cache lease. Before load: inventory complete expected component bytes/hashes; measure actual target disk/RAM/VRAM; reserve download/temp/cache/runtime/report space and refuse insufficient reservation. Fetch one arm only, compare expected hashes, then record actual served identity. After the arm: preserve outputs/errors/timings/provenance, stop/wait for only the owned server, prove unload, release its lease after exit, clean only verified owned inactive weights/partials and verify free bytes. The next arm consumes that receipt. Failure preserves diagnostics and blocks advancement if exit/unload/cleanup is unproven. Never evict production, shared, foreign, active-leased artifacts or permanent reports (GRPH-31/32, CARD-06).

Current VRAM sampling starts post-ready and aggregates returned GPU-device usage; it is not an owned cold-load peak. RSS sampled by pgrep after server exit is not owned-process measurement. First-token, KV, owned RSS and cold-load VRAM remain UNKNOWN. A future approved collector must bind owned PID/start identity and GPU slot concurrently through load/inference, with lifecycle timestamps, sampling windows, CPU quota and units. Serve-to-ready timing must keep its actual window name.

No NVIDIA tool on this CPU orchestration VM proves nothing about OCI reachability. Earlier read-only OCI queries exited 1, leaving availability UNKNOWN; actual target capacity is unmeasured. The supplied orchestration envelope (4 vCPU, 3.25 CPU quota, 16 GiB user limit) is orientation, not a fresh admission receipt. Use dynamic resource guards; logical independence does not set concurrency and model staging is exclusive. Prior 17-clone `du -sb` accounting of 27.804 GB is not physical `df` space reclaimed. No fresh disk, sibling-cleanup acknowledgment or local unfinished CURUX completion is claimed.

Artifact review asks whether these two files accurately describe existing tools, evidence, prerequisites and pending interfaces against fresh main. Its independent final gate may establish **artifact merge readiness only**. Actual GPU/runtime receipts, comparable baselines, loader/subject evidence, qualified task-specific GT and accepted measurement protocols remain prerequisites to research readiness. No threshold, new mandatory code gate, runtime change, source edit or model adoption is authorized by this reference.
