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
    d = REPO_ROOT / ".s2a" / "_fx3_guard_fixtures"
    d.mkdir(parents=True, exist_ok=True)
    yield d
    # Recursive cleanup so nested-path fixtures (RV4-04) cannot leak.
    for child in sorted(d.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            child.rmdir()
    if d.exists():
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
    """Narrow digest exclusions: sha256:, labelled digests with shape, sha256sum listings.

    RV4-02 / S5-03 / TEST-15: label alone is not enough — need sha256: prefix, ≥16 hex,
    or ellipsis / sha256sum path remainder. Bare 7-12 hex after a digest label is a
    commit citation (see test_digest_label_with_short_hex_is_not_excluded).
    """
    # Use tokens that definitely do not resolve as commits.
    path = _write(
        report_dir / "digests_ok.md",
        "\n".join(
            [
                "Content hash sha256: deadbeefcafebabe",
                "freeze manifest_sha256 was `859a083eabcdef01`",  # ≥16 hex + label
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


# ---------------------------------------------------------------------------
# RV4-02 / RV4-06 — digest labels must not veto bare 7-12 hex commit citations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body,token",
    [
        ("Sandbox golden sha is c9f7c6e (history-stripped clone).\n", "c9f7c6e"),
        ("fetch sha c9f7c6e was the sandbox base\n", "c9f7c6e"),
        ("manifest sha was c9f7c6e before rewrite\n", "c9f7c6e"),
        ("The freeze golden sha is 7ad6d52 at score-time.\n", "7ad6d52"),
        ("score-time golden sha is deadbee without ellipsis\n", "deadbee"),
        ("model_dump sha was cafebab in the freeze.\n", "cafebab"),
    ],
    ids=[
        "golden_sha_is",
        "fetch_sha",
        "manifest_sha_was",
        "freeze_golden_sha_is",
        "score_time_golden_sha_is",
        "model_dump_sha_was",
    ],
)
def test_digest_label_with_short_hex_is_not_excluded(
    report_dir: Path, body: str, token: str
) -> None:
    """RV4-02 / TEST-15: label vocabulary alone does not make 7-12 hex a digest.

    A bare short token after golden/fetch/manifest/freeze wording is a commit
    citation and must fail closed when unresolvable (AUDIT-07).
    """
    path = _write(report_dir / f"rv4_02_{token}.md", body)
    rel = str(path.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode != 0, (
        f"short hex after digest label must fail closed; body={body!r} "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert token in proc.stderr.lower()
    assert "does not resolve" in proc.stderr


def test_sandbox_base_control_still_flags(report_dir: Path) -> None:
    """RV4-02 control: unlabelled Sandbox base phrasing still fails closed."""
    path = _write(
        report_dir / "rv4_02_control.md",
        "Sandbox base was c9f7c6e (history-stripped clone).\n",
    )
    rel = str(path.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode != 0
    assert "c9f7c6e" in proc.stderr


# ---------------------------------------------------------------------------
# RV4-03 / RV4-06 — unicode / homoglyph evasion must not go invisible
# ---------------------------------------------------------------------------


def test_soft_hyphen_in_sha_is_visible_and_flagged(report_dir: Path) -> None:
    """RV4-03: U+00AD soft hyphen inside a SHA must not hide the citation."""
    # c9f7 + soft-hyphen + c6e renders as c9f7c6e in Markdown viewers
    body = "Sandbox base was c9f7\u00adc6e (history-stripped).\n"
    path = _write(report_dir / "rv4_03_soft_hyphen.md", body)
    rel = str(path.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode != 0, (
        f"soft-hyphen SHA must fail closed; stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    combined = (proc.stdout + proc.stderr).lower()
    assert "c9f7c6e" in combined or "does not resolve" in combined or "homoglyph" in combined
    assert "0 citations found" not in proc.stdout


def test_zwsp_in_sha_is_visible_and_flagged(report_dir: Path) -> None:
    """RV4-03: U+200B zero-width space inside a SHA must not hide the citation."""
    body = "Landed at commit `c9f7\u200bc6e`\n"
    path = _write(report_dir / "rv4_03_zwsp.md", body)
    rel = str(path.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode != 0, (
        f"ZWSP SHA must fail closed; stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    combined = (proc.stdout + proc.stderr).lower()
    assert "c9f7c6e" in combined or "does not resolve" in combined or "homoglyph" in combined


def test_fullwidth_hex_is_visible_and_flagged(report_dir: Path) -> None:
    """RV4-03: fullwidth hex digits must NFKC-normalize into a scanned token."""
    # ｃ９ｆ７ｃ６ｅ (fullwidth) → c9f7c6e under NFKC
    fullwidth = "\uff43\uff19\uff46\uff17\uff43\uff16\uff45"
    body = f"Sandbox base was {fullwidth} (history-stripped).\n"
    path = _write(report_dir / "rv4_03_fullwidth.md", body)
    rel = str(path.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode != 0, (
        f"fullwidth SHA must fail closed; stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert "c9f7c6e" in proc.stderr.lower() or "does not resolve" in proc.stderr


def test_cyrillic_homoglyph_sha_fails_loudly(report_dir: Path) -> None:
    """RV4-03: mixed Cyrillic/ASCII lookalike SHA must fail, not go invisible.

    с9f7с6е uses U+0441 CYRILLIC SMALL LETTER ES and U+0435 CYRILLIC SMALL
    LETTER IE — renders like c9f7c6e but is not ASCII hex.
    """
    # с = U+0441, е = U+0435
    body = "Sandbox base was \u04419f7\u04416\u0435 (history-stripped).\n"
    path = _write(report_dir / "rv4_03_cyrillic.md", body)
    rel = str(path.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode != 0, (
        f"homoglyph SHA must fail closed; stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    combined = (proc.stdout + proc.stderr).lower()
    assert (
        "homoglyph" in combined
        or "lookalike" in combined
        or "non-ascii" in combined
        or "does not resolve" in combined
    )
    assert "0 citations found" not in proc.stdout
    assert "citation(s) resolved" not in proc.stdout


def test_homoglyph_detection_is_unconditional_not_vocab_gated(report_dir: Path) -> None:
    """VLM6-R2-G-03 / TEST-15: homoglyph runs are examined on every line.

    Vocabulary must not gate detection. The Cyrillic-с variant of c9f7c6e must
    fail closed even when the surrounding prose has no commit vocabulary (and
    even when the line only contains 'HEAD', which is not in the vocab set).
    """
    # с = U+0441, е = U+0435  → renders like c9f7c6e
    sha = "\u04419f7\u04416\u0435"
    cases = [
        ("vocab.md", f"Sandbox base was {sha}."),
        ("no_vocab.md", f"Work landed under {sha} in the throwaway clone."),
        ("head_only.md", f"The lane worktree HEAD was {sha} at the time of the run."),
    ]
    for name, body in cases:
        path = _write(report_dir / f"g03_{name}", body + "\n")
        rel = str(path.relative_to(REPO_ROOT))
        proc = _run_guard(rel)
        assert proc.returncode != 0, (
            f"homoglyph must fail closed without vocab gate; body={body!r} "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
        combined = (proc.stdout + proc.stderr).lower()
        assert (
            "homoglyph" in combined
            or "lookalike" in combined
            or "non-ascii" in combined
        ), f"expected homoglyph signal for body={body!r}; got {combined!r}"


# ---------------------------------------------------------------------------
# RV4-04 / RV4-06 — default walk must match staged depth (recursive)
# ---------------------------------------------------------------------------


def _load_guard_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_lane_report_shas", GUARD)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_nested_s2a_path_is_scanned_by_default_walk(report_dir: Path) -> None:
    """RV4-04 / VLM6-R2-E-02: default walk membership is checked directly (no ambient pollution).

    Asserts path membership via ``_default_report_paths`` rather than a full-repo
    default-walk exit code. Uses a unique token that cannot substring-match ambient
    ``deadbeef`` citations in other lane reports.
    """
    mod = _load_guard_module()
    # Unique token: not a substring of ambient deadbeef / cafebab noise.
    unique_token = "f00ba12"  # 7 hex, unresolvable, no ambient substring collision
    nested = report_dir / "_rv4_nested" / "lane-report.md"
    _write(nested, f"Sandbox base was {unique_token}\n")
    defaults = {p.resolve() for p in mod._default_report_paths(REPO_ROOT)}
    assert nested.resolve() in defaults, (
        f"default walk missed nested path {nested}; "
        f"count={len(defaults)} sample={[str(p) for p in sorted(defaults) if '_rv4' in str(p) or '_fx3' in str(p)]}"
    )
    # Also confirm the file is actually scanned when targeted (path in stderr, unique token).
    rel = str(nested.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode != 0
    assert unique_token in proc.stderr
    assert "_rv4_nested" in proc.stderr or "lane-report" in proc.stderr


def test_default_walk_and_staged_predicate_agree_on_nested_paths(tmp_path: Path) -> None:
    """RV4-04 / rg-006 / RF-12: default walk filters through the shared path predicate.

    Fixture tree lives under ``tmp_path`` so the assertion does not depend on
    ambient repo content or leave residue under REPO_ROOT.
    """
    mod = _load_guard_module()

    # Nested and shallow paths must both be accepted by the shared predicate.
    assert mod._is_lane_report_relpath(".s2a/top.md") is True
    assert mod._is_lane_report_relpath(".s2a/nested/deep.md") is True
    assert mod._is_lane_report_relpath("pkg/.s2a/nested/deep.md") is True
    assert mod._is_lane_report_relpath("docs/tasks/note.md") is False
    assert mod._is_lane_report_relpath(".s2a/notes.txt") is False

    nested_dir = tmp_path / ".s2a" / "_fx3_walk_parity"
    nested_dir.mkdir(parents=True, exist_ok=True)
    nested_file = nested_dir / "deep.md"
    nested_file.write_text("no tokens here\n", encoding="utf-8")
    defaults = {p.resolve() for p in mod._default_report_paths(tmp_path)}
    assert nested_file.resolve() in defaults, (
        f"default walk missed nested path {nested_file}; sample={sorted(defaults)[:5]}"
    )


def test_default_walk_sees_s2a_at_arbitrary_depth_above_star(tmp_path: Path) -> None:
    """VLM6-R2-G-04 / rg-006 / RF-12: depth above ``*/.s2a`` is not missed.

    ``*`` does not cross path separators, so a parallel glob list drifts from the
    predicate. The collector must walk the tree and filter through
    ``_is_lane_report_relpath`` so e.g. ``a/b/c/.s2a/report.md`` is included.

    RF-12: build the fixture under ``tmp_path`` — never mkdir inside REPO_ROOT or
    rglob the real checkout (ambient content / pollution / cross-run bleed).
    """
    mod = _load_guard_module()
    deep_dir = tmp_path / "a" / "b" / "c" / ".s2a" / "_cx5_depth_parity"
    deep_dir.mkdir(parents=True, exist_ok=True)
    deep_file = deep_dir / "report.md"
    deep_file.write_text("no tokens here\n", encoding="utf-8")
    rel = deep_file.relative_to(tmp_path).as_posix()
    assert mod._is_lane_report_relpath(rel) is True
    defaults = {p.resolve() for p in mod._default_report_paths(tmp_path)}
    assert deep_file.resolve() in defaults, (
        f"default walk missed arbitrary-depth .s2a path {deep_file}; "
        f"predicate={mod._is_lane_report_relpath(rel)} defaults={sorted(defaults)}"
    )


# ---------------------------------------------------------------------------
# HARM-08 — block-scoped ignore (outside fenced verbatim output)
# ---------------------------------------------------------------------------


def test_ignore_next_block_skips_tokens_inside_following_fence(report_dir: Path) -> None:
    """HARM-08: sha-guard:ignore-next-block covers the next fenced block only."""
    path = _write(
        report_dir / "ignore_next_block.md",
        "\n".join(
            [
                "Prose before the capture.",
                "<!-- sha-guard:ignore-next-block -->",
                "```",
                "synthetic head_sha='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'",
                "PASS: genuine SHA accepted: aaaaaaaa…",
                "```",
                "After the fence, unresolvable beef001 must still fail.",
                "",
            ]
        ),
    )
    rel = str(path.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode != 0, (
        f"token after ignored fence must still fail; stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert "beef001" in proc.stderr
    assert "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in proc.stderr


def test_ignore_next_block_required_when_fence_has_foreign_sha(report_dir: Path) -> None:
    """HARM-08 control: foreign SHA inside a fence without the directive fails."""
    path = _write(
        report_dir / "fence_no_ignore.md",
        "\n".join(
            [
                "```",
                "synthetic head_sha='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'",
                "```",
                "",
            ]
        ),
    )
    rel = str(path.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode != 0
    assert "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" in proc.stderr


def test_ignore_next_block_alone_allows_fence_with_foreign_sha(report_dir: Path) -> None:
    """HARM-08: directive outside the fence restores verbatim content and passes."""
    path = _write(
        report_dir / "fence_with_ignore.md",
        "\n".join(
            [
                "<!-- sha-guard:ignore-next-block -->",
                "```",
                "synthetic head_sha='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'",
                "PASS: genuine SHA accepted: aaaaaaaa…   (synthetic test fixture)",
                "```",
                "",
            ]
        ),
    )
    rel = str(path.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode == 0, f"expected pass; stdout={proc.stdout!r} stderr={proc.stderr!r}"


def test_ignore_next_block_requires_immediate_adjacency(report_dir: Path) -> None:
    """VLM6-R2-G-05 / TEST-15: directive separated from fence by prose does NOT suppress.

    Docstring says 'immediately before'; blank lines are allowed, intervening
    non-blank content resets pending suppression (not 'anywhere earlier in file').
    """
    # Directive on line 3, seven lines of unrelated prose, fence on line 11.
    path = _write(
        report_dir / "ignore_block_nonadjacent.md",
        "\n".join(
            [
                "line1",
                "line2",
                "<!-- sha-guard:ignore-next-block -->",
                "prose a",
                "prose b",
                "prose c",
                "prose d",
                "prose e",
                "prose f",
                "prose g",
                "```",
                "synthetic head_sha='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'",
                "```",
                "",
            ]
        ),
    )
    rel = str(path.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode != 0, (
        f"non-adjacent ignore-next-block must NOT suppress fence; "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" in proc.stderr


def test_ignore_next_block_blank_lines_still_adjacent(report_dir: Path) -> None:
    """VLM6-R2-G-05: blank lines between directive and fence remain adjacent."""
    path = _write(
        report_dir / "ignore_block_blanks.md",
        "\n".join(
            [
                "<!-- sha-guard:ignore-next-block -->",
                "",
                "",
                "```",
                "synthetic head_sha='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'",
                "```",
                "",
            ]
        ),
    )
    rel = str(path.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode == 0, (
        f"blank lines must keep adjacency; stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )


# ---------------------------------------------------------------------------
# RF-07..RF-12 — Wave E guard-evasion closures (wE6)
# ---------------------------------------------------------------------------


def test_homoglyph_respects_sha_guard_ignore(report_dir: Path) -> None:
    """RF-07 / TEST-15: ``sha-guard:ignore`` must suppress homoglyph violations too.

    Pre-fix: the ASCII path honours ignore; the homoglyph loop does not, so the
    remediation the guard itself prints does not work for the class it names.
    """
    # с = U+0441, е = U+0435  → renders like c9f7c6e
    sha = "\u04419f7\u04416\u0435"
    path = _write(
        report_dir / "rf07_homoglyph_ignore.md",
        f"Foreign lookalike `{sha}` sha-guard:ignore for documentation.\n",
    )
    rel = str(path.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode == 0, (
        f"homoglyph + sha-guard:ignore must pass; "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert "homoglyph" not in (proc.stdout + proc.stderr).lower()


def test_homoglyph_without_ignore_still_fails(report_dir: Path) -> None:
    """RF-07 control: lookalike without ignore remains a hard violation."""
    sha = "\u04419f7\u04416\u0435"
    path = _write(
        report_dir / "rf07_homoglyph_no_ignore.md",
        f"Foreign lookalike `{sha}` for documentation.\n",
    )
    rel = str(path.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode != 0, (
        f"homoglyph without ignore must fail; stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    combined = (proc.stdout + proc.stderr).lower()
    assert "homoglyph" in combined or "lookalike" in combined


def test_unclosed_fence_after_ignore_next_block_fails_closed(report_dir: Path) -> None:
    """RF-08 / TEST-15: ignore-next-block + unclosed fence must not silence the rest.

    Pre-fix: ignore_this_fence stays true to EOF, every subsequent line is
    skipped, and the guard exits 0 with '0 citations found'.
    """
    path = _write(
        report_dir / "rf08_unclosed_fence.md",
        "\n".join(
            [
                "<!-- sha-guard:ignore-next-block -->",
                "```",
                "synthetic head_sha='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'",
                "After the unclosed fence, unresolvable beef001 must still surface.",
                "Landed at commit beef001.",
                "",
            ]
        ),
    )
    rel = str(path.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode != 0, (
        f"unclosed ignored fence must fail closed; "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    combined = (proc.stdout + proc.stderr).lower()
    assert "all resolve" not in combined
    assert "unclosed" in combined or "beef001" in combined


def test_default_walk_prunes_vendored_trees(tmp_path: Path) -> None:
    """RF-09 / TEST-15: default walk must not harvest .s2a reports under .venv etc."""
    mod = _load_guard_module()
    (tmp_path / ".venv" / "lib" / ".s2a").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / ".s2a" / "venv_report.md").write_text(
        "commit deadbee\n", encoding="utf-8"
    )
    (tmp_path / "node_modules" / "pkg" / ".s2a").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / ".s2a" / "nm_report.md").write_text(
        "commit cafebab\n", encoding="utf-8"
    )
    real_dir = tmp_path / ".s2a"
    real_dir.mkdir()
    real_file = real_dir / "real.md"
    real_file.write_text("no tokens here\n", encoding="utf-8")

    defaults = {p.resolve() for p in mod._default_report_paths(tmp_path)}
    assert real_file.resolve() in defaults
    vendored = [p for p in defaults if ".venv" in p.parts or "node_modules" in p.parts]
    assert vendored == [], f"default walk entered vendored trees: {vendored}"


def test_default_walk_zero_targets_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RF-10 / TEST-15: default walk with zero targets must not exit 0 silently.

    Pre-fix: empty target list falls through to '0 file(s), 0 citations found'
    and return 0 — CI green having checked nothing.
    """
    mod = _load_guard_module()
    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)
    # tmp_path has no .s2a reports → default walk is empty.
    proc_rc = mod.main([])
    assert proc_rc != 0, (
        f"empty default walk must exit non-zero; rc={proc_rc}"
    )


def test_markdown_emphasis_interior_hex_is_visible_and_flagged(report_dir: Path) -> None:
    """RF-11 / TEST-15: ``dead*beef*…`` must not evade the tokenizer.

    Pre-fix: ``\\b`` hex matching sees three fragments; rendered form is one SHA.
    """
    path = _write(
        report_dir / "rf11_md_emphasis.md",
        "Landed at commit dead*beef*1234567 in the sandbox.\n",
    )
    rel = str(path.relative_to(REPO_ROOT))
    proc = _run_guard(rel)
    assert proc.returncode != 0, (
        f"emphasis-interior hex must fail closed; "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    err = proc.stderr.lower()
    assert "deadbeef1234567" in err or "does not resolve" in err
    assert "0 citations found" not in proc.stdout
