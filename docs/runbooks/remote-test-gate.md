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
# Opt into the integration lane ONLY after the VM Postgres prerequisite below:
# REMOTE_GATE_TARGETS="test test-integration"
# REMOTE_GATE_ENV="IDENTITY_PG_TEST_URL=postgresql+psycopg://context:<pw>@localhost:55432/acx_identity_test"
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

## Postgres prerequisite for `test-integration` (open)

The pg-marked suite **skips (never fails)** when Postgres is unreachable or the
role lacks privileges (`recognition/tests/conftest.py` scratch-DB fixtures), so
routing `test-integration` through the gate without a usable DB **greenwashes**
— `make` exits 0 with the whole pg suite silently dropped (assessment
"Consumer HIGH"). As of 2026-07-13 the VM does **not** listen on
`localhost:55432`; before opting in:

1. Publish the co-resident dev Postgres on VM-localhost:55432 (never a tailnet
   peer grant — assessment B-6), or run a small dedicated PG owned by `gate`.
2. Provision `pgvector` and a role able to `CREATE DATABASE` on `*_test` names.
3. Set `REMOTE_GATE_ENV` with the DSN (above) so `doctor` probes the port —
   remembering the probe checks reachability only, not auth/extension usability.

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
