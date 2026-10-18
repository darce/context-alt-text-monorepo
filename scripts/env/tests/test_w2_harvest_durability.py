from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import time
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
    real_fchmod = module.os.fchmod
    real_replace = module.os.replace
    real_close = module.os.close

    def recording_fchmod(fd: int, mode: int) -> None:
        events.append(("fchmod", mode))
        real_fchmod(fd, mode)

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

    monkeypatch.setattr(module.os, "fchmod", recording_fchmod)
    monkeypatch.setattr(module.os, "fsync", recording_fsync)
    monkeypatch.setattr(module.os, "replace", recording_replace)
    monkeypatch.setattr(module.os, "close", recording_close)

    module._atomic_replace(target, b"new\n", 0o644)

    assert target.read_bytes() == b"new\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
    assert events == [
        ("fchmod", 0o644),
        ("fsync", "file"),
        "replace",
        ("fsync", "directory"),
        "close-directory",
    ]


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


@pytest.mark.parametrize(
    "index_flag",
    ["--assume-unchanged", "--skip-worktree"],
    ids=["assume-unchanged", "skip-worktree"],
)
def test_index_flagged_dirty_fragment_refuses_before_writing(
    clean_manifest_root, tmp_path, capsys, index_flag
):
    fragment = clean_manifest_root / "manifest.d" / "vars.toml"
    subprocess.run(
        ["git", "-C", str(clean_manifest_root), "update-index", index_flag, "--", "manifest.d/vars.toml"],
        check=True,
    )
    fragment.write_bytes(fragment.read_bytes() + b"# hidden local edit\n")
    dirty_bytes = fragment.read_bytes()

    code, stdout, stderr = _apply(clean_manifest_root, _source(tmp_path), capsys)

    assert code == 2
    assert stdout == ""
    assert "vars.toml" in stderr
    assert "safe-new" not in stderr
    assert fragment.read_bytes() == dirty_bytes


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


def test_untracked_wildcard_fragment_cannot_borrow_tracked_preimage(
    clean_manifest_root, tmp_path, capsys
):
    fragment = clean_manifest_root / "manifest.d" / "vars*.toml"
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
    original_fragments = {
        path: path.read_bytes() for path in (clean_manifest_root / "manifest.d").glob("*.toml")
    }
    source = _source(tmp_path)
    document = json.loads(source.read_text(encoding="utf-8"))
    document["values"] = {"EXTRA_MODE": "safe-new"}
    source.write_text(json.dumps(document), encoding="utf-8")

    code, stdout, stderr = _apply(clean_manifest_root, source, capsys)

    assert code == 2
    assert stdout == ""
    assert "vars*.toml" in stderr
    assert "safe-new" not in stderr
    assert fragment.read_bytes() == original
    assert {path: path.read_bytes() for path in original_fragments} == original_fragments


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
    mode = stat.S_IMODE(fragment.stat().st_mode)
    events: list[object] = []
    real_fsync = module.os.fsync
    real_fchmod = module.os.fchmod
    real_replace = module.os.replace
    directory_fsyncs = 0

    def record_fchmod(fd: int, file_mode: int) -> None:
        events.append(("fchmod", file_mode))
        real_fchmod(fd, file_mode)

    def fail_first_directory_fsync(fd: int) -> None:
        nonlocal directory_fsyncs
        is_directory = stat.S_ISDIR(module.os.fstat(fd).st_mode)
        events.append(("fsync", "directory" if is_directory else "file"))
        if is_directory:
            directory_fsyncs += 1
            if directory_fsyncs == 1:
                raise OSError("forced directory fsync failure")
        real_fsync(fd)

    def record_replace(source_path: str | Path, destination: str | Path) -> None:
        real_replace(source_path, destination)
        events.append("replace")

    monkeypatch.setattr(module.os, "fchmod", record_fchmod)
    monkeypatch.setattr(module.os, "fsync", fail_first_directory_fsync)
    monkeypatch.setattr(module.os, "replace", record_replace)

    code, stdout, stderr = _apply(clean_manifest_root, source, capsys)

    assert code == 2
    assert stdout == ""
    assert "safe-new" not in stderr
    assert directory_fsyncs >= 2
    assert fragment.read_bytes() == original
    replacement_order = [
        ("fchmod", mode),
        ("fsync", "file"),
        "replace",
        ("fsync", "directory"),
    ]
    assert events == replacement_order + replacement_order


def test_concurrent_applies_serialize_and_do_not_erase_the_first_update(
    clean_manifest_root, tmp_path
):
    marker_dir = tmp_path / "markers"
    marker_dir.mkdir()
    release = marker_dir / "release"
    script = """
import os
import sys
import time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import env.harvest_apply as apply
markers = Path(os.environ["HAPPLY_TEST_MARKERS"])
(markers / f"started-{os.getpid()}").touch()
real_write = apply._write_and_validate
def wait_before_write(*args):
    (markers / f"entered-{os.getpid()}").touch()
    while not (markers / "release").exists():
        time.sleep(0.01)
    return real_write(*args)
apply._write_and_validate = wait_before_write
raise SystemExit(apply.main(sys.argv[2:]))
"""
    scripts_dir = Path(__file__).resolve().parents[2]
    env = {**os.environ, "HAPPLY_TEST_MARKERS": str(marker_dir)}
    processes: list[subprocess.Popen[str]] = []
    for index, value in enumerate(("safe-first", "safe-second")):
        source = tmp_path / f"harvest-{index}.json"
        source.write_text(
            json.dumps(
                {
                    "version": 1,
                    "target": "vm",
                    "env": "prod",
                    "values": {"LOG_LEVEL": value},
                    "withheld": {
                        "secret": [], "derived": [], "unmanaged": [],
                        "missing": [], "secret_looking": [], "unparsed": [],
                    },
                }
            ),
            encoding="utf-8",
        )
        processes.append(
            subprocess.Popen(
                [
                    sys.executable, "-c", script, str(scripts_dir),
                    "--root", str(clean_manifest_root), "--prefer-harvest", str(source),
                ],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        )

    try:
        deadline = time.monotonic() + 10
        while len(list(marker_dir.glob("started-*"))) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(list(marker_dir.glob("started-*"))) == 2
        deadline = time.monotonic() + 0.5
        while len(list(marker_dir.glob("entered-*"))) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        entered_before_release = len(list(marker_dir.glob("entered-*")))
    finally:
        release.touch()
        results = [process.communicate(timeout=10) for process in processes]

    fragment = clean_manifest_root / "manifest.d" / "vars.toml"
    final_text = fragment.read_text(encoding="utf-8")
    assert entered_before_release == 1
    assert sorted(process.returncode for process in processes) == [0, 2]
    assert sum("set\tLOG_LEVEL\tprod\n" in stdout for stdout, _ in results) == 1
    assert sum("unsafe pre-image" in stderr for _, stderr in results) == 1
    assert ('prod = "safe-first"' in final_text) != ('prod = "safe-second"' in final_text)


def test_edit_after_preimage_check_is_preserved(clean_manifest_root, tmp_path, capsys, monkeypatch):
    module = load_module("harvest_apply")
    fragment = clean_manifest_root / "manifest.d" / "vars.toml"
    external_edit = fragment.read_bytes() + b"# external edit after check\n"
    real_check = module._unsafe_preimage_fragments
    injected = False

    def edit_after_check(root: Path, fragments: list[Path]) -> list[str]:
        nonlocal injected
        unsafe = real_check(root, fragments)
        if not injected:
            fragment.write_bytes(external_edit)
            injected = True
        return unsafe

    monkeypatch.setattr(module, "_unsafe_preimage_fragments", edit_after_check)
    code, stdout, stderr = _apply(clean_manifest_root, _source(tmp_path), capsys)

    assert injected
    assert code == 2
    assert stdout == ""
    assert "unsafe pre-image" in stderr
    assert "vars.toml" in stderr
    assert fragment.read_bytes() == external_edit
