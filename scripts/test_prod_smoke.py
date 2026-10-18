"""Unit tests for scripts/prod-smoke.sh (E15-3a-BR-04).

Exercises argument parsing and probe failure propagation via subprocess.
No live network; we point the script at an unreachable loopback port and
assert it fails closed.
"""

from __future__ import annotations

import pathlib
import subprocess

SCRIPT = pathlib.Path(__file__).resolve().parent / "prod-smoke.sh"


def test_script_is_executable() -> None:
    assert SCRIPT.is_file()
    assert SCRIPT.stat().st_mode & 0o111


def test_help_exits_zero_and_prints_usage() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert "--base-url" in result.stdout


def test_unknown_argument_exits_two() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--no-such-flag"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2


def test_probes_against_unreachable_host_fail_closed() -> None:
    # Post-BR-23 the script requires --api-key/--tenant-id or --unauth-only;
    # pass --unauth-only so the test continues to exercise the unauth probe
    # failure propagation (the original intent of this test).
    result = subprocess.run(
        ["bash", str(SCRIPT), "--base-url", "http://127.0.0.1:1", "--timeout", "2", "--unauth-only"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    # The script names each failing path in stderr.
    assert "/health" in result.stderr
    assert "/version" in result.stderr


def test_auth_probe_sends_x_tenant_id_header() -> None:
    """The auth'd probe must send X-Tenant-ID (E15-3a-BR-12).

    `/recognition/clusters` resolves tenant via the basic header/query resolver
    (`get_tenant_id`), not via the auth context. So even tenant-scoped keys must
    include `X-Tenant-ID` or the route returns 400 `tenant_id is required`.
    The smoke script must pass the canary tenant alongside the API key, and
    document the `--tenant-id` / `ACX_SMOKE_TENANT_ID` operator surface.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    assert "X-Tenant-ID:" in text, "auth probe must set X-Tenant-ID header"
    assert "--tenant-id" in text, "CLI must expose --tenant-id flag"
    assert "ACX_SMOKE_TENANT_ID" in text, "env override must be documented"


def test_missing_api_key_without_unauth_opt_in_exits_two() -> None:
    """E15-3a-BR-23: missing auth credentials must fail argument validation.

    If the script is invoked without --api-key or --tenant-id and without an
    explicit --unauth-only opt-in, the authenticated path is the only probe
    that exercises the plugin-facing contract; skipping it silently while
    the unauth probes are 200 would let a broken auth path pass the release
    gate. Fail with exit 2 (invalid arguments) before any network call so
    the operator sees the misconfiguration immediately.
    """
    result = subprocess.run(
        ["bash", str(SCRIPT), "--base-url", "https://example.invalid", "--timeout", "1"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, (result.returncode, result.stderr, result.stdout)
    combined = result.stderr + result.stdout
    assert "api-key" in combined.lower() or "tenant-id" in combined.lower()
    assert "unauth-only" in combined.lower() or "--unauth-only" in combined


def test_unauth_only_opt_in_allows_missing_auth_credentials() -> None:
    """E15-3a-BR-23: --unauth-only acknowledges the skip explicitly.

    When operators legitimately want to probe only public surfaces (e.g. in
    a pre-auth deploy), --unauth-only must be the documented opt-in. With
    the flag set, the script may exit 1 because of the unreachable host but
    must NOT exit 2 for missing credentials, and must not FAIL on an auth
    probe path it is no longer running.
    """
    result = subprocess.run(
        ["bash", str(SCRIPT), "--base-url", "http://127.0.0.1:1", "--timeout", "2", "--unauth-only"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 2, (result.stderr, result.stdout)
    combined = result.stderr + result.stdout
    assert "FAIL /recognition/clusters" not in combined


def test_unauth_only_flag_documented_in_help() -> None:
    """Operators must see --unauth-only in the usage output."""
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "--unauth-only" in result.stdout


def test_probe_list_documents_four_core_paths() -> None:
    """The probe list must reference real backend routes (E15-3a-BR-08, BR-11).

    `/recognition/settings/test` and `/recognition/describe-minimal` were
    invented in the original BR-04 slice. `/recognition/health` was a real
    route on the April-1st prod image but was removed in commit 6e475cfe
    (E15-2 Slice 2.5b consolidated the health surface to /health + /ready +
    /health/detailed). Replace it with /ready, the canonical readiness
    probe per the consolidated surface.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    for path in ("/health", "/ready", "/version", "/recognition/clusters"):
        assert path in text, f"expected {path} in prod-smoke.sh"
    for bogus in (
        "/recognition/settings/test",
        "/recognition/describe-minimal",
        "/recognition/health",
    ):
        assert bogus not in text, f"removed/bogus path {bogus} must not be in prod-smoke.sh"
