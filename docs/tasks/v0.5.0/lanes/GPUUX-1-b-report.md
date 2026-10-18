# GPUUX-1 lane B report

## Outcome

The production compose surface now passes `ACX_GPU_STATE_PATH` to the API and
bind-mounts the host snapshot directory read-only. The production env example
documents `ACX_GPU_STATE_PATH`, `ACX_GPU_STATE_STALE_SECONDS`,
`ACX_DESCRIBE_LOAD_PATH`, and `ACX_DESCRIBE_LOAD_REFRESH_SECONDS`, plus the
compose-only directory seam `ACX_GPU_SNAPSHOT_DIR`.

`scripts/deploy/check-gpu-snapshots.sh` fails closed when either snapshot is
missing, not a regular file, unreadable by the API uid, malformed, or outside
its freshness budget. It also rejects drift between the configured paths, the
paths in the lifecycle unit installer, and the API service's read-only compose
mount. The checker is covered by the local bash contract suite and that suite
is collected by `make test-scripts` / `make check-all`.

## Path-agreement seam

`.env.prod.example` is the deployment seam. Compose consumes
`ACX_GPU_SNAPSHOT_DIR` and `ACX_GPU_STATE_PATH` without declaring another
default, while the checker derives the writer paths directly from the
`--gpu-state-json` and `--load-json` flags in
`scripts/deploy/gpu-lifecycle-install.sh`. This was chosen because `.env` is
already the operator-owned input consumed by the API container, whereas
importing a Python application constant into Compose or systemd generation is
not available. The Python producer/reader defaults remain defensive code
fallbacks; the deployment checker makes drift from the installed units fatal.

## TEST-06 RED, revert, and GREEN

After the implementation was green, I deliberately changed the production
snapshot mount suffix from `:ro` to `:rw` and ran the focused command. The
literal failing output, including the assertion, was:

```text
PASS: checker has valid bash syntax
PASS: env documents GPU state path
PASS: env documents GPU freshness
PASS: env documents load path
PASS: env documents load refresh
PASS: compose passes GPU state path
FAIL: compose mounts snapshot directory read-only (missing: ${ACX_GPU_SNAPSHOT_DIR}:/run/acx:ro)
PASS: fresh readable snapshots and agreeing mount pass
PASS: missing GPU state fails closed
PASS: GPU state older than its budget fails
PASS: missing describe-load fails closed
PASS: describe-load older than its budget fails
PASS: snapshot unreadable by API uid fails
PASS: state variable disagreement fails
PASS: read-write mount fails
FAILED: 1 case(s)
```

I reverted the single `:rw` mutation back to `:ro`, then ran the identical
command:

```text
$ bash scripts/deploy/tests/test-check-gpu-snapshots.sh
PASS: checker has valid bash syntax
PASS: env documents GPU state path
PASS: env documents GPU freshness
PASS: env documents load path
PASS: env documents load refresh
PASS: compose passes GPU state path
PASS: compose mounts snapshot directory read-only
PASS: fresh readable snapshots and agreeing mount pass
PASS: checker derives the single writer paths from lifecycle units
PASS: missing GPU state fails closed
PASS: GPU state older than its budget fails
PASS: missing describe-load fails closed
PASS: describe-load older than its budget fails
PASS: snapshot unreadable by API uid fails
PASS: state variable disagreement fails
PASS: read-write mount fails
ALL PASS
```

The test was also observed RED before implementation (12 assertions failed
because the checker and deployment wiring did not exist), so both the initial
test-first failure and the deliberate mutation were witnessed.

## Full deploy-test suite

Exact command:

```bash
set -e
for test_file in scripts/deploy/tests/*.sh; do
  bash "$test_file"
done
```

Result:

```text
exit_code=0
test-check-gpu-snapshots.sh: ALL PASS (16 assertions)
test-db-reset-remote.sh: ALL PASS (6 assertions)
test-smoke-gate.sh: all assertions passed
```

`git diff --check` and Bash syntax checks for the new checker and test also
passed.

The assignment inbox requested a new
`scripts/deploy/tests/test_check_gpu_snapshots.py` wrapper and a pytest gate,
but the lane's authoritative owned-path list permits only
`scripts/deploy/tests/test-check-gpu-snapshots.sh` and prescribes the bash
verification command. I did not create the unowned Python path. The bash test
is wired into `test-scripts`, so it remains reachable from `make check-all`.

## Out-of-scope deployment finding

The repository contradicts the inbox claim that production has no `/run/acx`
mount. `scripts/deploy/recognition-service.sh` deploys
`docker-compose.env.yml`, not the lane-owned `docker-compose.prod.yml`, and the
former already mounts `${ACX_DESCRIBE_LOAD_DIR:-/run/acx}:/run/acx` read-write.
Consequently the actual deployed topology can already see host
`gpu-state.json` via the shared directory (and `env_file: .env` will pass the
new state variable), but that mount is not read-only. I did not edit
`docker-compose.env.yml` because it is explicitly outside this lane. The
orchestrator should reconcile the legacy/reference compose change with the
actual deployment surface before claiming read-only production enforcement.
