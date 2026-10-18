# FIRBENCH-1 comparison explorer: pinned v1 observations, requirements and future work

Status: **planning-only correction of residual UX-PLAN3-02 (gate-4 HOLD from independent reviewer commit `070b7a7bc3693e80f2816c1e672b70e96e126c17`: the required explorer `h2`/source-key copy had no named exact owner).** This is dispatch five (`UX-plan-state-r5`), following canon proposal MCP17204; it adds the prospective `resume-f-r5` explorer-copy grant to §4.3 P-07, §6 and §7 only. Dispatch four (`UX-plan-state-r4`) corrected UX-PLAN3-01/02 from reviewer commit `8a9958ada02325fa7268764f9e6f70d6bfc9dd75`. Low UX-PLAN4-01 (ASCII header column width) belongs to the map/ASCII owner and is not edited here. This lane owns only this plan and `.task-state/firbench-1/reports/UX-plan-state-r5-validation.json`. The master plan, model governance, scientific sections, product, tests, map and ASCII are read-only. Live finding and acceptance state stays in MCP; changing this document passes no gate. No inference, Monte Carlo, private corpus/DB/image/alias read, installation, push, merge or deployment is authorized here.

Source identity for this correction: supplied parentless privacy-verified snapshot `4747f0967b0c16ce66c2a7476f69237ea29f63b9`, with the **same** renderer SHA-256 `a536ea560e2bb063fcaeea6f851a351f2bb0df42799d28543b27cce2802bb210`. The bound exporter, renderer, CLI and other sources, frozen tests and evidence are byte-identical to r4's supplied snapshot `4e34534e527343ebffc6e165b2891a599734c3a8` (r5 receipt), so refreshed observations attributed below to `4e34534e`/`a536ea56` describe exactly these bytes. Stripped history is intentional. Refreshed observations below refer only to these exact bytes, never a moving HEAD. Inherited source observations and AST bounds outside this correction retain their historical attribution to author snapshot `6d921bf21dc7d3edc2ed26bf4c76f2499aea0ed3` (renderer `e51cc87bc368a4fc9dd8ef9d12a778bb224483a61494b3ace12c8a9827fa6d59`); they are not observations of a later composed candidate. Later code may differ (decision17191). Code-map coverage excludes scripts/docs/benchmarks, so bounded reads of actual supplied functions and fixtures, with exact hashes, are the fallback, not a complete graph. The r4 and r5 receipts record document validation only; earlier execution receipts remain attributed evidence.

Frozen common state: **“FIRBENCH explorer current-v1 state contract, freeze resume-f, decision17179”**, SHA-256 `0af216de41cccbd2788d824e1d363fecd2d9b626be9a5005bb0d094da68686cd` over the verbatim supplied text including its final newline. If this plan disagrees with that text, the frozen text governs and this plan is defective. `benchmarks/ux-maps/fir-bench.uxmap.json` and `benchmarks/reports/firbench-1-comparison-ascii.md` belong to a parallel owner working against the same frozen SHA.

Frozen ownership addendum: `resume-f-r4`, supplied SHA-256 `567beeabac5d4128364dd6f5d68198aedb9c39bea590f26641b0ff25560b0fb5`, alongside the unchanged state contract. Its exact grants and conflict edges govern §6. Prospective explorer-copy grant: `resume-f-r5`, SHA-256 `4c7ba3c1ef416355b19e5c5893b74ff92af12044e2977fb1ff6bc72951688b73` over its verbatim supplied text including the final newline. It supplements, and does not broaden, `567beeab` and `0af216de`.

Every behavior statement below has one of three labels:

- **CURRENT**: the pinned v1 contract or an explicitly attributed source observation, not a moving implementation inventory. Inherited observations use the historical author snapshot above; refreshed observations name supplied `4e34534e`/`a536ea56`. Earlier synthetic execution is attributed to its receipt. Implementation does not mean acceptance.
- **REQUIRED, PENDING**: an acceptance obligation; implementation status is stated separately. Existing implementation needs verification and independent acceptance, not repeated product work merely because this plan was refreshed.
- **FUTURE**: not a current route, wire or UI requirement. It needs a separately versioned, reviewed contract before anyone implements or depends on it.

## 1. Evidence boundary and reader jobs

The user's scope is historical exploration across **SFace128, InsightFace buffalo512 and AuraFace512**, plus grouping-method availability. The protocol's judge-side InsightFace role stays intact for inference and acceptance; it does not forbid descriptive UI columns. The explorer answers five questions: what was recorded, which population was measured, where it came from, what can be compared, and what is unavailable. It cannot turn a pipeline difference into an embedding-model-only effect.

| Evidence | What it supports and what remains unknown |
|---|---|
| `.task-state/firbench-1/ux/legacy-schema-aggregate.json` | Five inspected report candidates with four unique SHA-256 values; two buffalo artifact names share `84ed7fb3…`. `ort-yunet-sface` is 128-d, `buffalo_l` 512-d. AuraFace is not observed **in these five candidates**. The four unique hashes are **report variants, not independent runs**. Distinct hashes are distinct report bytes only. |
| Actual old producer `scripts/eval_harness/report.py` | `score_face_run_record` AST 4512–5332. `counts.scored` counts images; `matched_faces` counts faces. Refused, directional and floor states come from `_refused_face_identification_block` 3912–3934, `_refused_unknown_rejection_block` 3937–3952 and `_slice_status` 4063–4077. Sections carry `sampling_frame` (§3.4). Aggregate key lists show which fields exist, **not their numeric values**. |
| Legacy inventory arithmetic | SFace: 150 scored images, 189 matched faces, 186 detector misses. Buffalo: 150 scored images, 373 matched faces, 2 detector misses. Both recorded detection denominators `tp+fn` are 375. Equality does not establish exhaustive independent GT or equal inputs. Detector-only extra boxes are `fp`, not missed faces. |
| `recognition/infrastructure/face_pipeline/provenance.py`, `MODEL_MANIFEST` AST 104–168 | Configured 512-d AuraFace space. This is configuration evidence, not a historical report or measured result. |
| `benchmarks/manifests/fir-bench-decision-v1.json` | Present, unratified, unsealed; SHA-256 `7b89a3504d23b82c2a33e6fda1d52df2d181ec7d6bbfc9a5a24995c5f5ca5e2e`. No null rule is a pass. |
| `.task-state/firbench-1/ux/served-synthetic-preview.html` | SHA-256 `266c3a89e8969c56d6fa65e6a6af24d9ec2daee8fe7e11cdfd4231e88050d8b7`. Synthetic fixture: 5 independent units versus the required 50, intervals withheld, H1/H2 not evaluated. It is an insufficient-evidence state, not a population result. |
| User-supplied verified semantic reinjection (fresh ONNX `gte-base-en-v1.5`) | 17080 recovered the primary ignored historical 207 report. **18762: 150 shared source entries, 64 with the same and 86 with different representation hashes**. It makes **no raw-image or decoded-pixel parity claim**. 18708: search records are not classification evidence. 17142: the static glossary has independent scope. 17172: the actual producer carries `parameters.d_cut` only. 18886: plan/map state contradictions. 16891: exercise the actual producer, not a mocked wrong helper. Supplied evidence, not re-executed here. Never export underlying private locations or labels. |

Same counts do not show input parity. Shared entries do not show equal pixels; equal representation hashes do not show equal pixels either. `null == null` is not a verified binding. A duplicate hash is not an independent replication. Making the historical aggregates useful needs no private directory discovery, parallel path registry, private-table query, new source registry, private DB expansion or new GT collection.

Paths prefixed `scripts/` or `recognition/` are relative to `apps/prototype-description-service/`. The page's public provenance contains only reviewed artifact identifiers, digests and safe pointer metadata.

Inherited reference exception (UX-PLAN3-03): original L1's `code_ref`, `benchmarks/tools/fir_occ_label_queue.py`, is absent. The frozen dispatch identifies `apps/prototype-description-service/scripts/eval_harness/fir_occ_label_queue.py` as the actual supplied path; that path is also absent from this local parentless import, so its presence is dispatch-supplied context, not a verified local file observation. Preserve the original L1 object verbatim under the original-inventory contract. This note records the inherited reference/import exception, not a new product bug or a fabricated file; the parallel map/ASCII owner carries the corresponding reference note without rewriting that object.

## 2. Controlled vocabulary and exact metric mapping

The preferred label comes first; wire and protocol identifiers belong in source details or a secondary reference. Each definition states its population, denominator and limitation. No free category or identity text enters the export.

The committed v1 manifest is a source reference. It does not prove that every selected report used that decision. Show a leg pair or margin as active only when the run's recorded decision binding establishes it. Otherwise show “comparison question not recorded” next to the generic definition.

| Preferred label | Definition and typed source | Do not say |
|---|---|---|
| Recognition pipeline | Detector, alignment, embedder, gallery and scorer as one measured leg. UI columns: AuraFace, SFace, InsightFace (CURRENT order, §4.3). | “Embedding winner” from differing pipelines |
| Embedding model | The vector producer within that pipeline. Use only an exported recognized `model_id`; null means “model not recognized or not recorded”. | Pipeline and embedding model as synonyms |
| Grouping method | Partition of a pinned face/vector inventory within one embedding space. Historical cut settings and future fair-runner results are separate. | HDBSCAN result merely because metadata names HDBSCAN |
| Images scored / images failed | `counts.scored` / `counts.failed`; `total` is the run-record image population (`report.py` serialization inside `score_face_run_record`). | “Faces scored” for 150 images |
| Faces matched / labelled faces missed / extra detector boxes | `counts.matched_faces`; `detection.fn`; `detection.fp`. Detection recall `tp/(tp+fn)`; precision `tp/(tp+fp)`. Covers only the recorded complete-geometry association population. | Identification FNIR/FPIR, or independent exhaustive GT |
| Identification miss rate (FNIR) | Misses among eligible mated searches, where a true enrolled identity exists. End-to-end FNIR keeps undetected mates as misses. It is not simply `1 - legacy recall`. | Detector misses silently excluded |
| False identification rate (FPIR) | Non-mated source units producing any false identification, divided by the recorded eligible non-mated source-unit population, under the active aggregation rule. | Legacy `fp/(tp+fp)`, `1 - precision`, or “false positives” without a unit |
| Historical identification precision / recall | Exported `identification.headline` / `identification.full` from `slices.headline_identification` / `slices.full_corpus_identification` (`_face_pr_dict` AST 3955–3976). Not derived, not promoted to confirmatory rates. CURRENT renderer has no identification row (§4.6, gap P-06). | FPIR/FNIR interchangeable with face P/R |
| Historical cohort identification P/R (directional) | `slices.demographic.by_cohort.*` is named-face identification P/R. Strangers are excluded and `missed_gt` is not attributed per cohort (`face_metrics.py` `DemographicRollup` 1374–1389, `demographic_rollup` 1421–1477). **Not exported in v1.** | G1 FPIR, “lost faces by cohort” |
| Cohort / subgroup | A recorded population subset with a declared attribution rule. Genuine G1 needs per-cohort non-mated source-unit FPIR and denominators from its own producer; none exists here. | Demographic identification P/R as G1 evidence |
| Historical unknown rejection | Exported `unknown_rejection` from `slices.unknown_rejection`: correct rejects, false accepts, population, rate, numerator/denominator, floor. Its face-based frame is not independent source-unit FPIR. | G1 FPIR inferred from strangers |
| Historical grouping quality | Exported `clustering` numeric fields. `face_metrics.clustering_metrics_at_cut` AST 1632–1724 computes named matched-face single-linkage cut diagnostics: merge denominator M = co-clustered pairs; split denominator P_same = same-identity pairs. The cut value is exported only as `clustering.parameters.d_cut`. | Image count as grouping population; algorithm/metric inferred from `d_cut` |
| First question (H1 superiority) | Active manifest `[sface, auraface]`, margin 0: does the candidate improve end-to-end FNIR at FPIR .01? | H1 record = pass |
| Second question (H2 non-inferiority) | Active manifest `[auraface, insightface]`, margin .05. **Evaluate only after H1 passes** and every existing eligibility, guardrail, interval and H2 MDE gate allows continuation; otherwise “not evaluated: first question did not pass” (`firbench_score.decide` AST 844–967). | “Runs after H1 has a record” (CURRENT explorer glossary term `h2` uses this wording: gap P-07) |
| G1–G5 guardrails | Manifest veto/report-only rules; rules are null in current v1, so no pass/fail is declared. G4 is the allocated estimate in `firbench_score_io.timing_exposure` AST 553–611, not a stopwatch. | A guessed threshold or pass |
| Independent sampling units / effective sample size | `n_psu` versus dependence-adjusted `n_eff` from the recorded protocol. Faces, source entries and report hashes are not independent units. | Equal raw and effective counts by assumption |

No new estimand, formula, rule, threshold, seed, bootstrap B, replicate R, interval or fixed-order decision follows from this vocabulary. Frozen v6 H2 **126/2000=.063>.060** and cell power **1113/2000=.5565<.77** remain **FAILED** (`benchmarks/protocols/firbench-1-v7-implementation-ownership.md:119`). H2 and the scientific backlog stay on HOLD. No numerical acceptance is claimed.

## 3. Historical export (CURRENT exact producer wire)

### 3.1 APIs and command (CURRENT)

`scripts/eval_harness/firbench_comparison_export.py`:

```python
summarize_legacy_report(raw: bytes, *, artifact_id: str) -> dict
export_comparison(evidence_db: Path, artifact_ids: Sequence[str]) -> dict
write_export(payload: dict, out: Path) -> Path
```

```text
python -m scripts.eval_harness.firbench_cli comparison-export \
  --evidence-db PATH --artifact-id ID [--artifact-id ID ...] --out PATH
```

- **IDs.** `--artifact-id` is repeatable (`action='append'`) and required. Repeats collapse to a sorted unique set of 1–64 IDs (`MAX_ARTIFACT_IDS = 64`). Each must match `[A-Za-z0-9][A-Za-z0-9._-]{0,127}`.
- **Success.** Exit 0; stdout is the output path and a newline.
- **Refusal.** Exit 2; stderr is `error: ComparisonExportError: <fixed text>` (§3.6), and no output is written.
- **Pointer reads.** Only `firbench_evidence.show_artifact` (AST 463–469), `check_artifact` (482–494) and `resolve_artifact` (497–509). No private table, registry or second location store is used.

### 3.2 Supported inputs and unsupported refusal (CURRENT)

Supported input is **only** a pointer of kind `report-json` whose root object has `schema='acx-eval/v1'`, `kind='report'` and `report_kind='face_bakeoff'`. Any other pointer kind refuses **the whole export** with `artifact must be a registered report-json pointer`. Any other root schema/kind/report_kind refuses the whole export with `artifact is not an acx-eval/v1 face_bakeoff report`. The source `schema_version` is not read. There is **no `unsupported[]` inventory** and no partial export. A future inventory would need a separately reviewed version; it is not promised (FUTURE). No adapter exists for scores, clusters or comparison-v1.

### 3.3 Exact v1 wire (CURRENT)

`write_export` accepts only this shape. Serialization uses `sort_keys=True`, `indent=2`, ASCII escaping, `allow_nan=False` and a trailing newline. Extra or missing keys at any listed level are invalid.

| Member | Exact content and order |
|---|---|
| top level | **Exactly** `schema`, `schema_version`, `sources`, `dedup`, `reports`. `schema='firbench/comparison-explorer-export-v1'`, `schema_version=1` (exact int). No `unsupported`, status, path or free-text member. |
| `sources[]` | One per unique requested ID, sorted by `artifact_id`. Keys exactly: `artifact_id`, `file_sha256`, `kind`, `manifest_hash_kind`, `manifest_sha256`, `qualification`, `source_sha`. `kind='report-json'`; `qualification ∈ {unqualified, partial}`; `manifest_hash_kind ∈ {null, raw-sha256, legacy-model-dump-sha256}`; `file_sha256` 64 lowercase hex; `manifest_sha256` 64 hex or null; `source_sha` 40 hex or null. **No `status` field**; no path. |
| `dedup[]` | `{file_sha256, artifact_ids}`, one group per canonical file SHA-256, `artifact_ids` sorted. Groups are ordered by their lowest artifact ID, **not** by digest. Aliases are not independent runs, and equal hashes do not show input parity. |
| `reports[]` | One per dedup group, in dedup order. `artifact_id` is the group's lowest ID. Keys exactly: `artifact_id`, `clustering`, `compatibility`, `counts`, `detection`, `embedding_dim`, `file_sha256`, `identification`, `model_id`, `pipeline`, `qualification`, `slice_sections`, `unknown_rejection`. `compatibility='unknown'` always. `qualification` is the representative pointer's own value (no weakest-of-aliases computation; each alias keeps its value in `sources[]`; the CURRENT page does not render `reports[].qualification`). |

| Report field | Exact source → output |
|---|---|
| `model_id`, `pipeline`, `embedding_dim` | Read from the legacy top-level `model.{model_id, embedding_dim}` when that block exists. Otherwise read from singleton `provenance.model.model_ids` / `provenance.model.embedding_dims`; multi-element lists give null. `model_id ∈ {ort-yunet-sface, buffalo_l, auraface, null}`, and any other string becomes null. `pipeline` derives **only** from `model_id` (`sface`, `insightface`, `auraface`, or null). Leg fields are not read: a leg-only report has null pipeline. `embedding_dim` is an exact int in 1–4096 or null, never filled from a column label. |
| `counts` | Top-level `counts.{total, scored, failed, matched_faces, named_matched, stranger_matched}`. The first three are images; the last three are faces. |
| `detection` | Top-level `detection.{tp, fn, fp, precision, recall}`. |
| `unknown_rejection` | `slices.unknown_rejection.{correct_rejects, false_accepts, n, n_floor, rate, rate_numerator, rate_denominator}`. **Not exported:** `error_target`, `missed_stranger_gt`, `sampling_frame`, `status`, `directional`, `label`, `reasons`, `invariant`. |
| `clustering` | `{algorithm: null, metric: null, parameters: {d_cut}, false_merge, false_split, purity, n_faces, n_clusters, m_co_clustered, p_diff, p_same}`. **No top-level `d_cut`.** `algorithm`/`metric` are always null; the writer rejects non-null. **Not exported:** `sampling_frame` and status. |
| `identification` | `{headline, full}`, each with `tp, fp, fn, precision, recall, precision_numerator, precision_denominator, recall_numerator, recall_denominator, n_named_probes, n_recall_eligible, missed_gt, unmatched_detections, n_floor`. **Not exported:** `wrong_names`, `detection_recall_coupling_flag`, `sampling_frame`, `floor_unit`, `error_target`, notes, status fields, `invariant`. |
| `slice_sections` | Fixed-order subset of `clustering, full_corpus_identification, headline_identification, unknown_rejection` whose source section object exists. A refused section is still listed. **Presence is not value availability.** `demographic` and `occlusion` are never listed or exported. |

Counts are exact `int` (bool rejected) in `[0, 2^31-1]`. Rates and purity are finite numbers in `[0,1]`. `d_cut` is finite and `>= 0`. Strict UTF-8 JSON parsing rejects duplicate keys, `NaN`/`Infinity`, float overflow, and nesting deep enough to exhaust recursion. No other nesting cap exists. Source bytes are bounded at 16 MiB.

### 3.4 Scientific-honesty limitation: VALUE UNAVAILABLE, SOURCE STATUS NOT EXPORTED (UX-REGATE-02)

The producer emits refused sections with every value null (`refused: true`, `invariant`), directional/under-floor status (`status`, `directional`, `label`, `reasons`) and sampling frames on every gating slice. The v1 exporter keeps numbers only:

- A section flagged `refused: true` projects to **all-null values**, identical to an absent section, and is still listed in `slice_sections`.
- A directional (under-floor) section and a gating section with the same numbers project **identically**; no status, reason or frame survives.
- An explicit source null and an absent field both become null.

The first two bullets were exercised on public synthetic bytes through the actual `summarize_legacy_report` (receipt `witness`). The third follows from `live.get(name)` returning None for both cases.

**Chosen v1 limitation.** Every exported numeric null means **VALUE UNAVAILABLE, SOURCE STATUS NOT EXPORTED**. It does not establish not-recorded, absent, refusal, zero or an eligible denominator. A non-null value carries no exported gating, floor or qualification status, so it is a recorded descriptive number only. v1 does not silently extend the wire, and no new wire version is introduced here. “Not recorded” stays correct for **metadata** fields the export carries (`source_sha`, `manifest_sha256`, `manifest_hash_kind`, `embedding_dim`) when that exported field is null. A null `model_id` means “not recognized or not recorded”, because unrecognized strings are also nulled. A future separately versioned projection could carry a typed per-slice status and reviewed frame identifier (FUTURE, not promised). Map/ASCII must not promise source status or frame details for v1; that edit belongs to the parallel owner.

**P-01 numeric-null disclosure (REQUIRED, PENDING).** In supplied `4e34534e`/renderer `a536ea56`, numeric-null fallback, caption and glossary still use “not recorded” wording that overclaims for refused or unexported-status values. The numeric-null-copy owner (§6) must disclose VALUE UNAVAILABLE, SOURCE STATUS NOT EXPORTED; implementation and acceptance remain pending at this frozen baseline. The presentation fix already preserves the sparse count (P-04). Its frozen test `test_sparse_producer_rejection_preserves_count_and_labels_missing_denominator_and_rate` asserts “denominator not recorded” and “rate not recorded”; preserve that test and the reviewed count shape while reconciling disclosure through the owned copy regions and prospective null-status test. This is no request to repeat the presentation implementation or its completed targeted run.

### 3.5 Consumed-byte binding (CURRENT)

Every requested ID's pointer is read with `show_artifact`; kind must be `report-json`, and `check_artifact` status must be `matched` (`missing` → `artifact file is missing`, anything else → `artifact changed since registration`). For each hash group, only the representative ID is resolved; `resolve_artifact` yields the path, kept in memory only. `_read_bound`:

1. Does a no-follow `stat`, which must show a regular file.
2. Opens once with `O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC`.
3. Requires the descriptor's device/inode to equal the pathname's, and bounds pre-read size and streamed bytes at 16 MiB.
4. Requires identical device/inode/size/mtime_ns/ctime_ns across descriptor-before, descriptor-after and a pathname re-stat, and requires the byte count to equal the size.
5. Hashes exactly the parsed bytes and requires that hash to equal the pointer's `file_sha256`.

There is no second pointer re-read after the read. Do not claim one.

### 3.6 Fixed refusals and publication (CURRENT)

Fixed exporter texts (no input interpolation):

- `artifact ID must be 1-128 ASCII letters, digits, '.', '_' or '-', starting with a letter or digit`
- `artifact IDs must be a non-empty list of strings`
- `at most 64 artifact IDs can be exported at once`
- `artifact must be a registered report-json pointer`
- `artifact is not an acx-eval/v1 face_bakeoff report`
- `artifact report has a malformed field`
- `artifact report is not strict JSON`
- `artifact report exceeds the 16 MiB bound`
- `artifact report must be a regular file`
- `artifact report is unreadable`
- `artifact report changed while it was being read`
- `artifact report bytes do not match the registered SHA-256`
- `artifact file is missing`
- `artifact changed since registration`
- `output path already exists; refusing to overwrite`
- `output could not be written`
- `export payload failed validation`

Evidence-layer errors are re-raised with their fixed evidence texts.

`write_export` validates the whole payload before touching the filesystem. It writes `.{name}.{pid}.{random}.tmp` in the target's parent (`O_EXCL|O_NOFOLLOW`, mode 0600), then writes, flushes and fsyncs. It publishes with `os.link(temp, target)`, an OS atomic no-replace claim: an existing file, symlink, directory or competing writer is never replaced. Only its own temporary is unlinked.

### 3.7 Reader/producer validator differences (CURRENT, recorded)

The renderer validator (`firbench_explorer._validate`) accepts a superset the producer never emits. That superset includes source kinds `scores-json`/`run-manifest`, slice names `demographic`/`occlusion`, `wrong_names`, a non-null `algorithm ∈ {hdbscan, average, complete, median}` and `metric`, and null nested objects. **The producer wire in §3.3 is the contract**; reader leniency is not producer capability. Two bounds are narrower in the reader:

- counts: reader at most `10^9`, producer at most `2^31-1`;
- `d_cut`: reader in `[0,2]`, producer `>= 0`.

An exporter-valid file outside those reader bounds refuses at `explore` (gap P-08, low). Align the validators in the owning lanes; never mint a new input version to hide this.

## 4. Browser explorer

### 4.1 API, command and output (CURRENT)

```python
render_explorer(data_path: Path, out_dir: Path) -> Path   # returns out_dir / "index.html"
```

```text
python -m scripts.eval_harness.firbench_cli explore --data PATH --out DIR
```

Input checks:

- a `stat` size check at 1 MiB (`MAX_EXPORT_BYTES`), then `read_bytes`, with no no-follow or regular-file check (gap P-11, low); strict UTF-8 JSON with duplicate-key and non-finite rejection;
- closed-key validation (§3.7) and cross-checks: dedup equals sources, one report per file, each report's ID is an alias of its file;
- at most 64 entries per list.

Publication and output:

- **Output is a complete offline directory containing exactly `index.html`. No `data.json` sidecar is written.**
- The page is published by creating a sibling staging directory and atomically renaming it with no-replace: `renameat2(RENAME_NOREPLACE)` on Linux, `renamex_np(RENAME_EXCL)` on Darwin, otherwise refusal. Missing parent directories are created first and may remain after a failure. Owned staging is removed on failure.
- Success: exit 0, stdout is the returned index path and a newline (exercised).
- Refusal: exit 2, stderr `error: <fixed text>`, for example `invalid explorer export: <problem> at <schema location>`, `output directory already exists; choose a new --out path` (exercised), or `cannot publish explorer output; choose a writable --out path`.

Two-command orchestration on the remote VM is `comparison-export … --out EXPORT.json` then `explore --data EXPORT.json --out NEW_DIR`; open the printed index file. There is no browser bridge, DB access, report-pointer open or Python execution from the page.

### 4.2 One document, anchors and map panel aliases (CURRENT)

The page is one document with in-flow sections. It is not a SPA, router or modal. Native anchors:

- `#top`: the `<main>` element.
- `#results`: section with heading `#results-head`, the controls, the `#status` live region, the metric table and the conditional `#auraface-intake` callout.
- `#methods-head`: heading of the grouping availability section.
- `#source-evidence`: native `<details>` disclosure holding the source table and a nested “Source keys for code readers” disclosure.
- `#glossary`: the glossary section.
- `#term-<known-id>`: one per glossary term, 44 fixed IDs.

The map's seven explorer screens are **semantic panel aliases** in this one document, not routes:

| Map screen ID | Anchor in the one document | What it means |
|---|---|---|
| `explorer-home` | `#top` | Summary, compatibility-unknown banner |
| `explorer-runs` | `#results` | Per-pipeline report-file choice (`variant-<pipeline>`) |
| `explorer-pipelines` | `#results` | Three pipeline columns; a missing pipeline shows “No result in the selected set” |
| `explorer-grouping` | `#methods-head` | Method availability rows (`methods=`); historical grouping values stay in `#results` under `focus=grouping` |
| `explorer-measures` | `#results` | Metric table with the appropriate `focus=` value |
| `explorer-provenance` | `#source-evidence` | Native details disclosure |
| `explorer-terms` | `#glossary` | `#term-<known-id>` entries |

The original map objects are preserved unchanged: **10 screens, 4 jobs, 35 zones, 18 actions, 7 flows**, including L1 `l1-label-queue` (drawing/commit/cancel/undo/skip/export) and the static exit marker `exit-compare-refused`. That original exit has **no** invented loading, empty or error state (RLSE-04 does not fire for a static marker). The 17-screen map total is 10 original plus 7 aliases.

### 4.3 Page content (CURRENT)

- **Columns.** Three pipeline columns in fixed order **AuraFace → SFace → InsightFace** (`PIPELINE_ORDER`). Each pipeline with reports gets a `select#variant-<pipeline>` listing its artifact IDs in ID order. The first option is `config.defaults[pipeline]`, the first actual per-pipeline report. A pipeline with no report shows “No result in the selected set”, “No result” cells and **no control**, so it cannot be selected into existence. Reports with null pipeline are counted in a note and listed under source evidence.
- **Metric table.** 16 fixed rows in three groups. `detection` (7): images scored, images failed, faces matched, faces missed, extra detections, detection precision, detection recall. `strangers` (3): named faces matched, stranger faces matched, strangers rejected. `grouping` (6): merge rate, split rate, cluster purity, grouped faces, clusters, `d_cut` setting. Each row links its `#term-` definition. Values are rendered server-side; the page embeds only `{pipelines, defaults}` as JSON in a non-executing `script#explorer-config`, not the payload.
- **Grouping availability table.** 7 fixed rows (4 `in-tree`, 3 `other`). Availability and settings text only; no score and no Run control.
- **Other sections.** A “What this page does not evaluate” section. The source table shows ID, digest, kind, qualification, source commit and manifest hash. A static AuraFace intake recipe appears when no AuraFace report exists.
- **CSP.** `default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'`, plus `referrer no-referrer`. No fetch, network, localStorage or image load.

Requirements and explicitly pinned observations (product acceptance belongs in MCP; no product work is owned by this lane):

- **P-01** Null wording (§3.4).
- **P-02** Glossary caller restoration UX-RENDER05 (§4.5).
- **P-03 — IMPLEMENTED; independent acceptance pending.** Supplied `4e34534e`/renderer `a536ea56`: `_source_table` renders each source's `source_sha`, `manifest_sha256` and `manifest_hash_kind`, with per-field unknowns; `_provenance_summary` conditionally summarizes recorded fields and states that declared pins are not verified by this page. Verify lineage without inferring equal inputs or a winner (GRPH-14). The hard-coded absence was historical `6d921bf2`/`e51cc87b` behavior. Existing targeted evidence: `UX-render-metrics-r3-validation.json`, test `test_source_evidence_preserves_recorded_pins_and_per_source_unknowns` (UX-RENDER-03).
- **P-04 — IMPLEMENTED; independent acceptance pending.** In those same supplied bytes, `_value` preserves a known `correct_rejects` count with null `n`/`rate` and calls `_percent` only on a non-null rate. The earlier `_percent(None)` failure belongs to `e51cc87b`, not this baseline. Existing targeted evidence: the metrics-r3 receipt and frozen `test_sparse_producer_rejection_preserves_count_and_labels_missing_denominator_and_rate` (UX-RENDER-04). Numeric-null cause disclosure remains P-01; preserve this reviewed count shape.
- **P-05 — IMPLEMENTED; independent acceptance pending.** In those same supplied bytes, `_GLOSSARY`'s `auraface` tuple is a generic 512-dimensional definition conditional on the export's contents; the separate missing-AuraFace intake callout remains conditional. The blanket absence claim belongs to `e51cc87b`. Existing targeted evidence: the metrics-r3 receipt and `test_auraface_definition_does_not_claim_absence_when_all_pipelines_are_present` (UX-RENDER-07). Verify present/missing cases for acceptance without repeating completed implementation.
- **P-06** Exported identification P/R has no metric row. Showing it is a renderer decision for its owner; it is not current behavior.
- **P-07 — REQUIRED, PENDING; owner UX-explorer-copy (§6), not implemented at this baseline.** (a) Glossary term `h2` (`_GLOSSARY` tuple, AST 716–721) says H2 “runs only after H1 has a recorded result”, which contradicts the existing frozen order: H2 runs only after H1 passes. The “does not evaluate” section is correct. (b) Wire-key explanation: the nested “Source keys for code readers” list (`_render_page` 1269–1277) says `Grouping setting: clustering.d_cut, algorithm, metric`. The actual v1 paths are `clustering.parameters.d_cut`, `clustering.algorithm` and `clustering.metric`. The producer always emits null for the last two (`summarize_legacy_report` AST 255–303; `_check_report` 461–500 rejects non-null). This is the copy gap the companion map and ASCII record. Both parts are text/literal corrections only; they add no evaluation.
- **P-08** Validator bounds (§3.7), low.
- **P-09** Without script, selects/search render but do nothing, with no explanation (low). Native anchors and the details disclosure still work.
- **P-10** The intake recipe's “regenerate the comparison export” step shows only the `explore` command, not `comparison-export` (low).
- **P-11** The `explore` input read is `stat` then `read_bytes`: it follows symlinks, has no regular-file check, and leaves a gap between the size check and the read (low). The exporter's bound read (§3.5) is the reviewed pattern.

### 4.4 View state, controls and results (CURRENT)

Safe view state is **query parameters**; the native fragment is navigation only.

| Query parameter | Allowed values | Default | Invalid or unknown |
|---|---|---|---|
| `variant-auraface`, `variant-sface`, `variant-insightface` | An **artifact ID** in `config.pipelines[pipeline]`, never a digest | `config.defaults[pipeline]` | Falls back to the default. Ignored for a pipeline without reports. |
| `focus` | `all`, `detection`, `strangers`, `grouping` | `all` | `all` |
| `methods` | `all`, `in-tree`, `other` | `all` | `all` |
| `q` | Literal case-insensitive substring of a glossary term's label and aliases (not its definition text) | empty | (free text, trimmed on write) |

- **Reading.** The query is parsed once on initial load and on reload. Duplicate scalar fields use the first `URLSearchParams.get` value. Unknown parameters are ignored, and the serializer does not re-emit them.
- **Writing.** On every control update, `history.replaceState(null, "", path + query + location.hash)` emits non-default variant selections first. Their order is the embedded config key order, which `_script_json` sorts: auraface, insightface, sface. Then come `focus`, `methods` and trimmed non-empty `q`. The native hash is preserved; `history.state` stays null.
- **History.** Native fragment Back/Forward is browser navigation, not undo of filter mutations. No `popstate` listener re-reads the query. From the source (not browser-observed): after Back/Forward the address bar can show an older entry's query while controls keep their live values until the next control change or a reload.
- **Not implemented.** No 200-character cap, no “View settings reset” banner, no localStorage and no network.

| Object (INT-21 default → activated → updated; INT-22 result) | CURRENT behavior |
|---|---|
| Report file `select#variant-<pipeline>` | First per-pipeline report → choose another ID of that pipeline → that column's values switch to the chosen report and the URL updates. There is no clear/empty slot and no “Reset selections” command. |
| Metric focus `select#metric-focus` | `all` → choose a group → other metric groups hide. The `#status` live region reads “Showing N of M metric rows, X of Y grouping methods, and T of U glossary terms.” |
| Grouping methods `select#method-filter` | `all` → `in-tree`/`other` → availability rows filter. Never executes Python. |
| Term search `input#term-search` | Empty → type → only glossary terms filter (metric/method rows are unaffected), and the status count updates. On no match, `#term-empty` reads: No glossary term matches "<q>". Use Clear search and focus to show every term. |
| Escape in term search | Non-empty `q` → Escape → clears `q` only, and every other control is retained. |
| `button#clear-filters` “Clear search and focus” | Disabled at defaults → click → resets `focus`, `methods` and `q` to defaults, **keeps report choices**, focuses `#metric-focus`. |
| Source details `#source-evidence` | Closed → native summary toggle → the disclosure opens/closes itself. No raw private artifact open and no backend call. |
| Glossary link `a[href="#term-…"]` / “Back to results” `a[href="#results"]` | Native fragment navigation. If the target term is hidden by `q`, a `hashchange` handler clears `q` and re-applies. That loses the query, opener and scroll; P-02 covers it. |

The frozen state says no-match “offers Clear term search”. CURRENT markup offers Escape and the shared “Clear search and focus” button, which also resets focus and methods; no dedicated control has that label. This low wording/control difference is left for the renderer owner and the gate to reconcile; it is not claimed resolved.

### 4.5 Glossary return UX-RENDER05 (REQUIRED, PENDING; separate code lane)

Required behavior, from the frozen state and frozen test `scene/tests/test_eval_harness_firbench_explorer_interactions.py` (SHA-256 `e7e571f8…b6b88b7`, browser-gated by `FIR_EXPLORER_BROWSER=1`):

1. Before revealing a term hidden by `q`, retain the actual opener, query, scroll position and current controls.
2. Explicit Return and native Back restore the temporarily cleared `q`, the invoking control's focus and the scroll position (±2 px), while keeping report, focus and method selections and the URL parameters. Native hash navigation out of help also ends the temporary reveal.
3. Later manual choices made during help win; never blindly replay a stale snapshot. If the caller is now hidden, focus falls back to a visible control.
4. Direct entry without a caller (`?…&q=…#term-x`) reveals the term. Return keeps the URL's selections and query and focuses a visible `#results` control (the `#results` heading region).
5. Script-disabled native links still work.
6. No page errors across 1440/768/390/320 px × light/dark, with touch at ≤390 px.
7. No modal or router redesign.

Frozen-baseline observation: supplied `4e34534e` retains the caller-state implementation described in §4.4; glossary-state acceptance remains pending. Historical `UX-render-state-adj` receipts record `BLOCKED_ENVIRONMENT_NOT_RED`, `BLOCKED_PENDING_NORMAL_VM_RED_ACK` and `browser_green=false`: Chromium could not launch in that attempt, which is not a behavior RED. These are attributed receipt results, not live lane status or a new approval workflow. Actual browser evidence and independent acceptance belong to the caller-state owner and MCP.

Historical prediction for the unchanged caller-state region at this frozen baseline (TEST-06; not an observed failure by r4): `UX-RENDER05: explicit return must restore temporarily cleared glossary query`.

### 4.6 Not in current v1 (removed promises; FUTURE only if separately versioned)

None of these exists in current v1, and none is a current route or UI requirement:

- `#view=` router, `view` enum, `return_view`, `term` deep-link field;
- `scope`/`status`/`sort` facets, pipeline facet, metric/`method` facet;
- dialog/modal focus trap;
- clear/empty slot, “Reset selections”;
- digest-keyed selections, hash-fragment view state, `history.state` snapshot;
- 200-character `q` cap, “View settings reset” banner;
- live count of selected reports/images/faces;
- `data.json` sidecar or embedded full payload;
- `unsupported[]` inventory, `sources[].status`;
- per-slice status, refusal-reason or sampling-frame display;
- category (cohort/occlusion) rows;
- “Open original report”, “Run grouping”;
- identification rows (P-06).

Any of these would need its own reviewed contract version, browser regression and gate. Earlier text in this plan that required them is withdrawn.

### 4.7 Browser frame, type and visual verification

The renderer's CURRENT choices are:

- body `1rem/1.5` system UI stack;
- `main` at most `72rem`, prose at most `68ch`;
- headings 1.75/1.25/1rem;
- one breakpoint at `40rem`;
- tables in horizontally scrollable wrappers (each table has a caption), with sticky row headers and a 36rem table minimum;
- light/dark custom-property palettes.

These are renderer choices, not canon defaults, and not accepted. Acceptance needs measured evidence: computed size, measure and leading checked together (TYPE-02), with layout fit to the browser frame and the actual content (LAY-24) at the frozen test widths and 200% zoom, with no page-wide overflow or clipped control. Every text/UI pair needs a measured contrast ratio (A11Y-01: text ≥4.5:1, large text/UI ≥3:1), plus a keyboard walk (A11Y-11). Contrast and browser tests exist (`test_palette_meets_contrast_for_text_and_ui_in_light_and_dark`, `test_rendered_page_fits_four_widths_and_its_controls_work`). This lane ran neither, and no conformance claim is made (A11Y-22). Print grids, invented tokens and animation are not required.

## 5. Later grouping runner (FUTURE)

This section specifies a **later, separately reviewed producer**. It is not a dependency of the minimal historical explorer. A useful explorer on the existing wire comes before any grouping bridge, GT or numerical work. The runner reuses pinned existing embeddings per model: no inference, cross-space vectors, projected coordinates or parameter defaults from archive prose. The browser never invokes Python. The runner does not mutate an evidence DB or extend export-v1.

Future API: `run_grouping(embeddings, face_ids, method, *, binding, parameters, seed, gt=None) -> GroupingResult`. `binding` is mandatory and is checked against **consumed** bytes and face order before work. Methods with extra constraint inputs declare them as a distinct condition.

**GroupingResult wire `firbench/grouping-result-v1`, schema_version 1** (FUTURE; no module exists):

| Field group | Required semantics |
|---|---|
| Identity/status | Result ID, method enum, `available\|unavailable\|not_evaluated`, fixed reason code, producer code SHA, result digest. |
| Consumed inputs | Source artifact ID/SHA, consumed embedding-bytes SHA, matrix shape/dtype/order, ordered face-ID sequence SHA, inclusion hash, model-space and preprocessing hashes. Only safe digests and counts may reach a browser. |
| Geometry | Normalization policy and version, zero/nonfinite refusal, metric/units and any distance conversion. Never normalize differently across methods without saying so. |
| Executable/config | Library names and installed versions, code hash, validated parameter map, effective values, seed or deterministic policy, tie/order policy. |
| Partition | Private label vector aligned to face order; n_faces/n_clusters/n_noise/n_singletons; canonical labels by first occurrence. Noise is not one shared cluster. |
| GT binding | Independent GT artifact and face-binding hashes and the eligible population. Without it, quality `status='not_evaluated'` with null numerators, denominators and rates. |
| Quality | Merge = different-GT co-clustered pairs / M; split = same-GT separated pairs / P_same; purity = sum of majority counts / N. A zero denominator is undefined, never an achievement. |
| Consumer seam | A future reviewed aggregate projection plus a separately approved renderer input version. `explore --data` v1 refuses unknown documents. |

Recovery matrix (current sources; AST bounds from these bytes):

| Method | Exact current source / status | Next prerequisite before a fair run |
|---|---|---|
| Threshold-reference single-linkage | `firbench_clusters.reference_threshold_cluster` 196–213, called by `build_leg_diagnostics` 999–1177 | Adapt to the pinned binding/result contract; not production HDBSCAN |
| Average / complete HAC (cosine) | `firbench_clusters.cosine_dendrogram` 412–428; `ALLOWED_LINKAGE` 46 | Extract the actual cut partition; refuse an absent cut; no Ward on cosine distance |
| Production average HAC | `HierarchicalClustering.cluster_embeddings` 53–110 | Review linkage, the distance versus fixed-count branch, and singletons |
| Constrained HAC | `ConstrainedHAC.refine_clusters` 53–115 (median default linkage) | Pure adapter, immutable constraint binding, declared extra information |
| HDBSCAN | `HdbscanGraphAlgorithm.__init__` 19–46, `.cluster` 48–86; S4 metadata is not execution | Pin library/version and parameters; `d_euclid=sqrt(2*(1-cos))`; never reuse a cosine epsilon |
| DBSCAN | Not found in the bounded current `recognition/` + `scripts/eval_harness/` inventory; named in archive analysis | Recover or approve an adapter; not “never implemented” |
| Chinese Whispers | `recognition/infrastructure/clustering/` holds only `__init__.py`, `hdbscan_adapter.py`; archive analysis and hybrid strategy record removal; refs `11effe918`, `bbf1f0de7` are metadata only | Authorized recovery; pin graph, threshold, iterations, seed |
| Ward / K-means / hybrid variants | Archive prose only | Separately reviewed Euclidean-unit adapters; no invented quality |

The CURRENT page's grouping rows state this availability in fixed text, and no historical number is attributed to a method.

## 6. Ownership, composition and review

No subagents are spawned by this lane. Model routing, lane admission and review-packet contents have one authority: the read-only master plan's **Lane Decomposition**. The frozen `resume-f-r4` addendum governs the grants below. The prospective `resume-f-r5` grant adds only the UX-explorer-copy row. This plan stores pinned observations and requirements; live findings and acceptance stay in MCP (REF-09).

| Owner | Exact owned surface | Boundary |
|---|---|---|
| This lane, `UX-plan-state-r5` | This plan; `.task-state/firbench-1/reports/UX-plan-state-r5-validation.json` | Docs only; master plan, science, product, tests, map and ASCII read-only. Ships no product copy |
| Map/ASCII parallel owner | `benchmarks/ux-maps/fir-bench.uxmap.json`; `benchmarks/reports/firbench-1-comparison-ascii.md` | Same state and owner contracts; retain original objects and panel aliases (§4.2), exact state/API, and the L1 reference exception |
| Data/export owner | `firbench_comparison_export.py`; only the CLI `comparison-export` parser block and main `elif`; dedicated `comparison_export_wire`/`comparison_export_numeric` test files | Preserve export-v1 and its source-status omission decision; original exporter test is read-only |
| Validator owner | `firbench_explorer.py`: `_validate`, `_clustering`, `_number`, `CLUSTERING_KEYS`; dedicated `explorer_wire` test | No publisher, presentation, null-copy, caller-state or CLI grant |
| Publisher owner | `firbench_explorer.py`: `_write_atomically`, `_publish_staged_directory`, required stdlib imports; dedicated `explorer_publication` test | Distinct from validator symbols despite the shared module |
| Presentation owner | `firbench_explorer.py`: `_source_table`, `_provenance_summary`, `_value` strangers-rejected logic, `_GLOSSARY` AuraFace tuple, `_render_page` provenance paragraph; dedicated `explorer_presentation` test | P-03/P-04/P-05 implementation observed in supplied bytes; acceptance pending. Null-copy consumes the reviewed sparse-count result |
| Numeric-null-copy owner | `firbench_explorer.py`: `_cell` numeric-null fallback, `_GLOSSARY` not-recorded tuple, `_metric_table` numeric-null caption, `_value` strangers-rejected **TEXT qualifier only**; prospective dedicated `explorer_null_status` test | P-01; preserve count/rate logic and frozen presentation test. The null-status file is absent in supplied `4e34534e`, not an existing frozen test there |
| Caller-state owner, `UX-render-state-adj` | `firbench_explorer.py`: `_SCRIPT`; only if needed `_glossary` return-link markup / `_render_page` contextual-help attributes; dedicated `explorer_interactions` test | P-02; disjoint from presentation/null-copy, including their separate `_render_page` regions |
| Explorer-copy owner, `UX-explorer-copy` (`resume-f-r5`; pending prospective coordinator assignment) | `firbench_explorer.py` **only**: (1) the `_GLOSSARY` tuple whose id is `h2` (AST 716–721); (2) the `_render_page` nested “Source keys for code readers” literal list, from its opening `<details><summary>` through its closing `</ul></details>` (currently 1269–1277). Prospective dedicated `explorer_copy` test | P-07 text/literal correction only. Preserve HTML, anchors, query, API, wire and numerical behavior, including the trailing `</details>` that closes `#source-evidence` in the same 1277 literal. **Excludes** the `_render_page` provenance paragraph and contextual-help attributes; the `_GLOSSARY` AuraFace, not-recorded and every other tuple; `_source_table`, `_provenance_summary`, `_value`, `_cell`, `_metric_table`, `_SCRIPT`; validator, publisher and CLI; all old-report helpers. Original/frozen tests read-only. Not a product fix shipped by doc authors |
| Broad explorer/integration owner | Only explicitly remaining integration regions and the CLI `explore` parser block and main `elif` | **No whole-file grant**; excludes ALL assigned validator, publisher, presentation, null-copy, caller-state and explorer-copy regions above. No implicit grant to other glossary tuples or to any region not explicitly listed |
| Existing-report language/evidence/recovery owners | Their assigned regions in `firbench_report.py` / `firbench_glossary.py` and dedicated old-report language, evidence-links, empty-recovery and dynamic-language regression files | No explorer P-01/P-07, H2/AuraFace definitions or null tuple. `term_link` / `render_glossary(return_href='#verdict')` do not define explorer return policy. decision17190's `cc216ca7` binds exact reviewed reader-component bytes, not whole-task acceptance |
| Future grouping owner (unassigned) | Future runner and projection (§5) | Not started |

Test stems above resolve under `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_` with suffix `.py`. Each correction owner uses only its dedicated frozen test path; `explorer_null_status` is a named prospective owned path from a later author source. `explorer_copy` (`scene/tests/test_eval_harness_firbench_explorer_copy.py`) is likewise prospective. It is absent from supplied `4747f096`, and no test, dispatch or result exists for it. Every other owner row expressly excludes the explorer-copy regions, and no row carries an implicit remaining-region or whole-file grant. The original `explorer` test, shared typed fixtures and all other owners' tests are read-only: no cross-edits or weakening. Existing-report test stems are `report_language`, `report_evidence_links`, `report_empty_recovery` and `report_dynamic_language`, each with its own old-report owner.

**CLI composition (CURRENT).** `_build_parser` AST 1371–1415 holds the six original subcommands, `run`, `score`, `report`, `evidence` (help only), `compare` and `unseal`, plus the disjoint `explore` and `comparison-export` blocks. `main` AST 1431–1500 keeps the `evidence` fast path, `raw[:1] == ['evidence']` delegating before parsing. It adds an explicit `elif` for `comparison-export` and one for `explore` before the final `unseal` else. Neither owner edits the other's block.

**Work/data edges (GRPH-01/06/09).** The immutable state plus owner contract supplies the common input to plan correction, map/ASCII correction and the disjoint code groups. These branches may proceed in parallel: document alignment is not a prerequisite for code with the supplied shared contract. The descriptive explorer has no dependency on H2, new GT or new Monte Carlo.

The real **presentation-result → numeric-null-copy** edge carries the reviewed sparse-count shape from `_value`'s strangers-rejected branch. Both owners touch that branch, so those writes are not concurrently conflict-free; the null-copy owner changes only text qualifiers after consuming the presentation result. Caller-state `_SCRIPT` is disjoint and may proceed independently. Explorer-copy can be dispatched independently from the immutable source/state/owner contracts, in parallel with plan/map, caller-state and the input-boundary lanes. Its `h2` tuple and source-keys literal overlap no other grant, so sharing the module creates no serial edge. The current input-boundary lanes are not a planning dependency either. Validator and publication share a module but distinct symbols; sharing a file does not invent a serial edge. Data and integration share the CLI only through the disjoint `comparison-export` / `explore` literal blocks. Existing-report lanes own separate report files and do not supply explorer definitions.

The coordinator alone composes exact disjoint hunks and verifies AST/source outside each grant. An unresolved merge goes to the remote owner; it is not permission for local manual implementation. Final plan/map conformance and the composed actual producer/CLI/browser gates are **joins** of their required branches, followed by independent review; they are not a doc-first serial chain. Scientific/private/main-merge holds remain in force. This doc correction starts no product implementation or test run.

**Accountability coverage (§4.3; all at the frozen planning baseline).** Each required item has one named owner:

- P-01 numeric-null disclosure goes to numeric-null-copy.
- P-02 caller restoration goes to caller-state.
- P-03/P-04/P-05 are the existing presentation implementation, still needing independent acceptance.
- P-07 (`h2` ordering plus the wire-key explanation) goes to UX-explorer-copy.

The rest are not required code in this corrective bundle. P-06's identification row is an optional renderer decision, not an implicit required new metric. P-08/P-09/P-10/P-11 and the §4.4 no-match wording difference are inherited low observations. They remain pinned follow-up verification or re-scoping obligations, neither silently deferred nor turned into new scope. None is hidden under the broad integration grant.

## 7. Verification obligations (future; nothing here is a PASS)

This correction runs no product test or synthetic product witness. Its receipt records exact source/doc hashes, bounded source/fixture inspection, preserved state/API/science/inventory, correction checks and unresolved product acceptance. Earlier synthetic runs are evidence attributed to their original receipts, not execution by this lane. Existing acceptance obligations below remain with their owners; implemented presentation work needs no repeated fix or new test merely because prose changed:

- **Exporter.** Synthetic refused, absent, directional and available sections give the §3.4 projection. The stated whole-export refusals for unsupported kinds/schemas use the fixed texts. Bool, overflow, NaN and duplicate inputs refuse. Swap, mutation, symlink and oversize inputs refuse before output. A competing writer is preserved.
- **Renderer/composition.** Acceptance uses both actual commands on a public fixture, with only `index.html` in the output directory. Query parsing/serialization follows §4.4, including duplicates, unknowns, invalid enums and absent pipelines. Clear keeps reports. Escape clears only `q`. P-03/P-04/P-05 have implemented presentation evidence at `a536ea56`; independent acceptance remains pending. P-01 and glossary-state acceptance remain pending at this frozen planning baseline. P-07 remains pending with UX-explorer-copy: its prospective `explorer_copy` test is unwritten and unrun. Acceptance needs that test, the actual rendered page, and an independent review. The test must show that the `h2` definition states H2 runs only after H1 passes and that the code-reader list names `clustering.parameters.d_cut`, `clustering.algorithm` and `clustering.metric`. It must also show that markup and anchors are unchanged, and the coordinator verifies that no out-of-grant byte changed. Other inherited P-items require source-pinned verification or explicit re-scoping by their owners. Malicious synthetic strings create no markup or network request.
- **UX-RENDER05.** The frozen browser test runs on a normal VM: RED observed with the predicted message, then GREEN, then an independent gate.
- **Layout/contrast.** Measured per §4.7, or recorded as NOT RUN.
- **Frozen science.** Protected hashes are unchanged; no inference, simulator or Monte Carlo is rerun.

Any later authorized pytest runs from `apps/prototype-description-service` with only `/home/gate/workbay-sandbox/.venv-lane-feature-firbench-1-909fa00d/bin/python`, under `env OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.` and `-m pytest -q -n0 -o addopts= -p no:cacheprovider --basetemp=<fresh owned /tmp dir> --tb=short`. Never clean shared `/tmp/pytest-of-gate`.

## 8. Canon application (v0.26.2 full mirror)

Authority: `/home/gate/firbench-1-context/canon-full-0.26.2`, release `0.26.2`, dated `2026-10-14` (`meta/release-manifest.json`). Row text comes from the mirror; https://github.com/darce/heuristics-canon is only the reference link. Rows apply only where their trigger occurred. No approval workflow, token default or print grid is inferred.

| Observed trigger | Rule and exact source | Action and falsifier |
|---|---|---|
| Lane order for wire, renderer, UX-RENDER05, map and gate | **GRPH-01** Model the work as a DAG, then topological-sort (`lexicons/graph-theory.md:75`; *The Algorithm Design Manual*, ch. 7) | §6 work order. Falsifier: a step consumes an output whose producer has not run. |
| Ownership partition across exporter/renderer/language/map/runner | **GRPH-06** Partition by connected components first (`graph-theory.md:80`; *Graph Theory with Applications*, ch. 1) | §6 symbol/region grants and actual data edges. Falsifier: an undeclared overlap or an invented doc-first dependency. |
| Shared renderer symbols/CLI; plan versus map/ASCII contradictions (finding18886) | **GRPH-09** Colour the conflict graph (`graph-theory.md:97`; *Graph Theory with Applications*, ch. 8) | Disjoint regions except the explicit presentation → null-copy edge; coordinator composes exact hunks; conformance is a join. Falsifier: overlapping writes called conflict-free, or divergent state tokens. |
| Lane launches across VM capacity | **GRPH-31** Critical-path schedule the task DAG (`graph-theory.md:188`; *The Algorithm Design Manual*, ch. 17 + *Scheduling: Theory, Algorithms, and Systems*, ch. 5) | Master-plan admission by measured capacity, not graph width or an arbitrary cap. |
| Refused/directional/frame loss; representation-hash attribution; hard-coded provenance | **GRPH-14** Record provenance as a walkable lineage graph (`graph-theory.md:117`; *Building Knowledge Graphs*, ch. 8 + *Mental Models*, ch. 8) | §1 18762 wording as representation hashes, never pixel parity; §3.4 limitation; P-03. Falsifier: a null or digest is described beyond what its ancestor path supports. |
| Plan gap inventory mirrored older implementation and live acceptance | **REF-09** Mutable/derived-data drift (`lexicons/engineering.md:419`; *Refactoring: Improving the Design of Existing Code*, 2e, ch. 9) | Requirements plus explicitly pinned observations; MCP owns live findings/acceptance. Falsifier: historical `e51cc87b` behavior is asserted for `a536ea56` or later code. |
| Controls without complete state contracts | **INT-21** Specify interaction states (`lexicons/interaction-ux.md:237`; *Microinteractions*, ch. 3); **INT-22** Explain the result (`:238`; *Microinteractions*, ch. 4) | §4.4 table, live status text. Falsifier: a control whose activated/updated state is undocumented, or an inert control (P-09). |
| Glossary detour drops query/opener/scroll | **INT-16** Resume from preserved state (`interaction-ux.md:232`; *The Design of Everyday Things*, ch. 5) | §4.5 required, pending. |
| First run of a new or pending test | **TEST-06** Watch it fail once / predict the failure (`lexicons/engineering.md:494`; *Modern Software Engineering*, ch. 8) | §4.5 predicted message. Falsifier: passes before the fix, or fails differently. |
| Renderer frame/type choices exist but are unmeasured | **TYPE-02** Readability stool (`lexicons/design-aesthetics.md:104`; *Web Typography*, § designing-paragraphs-line-length); **LAY-24** Content-and-frame grid (`design-aesthetics.md:228`; *Thinking with Type*, ch. 3) | §4.7 measurement before acceptance. |
| Palette and interactive widgets present | **A11Y-01** Contrast floors (`lexicons/accessibility.md:73`; WCAG 2.2 SC 1.4.3 + *WebAIM Million 2026*); **A11Y-11** Keyboard walk (`:111`; WCAG 2.2 SC 2.1.1); **A11Y-22** Scoped conformance claims (`:155`; WCAG 2.2 § conformance) | Measured pairs and keyboard walk pending; no conformance claim. |
| Static exit marker | **RLSE-04** Undesigned state is a bug (`engineering.md:859`; bootstrap) | Does not fire for the unchanged static marker; no invented loading state. |
| Evidence path for each displayed value | **VIZ-23** Show the evidence path (`interaction-ux.md:360`; *Richard Feynman's Mental Models*, ch. 5 + *Envisioning Information*, ch. 4); **VIZ-32** Use a table for small exact-value tasks (`:369`; *The Visual Display of Quantitative Information*, ch. 9) | Exact tables, source evidence, compatibility unknown. |

Principles: **1** contract before components (the shared frozen contract already exists); **9** a claim must walk back (source/receipt lineage); **11** unknown is a designed state (VALUE UNAVAILABLE label); **12** correction must reach the source (r4 corrects the plan's stale observations and overlapping grants; P-03/P-04/P-05 already have source implementation, with acceptance pending); **18** machine contracts (exact wire, exit codes). Historical r3 card reads: CARD-01 `reasoning/contract-before-components.md`, CARD-02 `correction-at-source.md`, CARD-03 `designed-unknown.md`, CARD-08 `falsification-disconfirmers.md`, CARD-11 `measurement-integrity.md` (a sampling frame the export drops cannot be recovered from numbers). R4 revisits only triggered rows/principles/cards for lineage, derived-data drift and actual dependency/conflict scopes. NAV-13/WRIT-71 (`interaction-ux.md:164`, `writing.md:254`) continue to govern §2 vocabulary. R4 read hashes are in its receipt. R5 revisits only GRPH-01/06/09, GRPH-14, REF-09, CARD-02 and CARD-08 for the explorer-copy owner gap. Every required P-item now has one named owner. The falsifier is a required item with no owner, or an owner whose region overlaps another grant. R5 read hashes are in the r5 receipt.

## 9. Closure of UX-plan-gate-2 findings and remaining evidence

| Finding | Correction in this plan | What remains unproved or open |
|---|---|---|
| UX-REGATE-01 (route/state/selection contracts) | One frozen current-v1 state: query parameters, fragment navigation, artifact-ID variants, defaults from `config.defaults`, Clear keeps reports, Escape, no-match behavior. Seven map screens become panel aliases of one document. Router/facet/reset/deep-link promises are removed or marked FUTURE (§4.2, §4.4, §4.6). | Map/ASCII alignment by its parallel owner; P-02 (UX-RENDER05) and the no-match wording item; an independent re-gate across all three documents |
| UX-REGATE-02 (refusal/frame loss) | Explicit v1 limitation VALUE UNAVAILABLE, SOURCE STATUS NOT EXPORTED, chosen over a wire extension; directional/frame loss shown with the actual producer (§3.4) | P-01 renderer disclosure (pending) and the frozen-test wording tension; map/ASCII promise removal; future typed status only via a new reviewed version |
| UX-REGATE-03 (18762 attribution) | §1 and the receipt: 150 shared entries, 64 same/86 different **representation hashes**, no raw-image or decoded-pixel parity | None for this plan; other documents are checked by their owners |

Live UX-GATE-07/09 and finding acceptance state belongs to MCP. This plan closes no gate, ratifies or seals nothing, and does not override scientific/private/main-merge holds. A minimal useful historical browser can precede future grouping, GT or numerical work; the earlier plan receipt records two commands on public synthetic bytes, not execution by r4 or acceptance. All protocol numbers, existing commands and the frozen v6 failure are preserved.
