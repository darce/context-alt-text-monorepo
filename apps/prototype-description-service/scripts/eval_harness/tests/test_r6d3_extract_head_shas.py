"""S2R5-17 — extract_head_shas is dead; delete it (GF-11).

The repo-root guard's main path uses extract_stamps. extract_head_shas
was kept as a 'legacy helper' with zero callers. Greenfield policy is
delete-over-flag: the name must not remain as a wrapper, alias, or
NotImplemented stub.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import sys
from pathlib import Path


_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parents[5]
_GUARD_SCRIPT = _REPO_ROOT / "scripts" / "check_published_head_sha.py"


def _load_guard():
    spec = importlib.util.spec_from_file_location(
        "check_published_head_sha_r6d3", _GUARD_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_extract_head_shas_is_not_defined() -> None:
    """A retained legacy helper is the defect. hasattr must be False."""
    guard = _load_guard()
    assert not hasattr(guard, "extract_head_shas"), (
        "extract_head_shas is dead (zero callers); delete it — do not keep "
        "a wrapper, alias, or NotImplemented stub (S2R5-17 / GF-11)"
    )


def test_extract_head_shas_is_absent_from_source() -> None:
    """Walk-around pin: an assignment alias would still bind the name."""
    source = _GUARD_SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    defined = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "extract_head_shas":
            defined.append(f"def:{node.lineno}")
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "extract_head_shas":
                    defined.append(f"assign:{node.lineno}")
    assert defined == [], (
        "extract_head_shas still appears in "
        f"{_GUARD_SCRIPT.name} at {defined}"
    )


def test_extract_stamps_remains_the_public_harvester() -> None:
    """Deleting the dead helper must not take extract_stamps with it."""
    guard = _load_guard()
    assert hasattr(guard, "extract_stamps")
    assert inspect.isfunction(guard.extract_stamps)
    main_src = inspect.getsource(guard.main)
    assert "extract_stamps" in main_src
    assert "extract_head_shas" not in main_src
