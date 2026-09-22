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


def _caddy_stub(log_path: str, *, fail: bool = False, fail_on: str | None = None) -> str:
    exit_code = 1 if fail else 0
    fail_on_lit = fail_on or ""
    return (
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"printf 'caddy' >> {log_path}\n"
        f"printf ' %q' \"$@\" >> {log_path}\n"
        f"printf '\\n' >> {log_path}\n"
        "cmd=\n"
        'for a in "$@"; do\n'
        '  case "$a" in\n'
        '    validate|reload|adapt) cmd="$a" ;;\n'
        "  esac\n"
        "done\n"
        f"if [ {exit_code} -ne 0 ]; then\n"
        "  exit 1\n"
        "fi\n"
        f'if [ -n "{fail_on_lit}" ] && [ "$cmd" = "{fail_on_lit}" ]; then\n'
        "  exit 1\n"
        "fi\n"
        "exit 0\n"
    )


def _docker_stub(log_path: str) -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"printf 'docker' >> {log_path}\n"
        f"printf ' %q' \"$@\" >> {log_path}\n"
        f"printf '\\n' >> {log_path}\n"
        "exit 0\n"
    )


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
    caddy_fail_on: str | None = None,
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

    if include_caddy:
        _write_executable(
            bin_dir / "caddy",
            _caddy_stub(log_path, fail=caddy_fail, fail_on=caddy_fail_on),
        )
    if include_docker:
        _write_executable(bin_dir / "docker", _docker_stub(log_path))
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
    assert "reload" in log
    assert "ssh" not in log
    rollback_dir = tmp_path / "opt" / "acx-backend" / "app" / "rollback"
    assert rollback_dir.is_dir()
    backups = list(rollback_dir.glob("Caddyfile.*"))
    assert backups, f"missing rollback artifact in {list(rollback_dir.iterdir())}"
    rollback_text = backups[0].read_text(encoding="utf-8")
    assert "app.altcontext.com {" not in rollback_text
    assert "api.altcontext.com {" in rollback_text


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
    assert "reload" in text.lower()
    assert "health" in text.lower()
    assert "atomic" in text.lower() or "rename" in text.lower()
    assert "trap" in text.lower() or "restor" in text.lower()
    lowered = text.lower()
    for marker in SECRET_MARKERS:
        assert marker.lower() not in lowered, marker


def _prior_www(tmp_path: Path) -> Path:
    www = tmp_path / "opt" / "acx-backend" / "app" / "www"
    www.mkdir(parents=True, exist_ok=True)
    (www / "keep.txt").write_text("active\n", encoding="utf-8")
    return www


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
    result = _run(tmp_path, args=["--apply"], live_caddy=live, caddy_fail_on="reload")
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "reload" in output.lower(), output
    assert "applied:" not in result.stdout
    assert live.read_text(encoding="utf-8") == before
    assert (www / "keep.txt").read_text(encoding="utf-8") == "active\n"
    assert not (www / "index.html").exists()
    assert overlay_dest.read_text(encoding="utf-8") == "services: {}\n"
    for host in EXISTING_HOSTS:
        assert host in live.read_text(encoding="utf-8")


def test_apply_failed_health_restores_caddy_www_and_overlay(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    www = _prior_www(tmp_path)
    overlay_dest = tmp_path / "opt" / "acx-backend" / "app" / "docker-compose.app.yml"
    overlay_dest.write_text("services: {}\n", encoding="utf-8")
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
    before_files = _tree_files(tmp_path / "opt")
    result = _run(tmp_path, extra_env={"APP_FRONTEND_ROOT": "/"})
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "root" in output.lower() or "APP_FRONTEND_ROOT" in output
    assert _tree_files(tmp_path / "opt") == before_files
    assert _log(tmp_path) == ""
