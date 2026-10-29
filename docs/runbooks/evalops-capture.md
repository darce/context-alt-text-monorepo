# EVALOPS observation capture

This is **observation tooling**, not accepted QC, continuous event capture, native
accounting success, or a mature replay. Sources 1-2 / `EVALOPS-2-CAPTURE` own only
`capture.py`, its focused tests, and this runbook. No production capture was
started by this implementation. The coordinator must pass the real independent
pipeline gate and check host load/source compatibility before starting runtime.
Human 100-label adjudication, gold and QC are unavailable; do not read
`findings-v0-prelabels.jsonl` or infer acceptance from a successful CLI exit.

## Inputs and source boundary

The closed source inputs are the completed
`/home/gate/workbay-sandbox/evalops-next-replay-inventory-20261029/result.json`,
the native DDL/count inventory
`/home/gate/workbay-sandbox/evalops-next-assets-20261029/db-schema.json`, and the
partial committed upstream snapshot's `agent_errors.py`, `decisions.py` and
`import_export.py` under `src-upstream/packages/mcp-workbay-handoff/src/workbay_handoff_mcp/`.
Their SHA256 digests, base `b4f52e7b822551c05cb3bb90bbcb7b48dfa5db20`, and tree
`481773a3a4682d501a30462c7b85a4b37baaec46` are embedded in each run's provenance.
These identify the supplied contract evidence, not live producer ancestry.

Only the actual source DB supplied with `--db` is queried. The adapter requires
native `agent_errors` and `decisions` tables with integer primary-key `id` and
these declared column types:

| Table | Required columns |
| --- | --- |
| `agent_errors` | `id INTEGER`, `task_ref TEXT`, `error_class TEXT`, `created_at TEXT`, `occurrence_count INTEGER`, `last_seen_at TEXT` |
| `decisions` | `id INTEGER`, `task_ref TEXT`, `decision TEXT`, `rationale TEXT`, `created_at TEXT` |

It snapshots every column of these two tables, checks their actual DDL and column
metadata, and pins that schema hash from the first successful observation.
Additive or incompatible changes stop the run. Other tables are not scanned.

**Journal compatibility (source 2 correction, decision 20657).** The native
producer DB is in WAL mode (header journal version bytes 18/19 = `2,2`), even when
no sidecar exists. Source 1 refused WAL and any `-wal`/`-shm`, so the requested
capture could not start; that contract was overstrict and is replaced. Rollback
(`1,1`) and WAL (`2,2`) headers are accepted; any other value is refused. A WAL
source is read through the same ordinary `mode=ro` URI, `query_only=ON` and one
bounded read transaction as a rollback source. SQLite may create or update its
normal `-wal`/`-shm` auxiliary files for that read-only reader (WAL-index read
marks, or empty files on a cold WAL DB); that is standard read behaviour, not a
source change, and no byte-for-byte sidecar invariance is claimed. The main DB
file is opened read-only, so a reader never checkpoints into it. Existing
`-wal`/`-shm` must be regular single-link files: symlinks, hardlinks and other
non-regular sidecars are refused before SQLite opens the source. A `-journal` in
WAL mode, or any `-wal`/`-shm`/`-journal` beside a rollback-mode source, is
refused; in rollback mode a writer can make a journal appear briefly, and that
refusal is a visible gap, not an instruction to touch the producer. Sidecars
are not part of the pinned source identity (path, device, inode), because a
healthy WAL lifecycle recreates them. The adapter never switches journal mode,
checkpoints, pauses the producer, uses `immutable=1`, chmods source files or
copies the main file and WAL separately. Focused tests use disposable physical
WAL fixtures only: a separate writer process holding WAL open with a committed
WAL-only row and a mid-read commit, a cold WAL header with no sidecars, rollback
sources and sidecar/source alias guards. Live-source compatibility is still
established only by the coordinator's own gated runtime check.

## Start, smoke, resume and stop

Use an existing host venv and an existing real parent directory. The run root
must **not exist**; the CLI creates it as `0700`. All path components must be
real directories; symlink paths and multiply linked files are refused. Never
reuse an output directory for a different source or run.

After the independent gate, the coordinator's illustrative host command is:

```sh
.venv/bin/python benchmarks/tools/evalops/capture.py \
  --db /absolute/path/source.sqlite \
  --output-dir /absolute/private/NEW_CAPTURE_RUN \
  --duration-seconds 604800 --poll-seconds 60
```

This starts a lightweight stdlib host runtime process. It launches no model,
scheduler or agent. Maximum duration is seven days. Do not run this command as
an implementation/readiness check against a native production DB.

For a safe synthetic fixture or a separately authorized source smoke, add
`--once`. One complete bounded observation plus immutable exports/report is
published, then the process exits. `--once` does not complete the duration.
A later invocation can continue the same run:

```sh
.venv/bin/python benchmarks/tools/evalops/capture.py \
  --db /absolute/path/source.sqlite \
  --output-dir /absolute/private/EXISTING_CAPTURE_RUN --resume
```

Resume takes cadence, duration, deadline and limits from `run.json`; command-line
values cannot enlarge them. It requires the same DB path/identity and executed
capture/runner helper hashes. Before appending anything, it validates bounded
strict JSON, the entire ledger chain, every referenced artifact hash, row hashes,
snapshot replay and artifact file identities. Unknown names, symlinks, hardlinks,
malformed JSON, duplicate keys, nonfinite numbers and truncated/corrupt ledgers
are errors. It never truncates a ledger or overwrites an existing artifact.

Every restart records `restart_offline` from the last successful observation to
restart, even if no source change is visible. Complete uncommitted artifacts
from an interrupted publication stay intact and are named in an
`interrupted_publication` gap. Malformed partial artifacts require operator
review; automatic resume refuses them. Never delete or edit bytes to make the
validator pass. If initial publication failed before `run.json` or the ledger
existed, preserve that directory and use a new run after diagnosing the cause.

Send `SIGTERM` or `SIGINT` to the collector PID to stop. It finishes the bounded
active operation, records `operator_stop`, and publishes immutable exports plus
a `stopped` report. Sleep checks are at most 30 seconds; active SQL reads have
an independent deadline. A hard kill can leave an incomplete publication;
resume must validate it and disclose the uncertain interval. Stopping never
removes collected files. Resume is useful only before the **original** deadline;
a late resume reads no source rows and only publishes already observed evidence
with `duration_completed`. That status means elapsed observation time only.

## Poll contract and resource bounds

Each poll opens a URI with exactly `mode=ro`, sets `query_only=ON`, uses a bounded
busy timeout/progress-handler deadline, and closes one consistent read
transaction promptly. There are no SQL writes, checkpoints, vacuums, full DB
copies, network calls, classification models or native accounting operations.
Only a fixed DB header, file identity and sidecar file types are read outside
SQLite; full DB/sidecar hashing per poll is avoided. In WAL mode the single read
transaction is one snapshot: commits made while a poll reads are seen by the
next poll, never spliced into the current one.

A poll reads both tables in indexed integer-ID keyset pages, including negative,
old and imported IDs. It compares canonical UTF-8 compact sorted-key JSON row
SHA256 hashes against the previous observed state. The first snapshot records
observed existing rows. Later snapshots emit inserts, updates and tombstones;
unchanged rows emit no changes. Full rows preserve mutable occurrence counts,
`last_seen_at`, decision metadata and every observed version separately from
scorer inputs. The ten-minute error dedup producer changes an existing ID;
decision update/import paths also invalidate a new-ID-only cursor.

| Bound | Default / fixed cap |
| --- | --- |
| Total rows across both tables per poll | 50,000 / configurable up to 100,000 |
| Canonical row bytes per poll | 64 MiB / configurable up to 256 MiB |
| Rows per keyset page | 1,000 maximum |
| Read deadline / SQLite busy timeout | 5 seconds / 1 second; each configurable up to 30 seconds |
| Schema metadata | 256 KiB; at most 128 columns per table |
| Total stored bytes | 4 GiB / configurable up to 16 GiB |
| Retained distinct IDs across both exports | 100,000 |
| Ledger / events | 32 MiB / 50,000 events |
| Individual artifact / manifest reads | 256 MiB / 256 KiB |
| Resume validation | 30-second check between bounded artifacts/events |

CLI knobs are `--max-rows-per-poll`, `--max-bytes-per-poll`, `--page-size`,
`--read-deadline-seconds`, `--sqlite-timeout-seconds`, and `--max-run-bytes`.
Bounds cause failure, never a successful truncated observation. Data publication
or budget exhaustion may itself prevent a final failure report; stderr/nonzero
exit and previously durable bytes remain authoritative. Large distinct-ID
churn or mutation volume can exhaust a run before seven days.

The focused synthetic capacity case uses the inventory's 19,835 decisions and
1,548 errors under the defaults. This verifies representative row counts, not
production row widths, latency, memory, disk admission or co-tenant capacity.
Batches record row counts/bytes, bounded cursors, pages, schema identity and read
duration; reports include expected cadence, actual observations/times and gaps.
The coordinator must inspect measured host load before runtime admission.

Collector UTC times are aware and separate from raw source event times. Within
one host boot, monotonic and wall time must agree within two seconds; rollback,
jumps or backwards observations fail loudly. Across a reboot the run records an
offline gap and keeps the original UTC deadline; UTC correctness during offline
time is not independently proven. The first UTC or monotonic deadline ends the
active run. Missed cadence is recorded rather than hidden by moving the next
poll relative to a slow read. Timing, source replacement/schema/read/lock
failures and size overflows cannot produce an acceptance claim.

## Durable outputs and scorer contract

`run.json` is an exclusive immutable manifest. `.lock` is a persistent inode
with a process-held nonblocking `flock`; never unlink it to bypass a live writer.
Artifacts are exclusive `0600` files named `SEQUENCE-UUID.*`. Each completed
observation writes a `.batch.json` file. Export/report sets are published after
`--once`, finite termination, graceful stop, or a reportable failure, rather than
copying all exports on every poll. No existing artifact is replaced.

Referenced files are flushed/fsynced, and their directory entries fsynced,
**before** appending/fsyncing the corresponding JSONL ledger line. Each ledger
line contains sequence, previous hash, aware UTC and monotonic time, typed kind,
payload and artifact names/byte counts/SHA256 digests; its hash covers canonical
JSON of the line without its `hash` field. The first previous hash is the
canonical manifest hash. Hashes provide integrity evidence, not authentication,
producer completeness or an independently witnessed chain head.

Find the last `publication` entry in `ledger.jsonl`. Its `files` map names the
immutable `.errors.jsonl`, `.lessons.jsonl` and `.report.json`; the CLI prints
that report as JSON. The report schema is `evalops.capture.v1`. Scorer payloads
contain exactly:

| Export | Fields |
| --- | --- |
| errors | `id`, `task_ref`, `error_class`, `created_at` |
| lessons | `id`, `task_ref`, `decision`, `rationale`, `created_at` |

Exports contain one **latest observed** record per source ID, not an error per
observed version. A deleted ID retains its last observed row; `deleted_ids` in
the report and immutable tombstones disclose deletion outside strict scorer
payloads. Source timestamps are not suffixed with `Z` or replaced by collector
time. Naive strings remain naive. Unparseable/empty source times become `null`
in strict scorer payloads; the exact raw values remain in batches and are counted
as unknown. Reports count aware, naive and unknown latest-record timestamps.

The existing `run.load` and `run.validate_recurrence` accept these synthetic
exports in focused tests. Neither `run.py` nor recurrence semantics change.
No canonical `coverage.json` is emitted. Every report says
`quality_acceptance=false`, `seven_day_replay_ready=false` and
`source_guarantees_proven=false`. An independently justified future attestation
must follow `run.py`'s exact coverage schema and bind `errors_sha256` to the exact
export bytes. A hash chain, elapsed week, old event span, or gap-free polls alone
cannot justify `complete=true`.

Polling cannot observe intermediate changes between polls, delete/reinsert
cycles that return to the same state, or deletions before the first read.
Deduplicated rows do not enumerate original paid calls or individual error
occurrences. No producer delivery/retention guarantee, human validation, causal
improvement or accepted quality result is inferred.

## Rollback and verification evidence

Rollback is stopping the runtime PID and retaining the entire run directory.
There are no DB changes to reverse. Restore a reviewed code version for new
runs; an existing run refuses different executed-code hashes. Do not point an
older collector at an incompatible existing run, delete its lock/evidence,
reset a native subject, or restore an old DB over newer source data. The focused
stop/resume rehearsal verifies that previous artifact and source bytes survive.
A deployment rollback against a live source has not been practiced here.

The focused command, on the remote VM only, is:

```sh
LC_ALL=C uv run --no-project --with pytest python -m pytest benchmarks/tests/test_evalops_capture.py -q -p no:cacheprovider
```

Behavioral RED, scaffold/test hashes and logs are retained in
`.task-state/tdd/red-evidence.json`; the external coordinator acknowledgement
binds its SHA256 to MCP test-result `5701`. The source 2 WAL correction RED was
acknowledged as MCP test-result `5707`; its GREEN evidence is
`.task-state/tdd/green-evidence.json`. GREEN and deliberate original-scaffold,
mutation-diff, ledger-hash and read-only-URI controls are retained beside it.
Those controls restore the fixed bytes; they are test evidence, not quality
acceptance or a seven-day production trial. No unrelated full suite is needed
for this bounded slice.

## Decision trace

Use the pinned read-only Canon **v0.26.2**, all 53 manifest digests verified,
from `/home/gate/workbay-sandbox/evalops-1-assets-20261029/canon`;
[upstream citation target](https://github.com/darce/heuristics-canon).
Only observable triggers apply. Its measurement-integrity card and Principle 15
keep the observation denominator and acceptance decision outside the collector;
its reversible-commitments card and Principle 3 require preserved post-start
bytes. Principles 13, 16 and 19 support the acknowledged RED gate, loud failures
and bounded increments. Context-obedience and inference-graph/runtime-fork cards
are inert here and supply no authority for capture decisions.

- Named `snapshot → changes → ledger → export` contracts use
  [GRPH-32, An edge exists only where data moves](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/graph-theory.md#grph-32)
  and [GRPH-33, A node without a contract cannot be parallelised](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/graph-theory.md#grph-33),
  **practice labels**. Snapshot rows feed canonical changes; durable artifact
  hashes feed the ledger; validated latest rows feed scorer exports. The
  fsync-before-ledger order is a durability constraint, not inferred data flow.
- Measured admission rather than guessed concurrency follows
  [GRPH-31, Critical-path schedule the task DAG](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/graph-theory.md#grph-31),
  *The Algorithm Design Manual*, ch. 17, and *Scheduling: Theory, Algorithms,
  and Systems*, ch. 5 and §D.4. No model or extra implementation lane is launched.
- Independent row/byte/time/storage caps follow
  [RES-31, Bound high-impact automation](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/engineering.md#res-31),
  *The Site Reliability Workbook*, ch. 6; even reads create load.
- Refusal and disclosed gaps follow
  [AGT-10, Degrade loudly](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/engineering.md#agt-10),
  *The Art of UNIX Programming*, ch. 1. The deliberate regression controls use
  [TEST-15, Prove the green can go red](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/engineering.md#test-15),
  *The Pragmatic Programmer*, ch. 9.
- Future human/judge validation must satisfy
  [EVAL-12, Validate the judge against humans](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/ml-systems.md#eval-12)
  and [EVAL-13, Pin the judging protocol](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/ml-systems.md#eval-13),
  *AI Engineering*. The supplied research
  [FIR embeddings/dimensions/detectors QA](../../benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html)
  likewise requires blinded human adjudication and frozen independent
  denominators. This slice produces no new quality result.
- Preserving capture evidence during back-out applies
  [RLSE-08, Rollback written before ship](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/engineering.md#rlse-08),
  *Continuous Delivery*, ch. 10 and ch. 12. Capture speed is not proof of delivery
  improvement under
  [OPS-75, Improve the measured constraint](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/planning.md#ops-75),
  *The DevOps Handbook*, ch. 2; human gold/QC remain separate missing evidence.
