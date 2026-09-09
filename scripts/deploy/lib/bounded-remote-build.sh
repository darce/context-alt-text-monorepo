#!/usr/bin/env bash
# Generated remote BuildKit program for recognition-service.sh.
#
# This file is sourced by the deploy wrapper. The generated program deliberately
# carries only positional, allow-listed values over bash -s; it does not
# interpolate operator input into the program text.

bounded_remote_build_program() {
  cat <<'REMOTE_BUILD_PROGRAM'
set -euo pipefail

acx_bulkhead_fail() {
  printf 'remote BuildKit bulkhead: %s\n' "$*" >&2
  exit 125
}

acx_builder="${1:-}"
acx_node="${2:-}"
acx_endpoint="${3:-}"
acx_image="${4:-}"
acx_sha="${5:-}"
acx_target="${6:-}"
acx_deadline_epoch="${7:-}"
acx_build_dir="${8:-}"

case "$acx_builder" in
  ''|-*|*[!A-Za-z0-9_.-]*) acx_bulkhead_fail "unsafe or missing builder name" ;;
esac
case "$acx_node" in
  ''|-*|*[!A-Za-z0-9_.-]*) acx_bulkhead_fail "unsafe or missing builder node" ;;
esac
[[ "$acx_endpoint" == "unix:///var/run/docker.sock" ]] \
  || acx_bulkhead_fail "builder endpoint must be unix:///var/run/docker.sock"
case "$acx_image" in
  ''|*[!A-Za-z0-9_.:/-]*) acx_bulkhead_fail "unsafe or missing image repository" ;;
esac
[[ "$acx_sha" =~ ^[a-f0-9]{40}$ ]] \
  || acx_bulkhead_fail "build tag must be the full 40-character Git SHA"
if [[ -n "$acx_target" && "$acx_target" == *[!A-Za-z0-9_.-]* ]]; then
  acx_bulkhead_fail "unsafe build target"
fi
[[ "$acx_deadline_epoch" =~ ^[1-9][0-9]*$ ]] \
  || acx_bulkhead_fail "missing or invalid overall build deadline"
[[ "$acx_build_dir" == /* && "$acx_build_dir" != *[!A-Za-z0-9_./-]* ]] \
  || acx_bulkhead_fail "unsafe or missing generation directory"

for acx_command in docker awk date sleep kill; do
  command -v "$acx_command" >/dev/null 2>&1 \
    || acx_bulkhead_fail "required command unavailable: $acx_command"
done
acx_setsid=""
if command -v setsid >/dev/null 2>&1; then
  acx_setsid="setsid"
fi

acx_remaining() {
  local acx_phase="$1" acx_now acx_left
  acx_now="$(date +%s)" || acx_bulkhead_fail "could not read the remote clock"
  [[ "$acx_now" =~ ^[0-9]+$ ]] \
    || acx_bulkhead_fail "remote clock returned a non-numeric value"
  acx_left=$((acx_deadline_epoch - acx_now))
  if (( acx_left < 1 )); then
    printf 'remote BuildKit overall deadline exhausted during %s\n' "$acx_phase" >&2
    return 124
  fi
  printf '%s\n' "$acx_left"
}

# The local run_with_deadline bounds the SSH channel as well. This inner
# watchdog makes each Docker phase observe the same absolute deadline after a
# late lock acquisition, instead of restarting a fresh timeout per phase.
acx_run() {
  local acx_phase="$1" acx_pid acx_left acx_now
  shift
  acx_left="$(acx_remaining "$acx_phase")" || return $?
  # New session/process group so descendants die with the watchdog
  # (OCIR-ASTRA-20260908-04). kill of the direct child left synthetic
  # grandchildren running past the deadline.
  if [[ -n "$acx_setsid" ]]; then
    $acx_setsid "$@" &
  else
    "$@" &
  fi
  acx_pid=$!
  while kill -0 "$acx_pid" 2>/dev/null; do
    acx_now="$(date +%s)" || {
      acx_kill_tree "$acx_pid"
      wait "$acx_pid" 2>/dev/null || true
      acx_bulkhead_fail "could not read the remote clock while running $acx_phase"
    }
    if (( acx_now >= acx_deadline_epoch )); then
      acx_kill_tree "$acx_pid"
      wait "$acx_pid" 2>/dev/null || true
      printf 'remote BuildKit phase timed out during %s; outcome UNKNOWN\n' "$acx_phase" >&2
      return 124
    fi
    sleep 0.1
  done
  wait "$acx_pid"
}

acx_kill_tree() {
  local acx_pid="$1"
  # Negative PGID kills the whole session started by setsid. Fall back to the
  # direct child when the process is not a group leader.
  kill -TERM -- "-$acx_pid" 2>/dev/null || kill -TERM "$acx_pid" 2>/dev/null || true
  sleep 0.1
  kill -KILL -- "-$acx_pid" 2>/dev/null || kill -KILL "$acx_pid" 2>/dev/null || true
}

acx_verify_builder_metadata() {
  local acx_info="$1" acx_require_running="${2:-0}"
  printf '%s\n' "$acx_info" | awk \
    -v expected_node="$acx_node" \
    -v expected_endpoint="$acx_endpoint" \
    -v require_running="$acx_require_running" '
      $1 == "Driver:" { driver = $2 }
      $1 == "Nodes:" { in_nodes = 1; next }
      in_nodes && $1 == "Name:" {
        node_count++
        current_node = ($2 == expected_node)
        if (current_node) node_found = 1
        next
      }
      in_nodes && current_node && $1 == "Endpoint:" {
        if ($2 == expected_endpoint) endpoint_found = 1
        next
      }
      in_nodes && current_node && $1 == "Status:" {
        status = $2
        next
      }
      END {
        ok = (driver == "docker-container" &&
              node_count == 1 && node_found && endpoint_found &&
              (status == "running" || status == "starting" ||
               status == "stopped" || status == "stopping" ||
               status == "inactive"))
        if (require_running == "1") ok = ok && status == "running"
        exit(ok ? 0 : 1)
      }
    '
}

acx_verify_host_config_limits() {
  local acx_inspect="$1"
  printf '%s\n' "$acx_inspect" | awk '
    /"HostConfig"[[:space:]]*:/ { in_host_config = 1 }
    in_host_config && /"Memory"[[:space:]]*:/ {
      memory_keys++
      if ($0 ~ /"Memory"[[:space:]]*:[[:space:]]*6442450944([^0-9]|$)/) memory_ok++
    }
    in_host_config && /"MemorySwap"[[:space:]]*:/ {
      swap_keys++
      if ($0 ~ /"MemorySwap"[[:space:]]*:[[:space:]]*6442450944([^0-9]|$)/) swap_ok++
    }
    in_host_config && /"CpuPeriod"[[:space:]]*:/ {
      period_keys++
      if ($0 ~ /"CpuPeriod"[[:space:]]*:[[:space:]]*100000([^0-9]|$)/) period_ok++
    }
    in_host_config && /"CpuQuota"[[:space:]]*:/ {
      quota_keys++
      if ($0 ~ /"CpuQuota"[[:space:]]*:[[:space:]]*200000([^0-9]|$)/) quota_ok++
    }
   END {
      if (in_host_config &&
          memory_keys == 1 && memory_ok == 1 &&
          swap_keys == 1 && swap_ok == 1 &&
          period_keys == 1 && period_ok == 1 &&
          quota_keys == 1 && quota_ok == 1) exit 0
      exit 1
   }
  '
}

if ! acx_run "Buildx capability probe" docker buildx version >/dev/null 2>&1; then
  acx_bulkhead_fail "docker buildx is unavailable"
fi

acx_builder_container="buildx_buildkit_${acx_node}"
acx_builder_info=""
acx_existing_builder=0
if acx_builder_info="$(acx_run "builder metadata inspection" docker buildx inspect "$acx_builder")"; then
  acx_existing_builder=1
  if ! acx_verify_builder_metadata "$acx_builder_info"; then
    acx_bulkhead_fail "existing builder does not match the required driver, node, and endpoint"
  fi
else
  if ! acx_run "bounded builder creation" docker buildx create \
    --name "$acx_builder" \
    --node "$acx_node" \
    --driver docker-container \
    --driver-opt memory=6g \
    --driver-opt memory-swap=6g \
    --driver-opt cpu-period=100000 \
    --driver-opt cpu-quota=200000 \
    "$acx_endpoint" >/dev/null; then
    acx_bulkhead_fail "could not create the required docker-container builder"
  fi
fi

# A pre-existing builder must prove its container limits before it is reused.
# A newly-created builder may not have a container until bootstrap; it is
# inspected immediately after bootstrap below.
if [[ "$acx_existing_builder" == "1" ]]; then
  acx_builder_status="$(printf '%s\n' "$acx_builder_info" | awk \
    '$1 == "Status:" { print $2; exit }')"
  case "$acx_builder_status" in
    inactive)
      # Buildx reports inactive when the managed container is absent; bootstrap
      # will create it from the persisted builder driver options below.
      ;;
    running|starting|stopped|stopping)
      acx_container_inspect="$(acx_run "existing builder container inspection" \
        docker inspect "$acx_builder_container")" \
        || acx_bulkhead_fail "existing builder container inspection is unavailable"
      if ! acx_verify_host_config_limits "$acx_container_inspect"; then
        acx_bulkhead_fail "existing builder container HostConfig limits do not match the bulkhead"
      fi
      ;;
    *)
      acx_bulkhead_fail "existing builder status is unavailable"
      ;;
  esac
fi

if ! acx_run "builder bootstrap" docker buildx inspect --bootstrap "$acx_builder" >/dev/null; then
  acx_bulkhead_fail "required builder bootstrap failed"
fi
acx_builder_info="$(acx_run "post-bootstrap builder inspection" \
  docker buildx inspect "$acx_builder")" \
  || acx_bulkhead_fail "post-bootstrap builder inspection failed"
if ! acx_verify_builder_metadata "$acx_builder_info" 1; then
  acx_bulkhead_fail "post-bootstrap builder metadata does not match the required driver, node, endpoint, and running state"
fi
acx_container_inspect="$(acx_run "post-bootstrap builder container inspection" \
  docker inspect "$acx_builder_container")" \
  || acx_bulkhead_fail "builder container inspection is unavailable"
if ! acx_verify_host_config_limits "$acx_container_inspect"; then
  acx_bulkhead_fail "builder container HostConfig limits do not match the bulkhead"
fi

acx_run "isolated BuildKit cache prune" docker buildx prune \
  --builder "$acx_builder" --force --filter until=72h \
  || acx_bulkhead_fail "isolated BuildKit cache prune failed"

[[ -d "$acx_build_dir" ]] \
  || acx_bulkhead_fail "remote generation directory is unavailable"
cd -- "$acx_build_dir"
acx_build_args=(
  buildx build
  --builder "$acx_builder"
  --load
  --build-arg "GIT_COMMIT_SHA=$acx_sha"
)
if [[ -n "$acx_target" ]]; then
  acx_build_args+=(--target "$acx_target")
fi
acx_build_args+=(-t "${acx_image}:${acx_sha}" .)
acx_run "remote BuildKit build" docker "${acx_build_args[@]}"
REMOTE_BUILD_PROGRAM
}
