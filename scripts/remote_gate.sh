#!/usr/bin/env bash
# Remote test-gate offload (isolation-hardened; see docs/runbooks/remote-test-gate.md
# and docs/assessments/current/remote-gate-oci-tailscale-security-assessment-2026-07-12.md).
#
# Pushes the current HEAD to a dedicated companion clone on a remote host and
# runs the requested make gate targets there as an UNPRIVILEGED, resource-capped
# user. Output contract for log consumers: one `=== <target> ===` header, then
# `EXIT=<code> (<target>)` per target, then a final `DONE-ALL`; local exit is
# nonzero if any target failed, 75 if the clone lock is busy, 74 if host-memory
# admission deferred the run, 73 if the workdir's `gate-preflight` target failed.
# Those numeric codes are the SCRIPT's exit status; `make check-remote` collapses
# every failure to make's own exit 2, so read the code off the trailing
# `make: *** [check-remote] Error <n>` line or invoke this script directly.
# Only committed state is gated: HEAD is what runs remotely.
#
# Preflight: if the workdir's Makefile declares a `gate-preflight` target, it
# runs before any gate target and a nonzero exit aborts the whole run. That is
# where a repo asserts the fixtures/weights its suite would otherwise SKIP over
# — a skip is not a pass, but an exit code cannot tell them apart (GATE-BR-01).
#
# Usage:
#   scripts/remote_gate.sh bootstrap            # one-time clone provisioning
#   scripts/remote_gate.sh doctor               # read-only host readiness probe
#   scripts/remote_gate.sh run [target ...]     # push HEAD + run gate targets
#
# Config — env > file (no baked-in host; unset host is a hard error):
#   0. HOST is REQUIRED — set it (no default; see resolution below). Other
#      knobs default (dir src/<repo-slug>, workdir ., targets below).
#   2. .workbay/remote-gate.env at the repo root: REMOTE_GATE_HOST,
#      REMOTE_GATE_DIR, REMOTE_GATE_WORKDIR, REMOTE_GATE_TARGETS,
#      REMOTE_GATE_ENV ("KEY=VALUE ..." injected into the remote run env)
#   3. WORKBAY_REMOTE_GATE_{HOST,DIR,WORKDIR,TARGETS,ENV,NICE,MEMORY_MAX,
#      CPU_QUOTA} + PYTEST_WORKERS env vars (captured before the file is
#      sourced, so env always wins)
#
# The remote user is expected to be a no-sudo, no-service-groups account whose
# user slice is capped (Phase 1 of the provisioning runbook); each run
# additionally wraps itself in a systemd-run scope with its own
# MemoryMax/CPUQuota.
# shellcheck disable=SC2016,SC1003  # single-quoted remote command strings:
# non-expansion is deliberate — those $vars must expand on the REMOTE side.
set -euo pipefail

# Resolve the MAIN checkout root (parent of the git-common-dir), not the linked
# worktree's toplevel — the config file and clone slug must be identical whether
# invoked from the main checkout or a linked session worktree, and `.workbay/`
# is gitignored so it only ever exists in the main checkout.
git_common_dir="$(git rev-parse --path-format=absolute --git-common-dir)"
repo_root="$(dirname "$git_common_dir")"
repo_slug="$(basename "$repo_root")"

# Layer 3 capture FIRST: the config file is dot-sourced, so caller env must be
# snapshotted before sourcing or a file that sets caller-namespace vars would
# invert the documented env-over-file precedence.
_env_host="${WORKBAY_REMOTE_GATE_HOST:-}"
_env_dir="${WORKBAY_REMOTE_GATE_DIR:-}"
_env_workdir="${WORKBAY_REMOTE_GATE_WORKDIR:-}"
_env_targets="${WORKBAY_REMOTE_GATE_TARGETS:-}"
_env_extra="${WORKBAY_REMOTE_GATE_ENV:-}"
_env_nice="${WORKBAY_REMOTE_GATE_NICE:-}"
_env_workers="${PYTEST_WORKERS:-}"
_env_memmax="${WORKBAY_REMOTE_GATE_MEMORY_MAX:-}"
_env_cpuquota="${WORKBAY_REMOTE_GATE_CPU_QUOTA:-}"

# Layer 2: per-repo config file.
REMOTE_GATE_HOST="" REMOTE_GATE_DIR="" REMOTE_GATE_WORKDIR="" REMOTE_GATE_TARGETS="" REMOTE_GATE_ENV=""
config_file="$repo_root/.workbay/remote-gate.env"
if [ -f "$config_file" ]; then
    # shellcheck disable=SC1090
    . "$config_file"
fi

# Resolution: captured env > file. There is deliberately NO baked-in default
# host — a private tailnet address must never ship inside a would-be-distributed
# tool (assessment NG-5), and a fallback host is fail-open (an unconfigured
# caller would push HEAD to whatever address the default named). Unset => hard
# error, no fallback.
REMOTE_HOST="${_env_host:-${REMOTE_GATE_HOST:-}}"
if [ -z "$REMOTE_HOST" ]; then
    echo "remote-gate: host not configured — set WORKBAY_REMOTE_GATE_HOST or" \
         "REMOTE_GATE_HOST in .workbay/remote-gate.env (e.g. gate@<your-host>)" >&2
    exit 78
fi
REMOTE_DIR="${_env_dir:-${REMOTE_GATE_DIR:-src/${repo_slug}}}"
WORKDIR="${_env_workdir:-${REMOTE_GATE_WORKDIR:-.}}"
GATE_TARGETS="${_env_targets:-${REMOTE_GATE_TARGETS:-}}"
GATE_EXTRA_ENV="${_env_extra:-${REMOTE_GATE_ENV:-}}"
NICENESS="${_env_nice:-10}"
WORKERS="${_env_workers:-3}"
# Repo default lane: the description-service fast suite (no PG dependency).
# test-integration is config-opt-in only — it SKIPS (never fails) without a
# usable Postgres at the DSN, so gating it on an unprovisioned host greenwashes
# (assessment "Consumer HIGH"). Route it via REMOTE_GATE_TARGETS once the VM
# Postgres prerequisite is provisioned.
DEFAULT_TARGETS=(test)
# Bootstrap stamps this sentinel; run refuses without it so checkout/clean can
# never fire in a directory this script does not own.
CLONE_SENTINEL=".remote-gate-clone"
# Per-run scope caps (inside the outer user-slice fence from the runbook).
RUN_MEMORY_MAX="${_env_memmax:-6G}"
RUN_CPU_QUOTA="${_env_cpuquota:-200%}"

die() { echo "remote_gate: $*" >&2; exit 2; }

# --- validation (everything below is interpolated into a remote shell) -------
case "$REMOTE_DIR" in
    ""|.|/*|*..*) die "invalid REMOTE_DIR '${REMOTE_DIR}' (empty/./absolute/.. rejected)" ;;
    *"$repo_slug") : ;;
    *) die "REMOTE_DIR '${REMOTE_DIR}' must end with the repo slug '${repo_slug}' (collision guard)" ;;
esac
case "$WORKDIR" in
    /*|*..*) die "invalid REMOTE_GATE_WORKDIR '${WORKDIR}' (absolute/.. rejected)" ;;
esac
case "$REMOTE_DIR" in
    *[!A-Za-z0-9/_.-]*) die "REMOTE_DIR contains characters outside [A-Za-z0-9/_.-]" ;;
esac
case "$WORKDIR" in
    *[!A-Za-z0-9/_.-]*) die "REMOTE_GATE_WORKDIR contains characters outside [A-Za-z0-9/_.-]" ;;
esac
case "$NICENESS" in *[!0-9]*|"") die "WORKBAY_REMOTE_GATE_NICE must be an integer" ;; esac
case "$WORKERS" in *[!0-9]*|"") die "PYTEST_WORKERS must be an integer" ;; esac
case "$RUN_MEMORY_MAX" in *[!0-9GMK]*|"") die "MEMORY_MAX must look like 6G/512M" ;; esac
case "$RUN_CPU_QUOTA" in *[!0-9%]*|"") die "CPU_QUOTA must look like 200%" ;; esac

extra_env=()
# Word-split GATE_EXTRA_ENV without pathname expansion — an env value like
# `PATTERN=*` must stay literal, not glob against the cwd (shellcheck does not
# flag this). `set -f` is restored immediately after the split.
set -f
# deliberate unquoted split under noglob (tokens re-validated below)
# shellcheck disable=SC2206
_gate_env_tokens=($GATE_EXTRA_ENV)
set +f
for kv in ${_gate_env_tokens[@]+"${_gate_env_tokens[@]}"}; do
    case "$kv" in
    [A-Za-z_]*=*)
        case "$kv" in
        *'`'*|*'$('*|*';'*|*'&'*|*'|'*|*'<'*|*'>'*|*'\'*)
            die "REMOTE_GATE_ENV entry contains shell metacharacters: ${kv}" ;;
        esac
        extra_env+=("$kv")
        ;;
    *) die "REMOTE_GATE_ENV entries must be KEY=VALUE (got '${kv}')" ;;
    esac
done

SSH=(ssh -o BatchMode=yes -o ConnectTimeout=10
     -o ServerAliveInterval=30 -o ServerAliveCountMax=4 "$REMOTE_HOST")

cmd="${1:-run}"
[ "$#" -gt 0 ] && shift

case "$cmd" in
bootstrap)
    # uv is provisioned by the runbook's Phase 1 (pinned tarball, no curl|sh);
    # bootstrap only prepares the receive clone.
    "${SSH[@]}" 'set -euo pipefail
        command -v git >/dev/null || { echo "bootstrap: git missing on host" >&2; exit 1; }
        [ -x "$HOME/.local/bin/uv" ] || { echo "bootstrap: uv missing — run runbook Phase 1 first" >&2; exit 1; }
        mkdir -p "$HOME"/'"$REMOTE_DIR"'
        cd "$HOME"/'"$REMOTE_DIR"' || exit 1
        [ "$PWD" != "$HOME" ] || { echo "bootstrap: refusing to init \$HOME as the clone" >&2; exit 1; }
        [ -d .git ] || git init -q
        git config receive.denyCurrentBranch ignore
        # Test suites create fixture repos and commit in them; a fresh gate
        # user has no git identity and every such commit would fail.
        git config --global user.email >/dev/null 2>&1 || git config --global user.email "gate@remote-gate.invalid"
        git config --global user.name  >/dev/null 2>&1 || git config --global user.name  "remote-gate"
        touch '"$CLONE_SENTINEL"'
        echo "bootstrap: ok — $(git --version), clone at $PWD"'
    ;;
doctor)
    probe_urls=()
    for kv in ${extra_env[@]+"${extra_env[@]}"}; do
        case "$kv" in *://*) probe_urls+=("${kv#*=}") ;; esac
    done
    "${SSH[@]}" 'set -euo pipefail
        user="$(id -un)"
        groups="$(id -Gn)"
        echo "user=${user} groups=${groups}"
        arch="$(uname -m)"
        cores="$(nproc)"
        echo "arch=${arch} cores=${cores}"
        free -h | awk "NR==2{print \"mem_available=\" \$7}"
        df -h "$HOME" | awk "NR==2{print \"disk_free=\" \$4}"
        du -sh "$HOME/.cache/uv" 2>/dev/null || echo "uv_cache=none"
        if [ -x "$HOME/.local/bin/uv" ]; then "$HOME/.local/bin/uv" --version; else echo "uv: MISSING (runbook Phase 1)"; fi
        command -v make >/dev/null && make --version | head -1 || echo "make: MISSING (apt-get install make)"
        command -v systemd-run >/dev/null || echo "systemd-run: MISSING (per-run caps unavailable)"
        hostgov_found=""
        for cand in "$HOME/'"$REMOTE_DIR"'/'"$WORKDIR"'/.venv/bin/workbay-hostgov" "$HOME/.local/bin/workbay-hostgov" "$(command -v workbay-hostgov 2>/dev/null || true)"; do
            [ -n "$cand" ] && [ -x "$cand" ] && { hostgov_found="$cand"; break; }
        done
        if [ -n "$hostgov_found" ]; then
            echo "workbay-hostgov: present at $hostgov_found (memory admission active)"
        else
            echo "workbay-hostgov: MISSING (admission hook is a no-op; uv tool install mcp-workbay-orchestrator as the gate user to enable it)"
        fi
        if [ -f "$HOME"/'"$REMOTE_DIR"'/'"$CLONE_SENTINEL"' ]; then echo "clone: present"; else echo "clone: MISSING (run bootstrap)"; fi
        wd="$HOME"/'"$REMOTE_DIR"'/'"$WORKDIR"'
        if [ -d "$wd" ] && (cd "$wd" && make -n gate-preflight >/dev/null 2>&1); then
            if (cd "$wd" && PATH="$wd/.venv/bin:$HOME/.local/bin:$PATH" make gate-preflight >/dev/null 2>&1); then
                echo "gate-preflight: declared and PASSING (fixture/weight presence verified)"
            else
                echo "gate-preflight: declared but FAILING — runs will abort with 73 until provisioned (cd $wd && make gate-preflight)"
            fi
        else
            echo "gate-preflight: NOT declared by workdir (suite skips are indistinguishable from passes)"
        fi
        for url in '"${probe_urls[*]:-}"'; do
            hostport="${url#*://}"; hostport="${hostport#*@}"; hostport="${hostport%%/*}"
            host="${hostport%%:*}"; port="${hostport##*:}"
            case "$port" in ""|*[!0-9]*)
                echo "service ${host}: no explicit port in DSN — reachability probe skipped"
                continue ;;
            esac
            if nc -z -w3 "$host" "$port" 2>/dev/null; then echo "service ${host}:${port}: reachable"
            else echo "service ${host}:${port}: UNREACHABLE (tests depending on it may silently skip)"; fi
        done'
    ;;
run)
    targets=("$@")
    if [ "${#targets[@]}" -eq 0 ] && [ -n "$GATE_TARGETS" ]; then
        read -r -a targets <<< "$GATE_TARGETS"
    fi
    [ "${#targets[@]}" -gt 0 ] || targets=("${DEFAULT_TARGETS[@]}")
    for t in "${targets[@]}"; do
        case "$t" in
        *[!A-Za-z0-9_.-]*) die "refusing target with unsafe characters: ${t}" ;;
        esac
    done
    dirty="$(git status --porcelain | wc -l | tr -d ' ')"
    if [ "$dirty" -gt 0 ]; then
        echo "remote_gate: WARNING — ${dirty} dirty path(s) NOT gated (only committed HEAD is pushed)" >&2
    fi
    sha="$(git rev-parse HEAD)"
    echo "remote-gate: pushing ${sha} to ${REMOTE_HOST}:${REMOTE_DIR} (workdir ${WORKDIR})"
    # Transport ref lives OUTSIDE refs/heads/ on purpose. The gate publishes a
    # SHA to a scratch mirror; the remote checks out ${sha} directly and never
    # reads the ref by name, so nothing here is a branch. Under refs/heads/ the
    # push-side branch-naming guard classified the DESTINATION name
    # ("remote-gate") as the developer's branch and blocked every gate run on
    # every branch, main included — because git reports local_ref as "HEAD" for
    # a HEAD:refs/heads/<x> refspec and the guard falls back to the remote ref.
    # Keeping the guard fully armed for real branch pushes is the point: the fix
    # is to stop pretending the gate publishes a branch, not to override it.
    git push --quiet --force "${REMOTE_HOST}:${REMOTE_DIR}" "HEAD:refs/workbay/gate"
    # Shell options do not cross the SSH process boundary. Target failures are
    # captured with explicit `|| rc=$?` guards below so errexit can stay enabled
    # for every other command in this remote body.
    "${SSH[@]}" "set -euo pipefail
        cd \"\$HOME/${REMOTE_DIR}\" || exit 1
        [ -f \"${CLONE_SENTINEL}\" ] || { echo 'remote-gate: clone sentinel missing; refusing (re-run bootstrap)' >&2; exit 1; }
        exec 9>.gate.lock
        flock -n 9 || { echo 'remote-gate: gate busy (another run holds the clone lock)' >&2; exit 75; }
        git checkout -qf ${sha} || exit 1
        # Retire the pre-refs/workbay transport branch once we are detached off
        # it; left behind it pins old gate objects on a disk-tight VM. Idempotent.
        git update-ref -d refs/heads/remote-gate 2>/dev/null || true
        git clean -fdq -e .venv -e ${CLONE_SENTINEL} -e .gate.lock || exit 1
        cd \"${WORKDIR}\" || exit 1
        if [ -f pyproject.toml ]; then
            \"\$HOME/.local/bin/uv\" sync -q || { echo 'remote-gate: uv sync failed' >&2; exit 1; }
        else
            echo 'remote-gate: no pyproject.toml in workdir — skipping uv sync'
        fi
        # Admission gate: refuse to start under memory pressure — a deferred
        # run is recoverable; an OOM-killed co-resident service is not. Runs
        # AFTER uv sync so a console script the sync installs into
        # \$PWD/.venv/bin is visible; the hook is a no-op only when the CLI is
        # genuinely absent (logged, so a skip is never silent). Exit 74 (defer,
        # distinct from the lock-busy 75) so automation can tell them apart.
        hostgov=''
        for cand in \"\$PWD/.venv/bin/workbay-hostgov\" \"\$HOME/.local/bin/workbay-hostgov\"; do
            [ -x \"\$cand\" ] && { hostgov=\"\$cand\"; break; }
        done
        [ -n \"\$hostgov\" ] || hostgov=\"\$(command -v workbay-hostgov 2>/dev/null || true)\"
        if [ -n \"\$hostgov\" ]; then
            \"\$hostgov\" probe --json --workspace-root \"\$PWD\" \
                || { echo 'remote-gate: DEFERRED — host memory admission (workbay-hostgov); retryable' >&2; exit 74; }
        else
            echo 'remote-gate: workbay-hostgov not installed — memory admission SKIPPED (systemd caps remain the backstop)' >&2
        fi
        runner='nice -n ${NICENESS} ionice -c3'
        if command -v systemd-run >/dev/null && systemd-run --quiet --user --scope -p MemoryMax=${RUN_MEMORY_MAX} true 2>/dev/null; then
            runner=\"systemd-run --quiet --user --scope -p MemoryMax=${RUN_MEMORY_MAX} -p CPUQuota=${RUN_CPU_QUOTA} nice -n ${NICENESS} ionice -c3\"
        else
            echo 'remote-gate: systemd-run scope unavailable — falling back to nice/ionice only' >&2
        fi
        # Fail-closed repo preflight (GATE-BR-01). A workdir may declare a
        # 'gate-preflight' make target that asserts whatever its suite silently
        # (no backticks below this line: everything here is inside a
        # double-quoted remote-command string, so a backtick pair would run
        # locally at expansion time — the same hazard the extra_env validator
        # rejects)
        # SKIPS over when absent (here: the gitignored face-pipeline ONNX
        # weights). A skip is not a pass, but an exit code cannot tell them
        # apart — this gate was green for months on a face pipeline it never
        # ran. Declared-and-failing aborts before any target with exit 73
        # (distinct from the 74 defer / 75 lock-busy codes); undeclared is
        # logged, never silent.
        if make -n gate-preflight >/dev/null 2>&1; then
            echo \"=== gate-preflight ===\"
            rc=0
            \$runner env \
                ${extra_env[*]:-} \
                TMPDIR=/tmp \
                WORKBAY_DISABLE_INVOKING_HOOKS=1 \
                PATH=\"\$PWD/.venv/bin:\$HOME/.local/bin:\$PATH\" \
                make gate-preflight || rc=\$?
            echo \"EXIT=\$rc (gate-preflight)\"
            if [ \"\$rc\" -ne 0 ]; then
                echo 'remote-gate: PREFLIGHT FAILED — refusing to run targets (the suite would skip and report green)' >&2
                echo DONE-ALL
                exit 73
            fi
        else
            echo 'remote-gate: workdir declares no gate-preflight target — fixture/weight presence UNVERIFIED (skips are indistinguishable from passes)'
        fi
        overall=0
        for t in ${targets[*]}; do
            echo \"=== \$t ===\"
            rc=0
            \$runner env \
                ${extra_env[*]:-} \
                TMPDIR=/tmp \
                WORKBAY_DISABLE_INVOKING_HOOKS=1 \
                WORKBAY_HANDOFF_DEFAULT_AGENT=\${WORKBAY_HANDOFF_DEFAULT_AGENT:-remote-gate} \
                PYTEST_WORKERS=${WORKERS} \
                PATH=\"\$PWD/.venv/bin:\$HOME/.local/bin:\$PATH\" \
                make \"\$t\" || rc=\$?
            echo \"EXIT=\$rc (\$t)\"
            [ \"\$rc\" -eq 0 ] || overall=1
        done
        echo DONE-ALL
        exit \$overall"
    ;;
*)
    sed -n '2,33p' "$0" >&2
    exit 2
    ;;
esac
