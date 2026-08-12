"""TEST-15 discrimination surface for scripts/check_lane_report_shas.py.

Covers every escape class named in VLM6-D-03 / D-04 / D-05 / D-10:

* missing target path must fail closed (not "1 file(s) checked, all resolve")
* uppercase / mixed-case hex must be extracted and resolved
* ``Sandbox base:`` / ``Landing SHA`` phrasing without commit vocabulary
* citation on a line that also contains ``<!-- ... -->``
* citation on a line that also mentions ``digest``
* content digests (``sha256:``, ``manifest_sha256``, sha256sum listings) stay excluded
* resolvable commits and deliberate ``sha-guard:ignore`` / HTML-comment quotes pass

Each bad-fixture case asserts nonzero exit and a message naming the offending token.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD = REPO_ROOT / "scripts" / "check_lane_report_shas.py"


def _run_guard(*rel_paths: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GUARD), *rel_paths],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture()
def report_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate under repo .s2a with a unique prefix so default globs never see fixtures.

    The guard resolves paths relative to ``git rev-parse --show-toplevel``, so
    fixtures must live inside the real repo. Clean up after each test.
    """
    d = REPO_ROOT / ".s2a" / "_fx5_guard_fixtures"
    d.mkdir(parents=True, exist_ok=True)
    yield d
    for child in d.glob("*"):
        child.unlink()
    d.rmdir()


def test_missing_path_fails_closed_and_does_not_claim_resolve() -> None:
    """VLM6-D-03: nonexistent target is an error; summary must not claim resolution."""
    missing = ".s2a/does-not-exist-vlm6-fx5-guard.md"
    proc = _run_guard(missing)
    assert proc.returncode != 0, (
        f"missing path must exit non-zero; got 0 with stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    combined = proc.stdout + proc.stderr
    assert "all resolve" not in combined
    assert "not a readable file" in combined or "unopened path" in combined
    assert missing in combined or "does-not-exist-vlm6-fx5-guard" in combined


def test_uppercase_sha_is_visible_and_flagged(report_dir: Path) -> None:
    """VLM6-D-04: uppercase / mixed-case hex must not be invisible to the scanner."""
    path = _write(
        report_dir / "upper.md",
        "Landed at commit DEADBEE\nMixed form: Commit AbCdEf0 is claimed.\n",
    )
    rel = str(path.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode != 0, f"expected fail, got stdout={proc.stdout!r} stderr={proc.stderr!r}"
    err = proc.stderr
    # Message must name the offending token (case as written or as matched).
    assert "DEADBEE" in err or "deadbee" in err.lower()
    assert "does not resolve" in err


def test_sandbox_base_phrasing_flags_unresolvable_token(report_dir: Path) -> None:
    """VLM6-D-05: Sandbox base / Landing SHA without commit vocabulary still scan."""
    path = _write(
        report_dir / "sandbox.md",
        "**Sandbox base:** `deadbee`\nLanding SHA `cafebab`\n",
    )
    rel = str(path.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode != 0, f"expected fail, got stdout={proc.stdout!r} stderr={proc.stderr!r}"
    err = proc.stderr.lower()
    assert "deadbee" in err
    assert "cafebab" in err
    assert "does not resolve" in err


def test_citation_outside_html_comment_is_not_skipped(report_dir: Path) -> None:
    """VLM6-D-05: only the comment span is ignored; outside citation still flags."""
    path = _write(
        report_dir / "comment.md",
        "out here commit beef001 <!-- correction notes dead999 -->\n",
    )
    rel = str(path.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode != 0, f"expected fail, got stdout={proc.stdout!r} stderr={proc.stderr!r}"
    err = proc.stderr
    assert "beef001" in err
    # dead999 lives only inside the comment — must not be the (only) violation.
    # beef001 is the required hit.
    assert "does not resolve" in err


def test_digest_keyword_does_not_veto_commit_citation(report_dir: Path) -> None:
    """VLM6-D-05: a line that mentions digest must still flag a bare unresolvable commit."""
    path = _write(
        report_dir / "digest_line.md",
        "This line mentions digest but also cites commit abcd123 as the landing SHA.\n",
    )
    rel = str(path.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode != 0, f"expected fail, got stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "abcd123" in proc.stderr
    assert "does not resolve" in proc.stderr


def test_content_digest_exclusions_do_not_flag(report_dir: Path) -> None:
    """Narrow digest exclusions: sha256:, manifest_sha256, msha=, sha256sum listings."""
    # Use tokens that definitely do not resolve as commits.
    path = _write(
        report_dir / "digests_ok.md",
        "\n".join(
            [
                "Content hash sha256: deadbeefcafebabe",
                "freeze manifest_sha256 was `859a083e`",
                "trunc run msha=67040d45…",
                "fetch sha `67040d45…` ≠ score-time golden sha `859a083e…`",
                "sha256sum output:",
                "743d06ad…  …/S2A-determinism-anchor-run.json",
                "",
            ]
        ),
    )
    rel = str(path.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode == 0, f"digest exclusions leaked: stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "all resolve" in proc.stdout


def test_html_comment_and_ignore_marker_allow_deliberate_foreign_sha(report_dir: Path) -> None:
    """Deliberate foreign SHAs may be quoted in comments or with sha-guard:ignore."""
    path = _write(
        report_dir / "deliberate.md",
        "\n".join(
            [
                "<!-- the lane cited `ac2740b`, which resolves nowhere here -->",
                "Sandbox SHA quoted on purpose: `deadbee`  sha-guard:ignore",
                "",
            ]
        ),
    )
    rel = str(path.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode == 0, f"expected pass, got stdout={proc.stdout!r} stderr={proc.stderr!r}"


def test_resolvable_commit_passes(report_dir: Path) -> None:
    """A real object name in this repo must not be flagged."""
    head = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "--short=12", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    path = _write(report_dir / "good.md", f"Landed at commit `{head}`.\n")
    rel = str(path.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode == 0, f"expected pass for {head}: stderr={proc.stderr!r}"


def test_summary_counts_only_opened_files(report_dir: Path) -> None:
    """VLM6-D-03: success summary reports files actually opened, not path-arg count."""
    good = _write(report_dir / "only_good.md", "No hex tokens of commit length here.\n")
    rel = str(good.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode == 0
    assert "1 file(s) checked, all resolve" in proc.stdout
