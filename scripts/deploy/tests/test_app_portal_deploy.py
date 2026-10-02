"""Contract tests for scripts/deploy/app-portal.sh (APP-1 app host).

Filesystem-only: stub caddy/docker on PATH. Never SSH to the OCI host.
"""

from __future__ import annotations

import os
import re
import shlex
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "deploy" / "app-portal.sh"
SNIPPET = REPO_ROOT / "infra" / "oci" / "app" / "Caddyfile.app"
OVERLAY = REPO_ROOT / "infra" / "oci" / "app" / "docker-compose.app.yml"
ENV_EXAMPLE = REPO_ROOT / "infra" / "oci" / "app" / "env.example"
RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "app-portal-deploy.md"
LIVE_CADDY_SRC = REPO_ROOT / "apps" / "prototype-description-service" / "Caddyfile"

EXISTING_HOSTS = (
    "api.altcontext.com",
    "staging.api.altcontext.com",
    "dev.api.altcontext.com",
    "fir.dev.api.altcontext.com",
    "demo.altcontext.com",
    "129-213-40-111.sslip.io",
    "dl.darce.xyz",
)

SECRET_MARKERS = (
    "pk_live_",
    "pk_test_",
    "sk_live_",
    "sk_test_",
    "CLERK_SECRET_KEY",
    "POLAR_ACCESS_TOKEN",
    "POLAR_WEBHOOK_SECRET",
    "RECOGNITION_ADMIN_TOKEN",
)


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _write_frontend(root: Path, *, index: str = "<!doctype html><html><body>app</body></html>") -> Path:
    dist = root / "frontend-dist"
    assets = dist / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text(index, encoding="utf-8")
    (assets / "index.js").write_text("console.log('app-portal');\n", encoding="utf-8")
    return dist


def _write_live_caddy(path: Path, body: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if body is not None else LIVE_CADDY_SRC.read_text(encoding="utf-8"), encoding="utf-8")


def _write_caddy_compose(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("services:\n  caddy:\n    image: caddy:2\n", encoding="utf-8")
    return path


def _caddy_stub(log_path: str, *, fail: bool = False) -> str:
    exit_code = 1 if fail else 0
    return (
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"printf 'caddy' >> {log_path}\n"
        f"printf ' %q' \"$@\" >> {log_path}\n"
        f"printf '\\n' >> {log_path}\n"
        f"if [ {exit_code} -ne 0 ]; then\n"
        "  exit 1\n"
        "fi\n"
        "exit 0\n"
    )


def _docker_stub(log_path: str, compose_marker: str, *, fail_first_reload: bool = False) -> str:
    compose_marker_quoted = shlex.quote(compose_marker)
    reload_failure_marker = shlex.quote(f"{compose_marker}.failed-first-reload")
    failure_rule = (
        f'  if [ "$compose_reload" -eq 1 ] && [ ! -e {reload_failure_marker} ]; then\n'
        f'    : > {reload_failure_marker}\n'
        "    exit 1\n"
        "  fi\n"
        if fail_first_reload else ""
    )
    return (
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"printf 'docker' >> {log_path}\n"
        f"printf ' %q' \"$@\" >> {log_path}\n"
        f"printf '\\n' >> {log_path}\n"
        'if [ "${1:-}" = "compose" ]; then\n'
        "  compose_up=0\n"
        "  compose_reload=0\n"
        '  for arg in "$@"; do\n'
        '    [ "$arg" = "up" ] && compose_up=1\n'
        '    [ "$arg" = "reload" ] && compose_reload=1\n'
        "  done\n"
        f'  [ "$compose_up" -eq 0 ] || : > {compose_marker_quoted}\n'
        + failure_rule
        + "fi\n"
        + "exit 0\n"
    )


def _expected_compose_reload(backend_root: Path, overlay: Path | None = None) -> list[str]:
    argv = ["docker", "compose", "-f", str(backend_root / "docker-compose.caddy.yml")]
    if overlay is not None:
        argv.extend(["-f", str(overlay)])
    argv.extend(
        [
            "exec", "-T", "caddy", "caddy", "reload", "--config",
            "/etc/caddy/Caddyfile", "--adapter", "caddyfile",
        ]
    )
    return argv


def _compose_reload_calls(tmp_path: Path) -> list[list[str]]:
    calls = []
    for line in _log(tmp_path).splitlines():
        argv = shlex.split(line)
        if argv[:2] == ["docker", "compose"] and "exec" in argv and "reload" in argv:
            calls.append(argv)
    return calls


def _run(
    tmp_path: Path,
    *,
    args: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
    frontend: Path | None | str = "",
    live_caddy: Path | None | str = "",
    upstream: str | None = "prod-api:8000",
    hostname: str | None = "app.altcontext.com",
    caddy_fail: bool = False,
    docker_fail_first_reload: bool = False,
    fail_mv_dest: Path | None = None,
    include_caddy: bool = True,
    include_docker: bool = True,
    timeout: int = 20,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "commands.log"
    log_path = shlex.quote(str(log))
    app_root = tmp_path / "opt" / "acx-backend" / "app"
    app_root.mkdir(parents=True, exist_ok=True)
    backend_root = tmp_path / "opt" / "acx-backend"
    backend_root.mkdir(parents=True, exist_ok=True)
    caddy_compose = backend_root / "docker-compose.caddy.yml"
    if not caddy_compose.exists():
        _write_caddy_compose(caddy_compose)
    compose_marker = tmp_path / "compose-applied"

    if include_caddy:
        _write_executable(
            bin_dir / "caddy",
            _caddy_stub(log_path, fail=caddy_fail),
        )
    if include_docker:
        _write_executable(
            bin_dir / "docker",
            _docker_stub(
                log_path,
                str(compose_marker),
                fail_first_reload=docker_fail_first_reload,
            ),
        )
    health = bin_dir / "health-check"
    _write_executable(health, "#!/usr/bin/env bash\nexit 0\n")
    if fail_mv_dest is not None:
        dest = shlex.quote(str(fail_mv_dest))
        _write_executable(
            bin_dir / "mv",
            "#!/usr/bin/env bash\n"
            "set -u\n"
            'dest="${@: -1}"\n'
            f'if [ "$dest" = {dest} ]; then\n'
            '  echo "ERROR: simulated mv failure" >&2\n'
            "  exit 1\n"
            "fi\n"
            'exec /bin/mv "$@"\n',
        )

    if live_caddy is None:
        caddy_path = None
    elif live_caddy == "":
        caddy_path = backend_root / "Caddyfile"
        _write_live_caddy(caddy_path)
    else:
        caddy_path = Path(live_caddy)
        if not caddy_path.exists():
            _write_live_caddy(caddy_path)

    if frontend is None:
        frontend_path = None
    elif frontend == "":
        frontend_path = _write_frontend(tmp_path)
    else:
        frontend_path = Path(frontend)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    env["APP_ROOT"] = str(app_root)
    env["APP_WWW"] = str(app_root / "www")
    env["CADDY_COMPOSE"] = str(caddy_compose)
    env.pop("DRY_RUN", None)
    env.pop("APP_PORTAL_APPLY", None)
    env.pop("FRONTEND_DIST", None)
    env.pop("CADDYFILE", None)
    env.pop("APP_UPSTREAM", None)
    env.pop("APP_HOSTNAME", None)
    env.pop("SSH", None)
    env.pop("OCI_HOST", None)

    if caddy_path is not None:
        env["CADDYFILE"] = str(caddy_path)
    if frontend_path is not None:
        env["FRONTEND_DIST"] = str(frontend_path)
    if upstream is not None:
        env["APP_UPSTREAM"] = upstream
    if hostname is not None:
        env["APP_HOSTNAME"] = hostname
    env["APP_SNIPPET"] = str(SNIPPET)
    env["APP_OVERLAY"] = str(OVERLAY)
    env["APP_APPROVED_ROOTS"] = str(backend_root)
    env["APP_RELOAD_CMD"] = ""
    env["APP_HEALTH_CMD"] = str(health)
    if extra_env:
        env.update(extra_env)

    argv = ["bash", str(SCRIPT)]
    if args:
        argv.extend(args)

    return subprocess.run(
        argv,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _log(tmp_path: Path) -> str:
    path = tmp_path / "commands.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _tree_files(root: Path) -> set[str]:
    if not root.exists():
        return set()
    return {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}


def test_owned_artifacts_exist() -> None:
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    assert SNIPPET.is_file(), f"missing {SNIPPET}"
    assert OVERLAY.is_file(), f"missing {OVERLAY}"
    assert ENV_EXAMPLE.is_file(), f"missing {ENV_EXAMPLE}"
    assert RUNBOOK.is_file(), f"missing {RUNBOOK}"


def test_default_is_dry_run_and_side_effect_free(tmp_path: Path) -> None:
    caddy_path = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(caddy_path)
    _write_caddy_compose(caddy_path.parent / "docker-compose.caddy.yml")
    before = caddy_path.read_text(encoding="utf-8")
    before_files = _tree_files(tmp_path / "opt")
    result = _run(tmp_path, live_caddy=caddy_path)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "dry-run" in output.lower() or "plan:" in output.lower(), output
    assert caddy_path.read_text(encoding="utf-8") == before
    assert _tree_files(tmp_path / "opt") == before_files
    assert _log(tmp_path) == ""
    assert not (tmp_path / "opt" / "acx-backend" / "app" / "www").exists()


def test_explicit_dry_run_does_not_copy_frontend(tmp_path: Path) -> None:
    result = _run(tmp_path, args=["--dry-run"])
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "app.altcontext.com" in output
    assert "prod-api:8000" in output
    assert not (tmp_path / "opt" / "acx-backend" / "app" / "www").exists()
    assert _log(tmp_path) == ""


def test_apply_refuses_missing_frontend(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    result = _run(tmp_path, args=["--apply"], frontend=None, live_caddy=live)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "FRONTEND_DIST" in output
    assert live.read_text(encoding="utf-8") == before
    assert _log(tmp_path) == ""


def test_apply_refuses_empty_index(tmp_path: Path) -> None:
    dist = tmp_path / "empty-dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("", encoding="utf-8")
    (dist / "assets" / "index.js").write_text("x\n", encoding="utf-8")
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    result = _run(tmp_path, args=["--apply"], frontend=dist, live_caddy=live)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "index.html" in output
    assert live.read_text(encoding="utf-8") == before


def test_apply_refuses_missing_assets(tmp_path: Path) -> None:
    dist = tmp_path / "no-assets"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><html></html>\n", encoding="utf-8")
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    result = _run(tmp_path, args=["--apply"], frontend=dist, live_caddy=live)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "assets" in output.lower()
    assert live.read_text(encoding="utf-8") == before


def test_apply_refuses_path_traversal(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    result = _run(
        tmp_path,
        args=["--apply"],
        frontend=tmp_path / "frontend-dist" / ".." / "frontend-dist",
        live_caddy=live,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "traversal" in output.lower() or "unsafe" in output.lower() or ".." in output
    assert live.read_text(encoding="utf-8") == before
    assert _log(tmp_path) == ""


def test_apply_refuses_unsafe_shell_values(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    result = _run(
        tmp_path,
        args=["--apply"],
        live_caddy=live,
        extra_env={"APP_UPSTREAM": "prod-api:8000;reboot"},
        upstream=None,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "unsafe" in output.lower() or "APP_UPSTREAM" in output
    assert live.read_text(encoding="utf-8") == before
    assert _log(tmp_path) == ""


def test_apply_refuses_empty_upstream(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    result = _run(tmp_path, args=["--apply"], live_caddy=live, extra_env={"APP_UPSTREAM": ""}, upstream=None)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "APP_UPSTREAM" in output
    assert live.read_text(encoding="utf-8") == before


def test_apply_refuses_protected_existing_hostname(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    result = _run(tmp_path, args=["--apply"], live_caddy=live, hostname="api.altcontext.com")
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "api.altcontext.com" in output
    assert live.read_text(encoding="utf-8") == before
    assert "reverse_proxy prod-api:8000" in live.read_text(encoding="utf-8")


def test_apply_merges_vhost_preserves_existing_hosts_and_copies_frontend(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    result = _run(tmp_path, args=["--apply"], live_caddy=live)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    updated = live.read_text(encoding="utf-8")
    for host in EXISTING_HOSTS:
        assert host in updated, host
    assert "app.altcontext.com {" in updated
    assert "handle /portal*" not in updated
    assert "@portal path /portal /portal/*" in updated
    assert "handle @portal" in updated
    assert "reverse_proxy prod-api:8000" in updated
    www = tmp_path / "opt" / "acx-backend" / "app" / "www"
    assert (www / "index.html").is_file()
    assert (www / "index.html").stat().st_size > 0
    assert any((www / "assets").iterdir())
    overlay_dest = tmp_path / "opt" / "acx-backend" / "app" / "docker-compose.app.yml"
    overlay_text = overlay_dest.read_text(encoding="utf-8")
    assert str(www) in overlay_text
    assert f"{www}:/srv/app-portal" in overlay_text or f"{www}:/srv/app-portal:ro" in overlay_text
    assert "__APP_WWW__" not in overlay_text
    log = _log(tmp_path)
    assert "caddy" in log
    assert "validate" in log
    assert not any(line.startswith("caddy reload ") for line in log.splitlines())
    assert _compose_reload_calls(tmp_path) == [
        _expected_compose_reload(tmp_path / "opt" / "acx-backend", overlay_dest)
    ]
    assert "ssh" not in log
    rollback_dir = tmp_path / "opt" / "acx-backend" / "app" / "rollback"
    assert rollback_dir.is_dir()
    backups = list(rollback_dir.glob("Caddyfile.*"))
    assert backups, f"missing rollback artifact in {list(rollback_dir.iterdir())}"
    rollback_text = backups[0].read_text(encoding="utf-8")
    assert "app.altcontext.com {" not in rollback_text
    assert "api.altcontext.com {" in rollback_text


def test_apply_mounts_static_root_before_live_health_check(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    marker = tmp_path / "compose-applied"
    log_path = shlex.quote(str(tmp_path / "commands.log"))
    health = tmp_path / "bin" / "health-requires-compose"
    health.parent.mkdir()
    _write_executable(
        health,
        "#!/usr/bin/env bash\n"
        f"[ -f {shlex.quote(str(marker))} ] || exit 1\n"
        f"printf 'health\\n' >> {log_path}\n",
    )

    result = _run(
        tmp_path,
        args=["--apply"],
        live_caddy=live,
        extra_env={"APP_HEALTH_CMD": str(health)},
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    log_lines = _log(tmp_path).splitlines()
    compose_index = next(i for i, line in enumerate(log_lines) if line.startswith("docker compose ") and " up -d" in line)
    reload_index = next(
        i for i, line in enumerate(log_lines)
        if line.startswith("docker compose ") and " exec -T caddy caddy reload " in line
    )
    health_index = log_lines.index("health")
    assert "docker-compose.caddy.yml" in log_lines[compose_index]
    assert "docker-compose.app.yml" in log_lines[compose_index]
    assert compose_index < reload_index < health_index
    overlay = tmp_path / "opt" / "acx-backend" / "app" / "docker-compose.app.yml"
    assert shlex.split(log_lines[reload_index]) == _expected_compose_reload(
        tmp_path / "opt" / "acx-backend", overlay
    )
    assert not any(line.startswith("caddy reload ") for line in log_lines)


def test_apply_failed_validation_leaves_live_config_and_www_intact(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    www = tmp_path / "opt" / "acx-backend" / "app" / "www"
    www.mkdir(parents=True)
    (www / "keep.txt").write_text("active\n", encoding="utf-8")
    result = _run(tmp_path, args=["--apply"], live_caddy=live, caddy_fail=True)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "validate" in output.lower() or "caddy" in output.lower()
    assert live.read_text(encoding="utf-8") == before
    assert (www / "keep.txt").read_text(encoding="utf-8") == "active\n"
    assert not (www / "index.html").exists()
    for host in EXISTING_HOSTS:
        assert host in live.read_text(encoding="utf-8")


def test_apply_is_idempotent_for_existing_app_vhost(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    first = _run(tmp_path, args=["--apply"], live_caddy=live)
    assert first.returncode == 0, first.stdout + first.stderr
    once = live.read_text(encoding="utf-8")
    second = _run(tmp_path, args=["--apply"], live_caddy=live, extra_env={"APP_UPSTREAM": "prod-api:8000"})
    assert second.returncode == 0, second.stdout + second.stderr
    twice = live.read_text(encoding="utf-8")
    assert twice.count("app.altcontext.com {") == 1
    assert once.count("app.altcontext.com {") == 1
    for host in EXISTING_HOSTS:
        assert host in twice


def test_snippet_denies_admin_and_unrelated_api_surfaces() -> None:
    text = SNIPPET.read_text(encoding="utf-8")
    assert "app.altcontext.com {" in text
    assert "@admin path /admin /admin/*" in text
    assert "respond @admin 404" in text
    assert "/portal" in text
    assert "handle /portal*" not in text
    assert "@portal path /portal /portal/*" in text
    assert "handle @portal" in text
    assert "reverse_proxy" in text
    for surface in ("/recognition", "/roster", "/scene", "/billing/webhooks", "/health"):
        assert surface in text, surface
    assert "file_server" in text
    assert "try_files" in text


def test_artifacts_contain_no_vendor_credentials() -> None:
    paths = [SCRIPT, SNIPPET, OVERLAY, ENV_EXAMPLE, RUNBOOK]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for marker in SECRET_MARKERS:
            assert marker.lower() not in lowered, f"{path} contains {marker}"
        assert "ssh " not in lowered
        assert "scp " not in lowered


def test_script_does_not_open_production_ssh() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"\bssh\b", text)
    assert not re.search(r"\bscp\b", text)
    assert "129.213.40.111" not in text


def test_runbook_documents_later_integration_and_env_ownership() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "app.altcontext.com" in text
    assert "129.213.40.111" in text
    assert "/opt/acx-backend/app/www" in text
    assert "docker-compose.caddy.yml" in text
    assert "docker-compose.app.yml" in text
    assert "/srv/app-portal" in text
    assert "RECOGNITION_PORTAL_ENABLED" in text
    assert "/opt/acx-backend/prod/.env" in text
    assert "VITE_CLERK_PUBLISHABLE_KEY" in text
    assert "FRONTEND_DIST" in text
    assert "--apply" in text
    assert "dry-run" in text.lower()
    assert "do not" in text.lower() or "never" in text.lower()
    assert "symlink" in text.lower()
    assert "APP_APPROVED_ROOTS" in text
    assert "`/portal` plus `/portal/*`" in text or "path /portal /portal/*" in text
    assert "APP_HEALTH_CMD=/usr/local/bin/app-portal-health-check" in text
    assert "sudo install -m 0755 scripts/deploy/app-portal.sh /usr/local/bin/app-portal-health-check" in text
    assert "before frontend health runs" in text.lower()
    assert "https://app.altcontext.com/" in text
    assert "https://api.altcontext.com/ready" in text
    assert "local artifact checks" not in text
    assert "If reload is skipped" not in text
    assert "reload" in text.lower()
    assert "health" in text.lower()
    assert "atomic" in text.lower() or "rename" in text.lower()
    assert "trap" in text.lower() or "restor" in text.lower()
    lowered = text.lower()
    for marker in SECRET_MARKERS:
        assert marker.lower() not in lowered, marker


def test_checked_in_health_check_covers_both_https_endpoints(tmp_path: Path) -> None:
    health = tmp_path / "app-portal-health-check"
    _write_executable(health, SCRIPT.read_text(encoding="utf-8"))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl_log = tmp_path / "curl.log"
    curl = bin_dir / "curl"
    _write_executable(
        curl,
        "#!/usr/bin/env bash\n"
        'for url in "$@"; do :; done\n'
        'printf "%s\\n" "$url" >> "$CURL_LOG"\n'
        '[ "$url" = "${CURL_FAIL_URL:-}" ] && exit 22\n'
        "exit 0\n",
    )
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["CURL_LOG"] = str(curl_log)

    success = subprocess.run([str(health)], env=env, text=True, capture_output=True, check=False)
    assert success.returncode == 0, success.stdout + success.stderr
    assert curl_log.read_text(encoding="utf-8").splitlines() == [
        "https://app.altcontext.com/",
        "https://api.altcontext.com/ready",
    ]

    curl_log.unlink()
    failing_env = {**env, "CURL_FAIL_URL": "https://api.altcontext.com/ready"}
    failure = subprocess.run([str(health)], env=failing_env, text=True, capture_output=True, check=False)
    assert failure.returncode != 0, failure.stdout + failure.stderr
    assert curl_log.read_text(encoding="utf-8").splitlines() == [
        "https://app.altcontext.com/",
        "https://api.altcontext.com/ready",
    ]


def _prior_www(tmp_path: Path) -> Path:
    www = tmp_path / "opt" / "acx-backend" / "app" / "www"
    www.mkdir(parents=True, exist_ok=True)
    (www / "keep.txt").write_text("active\n", encoding="utf-8")
    return www


def test_apply_health_checks_selected_hostname(tmp_path: Path) -> None:
    health = tmp_path / "app-portal-health-check"
    _write_executable(health, SCRIPT.read_text(encoding="utf-8"))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl_log = tmp_path / "curl.log"
    _write_executable(
        bin_dir / "curl",
        "#!/usr/bin/env bash\n"
        'for url in "$@"; do :; done\n'
        'printf "%s\\n" "$url" >> "$CURL_LOG"\n'
        '[ "$url" = "https://preview.altcontext.com/" ] && exit 22\n'
        "exit 0\n",
    )
    result = _run(
        tmp_path,
        args=["--apply"],
        hostname="preview.altcontext.com",
        extra_env={"APP_HEALTH_CMD": str(health), "CURL_LOG": str(curl_log)},
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert curl_log.read_text(encoding="utf-8").splitlines() == [
        "https://preview.altcontext.com/", "https://api.altcontext.com/ready",
    ]
    assert "applied:" not in result.stdout


def test_recovery_refuses_changed_base_compose_without_mutation(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    hook = tmp_path / "interrupt.sh"
    hook.write_text(
        "sync() {\n"
        '  /bin/sync "$@" || return $?\n'
        '  if [ "${@: -1}" = "$CADDYFILE" ]; then kill -KILL "$BASHPID"; fi\n'
        "}\n",
        encoding="utf-8",
    )
    interrupted = _run(tmp_path, args=["--apply"], extra_env={"BASH_ENV": str(hook)})
    assert interrupted.returncode == -9, interrupted.stdout + interrupted.stderr
    app_root = live.parent / "app"
    journal = app_root / "activation.journal"
    before_caddy = live.read_bytes()
    before_journal = journal.read_bytes()
    before_log = _log(tmp_path)
    alternate = _write_caddy_compose(live.parent / "alternate-compose.yml")
    result = _run(
        tmp_path, args=["--apply"], live_caddy=live,
        extra_env={"BASH_ENV": "", "CADDY_COMPOSE": str(alternate)},
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "journal paths do not match" in result.stderr
    assert live.read_bytes() == before_caddy
    assert journal.read_bytes() == before_journal
    assert _log(tmp_path) == before_log
    assert f"caddy_compose={live.parent / 'docker-compose.caddy.yml'}\n" in journal.read_text()


def test_runbook_first_deploy_rollback_uses_base_only_compose() -> None:
    rollback = RUNBOOK.read_text(encoding="utf-8").split("## Rollback", 1)[1]
    assert "no prior overlay" in rollback
    assert "docker compose -f docker-compose.caddy.yml up -d" in rollback
    assert "docker compose -f docker-compose.caddy.yml exec -T caddy" in rollback


def test_apply_refuses_filesystem_root_paths(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    for name, value in (
        ("APP_WWW", "/"),
        ("APP_ROOT", "/"),
        ("APP_FRONTEND_ROOT", "/"),
        ("CADDYFILE", "/"),
    ):
        result = _run(tmp_path, args=["--apply"], live_caddy=live, extra_env={name: value})
        output = result.stdout + result.stderr
        assert result.returncode != 0, output
        assert "root" in output.lower() or name in output, output
        assert live.read_text(encoding="utf-8") == before
        assert _log(tmp_path) == ""


def test_apply_refuses_symlink_caddyfile(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    link = tmp_path / "opt" / "acx-backend" / "Caddyfile.link"
    link.symlink_to(live)
    result = _run(
        tmp_path,
        args=["--apply"],
        live_caddy=live,
        extra_env={"CADDYFILE": str(link)},
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "symlink" in output.lower(), output
    assert live.read_text(encoding="utf-8") == before
    assert link.is_symlink()
    assert _log(tmp_path) == ""


def test_apply_refuses_symlink_component_in_app_root(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    real_app = tmp_path / "opt" / "acx-backend" / "app"
    link_app = tmp_path / "opt" / "acx-backend" / "linked-app"
    link_app.symlink_to(real_app)
    result = _run(
        tmp_path,
        args=["--apply"],
        live_caddy=live,
        extra_env={
            "APP_ROOT": str(link_app),
            "APP_WWW": str(link_app / "www"),
        },
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "symlink" in output.lower(), output
    assert live.read_text(encoding="utf-8") == before
    assert not (real_app / "www" / "index.html").exists()


def test_apply_refuses_path_outside_approved_roots(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    outside = tmp_path / "outside" / "app"
    outside.mkdir(parents=True)
    result = _run(
        tmp_path,
        args=["--apply"],
        live_caddy=live,
        extra_env={"APP_ROOT": str(outside), "APP_WWW": str(outside / "www")},
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "approved" in output.lower() or "outside" in output.lower(), output
    assert live.read_text(encoding="utf-8") == before
    assert not (outside / "www").exists()
    assert list(outside.iterdir()) == []


def test_apply_refuses_caddyfile_directory(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    live.mkdir(parents=True)
    result = _run(tmp_path, args=["--apply"], live_caddy=live)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "regular file" in output.lower() or "not a file" in output.lower() or "directory" in output.lower()
    assert live.is_dir()
    assert list(live.iterdir()) == []


def test_overlay_template_uses_www_placeholder() -> None:
    text = OVERLAY.read_text(encoding="utf-8")
    assert "__APP_WWW__:/srv/app-portal" in text
    assert "/opt/acx-backend/app/www:/srv/app-portal" not in text


def test_apply_failed_reload_restores_caddy_www_and_overlay(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    www = _prior_www(tmp_path)
    overlay_dest = tmp_path / "opt" / "acx-backend" / "app" / "docker-compose.app.yml"
    overlay_dest.write_text("services: {}\n", encoding="utf-8")
    result = _run(
        tmp_path,
        args=["--apply"],
        live_caddy=live,
        docker_fail_first_reload=True,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "reload" in output.lower(), output
    assert "applied:" not in result.stdout
    assert live.read_text(encoding="utf-8") == before
    assert (www / "keep.txt").read_text(encoding="utf-8") == "active\n"
    assert not (www / "index.html").exists()
    assert overlay_dest.read_text(encoding="utf-8") == "services: {}\n"
    expected_reload = _expected_compose_reload(tmp_path / "opt" / "acx-backend", overlay_dest)
    assert _compose_reload_calls(tmp_path) == [expected_reload, expected_reload]
    assert not any(line.startswith("caddy reload ") for line in _log(tmp_path).splitlines())
    for host in EXISTING_HOSTS:
        assert host in live.read_text(encoding="utf-8")


def test_first_apply_reload_failure_rolls_back_with_base_compose(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    app_root = tmp_path / "opt" / "acx-backend" / "app"
    overlay_dest = app_root / "docker-compose.app.yml"
    www = app_root / "www"

    result = _run(
        tmp_path,
        args=["--apply"],
        live_caddy=live,
        include_caddy=False,
        docker_fail_first_reload=True,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert live.read_text(encoding="utf-8") == before
    assert not overlay_dest.exists()
    assert not www.exists()
    assert _compose_reload_calls(tmp_path) == [
        _expected_compose_reload(tmp_path / "opt" / "acx-backend", overlay_dest),
        _expected_compose_reload(tmp_path / "opt" / "acx-backend"),
    ]


def test_apply_default_reload_uses_compose_without_host_caddy(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    result = _run(tmp_path, args=["--apply"], live_caddy=live, include_caddy=False)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    overlay = tmp_path / "opt" / "acx-backend" / "app" / "docker-compose.app.yml"
    assert _compose_reload_calls(tmp_path) == [
        _expected_compose_reload(tmp_path / "opt" / "acx-backend", overlay)
    ]
    assert any(line.startswith("docker run ") and "validate" in line for line in _log(tmp_path).splitlines())
    assert not any(line.startswith("caddy ") for line in _log(tmp_path).splitlines())


def test_apply_requires_explicit_live_health_check(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_bytes()
    result = _run(tmp_path, args=["--apply"], live_caddy=live, extra_env={"APP_HEALTH_CMD": ""})
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "APP_HEALTH_CMD" in output
    assert "applied:" not in output
    assert live.read_bytes() == before


def test_docker_validation_with_explicit_reload_succeeds(tmp_path: Path) -> None:
    reload_cmd = tmp_path / "reload-edge"
    marker = tmp_path / "reloaded"
    _write_executable(reload_cmd, f"#!/bin/sh\ntouch {shlex.quote(str(marker))}\n")
    result = _run(
        tmp_path, args=["--apply"], include_caddy=False,
        extra_env={"APP_RELOAD_CMD": str(reload_cmd)},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "docker run" in _log(tmp_path)
    assert marker.exists()
    assert _compose_reload_calls(tmp_path) == []


def test_successful_applies_reclaim_old_snapshot_sets(tmp_path: Path) -> None:
    app_root = tmp_path / "opt" / "acx-backend" / "app"
    rollback = app_root / "rollback"
    rollback.mkdir(parents=True)
    for stamp in (1, 2, 3):
        (rollback / f"Caddyfile.{stamp}").write_text("old config")
        (rollback / f"www.{stamp}").mkdir()
        (rollback / f"www.{stamp}" / "index.html").write_text("old frontend")
        (rollback / f"docker-compose.app.yml.{stamp}").write_text("old overlay")
    unrelated = rollback / "operator-notes"
    unrelated.write_text("keep")
    operator_caddy = rollback / "Caddyfile.operator-copy.1"
    operator_caddy.write_text("operator caddy copy")
    operator_www = rollback / "www.backup.2"
    operator_www.mkdir()
    (operator_www / "keep.txt").write_text("operator frontend copy")
    operator_overlay = rollback / "docker-compose.app.yml.local.3"
    operator_overlay.write_text("operator overlay copy")
    operator_caddy_suffix = rollback / "Caddyfile.4.bak"
    operator_caddy_suffix.write_text("operator caddy backup")
    wrong_caddy_type = rollback / "Caddyfile.9001"
    wrong_caddy_type.mkdir()
    wrong_www_type = rollback / "www.9002"
    wrong_www_type.write_text("operator file")
    wrong_overlay_type = rollback / "docker-compose.app.yml.9003"
    wrong_overlay_type.mkdir()
    _prior_www(tmp_path)
    (app_root / "docker-compose.app.yml").write_text("services: {}\n")
    for _ in range(3):
        # Freeze the clock to exercise back-to-back snapshot names as well.
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        _write_executable(bin_dir / "date", "#!/bin/sh\nprintf '100\\n'\n")
        live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
        if not live.exists():
            _write_live_caddy(live)
        before = live.read_bytes()
        prior_index = app_root / "www" / "index.html"
        prior_contents = prior_index.read_bytes() if prior_index.exists() else None
        result = _run(tmp_path, args=["--apply"], live_caddy=live)
        assert result.returncode == 0, result.stdout + result.stderr
        caddy_backups = [
            p for p in rollback.glob("Caddyfile.*")
            if re.fullmatch(r"Caddyfile\.\d+", p.name) and p.is_file()
        ]
        assert len(caddy_backups) == 1
        stamp = caddy_backups[0].name.split(".")[-1]
        assert caddy_backups[0].read_bytes() == before
        assert {p.name for p in rollback.iterdir()} == {
            f"Caddyfile.{stamp}", f"www.{stamp}", f"docker-compose.app.yml.{stamp}", "operator-notes",
            "Caddyfile.operator-copy.1", "www.backup.2", "docker-compose.app.yml.local.3",
            "Caddyfile.4.bak", "Caddyfile.9001", "www.9002", "docker-compose.app.yml.9003",
        }
        assert operator_caddy.read_text() == "operator caddy copy"
        assert (operator_www / "keep.txt").read_text() == "operator frontend copy"
        assert operator_overlay.read_text() == "operator overlay copy"
        assert operator_caddy_suffix.read_text() == "operator caddy backup"
        assert wrong_caddy_type.is_dir()
        assert wrong_www_type.read_text() == "operator file"
        assert wrong_overlay_type.is_dir()
        if prior_contents is not None:
            assert (rollback / f"www.{stamp}" / "index.html").read_bytes() == prior_contents
        assert unrelated.read_text() == "keep"
        assert not (app_root / "activation.journal").exists()


def test_apply_refuses_symlink_rollback_directory(tmp_path: Path) -> None:
    app_root = tmp_path / "opt" / "acx-backend" / "app"
    app_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    snapshot = outside / "Caddyfile.1"
    snapshot.write_text("do not delete")
    (app_root / "rollback").symlink_to(outside, target_is_directory=True)
    result = _run(tmp_path, args=["--apply"])
    assert result.returncode != 0, result.stdout + result.stderr
    assert "symlink" in (result.stdout + result.stderr).lower()
    assert {p.name for p in outside.iterdir()} == {"Caddyfile.1"}
    assert snapshot.read_text() == "do not delete"


def test_apply_failed_health_restores_caddy_www_and_overlay(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    www = _prior_www(tmp_path)
    overlay_dest = tmp_path / "opt" / "acx-backend" / "app" / "docker-compose.app.yml"
    overlay_dest.write_text("services: {}\n", encoding="utf-8")
    rollback = overlay_dest.parent / "rollback"
    rollback.mkdir()
    old_snapshot = rollback / "Caddyfile.1"
    old_snapshot.write_text("previous recovery config")
    health = tmp_path / "opt" / "acx-backend" / "health-fail"
    _write_executable(health, "#!/usr/bin/env bash\nexit 1\n")
    result = _run(
        tmp_path,
        args=["--apply"],
        live_caddy=live,
        extra_env={"APP_HEALTH_CMD": str(health)},
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "health" in output.lower(), output
    assert "applied:" not in result.stdout
    assert live.read_text(encoding="utf-8") == before
    assert (www / "keep.txt").read_text(encoding="utf-8") == "active\n"
    assert not (www / "index.html").exists()
    assert overlay_dest.read_text(encoding="utf-8") == "services: {}\n"
    assert old_snapshot.read_text() == "previous recovery config"
    compose_up_lines = [line for line in _log(tmp_path).splitlines() if " compose " in line and " up -d" in line]
    assert len(compose_up_lines) == 2, _log(tmp_path)
    current_backups = [p for p in rollback.glob("Caddyfile.*") if p != old_snapshot]
    assert len(current_backups) == 1
    assert current_backups[0].read_text() == before


def test_apply_failed_www_move_restores_caddyfile(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    www = _prior_www(tmp_path)
    result = _run(tmp_path, args=["--apply"], live_caddy=live, fail_mv_dest=www)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "mv" in output.lower() or "activation" in output.lower() or "move" in output.lower(), output
    assert "applied:" not in result.stdout
    assert live.read_text(encoding="utf-8") == before
    assert (www / "keep.txt").read_text(encoding="utf-8") == "active\n"


def test_apply_failed_overlay_promote_restores_prior_www_and_caddy(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    www = _prior_www(tmp_path)
    overlay_dest = tmp_path / "opt" / "acx-backend" / "app" / "docker-compose.app.yml"
    result = _run(tmp_path, args=["--apply"], live_caddy=live, fail_mv_dest=overlay_dest)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "applied:" not in result.stdout
    assert live.read_text(encoding="utf-8") == before
    assert (www / "keep.txt").read_text(encoding="utf-8") == "active\n"
    assert not overlay_dest.exists() or overlay_dest.read_text(encoding="utf-8") != OVERLAY.read_text(encoding="utf-8")


def test_dry_run_refuses_symlink_and_root_without_writes(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    _write_caddy_compose(live.parent / "docker-compose.caddy.yml")
    before_files = _tree_files(tmp_path / "opt")
    result = _run(tmp_path, extra_env={"APP_FRONTEND_ROOT": "/"})
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "root" in output.lower() or "APP_FRONTEND_ROOT" in output
    assert _tree_files(tmp_path / "opt") == before_files
    assert _log(tmp_path) == ""
