"""VLM6-W17-L-01: <path-text> encoder has one definition site.

cli.py and manifest.py must re-export the same objects from _pathtext.py.
A second ``def _printable_path`` (or the marker helper / prefix constant)
under scripts/eval_harness/ is a wire-format fork. Scan source; do not
trust imports. Object identity is the second pin.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[2]
_HARNESS_DIR = _SERVICE_ROOT / "scripts" / "eval_harness"
_CANONICAL = "_pathtext.py"
_FUNCTION_NAMES = frozenset({"_printable_path", "_escape_undecodable_marker"})
_PREFIX_NAME = "_UNDECODABLE_PATH_PREFIX"


def _rel(path: Path) -> str:
    return path.relative_to(_HARNESS_DIR).as_posix()


def _definition_sites() -> dict[str, list[str]]:
    """AST definitions of the encoder names outside _pathtext.py."""
    found: dict[str, list[str]] = {
        "_printable_path": [],
        "_escape_undecodable_marker": [],
        _PREFIX_NAME: [],
    }
    for path in sorted(_HARNESS_DIR.rglob("*.py")):
        if _rel(path) == _CANONICAL:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in _FUNCTION_NAMES
            ):
                found[node.name].append(f"{_rel(path)}:{node.lineno}")
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == _PREFIX_NAME:
                        found[_PREFIX_NAME].append(f"{_rel(path)}:{node.lineno}")
            elif (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == _PREFIX_NAME
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

    assert (
        cli._printable_path
        is _pathtext._printable_path
        is manifest._printable_path
    )
