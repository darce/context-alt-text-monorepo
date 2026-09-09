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

if command -v systemctl >/dev/null 2>&1; then
  systemctl --user daemon-reload 2>/dev/null || true
fi
echo "install-user-slice-tasksmax: wrote ${dropin} (TasksMax=4096)"
