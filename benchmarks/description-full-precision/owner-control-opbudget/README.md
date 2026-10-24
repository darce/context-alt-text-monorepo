Operation capacity repair, source lane B

Production delta is limited to `MAX_WINDOW_OPERATIONS=1024`, its use in
`known_candidates`, and `owner-window.operation`. The seed is the manifest-verified
private `budget-source5` subtree (e1b7); commit 68a1981 copies it unchanged.
Native framing, callback behavior, all existing tests, six other scripts, and
independent 643a controls are unchanged.

Admission uses the same `window.lock` as the guardian. While holding it, the
client validates retained directories/candidates, checks the directory count,
and exclusively creates a fresh UUID directory and sealed intent. All directory
entries count, including failed/pending operations. START may reserve only when
the existing count is below 1022. STOP and AUTO may reserve below 1024, sharing
the last two slots: these are not one slot guaranteed to each action. Failed
admitted operations consume their slots permanently. At 1024 all creation is
refused before any new directory, intent, log, or guardian, while enumeration
and reconciliation still work. At 1025 enumeration fails closed. No pruning,
name reuse, window cloning, or authority reset implements this policy.

The admission lock is released in `finally` before opening the guardian log or
launching the child. A guardian can therefore acquire its own window fence;
contenders cannot race the count/reservation. The guardian still resolves the
exact `plan['previous']` through known candidate custody, requires its published
result, compares window actor and authority/publications through `guard`, and
validates unchanged window metadata in the CLI. Admission reserves capacity; it
does not authorize publication or replace those checks. The existing 15-second
window-fence timeout remains, and the per-read/native IPC bound stays 1 MiB.
1024 accommodates the stated 48h/240s envelope (~720 renewals), 33 old directories,
and rotation/cleanup. Finite capacity still requires stopping before exhaustion.

Source trace (direct source review; graph tools unavailable): CLI start/stop/auto
and withdraw -> operation -> local intent -> guardian CLI -> guardian ->
window.lock -> known_candidates -> exact previous result -> native view -> guard.
Readonly reconcile -> known_candidates -> result/publication/stopped proofs ->
native view -> guard. `root-flow.sh` and `final-stop.sh` remain consumers of those
CLI paths. No production entry point was executed during this repair.

The isolated fixture preserves the supplied snapshot verbatim, including failed
07a7a618-2c61-4a06-84ff-07849c5426c7 and last published sequence 264. It contains
33 UUID directories, 31 candidate payloads and two refusals. Because the snapshot
contains intent/result/candidate payloads only, publication/stopped proofs and
the source authority/publication view are explicitly synthesized for offline
reconcile. These are test fixtures, not claims about recovered live proofs.
Every original fixture payload is checked for unchanged bytes after each
relevant operation. A separate original-function probe runs the actual source5
operation and guardian: directory 33 produces exactly the saved refusal payload
and wedges readonly reconciliation. Removing that failed directory only in a
separate initial fixture gives the 32-directory GREEN cause-removal control.
The saved 33-directory snapshot itself is never pruned.

`test_operation_budget.py` loads complete custody source and compiles the exact
operation AST from its full client file, avoiding root-only CLI bootstrap.
Popen is replaced only at the external process boundary; filesystem custody,
flock, read validation, reconciliation, native fork/IPC and guard remain real.
Four genuine processes contend for each of the last START and cleanup slots.
The launch mock independently reacquires window.lock to detect lock retention.
Full-history tests also read candidate-bearing history at 1023/1024 directories
through real file reads, native IPC, and guard, with the 1 MiB bound intact.

Evidence commands and exits are in `evidence/runs.json`; complete raw logs are
retained. `source5-red.txt` is the same positive recovery/admission oracle run
against source5. `source5-author-tests.txt` has 23 behavioral passes and two
failures in historical source5-only scope/hash assertions. Those author tests
remain byte-identical as requested; our declared-region verifier checks every
other production byte. The two independent callback probes are still RED in
`known-callback-defect.txt`: completed values are lost after callback exception
or timeout (finding 19863). This lane does not fix that defect or run a combined
acceptance gate. The callback lane's scope verifier must allow precisely the
B constant/known_candidates/operation regions without relaxing other functions.
No installation, full report, model quality conclusion, GPU/root/API/network
or live owner-window operation is asserted. A combined independent gate follows.

DBG-11 / TEST-15: 32 vs actual 33 cause removal, unchanged positive oracle RED
on source5, and corrected recovery/admission GREEN. TEST-33: each requested
correction maps to named tests and retained failures. GRPH-14: manifest ->
source5 seed/snapshot -> real functions/private fixtures -> command/raw logs.
GRPH-32: admission and guardian share a lock resource, while candidate/previous
and native view fields are actual data edges. Shared custody source ownership
with callback lane A creates no precedence dependency. Matched rows, principles,
measurement-integrity, falsification and bounded-waiting cards were read at the
operator-pinned v0.26.2 hashes. Original pragmatic-programmer and code-review
distillations match supplied pins. Available immutable Why Programs Fail and
Debugging originals are under refactoring paths with different hashes from the
requested engineering copies; exact paths/hashes are recorded in provenance,
without claiming the missing engineering bytes were read. The disconfirmer is
any retained payload change, oversubscribed admission, leaked custody on budget
refusal, changed foreign guard, or native_job byte change. Next feedback boundary:
the single combined independent gate, followed by separately authorized adoption.

Scope correction for gate finding DW-IPC-RECOVERY-G1-01 (test/doc only)

The former single `test_declared_regions_only_against_source5` compared the
in-tree custody, after undoing B, with source5 bytes. After composition on
accepted callback A7 that rejects A7's authorized `native_job` completion proof
(retained RED: `evidence/composed-scope-red-pre-correction.txt`). Its later
assertions were masked by that first failure; under composition they would also
reject A7's `test_native_transport.py`, `README.md`, `native-transport.patch`
and the composed `candidate-scripts.json` pins. Production bytes are unchanged.

`undo_b` removes exactly one module-level `MAX_WINDOW_OPERATIONS=1024` line and
restores exactly one `len(names)<=32` inside `known_candidates`; a duplicate,
missing, moved or altered B region raises. The result must equal the bytes of
one explicitly named, SHA-256-pinned baseline:

| scope | candidate | baseline after undo-B |
|---|---|---|
| `b-only` | `fixtures/b-only-source009030-owner-custody.py` (f14b49bd..., B's pinned 009030 custody; rebuilt as source5 + `evidence/focused.patch`) | `fixtures/source5-owner-custody.py` (42b03d88..., budget-source5 manifest 6038b6e6...) |
| `composed` | production `../owner-control/owner-custody.py` | `fixtures/accepted-source7-owner-custody.py` (576bb831..., A7 commit 3a680fc622c41f0fb303b27275226280bd40fda9, copied from the custody-verified `accepted-source7` reference after hash check) |

Each scope also asserts that the other baseline rejects its candidate. Both scopes
keep the client comparison: `owner-window.py` outside `operation` equals source5
(1983f868..., which is also A7's client). The composed scope additionally checks the
whole `owner-control` tree against `fixtures/accepted-source7-control-files.json`
(64 files hashed from A7 commit 3a680fc; seven script pins match
COMPOSE-PREPIN-CORRECTION source7 pins from full custody 1d409dd0...): same file set,
all A7 files byte-identical except the two B-owned scripts and
`candidate-scripts.json`, whose only changes are those two pins, equal to the actual
composed bytes. B-only other-file identity is the historical B-only tree proof in
`evidence/scope-final.txt`; this composed checkout cannot re-run it.
`test_scope_proof_rejects_tampering` proves the green can go red for both scopes:
one extra byte in `native_job`, `guard`, `guardian` or `reconcile`, a moved or
changed bound, a duplicated constant, or undone B each fail the scope proof.

Functional tests still load the composed production (`CONTROL`), and
`OPBUDGET_BASELINE=1` still reproduces the original source5 33>32 refusal. All
earlier logs, RED evidence, `runs.json` and `artifact-hashes.json` (B 009030
state) are kept unchanged; the correction's runs and pins are appended in
`evidence/scope-correction.json`.
