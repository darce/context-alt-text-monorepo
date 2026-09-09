#!/usr/bin/env bash
# Raise the invoking user's systemd slice TasksMax (MAINT-ORCHW2-02).
# Hung `codex exec ... ping` probes plus bubblewrap forks exhaust the default
# pids.max=512 and starve later lanes. Idempotent drop-in.
set -euo pipefail

uid="$(id -u)"
dropin_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/user-${uid}.slice.d"
dropin="${dropin_dir}/tasksmax.conf"

mkdir -p "$dropin_dir"
cat >"$dropin" <<'EOF'
[Slice]
TasksMax=4096
EOF

if ! command -v systemctl >/dev/null 2>&1; then
  echo "install-user-slice-tasksmax: wrote ${dropin}, but systemctl is unavailable; the drop-in is not active" >&2
  exit 1
fi

if ! systemctl --user daemon-reload; then
  echo "install-user-slice-tasksmax: daemon-reload failed; the drop-in is not active" >&2
  exit 1
fi

active_tasks_max="$(systemctl --user show "user-${uid}.slice" --property=TasksMax --value)" || {
  echo "install-user-slice-tasksmax: could not verify active TasksMax for user-${uid}.slice" >&2
  exit 1
}
if [[ "${active_tasks_max}" != "4096" ]]; then
  echo "install-user-slice-tasksmax: active TasksMax is ${active_tasks_max:-unset}, expected 4096" >&2
  exit 1
fi

echo "install-user-slice-tasksmax: applied ${dropin} (TasksMax=${active_tasks_max})"
