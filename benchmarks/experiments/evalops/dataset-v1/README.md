# Real-case candidates v1

**Independent gold: `needs_labels`. Sealed train/dev/test assignments: withheld.**
This release contains 240 quarantined **aggregated operational error record
references**, representing 400 stored occurrences. It contains zero admitted
replay cases and zero independent healthy controls. The number of independent
episodes is unknown. These are handoff.db agent records, not end-user production
traces. Successful import or validation establishes candidate custody only.

The proposed initial collection is **200 independent cases: 120 representative,
40 rare-critical and 40 healthy controls**, followed by **60/20/20 grouped
train/dev/test allocation**. These are acquisition targets, not obtained data or
population prevalence. The latest-error frame cannot supply representative
population sampling or successful controls; inclusion probabilities and weights
remain null. `artifacts/coverage.json` exposes desired versus actual strata,
track counts, deficits, missingness and withheld assignments.

## Reproduce on the authorized VM

From the repository root, using Python with `jsonschema` and `pytest` available:

```sh
python3 benchmarks/experiments/evalops/dataset-v1/import_candidates.py --input-dir /home/gate/workbay-sandbox/evalops3-inputs-20261029 --check
python3 -m pytest -q --noconftest -p no:cacheprovider benchmarks/tests/test_evalops_seed_files.py benchmarks/experiments/evalops/dataset-v1/test_candidates.py
```

Omit `--check` to regenerate only this directory's `artifacts/`. No clocks,
randomness, network/model calls or parallel workers enter the importer. It has no
admit/split option. Checks require the retained private input directory; those
restricted source files are not committed. Tests use that VM path by default;
`EVALOPS_DATASET_INPUT_DIR` may point to a byte-identical retained snapshot.
Unknown or changed hashes, duplicate IDs, changed row membership, altered source
projections, malformed schema or modified generated artifacts fail closed.
A changed pinned repository input, such as a re-pinned retrieval manifest,
requires a lock update and producer regeneration; the tests rebuild the
committed artifacts from the default repository inputs and name the stale pin.
Diagnostic failures omit source content. No expert answers, real journals,
review-run contents or live databases are opened.

| Artifact | Contract |
| --- | --- |
| `schema.json` | Draft 2020-12 typed candidate schema; every field required, explicit nulls; quarantine only and `sealed_split=null`. It does not admit independent gold. |
| `protocol.json` | Proposed expert admission, three separate tracks, QC, evidence-backed grouping, future deterministic group allocation and sealed-test custody. No runtime split/admission implementation. |
| `input-lock.json` | Exact frozen input manifest/error snapshot/status hashes and query/time; analysis, current annotation source and other source-contract hashes; Canon release pins. |
| `import_candidates.py` | Exact source-ID/hash join to analysis-v1; preserves open codes and separately projects axial codes. No failure-to-case promotion. |
| `artifacts/candidates.jsonl` | Stable `agent_errors:<original-id>` reference per actual source record, ordered by source ID. All quarantined; expected behavior and independent labels remain null. |
| `artifacts/coverage.json` | Actual record/occurrence counts, unknown episode count, zero admissions, missingness and collection deficits. |
| `artifacts/manifest.json` | Exact schema/protocol/lock/producer/test/readme and output file hashes/lengths, without a self-hash cycle. |

File digests hash original bytes. Canonical row hashing uses UTF-8 JSON with
`ensure_ascii=False`, sorted keys, compact comma/colon separators, finite numbers
and no newline. `content_sha256` hashes the candidate after removing only that
field. Every candidate pins the exact protocol and input-lock bytes; the manifest
pins all other artifacts. The restricted source summary hash follows analysis-v1
(null summary encodes as empty bytes); it is **not** a replay input/content hash.
Raw summaries remain exclusively at their retained restricted refs.

## Source semantics and current holds

Actual `analysis-v1/open-coded.jsonl` rows retain `source_id`, original summary
ref/hash, canonical full-source-row hash, naive source timestamps and occurrence
counts. The importer verifies these against `agent-errors.json` and the frozen
manifest; its provenance is walkable without republishing source text. Native
`task_ref` is copied when present (153 records); 87 records lack it. An observed
task reference is not substantiated canonical task/root-cause/repeat linkage.
Naive timestamps stay verbatim with timezone null; they are not normalized UTC
or episode start/end times.

`analysis_record_group_id` preserves the original analysis record placeholder;
it is never a leakage-control group. Every actual incident link remains unknown.
Rule-assisted original free-text open codes are copied unchanged and kept apart
from the axial mapping; neither is a causal diagnosis or gold. The snapshot has
197 pattern-supported and 43 uncertain codings. Neither record identity,
matching text, nor an axial category proves independent incidents.

Replay input, expected output/rubric, intent, difficulty, segment, track,
criticality, canonical grouping, source context, exposure/attestation and
prompt/model/config/decoding/seed/order/environment/task-version pins are explicit
typed fields. Unsupported values stay null or `unknown`. There is no surrogate
replay made from an error summary. Empty linkage-evidence arrays mean no evidence
was supplied, not that no links exist. `input-lock.json` pins source contracts as
read; it does not assert their readiness or the accuracy of their historical
source ranges.

The current `label_ui.State._payload` separates validity (`label`) from
`disposition=blocks/nonblocking/unknown`, `affected_action` and `blocking_reason`.
Blocking requires defect validity plus action and reason; valid findings can be
nonblocking. Annotation provenance keeps the source enums
`blind_human/user_assisted/post_review/independent_expert/unknown`, exposure,
attestation/original refs and protocol version. Native events retain
`annotation_schema`, `original_event_id` and append-only `supersedes` history.
The candidate annotation wrapper records unavailable fields explicitly; it is
not a fabricated native event. Any later authorized projection must preserve the
existing journal authority and original event history. The existing partly
post-review/user-adjudicated 58/57/5 answers cannot become independent gold by
changing a provenance label.

The retrieval source contract has actual exposed seed/dev needs and a single
observed strategy with incomplete judgments, not untouched independent test
needs. Its independent relevance remains unavailable. The trajectory contract
proposes additional pins, not complete native trajectories. The evidence reuse
contract requires exact source/environment/command/input identity, not a generic
passing receipt. This release changes none of those source slices.

## Manual admission and grouping before split

The actionable sequence and required evidence are versioned in `protocol.json`.
A dataset steward first obtains authorized replay context, a suitable sampling
frame including successes, source/task/repeat evidence, and expert exposure
attestations. Independent experts supply expected outputs or rubrics and labels
using the existing authorized append-only annotation workflow, before seeing
assisted/model answers. Unresolved or exposed labels remain quarantined. No real
journal is imported or rewritten here. Admission decisions must carry reviewer,
time, reason, exact evidence/protocol hashes and original/superseded references
in a new dataset release; editing generated JSONL is not admission.

Before allocation, substantiate task aliases, root incidents, repeats/retries,
shared source content and cross-track reuse. Form transitive connected components
across all tracks from evidence-backed relationships. Record unresolved links and
hold potentially connected members; check exact and likely semantic duplicates.
Affirmative `not_applicable` evidence may establish that a healthy control has no
root incident; null alone cannot. Missing grouping, exposure, independent labels
or replay context withholds sealed assignments. This release therefore has no
split IDs, invented group IDs or balanced accepted dataset.

The proposed future algorithm hashes each frozen group with a pinned seed and
protocol version into 60/20/20 buckets. Entire groups inherit one assignment
across tracks; the algorithm is specified exactly in the protocol and is not run
here. Exact case ratios are not guaranteed for unequal group sizes. Report case
and group counts, achieved strata and insufficient heldout denominators. Never
reroll assignments, exclude difficult cases, or tune on reported test needs.
The independent steward controls test custody and exposure records. New evidence
of linkage or test contamination invalidates affected claims and requires a new
version, not a silent move between splits. This can constrain known leakage; it
cannot prove unknown links absent.

Review-policy, retrieval and description-generation use separate inputs, expected
rubrics, denominators and reports. Retrieval requires corpus/realistic needs/
independent relevance and a disclosed multi-strategy pool; unjudged is unknown.
Generation support/faithfulness is a separate track and includes abstention and
missing/stale/contradictory context. No description cases are supplied.

Per-field QC proposes at least 20 gold decisions and 20 repeat decisions, gold
and repeat shares each at least 10%, and separate 0.90 correctness/consistency
floors. Repeat presentations do not enlarge independent case counts. Independent
reference gold and QC execution are unavailable. Agreement around 0.80 is a
diagnostic, never label truth or a sufficient admission criterion. No judge
calibration, production rate, native runtime acceptance or quality gate is claimed.

## Authority and evidence

This is the authorized VM source1 slice using external `codex-remote` transport
precedent bootstrap20551, with no native dispatch success claim, extra model or
reviewer dispatch, paid review or merge. User-provided original slice identities
are rubric `f5997481`, analysis `6a89d9ad`, trajectory `6e20b870`, retrieval
`cc728cf3` and evidence `4169927b`. They identify the unmerged foundation train;
synthetic snapshot ancestry is not original ancestry. Original UI19998/source2/
action171 and capture19999/source4 routes, counters and custody remain with their
existing owners.

Canon **v0.26.2** was read from the supplied read-only VM copy and all **53**
release-manifest digests were verified. The lock pins that manifest and relevant
files. The evidence-before-commitment, measurement-integrity and durable-decision-
memory cards motivate withholding admission until evidence exists, freezing the
sampling frame separately from the optimizer, and retaining this rationale.
The correction-at-source card keeps this projection derived from one authority.

- [EVAL-12] **Validate the judge against humans** and [EVAL-13] **Pin the judging protocol** — *AI Engineering*: independent validation and immutable protocol pins precede any judging gate.
- [HITL-05] **Agreement is a diagnostic, not the truth** — *Human-in-the-Loop ML*: QC/agreement cannot substitute for authorized reference decisions.
- [EVAL-24] **Retrieval needs a test collection** and [EVAL-25] **Pool judgments; disclose incompleteness** — *Introduction to Information Retrieval*, ch. 8: expose missing corpus/pool/judgment evidence and keep unknown relevance.
- [GRPH-14] **Record provenance as a walkable lineage graph** — *Building Knowledge Graphs*, ch. 8 + *Mental Models*, ch. 8: IDs, original refs and exact hashes lead back to actual input rows.
- [DATA-14] **No dual writes** — *Designing Data-Intensive Applications*, ch. 11: the existing annotation journal remains authoritative; candidates are reproducible projections, not a second mutable label store.
