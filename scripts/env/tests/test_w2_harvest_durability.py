from __future__ import annotations

import json
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from conftest import load_module


TARGETS = '''
version = 1

[targets.vm]
audience = "backend"
envs = ["dev", "prod"]
sections = ["Runtime"]
'''

VARS = '''
version = 1

[[var]]
name = "LOG_LEVEL"
class = "config"
targets = ["vm"]
section = "Runtime"
example = "info"
values = { dev = "info" }
'''


def _commit_fixture(root: Path) -> None:
    subprocess.run(["git", "-C", str(root), "init", "--quiet"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "manifest.d"], check=True)
    subprocess.run(
        [
            "git", "-C", str(root), "-c", "user.name=Test Fixture",
            "-c", "user.email=fixture@example.invalid", "commit", "--quiet", "-m", "fixture",
        ],
        check=True,
    )


@pytest.fixture
def clean_manifest_root(write_manifest) -> Path:
    root = write_manifest(TARGETS, vars=VARS)
    _commit_fixture(root)
    return root


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "harvest.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "target": "vm",
                "env": "prod",
                "values": {"LOG_LEVEL": "safe-new"},
                "withheld": {
                    "secret": [], "derived": [], "unmanaged": [],
                    "missing": [], "secret_looking": [], "unparsed": [],
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _apply(root: Path, source: Path, capsys) -> tuple[int, str, str]:
    module = load_module("harvest_apply")
    code = module.main(["--root", str(root), str(source)])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_atomic_replace_fsyncs_and_closes_parent_directory_after_replace(tmp_path, monkeypatch):
    module = load_module("harvest_apply")
    target = tmp_path / "fragment.toml"
    target.write_bytes(b"old\n")
    events: list[object] = []
    directory_fds: set[int] = set()
    real_fsync = module.os.fsync
    real_replace = module.os.replace
    real_close = module.os.close

    def recording_fsync(fd: int) -> None:
        is_directory = stat.S_ISDIR(module.os.fstat(fd).st_mode)
        events.append(("fsync", "directory" if is_directory else "file"))
        if is_directory:
            directory_fds.add(fd)
        real_fsync(fd)

    def recording_replace(source: str | Path, destination: str | Path) -> None:
        real_replace(source, destination)
        events.append("replace")

    def recording_close(fd: int) -> None:
        if fd in directory_fds:
            events.append("close-directory")
        real_close(fd)

    monkeypatch.setattr(module.os, "fsync", recording_fsync)
    monkeypatch.setattr(module.os, "replace", recording_replace)
    monkeypatch.setattr(module.os, "close", recording_close)

    module._atomic_replace(target, b"new\n", 0o644)

    assert target.read_bytes() == b"new\n"
    assert events == [("fsync", "file"), "replace", ("fsync", "directory"), "close-directory"]


def test_clean_git_preimage_allows_apply(clean_manifest_root, tmp_path, capsys):
    source = _source(tmp_path)

    code, stdout, stderr = _apply(clean_manifest_root, source, capsys)

    assert code == 0
    assert stdout == "set\tLOG_LEVEL\tprod\n"
    assert stderr == ""


def test_unstaged_fragment_change_refuses_before_writing(clean_manifest_root, tmp_path, capsys):
    fragment = clean_manifest_root / "manifest.d" / "vars.toml"
    fragment.write_bytes(fragment.read_bytes() + b"# local edit\n")
    dirty_bytes = fragment.read_bytes()

    code, stdout, stderr = _apply(clean_manifest_root, _source(tmp_path), capsys)

    assert code == 2
    assert stdout == ""
    assert "vars.toml" in stderr
    assert "safe-new" not in stderr
    assert fragment.read_bytes() == dirty_bytes


def test_staged_fragment_change_refuses_even_if_worktree_matches_head(clean_manifest_root, tmp_path, capsys):
    fragment = clean_manifest_root / "manifest.d" / "vars.toml"
    head_bytes = fragment.read_bytes()
    fragment.write_bytes(head_bytes + b"# staged edit\n")
    subprocess.run(["git", "-C", str(clean_manifest_root), "add", "manifest.d/vars.toml"], check=True)
    fragment.write_bytes(head_bytes)

    code, stdout, stderr = _apply(clean_manifest_root, _source(tmp_path), capsys)

    assert code == 2
    assert stdout == ""
    assert "vars.toml" in stderr
    assert "safe-new" not in stderr
    assert fragment.read_bytes() == head_bytes


def test_untracked_affected_fragment_refuses_before_writing(clean_manifest_root, tmp_path, capsys):
    fragment = clean_manifest_root / "manifest.d" / "new.toml"
    fragment.write_text(
        '''version = 1
[[var]]
name = "EXTRA_MODE"
class = "config"
targets = ["vm"]
section = "Runtime"
example = "safe"
values = {}
''',
        encoding="utf-8",
    )
    original = fragment.read_bytes()
    source = _source(tmp_path)
    document = json.loads(source.read_text(encoding="utf-8"))
    document["values"] = {"EXTRA_MODE": "safe-new"}
    source.write_text(json.dumps(document), encoding="utf-8")

    code, stdout, stderr = _apply(clean_manifest_root, source, capsys)

    assert code == 2
    assert stdout == ""
    assert "new.toml" in stderr
    assert "safe-new" not in stderr
    assert fragment.read_bytes() == original


def test_non_git_root_refuses_before_writing(clean_manifest_root, tmp_path, capsys):
    shutil.rmtree(clean_manifest_root / ".git")
    fragment = clean_manifest_root / "manifest.d" / "vars.toml"
    original = fragment.read_bytes()

    code, stdout, stderr = _apply(clean_manifest_root, _source(tmp_path), capsys)

    assert code == 2
    assert stdout == ""
    assert "vars.toml" in stderr
    assert fragment.read_bytes() == original


def test_directory_fsync_failure_rolls_back_without_success_output(clean_manifest_root, tmp_path, capsys, monkeypatch):
    module = load_module("harvest_apply")
    fragment = clean_manifest_root / "manifest.d" / "vars.toml"
    original = fragment.read_bytes()
    source = _source(tmp_path)
    real_fsync = module.os.fsync
    directory_fsyncs = 0

    def fail_first_directory_fsync(fd: int) -> None:
        nonlocal directory_fsyncs
        if stat.S_ISDIR(module.os.fstat(fd).st_mode):
            directory_fsyncs += 1
            if directory_fsyncs == 1:
                raise OSError("forced directory fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(module.os, "fsync", fail_first_directory_fsync)

    code, stdout, stderr = _apply(clean_manifest_root, source, capsys)

    assert code == 2
    assert stdout == ""
    assert "safe-new" not in stderr
    assert directory_fsyncs >= 2
    assert fragment.read_bytes() == original
