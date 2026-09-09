#!/usr/bin/env bash
# Raise the invoking user's systemd slice TasksMax (MAINT-ORCHW2-02).
# Hung `codex exec ... ping` probes plus bubblewrap forks exhaust the default
# pids.max=512 and starve later lanes. Idempotent drop-in.
set -euo pipefail

uid="$(id -u)"
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
