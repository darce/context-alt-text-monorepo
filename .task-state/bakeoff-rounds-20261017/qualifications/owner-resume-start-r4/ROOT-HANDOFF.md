# Prospective publication TTL: next procedure only

The next qualified procedure publishes START, STOP and AUTO with a fixed
`PUBLICATION_TTL_SECONDS=1800`; requested-to-expiry delta is 1800 seconds.
This source change is not deployment, qualification or live acceptance. Existing
installed stages, windows, 600-second operation bodies and receipts remain
immutable. Never relabel, reissue, renew or extend an existing publication.

The exact pinned writer admits 60..7200 seconds; its dataclass constructor does
not validate bounds and its public writer clamps them. The guardian now refuses
before candidate sealing if this fixed TTL is outside the pinned writer bounds.
Writer/load source pins and all window, owner, checkpoint and clock guards remain.
The actual native running lease remains 3600 seconds with its original origin
and nonce; a pending START is not an honoured lease. New model/client budgets
must be declared before a future run. A fresh native fixture qualification and
coordinator XHIGH gate are still required before adoption.

The elapsed fixed publication deadline was the supplied R16B batch blocker;
the parse error did not stop the client. No inference or live-state action was
performed here. Scoped private tests exercise the real pinned constructor,
guardian guard, forked atomic publication and reconciliation for all three
actions with controlled requested time; they preserve a sealed historical
600-second candidate and authority/origin bytes. A reduced native maximum
refuses before candidate/publication. These are UNIT_ONLY controls, not native
lease or Root qualification. The private authority origin is preservation
sentinel data, not evidence that a START was honoured.

Heuristics requested: v0.26.2 RES-02 (finite bounds), DBG-11 (causal contrast),
GRPH-32 (true dependencies), GRPH-33 (receipt contracts). These IDs and glosses
are supplied by the operator; canon text/digests could not be verified: the
pinned Mac path is absent on this VM and bounded exact-tag raw fetch failed DNS.

Remote verification on `acx-backend`, actual gate UID/GID1002, in the supplied
workspace: `timeout 55s python3 -B .../test_window_ttl.py` passed 2 methods
(including all three action subtests); `timeout 55s python3 -B
.../test_resume_start.py` passed 8 methods. Initial checkpoint run at 55 seconds
timed out (exit124) during the final method with no reported assertion failure;
`timeout 120s python3 -B .../test_window_checkpoint.py` then passed all 12
methods in 64.195 seconds (exit0). No dependency installs occurred.

Current approved-scripts manifest SHA256: `45c86daf3bc312eea23ab1382965b56dcbc1c97dd1c82070decc6ee617d3c5ca`.
Only the owner-custody.py entry changed. The following handoff describes prior
role/checkpoint work and historical verification; its manifest receipts do not
qualify this new source.

# Same-window checkpoint source handoff

Source-only LOUD18504 typed-role correction on exact joined source
`875f80651f23d119185b205af4f6000bf150656b` (controller source `9def5c1` plus
the C3 private metadata fixtures). The remaining shared-role defect admitted
API writer10001 as an authority-lock/state owner. The unchanged checkpoint
suite reproduced it before this correction: 12 methods, one failed
`authority-fence-owner` subtest and seven later FileNotFoundError cascades,
42.282 seconds, exit1. The accepted checkpoint had already archived operations;
the later errors were consequences, not independent parser or fixture defects.
Native Root C3 qualification and the final exact-source independent gate for
these corrected bytes remain pending. No live window, old sealed procedure, installed
controller, authority, publication, load, service, model or provider was changed.
Canonical source origin is `45ab1fc4e1716cbffd32b80802831b83f0ce94d2`, recorded
in `context/source-origin.json`; the native export deliberately strips history.
Baseline source receipts, evidence pins and `root_fixture_plan.py` are historical
inputs and remain unchanged. Their old stage digests do not qualify this source.
The regenerated seven-script manifest SHA256 is
`7e38e54ccae1e470da7576faf75872b7a4e2febd94de07f5304c141af2d7e8d5`.
Failed stage `20877883...` remains immutable external evidence; it is not a
qualification or adoption target for these bytes.

The supplied native evidence identifies the 33rd terminal refused operation
(`a3711ad0`), full external history custody (`61347fe1`), and latest proven
published AUTO `2216f4f2-a79c-46d5-9f5b-cc451dc85f59`. These are coordinator
inputs, not authority issued by this patch. Qualification must establish the
actual current persisted predecessor using original native receipts and guards.
Never substitute a new window, reset authority, delete operations, raise the
ordinary cap, manufacture ACK/source proof, or modify the original sealed stage.

## Controller-role correction and complete supplied metadata readiness

The prior fixture used Root-owned controller state. Actual native controller
state belongs to ubuntu1001, including its mode0600 lifecycle fence. The old
checkpoint required every fence to be mode0660 and admitted only the current
owner/API writer for ancestors and state files. Fixing only the first fence
would still refuse at the controller-owned authority fence or state ancestry.

`Paths(..., writer_uid=None, writer_gid=None, now=None, *, controller_uid=None,
controller_gid=None)` preserves every existing positional argument through
`now`. The two new library-only keyword fields default independently to the
constructing EUID/EGID. Each must be a real integer in `[0, 2**32-1)`; booleans,
strings, floats, negative and reserved IDs refuse. Fixed Production construction
passes `controller_uid=1001, controller_gid=1001`; writer10001 is unchanged.
There is no public role flag, UID adoption argument or configuration lookup.

`_resource_roles(paths, kind)` separates controller state from runtime
publications. Controller resources accept only the declared controller pair
(Production `1001:1001`, default private fixtures EUID:EGID). Runtime resources
retain custodian, custodian/API-group and API writer pairs (Production `0:0`,
`0:10001`, `10001:10001`). The runtime writer is never added to controller
roles. Authority JSON, deferred STOP and durable intent publications therefore
refuse writer10001 ownership, including the existing authority-state-owner
control. Mixed pairs such as `1001:10001` also refuse for controller state.

Durable ancestry admits custodian/controller and filesystem-root pairs before
the store; the store itself requires controller0700. Its descendants require
the controller pair at 0700 or 0755, preserving private fixtures and native
intents/prod0755 while refusing store0770. Runtime ancestry keeps its runtime
pairs. Traversal retains held no-follow descriptors and refuses world write
except the existing filesystem-root sticky1777 case. State file modes remain
exactly 0400/0600/0640/0644/0660. Regular type, one link,
1 MiB bound, still-named identity and SHA256 checks remain; the metadata checked
before reading must also match the identity of the file actually proved.

Fence policy is specific to the fixed role: the window requires its current
custodian pair and 0660 (Production `0:0`); lifecycle accepts only the declared
controller at 0600 or 0660, plus existing custodian-owned 0660 creation forms;
authority requires the declared controller or an existing custodian-created
pair at 0660, so writer10001:10001 refuses; runtime intent fences
accept custodian, custodian/API-group or API writer pairs at 0660. Every fence
must be regular, single-link and zero bytes. Unknown fence paths refuse. Existing
fences are opened read-only without creation, chmod or chown. Held/named fence
identities and the one 15-second deadline are preserved. Private default-EUID
fixtures use their actual owner pair rather than pretending to be native Root.

Every supplied actual metadata entry was checked against that policy. This
matrix is source readiness, using pure/substituted metadata controls; it is
not a fresh observation of any native path or native Root qualification.

| Resource | Supplied UID:GID / mode | Policy readiness |
| --- | --- | --- |
| Original window `window.lock` | 0:0 / 0660 | Window custodian, admitted |
| `/var/lib/acx-gpu/lifecycle.lock` | 1001:1001 / 0600 | Declared controller lifecycle, admitted |
| `/var/lib/acx-gpu/.intent-authority.json.lock` | 1001:1001 / 0660 | Declared controller authority, admitted |
| `/run/acx-write/dev/gpu-intent.json.lock` | 0:10001 / 0660 | Root/API-group intent fence, admitted |
| `/run/acx-write/dev-fir/gpu-intent.json.lock` | 0:10001 / 0660 | Root/API-group intent fence, admitted |
| `/run/acx-write/prod/gpu-intent.json.lock` | 0:10001 / 0660 | Root/API-group intent fence, admitted |
| `/run/acx-write/staging/gpu-intent.json.lock` | 0:10001 / 0660 | Root/API-group intent fence, admitted |
| `/run/acx-write/dev-auraface/gpu-intent.json.lock` | 0:10001 / 0660 | Root/API-group intent fence, admitted |
| `/var/lib/acx-gpu` directory | 1001:1001 / 0700 | Declared controller ancestor, admitted |
| `/var/lib/acx-gpu/intents` directory | 1001:1001 / 0755 | Declared controller ancestor, admitted |
| `/var/lib/acx-gpu/intents/prod` directory | 1001:1001 / 0755 | Declared controller ancestor, admitted |
| `/var/lib/acx-gpu/intent-authority.json` | 1001:1001 / 0660 | Declared controller state, admitted |
| `/var/lib/acx-gpu/intents/prod/gpu-intent.json` | 1001:1001 / 0660 | Declared controller durable state, admitted |
| `/run/acx-write/prod/gpu-intent.json` | 10001:10001 / 0660 | API publication state, admitted |
| `/var/lib/acx-gpu/deferred-stop.json` | Absent | Existing optional absence, admitted |

All eight supplied fences additionally have the required regular/single-link/
zero-byte metadata. No supplied UID/GID/mode entry remains unexplained. Remaining
unknown here: runtime ancestor metadata was not supplied, native held identities/
state-file link counts and hashes were not reobserved, and final joined C3/gate
results are pending. The unchanged current-state, original publication-proof and
UNKNOWN checks must establish those facts natively; this source cannot certify
them from supplied ownership alone.

LOUD18504 verification on these corrected bytes, actual EUID/GID1002:1002:

- `timeout 55s python3 -B .../test_window_checkpoint.py`: unchanged 12 methods
  passed in 44.303 seconds, exit0. The controller refusal matrix now completes,
  including authority-fence-owner10001:10001, authority-state-owner10001:10001
  and store0770, with unchanged damaged metadata, custody and state.
- `timeout 55s python3 -B .../test_resume_start.py`: unchanged 8 methods
  passed in 1.465 seconds, exit0.
- Both helpers parse; the seven-script manifest was regenerated from actual
  bytes. `git diff --check` passed. Source changes are confined to
  `_resource_roles`, `_checkpoint_fence` and `checkpoint_view`; Production
  controller1001 construction, all tests and fixture drivers remain unchanged.

These are UNIT_ONLY results with the existing explicit stat-role substitution
on private inodes. No privileged fixture, network, dependency/model operation,
live path metadata change, authority reset, new window, cap increase or sealed
stage edit was performed. Parent must run actual Root C3 and the final exact
source XHIGH gate; these unit passes are not Root Green.

Historical `9def5c1` source controls, executed as actual UID1002 with
`timeout 55s` (these results do not qualify the current joined source):

- `python3 -B .../test_window_checkpoint.py`: 9 methods passed, 37.384 seconds.
- `python3 -B .../test_resume_start.py`: 7 methods passed, 1.353 seconds.
- `python3 -B /tmp/a3_controller_role_checks.py .../owner-resume-start-r4`:
  7 private methods passed, 6.614 seconds. This temporary, uncommitted control
  file has SHA256 `9a04de69be130b1f38f66240dafe02e1bc165d448efabd293391e40fcfdf709d`.
  It covers typed/default/positional construction, fixed Production kwargs,
  all supplied fence and state rows using explicit metadata substitution,
  wrong owner/group/mode/link/type/size/path refusals, state identity changes,
  and mutation-free fence/state refusal before checkpoint directory creation.
  A real current-EUID/controller lifecycle0600 fixture archives 33 operations
  with original bytes/inodes and current publications preserved. In-memory
  uniform0660 and omitted-controller-role defects make passing controls refuse.
- Both helpers parse. AST comparison to base `23a603a` confirms every other
  custody definition/constant is identical, and all CLI code apart from its
  fixed `Paths` construction is identical. All seven manifest entries were
  regenerated from actual script bytes.

No controller, fixture driver, selected limits or fixed 180-second Root proof
deadline was edited. Root C3 must consume these exact named kwargs and reproduce
all supplied roles in new proven-private overlays. Its controller emulator
executes as Root; kernel UID1001 metadata provisioning does not qualify actual
controller1001 credential execution. No native Root Green is claimed from
these UID1002 units. Keep the original window, 33 bound, current predecessor and all
prior archive proofs. A new protected stage must bind the ORIGINAL old stage
and window through the unchanged predecessor receipt contract below.

## Fixed fifth-environment correction (HIGH19197, preserved)

`owner-custody.py` now uses exactly
`ENVS=('dev','dev-fir','prod','staging','dev-auraface')`; fence order is unchanged.
Checkpoint fences all five intent producers and accepts these five environment
directories even when the fifth intent is absent. START/STOP additionally fence
and require all five current loads. Four-load inventories, a missing fifth load,
and nonzero/stale fifth-load evidence refuse. Foreign environment checks remain;
the directory bound is five, the ordinary operation cap stays 32, and checkpoint
alone remains bounded at 33. AUTO/checkpoint still do not read loads.

Historical prerequisite (coordinator now reports completed with peer ACK):
before checkpoint, the Root coordinator had to provision exactly the missing
`/run/acx-write/dev-auraface/gpu-intent.json.lock` as ordinary fixed-topology
setup from its Root0700 stage: exclusive creation (`O_EXCL`), no-follow open,
UID0/GID10001, mode0660. Preserve every existing persistent fence. The archive
function still requires existing fences and does not provision this file. Do
not repeat provisioning or alter an existing fence to fit fixture assumptions.
No authority, publication, load or service configuration change is authorized.
Use a new stage containing the exact seven script pins plus the protected old
procedure receipt. The sealed `991aa72e...` four-environment stage is immutable
and used only to reproduce old history; the full prior 993-file `61347fe1...`
custody evidence remains unchanged. Continue the same window and predecessor.

## Protected procedure continuation

The separately qualified new root0700 stage contains its exact seven scripts,
root0400 single-link `approved-scripts.json`, and, only for continuing a different
sealed procedure, root0400 single-link `procedure-predecessor.json`. All ancestry
and files are opened without following links. The new receipt has **exactly**
these fields; no extra proof fields were added to agreed contract v1:

```json
{
  "schema": "acx-owner-procedure-predecessor/v1",
  "window_id": "EXACT_ORIGINAL_WINDOW_UUID",
  "window_path": "/EXACT/ORIGINAL/PROTECTED/WINDOW",
  "procedure": "/EXACT/ORIGINAL/SEALED/STAGE",
  "manifest_sha256": "SHA256_OF_ORIGINAL_approved-scripts.json_BYTES",
  "owner_window_sha256": "SHA256_OF_ORIGINAL_owner-window.py_BYTES",
  "owner_custody_sha256": "SHA256_OF_ORIGINAL_owner-custody.py_BYTES"
}
```

Root obtains all values from held, protected original window/stage files.
Placeholder values above are documentation, never usable proof. The original
stage must still exist: root0700, exactly seven scripts plus its manifest, all
root0400/single-link. `validate_procedure(wfd, window, new_stage)` verifies the
sealed current window, exact UUID/path/procedure bindings, original manifest
digest, all seven original script digests and both explicit helper digests.
Held descriptors and before/after/named file identities verify the bytes read;
the original stage's held identity must still match its pathname. Old code is
never imported or executed by this validation.

The fixed receipt basename in the new stage is the only adoption seam. There is
no receipt path, predecessor path override, bypass flag or caller-supplied hash
argument. An absent receipt retains the exact original procedure equality guard.
A present receipt on an already matching stage is extraneous and refuses. Wrong
ownership, modes, links, fields, bindings, hashes or stage inventory refuse.
The sealed window still names its original procedure; the actor remains
`ubuntu:QWEN-OWNER-ADMISSION:capacity-only:ORIGINAL_WINDOW_UUID`.

## Checkpoint contract and durability

Library: `checkpoint(wfd, paths, window) -> receipt`. Public CLI in the qualified
stage: `checkpoint W EXACT_WINDOW_ID`. Success stdout is one JSON receipt with
schema `acx-owner-window-checkpoint-receipt/v1`, `checkpoint_id`, `window_id`,
`window_path`, `previous`, `retained`, `archived`, `manifest_sha256`, and
`durable: true`. This is archive durability evidence, not publication or Root
qualification evidence. Errors fail with no success receipt.

Only checkpoint opens up to 33 operation directories; encountering a 34th name
refuses before history mutation. Ordinary `known_candidates` remains capped at
32. Inventory traversal stops at the bound. Each operation permits only the ten
original supported filenames; `unknown.json`, pending/unrecognized outcomes,
missing proof, unsafe ownership/mode/link, or oversized files refuse. Receipts
must be owner0400, logs owner0600, directories owner0700, files single-link and
at most 1 MiB. Native boot/PID/start identities must prove both guardian and any
writer absent or replaced; an existing matching process, including a zombie,
refuses. A writer requires its original identity and native reaped wait receipt.

The helper takes the window fence, lifecycle fence, five intent fences, then
authority fence, exactly as the existing AUTO guardian. It requires existing
safe fences and uses one 15-second lock deadline. No checkpoint subprocess is
created. Client operation creation now also takes the window fence, preventing
a new operation from racing a checkpoint inventory. Existing publication,
sequence, load and first-use guards are unchanged.

Current authority, runtime/durable publications and deferred STOP are read from
the fixed topology with bounded inventory, held no-follow ancestry and file
owner/mode/link/hash/identity checks. Only the paired roles described above
are accepted; no foreign environment or world-writable source
is adopted. The unchanged `guard(..., 'auto')` validates actual state. Every
persisted publication must have complete original published operation proof.
The highest proven published operation must still be persisted. Every current
publication, that predecessor, and any proven deferred STOP candidate remain in
`ops/` with all their original files. Only other completed operations move.
Checkpoint does not read loads or allocate sequences or invoke a writer.

For each transaction, window-owned `checkpoints/UUID/manifest.json` is sealed
before any move. It records the original window identity and window file proof,
actual state and resource file proofs, the predecessor/partition, and every
operation directory identity plus every original file's identity/mode/size/SHA.
Files and directories are fsynced. Sealed `checkpoints/pending.json` binds the
transaction UUID to the exact manifest hash before any history rename.

All bytes and both possible directory locations are verified again before the
first move or recovery move. Each archive rename into
`checkpoints/UUID/ops/OP_UUID` preserves original file/directory inodes and bytes;
both source and destination directories are fsynced after each rename. A sealed
`complete.json` contains the returned receipt. All affected directories are
fsynced before removing and fsyncing the pending pointer. No operation is deleted
or copied over another directory. Completed checkpoint archives are retained;
later checkpoints do not scan or discard earlier archives.

Any pending pointer blocks ordinary operations and reconciliation. Only another
explicit `checkpoint W EXACT_WINDOW_ID` can resume that same manifest. It must
prove the exact complete split inventory, all original bytes/identities, dead
processes and unchanged actual resource state before finishing remaining moves.
Unexpected/missing/duplicate directories or changed state refuse without further
moves. UNKNOWN operation receipts are never retried, even if another terminal
receipt appears later. Partial/malformed manifest/pointer/completion writes
remain fail-closed for Root investigation; the helper never guesses or repairs
them. A crash before installing the pending pointer can leave an unused sealed
transaction directory, but no operation has moved. A crash after durable
completion/removing pending may lose stdout; retained operations and sealed
completion evidence remain valid. Do not automatically retry a timed-out CLI.

## Historical qualification boundary (prior fifth-environment source)

All executed controls here were author-owned temporary fixtures or explicit
dependency-substituted unit controls. No sudo, actual writer, namespace setup,
mount, Docker, network, service, GPU or live procedure command was run.

Source controls passed syntax, ordinary unchanged guard/guardian refusal cases,
33-operation compaction retaining two current publications, actual split-directory
recovery after injected rename interruption, UNKNOWN/34th-name/foreign/live
refusals, and tampered recovery refusal. Predecessor schema/hash/window controls
passed with root ownership explicitly substituted for author-owned fixtures;
the real root ownership policy refused the author-owned stage. These controls
are not native Root Green. Final controls also passed exact-ID JSON CLI dispatch
(explicit custody substitution), null-publication/missing-fence refusals with
unchanged operation inventory, and root-group authority acceptance. An isolated
in-memory mutation raising the ordinary cap from 32 to 33 made the cap control
fail, demonstrating Green-to-Red sensitivity without editing source or tests.
For this fifth-environment delta, the unchanged `test_window_checkpoint.py`
passed all seven methods (36.914 seconds). Twenty-seven private pure/source
controls passed, including exact fence ordering, four-to-five load admission,
fifth nonzero/stale/missing load refusals, five-directory acceptance with an
absent fifth intent, and fifth/foreign publication refusals. Private filesystem
controls also refused each of the five missing intent fences without creating
it or changing history, then retained an owned fifth publication with the same
window/predecessor, original operation bytes/inodes and unchanged resource bytes.
These ran as UID1002 and are source bounds, not native Root Green. The unchanged
`test_resume_start.py` ran seven methods: five passed, while its hardcoded
four-load fixtures caused one error and five failed subtests across the other
two methods (`unknown required load inventory`). Tests and pinned inputs were
not edited. Earlier four-environment Root/gate results do not qualify this delta.

Root must qualify the final exact seven-script manifest in actual isolated tmpfs
mounts/private proc with the complete pinned real writer/load/controller source,
real UID10001 writer and native process identities. Include the supplied native
33-operation Red, unchanged ordinary 32 cap, exact same-window continuation,
all-current-publication preservation, interruption/recovery, malformed/foreign/
newer/unreaped/live/UNKNOWN refusals, and prove a passing control can fail under
the corresponding defect. Preserve namespace and custody on UNKNOWN. The old
Root fixture plan is preserved, not silently repinned or presented as current
checkpoint qualification. Coordinator joins disjoint source commits, runs native
Root qualification, then the one independent gate. No live adoption is performed
by this source handoff.
