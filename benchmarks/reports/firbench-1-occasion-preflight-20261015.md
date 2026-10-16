# FIRBENCH-1 · capture-occasion, source-unit and real AE-5/AE-6/AE-12 preflight (2026-10-15)

**Status: proposal and evidence matrix only.** This document inspects tracked metadata, reads the tracked AE definitions, and runs the in-repo corpus loader and PSU builder once on the two tracked corpus manifests. It runs no inference, no image or model execution, no Monte Carlo, and no outcome analysis. It does not qualify capture occasions, does not establish independence, and does not change any gate. Nothing here is a merge-ready, acceptance, or real-data claim.

**Scope rule.** Every absence below is bounded by the inspected scope: the tracked files in this checkout, the tracked corpus manifests, and the pinned external context listed in §1. None of it is a VM-wide or global absence claim. Identity and image proxies (shared named identity, duplicate hashes, dimensions, captions, slice tags) do not establish capture occasions.

## 1. Sources and pins

**Current adjudication scope (2026-10-15).** This checkout is an allowlisted, history-free minimal review bundle, initially commit `96a58af884912381ba2ee02cdb31f49eb507738b`, tree `2427948c3f480e564adc72d64e2fd1e187607355`. It is not the original full source tree. `benchmarks/review-context/safe-source-map.json` (sha256 `c47d154dd30da476830c2685de507b4d15ff2945a7cdbc8a77091c5c9b07b021`) records historical source commit `870710fd073d9c0937e01e25e69921a3fcc95e59` and tree `e24f827b1a818c821bfbdd776c02dd82ecd1786c`; these are source-map metadata, not current-tree identifiers or verified ancestry. Dispatch source `685c0757d425cf6c3649a6258705908106d98df6` is supplied provenance, not independently verified here. Before correction, this document's sha256 `1c2e8991b4a955b109c300c70b3ad0fd7f4fde062c389668bdb720490577f3dc` matched its source-map pin.

**Historical attribution boundary.** The introductory loader-run description and the observations retained outside sections 1, 8, 10, and 12 belong to the original author's dated 2026-10-15 pass. Their phrases “this pass,” “tracked,” and “this checkout” refer to that earlier inspected scope. Corpus manifests, images, identities, mappings, raw records, and the count snapshot were not reopened or reverified in this adjudication; excluded manifests are intentionally unavailable. Earlier aggregate observations and absence claims remain bounded historical attributions, not current corpus verification. Current checks are enumerated in §12.

| Source | Locator | Pin / release |
| --- | --- | --- |
| Historical corpus manifest v3r (S1 inventory frame of record) | `benchmarks/manifests/corpus-manifest-v3r-20260814.json` | recorded sha256 `2d9d5ba3e04bcfa7ea29f960b2fdc05431bdae7993bd22042a5369ceee7d9bff`; reported 646 entries, manifest_version 3; not currently verified |
| Historical corpus manifest v3 (Golden-150 selection reference) | `benchmarks/manifests/corpus-manifest-v3.json` | recorded sha256 `154eb2b735f947e5ce670886bb848fc2749aad5e952a448a4f1b75f3125abe7e`; reported 646 entries; not currently verified |
| Historical Golden-150 draft | `benchmarks/manifests/golden150-draft-20260723.json` | recorded sha256 `0dc89a1d0378630522a16080a176c1533357419fcfbe704a7c2bfc487580ac54`; reported 150 entries, 54-item roster; not currently verified |
| Historical decision manifest (reported unratified, unsealed) | `benchmarks/manifests/fir-bench-decision-v1.json` | recorded sha256 `7b89a3504d23b82c2a33e6fda1d52df2d181ec7d6bbfc9a5a24995c5f5ca5e2e`; not currently verified |
| Historical gate contract | `benchmarks/manifests/fir-gate-contract-v1.json` | recorded sha256 `22963fdc5ff6aa0dd9463ce6468d967783a0d998360d0f79e7ee2da456740573`; not currently verified |
| Current allowlisted S1 producer | `apps/prototype-description-service/scripts/eval_harness/firbench_frames.py` | sha256 `b40ac89c4153d2d5f23808cb513dc0d2e107e09e9cecc1d56cd7a285128e3857`, verified against source map; historical code anchors in §3–§5 |
| Current allowlisted S1 frame contract | `docs/tasks/firdv/firbench-1/S1-frames.md` | bytes match its exact file key in the source map |
| Current allowlisted task plan AE definitions | `docs/tasks/firdv/FIRBENCH-1-fir-benchmark-tool-task-plan.md:451–458, 598–600` | bytes match its exact file key in the source map; cited AE and status rows inspected |
| Current allowlisted inventory prose (prior VM observations) | `docs/tasks/firdv/firbench-1/inventory.md` | bytes match its exact file key in the source map; its corpus observations are historical |
| Tracer and binding references | `docs/tasks/firdv/firbench-1/README.md`; `docs/tasks/firdv/firbench-1/S6a-cli-run-score.md` | both current files match their source-map pins; `docs/tasks/firdv/FIRBENCH-1-scope.md:39` remains an unavailable historical reference |
| Historical v6 simulation report (failed numerical gate; preserved) | `benchmarks/reports/firbench-1-simulation-v6-20261015.md` | unavailable here; recorded run source `2ff389e7`, tree `943a9131`, acceptance sha256 `809b2ed1f796fa89956d4e7bc104c966f8d5b3dbe12f39e1eb70355206151183`; not currently verified |
| Acceptance status summary, inspected now | artifact `full-mc-acceptance-receipt.json`, JSON pointers `/evals/AE-5`, `/evals/AE-6`, `/evals/AE-12`; external path withheld | verified sha256 `0362ff0f1c79ec47d13f65c00e8643cccc737305e06895329367a2769cfb393d`; each status is `pending`; not an approval-search receipt |
| Review status summary, inspected now | artifact `full-mc-review-context.json`, JSON pointer `/real_data_evidence`; external path withheld | verified sha256 `da7251446d3a5b96b5623c48620593fa195304cd87f8337f2ccd9890dad58c27`; evidence “not established”; not an approval-search receipt |
| Historical laptop-side sanitized count snapshot | external path withheld | recorded source sha256 `119cd5fee486ae0e1fd7e8bbb4508507ba8df806726a6939180613dcea93760a`; not reopened; not an exhaustive frame or human QC |
| Canon release manifest, inspected now (read-only) | `meta/release-manifest.json` relative to the supplied canon mirror | verified sha256 `46636aa71f2e2e0c413b6ccff1cae4959543026c6ee7e4abde2bc7f30645a260`; release `0.26.2`, `heuristics-canon/release@5`, dated 2026-10-14; available-file verification in §12 |
| CARD-27 supplement, inspected now (read-only) | artifact `margin-and-design-effect-before-the-run.md`; external path withheld | verified sha256 `186c94c2b0ba88897cebea26c39752d6f0e87bbab8bff3ec1fa9aace79f85aad`; matches manifest `/reasoning/reasoning~1margin-and-design-effect-before-the-run.md/sha256` |

File hashes bind only the named bytes. Neither source-map pins nor status-summary scalars establish corpus admissibility, approval, human GT/QC, observation, capture occasions, budget, seal, or numerical acceptance.

## 2. Metadata inventory: what exists for capture occasions

Key-level inspection of the tracked manifests. Values are not copied; no names, alias maps, or raw identities are recorded here.

| Candidate occasion field | v3r | v3 | Golden-150 draft | Status |
| --- | --- | --- | --- | --- |
| `session_id` (entry or image) | absent (0 entries) | absent | absent | **absent**. The corpus loader never reads it (`load_corpus_manifest`, `firbench_frames.py:805–860`), so `ImageUnit.session_id` is None for every corpus frame. |
| `synthetic_parent_id` | absent (0 entries) | absent | absent | **absent**. The loader never reads it. |
| capture timestamp, EXIF, album, shoot, event | absent (none of the 24 distinct entry keys) | absent | absent | **absent** in tracked metadata. Originals are not in the tracked tree (inventory §2). |
| `built_at` | present (manifest build time, 2026-07-28) | present | — | build time, not capture time |
| `provenance.source` | present on 646 entries (two labels, counts 591 and 55) | same | present on 144 entries (`source`, `license`, `note`) | a source category, not an occasion. The 591 / 55 counts match the `personal` / `celebs` bucket split. |
| `provenance.license`, `consent`, `consent_register`, `subject_naming` | present on 646 entries (string values, not inspected here) | same | license and note only | consent and naming pointers; not occasion evidence |
| `duplicate_groups` / `duplicate_of` | 3 groups, 6 members, 6 `duplicate_of` entries | same | none | exact-duplicate records only (§4) |
| `sources` (six string values) | present | present | — | file references; their content was not inspected |
| `slice_tags` | present; hand-labelled on 150 images | same | `tags` present | image-condition labels; not occasion labels |
| `dropped_from_source` | empty list | not inspected | — | none dropped in v3r |
| per-image `width`, `height`, `bytes`, `sha256`, `sha256_source` | present on 646 entries | same | `sha256` only | image proxies; not occasion evidence |
| `named_identities`, `primary_identity`, `identities[]` | present (130 identities in v3r) | present (137 in v3) | `present_identities` | identity proxy; not occasion evidence |

Laptop-side count snapshot (counts only, §1): 646 records = 591 personal + 55 editorial, which matches the tracked bucket split. 588 unique personal content = 591 − 3, which matches the 3 exact-duplicate groups' extra records. The snapshot's 231 known components and largest component of 79 match the loader run in §3. `unresolved_sessions = true` agrees with the absence of any session field above. Two snapshot fields (`first_annotation_wave_unique` 263 and `challenge_candidate_count` 106) have no tracked counterpart and are not used here.

**Conclusion for occasions:** no tracked field records a capture occasion. Occasion independence is therefore **not qualified**. The 231 image–identity components in §3 are identity-connectivity components. They are a dependence proxy, not a capture-occasion partition.

## 3. Unit rules: code support versus data presence

`build_psu_components` (`firbench_frames.py:258–319`) builds one union-find graph with four edge types. The table records whether the tracked data can activate each edge.

| Edge | Code locator | Activated by tracked corpus data? | Evidence |
| --- | --- | --- | --- |
| image ↔ named identity | `firbench_frames.py:292–294` | **yes**: 584 named faces, 0 unknown, 0 unresolved | loader run, this pass |
| exact-duplicate group | `firbench_frames.py:300–301`; grouping at `:820–830` | **yes**: 3 groups, 6 images | loader run, this pass |
| shared `session_id` | `firbench_frames.py:302–303` | **no**: field absent and never set by the loader | no occasion partition exists |
| `synthetic_parent_id` sibling | `firbench_frames.py:304–309` | **no**: field absent; 0 synthetic siblings in tracked data | the rule is not exercised |
| unknown or unresolved face | no identity edge (`firbench_frames.py:292–294`) | 0 such faces in the corpus manifests | — |

Real loader run on the tracked manifests (single-threaded, aggregate output only, this pass):

| Quantity | v3r | v3 | Inventory value | Match |
| --- | --- | --- | --- | --- |
| images / faces / named faces | 646 / 584 / 584 | 646 / 584 / 584 | 646 / 584 (inventory §4) | yes |
| PSUs (components, duplicate edges applied) | 231 | 231 | 231 (v3r); 230 (v3) | v3r yes; **v3 differs** |
| largest component (images) | 79 | 79 | 79 | yes |
| components with m = 0 | 115 | 115 | 115 (v3r); 114 (v3) | v3r yes; **v3 differs** |
| face-count M̃ over m ≥ 1 | 24.401 | 24.401 | 24.401 (inventory §4) | yes |
| PSUs without duplicate edges | 232 | 232 | 232 (v3r) | yes |

Notes:
- The v3 row differs from the inventory on the same 646 entries and 584 faces (231 vs 230 PSUs; 115 vs 114 zero-face components). This pass does not resolve the difference. v3 is therefore **unreconciled**. The v3r figures, which are the frame of record, reproduce.
- The inventory cites a face-count M̃ of 24.401 and an image-count M̃ of 18.192. This pass recomputed only the face-count value, which matches. The image-count value and the report §0f value of 12.925 were not recomputed here; inventory flag 8 records that 12.925 reproduces on neither manifest.
- Without duplicate edges the count rises from 231 to 232, which matches the inventory's "components before duplicate merge" for v3r.

## 4. Duplicate and source units

- **Exact duplicates:** 3 groups of 2 images. In each group the two entries share one `sha256` and one `sha256_source` (checked this pass, aggregate only). Each group merges its two images into one PSU component, unless they are already connected through a shared identity.
- **Near-duplicates, sibling captures, and re-encodes:** no rule is exercised. The loader reads only the exact duplicate-group list. The 6 `duplicate_of` values agree with the 3 group memberships (all 6 members are in a group).
- **Source units for non-mated sizing:** the S1 contract (`docs/tasks/firdv/firbench-1/S1-frames.md`, Build 7) defines one background unit per frame image, plus exhaustive unknown faces and enrollment-excluded named faces. Tracked data supplies only the background units (646 placeholders). The inventory (§5) states these are not an admissible non-mated calibration pool without independent exhaustive GT.
- **Exhaustive marker:** zero matches for `exhaust` (case-insensitive) in v3r, v3, and the Golden-150 draft (checked this pass; §12).

## 5. Mated versus non-mated PSU distinction

**FB1-OC-GATE-01: sustained.** Named identity does not establish enrollment or mated membership. The score reader tests membership in the declared `enrolled_identity_ids` (`firbench_score_io.py:281`); primary scoring then selects the probability arm and `inventory.test_fold` (`:1076–1077`). The corpus loader instead assigns every image `SamplingArm.challenge` (`firbench_frames.py:847`). Thus the inventory below cannot size the primary mated test.

Second-dispatch provenance boundary (2026-10-15): this is an allowlisted orphan review bundle with no parent history, not the original full source tree. `benchmarks/review-context/safe-source-map.json` supplies original per-file pins; the S1 producer, score reader and S1 contract bytes match those pins. Corpus manifests and private inputs are intentionally unavailable. The counts and corpus observations in §§1–4 and §12 are earlier report attributions, not checks repeated in this dispatch; no loader was run here. The supplied historical source `685c0757d425cf6c3649a6258705908106d98df6` is not asserted to exist locally.

| Quantity | Unit | Built from | Evidence and qualification status |
| --- | --- | --- | --- |
| Named-box inventory | named boxes per identity-connectivity component, without enrollment selection | earlier corpus-loader observation in §3 | **584 named boxes**, with conditional component-size summary **M̃ = 24.401** over components containing boxes; 115 components had zero boxes. These are dated inventory observations, neither mated query counts nor n_eff. |
| Actual mated queries (face level) | independently annotated GT face enrolled in its declared leg/fold gallery | actual per-leg/per-fold `enrolled_identity_ids`; canonical PSU map; primary inference additionally requires the preregistered test fold and probability arm | **N, PSU sizes, design effect and n_eff unestablished.** Retain upstream missed mates in the eventual end-to-end denominator; do not select only detected or embedded faces. |
| Non-mated, unknown faces | unknown GT face in `fold`, only when `exhaustive` is True | `build_nonmated_pool`, `firbench_frames.py:509–519` | Earlier inventory reported **0**; not currently reverified. The function refuses any build unless `exhaustive is True` (`:486–487`); independent exhaustive GT remains required. |
| Non-mated, named faces of non-enrolled identities | named GT face whose identity is in `fold` and absent from the declared enrollment set | same, with actual leg/fold gallery membership | **unestablished** pending enrollment, fold/arm bindings and independent exhaustive GT |
| Non-mated, background units | one per image in `fold`, id `background:<image_id>` | `firbench_frames.py:520–523` (prefix at `:40`) | Earlier inventory reported 646 structural placeholders before fold/arm selection; not an admissible pool or qualified count without independent exhaustive GT. |

Mated sizing must use the actual eligible mated faces per PSU; non-mated sizing uses its own fixed source units per PSU, including backgrounds independently of detector output. A PSU may contain both. The non-mated builder computes its design effect separately (`firbench_frames.py:528`). Neither whole-GT `Frame.n_eff`, the named-box inventory, extra negatives nor the global 50-PSU floor establishes mated adequacy (`docs/tasks/firdv/firbench-1/S1-frames.md:64`). No qualified mated or non-mated value is calculated here. This applies [AUDIT-11], **Account for cluster design effect**, *Sampling: Design and Analysis*, ch. 5, and [EXP-23], **Pseudoreplication check**, *Statistics Done Wrong*, ch. 3 (Canon v0.26.2).

## 6. Real AE-5 / AE-6 / AE-12 preflight matrix

Definitions come from the pinned task plan (lines 451–458), whose bytes match the safe source map. **FB1-OC-GATE-02: sustained.** AE-12 line 458 explicitly makes cold/warm measurement the producer of the later warm-budget preregistration; that preregistration precedes the budgeted warm rerun and W5 budgets. Receipts are completion evidence, not inputs to their own producer. The README (`:189`) defines `timings.json` as a once-written, non-replayable attempt/timing receipt.

All real artifacts below are **pending / unverified in this dispatch**. Earlier absence/null statements are dated observations, not a new search of private inputs. A code/schema declaration or scalar cannot qualify the evidence.

| Gate / stage | Entry requirements | Producer output and consumer | Evidence status |
| --- | --- | --- | --- |
| AE-5 real-data canary | Authorized Golden-150 images/GT and 54-entry draft gallery; declared k = 5 seeded derangement before outcomes; unsealed frame; real bindings | Actual canary produces measured FNIR, false-name effect and paired CI for the AE-5 reviewer whether significant or not; sealed runs refuse canary legs | **pending**; prior roster counts are not current GT or run evidence |
| AE-6 legacy parity | Raw reference output with run source SHA, model pins, template/gallery hashes and 207-probe provenance; declared boundary mode | Actual replay supplies exact-count parity evidence to the AE-6 reviewer; `v2` lists changed outcomes | **pending**; historical 204/207 prose alone cannot establish parity |
| AE-12 first bounded tracer | Verified S3 core/file-IO/default-wire join and required lanes; named responsible owner; approved bounded physical run cap; preregistered 20-image subset/selection; real source/query, GT, template and per-leg gallery/enrollment bindings; ledger rule requiring every GT face in exactly one state per leg/arm | First real three-leg tracer produces ledger-coverage evidence and cold/warm `timings.json` receipts. The budget owner consumes the measured timings for warm-budget preregistration | **pending** entry, coverage and timing artifacts; no prior receipt or warm rerun is required to start this producer |
| AE-12 budgeted warm rerun | Recorded warm budget derived from the first tracer measurement; same bound diagnostic workload and coverage rule; approved physical cap covering the rerun | Bounded warm rerun produces its own pass/fail timing and coverage receipt against the preregistered budget; AE-12 reviewer consumes both attempts, budget record and bindings; W5 budget owner consumes the measurement and recorded rerun result | **pending** warm-budget record, rerun and completion receipt; no budget value supplied |
| Capture-occasion independence | Independently checked occasion provenance and duplicate/source-unit rule, fixed before outcomes | Authorized private frame producer supplies occasion/PSU evidence to sizing and eligibility reviewers | **pending**; inventory components do not qualify occasions |
| Independent exhaustive GT | Detector-independent annotation of every face, human annotator/QC evidence and exhaustive assertion | Authorized GT producer supplies the bound frame/GT evidence consumed by pool construction, ledger coverage and the reviewer | **pending**; a schema flag alone is insufficient |
| MEAS-29 observation | Bounded contextual inspection of measurement collection/adjudication by a person | Recorded process, exceptions and limits consumed by the GT/QC and acceptance reviewers | **pending**; software tests and synthetic readers cannot produce this human evidence |

AE-12 ordering follows the project task plan, not a canon numerical default. Naming the artifact and consumer applies [GRPH-32], **An edge exists only where data moves**, bootstrap practice label, and [GRPH-14], **Record provenance as a walkable lineage graph**, *Building Knowledge Graphs*, ch. 8, plus *Mental Models*, ch. 8 (Canon v0.26.2). S4 may start after verified S1/S2; AE-12 does not block that start (task plan line 458).

The task plan's VM wording is historical. Under this dispatch's privacy scope, any actual real runtime would stay local on the private host unless separately authorized by explicit non-Git permission. This proposal executes nothing and grants no runtime permission. Private identities, pseudonyms, mappings and row-level records remain outside Git, prompts and portable exports; only allowed code/schema/synthetic material, aggregates and hashes may be portable.

## 7. Historical real parity candidates (AE-6)

Read-only checks on the tracked files; no rerun of any inference.

| Candidate | Locator | sha256 (verified this pass) | What it pins | Legitimate parity reference? |
| --- | --- | --- | --- | --- |
| `face_unknown_rejection` = 204/207 = 0.986 (M-06 row) | `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html` (one matching line, inventory §7 cites line 399) | `59bb9aac7a744604586fe89cf7ede11da898cb58ff2e78cb083ab95baad144f7` | the value only, as report prose | **no, on current evidence**: raw bench JSON not found (inventory §7); no provenance file for the 207 probes (inventory §5) |
| Same value, executive summary | `benchmarks/reports/fir-executive-summary-20260728.md` (one matching line, line 57) | `f71cda9e032566818601663d24893c7acd111fa2b48546342c6aae8dd388a2a1` | the value only | **no**: same reason. A second copy of the same prose value, not an independent run. |
| Raw bench JSON carrying `face_unknown_rejection` | tracked tree | — | — | **absent**: `benchmarks/results/` does not exist in this checkout, and no tracked JSON contains the string (inventory §7) |
| Golden-150 FIR-8 bench output | `benchmarks/results/` | — | — | **absent** in this checkout |
| Model pins (sface, auraface, yunet) | inventory §1a | pins recorded there; the inventory records the weight locations as confirmed | model identity only | **partial**: pins exist; they do not tie to any run output |
| Template and gallery pins | `S0-contract.md:56` (`gallery_lineage.templates_sha256` = null) | — | — | **null**: no template hash is pinned |

Verdict: **no tracked legitimate parity reference exists in this checkout for AE-6.** The 204/207 value is report prose with no raw run, source SHA, or probe provenance behind it. The inventory's historical "not found" statements are bounded to the explicitly probed paths.

## 8. Tracer identity and budget approvals

- **Tracer definition** (requirement, not an approval): the current allowlisted task plan AE-12 row, line 458, specifies a 20-image, three-leg diagnostic run after the required S3 join. The earlier scope-file citation is historical (§1).
- **Recorded identity approval for the 20 images:** **null (unknown/pending)** in the bounded evidence below. No specific subset-approval artifact is established by those fields; no claim is made about a search of other artifacts.
- **Recorded budget approval, warm or cold:** **null (unknown/pending)** in the same bounded evidence. The current task plan's AE-7 row, line 453, says the real budget stays unset until AE-12 preregisters it. That is a policy/configuration statement, not an actual budget approval or a measured physical budget. The earlier unpinned policy-patch attribution and decision-manifest observation are not current approval verification.
- No physical budget (wall-clock, memory, token, or cost) is supplied, derived, or invented here.

The approval-evidence scope is exactly two named, hashed summaries from §1: `full-mc-acceptance-receipt.json` at `/evals/AE-12` records `status: pending` with `details: real-data evidence; not supplied to the simulator`; `full-mc-review-context.json` at `/real_data_evidence` records `AE5/AE6/AE12, independent exhaustiveGT/QC/observation/budget/seal not established`. These inspected status fields establish pending/unestablished evidence only. They neither identify approved images nor record an approving party and approved budget. The previous claim to have classified matches in 19 committed-producer artifacts is withdrawn: no reproducible inventory or search receipt is supplied. A specific approval artifact could change the approval status; an unset-policy statement cannot (GRPH-14; Principle 9).

## 9. Minimal required inputs before any real AE-5 / AE-6 / AE-12 run

This checklist separates pre-run entry requirements from artifacts produced during execution. Each real item is **pending / unverified** here and needs a responsible owner and recorded private location; no person is assigned or approval inferred by this proposal. The AE-12 producer chain below is the dependency order. Private records stay local under §6's boundary; pointers in Git must contain no private identifiers or row-level data.

1. **Occasion and frame provenance.** The authorized private frame producer records an occasion identifier per image with original-metadata provenance or operator attestation and an independent check. Sizing/eligibility reviewers consume that evidence; identity-connectivity components alone are insufficient.
2. **Duplicate and source-unit rule.** The frame owner fixes rules for exact/near duplicates, sibling captures and synthetic children before outcomes. The frame and non-mated-pool producers consume them. The earlier report's 3 exact groups require authorized private verification; they were not checked again here.
3. **Independent exhaustive GT.** The GT owner supplies detector-independent exhaustive annotation, annotator/QC evidence and the exhaustive assertion before the real tracer. Pool construction and ledger coverage consume it; a declared flag does not establish human work. `build_nonmated_pool` refuses a non-exhaustive input.
4. **MEAS-29 observation.** A responsible human records bounded contextual inspection of collection/adjudication, including exceptions and limits, for the evidence reviewer. Plan any observation of runtime production before execution and attach the resulting observation afterward; never require that observation's own output to start its producer. [MEAS-29], **Observe measurement production**, *Seeing with Fresh Eyes: Meaning, Space, Data, Truth*, ch. 4.
5. **Real source/template/gallery bindings.** The runtime/frame owner fixes source/query hashes, template hashes, per-leg/per-fold gallery hashes and actual `enrolled_identity_ids`, probability-arm membership and the preregistered primary test fold. Frame preparation, §5 sizing and score/receipt reviewers consume those bindings (`README.md:50`; S1 contract). Actual mated N, PSU sizes and n_eff remain unestablished until those bindings and independent GT exist, including upstream missed mates.
6. **AE-5 entry.** The canary owner supplies authorized Golden-150 images/GT for the 54-entry roster, a pre-outcome k = 5 seeded derangement, real bindings and an unsealed frame. The canary produces its measured effect and paired CI for review whether significant or not (task plan line 451); no result is an entry condition.
7. **AE-6 entry.** The parity owner supplies raw reference output with run SHA, model pins, template/gallery hashes and the 207-probe provenance file. The replay/reviewer consumes it. Without it 204/207 and 0.986 stay historical prose, not numerical acceptance.
8. **AE-12 approval and physical cap before the first attempt.** The approving party records identity/data authorization, a named operator and an explicit bounded physical cap covering the proposed cold/warm work. The operator consumes this approval before protected reads or spending. A rerun also requires an approved cap covering its work. Approval records and cap values are pending; no wall-clock, memory, token or cost limit is invented here.
9. **AE-12 entry and output chain.** The operator supplies the preregistered 20-image subset/selection, verified S3 join/required lanes, real source/GT/template/gallery bindings, coverage rule and item 8 approval. The first tracer then produces measurements for the later budget decision. All stages below remain pending; none executes under this proposal.

   | Stage | Named output | Downstream consumer |
   | --- | --- | --- |
   | Approved first bounded three-leg tracer | Cold/warm `timings.json` receipt(s) and ledger evidence that every GT face has exactly one state per leg/arm | Budget owner reads actual cold/warm measurements; coverage reviewer reads GT/ledger reconciliation |
   | Warm-budget preregistration after measurement | Recorded warm budget tied to measured timings, bound workload and rerun criterion, fixed before the rerun and before W5 budgets | Warm-rerun operator and eventual W5 budget owner |
   | Bounded warm rerun under approved cap | Its own timing/coverage receipt and pass/fail result against that preregistered warm budget | AE-12 completion reviewer, with the first receipt and budget record; W5 budget owner |
   | Receipt review and W5 budget setting | Reviewed evidence chain and recorded W5 budgets derived from actual measurements, with rerun result retained | W5 execution owner; a failed/missing rerun cannot establish AE-12 completion |

   The first run needs the approved physical cap, not a measured warm budget or a passing rerun. The warm rerun needs its preregistered budget. Neither attempt can be replaced by simulated/fixture evidence. This removes the input/output cycle without inventing a budget or making W5 budgets an entry condition for their own measurement producer.

10. **Frozen calibration/power experiment and later adoption.** Once an authorized real PSU structure and actual eligible populations exist, freeze the proposed experiment, seeds, estimands, methods, margins/MDE, harm directions, α allocation, case obligations and pass/fail rules before any calibration or power outcomes. Include the planned null (A/A-style) check on the real PSU map before reading a real effect. Size from the appropriate n_eff, not inventory counts ([EXP-12], **Power and practical significance**, *Trustworthy Online Controlled Experiments*, ch. 2). Run/review the fixed calibration and power gates before adopting a method or making a real effect claim; do not calibrate and then freeze the same experiment or change its rule to pass ([EXP-22], **No circular analysis (double-dipping)**, *Statistics Done Wrong*, ch. 6). CARD-27 requires pre-run sealing and design-effect sizing; it selects no interval formula or project gate. This proposal runs neither calibration nor power and changes no method contract.

Original v6 results remain **FAILED**: H2 boundary 126/2000 = 0.063 > 0.060 and cell-only power 1113/2000 = 0.5565 < 0.77, with original seeds and receipts unchanged; these are supplied historical results, not reruns. The 166 software tests and synthetic reader 6/6 establish no real human GT/QC, contextual observation, capture occasions, budget, seal or numerical acceptance. Adoption remains blocked on the actual required gates and evidence.

## 10. Canon mapping (release 0.26.2)

Locators are relative to the read-only canon mirror. The release manifest lists digests under `lexicons`, `docs`, and `reasoning`; it is not limited to the three lexicons used here. In particular, `/docs/PRINCIPLES.md/sha256` and `/reasoning/reasoning~1designed-unknown.md/sha256` exist. Both available files were independently hashed in this adjudication and match those entries (§12). The available CARD-27 supplement also matches its reasoning entry. “Not independently verified by the earlier author” does not mean “not listed.” Listing a file in the release manifest does not establish that its bytes are available in this mirror or were read.

The table retains the original task-reference mapping; it does not newly apply every listed rule as an adjudication gate. This correction uses GRPH-14 and Principle 9 for claim lineage. CAL-02's full row is checked as the task plan's AE-6 source reference, without turning it into a numeric parity or approval criterion. The user's least-privilege boundary limits reads to named safe sources and edits to the owned sections; no private corpus or mappings are needed.

| Rule | Locator | Use in this document |
| --- | --- | --- |
| EXP-12 | `lexicons/epistemics.md#exp-12` (line 329) | power and practical effect size from n_eff; no real n_eff exists yet |
| EXP-13 | `lexicons/epistemics.md#exp-13` (line 330) | governs the AE-5 canary (task plan line 199); null calibration on the real structure before reading an effect (§9 item 10) |
| EXP-22 | `lexicons/epistemics.md#exp-22` (line 339) | occasion scheme, duplicate rule, and tracer subset fixed without looking at outcomes; no outcome-based selection |
| EXP-23 | `lexicons/epistemics.md#exp-23` (line 340) | count independent occasion or PSU units, not images or faces |
| AUDIT-11 | `lexicons/ml-systems.md#audit-11` (line 331) | cluster design effect; the 231 identity components are a dependence proxy, not occasions |
| EVAL-16 | `lexicons/ml-systems.md#eval-16` (line 271) | upstream failure counts against the end-to-end metric (relevant to any detector-based non-mated denominator) |
| EVAL-18 | `lexicons/ml-systems.md#eval-18` (line 273) | non-mated probes are needed for a reject-capable identity system |
| EVAL-19 | `lexicons/ml-systems.md#eval-19` (line 274) | detector alarms must not add non-mated searches |
| CAL-07 | `lexicons/ml-systems.md#cal-07` (line 355) | identity-disjoint folds for thresholds (S1 Build 6) |
| CAL-02 | `lexicons/ml-systems.md#cal-02` (line 350; full row checked now), source `SOURCES.md#src-designing-ml-systems` (*Designing Machine Learning Systems*) | task-plan AE-6 reference: trigger is forced identity/class choice under weak evidence; “Unknown is a valid result,” with an explicit below-threshold action. This is not a numeric parity criterion or an approval record. The earlier author's failure to locate the row is historical, not a current locator gap. |
| PROD-31 | release manifest `rule_ids` (cited by the task plan for AE-12) | listed in the release manifest; its row was not located in the partial mirror's lexicons. A pinned producer policy record says the text sits in a lexicon outside the pinned mirror, so it was not read. |
| MEAS-29 | `lexicons/epistemics.md#meas-29` (line 294) | observation of measurement production; no record exists |
| GRPH-14; Principle 9 | `lexicons/graph-theory.md#grph-14` (line 117); `PRINCIPLES.md`, “9. A claim must walk back to what produced it” | keep historical attributions separate from current evidence; bind approval-status claims to the named summaries and exact fields (§1, §8, §12) |
| CARD-27 | pinned supplement (§1); the margin and design-effect card | freeze the experiment's margin, interval method class, harm direction, α allocation, and design-effect sizing before outcomes; any adoption follows the gates, without a calibration-to-freeze cycle. It does not select an interval formula or prescribe project numbers. |

The three lexicons, PRINCIPLES, and the available designed-unknown reasoning card match their manifest digests; CARD-27's supplement matches its listed digest (§12). Other manifest-listed reasoning files are not thereby verified. In particular, the in-mirror CARD-27 file and least-privilege card are unavailable at their listed paths; their listing is distinct from verification of their bytes. No formula, API, seed, receipt, or numerical gate is changed by these citation corrections.

## 11. Code observations and historical findings

- A historical S1 finding, recorded only in lane context and not in any tracked file, says that `build_nonmated_pool` checks key coverage but never validates the supplied partition. In this checkout the function does validate it. `firbench_frames.py:498–504` requires `component_map` to cover exactly the frame images, to equal `build_psu_components(images, faces)`, and to cover exactly the PSUs in `folds`. This pass does not establish when or where that check landed. The historical finding is therefore **not reproduced in this checkout**. No code was changed.
- Exhaustive gate: `build_nonmated_pool` refuses `exhaustive is not True` (`firbench_frames.py:486–487`). The tracked manifests carry no exhaustive assertion, so a non-mated pool cannot be built from them without a new, reviewed assertion.
- The v6 cell-power result (1113/2000) and H2-boundary result (126/2000) are recorded in the v6 report and are not re-derived here. This document adds no power or interval number.

## 12. Static checks and results

**Rulings.** FB1-OC-GATE-03 is supported: the two cited status summaries do not substantiate the expanded 19-artifact approval-search claim. That claim is withdrawn in favor of the exact named summaries, hashes, and fields in §1 and §8; approvals remain unknown/pending. FB1-OC-GATE-04 is supported: the manifest lists PRINCIPLES and reasoning digests, and the full CAL-02 row is present at `lexicons/ml-systems.md:350`. The listing and independently verified bytes are now distinguished. Neither finding implies approval, qualification, a formula change, or a numerical pass.

**Current checks (2026-10-15 adjudication).** Reads were bounded to the named allowlisted document, source map, code/task documents, the two status summaries, and the supplied canon sources. The exact-production codemap search had zero results and lacks scripts/docs/benchmarks coverage (supplied context); that is a reason for bounded known-path reads, not evidence of absence. No repository-wide approval search or 19-artifact classification is claimed.

- The initial document digest and source-map digest are recorded in §1. Six current allowlisted files matched their exact `files` keys in that map: `firbench_frames.py`, `S1-frames.md`, the task plan, `inventory.md`, `README.md`, and `S6a-cli-run-score.md` at their full paths in §1. This verifies byte identity only. The historical scope file and v6 report are unavailable here and are not counted as matches.
- Both summary hashes in §1 were recomputed; only `/evals/AE-5`, `/evals/AE-6`, `/evals/AE-12` and `/real_data_evidence` were extracted for evidence. These are pending/status records, not real-run or approval artifacts.
- The task plan AE-5/6/12 rows and pending-status rows were read. Its AE-7 policy statement that the real budget stays unset was kept separate from actual approval. No unpinned policy patch was used as current evidence.
- The full CAL-02 row, manifest `docs` and `reasoning` entries, GRPH-14 row, Principle 9, and CARD-27 supplement were checked. The manifest sha256 is in §1; the following independently computed digests match its named entries:

| Available canon artifact | Verified sha256 | Manifest locator |
| --- | --- | --- |
| `lexicons/epistemics.md` | `866f67e6fe626671999bc9debd3774188c23f7b82905ea7d5e008a08dd5f7f07` | `/lexicons/lexicons~1epistemics.md/sha256` |
| `lexicons/ml-systems.md` | `1dfbd751c2d52d223b0ae617da7f709dd29970f37ddd9bcdc0eb09a7e839cf20` | `/lexicons/lexicons~1ml-systems.md/sha256` |
| `lexicons/graph-theory.md` | `23bdbc8262cbd3577e4fd5ef3e49c6ad1f50fdfd1472ba3990497ef57e3eb61c` | `/lexicons/lexicons~1graph-theory.md/sha256` |
| `PRINCIPLES.md` | `0bd3555fa6b97cadd02563f87ac292cb97ce34df960e6361fa82beaf9a07f205` | `/docs/PRINCIPLES.md/sha256` |
| `reasoning/designed-unknown.md` | `ad40d8aa302ff9d249cccdc7280b414eefd7aacb3ddc6ab7edca6832dd9e82fd` | `/reasoning/reasoning~1designed-unknown.md/sha256` |
| CARD-27 supplement (§1) | `186c94c2b0ba88897cebea26c39752d6f0e87bbab8bff3ec1fa9aace79f85aad` | `/reasoning/reasoning~1margin-and-design-effect-before-the-run.md/sha256` |

The original author's corpus-loader counts, exhaustive-marker search, full-anchor check, historical digest checks, and private-pattern scan are dated prior observations only. They were not rerun; the earlier blanket statement that all repository paths resolve is not valid for this minimal bundle. No private identity/map-based scan was performed here. Changed prose contains only safe locators, code/schema field names, aggregate/status evidence, and hashes.

Section-byte comparison against the initial document confirms that only sections 1, 8, 10, and 12 changed; all other sections and the preamble retain exact bytes. `git diff --check` on the owned file reports no errors. No product, test, fixture, or inference code changed, and no product/test suite, real inference, or Monte Carlo was run.

**Preserved failures and blockers.** The supplied historical v6 H2 result `0.063 > 0.060` and cell-power result `1113/2000 = 0.5565 < 0.77` remain **FAILED**; seeds and receipts are unchanged. Earlier failed trials remain failed. Reported 166 software tests and synthetic reader 6/6 are not independent human GT/QC, observation, capture-occasion, budget, or seal evidence. No schema, hash match, status scalar, or prose qualifies a frame or supplies numerical acceptance. Specific tracer identity and budget approval artifacts, real AE-5/AE-6/AE-12 evidence, independent exhaustive GT/QC and observation, capture-occasion provenance, and ratification/seal remain unestablished in the inspected summaries. Excluded corpus inputs and historical full-tree ancestry remain unverified here.

## 13. Limits

- Capture occasions are **not qualified**. No occasion field exists in the tracked metadata.
- The v3 PSU figures differ from the inventory's v3 row and are unreconciled (§3).
- The tracked corpus has no independent exhaustive GT, no MEAS-29 record, no approvals, and no budget. These are gaps in the inspected scope, not global absences.
- The pinned external context was read as a read-only snapshot. The live laptop state was not inspected.
