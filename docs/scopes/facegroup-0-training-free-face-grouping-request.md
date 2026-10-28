# Feature request: training-free face grouping (FACEGROUP-0)

**Requested by:** operator, via the semantic-image-search session · **Date:** 2026-10-27
**Status:** proposed; awaiting `/scope` intake
**Task:** FACEGROUP-0 · branch `feature/facegroup-0` · intake only, no code on this branch yet
**Blocks:** nothing today. FIR-6 S4 calibration and the FIRBENCH-1 model pick each gain a consumer that turns their numbers into grouping decisions.
**Canon:** heuristics canon v0.26.2. Rows are cited by id; the table in [Canon rows](#canon-rows) gives each rule name.
**Evidence rule:** this request cites code, plans and corpus sizes. It cites no accuracy number as evidence; open question 7 quotes one historical rate only to show that it cannot support an FPIR claim. Any number a later slice needs comes from a fresh run on the current stack (the FIR-13 plan line 48 discipline).

## The ask

Group a tenant's faces by person the way Desert Ant's Who groups the voices in a recording. Route every grouping decision the way TypeSafe's Jev routes an answer: act, ask, or abstain. Do it with no model training of any kind. That rules out training on tenant data, fine-tuning, an "initial training" step and learned clustering.

The embedders stay frozen: SFace-128 under the `face_pipeline` profile, AuraFace-512 under `auraface`. Everything held per tenant is data: embeddings, templates, constraints and labels. Calibration is a handful of scalar thresholds per embedding space. They are chosen once on the operator eval corpus and applied by a reviewed code commit, never fitted per tenant.

Most of the machinery already exists. ACX clusters frozen embeddings (HDBSCAN, anchors, complete-link validation, constrained HAC). It resolves one face per photo at assignment, bands suggestions, and names anonymous clusters `Person N`. The gaps are:

- per-space thresholds;
- bands defined by error rates;
- a validated quality gate;
- the same-photo constraint during discovery;
- a split that does not shatter clusters;
- face-level search;
- a minimum-photos listing filter;
- a curator confirmation before an automatic join can name someone.

## Summary

| ID | Capability | Closes | Shape | Gate |
| --- | --- | --- | --- | --- |
| FG-1 | Per-space thresholds and act/ask/abstain bands | G1, G2, G9 | a: dark settings split · b: offline calibrator · c: apply · d: confirm-before-naming flag | a, b, d (flag off): none · c: FIR-6 S4 corpus gate and FIR-13 D3 ratification · d flip: operator answer to open question 3 |
| FG-2 | Quality-gated templates (Who's "solo-moment prints") | G3 | a: proxy validation tool · b: dark seed/anchor/representative gate | Floors ship only for a validated proxy |
| FG-3 | Same-photo cannot-link during discovery | G4 | Runtime constraint behind a flag, default off | Flip after the FG-4a arm shows no regression |
| FG-4 | Partition plus verification instead of shattering | G5 | a: offline FIRBENCH-1 arm · b: production switch · c: re-partition suggestions | b, c: operator decision |
| FG-5 | Face-level search by example | G6 | New tenant-scoped read route | Privacy rows reviewed at `/scope` |
| FG-6 | Minimum-photos listing filter | G7 | Additive query parameter plus `photo_count` | None |
| FG-7 | Anonymous numbering invariants | G8 | Regression tests only | None |
| FG-8 | Recall arms E → C → D, inference only (optional) | none | Offline arms | Each arm gated on the one before |

## What "training-free" means here

| Allowed | Not allowed |
| --- | --- |
| Frozen pretrained weights (SFace, AuraFace) | Training or fine-tuning any model on tenant faces |
| Per-tenant state held as data: embeddings, templates, constraints, labels | Learned clustering (GCN-V/E, Hi-LANDER, Ada-NETS, STAR-FC) |
| Curator confirmations that add templates and constraints | Classifier heads per tenant or per person |
| A few scalar thresholds per embedding space, selected on the operator eval corpus with identity-disjoint folds | Thresholds fitted per tenant |
| Thresholds applied through the FIR-6 S4 apply commit | FIR-7 occlusion adapters and AdaFace retrain, which stay gated in their own plans |

**Deletion test (PROV-10, RAG-10).** Deleting a tenant's faces leaves nothing to retrain, because no model weights were ever fitted to them. Deletion must still reach every derived artifact: centroids, representatives, templates and index entries (RAG-10).

## Who, Face and Jev: what transfers

- **Who** is Desert Ant's speaker diarization model. It has no enrollment and no training at use time. It builds a voice print per speaker, matches speakers across the whole recording, numbers them anonymously and names nobody.
- **Face** is Desert Ant's closed-beta face product, and the capability we want. Pick one photo of a person, find every other photo of them, and group a library by person. Its architecture, training data and licence are not published, so only the behaviour is copied.
- **Jev** is TypeSafe's non-generative decision model. It answers typed questions (choice, score, yes/no) with a confidence that routes the answer: act automatically, ask for confirmation, or send it to a human. The model itself is trained, so only the decision contract is copied.

| Source mechanism | ACX counterpart | Capability | Canon rows |
| --- | --- | --- | --- |
| Who builds each voice print from moments when one speaker talks alone | Only faces that pass a validated quality gate may seed, anchor or represent a cluster. Other faces may still join one. | FG-2 | EMB-02, EMB-03, EMB-07, CAL-11 |
| Who matches every speaker across the whole recording at once | Library-wide partition plus verification over a mutual k-NN graph. A failing group splits by normalised cut instead of shattering. | FG-4 | GRPH-17, GRPH-18, GRPH-19, GRPH-22, GRPH-23 |
| Who treats two voices at the same moment as two speakers | Two faces in one photo cannot link during discovery | FG-3 | GRPH-18 |
| Who numbers speakers anonymously and never names them | `Person N` from the monotonic tenant counter, which already exists | FG-7 | none |
| Who's `keepingSpeakers(minimumShare:)` drops speakers who barely appear | `min_photos` filter on the cluster listing | FG-6 | none |
| Face: pick one photo, find every other photo of that person | Face-level search by example, inside one tenant's library | FG-5 | MLDATA-16, PROV-12, IDX-01, HAI-17 |
| Jev routes each answer by confidence: act, confirm, or send to a human | Per-space bands defined by false-positive identification rate (FPIR). Strong means auto-accept, possible means suggest and confirm, and anything below abstains. | FG-1 | CAL-02, CAL-07, EVAL-18, SECD-14, HAI-08 |
| Jev's choice question over categories fixed per request, with an abstain path | Roster candidates over the tenant's labelled clusters, where "none of these" is a valid outcome | FG-1 (bands) | GRPH-38, CAL-02 |

**Not transferred:**

| Source mechanism | Why not |
| --- | --- |
| Who attaches a speaker with under about a second of solo speech to the nearest speaker in time | Non-face evidence (time, clothing, VLM names, captions) never rescues a face identity in ACX. A face too poor to match abstains. |
| Jev shows the user a 0–1 confidence | Decision 10706 ([WBTRUST](./workbench-curation-trust-scope.md)) shows the measured cosine next to its named threshold. Bands route actions and are never displayed as probabilities (HAI-08; the [PUBFIG](./public-figure-library-scope.md) Not-Doing list says the same). |
| Jev's trained model | Only its decision contract is copied |
| Who numbers speakers in order of first appearance | ACX numbers clusters in allocation order. First-appearance order would mean renumbering, which breaks FG-7. |
| Face's video tracking; Eye-style attributes | Out of scope. This request covers still photos only, and CelebA, the usual attribute corpus, is research-only (`RESEARCH_ONLY_SOURCES`, `scripts/train/occlusion/license_policy.py:575`). |

## Current pipeline and anchors

The pipeline runs in this order:

1. YuNet detection with 5 landmarks.
2. Five-point alignment.
3. Embedding: SFace-128 (`face_pipeline`) or AuraFace-512 (`auraface`, `glintr100.onnx`, activation-gated by [ADR-016](../adrs/ADR-016-auraface-512d-activation-refusal.md)).
4. L2 normalisation, keeping the pre-normalisation magnitude.
5. Quality factors.
6. Discovery: HDBSCAN, anchors, complete-link validation, constrained HAC.
7. Joint assignment, one face per photo.
8. Suggestion bands.
9. `Person N` auto-label.

Paths below are under `apps/prototype-description-service/` at `b43e4d5d1e9c5bf5fdaa1da644d267b277149497`.

| Area | Anchor | Behaviour today |
| --- | --- | --- |
| Profiles | `recognition/config/settings.py:35` | `_FACE_PIPELINE_PROFILES = {"insightface", "face_pipeline", "auraface"}` |
| Knob surface | `settings.py:311` `FacePipelineSettings`; fields at `:363`, `:370`, `:377`, `:383` | One set of `face_*` thresholds for the face pipeline |
| Knob resolution | `settings.py:552` `ResolvedFacePipelineKnobs`; `:581` `resolve_face_pipeline_knobs`; branch at `:596` | `face_pipeline` and `auraface` resolve the same `FacePipelineSettings` values. The docstring says so: "AuraFace shares this tuning surface". |
| Overlay | `settings.py:633` `apply_resolved_clustering_settings`; `:664` `resolve_effective_clustering_settings` | Writes four resolved thresholds into `ClusteringSettings`: similarity, complete-link, suggestion floor, suggestion ceiling |
| Values outside the overlay | `recognition/application/settings/clustering.py`: `hdbscan_cluster_selection_epsilon` 0.45 (`:319`), `anchor_discovery_threshold` 0.40 (`:339`), `anchor_split_similarity_floor` 0.60 (`:343`), `AutoLabelSettings.similarity_floor` 0.85 (`:211`) | The same value applies to every embedder |
| Join an existing cluster | `recognition/application/discovery/centroid.py:49`, `recognition/application/discovery/representative.py:101–111` | A face becomes an assignment candidate at `similarity_threshold`. When no match clears `complete_link_min_floor`, a labelled cluster is preferred. The assignment gate then accepts, suggests or rejects (`recognition/application/assignment/gate.py`; `assignment/checks/confidence.py:222` accepts at a maturity-adjusted threshold). |
| Quality capture | `recognition/infrastructure/face_pipeline/_common.py:129` `EmbedBatchResult.norms` | Pre-normalisation magnitudes. SFace and AuraFace both run through `OrtSFaceEmbedder`, which selects preprocessing from the manifest. |
| Quality floors | `recognition/infrastructure/embeddings/face_quality_factors.py:161` `passes_factor_floors` | Floors default to 0.0, a no-op. [FIR-6](../tasks/fir/FIR-6-calibration-quality-switchover-task-plan.md) line 53 says so deliberately. |
| Representative quality | `clustering.py:29` `representative_quality_composite_enabled` | Default `False` |
| Discovery | `recognition/application/discovery/graph/discovery.py:124` `discover`; pairwise validation `:206`; singleton split `:222` | A cluster that fails validation becomes singletons |
| One face per photo | `recognition/application/assignment/joint.py:44` `resolve_photo_conflicts` | Assignment only. Discovery has no such constraint. |
| Curator constraints | `recognition/domain/constraints.py` | MUST_LINK and CANNOT_LINK from merge, split, wrong-person and manual reject |
| Bands | `recognition/application/suggestions/roster_candidates.py:28` `SimilarityBand`; `:75` `band_for`; `:84` `_capped_band` | Strong if cosine ≥ ceiling; possible if floor ≤ cosine < ceiling. A low-quality probe never shows strong. Docstring: "Never a calibrated probability." |
| Same-space check | `recognition/application/suggestions/embedding_space.py:62` `models_are_same_space` | Fails closed across models |
| Auto-label | `recognition/application/persistence/assignment_writer.py:771`; `recognition/application/labeling/auto_labeler.py` | `Person N` comes from `Tenant.next_person_number` (UPDATE … RETURNING) when a cluster has at least 3 members and mean similarity ≥ 0.85 |
| Description weave | `scene/application/identity_merge/join.py:66` `load_confirmed_faces`, filter at `:104` | Selects every face whose cluster is user-confirmed and named. `IdentityMember` (`db/models/identity.py:493`) has no per-face confirmation column. |
| Listing | `recognition/interface_adapters/http/routers/clusters_snapshot.py:387` `GET /clusters` | Parameters are `limit`, `offset`, `include_outliers`, `labeled_only` and `search`. `ClusterResponse.identity_count` (`schemas/responses.py:137`) counts faces, not photos. |
| Per-face routes | `routers/suggestions.py` `GET /identities/{identity_id}/suggestions` | Ranks labelled clusters for one face. No route returns faces similar to a face. |
| Face vectors | `db/models/identity.py:162` `MediaIdentity`; ivfflat cosine index at `:225` | No code sets `ivfflat.probes`, so pgvector uses its default of 1 |
| Eval harness | `scripts/eval_harness/`: `accept_predicate.py`, `open_set_identification.py`, `calibrate_face_thresholds.py:672` `select_threshold`, `gate_contract.py`, `firbench_clusters.py` | Single accept predicate, FNIR at fixed FPIR, threshold selection, the gate contract, and cluster diagnostics (diagnostics only) |

## Gaps

Each gap was verified at `b43e4d5d1e9c5bf5fdaa1da644d267b277149497`.

**G1. AuraFace inherits SFace's thresholds.**
- Both profiles resolve the same `FacePipelineSettings` values (`settings.py:596`).
- The same cosine does not mean the same error rate in two embedding spaces (EMB-01).
- Four more values sit outside the overlay and apply unchanged to every profile, including buffalo-era `insightface`: the HDBSCAN epsilon, the anchor discovery threshold, the anchor split floor and the auto-label floor.
- The FIR-6 S4 apply commit writes only `face_pipeline` values (plan lines 76 and 137).

**G2. Bands are cosine cut points, not error rates.**
- `band_for` compares cosine with `suggestion_ceiling` and `suggestion_floor`.
- Under `face_pipeline`, both are legacy placeholders until S4 (FIR-6 line 76).
- No band is tied to an FPIR, so "strong" promises nothing measurable (CAL-07, EVAL-18).

**G3. Seeds and representatives have no quality gate.**
- Magnitudes are captured, but floors are no-ops and composite representative quality is off.
- A blurred or occluded face can seed a cluster or become its representative. Who builds prints from clean moments only; ACX does not (EMB-02, EMB-03, CAL-11).
- The one partial gate: `_capped_band` keeps a low-quality probe out of the strong band.

**G4. Faces from one photo can share a cluster after discovery.**
- `joint.py` resolves one face per photo at assignment.
- Discovery has no such constraint, so a new cluster can hold two faces from one photo.

**G5. Verify-or-shatter.**
- When a discovered cluster fails pairwise validation, `discovery.py:222` splits it into singletons.
- A cluster that mixes two people loses both, instead of splitting into two clusters (GRPH-19, GRPH-22).

**G6. No face-level search.**
- Existing routes rank clusters for a face, or labelled clusters for a cluster.
- Nothing returns the faces most similar to one face.

**G7. No minimum-photos filter.**
- `GET /clusters` has no size filter.
- `AutoLabelSettings.min_members=3` gates only auto-labelling.
- `identity_count` counts faces. That is not the photo count while G4 is open, or when a curator approves a mirror.

**G8. Numbering is already stable; only a test is missing.**
- `allocate_person_label` increments `Tenant.next_person_number` atomically, so a number is never reused or renumbered. That is the property Who's anonymous numbering gives.
- No test pins it yet.

**G9. An automatic join can put a name on a face no curator has seen.**
- `representative.py:104` prefers a labelled cluster when no match clears `complete_link_min_floor`. The confidence check then accepts at a maturity-adjusted cosine (`assignment/checks/confidence.py:222`). Maturity tightens that threshold for confirmed clusters; it does not stop automatic acceptance.
- Membership rows (`IdentityMember`, `db/models/identity.py:493`) carry no per-face confirmation. The description weave (`load_confirmed_faces`, `scene/application/identity_merge/join.py:66`, filter at `:104`) takes every member of a user-confirmed, named cluster.
- So a face accepted automatically into a named cluster can be named in its photo's description, at a threshold that is a cosine rather than an error rate (G2). Consent and suppression checks still apply to the name. `/scope` should confirm this trace end to end before FG-1d is sized.

## Consumer-side behaviour already in force

- One face per photo is enforced at assignment (`joint.py`, behind `joint_assignment_enabled`).
- A low-quality probe never shows the strong band in roster candidates (`_capped_band`).
- `Person N` labels are monotonic per tenant.
- `include_outliers=false` hides outliers from the listing.
- FIRBENCH-1 S4 shows how each space groups people, as diagnostics only ([S4-clusters](../tasks/firdv/firbench-1/S4-clusters.md)).

## Requested capabilities

### FG-1: per-space thresholds and act/ask/abstain bands (Jev routing)

**Why.** Jev pairs every answer with a route: act, confirm, or send to a human. ACX already has three routes: join an existing cluster at `similarity_threshold`, suggest between the floor and the ceiling, nothing below. They are not tied to error rates, and two embedders share them.

**FG-1a: split the knobs per profile (dark, values unchanged).**
- Give `auraface` its own threshold fields, or a per-profile map; `/scope` picks the shape. Resolve them in `resolve_face_pipeline_knobs`.
- Add `hdbscan_cluster_selection_epsilon`, `anchor_discovery_threshold`, `anchor_split_similarity_floor` and the auto-label similarity floor to the resolved knobs, and route their readers through the resolved settings.
- New fields default to `None`, meaning "inherit today's effective value". An `auraface` field inherits the `face_pipeline` value; a moved field inherits the `ClusteringSettings` value, including any environment override. This keeps behaviour byte-identical even where production overrides a value by environment variable.
- Environment variable names follow the `_resolve_face_*` pattern (`settings.py:239`).
- `insightface` keeps today's values exactly.

**FG-1b: calibrate the bands from error rates (offline tooling).**
- For each embedding space, select thresholds at declared FPIR points with `calibrate_face_thresholds.select_threshold`. Use identity-disjoint folds (CAL-07) and the [FIRBENCH-1](../tasks/firdv/FIRBENCH-1-scope.md) protocol: k=5 identity- and PSU-disjoint folds, with the non-mated population defined there.
- Proposed points, reused from PUBFIG: strong at FPIR ≤ 0.001, possible at FPIR ≤ 0.01. Report FNIR at each point (EVAL-18), end to end so that detector misses count (EVAL-16).
- **Resolvability.** A point is resolvable only when the sealed test fold holds n_nonmated_eff ≥ 3/FPIR: 300 at 0.01 and 3,000 at 0.001 (FIRBENCH-1 scope line 83). Below that the calibrator emits `unresolvable` for the point and never extrapolates.
- **What counts as a unit.** Count people, not photos. A unit is one person who is not enrolled in the gallery. When people share photos, the unit is FIRBENCH-1's PSU, an image–identity connected component (scope line 92). False matches cluster on lookalikes, so a second photo of the same person adds little (EXP-23, AUDIT-11). Recommend counting each PSU once for this check, because the within-person correlation of false matches cannot be estimated when almost none are observed. Also recommend leaving FIRBENCH-1's per-image background units (scope line 122) out of this count: they measure false names on non-face detections, not lookalikes.
- Score-versus-threshold ties follow `accept_predicate.accepts`, the single authority ([FIR-12 BR-72](./fir12-br72-accept-predicate-single-authority.md)).
- Output: one JSON artifact per space with points, thresholds, FNIR, n_nonmated_eff, fold ids and the corpus manifest hash. The tool writes no settings.
- Runs on the VM only.

**FG-1b sizing.** The measurement needs three disjoint groups of people.
- Gallery: N enrolled people with 3–5 enrollment photos each. N is the largest library the claim covers. At a fixed threshold, FPIR rises roughly in proportion to N, so every result states N.
- Mated probes, for FNIR: 2–5 photos per gallery person, from sessions not used for enrollment. About 140 effective mated searches in the test fold give FNIR within ±5 points near 10%.
- Non-mated probes, for FPIR: people never enrolled, one face each, each from a different photo and event, in the deployment's quality mix.
- With k=5 and one sealed test fold (FIRBENCH-1 scope line 35), the test fold holds a fifth of the people. The non-mated total is therefore five times the test-fold floor.

| Point | Non-mated people in the test fold | Non-mated people in total at k=5 |
| --- | --- | --- |
| Possible, FPIR ≤ 0.01 | 300 (no false match allowed) to 630 (two allowed) | 1,500 to 3,150 |
| Strong, FPIR ≤ 0.001 | 3,000 (no false match allowed) to 6,300 (two allowed) | 15,000 to 31,500 |

At the zero-error floor, a system passes only when its true rate is far below the target: 74% of the time at a tenth of the target, 41% at three tenths. Allowing two false matches raises the pass rate at three tenths of the target to 71%. A per-slice claim needs these counts in every slice (FAIR-07).

**FG-1c: apply (gated).**
- Requested: extend the FIR-6 S4 apply commit from `face_pipeline` to every profile. The S4 owner decides.
- Requires the S4 corpus gate and operator ratification of the FIR-13 D3 operating point.
- An unresolvable point never gets a threshold that claims it. What runs instead is open question 2.

**FG-1d: confirm before naming (flag, default off).**
- When the target cluster is user-confirmed and named, an assignment that would pass becomes a suggestion instead of a membership. Joins into anonymous clusters are unchanged.
- Indicative shape: a new check under `recognition/application/assignment/checks/`, registered in `assignment/gate.py`, that turns the accept into a suggest for such clusters. `/scope` picks the shape.
- With the flag off, assignment output is byte-identical to today. Turning it on is the operator's answer to open question 3.

**Routing after apply.**

| Band | Route | Display |
| --- | --- | --- |
| Strong | Auto-accept into an anonymous cluster. A join into a user-confirmed, named cluster is suggested and confirmed while FG-1d is on (open question 3). | Measured cosine next to the named threshold (decision 10706) |
| Possible | Suggest; a curator confirms | Same |
| Below possible | Abstain. The face stays unassigned (CAL-02). | No match. An empty result is valid. |

A low-quality face caps at possible: generalise `_capped_band` from roster candidates to every band reader (SECD-14).

### FG-2: quality-gated templates (Who's solo-moment prints)

**Why.** Who builds a voice print only from moments when one person speaks alone. The face equivalent is that only faces with clear identity evidence may seed a cluster, anchor it or represent it. Weaker faces can still join through normal assignment.

**FG-2a: validate the proxy per embedder (tooling).**
- Candidates: the pre-normalisation magnitude (`EmbedBatchResult.norms`) and the existing sharpness and occlusion factors.
- Method: an error-versus-reject curve per embedder on identity-disjoint folds. Drop the lowest-quality fraction of faces and measure the false non-match rate at a fixed false match rate. The proxy is valid only if errors fall as rejection rises, inside every quality stratum reported (CAL-01, GRPH-23).
- Output: a verdict per embedder (validated or not validated) plus the curve. A proxy that fails for one embedder stays a no-op for that embedder (EMB-03).

**FG-2b: seed, anchor and representative gate (dark).**
- When a validated floor is configured, faces below it may join an existing cluster through assignment. They never seed a cluster, become an anchor, or get picked as a representative.
- Templates fuse the retained observations weighted by quality (EMB-02, EMB-07), through `representative_quality_composite_enabled`.
- Defaults stay no-op. Turning floors on is a gated apply, like FG-1c.
- Optional: uncertainty-penalised similarity (EMB-09) as one more offline arm. It does not ship from this request.

### FG-3: same-photo cannot-link during discovery (Who's overlap rule)

**Why.** Who knows that two voices at the same moment are two people. Two faces in one photo are two people too, except for mirrors, reflections, collages and photos of photos.

**Mechanism.**
- Derive cannot-link pairs at runtime from `media_id` for every face in a discovery batch, including existing members of candidate clusters.
- Do not persist the pairs, and do not add a `ConstraintSource` value. The curator constraints in `constraints.py` stay the only persisted constraints.
- Enforce the constraint in every discovery stage that can form or grow a cluster: the HDBSCAN output, anchor injection, complete-link validation and constrained HAC. GRPH-18 is why: a chain of merges can join two same-photo faces that were never compared directly.
- On a conflict inside a candidate cluster, keep the face with the higher mean similarity to the other members. Eject the others to the unassigned pool, where joint assignment can place them later. Break ties by face id so the result is deterministic.
- A curator MUST_LINK between two same-photo faces overrides the derived constraint, for example a confirmed mirror. Align any automatic exception with the FIR-6 S5 mirrors stratum (plan line 115).
- Ship behind a flag, default off. Flip it only after the FG-4a arm shows no FNIR regression at the declared FPIR.

**Done when.** With the flag on, no discovered cluster on the eval corpus holds two faces from one photo. With the flag off, discovery output is byte-identical to today.

### FG-4: partition plus verification (Who's whole-recording matching)

**Why.** Who matches all speakers across the full recording before it decides. ACX discovery verifies each candidate cluster and shatters it into singletons when verification fails (G5).

**FG-4a: offline arm.** Add a decision-bearing ablation module beside `firbench_clusters.py`. Leave the S4 diagnostics module as it is.
- **P0:** today's production discovery reproduced offline: HDBSCAN with epsilon 0.45, complete-link validation and shattering.
- **P1:** a mutual k-NN graph (GRPH-17), with a per-space edge floor from FG-1b and edges validated per quality stratum (GRPH-23). Partition by normalised cut or conductance (GRPH-19), then verify each part with the same complete-link rule (GRPH-22).
- **P2:** P1 plus same-photo cannot-link (FG-3).
- Metrics per arm and per space, using the S4 definitions: pairwise and B-cubed precision and recall, merges, fragmentation, same-photo violations and unknown-absorbed. Add downstream FNIR at the declared FPIR (EVAL-16).
- Runs on the VM only. Pseudonymised ids only.

**FG-4b: production switch (gated).** If P1 or P2 wins in both spaces, replace the singleton split at `discovery.py:222` with the normalised-cut split, behind a flag.

**FG-4c: library re-partition (suggestions only).** A periodic whole-library pass proposes merges and splits as suggestions. It never relabels a cluster, never moves a curator-confirmed face, and respects every constraint. Cadence is open question 8.

### FG-5: face-level search by example (Face's "pick one photo")

**Route:** `GET /identities/{identity_id}/similar-faces?top_k=…`, following the existing `/identities/{identity_id}/…` naming.
- **Tenant scope.** The tenant id must reach the query; row-level security alone is not the test. A face id from another tenant returns 404.
- **Probe.** The probe is an existing face in the tenant's library. Uploaded probes are not accepted. MLDATA-16 bounds the searchable population to the tenant's own library. PROV-12 scopes the purpose to curation of that library.
- **Same space only.** Candidates share the probe's `model_id` (`models_are_same_space`, fail closed; EMB-01).
- **Index.** Use the `MediaIdentity` ivfflat cosine index. Two risks: `ivfflat.probes` is unset today, and a tenant filter applied after an approximate scan can return fewer than `top_k` rows. RED test: compare approximate results with exact search on a seeded fixture and report recall (IDX-01). `/scope` picks either a probes setting or an exact-scan fallback for small tenants.
- **Result fields.** Each row carries identity id, media id, cluster id (nullable), measured cosine, band, and the named threshold the band used (decision 10706, HAI-08). An empty result is valid (CAL-02).
- **Validation.** Reuse `validate_entity_id` and `validate_top_k` (`interface_adapters/http/validation.py`, `MAX_TOP_K = 500`; reject out-of-range values, never clamp).
- **Deletion.** A deleted face disappears from results at once (RAG-10).
- **Surface.** API only. The UI rides UXREC-1 and CURUX-1 ([ADR-019](../adrs/ADR-019-person-anchored-curation-surfaces.md)); HAI-17 applies there.

### FG-6: minimum-photos listing filter (Who's `keepingSpeakers(minimumShare:)`)

- Add `min_photos: int | None` to `GET /clusters`. It counts distinct `media_id` values among a cluster's faces, not `identity_count`.
- Add `photo_count` to `ClusterResponse`.
- Default: no filter, which is today's behaviour. The UI default is open question 4.
- Reject `min_photos < 1` with 400, the same way `validate_top_k` rejects.
- Filter before `limit` and `offset`, so pages stay full and stable.

### FG-7: anonymous numbering invariants (Who's numbering)

Tests only:
- A label is never reused after its cluster is deleted, merged or dismissed.
- Creating new clusters never changes an existing label.
- Concurrent allocations get distinct numbers.
- A curator rename does not move the counter.

Ordering by first appearance is Not-Doing.

### FG-8: optional recall arms (inference only)

These arms come from the earlier advisory. They raise recall for faces the detector misses, and probably belong in their own scope.

**Arm order:**
- **E:** oracle head boxes. Stop if FNIR does not improve.
- **C:** registered person detectors `rt_detr`, `d_fine` and `pp_picodet` (`MODEL_INGEST_ENTRIES`, `scripts/train/occlusion/license_policy.py:802`).
- **D:** pose-guided head crops, only if D beats C. Candidates: RTMPose or RTMO with COCO-only checkpoints, ViTPose, DWPose and MediaPipe. Each needs a `MODEL_INGEST_ENTRIES` row.

**Ruled out by licence:**
- Ultralytics YOLO-pose (AGPL).
- YOLO-NAS-pose (non-commercial, `license_policy.py:628`).
- OpenPose (non-commercial).
- Sapiens (CC BY-NC).

**Rules:**
- Recovered head crops re-enter the normal YuNet → alignment → embedding path.
- Body and pose boxes feed only the face pipeline and never become identity evidence (PROV-12).
- End-to-end FNIR counts detector misses (EVAL-16).

## Success criteria and eval cases

Each criterion becomes a case in `docs/scopes/facegroup-evals.json` at `/scope`.

| # | Criterion | Eval case | Capability |
| --- | --- | --- | --- |
| 1 | Each profile resolves its own knobs, and defaults are unchanged | Unit: resolution matrix over the three profiles, with and without environment overrides | FG-1a |
| 2 | Calibrated thresholds hold their FPIR on held-out folds | Eval: held-out FPIR ≤ the declared point at the 95% upper bound | FG-1b |
| 3 | No threshold claims an unresolvable point | Unit: the calibrator returns `unresolvable` when the test fold's n_nonmated_eff < 3/FPIR. 3,000 photos of 300 non-mated people do not resolve 0.001. | FG-1b |
| 4 | Band comparisons agree with the accept predicate | Unit: a score exactly at τ lands the same way in `band_for` and `accepts` | FG-1 |
| 5 | No floor ships without a validated proxy | Unit and eval: floors stay no-op unless that embedder's verdict is validated | FG-2a |
| 6 | With a floor on, low-quality faces never seed, anchor or represent | Unit | FG-2b |
| 7 | With the flag on, no discovered cluster holds two faces from one photo | Unit and eval | FG-3 |
| 8 | With the flag off, discovery output is byte-identical | Unit: golden discovery output | FG-3, FG-4b |
| 9 | The partition arm reports every metric per space against P0 | Eval: artifact schema check | FG-4a |
| 10 | Search is tenant-isolated and same-space only | Integration: cross-tenant probe returns 404; cross-model candidates are excluded | FG-5 |
| 11 | Search recall against exact search is measured | Eval: recall@k on a seeded fixture | FG-5 |
| 12 | Deleting faces leaves nothing behind and nothing to retrain | Integration: after delete the face is absent from search results, clusters, centroids and representatives (RAG-10, PROV-10) | FG-5 |
| 13 | `min_photos` counts distinct photos and pages stably | Integration | FG-6 |
| 14 | Labels are never reused or renumbered | Unit and integration | FG-7 |
| 15 | Every metric is reported per quality stratum, with the worst slice | Eval: report check (CAL-01, FAIR-07) | FG-1, FG-2, FG-4 |
| 16 | End-to-end metrics count detector misses | Eval: FNIR denominators include undetected ground-truth faces (EVAL-16) | FG-1, FG-4, FG-8 |
| 17 | While FG-1d is on, no face joins a user-confirmed, named cluster without a curator | Integration: seed a confirmed, named cluster and a face above the accept threshold. The outcome is a suggestion and the weave does not name the face. With the flag off, the outcome is unchanged. | FG-1d |

## Dependencies and gates

| Dependency | Relation |
| --- | --- |
| [FIR-6](../tasks/fir/FIR-6-calibration-quality-switchover-task-plan.md) S4 | FG-1c and the FG-2b floors apply through its single apply commit. S4 is corpus-gated (lines 19, 135, 137). |
| [FIRBENCH-1](../tasks/firdv/FIRBENCH-1-fir-benchmark-tool-task-plan.md) | Protocol for FG-1b, FG-2a and FG-4a. Its model pick decides which space is calibrated first. |
| [FIR-13](../tasks/fir/FIR-13-open-set-gate-contract-task-plan.md) | GateContract; the D3 operating point stays unset until the operator ratifies it |
| [FIR-12 search adapter](./fir-12-search-adapter.md), [BR-72](./fir12-br72-accept-predicate-single-authority.md) | `argmax_gallery` is the harness 1:N search; `accept_predicate` is the single score-versus-τ authority |
| [ADR-016](../adrs/ADR-016-auraface-512d-activation-refusal.md) | AuraFace stays activation-gated, so `auraface` work is dark until activation |
| [ADR-011](../adrs/ADR-011-retire-on-device-recognition-remote-only.md) | Recognition is remote-only; nothing here runs on device |
| [ADR-018](../adrs/ADR-018-post-curation-identity-weaving.md) (proposed) | Curated names are woven into descriptions; GPUFLOW-3 N0 already re-weaves cached descriptions with the confirmed faces. A false join into a named cluster can therefore put a wrong name into alt text, which makes it the costly error (open question 3). |
| [WBTRUST](./workbench-curation-trust-scope.md), decision 10706 | Display contract for scores |
| [CURUX-1](../assessments/current/curux-1-identity-curation-screens-2026-10-16.md) / ADR-019, [UXREC-1](../tasks/uxrec/UXREC-1-workbench-recovery-task-plan.md) | UI for FG-5 and FG-6 |
| [PUBFIG](./public-figure-library-scope.md) | Merges its candidates into roster candidates, the `SimilarityBand` reader (scope lines 20 and 63). FG-1b reuses its FPIR points (lines 333–335). Its auto-name rule (decision 18958, line 66) is the public-figure counterpart of open question 3. |
| [FIR scope (E22)](./commercial-face-identity-replacement.md) | "Clustering algorithms are dimension-agnostic … and need calibration only" (line 37). No training in the MVP (lines 101, 107). No A10 spend and no SCRFD/AdaFace retrain before D-01 (line 119). |
| buffalo_l | Eval and judge reference only; never user-facing, never training data |

## Open questions and recommendations

1. **Which space first?** Recommend building FG-1a and FG-1b for both spaces, then calibrating whichever space FIRBENCH-1 picks first. The other stays dark.
2. **What runs while a point is unresolvable?** On today's corpus neither point resolves (open question 7). Today joins use a legacy cosine. Recommend keeping that value for anonymous clusters only, recorded as "uncalibrated" in the decision log, until the point becomes resolvable. Never label it with an FPIR it cannot support.
3. **May a strong match auto-join a named cluster?** Today it can (G9). Recommend no: turn FG-1d on, so a curator confirms every join into a user-confirmed, named cluster, at least until a ratified FPIR point is resolvable. A false join can put a wrong name into a description (SECD-14, ADR-018). PUBFIG does auto-name public figures on a strong match (decision 18958), but only with calibration evidence for the tier and only when the image's setting is a public role. Tenant libraries hold private people and have no calibration evidence yet.
4. **What should `min_photos` default to in the UI?** The API default is no filter. Recommend deciding the UI default with CURUX-1.
5. **Which same-photo exceptions exist at launch?** Mirrors, reflections, collages and photos of photos. Recommend a curator MUST_LINK as the only exception; no automatic mirror detection until FIR-6 S5 measures the mirrors stratum.
6. **Search surface?** Recommend API only in this feature; the UI rides CURUX-1.
7. **Is the corpus big enough?** The capacity assessment counts 130 identities in the manifest, 87 in the personal partition, and 15 of those appear in only one image ([assessment](../assessments/current/fir-model-capacity-and-training-2026-09-19.md) line 65). FIRBENCH-1's current evidence is 30 probes from 17 identities (task plan line 32). No: even if all 130 people were non-mated test probes, the best zero-error claim would be 3/130, about 2.3%, so neither point resolves. The FIR report's only non-mated number does not change this. Its M-06 row reads 0.986 (204/207), but the 207 are stranger faces, not people: `face_metrics.py` lines 67–71 (FIR5RR-13) say they cluster within images and within unnamed individuals. Even if they were 207 independent people, at most 3 false accepts bound FPIR at 3.7% (exact binomial, one-sided 95%), and zero would still bound it at 1.4%. At k=5 the possible point needs about 1,500 distinct non-mated people and the strong point about 15,000 (FG-1b sizing). A 1:1 calibrate/test split would cut those to about 600 and 6,000, but the smaller calibration set makes the threshold more conservative and FNIR higher. Recommend planning for both points to be unresolvable at first apply. Decide at `/scope` the fold split and a licensed source of non-mated people: `RESEARCH_ONLY_SOURCES` excludes the large public face sets, Open Images needs per-image licence checks, and generated faces are not identity evidence. Public faces from Wikimedia Commons are open question 9.
8. **How often should the library re-partition?** Recommend after scan jobs, suggestions only, with the trigger size chosen at `/scope`.
9. **Can public faces from Wikimedia Commons supply the non-mated people?** There are enough of them, but permission is not settled. Recommend using them only after counsel answers [PUBFIG](./public-figure-library-scope.md) call 3, only as a separately reported stratum, and never as the production FPIR.
   - **Supply.** Wikidata lists 1,421,991 people with an image (P18). 647,152 of them were born 1926–2008 and have no recorded date of death (QLever count, 2026-10-27). These are upper bounds: filtering to single-face photographs will cut them, but the strong point needs about 15,000. The population skews male: 307,387 of the 1,421,991 (22%) are recorded as female, so the per-slice floors (FAIR-07) bind on the smaller slices first.
   - **A free licence is not consent.** CC BY 4.0 §2(b)(1) leaves publicity, privacy and similar personality rights outside the licence. The Commons guideline on identifiable people says the same, and many files carry the `{{Personality rights}}` warning. Whether CC BY and CC BY-SA allow deriving a template at all is already PUBFIG counsel question Q5.
   - **A template is biometric processing, even for a public figure.** PUBFIG's public/private line (scope lines 149–165) covers the law: GDPR Art. 9 applies, the OPC's Clearview findings held that publicly accessible images are not "publicly available" and that facial biometrics need express consent, and BIPA has no public-figure exemption. PUBFIG line 147 puts "building templates for the calibration benchmark" inside counsel call 3, so this measurement waits on the same answer. A CC licence did not stop the BIPA suits over IBM's Diversity in Faces set, which was built from CC-licensed Flickr photos. Amazon and Microsoft won summary judgment in 2022 on extraterritoriality, not on the licence.
   - **Deceased people.** GDPR does not cover them (Recital 27), and PIPEDA allows disclosure 20 years after death (PUBFIG line 165, which also asks counsel to verify both). Wikidata has 197,889 people with an image who died between 1950 and 2006. Older photos are a different capture regime from tenant photos (EVAL-20), so this route trades legal risk for validity.
   - **Validity conditions if counsel agrees:**
     - Report the Commons stratum separately (AUDIT-10) and never cite it as the production FPIR (FAIR-08). Commons portraits searched against a tenant gallery are a different cell from tenant photos searched against it (EVAL-20).
     - Public figures may be enrolled in a news tenant's gallery or in the PUBFIG library. Exclude anyone in the gallery under test and adjudicate every alarm before counting it as a false match.
     - The embedders' training identities are not fully published, and celebrity photos are common in face-recognition training sets. A face the model was trained on may be easier to reject, so FPIR can come out optimistic. Compare the impostor-score tail against in-distribution non-mated people (EVAL-15).
     - Use one photograph per Wikidata item and one face per photograph. Exclude paintings, drawings and sculptures. The unit is the person (EXP-23).
     - P21 records a public gender identity, not an observed attribute. Record that provenance on every slice label (PROV-04).
     - Keep a per-file licence and attribution record. Run on the VM only, with pseudonymised IDs, and give the copies the same access controls and deletion as consented data (PROV-11).
   - In-distribution non-mated people from the operator corpus or consenting tenants are still needed for the production claim.

## Not-Doing

- Any training: on tenant faces, fine-tuning, FIR-7 adapters, learned clustering, AdaFace retrain, classifier heads, per-tenant thresholds.
- Cross-tenant matching or any shared gallery.
- Uploaded or external probe images.
- Face attributes such as age, gender or emotion (Eye-style). CelebA is research-only.
- Video and face tracking.
- Non-face evidence for identity: time adjacency, clothing, VLM names, captions.
- Displaying probabilities or Jev-style confidence numbers.
- Automatic naming. `Person N` stays the only automatic label.
- Renumbering, or ordering by first appearance.
- The public-figure library; PUBFIG owns it.
- buffalo_l in any user-facing path.
- Local inference. Every eval run happens on the VM, and image-bearing outputs stay in ignored `benchmarks/private/`.

## Suggested slicing for junior agents

Every slice is two dispatches. First a RED dispatch writes failing tests only, with no source changes. Then an implementation dispatch makes those tests pass without editing them. Each RED brief names its eval cases from the table above.

| Wave | Slice | Owned paths (indicative) | RED tests | Notes |
| --- | --- | --- | --- | --- |
| W0 | `/scope` intake | `docs/scopes/facegroup-scope.md`, `docs/scopes/facegroup-evals.json`, task plans | none | Coordinator; answers the open questions |
| W1 | FG-3, flag off | `recognition/application/discovery/graph/`, `recognition/application/settings/clustering.py` | Cases 7, 8 | Behaviour unchanged until the flip |
| W2 | FG-6 and FG-7 | `routers/clusters_snapshot.py`, `schemas/responses.py`, cluster service and repository; tests around `auto_labeler.py` | Cases 13, 14 | Additive API |
| W3 | FG-1a | `recognition/config/settings.py`, `recognition/application/settings/clustering.py`, readers of the four moved values | Case 1 | Dark; values unchanged |
| W4 | FG-5 | New router and use case; read path on `MediaIdentity` | Cases 10, 11, 12 | Privacy rows reviewed at `/scope` |
| W5 | FG-1b | New module under `scripts/eval_harness/` | Cases 2, 3, 4 | Offline; runs on the VM |
| W6 | FG-2a and FG-2b | New error-versus-reject tool under `scripts/eval_harness/`; seed, anchor and representative gate in discovery | Cases 5, 6 | Dark |
| W7 | FG-4a | New module beside `scripts/eval_harness/firbench_clusters.py` | Cases 9, 15, 16 | Offline; runs on the VM. P1 needs W5's edge floor. |
| W8 | FG-1d, flag off | New check under `recognition/application/assignment/checks/`, registered in `assignment/gate.py`; flag in `recognition/application/settings/clustering.py` | Case 17 | Small and independent; can run first |
| Gated | FG-1c, floors on, FG-3 flip, FG-4b, FG-4c, FG-8 | none | none | Coordinator and operator decisions |

## Glossary for implementers

- **FPIR**: false-positive identification rate. The share of non-mated probes (faces of people not in the gallery) that are wrongly accepted at a threshold.
- **FNIR**: false-negative identification rate. The share of mated probes that are missed at that threshold, counted end to end.
- **Identity-disjoint folds**: no person appears in both the fold that selects a threshold and the fold that tests it.
- **n_nonmated_eff**: the effective number of independent non-mated units in the sealed test fold. For this request a unit is a person never enrolled in the gallery, or a PSU when people share photos. A photo is not a unit. It decides whether an FPIR point can be claimed at all.
- **PSU**: primary sampling unit. FIRBENCH-1 defines it as an image–identity connected component: a person plus everyone linked to them through shared photos. Floors and intervals count PSUs, not images.
- **Template**: the fused representation of a cluster, built from its retained observations.
- **Anchor**: an existing cluster's representative embedding, injected into discovery so that new faces can group with that cluster (`recognition/application/orchestration/clustering/discovery_pipeline.py:508`).
- **Representative**: a face picked to stand for its cluster when new faces are compared with it (`representative.py`). Representatives also serve as anchors.
- **Band**: strong, possible or none. A band routes an action. It is not a probability.

## Canon rows

Heuristics canon v0.26.2.

| Row | Rule |
| --- | --- |
| EMB-01 | One embedding space per comparison |
| EMB-02 | Quality-aware template fusion |
| EMB-03 | Use a validated quality proxy |
| EMB-07 | Fuse the retained observations, do not match on one |
| EMB-09 | Uncertainty-penalized similarity |
| GRPH-17 | Build a mutual k-NN graph, not a complete similarity graph |
| GRPH-18 | Never trust the transitive closure of a raw similarity threshold |
| GRPH-19 | Cut on normalised cut / conductance, not plain min-cut |
| GRPH-22 | Replace hard-τ-plus-components with partition-plus-verification |
| GRPH-23 | Validate graph edges across quality strata |
| GRPH-38 | Shortlist by similarity, adjudicate, allow abstention, backstop with traversal |
| CAL-01 | Measure FN differences within quality strata |
| CAL-02 | Unknown is a valid result |
| CAL-07 | Select face thresholds on identity-disjoint folds |
| CAL-11 | Quality gate, not decoration |
| EVAL-15 | Treat public benchmarks as contaminated |
| EVAL-16 | Upstream failure counts against the end-to-end metric |
| EVAL-18 | Non-mated probes and a score threshold, not rank |
| EVAL-20 | The slice is a cell of the pair, not a stratum of one side |
| EXP-23 | Pseudoreplication check |
| AUDIT-10 | Stratify the audit sample |
| AUDIT-11 | Account for cluster design effect |
| PROV-04 | Group-label provenance |
| PROV-10 | Deletion must reach artifacts that can only be rebuilt |
| PROV-11 | A derived copy inherits the source's access controls |
| PROV-12 | Consumers are scoped to the collection purpose, not merely registered |
| RAG-10 | Deletion must propagate to every index |
| MLDATA-16 | Bound face-search scope |
| SECD-14 | FP/FN harm polarity for face decisions |
| FAIR-07 | Prevalence ≠ incidence |
| FAIR-08 | Know your algorithm |
| HAI-08 | Uncertainty at the decision granularity |
| HAI-17 | Every reference the store holds |
| IDX-01 | Index recall is not model recall |

## Sources

External (behaviour only; no data was sent to these services):

- Desert Ant models: <https://desertant.com/models/>
- Desert Ant Who: <https://desertant.com/models/who/>
- Desert Ant Face: <https://desertant.com/models/face/>
- Jev typed decisions: <https://www.noze.it/en/insights/jev-system-one-typed-decisions/>
- Jev explained: <https://blog.gopenai.com/jev-explained-the-ai-that-refuses-to-write-a-word-b1788b932ae0>
- TypeSafe launch: <https://www.vktr.com/ai-platforms/chatgpt-cocreator-launches-typesafe-ai-with-jev/>
- Jev overview (Portuguese): <https://horadecodar.com.br/?p=46143>

Public faces (open question 9; read only, no data was sent):

- Commons guideline on identifiable people: <https://commons.wikimedia.org/wiki/Commons:Photographs_of_identifiable_people>
- Commons personality-rights warning: <https://commons.wikimedia.org/wiki/Template:Personality_rights>
- CC BY 4.0 legal code, §2(b)(1): <https://creativecommons.org/licenses/by/4.0/legalcode.en>
- OPC Canada, Clearview findings PIPEDA-2021-001: <https://www.priv.gc.ca/en/opc-actions-and-decisions/investigations/investigations-into-businesses/2021/pipeda-2021-001/>
- Amazon and Microsoft summary judgment (W.D. Wash., 2022-10-17): <https://perkinscoie.com/insights/update/amazon-and-microsoft-win-summary-judgment-illinois-bipa-lawsuits-based>
- Wikidata counts: QLever endpoint <https://qlever.dev/api/wikidata>, 2026-10-27. Every count is `COUNT(DISTINCT ?p)` over `?p wdt:P31 wd:Q5 . ?p wdt:P18 ?img`, plus: nothing else (1,421,991); P569 year 1926–2008 and no P570 (647,152); P570 year 1950–2006 (197,889); grouped by P21 (male 1,104,828; female 307,387).

Internal: the plans, scopes, ADRs and assessments linked inline above, and the code anchors in [Current pipeline and anchors](#current-pipeline-and-anchors).
