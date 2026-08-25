---
title: GPU lifecycle controller
boundary_owner: infrastructure
status: draft
since: GPU-01
---

# GPU lifecycle controller

Out-of-band OCI burst-GPU start/stop. Not the describe HTTP API. Decision
tuples are `(action, instance_id)` with `action` ∈ `{START, STOP}`.

## CLI

`python -m infra.oci.gpu_lifecycle --mode reap|start` (default `reap`).

`--mode start` emits START for STOPPED instances when the load snapshot has
work (`queue_depth > 0` or `in_flight > 0`). `--mode reap` remains the idle
STOP path.

## Actuators

`OciCliStartActuator` / `OciCliStopActuator` are twins: same `oci compute
instance action` argv except `--action START|STOP` and `--wait-for-state
RUNNING|STOPPED`.

Auth: `~/.oci/config` or `--oci-auth` / `OCI_CLI_AUTH`.
