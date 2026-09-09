"""VLM6-RV18-13: keep operator-facing path slots on the shared wire.

This is a source census rather than a test of one command's happy path.  The
eval harness has several small, offline commands and an incident report that
checked only two of them would leave the same surrogate-path failure in the
next generator.  The census follows the operator sinks owned by this slice;
machine-readable ``path`` fields are deliberately outside this check.
"""

from __future__ import annotations

import ast
import os
import warnings
from pathlib import Path

import pytest

from scripts.eval_harness._pathtext import _printable_path
from scripts.eval_harness.bakeoff_candidates import RegistryError, load_bakeoff_candidates
from scripts.eval_harness.corpus_inventory import load_records
from scripts.eval_harness.export_identities import identities_for_image

_SERVICE_ROOT = Path(__file__).resolve().parents[2]
_HARNESS_DIR = _SERVICE_ROOT / "scripts" / "eval_harness"

# These are the non-CLI producers in the RV18-13 audit frontier.  Keep this
# list explicit so adding a new producer forces the audit to make a decision.
_OWNED_MODULES = frozenset(
    {
        "bakeoff_candidates.py",
        "corpus_inventory.py",
        "draft_labels.py",
        "export_identities.py",
        "face_pass.py",
        "fusion_runner.py",
        "generate_determinism_anchor.py",
        "generate_face_determinism_anchor.py",
        "strata.py",
        "seed_roster.py",
        "zero_rule_baseline.py",
    }
)

# These files have operator sinks but are owned by the neighbouring CLI/report
# slices.  Naming them here keeps the whole current module inventory visible;
# their own owners must carry the same wire contract when those slices land.
_NEIGHBOUR_MODULES = frozenset(
    {
        "build_bakeoff_report.py",
        "cli.py",
        "describe_baseline.py",
        "report.py",
    }
)

_SINK_NAMES = frozenset(
    {"print", "error", "warn", "exit", "FacePassStalledError", "RegistryError", "RuntimeError"}
)


def _call_name(node: ast.Call) -> str | None:
    function = node.func
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return function.attr
    return None


def _contains_path_hint(node: ast.AST) -> bool:
    """Conservative source hint for a value occupying a path-bearing slot."""
    names = [candidate.id.lower() for candidate in ast.walk(node) if isinstance(candidate, ast.Name)]
    names.extend(candidate.attr.lower() for candidate in ast.walk(node) if isinstance(candidate, ast.Attribute))
    for name in names:
        if name in {"path", "paths", "dir", "root", "file", "filename", "checkpoint", "out"}:
            return True
        if name.endswith(("_path", "_dir", "_file", "_filename", "_checkpoint")):
            return True
        # The anchor generators return report paths under short names; hashes
        # and report objects use the same prefixes but are not path slots.
        if name in {"report_json", "report_md", "manifest_json", "manifest_md"}:
            return True
    return False


def _has_path_encoder(node: ast.AST) -> bool:
    return any(
        isinstance(candidate, ast.Call)
        and isinstance(candidate.func, ast.Name)
        and candidate.func.id == _printable_path.__name__
        for candidate in ast.walk(node)
    )


def _module_operator_path_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node) not in _SINK_NAMES:
            continue
        # FacePassStalledError's checkpoint Path is a structured exception
        # field consumed by the caller; only its first argument is operator
        # text.  The other sinks receive operator text in every argument.
        arguments = node.args[:1] if _call_name(node) == "FacePassStalledError" else node.args
        for argument in arguments:
            values: list[ast.AST] = []
            if isinstance(argument, ast.JoinedStr):
                values.extend(
                    formatted.value
                    for formatted in argument.values
                    if isinstance(formatted, ast.FormattedValue)
                )
            else:
                values.append(argument)
            for value in values:
                if _contains_path_hint(value) and not _has_path_encoder(value):
                    violations.append(f"{path.name}:{getattr(value, 'lineno', node.lineno)}: {ast.unparse(value)}")
    return violations


def test_current_harness_inventory_is_classified() -> None:
    current = {path.name for path in _HARNESS_DIR.glob("*.py")}
    assert current >= _OWNED_MODULES
    assert current >= _NEIGHBOUR_MODULES

    # Every module with a path-bearing operator sink must be either owned by
    # this slice or named for the neighbouring owner.  This catches a new
    # generator silently escaping the review frontier.
    sink_modules = {
        path.name
        for path in _HARNESS_DIR.glob("*.py")
        if _module_operator_path_violations(path)
    }
    assert sink_modules <= _OWNED_MODULES | _NEIGHBOUR_MODULES


def test_owned_operator_path_slots_use_the_canonical_encoder() -> None:
    violations = {
        path.name: _module_operator_path_violations(path)
        for path in sorted(_HARNESS_DIR.glob("*.py"))
        if path.name in _OWNED_MODULES and _module_operator_path_violations(path)
    }
    assert not violations


def _surrogate_path(tmp_path: Path, leaf: bytes) -> Path:
    """Create a path whose Python spelling contains a PEP-383 surrogate."""
    raw = os.fsencode(str(tmp_path)) + b"/" + leaf
    return Path(os.fsdecode(raw))


class _ReadablePathProbe:
    """Path-like checkpoint whose bytes cannot be created on macOS/APFS."""

    def __init__(self, raw: bytes) -> None:
        self._path = os.fsdecode(raw)

    def __fspath__(self) -> str:
        return self._path

    def exists(self) -> bool:
        return True

    def read_text(self) -> str:
        return '{"stale": true}\n'


def test_checkpoint_warning_uses_path_wire_for_surrogate_name(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _ReadablePathProbe(os.fsencode(str(tmp_path)) + b"/checkpoint-\xe9.jsonl")

    assert load_records(path) == []
    stderr = capsys.readouterr().err
    assert "undecodable:" in stderr and "checkpoint-\\xe9.jsonl" in stderr
    assert "\\udce9" not in stderr


def test_registry_error_uses_path_wire_for_surrogate_name(tmp_path: Path) -> None:
    path = _surrogate_path(tmp_path, b"candidate-\xe9.yaml")

    with pytest.raises(RegistryError) as excinfo:
        load_bakeoff_candidates(path)

    assert "candidate-\\xe9.yaml" in str(excinfo.value)
    assert "\\udce9" not in str(excinfo.value)


def test_identity_warning_uses_path_wire_for_surrogate_filename() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        identities_for_image(b"\xff\xd8\xff\xd9", source="celeb", filename="28514407-\udce9.jpg")

    assert caught
    message = str(caught[0].message)
    assert "undecodable:28514407-\\xe9.jpg" in message
    assert "\\udce9" not in message


def test_caption_anchor_main_uses_path_wire_for_report_outputs(tmp_path: Path, monkeypatch, capsys) -> None:
    from scripts.eval_harness import generate_determinism_anchor as anchor

    output_dir = _surrogate_path(tmp_path, b"anchor-\xe9")
    paths = tuple(
        _surrogate_path(tmp_path, leaf)
        for leaf in (b"manifest-\xe9.json", b"run-\xe9.json", b"report-\xe9.json")
    )
    paths += (_surrogate_path(tmp_path, b"report-\xe9.md"),)
    monkeypatch.setattr(anchor, "validate_live_head_sha", lambda _value: None)
    monkeypatch.setattr(anchor, "write_anchor", lambda **_kwargs: (*paths[1:], "a" * 64))

    assert anchor.main(["--out-dir", str(output_dir)]) == 0
    stdout = capsys.readouterr().out
    assert stdout.count("undecodable:") == 4
    assert "\\udce9" not in stdout


def test_face_anchor_main_uses_path_wire_for_report_outputs(tmp_path: Path, monkeypatch, capsys) -> None:
    from scripts.eval_harness import generate_face_determinism_anchor as anchor

    output_dir = _surrogate_path(tmp_path, b"face-anchor-\xe9")
    paths = tuple(
        _surrogate_path(tmp_path, leaf)
        for leaf in (b"manifest-\xe9.json", b"run-\xe9.json", b"report-\xe9.json", b"report-\xe9.md")
    )
    monkeypatch.setattr(anchor, "write_face_anchor", lambda **_kwargs: (*paths, "b" * 64))

    assert anchor.main(["--out-dir", str(output_dir)]) == 0
    stdout = capsys.readouterr().out
    assert stdout.count("undecodable:") == 4
    assert "\\udce9" not in stdout
