#!/usr/bin/env bash
# Raise the invoking user's systemd slice TasksMax (MAINT-ORCHW2-02).
# Hung `codex exec ... ping` probes plus bubblewrap forks exhaust the default
# pids.max=512 and starve later lanes. Idempotent drop-in.
set -euo pipefail

effective_uid="$(id -u)"
case "${effective_uid}" in
  ""|*[!0-9]*)
    echo "install-user-slice-tasksmax: id -u returned an invalid UID: ${effective_uid}" >&2
    exit 1
    ;;
esac

# The system-manager drop-in must be installed by root.  When invoked through
# sudo, SUDO_UID identifies the gate user whose slice should be raised; using
# id -u here would otherwise configure user-0.slice.  Direct root invocations
# must name their target explicitly because root has no unambiguous gate-user
# identity.
if [[ "${effective_uid}" == "0" ]]; then
  uid="${TASKSMAX_TARGET_UID:-${SUDO_UID:-}}"
  if [[ -z "${uid}" ]]; then
    echo "install-user-slice-tasksmax: root invocation requires SUDO_UID or TASKSMAX_TARGET_UID" >&2
    exit 1
  fi
else
  echo "install-user-slice-tasksmax: run as root (for example, sudo with the gate user as SUDO_UID)" >&2
  exit 1
fi
case "${uid}" in
  ""|*[!0-9]*)
    echo "install-user-slice-tasksmax: target UID is invalid: ${uid}" >&2
    exit 1
    ;;
esac

# The user-${uid}.slice unit is owned by the system manager (it contains the
# user@${uid}.service), so its drop-in belongs under /etc/systemd/system.  The
# override is only a hermetic-test seam; production uses the system path.
systemd_system_dir="${TASKSMAX_SYSTEMD_SYSTEM_DIR:-/etc/systemd/system}"
dropin_dir="${systemd_system_dir}/user-${uid}.slice.d"
dropin="${dropin_dir}/tasksmax.conf"

if ! command -v systemctl >/dev/null 2>&1; then
  echo "install-user-slice-tasksmax: systemctl is unavailable; the drop-in is not active" >&2
  exit 1
fi

if ! mkdir -p "$dropin_dir"; then
  echo "install-user-slice-tasksmax: could not create ${dropin_dir}" >&2
  exit 1
fi

cat >"$dropin" <<'EOF'
[Slice]
TasksMax=4096
EOF

if ! systemctl daemon-reload; then
  echo "install-user-slice-tasksmax: daemon-reload failed; the drop-in is not active" >&2
  exit 1
fi

active_tasks_max="$(systemctl show "user-${uid}.slice" --property=TasksMax --value)" || {
  echo "install-user-slice-tasksmax: could not verify active TasksMax for user-${uid}.slice" >&2
  exit 1
}
if [[ "${active_tasks_max}" != "4096" ]]; then
  echo "install-user-slice-tasksmax: active TasksMax is ${active_tasks_max:-unset}, expected 4096" >&2
  exit 1
fi

echo "install-user-slice-tasksmax: applied ${dropin} (TasksMax=${active_tasks_max})"
