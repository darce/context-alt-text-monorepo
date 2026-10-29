# Weekly EVALOPS measurements

Owner: EVALOPS coordinator; implementation task `EVALOPS-1-RUNNER`, umbrella
`EVALOPS-1`. This stdlib runner joins the three existing scorer APIs. It reads
exports or an explicitly selected read-only SQLite source and creates one new
JSON report per invocation. It makes no model, provider, MCP or network calls.
No scheduler is installed.

```sh
make evalops
```

The default uses tracked `benchmarks/experiments/evalops/` evidence: 100 blind
findings, qrels, **100 coded error samples, not all 441 historical errors**, and
lesson exports. The default successfully reports `needs_labels`, unavailable
retrieval results, unknown protocol/QC, and unknown replay coverage. Missing
human work is not a tooling release blocker. Resolution status, notes and
machine prelabels are never human truth. Seed inputs are never edited.

Successful reports are printed as JSON and saved under
`.task-state/evalops/reports/evalops-<UTC>-<unique-id>.json`. Run history is the
collection of these separate files; no central ledger or database is needed.
Use `--output-dir DIR` or `--output NEW.json`. An explicit output overrides the
directory option. Existing artifacts, symlinks (including parent directory
symlinks), inputs and SQLite sidecars cannot be replaced. Temporary publication
files are private; only those temporary files are cleaned up. Preserve reports,
capture records, original labels and pre-adjudication QC events.

## Run after seven days of observed replay

The following is an exact example for a replay actually captured continuously
from `2026-10-30T00:00:00Z` through `2026-11-06T00:00:00Z`. Run it **after** that
capture, with those exports and its capture ledger in `/tmp/evalops-week-1/`.
Change the dates and paths together for the actual week's evidence. This is a
procedure, not a claim that this future replay has happened.

First create `coverage.json` from the capture ledger, independently of the error
timestamps. This example is valid only if there were no capture gaps:

```sh
python3 - <<'PY'
import hashlib
import json
from pathlib import Path

week = Path('/tmp/evalops-week-1')
coverage = {
    'since': '2026-10-30T00:00:00Z',
    'until': '2026-11-06T00:00:00Z',
    'complete': True,
    'gaps': [],
    'source': 'capture-ledger-week-1.json: independently checked continuous capture',
    'errors_sha256': hashlib.sha256((week / 'errors.jsonl').read_bytes()).hexdigest(),
}
with (week / 'coverage.json').open('x', encoding='utf-8') as stream:
    json.dump(coverage, stream, indent=2)
PY

make evalops EVALOPS_ARGS='--findings /tmp/evalops-week-1/findings-human.jsonl --qrels /tmp/evalops-week-1/qrels.jsonl --errors /tmp/evalops-week-1/errors.jsonl --lessons /tmp/evalops-week-1/lessons.jsonl --predictions /tmp/evalops-week-1/predictions.json --qc /tmp/evalops-week-1/qc.json --results /tmp/evalops-week-1/results.jsonl --coverage /tmp/evalops-week-1/coverage.json --since 2026-10-30T00:00:00Z --until 2026-11-06T00:00:00Z --k 5 --k 10 --pool-depth 20 --pool-contributor lexical --pool-contributor semantic'
```

Only supply pool metadata that actually describes the pool used. Optional files
can be omitted. An omitted `--results` means unavailable; an explicitly supplied
empty results file means an observed empty retrieval run and scores accordingly.
All supplied files must exist and validate, even when other evidence is missing.
An explicit external errors export without lessons does not establish lesson
capture; pass `--lessons` to include its corresponding export.

Top-level `replay` is the weekly interpretation authority. It discloses the
exact requested duration, covered duration, timestamp support, error-event span,
and capture evidence. Maturity requires at least 604800 observed seconds after
the scorer's fixed intervention boundary, no gaps, complete capture attestation
bound to the error input hash, and no unknown/naive error dates. Seed coverage
is always unknown. A default seven-day request, old filename, or two distant
events cannot establish continuous observation. A complete zero-error capture
can be mature; zero events without capture evidence cannot. Coverage attestation
is supplied by the operator and is not independently audited by this tool.

The nested recurrence scorer also reports a timestamp-span maturity diagnostic;
it does **not** establish capture completeness. Its baseline is the rounded
historical n=441 class proportions, with exact counts unavailable. Rates divide
by observed error rows, not dispatch exposure; classifications can overlap.
Pre/post and baseline differences are descriptive, not proof of improvement.
Retain the scorer's unknowns, denominators, limitations and follow-up owners.

## Explicit input contracts

All JSON is strict UTF-8: duplicate keys, non-finite constants, truncated JSON,
wrong shapes, unsupported fields, unreadable files and limit overflow fail
loudly. Blank JSONL lines are ignored. Limits are per input: at most 100000 rows
and 64 MiB; `--max-rows` and `--max-bytes` can lower them. Predictions and QC
arrays have the same row bound. At most 16 cutoffs in 1..10000 are accepted.
Regular files only; FIFO/device inputs cannot hold the runner open.

The real scorer sources are the schema authorities:

* [score_judge.py](../../benchmarks/tools/evalops/score_judge.py): findings JSONL
  preserves the full stratified sample/design and sets `human_label` only from
  independent blinded decisions (`defect`, `not_defect`, `unclear`, or null).
  `--predictions` is a JSON object with a `predictions` array of `{id, label}`
  and optional `protocol`. The latter pins `model`, `prompt`, `rubric`,
  `decoding`, `seed`, and `order_handling`; omitted fields stay unknown.
  Without predictions the scorer discloses raised findings assumed positive,
  measuring finding precision, not invented model/human predictions.
* `--qc` is `{ "decisions": [...] }`. Events require `decision_id`, `item_id`,
  `annotator`, `field`, `label`; optional `gold_label` is an independent known
  answer and `repeat_of` references an earlier original for that same identity,
  annotator and field. A repeat cannot also count as gold.
* [score_retrieval.py](../../benchmarks/tools/evalops/score_retrieval.py): qrels
  JSONL requires `query_id`, `query`, `doc_id`, with `relevance` integer 0..2 or
  null/absent, and optional seed provenance fields. Results JSONL has exactly
  `{ "query_id": "...", "doc_ids": ["ranked-id", "..."] }`. Null/unpooled
  relevance stays UNKNOWN. Recall/nDCG are conditional pooled estimates, not
  exhaustive collection recall. Pool depth/contributors default to unknown.
  Without results, qrels/pool are validated via the API, but all computed
  empty-run metrics are discarded; only qrel support and pool metadata remain.
* [error_recurrence.py](../../benchmarks/tools/evalops/error_recurrence.py):
  errors JSONL requires an `error_class` or `open_codes` field. The former is
  text, a text array, or null; the latter is a text array or null. Empty/missing
  classification remains unknown. `created_at` may be missing/null, or an ISO
  string; naive export dates are disclosed as assumed UTC and prevent maturity.
  Malformed date strings/types fail. The runner accepts the seed's metadata
  fields and the helper's projected identity/classification/time fields.
  Lessons JSONL accepts identity/time, `decision`, `rationale`, `memory`, `text`,
  `content`, explicit `error_class`/`open_codes`, and `recur`/`recurred` flags.
  Marker recurrence is declared evidence, not an inferred causal relationship.
* `--coverage` is exactly `{since, until, complete, gaps, source,
  errors_sha256}`. Bounds require timezones and increasing order. `complete`
  is a boolean, `source` names actual capture evidence, and `errors_sha256`
  binds that claim to the input. Gaps are `{since, until, reason}` objects
  contained in the coverage interval. Any gap withholds maturity. Omit this
  file when coverage is unknown; never manufacture it from event span.

To use a DB instead of an errors export:

```sh
make evalops EVALOPS_ARGS='--db file:/absolute/stable/handoff.db?mode=ro --since 2026-10-30T00:00:00Z --until 2026-11-06T00:00:00Z'
```

`--db` and `--errors` are mutually exclusive. The existing public helper opens
SQLite with `mode=ro`, `query_only=ON`, a one-second lock timeout and bounded
projection from `agent_errors` or `errors`. No DB is created or written. SQLite
is imported only on this path; import/schema/read errors exit nonzero. Use a
stable read-only snapshot or JSONL export: the runner hashes the main file and
existing WAL/SHM/journal before and after and rejects changes. DB provenance
also hashes canonical projected rows (compact sorted-key JSON array), which is
the `errors_sha256` for DB coverage. The helper has no public lessons exporter;
the runner does not scan memory/decision tables. Supply an explicit lessons
export, otherwise lessons are unavailable in DB mode.

## Blind labels, independent predictions and QC

The coordinator arranges independent blinded labeling on a copy of the findings
seed. Keep machine predictions, resolutions, commentary and tuning information
hidden during that work. Preserve original per-annotator events before
adjudication; collect independently known gold and repeat identities rather
than inferring them from agreement with a model. Freeze protocol and evaluation
items before inspecting errors; use separate development material for tuning.
Single-operator answers without independent gold/QC do not establish validity.

FIRBENCH decision16734 requires 10% gold and 10% repeats, at least 20 gold
decisions per annotator, at least 20 repeats per annotator/field, independent
gold accuracy >=.90 and repeat agreement >=.90. Small support stays
`insufficient_support`. Cohen kappa near .80 is diagnostic only. Supplied QC
only covers its supplied identities/fields and does not certify finding labels.
No quality floor is accepted here, even with complete labels or passing QC.
`statistical_acceptance.status` remains `not_evaluated`; a later acceptance
decision needs actual independent evidence and a predeclared protocol.

## Reproduce, verify and roll back

Each report records UTC bounds and observation time, immutable HEAD commit/tree,
executed source byte hashes and whether those bytes match that tree, input byte
hashes, support, provenance, and all three nested scorer payloads/availability.
Run from a committed clean tree for immutable execution evidence. A dirty tree
is disclosed; its HEAD tree alone does not identify the edited executed bytes.
Reuse the same evidence, tree, bounds and `--now` for identical JSON (unique
artifact filenames are deliberately outside the payload).

Both invocation forms work outside the repository; module form needs its root
on `PYTHONPATH`:

```sh
python3 /absolute/repo/benchmarks/tools/evalops/run.py --output-dir /tmp/evalops-reports
PYTHONPATH=/absolute/repo python3 -m benchmarks.tools.evalops.run --output-dir /tmp/evalops-reports
LC_ALL=C uv run --no-project --with pytest python -m pytest benchmarks/tests/test_evalops_runner.py -q -p no:cacheprovider
```

Exit 0 means execution succeeded, including `needs_labels` and unavailable
optional evidence. Exit 2 means a supplied-input, import, provenance or output
failure; inspect structured stderr. Argparse usage failures also exit 2.
Unexpected implementation defects propagate with traceback. No report is
published on validation failure; output publication never replaces history.

Rollback is **git revert of the runner change**. Retain all observations,
reports, input exports, blind labels and capture ledgers. No handoff retention
deletion, seed reset, deployment or scheduler changes are part of this task.
The coordinator owns integration/review/lifecycle and records lane evidence to
MCP; this isolated source does not require an MCP connection.

## Decision basis

Verified pinned Canon **v0.26.2**, matched rows and source locators:

* [TEAM-42] **Make repeatable guidance executable** (*The DevOps Handbook*,
  ch. 20): the make target, tested runner and this workflow are the owned tool.
* [GRPH-32] **An edge exists only where data moves** and [GRPH-33] **A node
  without a contract cannot be parallelised** (practice labels): call actual
  scorer APIs with explicit inputs; do not synthesize API shapes or labels.
* [EVAL-04] **Slice-based gate** (*Designing Machine Learning Systems*): retain
  strata and support; the aggregate cannot hide incomplete slices.
* [EVAL-12] **Validate the judge against humans** and [EVAL-13] **Pin the judging
  protocol** (*AI Engineering*): withhold acceptance and disclose unknowns.
* [EVAL-24] **Retrieval needs a test collection** and [EVAL-25] **Pool judgments;
  disclose incompleteness** (*Introduction to Information Retrieval*, ch. 8):
  preserve conditional estimates, missing rankings and unknown pool metadata.
* [MEAS-23] **Make toil visible before automating it** (*Mastering Site
  Reliability Engineering in Enterprise*, ch. 6) and [DIAG-10] **Close the
  learning loop** (*High Performance SRE*, ch. 9): preserve sample/baseline
  disclosure and recurrence follow-ups, then check observed replay.
* [OPS-75] **Improve the measured constraint** (*The DevOps Handbook*, ch. 2):
  prior operational decisions20545/17577 locate the delivery constraint in
  review-pass-to-MERGE evidence. Faster implementation alone is no improvement
  claim. This runner's bounded smoke check is not authoritative merge review.
* [AGT-10] **Degrade loudly** (*The Art of UNIX Programming*, ch. 1): invalid
  evidence fails visibly; missing optional work is an explicit data status.

Anchor correction: [MEAS-23] is about classifying toil before automation, not a
generic comparative-baseline rule; historical comparisons are disclosed through
the recurrence scorer's actual contract. The evidence-before-commitment,
reversible-commitments and durable-decision-memory cards support evidence before
completion, revert preserving observations, and a concrete coordinator handoff.
