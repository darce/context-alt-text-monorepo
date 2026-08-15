"""S2R4-07 — check_published_head_sha.py must fail unreadable stamps (TEST-15).

Drives the real repo-root script against a scratch git repo. A present stamp
that is not a resolvable commit is invalid, not absent. Uppercase hex is a
SHA. ``git_sha`` / ``commit`` keys, markdown ``commit <40hex>``, tracked HTML,
and an empty scan must not exit 0.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parents[5]
_GUARD_SCRIPT = _REPO_ROOT / "scripts" / "check_published_head_sha.py"
_ORPHAN = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init"], cwd=repo, check=True, capture_output=True, text=True
    )
    subprocess.run(["git", "config", "user.email", "t@t.test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    return repo


def _track(repo: Path, rel: str, content: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "--", rel], cwd=repo, check=True, capture_output=True)


def _commit(repo: Path, message: str) -> str:
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _run_guard(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_GUARD_SCRIPT)],
        cwd=repo,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )


def _json_report(head_sha: str, extra: dict | None = None) -> str:
    payload: dict = {"provenance": {"head_sha": head_sha}}
    if extra:
        payload["provenance"].update(extra)
    return json.dumps(payload)


def test_lowercase_orphan_is_missing(tmp_path: Path) -> None:
    """The class the original script shipped for must stay covered."""
    repo = _init_repo(tmp_path)
    _track(repo, "docs/report.json", _json_report(_ORPHAN))
    _commit(repo, "add orphan")
    proc = _run_guard(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, combined
    assert "MISSING" in combined
    assert _ORPHAN in combined


def test_uppercase_resolvable_sha_is_ok(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _track(repo, "docs/seed.md", "seed\n")
    sha = _commit(repo, "seed")
    _track(repo, "docs/report.json", _json_report(sha.upper()))
    _commit(repo, "add uppercase stamp")
    proc = _run_guard(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "ok —" in proc.stdout
    assert "1 head_sha stamp" in proc.stdout


def test_uppercase_orphan_is_missing_not_absent(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _track(repo, "docs/report.json", _json_report(_ORPHAN.upper()))
    _commit(repo, "add uppercase orphan")
    proc = _run_guard(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, combined
    assert "MISSING" in combined
    assert _ORPHAN in combined
    assert "ok — 0 head_sha" not in combined


def test_unknown_stamp_is_unreadable_not_absent(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _track(repo, "docs/report.json", _json_report("unknown"))
    _commit(repo, "add unknown")
    proc = _run_guard(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, combined
    assert "UNREADABLE" in combined
    assert "unknown" in combined
    assert "ok — 0 head_sha" not in combined
    assert "0 head_sha stamp(s) resolve" not in combined


def test_truncated_sha_is_unreadable(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _track(repo, "docs/report.json", _json_report("abc1234"))
    _commit(repo, "add truncated")
    proc = _run_guard(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, combined
    assert "UNREADABLE" in combined
    assert "abc1234" in combined


def test_garbage_stamp_is_unreadable(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _track(
        repo,
        "docs/report.json",
        _json_report("definitely-not-a-resolvable-commit"),
    )
    _commit(repo, "add garbage")
    proc = _run_guard(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, combined
    assert "UNREADABLE" in combined
    assert "definitely-not-a-resolvable-commit" in combined
    assert proc.returncode != 0


def test_markdown_head_sha_unknown_is_unreadable(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _track(repo, "docs/report.md", "- head_sha: `unknown`\n")
    _commit(repo, "add md unknown")
    proc = _run_guard(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, combined
    assert "UNREADABLE" in combined


def test_markdown_commit_line_is_harvested(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _track(repo, "docs/seed.md", "seed\n")
    sha = _commit(repo, "seed")
    _track(repo, "docs/report.md", f"commit {sha}\n")
    _commit(repo, "add commit line")
    proc = _run_guard(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "1 head_sha stamp" in proc.stdout


def test_markdown_commit_line_orphan_is_missing(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _track(repo, "docs/report.md", f"commit {_ORPHAN}\n")
    _commit(repo, "add commit orphan")
    proc = _run_guard(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, combined
    assert "MISSING" in combined
    assert _ORPHAN in combined


def test_git_sha_json_key_is_harvested(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _track(repo, "docs/seed.md", "seed\n")
    sha = _commit(repo, "seed")
    _track(repo, "docs/report.json", json.dumps({"provenance": {"git_sha": sha}}))
    _commit(repo, "add git_sha")
    proc = _run_guard(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "1 head_sha stamp" in proc.stdout


def test_git_sha_unknown_is_unreadable(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _track(repo, "docs/report.json", json.dumps({"provenance": {"git_sha": "unknown"}}))
    _commit(repo, "add git_sha unknown")
    proc = _run_guard(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, combined
    assert "UNREADABLE" in combined


def test_commit_json_key_is_harvested(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _track(repo, "docs/seed.md", "seed\n")
    sha = _commit(repo, "seed")
    _track(repo, "docs/report.json", json.dumps({"provenance": {"commit": sha}}))
    _commit(repo, "add commit key")
    proc = _run_guard(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "1 head_sha stamp" in proc.stdout


def test_html_is_scanned(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _track(repo, "docs/seed.md", "seed\n")
    sha = _commit(repo, "seed")
    _track(repo, "docs/report.html", f"<html>\nhead_sha: `{sha}`\n</html>\n")
    _commit(repo, "add html")
    proc = _run_guard(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "1 head_sha stamp" in proc.stdout
    assert "2 files scanned" in proc.stdout


def test_html_unknown_is_unreadable(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _track(repo, "benchmarks/report.html", "- head_sha: unknown\n")
    _commit(repo, "add html unknown")
    proc = _run_guard(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, combined
    assert "UNREADABLE" in combined


def test_zero_matching_files_exits_nonzero(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _track(repo, "README.md", "no artifacts\n")
    _commit(repo, "readme only")
    proc = _run_guard(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, combined
    assert "no tracked" in combined
    assert "ok —" not in combined


def test_shallow_clone_is_cannot_verify_not_missing(tmp_path: Path) -> None:
    """S2R5-21: a shallow clone must not report unseen stamps as MISSING."""
    src = _init_repo(tmp_path)
    _track(src, "docs/seed.md", "seed\n")
    first = _commit(src, "first")
    _track(src, "docs/later.md", "later\n")
    _commit(src, "second")
    _track(src, "docs/report.json", _json_report(first))
    _commit(src, "stamp first commit")
    clone = tmp_path / "shallow"
    # Local-path clones ignore --depth unless --no-local (or file://).
    subprocess.run(
        ["git", "clone", "--depth", "1", "--no-local", str(src), str(clone)],
        check=True,
        capture_output=True,
        text=True,
    )
    shallow_flag = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert shallow_flag == "true"
    proc = _run_guard(clone)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, combined
    assert "cannot verify" in combined
    assert "shallow clone" in combined
    assert "--unshallow" in combined
    assert "  MISSING  " not in combined
    assert first not in combined


def test_full_clone_orphan_is_still_missing(tmp_path: Path) -> None:
    """Shallow handling must not swallow a real missing stamp in a full repo."""
    repo = _init_repo(tmp_path)
    _track(repo, "docs/report.json", _json_report(_ORPHAN))
    _commit(repo, "add orphan")
    shallow_flag = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert shallow_flag == "false"
    proc = _run_guard(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, combined
    assert "MISSING" in combined
    assert "shallow clone" not in combined


def test_file_without_stamp_is_not_an_error_when_scan_is_nonempty(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _track(repo, "docs/seed.md", "seed\n")
    sha = _commit(repo, "seed")
    _track(repo, "docs/notes.md", "no stamp here\n")
    _track(repo, "docs/report.json", _json_report(sha))
    _commit(repo, "mixed")
    proc = _run_guard(repo)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "1 head_sha stamp" in proc.stdout
    assert "3 files scanned" in proc.stdout
