from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from conftest import load_module


INTO = "/opt/acx-backend/dev/.env"


def _targets() -> str:
    return "\n".join(
        (
            "version = 1",
            "[targets.t]",
            'audience = "backend"',
            'envs = ["dev"]',
            'sections = ["S"]',
            f'remote_paths = {{ dev = {json.dumps(INTO)} }}',
        )
    )


def _var(name: str, *, cls: str, required: bool = True, source: str) -> str:
    lines = [
        "[[var]]",
        f"name = {json.dumps(name)}",
        f"class = {json.dumps(cls)}",
        'targets = ["t"]',
        'section = "S"',
        'example = "example-value"',
    ]
    if not required:
        lines.append("required = false")
    lines.append(source)
    return "\n".join(lines)


@pytest.fixture
def case(tmp_path: Path, write_manifest):
    root = write_manifest(
        _targets(),
        **{
            "10-materialize": "version = 1\n"
            + "\n".join(
                (
                    _var("PGPASSWORD", cls="secret", source='secret = { dev = "host:" }'),
                    _var("OPTIONAL_TOKEN", cls="secret", required=False, source="secret = {}"),
                )
            )
        },
    )
    render = load_module("render_env")
    fs_root = tmp_path / "fs"
    path = fs_root / INTO.lstrip("/")
    path.parent.mkdir(parents=True)
    path.write_text(
        f"{render.HEADER_LINE}\n# materialized target=t env=dev digest=test\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return root, fs_root, path


def _run(root: Path, fs_root: Path, tmp_path: Path, *, check: bool = False):
    materialize = load_module("materialize")
    out, err = io.StringIO(), io.StringIO()
    result = materialize.run(
        root,
        env="dev",
        target="t",
        into=INTO,
        check=check,
        fs_root=fs_root,
        backup_root=tmp_path / "backups",
        out=out,
        err=err,
    )
    return result, out.getvalue(), err.getvalue()


@pytest.mark.parametrize("assignment", ("PGPASSWORD=", "PGPASSWORD=''", 'PGPASSWORD=""'))
def test_empty_required_host_secret_is_missing(case, tmp_path: Path, assignment: str):
    root, fs_root, path = case
    path.write_text(
        path.read_text(encoding="utf-8") + assignment + "\n",
        encoding="utf-8",
    )
    before = path.read_bytes()

    result, _, err = _run(root, fs_root, tmp_path)

    assert result == 4
    assert "PGPASSWORD" in err
    assert path.read_bytes() == before

    result, out, err = _run(root, fs_root, tmp_path, check=True)

    assert result == 1
    assert out.splitlines() == ["missing\tPGPASSWORD"]
    assert err == ""


def test_nonempty_required_host_secret_remains_available(case, tmp_path: Path):
    root, fs_root, path = case
    path.write_text(
        path.read_text(encoding="utf-8") + "PGPASSWORD=secret-value\n",
        encoding="utf-8",
    )

    result, _, err = _run(root, fs_root, tmp_path)

    assert result == 0
    assert err == ""


def test_check_reports_stale_optional_managed_key_until_apply(case, tmp_path: Path):
    root, fs_root, path = case
    path.write_text(
        path.read_text(encoding="utf-8")
        + "PGPASSWORD=secret-value\nOPTIONAL_TOKEN=stale-value\n",
        encoding="utf-8",
    )

    result, out, err = _run(root, fs_root, tmp_path, check=True)

    assert result == 1
    assert out.splitlines() == ["stale\tOPTIONAL_TOKEN"]
    assert err == ""

    result, _, err = _run(root, fs_root, tmp_path)
    assert result == 0
    assert err == ""
    assert "OPTIONAL_TOKEN=" not in path.read_text(encoding="utf-8")

    result, out, err = _run(root, fs_root, tmp_path, check=True)
    assert result == 0
    assert out == ""
    assert err == ""
