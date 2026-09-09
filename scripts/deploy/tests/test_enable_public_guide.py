"""Contract tests for scripts/deploy/enable-public-guide.sh (GUIDEROUTE-1).

Runs the operator enable script against stubbed `wp` and `curl` on PATH so
argv order and fail-closed checks are asserted without a WordPress install.
"""

from __future__ import annotations

import os
import shlex
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "deploy" / "enable-public-guide.sh"
DEFAULT_SITE = "https://guide.test"
DEFAULT_BODY = (
    '<main id="acx-public-guide" data-scope="recorded" data-example="bundled"></main>'
    '<script type="module" src="https://guide.test/assets/guide.js" id="acx-public-guide-js"></script>'
)
FALLBACK_ONLY_BODY = (
    '<main id="acx-public-guide">'
    '<p class="acx-public-guide__fallback" role="alert">'
    "The walkthrough could not load. Reload the page, or watch the recorded video on the case study page."
    "</p>"
    "</main>"
)


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _wp_stub_body(
    *,
    log_path: str,
    mutations_path: str,
    demo_enabled: str,
    prefix: str,
    fail_first_flush: bool = False,
    once_path: str = "",
) -> str:
    flush_fail = ""
    if fail_first_flush:
        flush_fail = (
            f"if [[ \"$joined\" == *'rewrite flush'* ]]; then\n"
            f"  if [[ ! -f {shlex.quote(once_path)} ]]; then\n"
            f"    printf '1' > {shlex.quote(once_path)}\n"
            f"    printf 'rewrite_flush\\n' >> {mutations_path}\n"
            "    exit 1\n"
            "  fi\n"
            "fi\n"
        )
    return (
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"printf {shlex.quote(prefix)} >> {log_path}\n"
        f"printf ' %q' \"$@\" >> {log_path}\n"
        f"printf '\\n' >> {log_path}\n"
        "joined=\"$*\"\n"
        f"if [[ \"$joined\" == *'option update acx_public_guide_enabled'* ]]; then\n"
        "  if [[ \"$joined\" == *'acx_public_guide_enabled 0'* ]]; then\n"
        f"    printf 'guide_disable\\n' >> {mutations_path}\n"
        "  else\n"
        f"    printf 'guide_enable\\n' >> {mutations_path}\n"
        "  fi\n"
        "fi\n"
        f"if [[ \"$joined\" == *'option update acx_public_demo_enabled'* ]]; then printf 'demo_enable\\n' >> {mutations_path}; fi\n"
        + flush_fail
        + f"if [[ \"$joined\" == *'rewrite flush'* ]]; then printf 'rewrite_flush\\n' >> {mutations_path}; fi\n"
        "if [[ \"$joined\" == *'option get acx_public_demo_enabled'* ]]; then\n"
        f"  printf '%s\\n' {shlex.quote(demo_enabled)}\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    )


def _docker_stub_body(*, log_path: str, mutations_path: str, demo_enabled: str) -> str:
    # Mimic `docker compose -f FILE run --rm --no-deps wpcli wp ...` and apply the
    # same mutation/option-get behaviour as the host wp stub to the wp argv.
    return (
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"printf 'docker' >> {log_path}\n"
        f"printf ' %q' \"$@\" >> {log_path}\n"
        f"printf '\\n' >> {log_path}\n"
        "wp_args=()\n"
        "seen_wpcli=0\n"
        "seen_wp=0\n"
        "for arg in \"$@\"; do\n"
        "  if [[ \"$seen_wp\" -eq 1 ]]; then wp_args+=(\"$arg\"); continue; fi\n"
        "  if [[ \"$seen_wpcli\" -eq 1 && \"$arg\" == wp ]]; then seen_wp=1; continue; fi\n"
        "  if [[ \"$arg\" == wpcli ]]; then seen_wpcli=1; continue; fi\n"
        "done\n"
        "joined=\"${wp_args[*]}\"\n"
        f"if [[ \"$joined\" == *'option update acx_public_guide_enabled'* ]]; then\n"
        "  if [[ \"$joined\" == *'acx_public_guide_enabled 0'* ]]; then\n"
        f"    printf 'guide_disable\\n' >> {mutations_path}\n"
        "  else\n"
        f"    printf 'guide_enable\\n' >> {mutations_path}\n"
        "  fi\n"
        "fi\n"
        f"if [[ \"$joined\" == *'option update acx_public_demo_enabled'* ]]; then printf 'demo_enable\\n' >> {mutations_path}; fi\n"
        f"if [[ \"$joined\" == *'rewrite flush'* ]]; then printf 'rewrite_flush\\n' >> {mutations_path}; fi\n"
        "if [[ \"$joined\" == *'option get acx_public_demo_enabled'* ]]; then\n"
        f"  printf '%s\\n' {shlex.quote(demo_enabled)}\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    )


def _run(
    tmp_path: Path,
    *,
    args: list[str] | None = None,
    wp_path: Path | None | str = "",
    site_url: str | None = DEFAULT_SITE,
    extra_env: dict[str, str] | None = None,
    curl_http_code: str = "200",
    curl_body: str = DEFAULT_BODY,
    demo_enabled: str = "0",
    include_site_url_flag: bool = True,
    include_wp: bool = True,
    include_docker: bool = False,
    compose_file: Path | None = None,
    curl_exit: int = 0,
    fail_first_flush: bool = False,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "commands.log"
    log_path = shlex.quote(str(log))
    mutations = tmp_path / "mutations.log"
    mutations_path = shlex.quote(str(mutations))
    once_path = str(tmp_path / "flush-failed-once")

    if include_wp:
        _write_executable(
            bin_dir / "wp",
            _wp_stub_body(
                log_path=log_path,
                mutations_path=mutations_path,
                demo_enabled=demo_enabled,
                prefix="wp",
                fail_first_flush=fail_first_flush,
                once_path=once_path,
            ),
        )
    if include_docker:
        _write_executable(
            bin_dir / "docker",
            _docker_stub_body(
                log_path=log_path,
                mutations_path=mutations_path,
                demo_enabled=demo_enabled,
            ),
        )
    _write_executable(
        bin_dir / "curl",
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"printf 'curl' >> {log_path}\n"
        f"printf ' %q' \"$@\" >> {log_path}\n"
        f"printf '\\n' >> {log_path}\n"
        "outfile=''\n"
        "format=''\n"
        "url=''\n"
        "while [[ $# -gt 0 ]]; do\n"
        "  case \"$1\" in\n"
        "    -o|--output) outfile=\"$2\"; shift 2 ;;\n"
        "    -w|--write-out) format=\"$2\"; shift 2 ;;\n"
        "    -D|--dump-header|-H|--header|--connect-timeout|--max-time|--max-redirs|--retry) shift 2 ;;\n"
        "    -s|--silent|-S|--show-error|-L|--location|-f|--fail|-I|--head|-k|--insecure) shift ;;\n"
        "    http://*|https://*) url=\"$1\"; shift ;;\n"
        "    *) shift ;;\n"
        "  esac\n"
        "done\n"
        f"body={shlex.quote(curl_body)}\n"
        f"code={shlex.quote(curl_http_code)}\n"
        "if [[ -n \"$outfile\" && \"$outfile\" != /dev/null ]]; then\n"
        "  printf '%s\\n' \"$body\" >\"$outfile\"\n"
        "fi\n"
        "if [[ -n \"$format\" ]]; then\n"
        "  printf '%s' \"${format//\\%{http_code\\}/$code}\"\n"
        "else\n"
        "  printf '%s' \"$body\"\n"
        "fi\n"
        f"exit {int(curl_exit)}\n",
    )

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["LC_ALL"] = "C"
    env.pop("ACX_RETAIN_PUBLIC_DEMO_DESCRIBE", None)
    env.pop("DRY_RUN", None)
    env.pop("SITE_URL", None)
    env.pop("ACX_WP_RUNNER", None)
    env.pop("COMPOSE_FILE", None)
    # Isolate auto-detect from a host DEMO_DIR such as /opt/acx-backend/demo.
    env["DEMO_DIR"] = str(tmp_path / "missing-demo-dir")
    if compose_file is not None:
        env["COMPOSE_FILE"] = str(compose_file)

    if wp_path is None:
        env.pop("WP_PATH", None)
    else:
        resolved_wp = tmp_path / "wp" if wp_path == "" else Path(wp_path)
        if isinstance(wp_path, str) and wp_path == "":
            resolved_wp.mkdir(exist_ok=True)
        env["WP_PATH"] = str(resolved_wp)

    env["CURL_HTTP_CODE"] = curl_http_code
    if extra_env:
        env.update(extra_env)

    argv = ["bash", str(SCRIPT)]
    if include_site_url_flag and site_url is not None:
        argv.extend(["--site-url", site_url])
    if args:
        argv.extend(args)

    return subprocess.run(
        argv,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )


def _log(tmp_path: Path) -> str:
    path = tmp_path / "commands.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _mutations(tmp_path: Path) -> str:
    path = tmp_path / "mutations.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_script_exists() -> None:
    assert SCRIPT.is_file(), f"missing {SCRIPT}"


def test_refuses_without_wp_path(tmp_path: Path) -> None:
    result = _run(tmp_path, wp_path=None, site_url=DEFAULT_SITE)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "WP_PATH" in output
    assert _mutations(tmp_path) == ""
    assert "wp " not in _log(tmp_path)
    assert "curl " not in _log(tmp_path)


def test_refuses_without_site_url(tmp_path: Path) -> None:
    result = _run(tmp_path, site_url=None, include_site_url_flag=False)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "site-url" in output or "SITE_URL" in output
    assert _mutations(tmp_path) == ""
    assert "wp " not in _log(tmp_path)
    assert "curl " not in _log(tmp_path)


def test_refuses_without_both_and_does_not_default_a_site(tmp_path: Path) -> None:
    result = _run(tmp_path, wp_path=None, site_url=None, include_site_url_flag=False)
    output = result.stdout + result.stderr
    log = _log(tmp_path)
    assert result.returncode != 0, output
    assert "demo.altcontext.com" not in output
    assert "demo.altcontext.com" not in log
    assert _mutations(tmp_path) == ""
    assert "wp " not in log
    assert "curl " not in log


def test_updates_option_then_flushes_rewrites(tmp_path: Path) -> None:
    result = _run(tmp_path)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    log = _log(tmp_path)
    wp_lines = [line for line in log.splitlines() if line.startswith("wp ")]
    update_indexes = [
        index
        for index, line in enumerate(wp_lines)
        if "option" in line and "update" in line and "acx_public_guide_enabled" in line and " 1" in line
    ]
    flush_indexes = [
        index for index, line in enumerate(wp_lines) if "rewrite" in line and "flush" in line and "--hard" in line
    ]
    assert update_indexes, log
    assert flush_indexes, log
    assert update_indexes[0] < flush_indexes[0], log
    wp_root = tmp_path / "wp"
    assert any(str(wp_root) in line for line in wp_lines), log
    assert f"{DEFAULT_SITE}/guide/" in log
    assert "acx_public_demo_enabled" in output
    mutations = _mutations(tmp_path).splitlines()
    assert "guide_enable" in mutations
    assert "rewrite_flush" in mutations
    assert "demo_enable" not in mutations


def _assert_rolled_back(tmp_path: Path, output: str) -> None:
    mutations = _mutations(tmp_path).splitlines()
    assert "guide_enable" in mutations, mutations
    assert mutations[-2:] == ["guide_disable", "rewrite_flush"], mutations
    assert "rolled back" in output


def test_fails_when_guide_http_code_is_not_200(tmp_path: Path) -> None:
    result = _run(tmp_path, curl_http_code="404")
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "200" in output or "404" in output
    _assert_rolled_back(tmp_path, output)


def test_fails_when_guide_body_lacks_mount_id(tmp_path: Path) -> None:
    result = _run(tmp_path, curl_body="<html><body>not the guide</body></html>")
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "acx-public-guide-js" in output
    _assert_rolled_back(tmp_path, output)


def test_fails_when_guide_body_is_fallback_only(tmp_path: Path) -> None:
    result = _run(tmp_path, curl_body=FALLBACK_ONLY_BODY)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "acx-public-guide-js" in output
    _assert_rolled_back(tmp_path, output)


def test_rolls_back_when_curl_transport_fails(tmp_path: Path) -> None:
    result = _run(tmp_path, curl_exit=28)
    output = result.stdout + result.stderr
    assert result.returncode == 28, output
    _assert_rolled_back(tmp_path, output)


def test_rolls_back_when_pre_verification_flush_fails(tmp_path: Path) -> None:
    result = _run(tmp_path, fail_first_flush=True)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    _assert_rolled_back(tmp_path, output)


def test_fails_when_public_demo_describe_is_on_unless_retained(tmp_path: Path) -> None:
    blocked = _run(tmp_path, demo_enabled="1")
    blocked_out = blocked.stdout + blocked.stderr
    assert blocked.returncode != 0, blocked_out
    assert "acx_public_demo_enabled" in blocked_out
    assert "1" in blocked_out
    assert "guide_enable" not in _mutations(tmp_path).splitlines()

    retained_dir = tmp_path / "retained"
    retained_dir.mkdir()
    retained = _run(
        retained_dir,
        demo_enabled="1",
        extra_env={"ACX_RETAIN_PUBLIC_DEMO_DESCRIBE": "1"},
    )
    retained_out = retained.stdout + retained.stderr
    assert retained.returncode == 0, retained_out
    assert "acx_public_demo_enabled" in retained_out
    assert "guide_enable" in _mutations(retained_dir).splitlines()


def test_prints_public_demo_describe_value_when_off(tmp_path: Path) -> None:
    result = _run(tmp_path, demo_enabled="0")
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "acx_public_demo_enabled" in output
    assert "0" in output


def test_dry_run_prints_plan_and_mutates_nothing(tmp_path: Path) -> None:
    result = _run(tmp_path, args=["--dry-run"])
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "acx_public_guide_enabled" in output
    assert "rewrite flush" in output
    assert "/guide/" in output
    assert _log(tmp_path) == ""
    assert _mutations(tmp_path) == ""


def test_never_enables_public_demo_describe(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    log = _log(tmp_path)
    assert "option update acx_public_demo_enabled" not in log
    assert "demo_enable" not in _mutations(tmp_path).splitlines()


@pytest.mark.parametrize("flag", ["-u", "--cookie", "-b"])
def test_signed_out_curl_does_not_send_auth(tmp_path: Path, flag: str) -> None:
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    for line in _log(tmp_path).splitlines():
        if line.startswith("curl "):
            assert flag not in line.split(), line


def _write_compose_file(tmp_path: Path) -> Path:
    path = tmp_path / "docker-compose.demo.yml"
    path.write_text("services:\n  wpcli:\n    image: wordpress:cli\n", encoding="utf-8")
    return path


def test_compose_runner_used_by_default_when_compose_file_present(tmp_path: Path) -> None:
    compose_file = _write_compose_file(tmp_path)
    result = _run(tmp_path, include_docker=True, compose_file=compose_file)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    log = _log(tmp_path)
    docker_lines = [line for line in log.splitlines() if line.startswith("docker ")]
    assert docker_lines, log
    for line in docker_lines:
        tokens = line.split()
        assert "compose" in tokens, line
        assert "--rm" in tokens, line
        assert "--no-deps" in tokens, line
        assert "wpcli" in tokens, line
        assert "wp" in tokens, line
    assert any("option" in line and "update" in line and "acx_public_guide_enabled" in line for line in docker_lines), log
    assert any("rewrite" in line and "flush" in line and "--hard" in line for line in docker_lines), log
    wp_lines = [line for line in log.splitlines() if line.startswith("wp ")]
    assert wp_lines == [], log
    mutations = _mutations(tmp_path).splitlines()
    assert "guide_enable" in mutations
    assert "rewrite_flush" in mutations


def test_host_runner_reachable_via_acx_wp_runner(tmp_path: Path) -> None:
    compose_file = _write_compose_file(tmp_path)
    result = _run(
        tmp_path,
        include_docker=True,
        compose_file=compose_file,
        extra_env={"ACX_WP_RUNNER": "host"},
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    log = _log(tmp_path)
    wp_lines = [line for line in log.splitlines() if line.startswith("wp ")]
    assert wp_lines, log
    assert any("option" in line and "update" in line and "acx_public_guide_enabled" in line for line in wp_lines), log
    docker_lines = [line for line in log.splitlines() if line.startswith("docker ")]
    assert docker_lines == [], log


def test_refuses_when_neither_runner_is_available(tmp_path: Path) -> None:
    result = _run(tmp_path, include_wp=False, include_docker=False)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "wp" in output.lower() or "compose" in output.lower() or "runner" in output.lower()
    assert _mutations(tmp_path) == ""
    assert "wp " not in _log(tmp_path)
    assert "docker " not in _log(tmp_path)


def _curl_lines(tmp_path: Path) -> list[str]:
    return [line for line in _log(tmp_path).splitlines() if line.startswith("curl ")]


def test_signed_out_curl_sets_timeouts_and_follows_redirects(tmp_path: Path) -> None:
    result = _run(tmp_path)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    curl_lines = _curl_lines(tmp_path)
    assert curl_lines, _log(tmp_path)
    for line in curl_lines:
        tokens = line.split()
        assert "--connect-timeout" in tokens, line
        timeout_idx = tokens.index("--connect-timeout")
        assert tokens[timeout_idx + 1] == "10", line
        assert "--max-time" in tokens, line
        max_idx = tokens.index("--max-time")
        assert tokens[max_idx + 1] == "15", line
        assert "-L" in tokens, line
        assert "--max-redirs" in tokens, line
        redirs_idx = tokens.index("--max-redirs")
        assert tokens[redirs_idx + 1] == "3", line
