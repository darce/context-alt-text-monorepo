# Fifth-source independent native transport controls

Task B is test-only, authored in the private OCI VM scratch checkout. This is
source-family pass 5, parent `MAINT-LEXICON-EXTRACTION-20261022`, not a new repair
lineage. No production source was authored, patched, imported, installed, or
invoked. No GPU, model, customer-image, controller, or production helper action
was executed. Native workers only run fixture-returning functions, deliberate
failures, and scratch-file callback probes.

## Run the two distinct gates

From the repository root, lane self-verification is exactly:

```sh
pytest -q --noconftest benchmarks/description-full-precision/owner-control-regression/test_native_transport.py -k baseline
```

Unfiltered candidate acceptance is exactly:

```sh
pytest -q --noconftest benchmarks/description-full-precision/owner-control-regression/test_native_transport.py
```

The default candidate is the sibling
`benchmarks/description-full-precision/owner-control/owner-custody.py`.
An explicit source fixture can be supplied with `OWNER_CONTROL_CANDIDATE`:

```sh
OWNER_CONTROL_CANDIDATE=/absolute/path/to/owner-custody.py pytest -q --noconftest benchmarks/description-full-precision/owner-control-regression/test_native_transport.py
```

Missing candidates are assertion failures. There are no skips, xfails, implicit
original fallback, or conditionally removed candidate tests. The baseline
selection is green because it asserts the known original failure. It cannot
certify a candidate. Candidate implementation acceptance has **not been run**
in this private checkout; no candidate was supplied. The missing-path acceptance
gate and the retained-original negative acceptance control were executed.

## Independent oracle and execution boundary

All fixture bytes are verified against the sealed manifest before each probe.
The manifest, exact installed seven-script baseline, real 137715-byte view,
six accepted R4 files, and explicitly failed R3 seed are included for portable
replay. The failed seed remains at `fixtures/prior-r4/seed-failed-caller.patch`;
only `fixtures/prior-r4/accepted/caller.patch` is the accepted patch.

The loader compiles actual top-level function ASTs and their function helpers,
with inert constants (including constant arithmetic) and allowlisted stdlib imports. It never imports an
application module, executes the subject's top-level body, loads its CLI, or
invokes `main`, guardian, writer, launch, or stop paths. Unsupported loader
dependencies fail loudly for explicit review; they never select a substitute
implementation. An OS forwarding observer records fork PIDs without adding a
`before` gate to the full/small read probes or reconcile's read. Callback probes
exercise the actual `before(pid)` gate separately.

Each behavioral test starts a fresh isolated Python subprocess/process group
with a private scratch directory and a 12-second watchdog. The real caller's
five-second native deadline is used for full-view acceptance, with its existing
two-second reap grace. Acceptance requires exact full-object equality, including
all authority history, both publications, loads, and deferred state. These
inputs, deadlines, and the oracle are fixed outside the candidate. No candidate
serializer or advertised result cap is used to construct expected output.

Reconcile executes its actual AST against immutable-format scratch custody
records. Its live `view` read is replaced with the exact sealed actual view;
its guard is a recording assertion so reconciliation selection can be tested
independently of whether the real captured publication belongs to this test.
All custody enumeration/receipt parsing and native transport remain actual
source functions. Separate tests transport hostile ownership changes and call
the actual guard, requiring precise foreign-publication and authority-conflict
refusal. These separate concerns have separate assertions.

Contracts also cover identity retention before effects, `after()` ordering,
admission refusal, function exceptions, serialization failure, abrupt exit,
native timeout/reaping, and a child that completes its result but then blocks or
raises in `after()`. Successful result bytes alone must not turn a nonzero child
status into success. `waitpid` must report that every observed native worker
was already reaped before the API returns.

## Actual-source call-path review

Graph tools were unavailable in this session. The requested bounded review was
performed directly against all seven manifest-verified installed scripts; it
does not claim a fresh knowledge-graph generation. The baseline inventory test
also verifies all five direct native call sites by AST.

| Source path | Data that actually moves |
| --- | --- |
| `owner-window.py:44` inspect | `c.view(paths,'inspect')` full result through `native_job(...,5)` to sealed `inspect.json` |
| `owner-custody.py:278` guardian preflight | `view(paths,plan['action'])` full result to sealed preflight and ownership guard |
| `owner-custody.py:300` writer | `effect()` completion marker, `started(pid)` identity custody before effects, `after()` hook outcome, wait status to `writer-stopped.json` |
| `owner-custody.py:307` guardian reconciliation | full `view(paths,'auto')` publications and authority compared under retained fences; uncertainty retains guardian/custody |
| `owner-custody.py:357` read-only reconcile | full `view(paths,'auto')` through five-second native read into guard and latest proven operation selection |

`owner-window.py:46-62` operation launches `--guardian` and polls immutable
result receipts. CLI `start`, `stop`, and `auto` route through that operation;
`--guardian` loads exact custody/writer inputs then calls `c.guardian`.
`reconciled()` retries only pending/unresolved outcomes; the actual native
`reconciliation read unknown` is not repaired by that retry. `withdraw` uses
reconcile and an owned AUTO operation. `root-flow.sh` inspects, starts, observes,
and requests AUTO withdrawal (including its failure trap). `final-stop.sh`
reconciles the explicit window, requests STOP, observes it, then requests AUTO.
None of these production paths was executed. The native timeout path kills and
reaps the owned worker; inability to reap retains the guardian/fences. Guardian
publication reconciliation likewise does not release uncertain custody merely
because a worker exited.

The installed `MAX=1048576` is an individual source/receipt read cap. It is not
the `native_job` result limit. The exact original result encoder rejects
`len(json.dumps(value).encode()) >= 60000`. The actual view is 137715 bytes in
both its sealed file and original native encoding. The 91-byte cause-removal
control preserves the four top-level result fields but removes history and
publications. It is only a falsification control, never an acceptable projection
for guard or reconcile.

## Evidence and retained lineage

`evidence/runs.json` records actual commands, return codes, and log hashes;
the adjacent text logs retain failures. `provenance.json` names every source
and hashes the retained references. `evidence/baseline-probes.json` records raw
status/equality/reaping summaries without dumping publication or environment
values.

The original supplied as a candidate fails the *same positive candidate tests*
for full roundtrip and real reconcile, while the other eleven candidate
contracts pass. The missing-candidate unfiltered command fails all thirteen
candidate tests while all fifteen baseline tests pass. These negative controls
are intentionally retained; they are not candidate acceptance success.

R3 source `c8f3e463e4ba5c387a9cd68c2606e9350a9ffe29` remains REVISE (review
1659: top-level cursor bug). R4 source
`506ecedda3cad4ac48be05d84518c649255785a4` remains an unadopted
SOURCE_ONLY_PASS (review 1660), limited to its offline caller excerpt. Its
20-green suite and original-caller-red history do not imply installed native
transport success. The owner-window workaround is disproved; this lane makes
no end-to-end reconcile/STOP or live-effect success claim.

Canon is operator-pinned published v0.26.2. The remote copies of engineering,
falsification-disconfirmers, measurement-integrity, and PRINCIPLES match the
operator's supplied digest prefixes. Read rows/cards and original distillations
are retained with hashes. DBG-11 drives the full/small absence experiment;
TEST-15 drives original-as-candidate RED; TEST-33 requires the later independent
review to rerun every requested correction; GRPH-14/32 drive the provenance
edges naming the actual fields passed. The supplied description input snapshots
contain pragmatic-programmer and implementing-effective-code-reviews originals;
Why Programs Fail was read from the remote archived refactoring distillation
whose book/chapter identity is recorded separately. No engineering-path copy
of that original is falsely claimed. STOR-10 tombstone material has no role here.
