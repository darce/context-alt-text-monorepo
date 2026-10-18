# FIRBENCH-1 comparison explorer: current-v1 one-page interaction draft

The explorer is one offline page that shows historical aggregate report files side by side. A reader chooses one report file per pipeline, reads exact values with their denominators, and traces each value to its file digest. Historical reports remain descriptive and unqualified: no winner, paired difference, independent-ground-truth promotion or invented algorithm score. This draft is a hand-written planning companion to `benchmarks/ux-maps/fir-bench.uxmap.json`; it is not a rendering of that map, and it is not a browser test.

This fourth correction addresses MCP findings UX-PLAN3-01/02 and inherited reference note 03 from the independent planning review `8a9958ada02325fa7268764f9e6f70d6bfc9dd75`. The unchanged authority is *FIRBENCH explorer current-v1 state contract, freeze resume-f, decision17179*, SHA-256 `0af216de41cccbd2788d824e1d363fecd2d9b626be9a5005bb0d094da68686cd`, plus owner addendum **resume-f-r4**, SHA-256 `567beeabac5d4128364dd6f5d68198aedb9c39bea590f26641b0ff25560b0fb5`. Observations are frozen to supplied public snapshot **`4e34534e527343ebffc6e165b2891a599734c3a8`**, renderer SHA-256 **`a536ea560e2bb063fcaeea6f851a351f2bb0df42799d28543b27cce2802bb210`**, never moving CURRENT HEAD. “Current v1” names the frozen contract; later composed source can differ (17191). Live findings and acceptance stay MCP.

Historical cross-checks below belong to author source `6d921bf21dc7d3edc2ed26bf4c76f2499aea0ed3`, renderer `e51cc87bc368a4fc9dd8ef9d12a778bb224483a61494b3ace12c8a9827fa6d59`, and the r3 receipt; they were not rerun here. Supplied `a536ea56` implements per-source pins, conditional provenance summary, sparse rejection counts and a generic AuraFace definition, with targeted green recorded in `.task-state/firbench-1/reports/UX-render-metrics-r3-validation.json`; independent acceptance remains pending. Numeric-null cause disclosure and glossary-state acceptance remain pending at this baseline. This correction requests no repeated product implementation or new tests. Only the map, this draft and `.task-state/firbench-1/reports/UX-map-state-r4-validation.json` change; no product command or test runs here.

Fifth correction (r5): independent gate-4 review commit `070b7a7bc3693e80f2816c1e672b70e96e126c17` holds only residual UX-PLAN3-02, because the required explorer H2 and source-key copy had no named exact owner, plus low UX-PLAN4-01, a 73-column row in the 72-column §12 frame. This correction records the prospective explorer-copy grant **resume-f-r5**, SHA-256 `4c7ba3c1ef416355b19e5c5893b74ff92af12044e2977fb1ff6bc72951688b73`, in §2, §12 and §18, and fixes §12 and §13 frame widths. The planning baseline is supplied snapshot `4747f0967b0c16ce66c2a7476f69237ea29f63b9`, with the same renderer bytes `a536ea56`; the observations above stay pinned. Only the map, this draft and `.task-state/firbench-1/reports/UX-map-state-r5-validation.json` change; no product command or test runs here.

## 1. Original inventory and separate entry

The map starts from `.task-state/firbench-1/ux/original-fir-bench.uxmap.json`. Its 10 screens, 4 jobs, 35 zones, 18 actions and 7 flows stay equal JSON objects in their original order, and so do its four goals and six not-doing entries. S1–S8 remain the private report. L1 keeps drawing, commit, cancel, unknown marking, next, undo, skip/nonresponse and export. `exit-compare-refused` remains the static exit marker without invented loading, empty or error states: S6's refusal and S1's destination own those states.

Inherited reference exception UX-PLAN3-03: L1's original `code_ref`, `benchmarks/tools/fir_occ_label_queue.py`, is absent in supplied `4e34534e`; the owner addendum identifies the actual source path as `apps/prototype-description-service/scripts/eval_harness/fir_occ_label_queue.py`. That target is also absent from this local stripped transport tree and its Git root; the reference is retained exactly as supplied, without claiming local resolution or fabricating the file. The original L1 object stays verbatim under the inventory contract. This note records the inherited reference exception, not a new product bug.

The explorer is a separate entry. Its seven map entries are semantic panel aliases into sections of one document, not routes and not new screens of the private report. The explorer exports no images, face rows, pseudonyms, private labels or paths, and it has no bridge that opens a private report.

## 2. Two commands, two owners

```text
# Data owner: reads the evidence DB through show/check/resolve, writes one export file
python -m scripts.eval_harness.firbench_cli comparison-export --evidence-db EVIDENCE_DB \
    --artifact-id ARTIFACT_ID [--artifact-id ARTIFACT_ID ...] --out EXPORT.json

# Renderer owner: reads only that file, publishes one new directory
python -m scripts.eval_harness.firbench_cli explore --data EXPORT.json --out REVIEW_DIR
```

| Command | Owner and actual function | Success | Refusal |
|---|---|---|---|
| `comparison-export` | Data owner. `firbench_comparison_export.export_comparison` builds the payload in memory; `write_export` publishes it with an exclusive hard link | Prints the export path. The file is `firbench/comparison-explorer-export-v1` with exactly `schema`, `schema_version`, `sources`, `dedup`, `reports` | Exit 2 with fixed text, for example “artifact is not an acx-eval/v1 face_bakeoff report” or “output path already exists; refusing to overwrite”. An unsupported source schema or kind refuses the whole export |
| `explore` | Renderer owner. `firbench_explorer.render_explorer(data_path: Path, out_dir: Path) -> Path` | Prints the returned `REVIEW_DIR/index.html`. The directory holds only `index.html`, published by an OS atomic no-replace rename. There is no `data.json` sidecar | Exit 2 with fixed text, for example `error: invalid explorer export: …` or `error: output directory already exists; choose a new --out path`. Nothing is published |

The two CLI branches are disjoint blocks. The six original commands (`run`, `score`, `report`, `evidence`, `compare`, `unseal`) and the `evidence` fast path stay unchanged. In the export, `dedup` groups artifact IDs by `file_sha256`; there is one report per unique digest, keyed by its lowest artifact ID. Clustering carries `parameters.d_cut` only, with no duplicate top-level `d_cut`, and its `algorithm` and `metric` are null. No `unsupported[]` inventory or status field exists. This draft does not invent a new input version to carry more.

Cross-check, recorded in the receipt: the actual `explore` command on `.task-state/firbench-1/ux/export-v1-produced-fixture.json` printed `…/explorer/index.html`, published a directory containing only `index.html`, and refused a repeat run with exit 2 and the fixed “already exists” message.

That is the historical `6d921bf2/e51cc87b` cross-check in the r3 receipt, not execution against this frozen review baseline. Runtime ownership is narrower than the command labels: the broad explorer/integration owner has only explicitly remaining integration symbols and the CLI `explore` block, with every assigned region below excluded; there is no whole-file grant.

| Owner | Exact grant in supplied source / dedicated test |
|---|---|
| Validator | `firbench_explorer.py`: `_validate`, `_clustering`, `_number`, `CLUSTERING_KEYS`; `test_eval_harness_firbench_explorer_wire.py` |
| Publisher | `_write_atomically`, `_publish_staged_directory`, required stdlib imports; `test_eval_harness_firbench_explorer_publication.py` |
| Presentation | `_source_table`, `_provenance_summary`, `_value` strangers-rejected logic, `_GLOSSARY` AuraFace tuple, `_render_page` provenance paragraph; `test_eval_harness_firbench_explorer_presentation.py` |
| Numeric-null copy | `_cell` numeric-null fallback, `_GLOSSARY` not-recorded tuple, `_metric_table` numeric-null caption, `_value` strangers-rejected **TEXT qualifier only**; prospective `test_eval_harness_firbench_explorer_null_status.py`, absent in `4e34534e` |
| Caller state | `_SCRIPT`; only if needed `_glossary` return-link markup / `_render_page` contextual-help attributes; `test_eval_harness_firbench_explorer_interactions.py` |
| Explorer copy, `UX-explorer-copy` (prospective, pending coordinator assignment) | Only the `_GLOSSARY` tuple whose id is `h2`, and `_render_page`'s nested “Source keys for code readers” literal list, from its opening `<details><summary>` through its closing `</ul></details>` (lines 1269–1277 in `4747f096`); prospective `test_eval_harness_firbench_explorer_copy.py`, absent in `4747f096` |
| Data | `firbench_comparison_export.py` and the CLI `comparison-export` block; the CLI `explore` block stays integration-owned, disjoint literals only |
| Existing-report language/evidence/recovery | `firbench_report.py` / `firbench_glossary.py` and their dedicated old-report language/evidence/recovery/dynamic regression files; no explorer P01/P07 or implied H2/AuraFace definition grant |

Test paths above are under `apps/prototype-description-service/scene/tests/`; module paths are under `apps/prototype-description-service/scripts/eval_harness/`. Original explorer tests and shared typed fixtures are read-only to correction owners; no cross-edits or weakening of old-report tests. The prospective null-status file belongs to its later author source, not this snapshot.

**Explorer-copy grant `resume-f-r5` (P-07).** It supplements, and does not broaden, `resume-f-r4` and the state contract. Required outcomes: the `h2` definition says H2 runs only after H1 passes, the existing frozen order, with no new evaluation; the key list names `clustering.parameters.d_cut`, and the algorithm and metric keys as `clustering.algorithm` and `clustering.metric`. These are the actual v1 paths: `_clustering` 232–255 reads them, and the exporter writes both as null. The change is text and literals only. HTML, the `#term-h2` anchor, query, API, wire and numeric behaviour are preserved, including the outer `#source-evidence` `</details>` that shares line 1277. The grant excludes the `_render_page` provenance paragraph and contextual-help attributes, every other `_GLOSSARY` tuple (AuraFace, not-recorded and the rest), `_source_table`, `_provenance_summary`, `_value`, `_cell`, `_metric_table`, `_SCRIPT`, the validator, publisher and CLI, and all old-report helpers. Every other owner, including integration's remaining regions, excludes this grant; nobody holds the whole file. Original and frozen tests stay read-only. The owner awaits prospective coordinator assignment: no dispatch, test or result exists, and this doc lane ships no product fix.

From the immutable state and owner contract, plan correction, map/ASCII correction and disjoint code scopes proceed in parallel. Document alignment is not a prerequisite for code with that shared contract already supplied. **presentation-result → null-copy** is a real conflict/data edge: both touch the strangers-rejected branch, and null-copy consumes the reviewed sparse-count shape. Caller-state is independent of both; validator and publisher share a module but distinct symbols, with no invented whole-file serial edge. Explorer-copy is independently dispatchable, in parallel with plan/map, caller-state and input-boundary lanes; sharing `firbench_explorer.py` alone creates no serial edge. The coordinator alone composes exact disjoint hunks and verifies AST/source outside grants; unresolved merges go remote. Final plan/map conformance and composed actual producer/CLI/browser gates are joins. The descriptive explorer has no dependency on H2, GT or new MC; scientific/private/main-merge holds remain.

## 3. Recorded data, units and provenance

Safe source: `.task-state/firbench-1/ux/legacy-schema-aggregate.json`, `acx-eval/v1`, `report_kind=face_bakeoff`. The five entries have four distinct report hashes. Four unique report hashes are report variants, not independent runs. The two buffalo entries share one hash, so they name the same report bytes. IDs below are the aggregate's candidate names; registered artifact IDs may differ.

| Candidate artifact ID | Pipeline | Dimensions | Images scored | Faces matched | Report SHA-256 prefix |
|---|---|---:|---:|---:|---|
| golden150-fir-baseline-20260723 | SFace | 128 | 150 | 189 | c05fa6a7 |
| golden150-fir-final-20260723 | SFace | 128 | 150 | 189 | af3c3baa |
| golden150-fir-v2-20260723 | SFace | 128 | 150 | 189 | ff9dbaad |
| golden150-fir-buffalo-20260723 | InsightFace buffalo_l | 512 | 150 | 373 | 84ed7fb3 |
| golden150-fir-buffalo-baseline-20260723 | InsightFace buffalo_l | 512 | 150 | 373 | 84ed7fb3 (same bytes) |

No AuraFace report is in this set. That does not establish absence elsewhere, and the AuraFace column stays visible as “No result”. Supplied `a536ea56` already defines AuraFace generically as configured with 512-dimensional embeddings, with result/No result conditional on the export; that definition is implemented with targeted receipt, independent acceptance pending.

Images scored are images, not faces. In `apps/prototype-description-service/scripts/eval_harness/report.py`, `score_face_run_record` (AST lines 4512–5332 in this snapshot) writes `"scored": len(scoreable)` at line 5294, separately from `"matched_faces": len(assignment.matched)` at line 5296. So 150 is a count of scored media items.

| Renderer row label | SFace (baseline) | InsightFace (buffalo) | Source and meaning |
|---|---:|---:|---|
| Images scored | 150 of 150 images | 150 of 150 images | `counts.scored` of `counts.total` |
| Images that failed | 0 | 0 | `counts.failed` |
| Faces matched | 189 | 373 | `counts.matched_faces`; equals `detection.tp` in these reports |
| Faces missed | 186 of 375 labelled faces | 2 of 375 labelled faces | `detection.fn`; 375 = `tp + fn` recorded labelled faces |
| Extra detections | 0 | 2 | `detection.fp` |
| Detection precision | 100.0% (exact 1.0) | 99.5% (exact 0.9946666666666667) | `tp ÷ (tp + fp)` |
| Detection recall | 50.4% (exact 0.504) | 99.5% (exact 0.9946666666666667) | `tp ÷ (tp + fn)` |
| Named faces matched | 100 | 166 | `counts.named_matched` |
| Stranger faces matched | 89 | 207 | `counts.stranger_matched` |

The page shows rates as rounded percentages with their counts; exact rates are in the export. The arithmetic describes the reports' recorded detection inventory and does not prove independent exhaustive ground truth. Differences can come from detector, alignment, gallery, embedder and scorer, so no gap is attributed to the embedding model alone.

Grouping face counts are a different population. The task supplies historical grouping populations of **100 SFace faces and 166 InsightFace faces**, not 150. They are attributed, not present in the supplied safe aggregate, which lists clustering keys only. The aggregate's `counts.named_matched` is also 100 and 166; this draft does not infer that the grouping population is the named matched faces. The page shows “Grouped faces” only from the loaded export's `clustering.n_faces`.

Attributed provenance, not rerun here: the verified ONNX gte-base-en-v1.5 retrieval recovered the primary ignored historical evidence (17080). Record 18762 covers 150 shared entries with 64 same and 86 different **representation hashes**. That is representation-hash evidence only: it makes no raw-image or decoded-pixel parity claim, and shared entries do not prove equal pixels. Search records (18708) are not classification evidence. The independent glossary scope is 17142.

## 4. One document: sections and panel aliases

The page is one document of in-flow sections, not a single-page app, router or modal. Native fragments are navigation. The seven map entries alias these anchors:

| Map entry | Anchor | What is there | Query state it reads |
|---|---|---|---|
| `explorer-home` | `#top` | Heading, summary, Compatibility unknown banner | none |
| `explorer-runs` | `#results` (column headers) | A “Report file” select for each pipeline that has a report | `variant-<pipeline>` |
| `explorer-pipelines` | `#results` | Controls, status line, metric table, AuraFace intake note | all six keys |
| `explorer-measures` | `#results` with `focus=detection` or `focus=strangers` | Detection or stranger row groups | `focus` |
| `explorer-grouping` | `#methods-head` | Grouping method availability table | `methods` |
| `explorer-provenance` | `#source-evidence` | Native details: source table, code-reader keys | none |
| `explorer-terms` | `#glossary`, `#term-<known-id>` | 44 term articles and the no-match note | `q` |

Document order: `#top`, `#results`, `#methods-head`, “What this page does not evaluate” (`#notes-head`), `#source-evidence`, `#glossary`. No `#view=` router, view enum, scope/status/sort facet, pipeline facet, dialog, focus trap or term deep-link query field exists in current v1.

## 5. Desktop specimen

Planning frame 1440 × 900 CSS px. The selects show candidate default artifact IDs, abbreviated here only. Placeholders in angle brackets are values the loaded export supplies; the safe aggregate lists only the keys of those sections.

```text
+--------------------------------------------------------------------------------------------------+
| FIRBENCH-1 comparison explorer                                       explorer-home -> #top       |
| Historical results                                                                               |
| 5 source entries name 4 distinct files, by SHA-256 digest. Pipelines with a file: AuraFace (no   |
| result in this set), SFace (3 files), InsightFace (1 file). These are descriptive historical     |
| counts, read as recorded. The files are not 4 independent runs, and nothing on this page names   |
| a winner.                                                                                        |
|                                                                                                  |
| COMPATIBILITY UNKNOWN  These files do not record enough to check that they used the same         |
| detected population, thresholds, model weights, templates or gallery pins. Read the columns as   |
| separate historical results.  [What does compatibility mean?]                                    |
+--------------------------------------------------------------------------------------------------+
| Results by pipeline                          explorer-pipelines / explorer-runs -> #results      |
| How to read this: each value comes from one report file, listed under Source evidence. A missing |
| value is not zero.   * SFace has 3 files with different digests. Equal counts do not show that   |
| two files used the same images.                                                                  |
|                                                                                                  |
| Metric focus [All metrics   v]  Search glossary terms [for example: missed]                      |
| Grouping methods [All methods v]  [Clear search and focus] (disabled while all are defaults)     |
| Showing 16 of 16 metric rows, 7 of 7 grouping methods, and 44 of 44 glossary terms.  (status)    |
|                                                                                                  |
| Metric                    | AuraFace     | SFace                    | InsightFace                |
|                           | No result in | 3 file(s) for this       | Report file                |
|                           | the selected | pipeline. Report file    | [..fir-buffalo-2026.. v]   |
|                           | set          | [..baseline-2026.. v]    |                            |
| IMAGES AND DETECTIONS     |              |                          |                            |
| Images scored [?]         | No result    | 150  of 150 images       | 150  of 150 images         |
| Images that failed [?]    | No result    | 0                        | 0                          |
| Faces matched [?]         | No result    | 189                      | 373                        |
| Faces missed [?]          | No result    | 186  of 375 labelled     | 2  of 375 labelled         |
| Extra detections [?]      | No result    | 0                        | 2                          |
| Detection precision [?]   | No result    | 100.0% 189 ÷ (189 + 0)   | 99.5% 373 ÷ (373 + 2)      |
| Detection recall [?]      | No result    | 50.4% 189 ÷ (189 + 186)  | 99.5% 373 ÷ (373 + 2)      |
| NAMED AND STRANGER FACES  |              |                          |                            |
| Named faces matched [?]   | No result    | 100                      | 166                        |
| Stranger faces matched[?] | No result    | 89                       | 207                        |
| Strangers rejected [?]    | No result    | <export value or null>   | <export value or null>     |
| GROUPING (6 rows) [?]     | No result    | <export values or null>  | <export values or null>    |
|                                                                                                  |
| [?] = 'What does this mean?' link to #term-<known-id>.                                           |
+--------------------------------------------------------------------------------------------------+
| NO AURAFACE RESULT IN THE SELECTED SET (#auraface-intake): register a report file with           |
| 'evidence register', check it with 'evidence check', regenerate the export, render again.        |
+--------------------------------------------------------------------------------------------------+
```

Below the results, the same page continues in flow:

```text
+--------------------------------------------------------------------------------------------------+
| Grouping methods: availability                          explorer-grouping -> #methods-head       |
| These rows say what code exists in this tree. They are not measured scores, and the historical   |
| files do not name the method that produced them.    (7 rows; see section 11)                     |
+--------------------------------------------------------------------------------------------------+
| What this page does not evaluate                                     #notes-head (in flow)       |
| - H1 and H2 (second, only after H1 passes) are not evaluated here. [H1] [H2]                     |
| - Guardrails G1 to G5 are not evaluated; their rules are null in the committed manifest. [G...]  |
| - G4 timing is an allocated estimate per expected face, not a stopwatch. [G4]                    |
+--------------------------------------------------------------------------------------------------+
| > Source evidence and provenance       explorer-provenance -> #source-evidence (closed details)  |
+--------------------------------------------------------------------------------------------------+
| Glossary                                            explorer-terms -> #glossary, #term-<id>      |
| Acceptance threshold, AuraFace, Average-link clustering, ... (44 articles by label)              |
|   each article: label, definition, [Back to results] -> #results                                 |
+--------------------------------------------------------------------------------------------------+
```

## 6. Tablet and phone specimens

Same document, same content and same control order. The current CSS caps `main` at 72rem, wraps the control group, gives the table a 36rem minimum width inside an `overflow-x: auto` region, and keeps the row-header column sticky. These frames show that intent; only a real browser can show the fit.

```text
+----------------------------------------------------------------------+
| Results by pipeline              planning frame 768 x 1024 CSS px    |
| How to read this: each value comes from one report file ...          |
| Metric focus [All metrics v]   Search glossary terms [__________]    |
| Grouping methods [All methods v]   [Clear search and focus]          |
| Showing 16 of 16 metric rows, 7 of 7 grouping methods, and 44 of     |
| 44 glossary terms.                                                   |
+----------------------------------------------------------------------+
| Metric              | AuraFace     | SFace          | InsightFace >  |
|                     | No result in | 3 file(s) ...  | Report file >  |
|                     | the selected | Report file    | [buffalo v] >  |
|                     | set          | [baseline v]   |             >  |
| Images scored   [?] | No result    | 150 of 150     | 150 of 150  >  |
| Faces matched   [?] | No result    | 189            | 373         >  |
| Faces missed    [?] | No result    | 186 of 375     | 2 of 375    >  |
| Detection recall[?] | No result    | 50.4%          | 99.5%       >  |
| ...                 |              |                |             >  |
+----------------------------------------------------------------------+
| '>' = the table region may scroll sideways inside its own frame; the |
| page itself must not. The Metric column is sticky. Browser check     |
| decides the real fit; these characters certify nothing.              |
+----------------------------------------------------------------------+
```

```text
+--------------------------------------+
| Results by pipeline     390 x 844 px |
| Metric focus                         |
| [All metrics                     v]  |
| Search glossary terms                |
| [for example: missed              ]  |
| Grouping methods                     |
| [All methods                     v]  |
| [Clear search and focus]             |
| Showing 16 of 16 metric rows, 7 of 7 |
| grouping methods, and 44 of 44       |
| glossary terms.                      |
+--------------------------------------+
| Metric (sticky)   | AuraFace     |>> |
|                   | No result in |>> |
|                   | the selected |>> |
|                   | set          |>> |
| Images scored [?] | No result    |>> |
| Faces matched [?] | No result    |>> |
| Faces missed  [?] | No result    |>> |
| ...               |              |>> |
+--------------------------------------+
| SFace and InsightFace columns are    |
| reached by scrolling the table       |
| region sideways; the AuraFace No     |
| result column comes first in         |
| renderer order.                      |
+--------------------------------------+
```

On a narrow frame, the first data column is AuraFace “No result”, so the populated columns need sideways scrolling inside the table region. A table that needs two dimensions is an exempt case under A11Y-08, but the page itself must not scroll sideways. Whether this narrow layout is acceptable is for the browser check to decide; it is not claimed here.

## 7. Report file selection (`explorer-runs`)

| Object | Default | Activated | Updated result |
|---|---|---|---|
| “Report file” select (`id=variant-<pipeline>`) for each pipeline that has a report | The first actual report of that pipeline (`config.defaults`); options are that pipeline's artifact IDs in sorted order (`config.pipelines`) | Choose another artifact ID | That column's values swap. The query gains `variant-<pipeline>=<artifact ID>`. Choosing the first ID again drops the key |
| Pipeline with no report (AuraFace here) | Column header “No result in the selected set”, cells “No result”, no select | None | It cannot be selected into existence; `variant-auraface` is ignored |
| Artifact ID that shares a digest with another | Listed under Source evidence | None | It is never a separate option, because it is the same report file |

There is no clear or empty slot and no Reset selections command. Selections are artifact IDs, never digests. The status line counts metric rows, methods and terms. It does not name the selected report, so the visible result of a selection is the select's own value and the changed column. That is an observation for the browser and accessibility review, not a claimed announcement.

## 8. Focus, methods, search and clear

| Control | Default | Activated | Updated result and status message |
|---|---|---|---|
| Metric focus (`focus`) | All metrics | Images and detections, Named and stranger faces, or Grouping | The other row groups hide. Status: “Showing 7 of 16 metric rows, …” (3 for stranger faces, 6 for grouping). Report choices stay |
| Grouping methods (`methods`) | All methods | Code in this tree, or No code here or unknown | Availability rows filter: “… 4 of 7 grouping methods …” or “3 of 7”. Nothing executes |
| Search glossary terms (`q`) | Empty; 44 of 44 terms | Type | Glossary articles filter by literal, case-insensitive substring of label and aliases: “… Z of 44 glossary terms.” Metric and method rows do not change |
| Escape in the search box | None | Escape while `q` is not empty | `q` clears; focus, methods and report choices stay |
| Clear search and focus | Disabled while focus, methods and `q` are defaults | Activate | `focus`, `methods` and `q` return to defaults; report choices stay; keyboard focus moves to Metric focus |
| Glossary no match | None | `q` matches no term | Note: No glossary term matches “q”. Use Clear search and focus to show every term |

The status line is `role="status"` with `aria-live="polite"`. Term search filters the glossary only. Grouping controls filter availability rows only and never run Python.

## 9. View state lives in the query

- **Keys.** `variant-auraface`, `variant-sface` and `variant-insightface` carry artifact IDs, never digests. Choices come from `config.pipelines`; defaults come from `config.defaults`, the first actual per-pipeline report. `focus=all|detection|strangers|grouping`, `methods=all|in-tree|other`, and `q` is a literal glossary substring. Defaults are the report defaults, `all`, `all` and empty.
- **Parsing, on initial load and on reload.** An unsupported enum value or unknown artifact ID falls back to that field's default. Unknown parameters are ignored. A duplicated scalar key uses the first `URLSearchParams.get` value. No reset banner is shown and no input is echoed.
- **Serializing.** After each control update, `history.replaceState` writes the nondefault selections first, in `config` key order (alphabetical: auraface, insightface, sface), then `focus`, `methods` and the trimmed `q`, and keeps the current native hash. No 200-character cap is implemented.
- **Navigation.** Native fragment links (`#term-…`, `#results`) make browser history entries. Back and Forward are browser navigation, not an undo of every control change, because control updates replace the current entry.
- **Storage and network.** No localStorage, cookies or network. The page's content security policy sets `default-src 'none'`.

Example: `REVIEW_DIR/index.html?variant-sface=golden150-fir-final-20260723&focus=detection&q=missed#results`.

## 10. Null values and producer status (UX-REGATE-02)

This draft chooses the explicit v1 limitation instead of silently extending the wire. The exporter's `_live` turns a section flagged `refused: true` into nulls, an absent section is also null, and producer refused, directional, floor, status and sampling-frame keys are never copied. So a null value is **VALUE UNAVAILABLE, SOURCE STATUS NOT EXPORTED**. It does not establish not recorded, absent, refusal, zero or an eligible denominator. `slice_sections` names source sections that were present, including refused ones. It does not separate refused from present-but-null values, and the page does not display it.

Metadata absence can still be called *not recorded* for that exported field, such as a null `source_sha` or `manifest_sha256`.

```text
+----------------------------------------------------------------------+
| FROZEN a536ea56 MARKUP         | REQUIRED DISCLOSURE (pending)       |
| Strangers rejected  [?]        | Strangers rejected  [?]             |
|   not recorded                 |   value unavailable                 |
|                                |   source status not exported        |
| Glossary 'Not recorded': The   | Glossary: the export carries no     |
| file does not contain this     | value and no producer status, so    |
| value.                         | refused, absent, zero and eligible  |
|                                | denominators are not told apart.    |
+----------------------------------------------------------------------+
```

| Place | Frozen a536ea56 markup | Required honest wording | Status at baseline |
|---|---|---|---|
| Null metric cell (`_cell`) | “not recorded” | value unavailable, source status not exported | Product gap, pending in a separate code lane |
| Glossary term “Not recorded” | “The file does not contain this value.” | Define value unavailable; keep not recorded for exported metadata fields | Product gap, pending |
| Table caption | “"not recorded" means the file does not contain it.” | Same correction | Product gap, pending |

Historical witness (`6d921bf2/e51cc87b`, r3 cross-check): the synthetic InsightFace report lists `unknown_rejection` in `slice_sections`, but every one of its values is null, and that page prints “not recorded” under Strangers rejected. Supplied `a536ea56` still has the `_cell`, glossary and caption numeric-null wording above. Separately, its `_value` strangers-rejected branch already preserves a known `correct_rejects` count when `n` or rate is missing: the metrics-r3 receipt's public synthetic example is **7**, with “denominator not recorded; rate not recorded”. That sparse-count fix is implemented, targeted green, independent acceptance pending; its qualifier's numeric-null cause wording remains pending. No count, rate or eligible denominator is invented.

Removed from the map and this draft: status, sampling-frame and directional details for grouping, identification and unknown rejection. Identification headline/full numbers are exported but not displayed by the current page. Cohort and occlusion categories are not exported.

## 11. Grouping: recorded values and availability-only methods

Recorded grouping values are the Grouping rows in `#results` (`focus=grouping`): Merge rate (`false_merge` over `m_co_clustered` pairs), Split rate (`false_split` over `p_same` pairs), Cluster purity (definition pending), Grouped faces (`clustering.n_faces`), Clusters (`n_clusters`) and Clustering setting d_cut (`clustering.parameters.d_cut`, cosine distance). The cell detail reads “method not recorded” because the export carries `algorithm` and `metric` as null. Grouped faces is the grouping population, never Images scored.

```text
+------------------------------------------------------------------------------+
| Grouping methods: availability                        #methods-head          |
| Filter (in the #results controls): Grouping methods [Code in this tree v]    |
| Showing ... 4 of 7 grouping methods ...                         (status)     |
+------------------------------------------------------------------------------+
| Method              | Availability in this tree     | Historical numbers     |
| HDBSCAN             | production adapter; recorded  | None attributed. No    |
|                     | as metadata, not run here     | historical file has it |
| Average-link HAC    | current analysis reference    | None attributed        |
| Complete-link HAC   | current analysis reference    | None attributed        |
| Constrained HAC     | production code; median link  | None attributed        |
| (methods=other)     |                               |                        |
| Chinese Whispers    | archived; removed; not run    | None attributed        |
| DBSCAN              | not located in bounded        | None attributed        |
|                     | snapshot; recovery needed     |                        |
| d_cut in historical | method that used it is not    | Shown per file in the  |
|   files             | recorded                      | table, not per method  |
+------------------------------------------------------------------------------+
```

The rows describe availability, not scores. No row runs, loads embeddings or ranks methods. A later grouping runner needs its own reviewed contract: pinned embeddings, face order, preprocessing, metric, library version, parameters, seed and independent GT before any quality claim.

## 12. Glossary: in-flow section, search and return

`#glossary` is an in-flow section of 44 term articles (`#term-<known-id>`, sorted by label); it is not an overlay. Term links sit on metric rows, in the compatibility banner and in the not-evaluated note. The search box sits in the `#results` controls.

```text
+--------------------------------------+
| Search glossary terms  (in #results) |
| [zzz                              ]  |
| Showing 16 of 16 metric rows, 7 of 7 |
| grouping methods, and 0 of 44        |
| glossary terms.                      |
+--------------------------------------+
| Glossary                   #glossary |
| No glossary term matches "zzz". Use  |
| Clear search and focus to show every |
| term.                                |
|                                      |
| Escape in the search box: q only.    |
| Clear search and focus: q, focus and |
| methods; report choices kept.        |
+--------------------------------------+
```

**UX-RENDER05 (separate code lane) is required but not accepted.** Before revealing a search-hidden term, the page must keep the actual opener, query, scroll position and current controls. An explicit Return and native Back must restore the temporarily cleared `q`, the invoking control and the scroll position, while keeping report, focus and method selections. Later manual choices win; a stale snapshot is never replayed blindly. Direct entry without a caller uses the `#results` heading.

```text
+----------------------------------------------------------------------+
| #term-faces-missed                                                   |
| caller: Faces missed [?] with focus=detection and q=precision        |
+----------------------------------------------------------------------+
| FROZEN a536ea56 OBSERVATION        | REQUIRED UX-RENDER05 (pending)  |
| hashchange to a hidden term clears | retain opener, q, scroll and    |
| q; nothing is remembered           | controls before revealing it    |
| [Back to results] -> #results      | explicit Return: restore q,     |
|   q stays cleared, focus not on    |   invoking link focus, scroll   |
|   the invoking link                | native Back: same restoration   |
| browser Back: native fragment      | later manual choices win over   |
|   history only                     |   the stale snapshot            |
| direct entry: #results link        | direct entry: #results heading  |
+----------------------------------------------------------------------+
| Not accepted until a normal-VM browser regression and an independent |
| gate pass. No modal, focus trap, router or caller query field.       |
+----------------------------------------------------------------------+
```

Historical browser evidence: the frozen test `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_explorer_interactions.py` (SHA-256 `e7e571f8aa3a2da95f2640e68ad4ceb3e40b66d821d308b6c07ab7084b6b88b7`, unchanged) is skipped unless `FIR_EXPLORER_BROWSER=1`. `.task-state/firbench-1/reports/UX-render-state-adj-red.json` records a Chromium SIGTRAP at launch, not an observed assertion failure. The r3 author predicted “UX-RENDER05: explicit return must restore temporarily cleared glossary query” from `6d921bf2/e51cc87b`; this correction invents no measured failure or new TDD gate. Glossary-state acceptance remains pending at `4e34534e/a536ea56`; no browser PASS is claimed.

Vocabulary, aligned to the renderer's row labels (decision17142 keeps the explorer glossary independent of the report helper):

| Say | Meaning | Don't say |
|---|---|---|
| Images scored | Media items successfully scored (`counts.scored`) | Faces scored |
| Faces matched | Detected boxes matched to labelled faces | Images, or the grouping population |
| Faces missed | Labelled faces with no matched box | All identification errors, or FNIR |
| Extra detections | Boxes that match no labelled face | FPIR, or false names |
| Grouped faces | Faces in the grouping sample (`clustering.n_faces`) | 150 because 150 images were scored |
| Pipeline | Detector, alignment, embedder, gallery and scorer together | The embedding model alone |
| FNIR | Eligible mated searches not ending with the correct accepted identity; includes undetected mates end to end | Detection recall alone |
| FPIR | Eligible non-mated source units with at least one false identification | Per-box false positives, `1 − precision`, or stranger rejection |
| H1 | Superiority: SFace versus AuraFace end-to-end FNIR at the existing FPIR target | A historical detection comparison |
| H2 | Non-inferiority, AuraFace versus InsightFace, margin 0.05; reached only after H1 PASS/rejection | “After H1 has a recorded result” |
| Value unavailable, source status not exported | A null value in the v1 export | Not recorded, zero, refused or failed |
| Not recorded | An exported metadata field that is null | Any null metric |
| No result | No report for that pipeline in this export | Absent everywhere |
| Compatibility unknown | Lineage bindings needed to check comparability are missing | Same data because counts or hashes match |

Renderer wording gaps at `a536ea56`: the H2 term says it “runs only after H1 has a recorded result” (the protocol, `firbench_score.decide` AST 844–967, stops at the first non-rejection), and the code-reader list names `clustering.d_cut` where the wire key is `clustering.parameters.d_cut`. Both belong to the prospective UX-explorer-copy owner (§2), pending assignment. “Not recorded” is defined for nulls; that tuple belongs to the numeric-null-copy owner (P-01). The manifest `benchmarks/manifests/fir-bench-decision-v1.json` defines H1 as superiority on legs sface/auraface and H2 as non-inferiority on legs auraface/insightface with margin 0.05. Manifest policy is not ratification or active deployment policy, and absent active values remain unknown. Historical pages do not evaluate H1 or H2. Frozen failedv6 **0.063/0.5565** remains unchanged.

## 13. Source evidence

`#source-evidence` is a native `details` disclosure, closed by default, that opens and closes itself without script, dialog or focus trap. It never opens a raw private artifact or invokes a backend.

```text
+------------------------------------------------------------------------------+
| v Source evidence and provenance                 #source-evidence (open)     |
+------------------------------------------------------------------------------+
| Artifact ID (candidate)       | File SHA-256 | Kind        | Qualification   |
| golden150-fir-baseline-2026.. | c05fa6a7...  | report-json | <export>        |
| golden150-fir-buffalo-2026..  | 84ed7fb3...  | report-json | <export>        |
| golden150-fir-buffalo-base..  | 84ed7fb3...  | report-json | <export>        |
| golden150-fir-final-2026..    | af3c3baa...  | report-json | <export>        |
| golden150-fir-v2-2026..       | ff9dbaad...  | report-json | <export>        |
| Each row also has three separate columns: Source commit | Manifest hash |    |
| Manifest hash kind. Each uses that source's exported value, or not recorded  |
| for its null field. Digests above are abbreviated only in this specimen.     |
+------------------------------------------------------------------------------+
| > Source keys for code readers                     (nested native details)   |
+------------------------------------------------------------------------------+
```

The walk is page value → selected artifact ID → file SHA-256 → kind and qualification → source commit and manifest metadata where exported. A missing binding ends at “not recorded” for that entry and metadata field, not at an invented ancestor. Supplied `a536ea56` implements `_source_table` per-source pins and `_provenance_summary` conditional field counts, including a separate zero-source sentence. The metrics-r3 receipt records a public synthetic example with source commit 1 of 3, manifest hash 1 of 3 and hash kind 2 of 3; these are example-specific, not historical-report pin claims. Recorded pins are declared by the export, not verified by this page. UX-RENDER-03 is implemented with targeted green, independent acceptance pending. Fixed commit cells and blanket absence prose describe historical `6d921bf2/e51cc87b` only. A report SHA-256 binds report bytes only, not frame, gallery or pixel equality.

## 14. Content, frame and typography

Current values read from the renderer's CSS, which are the renderer's choices, not canon defaults and not browser measurements: body text 1rem with 1.5 line height in a system font stack; `main` capped at 72rem; paragraphs and list items capped at 68ch; tabular numerals in numeric cells; controls at least 2.5rem high; a 3px visible focus outline; light and dark colour sets. Size, measure and leading are set together, as TYPE-02 asks. LAY-24 is answered by the 72rem frame, the wrapping control group and the table region, but the real fit at actual frames is unmeasured.

Still pending, in a real browser: computed values at the planning frames 1440 × 900, 768 × 1024, 390 × 844 and at 320 px; 200% zoom; text and UI contrast ratios for both colour sets; a keyboard walk; and whether a screen reader announces the status line. No accessibility or WCAG conformance claim is made.

## 15. State coverage

| MapState | Panels | Concrete meaning |
|---|---|---|
| default | All seven | Export loaded; defaults applied |
| degraded | Home, report files, results, measures, grouping, source evidence | Compatibility unknown, partial provenance, AuraFace “No result”, null values unavailable |
| empty | Home, glossary | Export with no reports leaves every column “No result”; glossary search with no match |
| edge_input | Report files, results, measures, grouping, glossary | Unsupported query values fall back to defaults; `q` is matched literally |
| error | Home | `explore` or `comparison-export` refusal: exit 2, fixed text, nothing published |

There is no `loading`, `offline` or `first_time` state: nothing is asynchronous and the page is offline by construction. The static exit marker keeps its exemption. No state is added to satisfy a critique proxy.

## 16. Removed promises

These earlier map, draft and plan-era items are not current v1 route requirements. Future work would need its own reviewed contract.

| Earlier promise | Current v1 |
|---|---|
| `#view=explorer-*` routes; `v` and `view` fields; plan-era `view=compare\|grouping\|inventory\|glossary`, `return_view` | Panel aliases to native anchors; no router or view enum |
| `runs`, `scope`, `pipeline`, `status`, `sort` fragment facets; plan-era full-SHA per-pipeline keys, `method`, `metric` | Query keys are `variant-<pipeline>` (artifact IDs), `focus`, `methods`, `q` |
| Pick runs with scope and status filters, Clear filters, Change scope, Sort, View selected runs | Column selects update values immediately |
| Reset selection or Reset selections; empty slots | None; choosing the first artifact ID restores a default |
| Terms overlay dialog with focus trap, inert background, Terms buttons on every panel, caller-specific Close actions | In-flow `#glossary` and native term links; caller-aware return is pending UX-RENDER05 |
| `term` and `caller` fragment fields, “View settings invalid” banner, 200-character cap, duplicate-key rejection | None; silent fallback and first-value rules |
| Status and sampling-frame details for grouping, identification and unknown rejection | Not exported; a null is value unavailable, source status not exported |
| `data.json` beside `index.html` | Not published |

## 17. Canon disposition

Canon **v0.26.2** (2026-10-14), full read-only mirror `/home/gate/firbench-1-context/canon-full-0.26.2`, is the citation authority; https://github.com/darce/heuristics-canon is a reference link only. Rule text was read from the mirror. Canon adds no approval workflow here.

| Rule and exact source | Application |
|---|---|
| [GRPH-01] Model the work as a DAG, then topological-sort — *The Algorithm Design Manual*, ch. 7 | Common frozen contract → parallel plan, map/ASCII and disjoint code scopes; presentation-result → null-copy; final conformance and composed producer/CLI/browser gates are joins (§2). No doc-first code prerequisite. Runtime data chain: `comparison-export` → `EXPORT.json` → `explore` → `index.html`; no product execution in this correction |
| [GRPH-06] Partition by connected components first — *Graph Theory with Applications*, ch. 1 | Partition by actual file, symbol and shared-branch scopes (§2), not a whole-renderer grant. Exporter and explorer share the typed export; CLI blocks are disjoint. The descriptive explorer has no H2/GT/new-MC dependency; scientific/private holds remain |
| [GRPH-09] Colour the conflict graph — *Graph Theory with Applications*, ch. 8 | The presentation/null-copy shared branch is a conflict edge; caller-state and explorer-copy literals are disjoint. Validator/publication distinct symbols need no whole-file serial edge. Coordinator alone composes exact disjoint hunks and checks outside-grant AST/source; unresolved merges go remote (§2) |
| [GRPH-14] Record provenance as a walkable lineage graph — *Building Knowledge Graphs*, ch. 8 + *Mental Models*, ch. 8 | §3, §13: value → artifact ID → file SHA-256 → metadata; absent metadata ends as not recorded; the receipt records input and output hashes |
| [REF-09] Mutable/derived-data drift — *Refactoring: Improving the Design of Existing Code* (2nd ed), ch. 9 | Requirements and exact pinned observations replace a moving CURRENT-gap mirror. Source implementation and independent acceptance are separate; live finding/acceptance state stays MCP |
| [INT-16] Resume from preserved state — *The Design of Everyday Things*, ch. 5 | Query state survives reload; caller restoration is pending UX-RENDER05 |
| [INT-21] Specify interaction states — *Microinteractions*, ch. 3 | §7 and §8 default, activated and updated states |
| [INT-22] Explain the result — *Microinteractions*, ch. 4 | Status-line counts and the no-match note; the selection observation in §7 |
| [TEST-06] Watch it fail once / predict the failure — *Modern Software Engineering*, ch. 8 | Historical prediction is attributed in §12; this planning correction adds no tests, product execution or TDD gate. Product/browser acceptance remains with its existing owners |
| [NAV-13] Controlled vocabulary before label freeze — *How to Make Sense of Any Mess*, ch. 4 | §12 say and don't-say list, aligned to renderer labels; reader validation is still pending |
| [WRIT-71] Unpack private knowledge — *The Sense of Style*, ch. 3 | Images versus faces, grouping population and the null limitation are explained where used |
| [VIZ-23] Show the evidence path — *Richard Feynman's Mental Models*, ch. 5 + *Envisioning Information*, ch. 4 | Denominators under each rate, Source evidence, and the interacting pipeline factors |
| [VIZ-32] Use a table for small exact-value tasks — *The Visual Display of Quantitative Information*, ch. 9 | Already served by the metric table; no chart is required |
| [LAY-24] Content-and-frame grid — *Thinking with Type*, ch. 3 | §14 frame, wrapping controls and table region; measurement is pending |
| [TYPE-02] Readability stool — *Web Typography (Richard Rutter)*, § designing-paragraphs-line-length | §14 size, measure and leading set together; computed values are pending |
| [A11Y-08] Reflow and resize — *WCAG 2.2*, SC 1.4.4 | The page must not scroll sideways at 320 px or 200%; the table region is the two-dimensional exemption; unmeasured |
| [A11Y-11] Keyboard walk — *WCAG 2.2*, SC 2.1.1 | There is no dialog, so there is no trap by construction; the keyboard walk itself is pending |
| [A11Y-12] Native first, ARIA last — *WCAG 2.2*, SC 4.1.2 + *The WebAIM Million*, 2026 | Native select, search input, button, details and anchors |
| [A11Y-21] Announce status — *WCAG 2.2*, SC 4.1.3 | `role="status"` count line; announcement is unverified |
| [A11Y-22] Scoped conformance claims — *WCAG 2.2*, § conformance | No conformance claim is made |
| [A11Y-24] Every state accessible — *WCAG 2.2*, § conformance | §15 states are listed for the future check |
| [RLSE-04] Undesigned state is a bug — bootstrap (practice label) | Explorer states are enumerated; the static exit marker stays exempt |

Principles 1 (author the contract before the components), 2 (specify what would prove you wrong), 9 (a claim must walk back to what produced it), 10 (perceived boundaries must match enforced boundaries) and 11 (unknown is a designed state) support one frozen contract, no fake controls, and honest unavailable values. Cards read: `contract-before-components`, `designed-unknown`, `falsification-disconfirmers`, `perceived-enforced-boundaries` and `proxy-outcome-integrity` (no static-exit state is invented to satisfy a critique proxy). No card authorizes new inference, a winner or protocol changes.

## 18. Validation and handoff

Exact source/doc hashes, preservation checks, reference exception, scope proof and unresolved acceptance obligations for this correction are in `.task-state/firbench-1/reports/UX-map-state-r5-validation.json`. The r3 receipt retains its historical executions. Bounded actual supplied-source reads are the fallback because the code map excludes scripts/docs/benchmarks; no complete graph is claimed. This correction runs document/schema validation only, not product or browser tests.

Local WorkBay canvas CLI availability is recorded in the r5 receipt; no local render or critique PASS is claimed. Coordinator handoff on the **exact final map hash in that receipt**:

```text
workbay-canvas-mcp ux-map render --path benchmarks/ux-maps/fir-bench.uxmap.json --format markdown
workbay-canvas-mcp ux-map critique --path benchmarks/ux-maps/fir-bench.uxmap.json --json
```

Unresolved acceptance belongs to separate owners and MCP: numeric-null cause disclosure, glossary caller-state, independent acceptance of implemented per-source pins/sparse counts/generic AuraFace copy, explorer H2/source-key copy (prospective UX-explorer-copy, pending coordinator assignment; its dedicated test is absent), real-browser usability/accessibility, and the composed actual producer/CLI/browser joins. The metrics-r3 targeted receipt is not a whole-task pass; the reader component's exact reviewed bytes at `cc216ca7` (17190) are not a whole-task PASS either. No completed presentation work or new tests are requested here. Frozen failedv6 **0.063/0.5565**, the numerics, commands, scientific/private/main-merge holds and master-plan/model governance remain unchanged.
