# Same-window checkpoint source handoff

Source only. Native Root qualification and the coordinator's one independent
SolXHIGH gate remain pending. No live window, old sealed procedure, installed
controller, authority, publication, load, service, model or provider was changed.
Canonical source origin is `45ab1fc4e1716cbffd32b80802831b83f0ce94d2`, recorded
in `context/source-origin.json`; the native export deliberately strips history.
Baseline source receipts, evidence pins and `root_fixture_plan.py` are historical
inputs and remain unchanged. Their old stage digests do not qualify this source.
The regenerated seven-script manifest SHA256 is
`20877883ec65bf7ff992510946db5d36955849d9dfd15ac0e3715b2825d577c9`.

The supplied native evidence identifies the 33rd terminal refused operation
(`a3711ad0`), full external history custody (`61347fe1`), and latest proven
published AUTO `2216f4f2-a79c-46d5-9f5b-cc451dc85f59`. These are coordinator
inputs, not authority issued by this patch. Qualification must establish the
actual current persisted predecessor using original native receipts and guards.
Never substitute a new window, reset authority, delete operations, raise the
ordinary cap, manufacture ACK/source proof, or modify the original sealed stage.

## Fixed fifth-environment correction (HIGH19197)

`owner-custody.py` now uses exactly
`ENVS=('dev','dev-fir','prod','staging','dev-auraface')`; Paths is unchanged.
Checkpoint fences all five intent producers and accepts these five environment
directories even when the fifth intent is absent. START/STOP additionally fence
and require all five current loads. Four-load inventories, a missing fifth load,
and nonzero/stale fifth-load evidence refuse. Foreign environment checks remain;
the directory bound is five, the ordinary operation cap stays 32, and checkpoint
alone remains bounded at 33. AUTO/checkpoint still do not read loads.

Before checkpoint, the Root coordinator must provision exactly the missing
`/run/acx-write/dev-auraface/gpu-intent.json.lock` as ordinary fixed-topology
setup from its Root0700 stage: exclusive creation (`O_EXCL`), no-follow open,
UID0/GID10001, mode0660. Preserve every existing persistent fence. The archive
function still requires existing fences and does not provision this file.
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
owner/mode/link/hash/identity checks. Root/controller and configured writer
ownership/groups are accepted; no foreign environment or world-writable source
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

## Qualification boundary

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
