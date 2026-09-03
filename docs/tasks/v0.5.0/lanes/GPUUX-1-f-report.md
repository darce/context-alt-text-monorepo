# GPUUX-1 lane F report

## Outcome

Implemented the lifecycle snapshot producer and wired it to the end of every
reap and start cycle. The writer publishes exactly `state` and `written_at`,
uses an exhaustive OCI lifecycle-state mapping, refuses `unknown`, creates the
parent directory when needed, and atomically replaces the target from a
same-directory temporary file. Snapshot failures are logged at WARNING and do
not change cycle results.

Both installed systemd services now pass
`--gpu-state-json /run/acx/gpu-state.json`. When no flag is supplied, the
writer honors `ACX_GPU_STATE_PATH` and defaults to that same path.

## TDD evidence

RED was committed first as `ef74a1a76a9166019e27bf0665257fede6e04552`.
The first failing line was:

```text
E   ModuleNotFoundError: No module named 'infra.oci.gpu_lifecycle.state_snapshot'
```

The focused GREEN summary was:

```text
15 passed in 0.11s
```

The socket-free full lane summary was:

```text
65 passed, 2 deselected in 0.17s
```

TEST-15 mutation: the producer was deliberately changed to serialize
`"state": "unknown"` for every valid input. The round-trip test failed at the
exact payload assertion with:

```text
E         {'state': 'unknown'} != {'state': 'stopped'}
```

All five parametrized states failed. The mutation was then restored before
the GREEN runs and was never committed.

## Verification

- `bash -n scripts/deploy/gpu-lifecycle-install.sh` passed.
- `/usr/bin/python3 -m compileall -q infra/oci/gpu_lifecycle` passed.
- The full pytest suite reached 65 passing tests when the two localhost-server
  tests were deselected. Running all tests produced 64 passes and two failures
  because this managed sandbox rejects `socket.socket()` with
  `PermissionError: [Errno 1] Operation not permitted`.
- The prescribed `uv run` command could not acquire its cache lock because
  `/home/gate/.cache/uv` is read-only in this sandbox. The selected lane venv
  has no pytest installed, so the equivalent tests were run with the ambient
  Python 3.12 pytest from the required application directory.

## Files changed

- `infra/oci/gpu_lifecycle/state_snapshot.py`
- `infra/oci/gpu_lifecycle/reaper.py`
- `infra/oci/gpu_lifecycle/tests/test_state_snapshot.py`
- `scripts/deploy/gpu-lifecycle-install.sh`

Implementation HEAD before this report commit:
`3d20ff75510aaea2f4a3ac245d3cd7befe74736f`.

## Open threads and mapping judgement

There are no known implementation blockers. A running OCI instance maps to
`warming` unless a previous valid producer snapshot recorded a non-stopped
state; reap/start cycles without readiness evidence preserve that state while
refreshing `written_at`. This avoids demoting `ready` on the next timer tick.
`STOPPING` maps conservatively to `stopped`, while unrecognized/`UNKNOWN` OCI
states and fallback outcomes map to `degraded`.

The two dependency briefs disagreed on payload shape. This implementation
follows the newer brief and the merged reader contract by emitting exactly the
two keys the reader consumes, rather than the older draft's `instance_id`,
`reason`, and `since` fields.
