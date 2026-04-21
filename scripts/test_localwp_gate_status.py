from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "localwp-gate-status.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def test_gate_status_reports_localwp_probe_summary(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    wrapper = bin_dir / "fake-localwp-wp"
    _write_executable(
        wrapper,
        """#!/bin/sh
set -eu
args="$*"
if printf '%s' "$args" | grep -F 'option get siteurl' >/dev/null; then
    printf '%s\n' 'http://localhost:10010'
elif printf '%s' "$args" | grep -F 'plugin status alt-context' >/dev/null; then
    cat <<'EOF'
Plugin alt-context details:
    Name: Alt Context
    Status: Active
    Version: 0.0.2
EOF
elif printf '%s' "$args" | grep -F 'hash("sha256", $raw)' >/dev/null; then
    printf '%s\n' '{"fingerprint":"ad36dcba1af8","source":"constant"}'
elif printf '%s' "$args" | grep -F 'TenantIdentity::derive_from_site_url' >/dev/null; then
    printf '%s\n' 'd2e4d6f0-1111-5222-8abc-1234567890ab'
elif printf '%s' "$args" | grep -F 'GET", "/acx/v1/settings' >/dev/null; then
    printf '%s\n' '{"url":"https://api.altcontext.com","url_source":"constant","api_key_set":true,"api_key_last4":"****L3XY","key_source":"constant"}'
elif printf '%s' "$args" | grep -F 'POST", "/acx/v1/settings/test' >/dev/null; then
    printf '%s\n' '{"outcome":"connected","status_code":200,"body":{"ok":true}}'
else
    echo "unexpected args: $*" >&2
    exit 1
fi
""",
    )

    result = subprocess.run(
        ["/bin/bash", str(SCRIPT), "--wp-path", "/tmp/fake-site"],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "LOCALWP_GATE_WP_WRAPPER": str(wrapper),
            "PATH": f"{bin_dir}:/usr/bin:/bin:/usr/sbin:/sbin",
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["site_url"] == "http://localhost:10010"
    assert payload["tenant_uuid"] == "d2e4d6f0-1111-5222-8abc-1234567890ab"
    assert payload["plugin"]["status"] == "Active"
    assert payload["settings"]["url_source"] == "constant"
    assert payload["settings"]["key_source"] == "constant"
    assert payload["effective_key"]["fingerprint"] == "ad36dcba1af8"
    assert payload["probe"]["outcome"] == "connected"
