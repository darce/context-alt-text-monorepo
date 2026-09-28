from __future__ import annotations

import json
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import load_module

def _toml_table(values: dict[str, str]) -> str:
    return "{ " + ", ".join(f"{key} = {json.dumps(value)}" for key, value in values.items()) + " }"


def _targets(
    *,
    sections: tuple[str, ...] = ("Database",),
    envs: tuple[str, ...] = ("local",),
    audience: str = "backend",
    path: str | None = None,
    example: str | None = None,
    version: int = 1,
) -> str:
    lines = [
        f"version = {version}",
        "",
        "[targets.t]",
        f"audience = {json.dumps(audience)}",
        f"envs = {json.dumps(list(envs))}",
    ]
    if path is not None:
        lines.append(f"path = {json.dumps(path)}")
    if example is not None:
        lines.append(f"example = {json.dumps(example)}")
    lines.append(f"sections = {json.dumps(list(sections))}")
    return "\n".join(lines)


def _var(
    name: str,
    *,
    cls: str = "config",
    section: str = "Database",
    example: str = "example-value",
    values: dict[str, str] | None = None,
    secret: dict[str, str] | None = None,
    derive: str | None = None,
    doc: str | None = None,
    required: bool = True,
) -> str:
    lines = [
        "[[var]]",
        f"name = {json.dumps(name)}",
        f"class = {json.dumps(cls)}",
        'targets = ["t"]',
        f"section = {json.dumps(section)}",
    ]
    if doc is not None:
        lines.append(f"doc = {json.dumps(doc)}")
    lines.append(f"example = {json.dumps(example)}")
    if not required:
        lines.append("required = false")
    if values is not None:
        lines.append(f"values = {_toml_table(values)}")
    if secret is not None:
        lines.append(f"secret = {_toml_table(secret)}")
    if derive is not None:
        lines.append(f"derive = {json.dumps(derive)}")
    return "\n".join(lines)


REPO = Path(__file__).resolve().parents[3]


def test_harden_temp_naming(write_manifest, tmp_path, monkeypatch):
    render = load_module("render_env")
    replace = render.os.replace
    calls = []

    def record(src, dst):
        calls.append((Path(src), Path(dst), stat.S_IMODE(Path(src).stat().st_mode)))
        return replace(src, dst)

    monkeypatch.setattr(render.os, "replace", record)
    path = tmp_path / ".env"
    render.write_env_file(path, render.HEADER_LINE + "\nNAME=value\n")
    assert len(calls) == 1
    src, dst, mode = calls[0]
    assert dst == path
    assert src.parent == path.parent
    assert mode == 0o600
    assert re.fullmatch(re.escape(".env") + r"\.envman-tmp-.+", src.name)
    assert "*.envman-tmp-*" in (REPO / ".gitignore").read_text().splitlines()


@pytest.mark.parametrize("mutation", ["mode", "duplicate", "comment"])
def test_harden_check_runtime_exactness(write_manifest, tmp_path, mutation):
    render = load_module("render_env")
    root = write_manifest(
        _targets(),
        config="version = 1\n" + _var("NAME", values={"local": "configured"}) + "\n" +
        _var("SESSION", cls="secret", secret={"local": "env:SESSION"}),
    )
    manifest = load_module("manifest").load_manifest(root)
    secret_value = "s3cr3t-" + "value"

    def resolve(ref, name):
        return secret_value

    path = tmp_path / ".env"
    text = render.render_target(manifest, "t", "local", resolve=resolve)
    render.write_env_file(path, text)
    assert render.check_runtime(manifest, "t", "local", path, resolve=resolve) == []
    if mutation == "mode":
        path.chmod(0o644)
        assert path.read_bytes() == text.encode("utf-8")
        expected = f"{path}: mode is not 0600"
    elif mutation == "duplicate":
        assignment = next(line for line in text.splitlines() if line.startswith("NAME="))
        path.write_text(text + assignment + "\n", encoding="utf-8")
        expected = "NAME: duplicate assignment"
    else:
        path.write_text(text + "# extra comment\n", encoding="utf-8")
        expected = f"{path}: non-assignment lines differ"
    messages = render.check_runtime(manifest, "t", "local", path, resolve=resolve)
    assert all(secret_value not in message for message in messages)
    assert expected in messages


def test_harden_unexpected_exception_exit(write_manifest, tmp_path, monkeypatch, capsys):
    render = load_module("render_env")
    root = write_manifest(_targets(), config="version = 1\n" + _var("NAME", values={"local": "ok"}))

    def boom(root):
        raise RuntimeError("boom-" + "detail")

    monkeypatch.setattr(render, "load_manifest", boom)
    try:
        status = render.main(["check", "--root", str(root), "--repo-root", str(tmp_path), "--all-examples"])
    except RuntimeError:
        pytest.fail("main leaked RuntimeError instead of returning exit 4")
    captured = capsys.readouterr()
    assert status == 4
    assert "RuntimeError" in captured.out + captured.err
    assert "boom-" + "detail" not in captured.out + captured.err


def test_harden_interpreter_floor(write_manifest, tmp_path):
    render = load_module("render_env")
    root = write_manifest(_targets(example=".env.example"), config="version = 1\n" + _var("NAME", values={"local": "ok"}))
    manifest = load_module("manifest").load_manifest(root)
    render.write_env_file(tmp_path / ".env.example", render.render_target(manifest, "t", None))
    assert render.check_example(manifest, "t", tmp_path) == []
    argv = ["render_env.py", "check", "--root", str(root), "--repo-root", str(tmp_path), "--all-examples"]
    script = (
        "import runpy, sys; sys.version_info = (3, 10, 0, 'final', 0); "
        f"sys.argv = {argv!r}; runpy.run_path({str(REPO / 'scripts/env/render_env.py')!r}, run_name='__main__')"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert "3.11" in result.stderr


@pytest.mark.parametrize("args,expected", [
    (["env-check", "ENV_PYTHON=/opt/py3"], "/opt/py3 /r/scripts/env/render_env.py check"),
    (["env-secret-set", "NAME=X", "ENV_SECRET_SERVICE=svc-a"], '-s "svc-a" -a "X"'),
    (["env-secret-set", "NAME=X", "SERVICE=api"], '-s "acx-local"'),
], ids=["python", "secret-service", "ignore-service"])
def test_harden_make_variables(args, expected):
    make = shutil.which("make")
    if make is None:
        pytest.skip("make is unavailable")
    result = subprocess.run(
        [make, "-n", "-f", str(REPO / "mk/env.mk"), "ROOT_MAKEFILE_DIR=/r", *args],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert expected in result.stdout


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("${PGUSER}", '"${PGUSER}"'),
        (
            "postgresql+asyncpg://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT}/${DB_NAME}",
            '"postgresql+asyncpg://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT}/${DB_NAME}"',
        ),
        ("${A}${B}", '"${A}${B}"'),
        ("${lower_ok}", '"${lower_ok}"'),
        ("cash$value", "'cash$value'"),
        ("$PGUSER", "'$PGUSER'"),
        ("${PGUSER", "'${PGUSER'"),
        ("${PG USER}", "'${PG USER}'"),
        ("${PGUSER} x", "'${PGUSER} x'"),
        ("${1X}", "'${1X}'"),
        ("${}", "'${}'"),
    ),
)
def test_harden_reference_quoting(write_manifest, value: str, expected: str):
    render = load_module("render_env")
    root = write_manifest(
        _targets(),
        config="version = 1\n" + _var("VALUE", example=value, values={"local": value}),
    )
    manifest = load_module("manifest").load_manifest(root)
    rendered = render.render_target(manifest, "t", None)
    assert f"VALUE={expected}" in rendered.splitlines()


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is unavailable")
def test_harden_reference_expands_under_bash_source(write_manifest, tmp_path):
    render = load_module("render_env")
    root = write_manifest(
        _targets(),
        config="version = 1\n"
        + _var("PGUSER", values={"local": "alice"})
        + "\n"
        + _var("APP_PGUSER", values={"local": "${PGUSER}"}),
    )
    manifest = load_module("manifest").load_manifest(root)
    path = tmp_path / "x.env"
    path.write_text(render.render_target(manifest, "t", "local"), encoding="utf-8")
    result = subprocess.run(
        [
            "bash", "--noprofile", "--norc", "-c",
            'set -a; source "$1"; printf %s "$APP_PGUSER"', "_", str(path),
        ],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "alice"


def test_harden_resolved_secret_stays_literal(write_manifest):
    render = load_module("render_env")
    root = write_manifest(
        _targets(),
        config="version = 1\n"
        + _var("SERVICE_PASSWORD", cls="secret", secret={"local": "env:ACX_TEST_SECRET"}),
    )
    manifest = load_module("manifest").load_manifest(root)
    rendered = render.render_target(manifest, "t", "local", resolve=lambda name, ref: "p${UNSET_X}s")
    assert "SERVICE_PASSWORD='p${UNSET_X}s'" in rendered.splitlines()


def test_harden_derived_value_with_secret_stays_literal(write_manifest):
    render = load_module("render_env")
    root = write_manifest(
        _targets(),
        config="version = 1\n"
        + _var("PGPASSWORD", cls="secret", secret={"local": "env:ACX_TEST_SECRET"})
        + "\n"
        + _var("PGUSER", values={"local": "alice"})
        + "\n"
        + _var("DSN", cls="secret", derive="postgresql://${PGUSER}:${PGPASSWORD}@db/app"),
    )
    manifest = load_module("manifest").load_manifest(root)
    rendered = render.render_target(manifest, "t", "local", resolve=lambda name, ref: "p${UNSET_X}s")
    assert "DSN='postgresql://alice:p${UNSET_X}s@db/app'" in rendered.splitlines()


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is unavailable")
def test_harden_resolved_secret_literal_under_bash_source(write_manifest, tmp_path):
    render = load_module("render_env")
    root = write_manifest(
        _targets(),
        config="version = 1\n"
        + _var("SERVICE_PASSWORD", cls="secret", secret={"local": "env:ACX_TEST_SECRET"}),
    )
    manifest = load_module("manifest").load_manifest(root)
    path = tmp_path / "x.env"
    path.write_text(
        render.render_target(manifest, "t", "local", resolve=lambda name, ref: "p${UNSET_X}s"),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            "bash", "--noprofile", "--norc", "-c",
            'set -a; source "$1"; printf %s "$SERVICE_PASSWORD"', "_", str(path),
        ],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == "p${UNSET_X}s"


def test_harden_config_runtime_reference_still_double_quoted(write_manifest):
    render = load_module("render_env")
    root = write_manifest(
        _targets(),
        config="version = 1\n"
        + _var("PGUSER", values={"local": "alice"})
        + "\n"
        + _var("APP_PGUSER", values={"local": "${PGUSER}"}),
    )
    manifest = load_module("manifest").load_manifest(root)
    rendered = render.render_target(manifest, "t", "local")
    assert 'APP_PGUSER="${PGUSER}"' in rendered.splitlines()


def test_harden_optional_secret_absent_omitted(write_manifest):
    refs = load_module("secret_refs")
    render = load_module("render_env")
    root = write_manifest(
        _targets(),
        config="version = 1\n"
        + _var("NAME", values={"local": "ok"})
        + "\n"
        + _var("E2E_KEY", cls="secret", secret={"local": "env:ACX_TEST_OPT_KEY"}, required=False),
    )
    manifest = load_module("manifest").load_manifest(root)

    def resolve(name, ref):
        raise refs.SecretNotFound(f"secret {name!r} unavailable")

    rendered = render.render_target(manifest, "t", "local", resolve=resolve)
    assert not any(line.startswith("E2E_KEY=") for line in rendered.splitlines())
    assert "NAME=ok" in rendered.splitlines()


def test_harden_optional_secret_backend_error_propagates(write_manifest):
    refs = load_module("secret_refs")
    render = load_module("render_env")
    root = write_manifest(
        _targets(),
        config="version = 1\n"
        + _var("NAME", values={"local": "ok"})
        + "\n"
        + _var("E2E_KEY", cls="secret", secret={"local": "env:ACX_TEST_OPT_KEY"}, required=False),
    )
    manifest = load_module("manifest").load_manifest(root)

    def resolve(name, ref):
        raise refs.SecretUnavailable(f"secret {name!r} unavailable")

    with pytest.raises(refs.SecretUnavailable):
        render.render_target(manifest, "t", "local", resolve=resolve)


def test_harden_required_secret_absent_still_fails(write_manifest):
    refs = load_module("secret_refs")
    render = load_module("render_env")
    not_found = refs.SecretNotFound
    root = write_manifest(
        _targets(),
        config="version = 1\n"
        + _var("NAME", values={"local": "ok"})
        + "\n"
        + _var("E2E_KEY", cls="secret", secret={"local": "env:ACX_TEST_OPT_KEY"}, required=True),
    )
    manifest = load_module("manifest").load_manifest(root)

    def resolve(name, ref):
        raise not_found(f"secret {name!r} unavailable")

    with pytest.raises(refs.SecretUnavailable) as excinfo:
        render.render_target(manifest, "t", "local", resolve=resolve)
    assert "ACX_TEST_OPT_KEY" not in str(excinfo.value)


def test_harden_optional_secret_resolved_renders(write_manifest):
    refs = load_module("secret_refs")
    render = load_module("render_env")
    root = write_manifest(
        _targets(),
        config="version = 1\n"
        + _var("NAME", values={"local": "ok"})
        + "\n"
        + _var("E2E_KEY", cls="secret", secret={"local": "env:ACX_TEST_OPT_KEY"}, required=False),
    )
    manifest = load_module("manifest").load_manifest(root)

    rendered = render.render_target(manifest, "t", "local", resolve=lambda name, ref: "k1")
    assert "E2E_KEY=k1" in rendered.splitlines()


def test_harden_optional_absent_check_runtime_clean(write_manifest, tmp_path):
    refs = load_module("secret_refs")
    render = load_module("render_env")
    root = write_manifest(
        _targets(),
        config="version = 1\n"
        + _var("NAME", values={"local": "ok"})
        + "\n"
        + _var("E2E_KEY", cls="secret", secret={"local": "env:ACX_TEST_OPT_KEY"}, required=False),
    )
    manifest = load_module("manifest").load_manifest(root)

    def resolve(name, ref):
        raise refs.SecretNotFound(f"secret {name!r} unavailable")

    rendered = render.render_target(manifest, "t", "local", resolve=resolve)
    path = tmp_path / "rt.env"
    path.write_text(rendered, encoding="utf-8")
    path.chmod(0o600)
    assert render.check_runtime(manifest, "t", "local", path, resolve=resolve) == []


@pytest.mark.parametrize(
    "ref, rc, expected",
    [
        ("keychain:acx-local/X", 44, True),
        ("keychain:acx-local/X", 1, False),
        ("env:ACX_TEST_UNSET_VAR", None, True),
    ],
)
def test_harden_secret_not_found_classification(ref, rc, expected):
    refs = load_module("secret_refs")
    render = load_module("render_env")
    runner = lambda *a, **k: subprocess.CompletedProcess(a[0], rc, "", "")
    with pytest.raises(refs.SecretUnavailable) as excinfo:
        refs.resolve_secret("E2E_KEY", ref, environ={}, runner=runner)
    assert isinstance(excinfo.value, refs.SecretNotFound) is expected


def test_harden_e2e_api_key_has_local_ref():
    refs = load_module("secret_refs")
    render = load_module("render_env")
    manifest = load_module("manifest").load_manifest(REPO / "config" / "env")
    var = next(var for var in manifest.vars if var.name == "ACX_E2E_RECOGNITION_API_KEY")
    assert var.required is False
    assert var.secret.get("local", "").startswith("keychain:acx-local/")
