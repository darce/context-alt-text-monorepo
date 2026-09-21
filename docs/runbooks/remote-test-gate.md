# Remote test-gate (`make check-remote`)

Offloads gate suites to the shared OCI VM over Tailscale SSH, running as the
unprivileged, resource-capped `gate` user. Consumer wiring for the workbay
remote-gate mechanism (`scripts/remote_gate.sh`); VM-side provisioning (gate
user, systemd slice caps, pinned uv, Tailscale ACL) is owned by the workbay
provisioning runbook and was completed for this tailnet — this doc covers only
what this repo needs.

Security baseline: `docs/assessments/current/remote-gate-oci-tailscale-security-assessment-2026-07-12.md`
(NG-5 fail-closed host, Tailscale ACL findings B-1…B-6).

## Contract

- Only **committed HEAD** is gated — dirty paths are warned about and NOT pushed.
- Exit codes: nonzero = a target failed · `75` = clone lock busy (another run) ·
  `74` = host memory admission deferred (retryable) · `73` = `gate-preflight`
  failed (see below) · `78` = host not configured · `2` = local validation
  refusal (nothing touched the network). These are the **script's** codes; `make
  check-remote` collapses every failure to make's own exit `2`, so read the code
  off the trailing `make: *** [check-remote] Error <n>` line.
- Output per target: `=== <target> ===` … `EXIT=<code> (<target>)`, then `DONE-ALL`.
- The gate `make` runs in `REMOTE_GATE_WORKDIR`; `uv sync` runs there first when a
  `pyproject.toml` exists.

## Operator setup (one-time per machine)

There is deliberately **no baked-in host** (assessment NG-5: a private tailnet
address must never ship in a distributable script; a fallback host is fail-open).
Create the gitignored config in the **main checkout** root — linked worktrees
resolve to it automatically:

```bash
cat > .workbay/remote-gate.env <<'EOF'
REMOTE_GATE_HOST="gate@<your-gate-host>"          # tailnet FQDN, gate user only
REMOTE_GATE_WORKDIR="apps/prototype-description-service"
REMOTE_GATE_TARGETS="test"
# Integration lane (VM Postgres prerequisite below is met as of 2026-09-21):
# REMOTE_GATE_TARGETS="test test-integration"
# REMOTE_GATE_ENV="IDENTITY_PG_ADMIN_URL=postgresql+psycopg://gate@localhost:5432/postgres IDENTITY_PG_TEST_URL=postgresql+psycopg://context@localhost:5432/acx_identity_test"
EOF
scripts/remote_gate.sh bootstrap   # one-time clone provisioning on the host
scripts/remote_gate.sh doctor      # readiness probe (uv, make, hostgov, clone, DSN ports)
```

Env vars (`WORKBAY_REMOTE_GATE_HOST` etc.) override the file; see the script
header for the full knob list.

## Usage

```bash
make check-remote                       # configured targets (default: desc-service `test`)
make check-remote TARGETS="test lint"   # explicit targets, run in REMOTE_GATE_WORKDIR
```

## Two ways a gate run lies, and the flags that stop them

Both were observed on the same run (2026-09-21). Neither surfaces as a
failure, which is the point: a gate that reports nothing is not reporting
success ([OBS-08]).

**It ran only part of the suite.** `conftest.py` writes a collection-scope
receipt on every run and compares the collected roots against the five
declared in `testpaths`. The comparison is *advisory* unless you ask for
it. That run's receipt read `scope: "narrowed"`, `collected_roots:
["recognition/tests"]` — one of five — and the run said nothing. Make it
fail instead:

```bash
WORKBAY_REMOTE_GATE_ENV="ACX_STRICT_GATE=1" make check-remote TARGETS=test
```

Pin it to `test`. The flag demands a *full* collection, and any target that
selects by marker is narrowed by construction — `test-integration` is
`pytest -m "integration or pg or timing"`, and `scene/tests` and
`scripts/eval_harness/tests` contain none of those markers, so the run
aborts at collection with zero tests executed and the message `full
collection required; collection was narrowed`. That is the same phrase this
section just taught you to read as the greenwash symptom, which makes it a
particularly bad way to fail. Do not set the flag for the integration lane,
and note that `WORKBAY_REMOTE_GATE_ENV` *overrides* rather than appends to
`REMOTE_GATE_ENV`, so setting it inline also drops any DSNs from
`.workbay/remote-gate.env`.

Read the receipt afterwards either way; it is written even on a green run:

```bash
ssh gate@<your-gate-host> \
  cat /tmp/prototype-description-service-pytest-collection-scope.json
```

**It hung and held the mutex.** The gate serialises on `.gate.lock` and has
no liveness bound of its own — it cannot tell a frozen output stream from a
slow test, so a deadlocked test holds the lock until someone intervenes,
and the run's partial results are unrecoverable (stdout goes to a deleted
`/tmp/#<inode>` whose `/proc/<pid>/fd/1` reopens write-only). A bound now
lives in the suite, so it needs no flag and cannot be forgotten at the call
site: `apps/prototype-description-service/pyproject.toml` declares
`faulthandler_timeout` (dump every thread's stack, keep running) and
`timeout` (abort the test, name it, let the other xdist workers finish).
A test that legitimately needs longer overrides it with
`@pytest.mark.timeout(n)` — do not raise the global ceiling.

**That bound covers the test phase only, and only Python-level hangs.**
Two gaps remain, both of which still hold the mutex:

- `timeout_method = "signal"` raises inside the test, which is what
  preserves sibling workers' results — but a Python signal handler cannot
  run while the interpreter is inside a C call. A wedge in `onnxruntime`
  `session.run`, an hdbscan/BLAS/OpenCV kernel, or an asyncpg C path is
  *dumped* by `faulthandler` and never *aborted*. (Measured: a
  `hashlib.pbkdf2_hmac` call outlived a 5s bound by 35s and died only to an
  external `SIGKILL`.) Do not "fix" this with `timeout_method = "thread"` —
  it `os._exit`s the worker, which is the evidence loss this bound exists
  to prevent.
- The lock is taken before the test phase and spans more than it. Inside
  the same critical section the gate runs `git checkout`, `git clean`,
  `uv sync` (which builds hdbscan from source), and the admission probe.
  None of those is inside a pytest runtest protocol, so no per-test alarm
  is ever armed for them.

The real control for both belongs in the gate script — wrapping the remote
body in `timeout -k 30 "${GATE_MAX_SECONDS}"` with a distinct exit code, so
`flock` releases when the holder dies. That is filed upstream; until it
lands, a wedge in those surfaces still needs `make gate-reap CONFIRM=REAP`.

To tell a hung run from a merely slow one while it is still running, sample
consumed CPU twice on the VM and read each thread's kernel wait channel:

```bash
ssh gate@<your-gate-host> \
  'for i in 1 2; do ps -o pid,cputimes,etimes --no-headers -p <ctl>,<w1>,<w2>; sleep 10; done
   for t in /proc/<worker-pid>/task/*; do echo "$t $(cat $t/wchan)"; done'
```

Use `ps -o cputimes`, **not** `awk '{print $14+$15}' /proc/<pid>/stat`. The
`/proc` form returned a frozen value across three samples spanning three
minutes on a run that `ps` showed advancing by 4 CPU-seconds per 10 seconds
of wall clock — i.e. it reported a deadlock that was not happening. A
diagnostic that fails toward "hung" is worse than none: it argues for
killing a healthy run and losing the lock-holder's work.

Zero CPU delta alone does **not** mean deadlock. Read the wait channel — but
treat it as corroboration, never as the verdict:

| main-thread `wchan` | meaning |
| --- | --- |
| `0` | on CPU right now — running |
| `hrtimer_nanosleep` / `do_nanosleep` | `time.sleep()` — benign, and the most common quiet case |
| `poll_schedule_timeout*` | `select`/`poll` — **bounded and unbounded are indistinguishable by name** |
| `ep_poll` / `futex_do_wait` on **every** process, with no CPU duty anywhere | the actual deadlock signature |

The `poll_schedule_timeout` row is the trap. Measured on this gate host
(Linux 6.17.0-1011-oracle aarch64, CPython 3.12.3), `select.select([r],[],[])`
with no timeout and `select.select([r],[],[],600)` both report
`poll_schedule_timeout.constprop.0` — the kernel parks an *infinite* wait on the
same channel as a bounded one. So the name cannot tell you whether a bound
exists, and reading it as "timed, therefore fine" classifies a permanent block
as healthy while it holds the gate mutex. **CPU duty is the discriminator** —
the `ps -o cputimes` delta above is what the original field call actually rested
on (~4 CPU-seconds per 10s wall = periodic wakeups = alive).

A single idle worker is normal: xdist balances by test count, not by
duration, so one worker can draw a cluster of sleep-bound tests and sit at
near-zero CPU for minutes while its sibling saturates a core.

Calibrate against the right baseline before calling a run slow. A full `make test`
collects 6791 items and takes ~15 minutes on this host; that is the yardstick.

`ACX_STRICT_GATE=1` does **not** change what gets collected — `conftest.py`
only raises `pytest.UsageError` when the scope is already narrowed, and
`make test` passes no path arguments, so pytest always falls through to the
declared `testpaths`. The flag is a tripwire, not a workload multiplier; a
strict run and a non-strict run of the same target do identical work.

Do not size a run against the collection-scope receipt. Its default path
(`/tmp/prototype-description-service-pytest-collection-scope.json`) is
machine-global, so *any* concurrent pytest on the host overwrites it — this has
been observed mid-run reporting 3071 items and then 1, while the gate run it was
supposed to describe had collected 6791 across three roots. Pass an explicit
`--collection-scope-receipt=<path>` if you need a receipt you can trust.

## Host prerequisite: C toolchain (operator, one-time)

`uv sync` for the description service **builds `hdbscan` from source** on the
VM — the package publishes no Linux aarch64 wheels for any CPython — so the
host needs a compiler once, installed by the operator (never the gate user):

```bash
ssh ubuntu@<gate-host> 'sudo apt-get update && sudo apt-get install -y build-essential libgl1 libglib2.0-0'
```

Without `build-essential` the run fails fast at `remote-gate: uv sync failed`
(`command 'cc' failed: No such file or directory`); without `libgl1`/
`libglib2.0-0` the suite collects with ~45 ImportErrors (`libGL.so.1: cannot
open shared object file` — opencv on a headless host).

## Postgres prerequisite for `test-integration`

Without a usable DB the pg-marked suite used to **skip (never fail)**, so routing
`test-integration` through the gate **greenwashed** — `make` exited 0 with the
whole pg suite silently dropped (assessment "Consumer HIGH"). Two things close
that:

- `make test-integration` now exports `IDENTITY_PG_REQUIRED=1`, which turns the
  scratch-DB skip in `recognition/tests/conftest.py` into `pytest.fail`. Set
  `IDENTITY_PG_REQUIRED=0` only for a deliberate local opt-out.
- The gate host runs its own Postgres, owned by `gate` (not the Docker
  `acx-*-postgres-1` containers, which publish no port): PG 17.11 on
  `127.0.0.1:5432` (socket `/tmp/.s.PGSQL.5432`, trust auth), `psql` and
  `pg_config` under `/home/gate/.local/share/pg-prefix/bin`, pgvector 0.8.1
  built from source into that prefix, and a `context` role that is `LOGIN
  NOSUPERUSER NOBYPASSRLS` (the suite `pytest.fail`s on a privileged test role
  because RLS is not enforced for it). `55432` is the **laptop** Docker mapping
  (`docker-compose.db.yml`) and never applied on the VM.

Re-provisioning pgvector (as `gate`, no sudo — runs as written):

```bash
P=/home/gate/.local/share/pg-prefix
git clone --depth 1 --branch v0.8.1 https://github.com/pgvector/pgvector.git
cd pgvector
make         CC=gcc PG_CONFIG="$P/bin/pg_config"
make install CC=gcc PG_CONFIG="$P/bin/pg_config"
"$P/bin/psql" -d postgres -c \
  "CREATE ROLE context LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB"
```

The `CC=gcc` override is required because the conda `pg_config` reports an
`aarch64-conda-linux-gnu-cc` that is not installed on the host; without it both
`make` lines die at `cc: not found`. `doctor` probes port reachability only,
not auth or extension usability.

## Memory admission

Runs are wrapped in a systemd-run scope (`MemoryMax=6G`, `CPUQuota=200%`) inside
the gate user's slice fence. When `workbay-hostgov` is on the host it gates run
admission (exit 74 defer under pressure); absence is logged, never silent.
Known gap (2026-07-13): the hostgov CLI ships in `mcp-workbay-orchestrator`
≥0.2.8, which is git+ssh-only — PyPI stops at 0.2.0 (no hostgov), and the gate
user deliberately has no GitHub access. Until the package is published,
admission stays SKIPPED and the systemd caps are the backstop.

## Preflight: `gate-preflight` (fail-closed fixture presence)

A skip is not a pass, but an exit code cannot tell them apart. This gate was
green for months on a face pipeline it never ran: the `face_pipeline` ONNX
weights are gitignored, so a host that never fetched them skipped ~45
detector/aligner/embedder/ORT-parity tests and still reported `EXIT=0`.

The runner stays generic; the **repo** declares what must be present. If the
workdir's Makefile declares a `gate-preflight` target, `remote_gate.sh` runs it
before any gate target and a nonzero exit aborts the whole run with `73` —
**no target executes**. A workdir that declares no such target is logged, not
silently accepted.

`apps/prototype-description-service` declares:

```make
gate-preflight:
	@$(UV_RUN) python scripts/fetch_face_pipeline_models.py --verify-only
```

`--verify-only` is offline (sha256 against the pinned manifest, no download), so
it is safe on every invocation. Operator checks:

- `scripts/remote_gate.sh doctor` reports `gate-preflight: declared and
  PASSING` / `declared but FAILING` / `NOT declared`.
- When a run aborts with `73`, provision the host and re-run:
  `cd <workdir> && make gate-preflight` names exactly what is missing.

Add a `gate-preflight` target to any workdir whose suite skips on absent
fixtures, weights, or corpora — otherwise those skips read as passes.

## Guards

`scripts/test_remote_gate_guards.py` (in `make test-scripts`) pins the local
validation surface hermetically: fail-closed host (exit 78), no private host
baked in, unsafe target/dir/workdir/env refusals (exit 2) — all before any
ssh/push.
