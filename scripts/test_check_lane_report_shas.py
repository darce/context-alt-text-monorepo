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
    """Narrow digest exclusions: sha256:, manifest_sha256, msha=, sha256sum listings.

    S5-03 / TEST-15: bare commit + ellipsis is NOT excluded — only labelled digests
    and sha256sum-style ``hex…  path`` listings. (Revisited: former loophole removed.)
    """
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
    # S5-05: success no longer says "all resolve" when wording may over-claim.
    assert "citation" in proc.stdout.lower() or "resolved" in proc.stdout.lower() or "none to resolve" in proc.stdout


def test_bare_commit_ellipsis_is_not_a_content_digest(report_dir: Path) -> None:
    """S5-03 / TEST-15: truncated commit display must still resolve (not digest-vetoed)."""
    path = _write(
        report_dir / "commit_ellipsis.md",
        "Landed at commit `deadbee…` (sandbox).\nBase was cafebab...\n",
    )
    rel = str(path.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode != 0, (
        f"bare commit+ellipsis must fail; got stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    err = proc.stderr.lower()
    assert "deadbee" in err
    assert "does not resolve" in err


def test_html_comment_does_not_hide_unresolvable_sha(report_dir: Path) -> None:
    """S5-01: unresolvable hex inside HTML comments is not a free pass."""
    path = _write(
        report_dir / "hidden_comment.md",
        "**Sandbox base:** history-stripped clone.\n"
        "<!-- sandbox base was `c9f7c6e` — unresolvable at destination; do not cite as a commit -->\n"
        "**Destination-reachable parent base:** placeholder\n",
    )
    rel = str(path.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode != 0, (
        f"comment-hidden unresolvable SHA must fail; stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert "c9f7c6e" in proc.stderr
    assert "does not resolve" in proc.stderr


def test_real_report_shape_f1a_f2b_comment_hide_fails(report_dir: Path) -> None:
    """S5-01 / TEST-15: real f1a/f2b prose with sandbox hex restored must exit 1."""
    f1a_shape = (
        "**Sandbox base:** history-stripped clone (sandbox-only object; not present here).\n"
        "<!-- sandbox base was `c9f7c6e` — unresolvable at destination; do not cite as a commit -->\n"
        "**Destination-reachable parent base:** `6b50ddde`\n"
    )
    f2b_shape = (
        "Sandbox history is stripped to a single base commit that does not exist in this\n"
        "repository, so a literal `git checkout ec493295 -- cli.py` is impossible here.\n"
        "<!-- sandbox base was `7ad6d52` — unresolvable at destination; named only inside this comment -->\n"
    )
    p1 = _write(report_dir / "f1a_shape.md", f1a_shape)
    p2 = _write(report_dir / "f2b_shape.md", f2b_shape)
    rels = [str(p1.relative_to(REPO_ROOT)), str(p2.relative_to(REPO_ROOT))]
    proc = _run_guard(*rels)
    assert proc.returncode != 0, (
        f"restored f1a/f2b comment-hide shape must fail; stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    err = proc.stderr
    assert "c9f7c6e" in err
    assert "7ad6d52" in err


def test_unclosed_html_comment_fails_closed(report_dir: Path) -> None:
    """S5-02 / TEST-15: unclosed <!-- must not skip the rest of the file."""
    path = _write(
        report_dir / "unclosed.md",
        "note <!-- sandbox deadbee\n"
        "Landed at commit beef001 for real.\n"
        "Also cafebab.\n",
    )
    rel = str(path.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode != 0, (
        f"unclosed comment must exit non-zero; stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    combined = (proc.stdout + proc.stderr).lower()
    assert "all resolve" not in combined
    # Either unclosed-comment violation and/or the later commit tokens must surface.
    assert (
        "unclosed" in combined
        or "beef001" in combined
        or "cafebab" in combined
        or "deadbee" in combined
    )


def test_scan_staged_empty_does_not_claim_resolve() -> None:
    """S5-04 / TEST-15 / AUDIT-07: empty staged set must not print 'all resolve'."""
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        empty_index = Path(td) / "empty-index"
        subprocess.run(
            ["git", "read-tree", "--empty"],
            cwd=REPO_ROOT,
            env={**os.environ, "GIT_INDEX_FILE": str(empty_index)},
            check=True,
            capture_output=True,
        )
        proc = subprocess.run(
            [sys.executable, str(GUARD), "--scan-staged"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "GIT_INDEX_FILE": str(empty_index)},
        )
    combined = proc.stdout + proc.stderr
    assert "all resolve" not in combined, f"empty sample claimed resolve: {combined!r}"
    # Exit 0 is fine (nothing to check) — but must not claim resolution over empty sample.
    assert "nothing to check" in combined.lower() or "0 staged" in combined.lower(), (
        f"expected empty-sample message; got {combined!r}"
    )


def test_ignore_marker_scopes_to_nearest_token(report_dir: Path) -> None:
    """S5-07: sha-guard:ignore applies to the nearest token only, not the whole line."""
    path = _write(
        report_dir / "nearest_ignore.md",
        "Foreign `deadbee` sha-guard:ignore and also unresolvable `beef001` here.\n",
    )
    rel = str(path.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode != 0, (
        f"second token must still fail; stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    err = proc.stderr
    assert "beef001" in err
    # deadbee is nearest to ignore marker — must not be the only/required violation name alone.
    # It is OK if deadbee is absent from err (ignored); beef001 must be present.
    assert "does not resolve" in err


def test_success_message_reports_citation_counts(report_dir: Path) -> None:
    """S5-05: success string must not claim 'all resolve' over zero tokens."""
    empty = _write(report_dir / "no_tokens.md", "No hex tokens of commit length here.\n")
    rel = str(empty.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode == 0
    assert "all resolve" not in proc.stdout
    assert "0 citations found" in proc.stdout or "none to resolve" in proc.stdout


def test_html_comment_and_ignore_marker_allow_deliberate_foreign_sha(report_dir: Path) -> None:
    """Deliberate foreign SHAs belong in visible prose with sha-guard:ignore (S5-01)."""
    path = _write(
        report_dir / "deliberate.md",
        "\n".join(
            [
                "Sandbox SHA quoted on purpose: `deadbee`  sha-guard:ignore",
                "Another foreign object `cafebab` sha-guard:ignore for documentation.",
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
    assert "citation" in proc.stdout.lower() or "resolved" in proc.stdout.lower()


def test_summary_counts_only_opened_files(report_dir: Path) -> None:
    """VLM6-D-03: success summary reports files actually opened, not path-arg count."""
    good = _write(report_dir / "only_good.md", "No hex tokens of commit length here.\n")
    rel = str(good.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode == 0
    assert "1 file(s)" in proc.stdout
    assert "all resolve" not in proc.stdout
    assert "0 citations found" in proc.stdout or "none to resolve" in proc.stdout
