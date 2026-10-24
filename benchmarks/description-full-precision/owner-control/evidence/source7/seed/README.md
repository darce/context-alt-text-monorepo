# Fifth-source native owner result repair — adoption pending

The installed `native_job()` refused the complete 137,715-byte saved view with
child exit 71, leaving actual reconciliation unknown. This correction streams
the complete JSON result through the native pipe, checks writes, and requires
EOF plus successful reaping before returning usable evidence. It preserves all
261 authority records, sequence/rejection history, publications, loads, deferred
state and ownership fields. No cursor projection, history filter or caller
excerpt correction is applied.

All authoring, tests and source inspection occurred in the private OCI VM
scratch repository. This is source pass 5 in the existing repair family.
Independent lane B, joined review, WorkBay landing and native adoption remain
pending. No root helper install, controller command, model/GPU operation,
customer image action or live launch/report occurred.

## Exact changed bytes

Seven installed scripts were copied from the verified sealed baseline. Only
`owner-custody.py` differs. Its original 17,715 bytes have SHA256
`cba8527bf94603778e78910b60b04ad9c5bad38eafa0691bb21b3435990a158f`;
the candidate is 18,974 bytes (+1,259), SHA256
`42b03d88a7cf89b4fcc4bf6ac6ce2c84ba0789abfa67abdadcab6dc5f37a1ef9`.
Only `native_job()` changed: original byte interval [9903,11730), lines 203–260,
became [9903,12989), lines 203–285. The prefix and suffix are byte-identical.
`native-transport.patch` records the exact change (zero context); SHA256
`1148dd2d594d0d4001202c062d1f6350d781a98fbb736b2e4d0ca28ef7aec42f`.
`candidate-scripts.json` pins the seven candidate files, without representing
an approved production staging manifest.

The other six scripts retain their original hashes in the rollback table below.
Additional files are offline tests, exact sealed fixtures, this documentation,
the diff and evidence/provenance. The original custody script is retained in
`fixtures/original-owner-custody.py` for portable RED replay and rollback.

## Explicit resource and outcome contract

The transport accepts at most **1,048,576 encoded JSON bytes**, inclusive. This
uses the existing `MAX` custody-read budget: native views are persisted as
custody receipts, and existing `read_at()`/`bounded_json()` already admit at
most that many bytes per file. It is an explicit aggregate transport budget,
not a claim that every possible sum of individually valid input files fits.
The complete supplied full view fits. Larger results are refused, never
truncated or projected, and do not advance authority. Existing receipt-format
and read limits remain unchanged.

The child uses incremental JSON encoding, writes in blocks of at most 65,536
bytes, retries interrupted/short writes and refuses zero progress. Parent reads
are at most 65,536 bytes; the receive buffer is capped at MAX+1, including an
overflow detection byte. No spool paths or temporary transport files are used.
This bounds transport bytes, not the heap consumed by the existing `fn()` that
constructs a view, or by a JSON encoder's individual string fragment/decoded
object. No history bound was invented to justify pruning.

The monotonic deadline starts before fork, is checked between receive blocks,
and gates release after `before(pid)`. The synchronous identity callback must
finish before any native effect; it cannot itself be preempted by this function.
If it finishes after the deadline, the child is killed/reaped without release.
`after()` runs only after the complete result was written, as before; its
failure or timeout makes all delivered bytes unusable. Nonzero child status,
incomplete/oversized data, invalid UTF-8/JSON and nonfinite JSON numbers yield
no usable value. Actual wait status is retained; a malformed stream can have
status zero, so callers must continue checking both status and result.

All parent error/timeout paths kill and seek positive `waitpid` reaping proof.
After a two-second reap attempt, an unreaped or unknown worker retains the
native guardian indefinitely, holding its inherited fences. IPC results remain
evidence. They cannot replace actual candidate custody, persisted-publication
comparison, foreign-state checks or monotonic sequence checks.

## Trace against actual source

All seven scripts were searched; AST inspection of the complete Python files
found exactly five native call sites. `evidence/provenance.json` records their
expressions, line numbers and source hashes.

| Caller | Native input and downstream use |
| --- | --- |
| `owner-window.inspect`, line 44 | `view(paths,'inspect')`, 5 seconds; seals the complete inspect receipt. Inspect's container/config commands were only read as source. |
| `guardian`, line 303 | `view(paths,plan['action'])`, 5 seconds; seals preflight and passes all fields to unchanged `guard()`. |
| `guardian`, line 325 | `effect`, 12 seconds; `started(pid)` seals boot/start/PID identity before gate release; candidate publication and optional `after` hook remain unchanged. |
| `guardian`, line 332 | `view(paths,'auto')`, 5 seconds; compares actual persisted publication or the complete prior state under held fences; otherwise retains guardian and retries reads. |
| `reconcile`, line 382 | `view(paths,'auto')`, 5 seconds, no projection floor; checks proven receipts, then unchanged `guard()` before selecting an operation. |

`root-flow.sh` performs inspect → start → observe → owned AUTO; its cleanup
uses `withdraw`. `final-stop.sh` verifies the exact window ID → reconcile →
STOP → observe → AUTO; its cleanup also uses `withdraw`. In `owner-window.py`,
start/stop/auto create an operation and detached guardian; reconcile/withdraw
first select through actual `reconcile()`. The guardian holds window/lifecycle,
publication and authority fences, binds the immutable candidate, registers the
native writer identity, publishes, reaps and compares persisted bytes before
unlocking. The transport correction is shared by every native read and writer
result on those paths. None of these live CLI paths was executed here.

## Reproduce offline

From the repository root:

```sh
python3 -B -m unittest discover -s benchmarks/description-full-precision/owner-control -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q --noconftest benchmarks/description-full-precision/owner-control -p no:cacheprovider
python3 -B benchmarks/description-full-precision/owner-control/test_native_transport.py --baseline NativeRealShapeTests -v
python3 -B benchmarks/description-full-precision/owner-control/test_native_transport.py NativeRealShapeTests -v
```

The baseline replay intentionally exits 1: full-view child code 71, plus two
actual reconcile failures with `reconciliation read unknown`. Its 91-byte
cause-removal control passes. The corrected replay runs the same four tests
and input and exits 0. One reconcile test substitutes only the read-only view
input; the other uses actual `view()` reading private temporary files, with
publication path keys relocated to those files. Both retain actual native
fork/pipe, guard and sealed operation receipts.

The stdlib suite and pytest also cover the exact byte budget, overflow,
short/interrupted/zero writes, child/serialization/after failures, malformed
wire data, identity-before-effect ordering, gate refusal, receive/after
timeouts, fork/read failures, reaping and descriptor closure. Uninterruptible
and unknown-reap controls simulate kernel outcomes without abandoning a real
child. Authority controls retain rejection history, old/new conflicting
records, foreign publications/deferred STOP, owner identity and STOP loads.
Tests import the complete native source; no duplicated transport algorithm or
service/conftest dependency is used.

Actual outputs are retained under `evidence/`. The initial harness's erroneous
104-versus-106 byte-count assertion is kept separately; it was corrected to an
explicit 91-byte control before the paired baseline/corrected replay. It is
not transport evidence. The originally captured three-test RED/GREEN and later
expanded outputs remain available alongside final logs.

Final recorded results: stdlib unittest **25 tests, OK**; pytest **25 passed,
17 subtests passed in 3.35s**, exit 0. The paired original replay exits 1 with
one failure/two errors; the corrected replay exits 0 with four tests OK.

## Input custody, Canon and earlier evidence

`fixtures/input-manifest.json` is the exact input manifest, SHA256
`80f7267a090a69fbe05e8a55ce6dce4f9c958290db3a9c97f1efc67cda95e7fc`.
All 15 members were verified before use. `fixtures/actual-view.json` is the
exact 137,715-byte view, SHA256
`e388f8be6741710f0399176368b633ef0894f9f123e13afb8f7bdad2aa5e9939`.
It contains the authority/publication contract, no credentials, environment
snapshot or customer images. Fixture files were sealed read-only in this
workspace; committed content hashes are the portable seals.

R3 source `c8f3e463e4ba5c387a9cd68c2606e9350a9ffe29`, review 1659 REVISE,
failed at the top-level cursor lookup. R4 source
`506ecedda3cad4ac48be05d84518c649255785a4`, review 1660 SOURCE_ONLY_PASS,
corrected only the offline caller excerpt and remains unadopted. The accepted
six-member R4 identity is preserved in the input manifest and provenance;
accepted `caller.patch` SHA256 is
`30e4e8db654a6f5af7e8291056a00640875ef0d67753d66ae93f9a0ee3a804ce`.
The failed seed patch was verified only as a manifest member and never applied
or selected as accepted. Supplied prior R4 20-GREEN/original-caller-RED evidence
and current installed-native failure evidence are retained unchanged under
`evidence/prior/`; these are prior records, not fresh runs claimed by this lane.
The old-owner workaround is disproved for the current owner. No last-wave
end-to-end success is claimed.

The operator's published Canon v0.26.2 pin takes precedence. Read-only VM mirror
engineering/cards/PRINCIPLES digests match the supplied pin; exact paths and
hashes are in provenance. DBG-11/TEST-15 drive unchanged-input RED/GREEN and
cause removal. TEST-33 drives named-request rechecks; independent approval is
still pending. GRPH-14 records input → source → tests → coordinator lineage;
GRPH-32 records fields that actually cross edges and explicitly names native
side-effect/custody ordering. Falsification/measurement cards and relevant
principles were read, along with supplied original distilled Pragmatic
Programmer ch9, Effective Code Reviews ch11 and graph lineage material.
Why Programs Fail was absent from the two supplied description bundles; its
ch12 was read from an existing VM distilled source and that path/hash is
recorded. GRPH-32 remains a practice label; STOR-10 is inert here.

## Safe staging and rollback — instructions only

After exact-source independent joined review and WorkBay landing, the
coordinator may use the existing protected bootstrap to stage a **fresh**
root-owned, sealed procedure directory containing all seven reviewed scripts.
Verify held no-follow file identities and hashes against
`candidate-scripts.json`; only the adopting coordinator may produce the
approved staging manifest. Keep the original sealed procedure directory and
its original hash manifest. Do not overwrite an in-use procedure or change
existing window/guardian bindings. Existing windows name their immutable
procedure path and must retain their native guardians/fences until proven
resolved. Installation does not authorize launch, STOP, controller or GPU work.

For rollback, select a separate sealed procedure assembled from the six
unchanged scripts plus `fixtures/original-owner-custody.py` restored under its
original filename. Verify **all seven ORIGINAL hashes** below before selecting
it for future explicitly authorized windows. Never use the candidate custody
hash as rollback identity. Rollback restores the known original large-result
failure too; it is not permission to discard custody, stop guardians or retry
uncertain publication. Retain candidate and original evidence.

| Original script | Original SHA256 |
| --- | --- |
| capacity-read.sh | `35f64983953f813b16449055508ebbe47b34a3cfeb47d48d84b3abd1615706f2` |
| final-stop.sh | `941bacf28640512a76a878d19a44dac44c7997ff577d81138f52d07fbd2a954e` |
| guest-read.sh | `2f614b1747faab8dd41cfa055133cedc1b3f25376652d794429a5984b143e8ca` |
| observe.py | `d71f1cc76e9fa6bc3e59c1f56723d3896f4b40baacb59bfad2c2745e52463bd1` |
| owner-custody.py | `cba8527bf94603778e78910b60b04ad9c5bad38eafa0691bb21b3435990a158f` |
| owner-window.py | `1983f8684de3d03a59c090b1b469e65f5b84ad201283e787bdf5fb872b8b6600` |
| root-flow.sh | `12c7fe5a2d1256c4c6fe5d00dfbdbdd5c546db521694663214b5235d207deb62` |
