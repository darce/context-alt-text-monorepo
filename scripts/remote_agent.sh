#!/usr/bin/env bash
# Tracked remote-agent ping hygiene entrypoint (MAINT-ORCHW2-02).
# The plugin overlay may replace this file with a fuller transport; this copy
# keeps ping bounding and orphan reaping available without that overlay.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$here/remote_agent_hygiene.sh" "$@"
