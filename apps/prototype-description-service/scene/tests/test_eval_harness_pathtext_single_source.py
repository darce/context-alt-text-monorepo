"""VLM6-W17-L-01: <path-text> encoder has one definition site.

cli.py and manifest.py must re-export the same objects from _pathtext.py.
A second ``def _printable_path`` (or the marker helper / prefix constant)
under scripts/eval_harness/ is a wire-format fork. Scan source; do not
trust imports. Object identity is the second pin.

VLM6-W18-F1-01: the path encoder and the message encoder must not compose
into a third wire form. Double application is a no-op on EncodedText;
it must never mutate an already-encoded value.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts.eval_harness._pathtext import (
    EncodedText,
    MessageText,
    PathText,
    _printable_message,
    _printable_path,
)

_SERVICE_ROOT = Path(__file__).resolve().parents[2]
_HARNESS_DIR = _SERVICE_ROOT / "scripts" / "eval_harness"
_CANONICAL = "_pathtext.py"
_FUNCTION_NAMES = frozenset({"_printable_path", "_printable_message", "_escape_undecodable_marker"})
_PREFIX_NAME = "_UNDECODABLE_PATH_PREFIX"

# Adversarial corpus for VLM6-W18-F1-01. latin-1 0xe9 is the PEP-383
# surrogate ``\udce9``, never café (os.fsencode+utf-8 masks the defect).
_ADVERSARIAL_CORPUS: tuple[tuple[str, str], ...] = (
    ("lone_surrogate", "\udce9"),
    ("latin1_0xe9_filename", "run-caf\udce9-report.md"),
    ("literal_undecodable_prefix", "undecodable:real-name.txt"),
    ("literal_backslash", "foo\\bar.txt"),
    ("literal_four_char_xe9", "run-caf\\xe9-report.md"),
    ("empty", ""),
    ("pure_ascii", "hello.txt"),
)


def _rel(path: Path) -> str:
    return path.relative_to(_HARNESS_DIR).as_posix()


def _definition_sites() -> dict[str, list[str]]:
    """AST definitions of the encoder names outside _pathtext.py."""
    found: dict[str, list[str]] = {
        "_printable_path": [],
        "_printable_message": [],
        "_escape_undecodable_marker": [],
        _PREFIX_NAME: [],
    }
    for path in sorted(_HARNESS_DIR.rglob("*.py")):
        if _rel(path) == _CANONICAL:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in _FUNCTION_NAMES:
                found[node.name].append(f"{_rel(path)}:{node.lineno}")
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == _PREFIX_NAME:
                        found[_PREFIX_NAME].append(f"{_rel(path)}:{node.lineno}")
            elif (
                isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == _PREFIX_NAME
            ):
                found[_PREFIX_NAME].append(f"{_rel(path)}:{node.lineno}")
    return found


def test_pathtext_encoder_has_single_definition_site() -> None:
    found = _definition_sites()
    offenders = {name: sites for name, sites in found.items() if sites}
    assert not offenders, (
        "wire-format encoder must be defined only in "
        "scripts/eval_harness/_pathtext.py; forked definitions: "
        f"{offenders}"
    )


def test_printable_path_is_shared_object() -> None:
    from scripts.eval_harness import _pathtext, cli, manifest

    assert cli._printable_path is _pathtext._printable_path is manifest._printable_path


def _hex(text: str) -> str:
    return text.encode("utf-8", errors="surrogateescape").hex()


@pytest.mark.parametrize("label,name", _ADVERSARIAL_CORPUS)
def test_printable_path_double_application_is_idempotent(label: str, name: str) -> None:
    """Property: path(path(x)) == path(x) for every adversarial name.

    MUT: drop the EncodedText re-entry guard in ``_printable_path`` (TEST-15).
    """
    once = _printable_path(name)
    twice = _printable_path(once)
    assert twice == once, (
        f"{label}: path(path(x)) mutated wire form {once!r} ({_hex(once)}) -> {twice!r} ({_hex(twice)})"
    )
    assert twice is once, f"{label}: re-entry must be identity on EncodedText"


@pytest.mark.parametrize("label,name", _ADVERSARIAL_CORPUS)
def test_printable_message_double_application_is_idempotent(label: str, name: str) -> None:
    """Property: message(message(x)) == message(x).

    MUT: drop the EncodedText re-entry guard in ``_printable_message``.
    Identity ``is`` fails; string equality can still hold because the
    message encoder is already string-idempotent.
    """
    once = _printable_message(name)
    twice = _printable_message(once)
    assert twice == once, f"{label}: message(message(x)) mutated {once!r} -> {twice!r}"
    assert twice is once, f"{label}: re-entry must be identity on EncodedText"


@pytest.mark.parametrize("label,name", _ADVERSARIAL_CORPUS)
def test_path_encoder_does_not_reencode_message_text(label: str, name: str) -> None:
    """Cross-composition: path(message(x)) is a no-op (first encoder wins).

    MUT: drop EncodedText re-entry in ``_printable_path``. A name that
    starts with ``undecodable:`` then gains a leading backslash — neither
    message form nor path form of the original.
    """
    encoded_msg = _printable_message(name)
    composed = _printable_path(encoded_msg)
    assert composed == encoded_msg, (
        f"{label}: path(message(x)) mutated {encoded_msg!r} ({_hex(encoded_msg)}) -> {composed!r} ({_hex(composed)})"
    )
    assert composed is encoded_msg


@pytest.mark.parametrize("label,name", _ADVERSARIAL_CORPUS)
def test_message_encoder_does_not_reencode_path_text(label: str, name: str) -> None:
    """Cross-composition: message(path(x)) is a no-op.

    MUT: drop EncodedText re-entry in ``_printable_message``.
    """
    encoded_path = _printable_path(name)
    composed = _printable_message(encoded_path)
    assert composed == encoded_path, f"{label}: message(path(x)) mutated {encoded_path!r} -> {composed!r}"
    assert composed is encoded_path


def test_first_encode_preserves_pathtext_wire_contract() -> None:
    """Idempotence must not be bought by changing the first-pass wire form."""
    latin1 = _printable_path("run-caf\udce9-report.md")
    assert isinstance(latin1, PathText)
    assert latin1 == "undecodable:run-caf\\xe9-report.md"
    assert latin1.encode("ascii") == bytes.fromhex("756e6465636f6461626c653a72756e2d6361665c7865392d7265706f72742e6d64")
    assert b"udce9" not in latin1.encode("ascii")

    assert _printable_path("undecodable:real-name.txt") == "\\undecodable:real-name.txt"
    assert _printable_path("run-caf\\xe9-report.md") == "run-caf\\xe9-report.md"
    assert _printable_path("") == ""
    assert _printable_path("hello.txt") == "hello.txt"
    assert _printable_path("foo\\bar.txt") == "foo\\bar.txt"


def test_encoded_types_are_str_subclasses() -> None:
    path = _printable_path("hello.txt")
    msg = _printable_message("hello.txt")
    assert isinstance(path, PathText)
    assert isinstance(path, EncodedText)
    assert isinstance(path, str)
    assert isinstance(msg, MessageText)
    assert isinstance(msg, EncodedText)
    assert isinstance(msg, str)
    assert type(path) is not type(msg)
