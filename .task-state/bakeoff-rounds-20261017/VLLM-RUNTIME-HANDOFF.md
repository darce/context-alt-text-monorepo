# Qwen3-VL BF16 maintenance helper

This standalone stdlib helper implements only the already selected
Qwen3-VL-8B-Instruct BF16/vLLM v0.11.0 arm. The bakeoff client is unchanged.
Source tests use fake command runners, fake sockets, and private temporary files;
no native Docker, GPU, systemd, model download, or installation was performed.
The coordinator owns independent review, transfer, native activation, and the
outer public owner-window contract. A pending START is not an honoured lease.

## Public contract

The coordinator chooses one canonical lowercase hyphenated UUID, derives its
32 lowercase hexadecimal digits, and transfers these **three exact files** into
`/run/bakeoff-vllm-<32hex>` before invoking the helper:

- `gpu_vllm_maintenance.py`: the exact reviewed standalone source, at most 256 KiB.
- `spec.json`: the sealed public spec below, at most 16 KiB.
- `api-key`: a private ASCII token of 32–256 characters from `[A-Za-z0-9_-]`,
  without whitespace or newline. Supply it privately; never place its value in
  argv, command transcripts, receipts, fixtures, or this document.

The existing root must be an actual UID 0/GID 0 directory, mode 0700, with no
symlinks in its path. All three files must be UID 0/GID 0 regular single-link
files, mode 0400; no other entries are accepted for prepare. The helper does not
create/adopt a launch root. It refuses a second prepare, including a root with
only an old lock from a failed preflight. Use a new operation/root for a new
attempt; retain the old evidence. There is no reset, resume, lease extension,
custom command, image, path, runner, or runtime-flag option in the CLI.

Example **public** spec (replace the UUID consistently):

```json
{
  "version": 1,
  "operation": "12345678-1234-4234-8234-123456789abc",
  "original_network_mode": "host",
  "original_port_bindings": {}
}
```

The last two fields must equal the actual original Docker inspect
`HostConfig.NetworkMode` and `HostConfig.PortBindings`. Host mode accepts `{}` or
`null` according to the actual inspect producer. A bridge incumbent is accepted
only with exactly one `8000/tcp` binding to host port `8000`, on wildcard or
loopback; the exact binding is captured and rechecked. The candidate always uses
host networking and port 8000. Unknown fields, duplicate JSON keys, alternate
model paths, and caller flags are refused. Pins and all fourteen asset sizes and
SHA256s are embedded in source, outside spec control.

Invoke as root using the transferred file, with Python isolation:

```text
/usr/bin/python3 -I -B /run/bakeoff-vllm-<32hex>/gpu_vllm_maintenance.py prepare --operation <UUID> --spec /run/bakeoff-vllm-<32hex>/spec.json
/usr/bin/python3 -I -B /run/bakeoff-vllm-<32hex>/gpu_vllm_maintenance.py restore --operation <UUID> --spec /run/bakeoff-vllm-<32hex>/spec.json
```

Success emits one redacted JSON receipt. Failure emits one safe JSON diagnostic
and exits nonzero; no command stdout/stderr, raw inspect, environment, HTTP body,
headers, or private key is reported. On startup/readiness failure the diagnostic
preserves the safe original failure reason and states whether restoration was
verified or remains unknown. Unexpected exception details are suppressed.

## Identity and preparation

These are distinct immutable identities:

| Identity | Pin |
| --- | --- |
| Original Qwen image config ID | `sha256:fc26b60b30836e5a12fdb28823a3d4bda984c9386a4b04200c78e5a5150067fb` |
| Original selected Config hash | `60b918fa38f308933e08bbbcf881d66336c2567b786764a095430c7313710849` |
| Original running binary hash | `59a74a6528e0dcedfb89e6a3df41b8dbd593a2c3689096a2d030ad1c67ffe4d0` |
| Candidate immutable reference | `vllm/vllm-openai@sha256:d8d39b59e909d2378ac4feeb191f7e7b6f1342477dc66b7c47cec89e9985ad8a` |
| Candidate pinned amd64 manifest; installed containerd-backed Docker `Id` | `sha256:d8d39b59e909d2378ac4feeb191f7e7b6f1342477dc66b7c47cec89e9985ad8a` |
| Candidate legacy Docker config `Id` (distinct provenance) | `sha256:ee2917e260bb5037ca93944bfcb845a8f867674c63de2284d28c541f1eaf3f08` |

The original hash exactly follows the supplied producer: SHA256 of ordinary
`json.dumps(..., sort_keys=True)` for selected `Config` fields `Image`, `Cmd`,
`Entrypoint`, `Env`, `WorkingDir`, `User`. Environment values participate only in
the hash; they are never persisted or printed. Original image, binary, running
state, AutoRemove lifecycle, exact route, and enabled/active
`acx-gpu-vlm.service` are checked before stop. The coordinator has independently
hashed the original weights for this residency. The helper captures and later
compares actual path/bytes/inode/mtime_ns for exactly:

```text
/opt/acx-gpu/models/qwen3-vl-30b-a3b-instruct-q4.gguf
/opt/acx-gpu/models/qwen3-vl-30b-a3b-instruct-mmproj.gguf
```

Before stopping anything it inspects the candidate immutable image reference and
requires its actual `Id` to be exactly one of those two candidate identities and
`RepoDigests` to equal the singleton pinned reference above. All other IDs or
digests, including additional digests, are refused. The actual observed `Id` is
sealed in `before.json` and the prepared receipt; every candidate check, including
a fresh restore process, requires that residency's sealed ID. The other known
ID is not an interchangeable container identity. It also verifies exactly
one NVIDIA A10, at least 8 host CPUs and 64 GiB available memory; and hashes all
14 pinned assets from the supplied download spec. The only candidate model path
is:

```text
/root/bakeoff-owned-cache/qwen3-vl-8b-0c351dd01ed87e9c1b53cbc748cba10e6187ff3b
```

Model files cannot be symlinks or hardlinks; model paths must be root owned and
not writable by group/other. The model directory and **every ancestor through
`/`** must pass the unchanged ownership, mode and symlink guards. Native R23
refused the previous `/opt/acx-gpu/bakeoff-owned-cache` location because
`/opt/acx-gpu` was UID 1001/GID 1001, mode 0755, despite the owned leaf and cache
parent both being root/root, mode 0700. The refusal occurred before `before.json`,
original stop or candidate launch; the original Qwen/config remained unchanged.

The coordinator owns relocation of **only the owned model leaf** by atomic
same-device rename (captured device 2049) into the private cache parent. `/root`
and `/root/bakeoff-owned-cache` must be root/root, mode 0700. Preserve all 14
files' bytes, SHA256s and inodes; do not copy weights or change ownership of the
shared `/opt/acx-gpu` ancestor. This source change performs no cache mutation.
Retain the failed R23 root, key proof and full capture, including its lock and
three initial files. The coordinator owns exact source promotion, independent
XHIGH review and fresh native activation under a new UUID and owner window;
the failed operation is not reused and no active clock is extended.

Nothing is fetched or installed. Neither an existing candidate container nor an
existing candidate service is adopted.
Docker absence requires return code 1 and, after the existing outer whitespace
trim, exactly `Error: No such object: <requested-name>`,
`Error: No such container: <requested-name>`, or the installed CLI's observed
`error: no such object: <requested-name>`. The full requested name must match.
Other return codes, name prefixes/suffixes, daemon/permission errors, and
unfamiliar messages are refused; stdout `[]` alone does not establish absence.

`before.json` contains only safe immutable operation, identity, labels, original
weight stats, route, config/binary hashes, enabled service, and fixed-clock
fields. It is published with O_EXCL/O_NOFOLLOW, mode 0400, file fsync and directory
fsync **before** stopping the original service. Existing before/receipt data is
never overwritten. A partial write fails closed and retains evidence.

The original stop and its postcondition reads share a finite 110-second phase,
covering the native unit's `TimeoutStopUSec=1min 30s`. Before any candidate launch,
`systemctl show` must succeed and report `ActiveState=inactive` or `failed`,
`MainPID=0`, `ControlGroup=` and `Job=`. Every field must be present. Docker must
then report literal exact-name absence for `acx-gpu-vlm` under the same strict
absence contract above. A nonzero stop exit is accepted only with all these
postconditions. A timeout, active/deactivating state, pending job, live PID,
nonempty group, missing field, materialized container or unknown absence refuses
launch and retains the existing restoration path. No `reset-failed`, start-rate
limit reset, or unit configuration change is performed.

## Candidate and automatic restore

The fixed name is `workbay-bakeoff-vllm-<UUID>`; its system service adds `.service`.
Labels are `workbay.owner=Bakeoff` and `workbay.operation=<UUID>`. It uses `--rm`,
`--pull=never`, all GPUs on the proven one-A10 host, host network/port 8000,
8 CPUs, 64 GiB memory with no extra swap, and 8 GiB shared memory. The exact
model directory mounts read-only at `/models`. Only the owned root's `cache`
is mounted at `/root/.cache`; HF, Transformers, XDG, CUDA and vLLM cache paths
are explicitly directed there. No shared HF cache is written.

The fixed vLLM arguments select `/models` for model/tokenizer,
`Qwen/Qwen3-VL-8B-Instruct`, bfloat16, context 8192, one sequence, GPU memory
utilization 0.9, eager execution, one image, and processor `max_pixels=1572864`.
The original preprocessor has patch size 16 and merge size 2; this distinct vLLM
pixel condition makes no claim of renderer equality with llama.
`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, and `VLLM_NO_USAGE_STATS=1` are fixed.
The private file is read only by the helper; the value travels in subprocess
environment `VLLM_API_KEY`, through systemd's name-only `--setenv=VLLM_API_KEY`
and Docker's name-only `--env VLLM_API_KEY`. Neither argv contains its value.

A root-owned native transient service controls the attached Docker CLI. Its
control limits are CPUQuota=25%, MemoryMax=256 MiB, RuntimeMaxSec=1500,
TimeoutStopSec=120, Restart=no. ExecStopPost calls this exact transferred helper's
restore CLI with the same operation/spec. The runtime clock is fixed before
start; no helper operation updates or extends the service timer. This service
is a bounded maintenance backstop, not an outer owner-window grant.

After the stop phase, prepare fixes a separate 150-second readiness deadline
immediately before candidate launch, with HTTP 200 on `/health` and `/v1/models` containing exactly the expected
served ID. It then rechecks the same running, correctly labelled candidate.
The root lock is released during HTTP polling so ExecStopPost can restore after
an early candidate exit. A failed start/stop/readiness path attempts restore;
foreign candidate identities are refused untouched, including in failure cleanup.

Restore serializes on an owned nonblocking-flock loop with a finite deadline.
It validates the sealed before record, verifies the exact candidate name,
labels/operation/image ID before any stop, stops only that container ID, and
waits for AutoRemove absence. Before starting the original, it also verifies the
Docker CLI has exited: the unit must be absent, inactive/failed with MainPID=0,
or already in ExecStopPost with MainPID=0. A still-pending launcher fails closed
after a bounded wait rather than starting the original underneath a late
candidate launch. It starts the unchanged enabled original service,
allows at most 90 seconds of readiness within a 110-second total restore budget,
and rechecks exact original image/config/route/weight stats/binary and HTTP 200
`/health`. All command/socket/poll waits are finite. The 110-second budget leaves
margin within systemd's 120-second stop timeout. Unknown state or drift retains
before/key/evidence and produces no restored claim.

Only after verification does restore remove its own private `api-key`, fsync the
directory, and seal `restored.json` with exclusive creation. If publishing fails
after unlink, a retry still performs full verification before publishing.
Subsequent restore calls return the same sealed historical receipt without
restarting the original or touching a candidate. A historical receipt is not a
new assertion of ongoing residency. No other cache, service configuration, PID,
sandbox, OCI/controller/DB/registry object, driver or installation is changed.

## Validation and coordinator boundary

Run only the scoped stdlib tests from this directory:

```text
python -B test_gpu_vllm_maintenance.py
python -B test_gpu_native_contracts.py
python -B test_vllm_cache_ancestry.py
```

The in-process Runtime/FilePolicy seams permit fake execution and current-UID
private directories; the public CLI exposes none of those overrides. Tests
exercise distinct incumbent/candidate images, actual producer-shaped inspect
objects, foreign identities, image/config/route/weights/binary drift, startup
failure and restore uncertainty, repeated restore, secret redaction, strict
files/specs, asset hashing, fixed resource/command contract, AutoRemove delay,
automatic restore during readiness, pending-launch refusal, and finite
command/HTTP clocks. The final scoped run passes 30 tests (the existing 24 plus
six absence regressions).

For VLLM-NATIVE-ABSENCE-01 (MCP19207), the standalone regression copies the literal
return code 1, stdout `[]\n`, stderr
`error: no such object: wb-bake-minicpm45-058c78d4a8ad480a8c787b870e805f8e\n`,
and requested name from `references/actual-docker-producer.json`, retaining both
trailing newlines. The producer was read before constructing the fixture
([GRPH-33](../../references/canon-matched.md#grph-33)). The original 24 tests
passed; the literal regression then failed on unchanged production source with
`container absence unknown`. Adding only the exact lowercase allowlist entry
makes it pass ([DBG-11](../../references/canon-matched.md#dbg-11)). Additional
tests preserve both uppercase variants, reject other return codes and inexact
names/messages, verify refusal before any stop/launch, and exercise fake
prepare/restore using lowercase absence throughout. This verifies the captured
CLI response contract, not native execution.

The current native-contract regression first failed on unchanged R2 source:
the literal `references/actual-native-producers.json` image produced `candidate
image pin drift`; a virtual 90-second native stop exceeded the original
30-second timeout in the helper and all three extracted setup programs. After
the change, the existing 30 tests and nine new stdlib tests complete successfully.
The new tests execute the actual recipe AST stop/start/readiness block and its
recovery handler against `subprocess.CompletedProcess` producers, virtual clocks,
fake HTTP responses and private temporary directories. They cover terminal
failed/inactive states despite a nonzero stop exit, the complete refusal matrix,
110-second stop exhaustion, slow HTTP/inspect work within readiness 150, and
executed setup scope/outer bounds 540/570. The capture omits `ControlGroup`;
tests explicitly supply an empty group for the positive scenario and refuse a
missing group. This is a prospective source contract, not proof of native
quiescence.

Only the unclaimed R20C/R21/R22 recipes are changed. Their standalone transferred
setup strings implement the same stop postconditions and readiness 150, with
setup scope `RuntimeMaxSec=540` and outer call 570. Model runtime 1500, client
1200, the coordinator's intent 1800, and all model/prompt/cohort/seed/sampling
inputs stay fixed. R20C is prospective and contains no asset-prefetch task;
already verified assets are reused. Each recipe retains exactly one
`__PREVIOUS_AUTO__` placeholder for the coordinator to fill from the actual prior
full settlement. Setup quiescence is still required before cleanup. No active
R20/R20B script or publication is edited.

The export baseline is scoped R2 native8a974 plus the unclaimed coordinator
recipes from canonical8b9829d6; it is not a whole-tree equivalence claim. The
supplied verified ONNX semantic reinjection (MCP19207/18561/18562) and literal
native producer are the evidence inputs. R20's GSQ load and R20B's stop timeout
do not establish GSQ inference or a model defect. The original later returned
HTTP 200 with unchanged config/binary/weights; report the actual native response
on activation rather than attributing failure to the last warning.

The Pinedo/Sinnen physical-host separation remains: the backend Root scope
controls the recipe/client, while the GPU guest's setup scope, model service and
restore process consume their separately bounded CPU/memory and exclusive GPU
residency. The real resource DAG requires prior full settlement before START,
actual host identity and sealed before evidence before stopping the incumbent,
original quiescence before candidate launch, authenticated candidate identity
before client inference, and client reaping plus setup quiescence before cleanup.
Verified original restoration precedes physical lease closure and withdrawal.
These resource-exclusion and evidence dependencies are unchanged; there is no
new CLI surface or UX map.

Native vLLM/image/GPU/systemd compatibility remains untested by this source turn.
If v0.11.0 rejects the fixed arguments, lacks native Qwen3-VL compatibility, or
fails readiness, report the native failure; do not substitute another runtime,
install drivers, or patch the original service. The coordinator must verify the
actual `/v1/models` response **and the completion response's model** downstream;
automatic Qwen restoration must never be relabelled as a candidate response.
The supplied [canon v0.26.2](https://github.com/darce/heuristics-canon) excerpts
for [RES-02](../../references/canon-matched.md#res-02) deadlines,
[DBG-11](../../references/canon-matched.md#dbg-11) causal failure cases,
[GRPH-32](../../references/canon-matched.md#grph-32) named before fields, and
[GRPH-33](../../references/canon-matched.md#grph-33) sealed input/output contracts
informed these boundaries.

For the R23 ancestry regression, the supplied
`references/actual-native-cache-ancestry.json` was read before constructing the
stat fixture (GRPH-33 actual producer). The new six-test suite executes the real
`Runtime.validate_assets` with the default root policy, real `Path` ancestry and
predicates, and `os.stat_result` producers, including directory type bits in
`st_mode`. `Path.stat` supplies metadata and per-asset reads are spied; test-only
`MODEL_DIR` replacement contrasts the old and prospective paths. The old fixed
location first raised the captured ownership/mode refusal; the
prospective private location passed against the same unchanged guard (DBG-11
cause). After changing only `MODEL_DIR`, the fixed-location case also passes and
forwards exactly all 14 original size/SHA256 pins to `validate_asset`. Non-root
ownership, group/other write permission and symlinks at every directory remain
refused before any asset call. This is a source regression, not native cache
verification or a new residency claim. Existing finite stop, readiness, restore
and service bounds remain unchanged (RES-02 finite bounds).

In this scoped checkout the 30 existing helper tests and six ancestry tests
pass. The existing nine-test native-contract suite was attempted but cannot
import because `references/actual-native-producers.json` is absent; its
`*.remote.py` recipe inputs are also absent. Those tests were not changed and
their missing producer/recipe inputs were not synthesized. The earlier nine-test
result above describes the prior source turn, not this checkout's validation.
