"""S2R5-01: eval-harness tests must sit on the default pytest gate.

The default collection must reach this tree while recursive collection
from the service root still excludes the service's non-test scripts.
A green app suite that never executes this directory is the same class
of gate-greenwash as the prior remote-gate incident (TEST-15 / AUDIT-08).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _collect(project_root: Path, *paths: str) -> tuple[list[str], str]:
    env = os.environ.copy()
    env.pop("ACX_STRICT_GATE", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            *paths,
        ],
        cwd=project_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return (
        [line.split("::", maxsplit=1)[0] for line in result.stdout.splitlines() if "::" in line],
        result.stdout + result.stderr,
    )


def _is_under(item_path: str, root: Path, project_root: Path) -> bool:
    path = Path(item_path)
    if not path.is_absolute():
        path = project_root / path
    return path.resolve().is_relative_to(root.resolve())


def test_eval_harness_tests_are_on_default_testpaths() -> None:
    """The default gate must collect this tree through pytest's public interface."""
    project_root = Path(__file__).resolve().parents[3]
    items, output = _collect(project_root)

    assert any(item.startswith("scripts/eval_harness/tests/") for item in items), output


def test_scripts_norecursedirs_still_blocks_unrelated_script_trees() -> None:
    """Keep service scripts out of broad collection while default tests stay reachable."""
    project_root = Path(__file__).resolve().parents[3]
    script_root = project_root / "scripts"
    default_items, default_output = _collect(project_root)
    assert any(
        item.startswith("scripts/eval_harness/tests/") for item in default_items
    ), default_output

    broad_items, broad_output = _collect(project_root, ".")
    unrelated = [
        item
        for item in broad_items
        if _is_under(item, script_root, project_root)
    ]
    assert not unrelated, f"collected service script items: {unrelated}\n{broad_output}"
