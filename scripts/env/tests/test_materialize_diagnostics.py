from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from conftest import load_module


INTO = "/opt/acx-backend/dev/.env"


def _table(values: dict[str, str]) -> str:
    return "{ " + ", ".join(f"{key} = {json.dumps(value)}" for key, value in values.items()) + " }"


def _targets() -> str:
    return "\n".join([
        "version = 1", "[targets.t]", 'audience = "backend"',
        'envs = ["dev"]', 'sections = ["S"]',
        f"remote_paths = {_table({'dev': INTO})}",
    ])


def _variable(values: dict[str, str]) -> str:
    return "\n".join([
        "version = 1", "[[var]]", 'name = "SETTING"', 'class = "config"',
        'targets = ["t"]', 'section = "S"', 'example = "example-value"',
        f"values = {_table(values)}",
    ])


@dataclass
class MaterializeCase:
    root: Path
    file: Path
    fs: Path
    backups: Path

    def run(self, mat, **kwargs):
        out, err = io.StringIO(), io.StringIO()
        options = dict(
            env="dev", target="t", into=INTO, fs_root=self.fs,
            backup_root=self.backups, out=out, err=err,
        )
        options.update(kwargs)
        rc = mat.run(self.root, **options)
        return rc, out.getvalue(), err.getvalue()


def _case(tmp_path: Path, write_manifest, values: dict[str, str]) -> MaterializeCase:
    root = write_manifest(_targets(), **{"10-materialize": _variable(values)})
    render = load_module("render_env")
    fs = tmp_path / "fs"
    file = fs / INTO.lstrip("/")
    file.parent.mkdir(parents=True)
    file.write_text(
        render.HEADER_LINE + "\n# materialized target=t env=dev digest=x\nSETTING=old\n",
        encoding="utf-8",
    )
    file.chmod(0o600)
    return MaterializeCase(root, file, fs, tmp_path / "backups")


@pytest.fixture
def case(tmp_path, write_manifest):
    return _case(tmp_path, write_manifest, {"dev": "configured"})


def test_missing_required_value_names_variable_and_env(tmp_path, write_manifest):
    mat = load_module("materialize")
    case = _case(tmp_path, write_manifest, {})

    rc, _, err = case.run(mat)

    assert rc == 2
    assert err.startswith("materialize refused: ")
    assert "SETTING" in err
    assert "env dev" in err


def test_unmanaged_key_refusal_names_key(case):
    mat = load_module("materialize")
    case.file.write_text(case.file.read_text(encoding="utf-8") + "UNMANAGED_KEY=harmless\n", encoding="utf-8")

    rc, _, err = case.run(mat)

    assert rc == 2
    assert err.startswith("materialize refused: ")
    assert "UNMANAGED_KEY" in err


def test_target_path_mismatch_refusal_names_reason(case):
    mat = load_module("materialize")

    rc, out, err = case.run(mat, into="/opt/acx-backend/dev/wrong.env")

    assert rc == 2
    assert out == ""
    assert err == "materialize refused: target path mismatch\n"


def test_existing_file_required_refusal_names_reason(case):
    mat = load_module("materialize")
    case.file.unlink()

    rc, out, err = case.run(mat)

    assert rc == 2
    assert out == ""
    assert err == "materialize refused: existing file required\n"


def test_oserror_refusal_names_path(case, monkeypatch):
    mat = load_module("materialize")

    def fail_write(path, *_args, **_kwargs):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(mat, "_owned_write", fail_write)
    rc, _, err = case.run(mat)

    assert rc == 2
    assert "materialize refused: PermissionError: Permission denied" in err
    assert str(case.file) in err


def test_third_party_value_error_redacts_message(case, monkeypatch):
    mat = load_module("materialize")
    private_input = "library-rejected-value-4821"

    def fail_render(*_args, **_kwargs):
        raise ValueError(private_input)

    monkeypatch.setattr(mat.render, "render_target", fail_render)
    rc, _, err = case.run(mat)

    assert rc == 2
    assert err == "materialize refused: ValueError\n"
    assert private_input not in err
