# GPUOPS-1 lane L1 — lifecycle honours operator intent

Branch `feature/gpuops-1-lifecycle`, worktree `context-alt-text-monorepo-gpuops-1-lifecycle`. Owns `infra/oci/gpu_lifecycle/**` and `docs/workbay/contracts/gpu-lifecycle.md`.

## Goal

`python -m infra.oci.gpu_lifecycle --mode start|reap` gains `--intent-dir <dir>` and honours the operator intent file from contract C1 with the exact semantics in the C1 table, while every existing automatic behaviour stays identical when no intent is present.

## Current anchors

- `infra/oci/gpu_lifecycle/reaper.py`: argparse from ~:1605 (`--load-dir`, `--gpu-state-json`, `--running-since-path`, `--max-lease-seconds`, `--idle-seconds`, `--probe-oci`), `main()` ~:1790, actuators `OciCliStartActuator` ~:382 / `OciCliStopActuator` ~:330.
- `infra/oci/gpu_lifecycle/controller.py`: `GpuLifecycleController.start_needed_instances` :68, `reap_idle_instances` :101, `lease_expired_instances` :117, `fence_stop_actions` :151, `fallback_on_boot_failure` :170; `JobLoadSnapshot.has_work` :58.
- `infra/oci/gpu_lifecycle/state_snapshot.py`: `write_gpu_state_snapshot` :173 writes `state`, `since`, `written_at`; readers already tolerate unknown keys (verify in `test_state_snapshot_contract.py`).
- `infra/oci/gpu_lifecycle/load_source.py`: aggregate reader over `/run/acx-write/*/describe-load.json` — copy its shape for the intent aggregate.

## Deliverables

1. `infra/oci/gpu_lifecycle/intent.py`: `IntentAction(StrEnum)` (`start`, `stop`, `auto`), frozen `OperatorIntent` dataclass, `read_effective_intent(intent_dir, now) -> EffectiveIntent`. Aggregate `<intent_dir>/*/gpu-intent.json`; newest unexpired `requested_at` wins, tie → `stop`; missing dir/file, expired, `schema_version != 1`, bad JSON or bad fields → `auto` with a WARNING log naming the file and the parse error (AGT-10). Defensive cap: `expires_at` more than 7200 s after `requested_at` is clamped to 7200 s.
2. Controller semantics (C1 table): `start` allows START with no work and suppresses idle STOP but never lease-cap STOP or boot-failure fallback; `stop` suppresses START and stops only when `has_work` is false, otherwise publishes `intent_status = blocked_work_in_flight`; START for a given intent is honoured at most once per `nonce` (persist `honoured_nonce` in the running-since lease record, which the lifecycle already owns).
3. `state_snapshot.py` additive fields from C2: `intent`, `intent_expires_at`, `intent_status`, `honoured_nonce`, `lease_expires_at`, `instance_running_since`, `last_transition_reason`. Update the contract tests so absence of intent yields `intent = auto`, `intent_status = none`.
4. `reaper.py`: `--intent-dir` (default `None` = intent disabled, pure legacy behaviour) wired into both modes; `last_transition_reason` set on every actuation (`work`, `operator`, `idle`, `lease_cap`, `start_failed`).
5. `docs/workbay/contracts/gpu-lifecycle.md`: new "Operator intent" section documenting C1 and C2 verbatim from the task plan, plus the precedence rule and clamp.

## Tests (`python3 -m pytest infra/oci/gpu_lifecycle/tests -q -p no:cacheprovider`)

- `tests/test_intent.py`: parse, expiry, precedence, tie, malformed → auto with warning, clamp.
- `tests/test_intent_controller.py`: each row of the C1 table as a separate test; lease cap wins over `start`; `stop` with work is deferred and re-evaluated; nonce honoured once across two cycles.
- Existing tests unchanged and green (TEST-03). Add a regression asserting that with `--intent-dir` unset, the snapshot has `intent = auto` and behaviour equals the pre-change fixtures.

## Non-goals

Installer or systemd changes (L2), the service writer (L3), anything under `scripts/deploy/`.
