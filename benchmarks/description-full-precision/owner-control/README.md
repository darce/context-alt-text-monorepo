# Source7 native result completion repair — source only

DW-IPC-R5-G1-01 / finding 19863: source5 returned `None` after a fully delivered
result when `after()` failed or timed out. The unchanged guardian derives its
publication barrier from the completed marker, independently of exit status,
then compares actual persisted bytes under all fences. Losing that marker
wedged custody. This candidate finishes the actual frozen source6 framing
implementation; it does not redo the transport or alter those consumers.

The verified repair input manifest is SHA256
`6038b6e69ddfb87248bcd44a320cf749a0e19d2088a69220d95042e925f9e123`.
All 64 listed files were verified. `callback-source6-partial` was copied and
committed before the focused changes. Its native source hash was
`426c3fe3e2530c298b10f091a36eb071f3e857cbc85bd5fbe85a0ddbb3bbc39f`;
source6 ended with wall-clock exit 124, not provider exhaustion. Its seed
commit was `8e275c8ccb45c47d3276b527ed0cee163ce3c768` and custody archive hash
was `327fa8fc0cb377bb9a42a4933eedd8f85faa25afb3240655844642b12809a4c9`.
No archive, repository checkout, independent control or live helper was copied
as the working seed.

## Completion and limits

The child incrementally encodes the complete JSON value and writes it through
the native pipe. Before calling `after()`, it writes a final proof:
`NUL native-result-complete NUL`, an unsigned 8-byte big-endian payload length,
and the 32-byte SHA-256 digest of the exact encoded payload. The proof is 64
bytes. Parent acceptance requires EOF, that exact final proof, matching length
and digest, valid finite JSON, and positive `waitpid` proof for the owned PID.
A syntactically valid JSON prefix is insufficient. Extra trailing bytes,
short/altered/repeated frames, malformed data and oversize payloads are unusable.
The digest detects stream corruption; it is not publication authority.

A complete result remains usable with actual child status 71, another exit
code, or SIGKILL after delivery. A timeout kills and reaps before returning;
post-reap nonblocking draining collects already delivered bytes. Worker status
and result completeness are separate facts. Four read consumers still require
status zero and a non-None value. The guardian writer barrier still uses the
completed marker and verifies actual persisted bytes under unchanged fences.

The inclusive payload bound remains **1,048,576 encoded JSON bytes**. Wire
storage allows the additional 64-byte proof and one overflow-detection byte.
Body chunks and parent reads are at most 65,536 bytes; the final write combines
at most 65,535 payload bytes with the proof. Short writes and EINTR are retried;
zero progress refuses. No spool files, projection, receipt pruning or authority
reset occurs. This bounds aggregate encoded transport data, not `fn()` heap,
an encoder fragment, decoded object size, or every sum of individually bounded
source receipts. JSON `null` still returns `None`, the existing unusable-value
sentinel for these callers.

Monotonic deadlines start before fork and are checked between reads and before
gate release. The synchronous `before(pid)` callback cannot be preempted; it
must persist native identity before effects. An expired callback never opens
the gate. Unknown or uninterruptible reaping retains the guardian/fences after
the existing two-second reap attempt; it never fabricates a successful wait.
These kernel outcomes are simulated in tests, not claimed as live observations.
EOF withheld by an inherited pipe descriptor does not establish completion.

## Scope and validation

Only `native_job` changes in this tree's production scripts. The six sibling
scripts, `known_candidates`, all globals, guards, guardian, reconciliation,
fence order and fence locks remain byte-identical to source5. The scope tests
also anticipate composition with the separately authorized budget lane: only
`known_candidates`, `owner-window.operation`, and new positive literal integer
constants <=1024 used exclusively by those two functions are exempted. Existing
globals (including MAX/pins/imports), every other function and all interfaces
remain asserted. In-memory scope probes accept those named regions and reject
changed guards, MAX, reconciliation, unbounded constants and escaped uses.
No sibling budget implementation is present here; its gate remains separate.

Using `/home/gate/description-import-environment-20261023/venv/bin/python3`, set
`PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` and run from the
workspace root (the recorded commands include absolute paths):

```sh
OWNER_CONTROL_CANDIDATE="$PWD/benchmarks/description-full-precision/owner-control/owner-custody.py" \
  /home/gate/description-import-environment-20261023/venv/bin/python3 -m pytest \
  --noconftest --import-mode=importlib -p no:cacheprovider -v \
  benchmarks/description-full-precision/owner-control/test_native_transport.py \
  /home/gate/description-owner-ipc-join-20261024T0408/code/benchmarks/description-full-precision/owner-control-regression/test_native_transport.py
```

The unchanged independent controls are commit
`643a2dd6fc8f7b9d6c78c00eb2d077d4338b69e7`; all 45 files are hash-verified.
They run in place with explicit `OWNER_CONTROL_CANDIDATE`, without copying or
editing the oracle. `evidence/source7/verification.json` records exact commands,
exit codes, hashes, fresh results and expected RED controls. Fresh author tests
cover complete delivery after callback error/timeout, a real guardian 12-second
writer timeout, persisted-byte mismatch retaining fences, valid JSON prefixes,
short/altered/malformed frames, exact/over-limit payloads, interrupted/short
writes and reads, identity ordering, real reaping and unknown-state retention.
The full 137,715-byte, 261-record fixture and actual reconciliation remain covered.

All prior evidence is retained. `evidence/source7/seed/` preserves the old README,
pin manifest and patch; other existing evidence/provenance files remain historical
source5 records. They are not this candidate's results. Current script pins are
`candidate-scripts.json`; `native-transport.patch` is the full original-to-current
native_job diff; `evidence/source7/source6-to-source7.patch` shows the finishing
change. The original and source5 source fixtures are immutable-content RED inputs.

## Lineage and acceptance boundary

Canon v0.26.2 engineering, graph and PRINCIPLES pins were verified from the VM
mirror. Matched rows, reasoning cards and original distilled chapters inform
DBG-11 (cause removal), TEST-15 (green-to-red controls), TEST-33 (named-request
recheck), GRPH-14 (manifest/source/test lineage) and GRPH-32 (actual data flow).
The supplied R6/R7 proposals, gate1668 result and verified ONNX reinjection are
retained in `evidence/source7/`. R3's wrong top-level cursor and R4's 20-GREEN
caller-excerpt patch remain earlier failed/inapplicable paths. Graph tools were
unavailable; direct complete-source/AST inspection traces all five native_job
consumers, including the sole normal CLI guardian call with hook=None.

This is an offline source candidate awaiting the combined independent gate.
Source5's controlled installation/reconciliation GREEN5415 is operator-supplied
history; no installation is implied by these source tests. The snapshot contains
all 33 operations, including the separate hard-32 admission defect. This lane
preserves all of them and does not repair that disjoint budget scope. The reported
154-token BF16 extraction is not a quality conclusion or complete report.

No root procedure, existing GPU owner window, GPU, cloud/API/network, model
service or customer-image operation was executed. No authority, receipt, window
ID or foreign-state guard was reset, cloned, deleted or weakened. Source7 adoption,
sibling composition, live runtime acceptance and model quality remain unverified.
