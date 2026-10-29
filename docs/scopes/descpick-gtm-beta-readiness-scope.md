# DESCPICK GTM scope: beta readiness for the kept description model

> **Source assessment:** [description-model-gtm-selection-assessment-2026-10-28.md](../assessments/current/description-model-gtm-selection-assessment-2026-10-28.md). Canon release **v0.26.2** (`meta/release-manifest.json`). Corpus: `heuristics-canon-research/distilled/` (remote lanes mounted it as `corpus/`; citations below are `<domain>/<file>.md:<line>`).

Date: 2026-10-28 20:49 EDT. Status: proposed; intake answered; four task plans drafted, awaiting planning review.
Handoff decisions: `MAINT-descpick-gtm-scope-20261028` #20466 (intake), #20467 (outcome storage), #20469 (accepted definition and floor), #20470 (report control), #20471 (canon resolution), #20472 (web facts), #20474 (Florence dormant, quota, Stop waiting); `MAINT-desc-model-pick-20261026` #20420 (Q4 fourth candidate).

Anchors verified at `43366e5d25`; unchanged at main `8eece0358f` (`git diff --stat 43366e5d25 8eece0358f` over every planned path is empty).

## Intent and recommendation

The assessment keeps the served incumbent (Qwen3-VL-30B-A3B Q4_K_M) for beta and rejects a speed/quality toggle (assessment F1, F3). The model was kept, not proven best (C1): the beta must say what it is, wait honestly, refuse rather than fall back, and measure whether drafts are accepted.

| Plan | Covers | State |
|---|---|---|
| [E15-38](../tasks/15.0/E15-38-public-demo-honest-wait-and-beta-copy-task-plan.md) | Rec 2 beta expectations copy; Rec 5 honest wait plus demo **Stop waiting**; demo i18n | ready |
| [E15-39](../tasks/15.0/E15-39-description-default-trusted-set-and-serve-pin-task-plan.md) | Rec 6 adapter default `seeded`; `florence_small` out of the trusted set; SERVE-07 digest pin; Rec 5 operator cold start | ready; S0 and S4 operator |
| [E15-40](../tasks/15.0/E15-40-description-outcome-telemetry-and-cost-per-accepted-task-plan.md) | Rec 3 outcome telemetry and cost per accepted | S0 ready; rest blocked on DESCAUTH-1 |
| [DESCPICK-5](../tasks/vlm/DESCPICK-5-served-q4-candidate-and-four-candidate-panel-task-plan.md) | #20420 Q4 as fourth candidate in the review panel | ready; S2 GPU owner |

The export filename already shipped in DESCPICK-4 (`43366e5d25`); no plan. No separate spec: the plans carry the copy and contracts, and the E15-40 S0 ADR-017 amendment carries the schema.

## Intake record

| Question | Answer (verbatim) | Resolution | Decision |
|---|---|---|---|
| Where do per-draft outcomes live? | "i prefer 3 wp post meta only. see which solution is correct according to adr, semantic embeddings, and heuristics canon research with original distilled corpus" | WordPress-only kept, but as ADR-017's append-only `acx_description_events` table, not post meta. Post meta holds only current state, so supersession, edit-after-apply and idempotent reports cannot be derived; ADR-017 :48/:84 already selects the table; DATA-14 one system of record (`ml-systems/manning-information-retrieval.md:161`). Adds `reported`, `report_reason`, `edit_ratio`, `request_key` by ADR amendment (AGT-13). | #20467 |
| What counts as "accepted"? | "use heuristics canon research to evaluate, along with adrs and semantic embeddings" | Six outcome classes over the presented `generation_id`, window 14 days, lenient rate primary with strict alongside, edit-ratio sensitivity 0.10/0.20/0.30, floor 50% on ≥200 drafts from ≥5 sites, `n_eff` < 96 inconclusive, descriptive or cluster-robust intervals only, plan sealed before the first counted draft, blind audit. | #20469 |
| Report-a-problem: linked to in-house FIR curriculum? | "i think this is linked to the curriculum cnn for inhouse FIR . confirm if so, and pick best option according to heuristics canon research & semantic embeddings + adrs" | Not confirmed: prior art #16800 defines `curriculum_t` as a per-identity threshold, not a training feed. One report action per draft, optional concept-id reasons, no free text; identity reason deep-links to People (D12). Copy says reports inform model choice and do not retrain (D14, accurate). | #20470 |
| Wait and cancel behaviour | "Honest wait + Cancel (Recommended)" | Shared cold-start sentence everywhere; demo **Stop waiting** is client-only; the retry key survives a client stop and resets only on a server-terminal outcome. | #20471, #20474 |

## MVP scope and completion signals

| Plan | MVP | Completion signal |
|---|---|---|
| E15-38 | Translatable demo (PHP and JS); Stop waiting; truthful timeout copy; retry-key lifecycle; C1 shared by demo and admin; beta notice under the Review Queue heading; ux-maps in sync | GTM-SC-01 … GTM-SC-07 green |
| E15-39 | Default `seeded` from one constant; `florence_small` untrusted at the gate; quota refusal and cancel pinned; runtime image pinned by digest with explicit flags; one measured cold start | GTM-SC-08 … GTM-SC-11, GTM-SC-20 |
| E15-40 | ADR-017 and DESCAUTH-1 amended now; outcome classes, Report a problem, cost per accepted and sealed plan after DESCAUTH-1 S3, S5–S8 | GTM-SC-12 now; GTM-SC-13 … GTM-SC-16 when unblocked |
| DESCPICK-5 | Q4 cells generated under the shared decision profile; panel extended to four candidates with 192 reviews kept; rule v2 | GTM-SC-17 … GTM-SC-19 |

## Assumptions

| Assumption | If false |
|---|---|
| The served build stays Q4_K_M at revision `0af19e7479857aa7f3246466a4ad16c7e7299639`; the digest pin freezes what already serves | E15-39 S0 stops and re-plans |
| #10035 is fixed only on `feature/defwave-2` (`016789be8d`) | E15-39 S4 reconciles before any wait figure is quoted |
| "Several minutes" stays the wait copy until a p95 with its n exists (PERF-01) | Copy changes only through a new copy decision |
| ADR-017 stays Proposed until operator acceptance (`ADR-017…md:3`); DESCAUTH-1 Wave Order (:1111) bars S1+ | E15-40 S1+ stay blocked |
| A10 price USD 2.00 per GPU-hour, per-second billing, 1-minute minimum (#20472 W1) | E15-40 cost report takes the rate as a flag |
| `packages/workbay-system` is absent here | Evals JSON stays provisional data |

## Proposed non-functional envelope

| Concern | Envelope | Source |
|---|---|---|
| Wait | Quote p95, never the mean; no number until a re-measure; Cancel offered (Stop waiting) | PERF-01, INT-08 |
| Demo deadline | Client ceiling 120 s kept (`PUBLIC_DEMO_CLIENT_DEADLINE_CEILING_SECONDS`) | #20474 |
| Idempotency | Same key replays free; client stop keeps key; server-terminal outcome or 403 `acx_public_demo_run_not_available` resets it; reports unique by `request_key` | #20474, #20467 |
| Failure | No unscored fallback; GPU unavailable refuses before the quota charge | C5, `engineering/release-it.md:602` |
| Cost | Always-on ≈ USD 1,400–1,460/month vs scale-to-zero; cost per accepted replaces the F7 estimate | COST-04, #20472 |
| Durability | Events append-only; a failed history write never loses the applied outcome | DESCAUTH-1 S7 |
| Privacy | Report reasons are concept ids, no free text; text retention follows ADR-017 (180 days) | C10 (contested), D3 |

## Not doing

| Item | Why |
|---|---|
| Speed/quality toggle | Minutes-long wait for an unproven gain on a build that cannot be served (assessment F1, F3; C2) |
| Server-side cancel of a demo run | Quota is charged at creation (`apps/prototype-description-service/scene/interface_adapters/http/routers/describe_run.py:687`); cancel keeps the charge (#20474) |
| Auto-describe on upload | Out of scope for beta readiness |
| Quoting an accuracy rate | Convenience sample, no design-based CI (AUDIT-08, `ml-systems/lohr-sampling-design-analysis.md:27`) |
| Deleting the Florence enum, adapter, benchmark tool or dormant CPU fallback (`infra/oci/gpu_lifecycle/controller.py:26`) | Benchmark-only and dormant (#20474) |
| `infra/oci/README.md` Florence command section | Its commands still run; E15-39 I2 edits only its trusted-adapter statements |
| `describe-gpu-tier.notes.md` dated sketches | Dated audit record (July) |
| Retraining from reports; FIR curriculum link | #20470 |
| EU AI Act Art. 50 marking | Operator/legal question (#20472 W5) |
| Separate spec `docs/specs/e15-beta-expectations-and-telemetry-spec.md` | Plans plus the ADR-017 amendment carry the contract |
| Epic edit | Plans attach to E15 as written |
| New hardware or a bigger beta model | Eliminate work before buying hardware (`ml-systems/systems-performance-gregg.md:62`) |

## Validation

Canon v0.26.2 rows, read through the pinned link:

| Row | Gloss | Applied in |
|---|---|---|
| PROD-39, HAI-05, HAI-12 | Stage; disclose; proposal, not decision | E15-38 beta notice |
| INT-08, INT-10, A11Y-21 | Cancel past ~2 s; status-predict-stop; `role=status` | E15-38 Stop waiting |
| PERF-01 | p95, not mean | E15-38 copy, E15-39 S4 |
| REF-27, FORM-02 | No unstated locale or default; locale-aware formats | E15-38 i18n, E15-39 default |
| RLSE-04 | Undesigned state is a bug (focus and announcement designed) | E15-38 stopped state |
| SERVE-07 | Quantization gate on the served build | E15-39 I3, DESCPICK-5 |
| AGT-13 | No silent ADR override | E15-40 S0 |
| AIPX-03, COST-04, EVAL-22, AUDIT-08, EXP-09 | Instrument; cost per accepted; validate offline proxy; no design CI on convenience samples; no peeking | E15-40, DESCPICK-5 S6 |
| DATA-14 | One system of record | E15-40 storage |
| EVAL-01, EVAL-14 | Served build as baseline; counterbalanced order | DESCPICK-5 |
| TEST-15 | Green can go red | Every RED lane |

Corpus checks (S supports, Q qualifies):

| Claim | Verdict and evidence | Plan consequence |
|---|---|---|
| C1 kept, reversible | S `engineering/pragmatic-programmer.md:65`; Q `epistemics/reinhart-statistics-done-wrong.md:47` | Copy says "the beta uses the faster model", never "best" |
| C2 no toggle | S `interaction/microinteractions-saffer.md:153`; Q `interaction/human-centered-ai.md:60` | Not doing |
| C3 stage, disclosure, qualitative capability | S `business/perri-escaping-the-build-trap.md:304`, `business/designing-ai-interfaces.md:308`, `ml-systems/guidelines-human-ai-interaction.md:24` | E15-38 notice |
| C4 two waits, true state, Cancel | S `business/designing-ai-interfaces.md:171`, `interaction/microinteractions-saffer.md:440` | E15-38 C1 and Stop waiting |
| C5 fail fast before charging | S `engineering/release-it.md:602`; Q `:409` (interrogable failure) | E15-39 Q1 pins |
| C6 log outcome with model version | S `ml-systems/ai-engineering.md:76`, `business/building-ml-powered-applications.md:179`; Q `ml-systems/designing-ml-systems.md:50` | E15-40 events carry profile and revision |
| C7 online vs offline descriptive only | S `ml-systems/ml-test-score.md:74`; Q `epistemics/trustworthy-controlled-experiments.md:38` | E15-40 report labels |
| C8 cost per accepted, accepted predefined | S `ml-systems/systems-performance-gregg.md:17`; Q `:20` | E15-40 Slice 4 |
| C9, D7 pre-registered floor and sample | S `epistemics/reinhart-statistics-done-wrong.md:27`, `ml-systems/lohr-sampling-design-analysis.md:35`, `epistemics/trustworthy-controlled-experiments.md:68` | E15-40 operator S5 sealed plan |
| C10 telemetry minimum | Q `security/face-recognition-compulsory-visibility.md:76`; contradicted by `business/building-ml-powered-applications.md:186` | Scope decision: ADR-017 retention only; no new text store |
| C11 pin image, match flags | S `engineering/continuous-delivery-humble-farley.md:63`, `:28`; Q `ml-systems/ai-engineering.md:212` | E15-39 I3 |
| C12 eliminate work first | S `ml-systems/systems-performance-gregg.md:41` | Not doing |
| C13, D8 effective n, descriptive estimates | S `ml-systems/lohr-sampling-design-analysis.md:49`, `:51`; Q `:27` | E15-40 intervals |
| C14 retired default is a defect | S `engineering/continuous-delivery-humble-farley.md:65`; Q `engineering/release-it.md:409` | E15-39 `seeded` default (fails closed, does not terminate) |
| C15 same words everywhere | S `interaction/how-to-make-sense-of-any-mess.md:49` | E15-38 C1 parity test |
| D1 one outcome record | S `ml-systems/manning-information-retrieval.md:161` | E15-40 events table |
| D2 include unsuccessful attempts | S `epistemics/trustworthy-controlled-experiments.md:114`; Q `:118` | `no_outcome` class counted; estimand stated |
| D5, D6 observable acceptance, fixed window, declared primary | S `business/croll-yoskovitz-lean-analytics.md:172`, `epistemics/trustworthy-controlled-experiments.md:28`; Q `business/building-ml-powered-applications.md:179` | W = 14 days; lenient primary, strict alongside, sensitivity sweep (no evidence for one edit threshold) |
| D9 independent audit | S `ml-systems/forensic-face-matching.md:65`; Q `:64` | Blind audit (reviewer sees no model label first) |
| D10 lightweight per-draft report | S `ml-systems/guidelines-human-ai-interaction.md:120`, `business/building-ml-powered-applications.md:369`; Q `ml-systems/guidelines-human-ai-interaction.md:122` | One action; identity goes to People adjudication |
| D11 implicit signals aggregate-only | S `business/building-ml-powered-applications.md:369`, `ml-systems/designing-ml-systems.md:50` | Edit ratio reported in aggregate only |
| D12 correct the responsible component | S `ml-systems/guidelines-human-ai-interaction.md:201`, `ml-systems/identity-aware-video-summarization.md:37` | Identity reason links to People |
| D14 explain consequences accurately | S `ml-systems/guidelines-human-ai-interaction.md:126`; Q `:188` | "They do not retrain the model." (true today) |

Current research, FIR report v16 (2026-10-27, on main `8eece0358f`): `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html`.

| Section | Finding | Applied in |
|---|---|---|
| Report header | "preserve the pinned Qwen3-VL-30B-A3B-Instruct Q4_K_M as the caption comparator" | DESCPICK-5 `incumbent-q4km`; E15-39 I3 |
| `#v13-caption` | A Florence fallback when the profile is unset is "configuration drift, not the operating baseline" (decision 15953) | E15-39 `seeded` default |
| `#v15-heading` | "Verdict: Flint is excluded; it is not a native image-caption candidate." | No Flint candidate in any plan |
| `#v16-heading` (FACEGROUP-0) | "No model training of any kind…" | Supports "They do not retrain the model"; FIR curriculum link not confirmed (#20470) |

## Evals

[`descpick-gtm-beta-readiness-evals.json`](descpick-gtm-beta-readiness-evals.json): one case per criterion, GTM-SC-01 … GTM-SC-20. **Provisional data:** `packages/workbay-system` is absent from this repo, so the suite is not runnable through the suite registry; registration needs an executor in `EXECUTOR_BY_SUITE_ID` (`packages/workbay-system/scripts/workbay_evals/registry.py`), owned by a separate lane. `make eval-list` (`mk/evals.mk`) is the model-eval harness, not that registry.

## Dispatch decomposition

A lane dispatches once every lane it depends on has merged; waves are the earliest possible.

| Wave | Lanes (each RED lane merges before its implementation lane) |
|---|---|
| 1 | E15-38 L1R, L2R, L4R, L5R; E15-39 R1, Q1, R2a, R2b; DESCPICK-5 X1R, X3R, X4R; E15-40 S0 docs |
| 2 | E15-38 L1, L2, L4a; E15-39 I1, I2; DESCPICK-5 X3, X4 |
| 3 | E15-38 L3, L4b, L5; E15-39 D2; E15-39 R3 (after operator S0) |
| 4 | E15-38 L6, L7; E15-39 I3 |
| 5 | E15-38 L8; DESCPICK-5 X1 |
| Operator | E15-39 S0 digest and S4 cold start; DESCPICK-5 S0, S2 (GPU owner), S4b, S5, S6; E15-40 ADR acceptance |

Executor routing: implementation codex `gpt-6.1-sol` high FAST; grunt work (classification, web fetch) `gpt-6.1-sol` low FAST. A RED lane may not touch implementation source; it finishes when its tests collect and fail for the stated reason.
