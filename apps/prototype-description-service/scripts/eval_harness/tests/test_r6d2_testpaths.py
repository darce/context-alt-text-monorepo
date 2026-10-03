"""S2R5-01: eval-harness tests must sit on the default pytest gate.

The default collection must reach this tree while recursive collection
from the service root still excludes the service's non-test scripts.
A green app suite that never executes this directory is the same class
of gate-greenwash as the prior remote-gate incident (TEST-15 / AUDIT-08).
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest


def _pytest_ini() -> dict[str, Any]:
    project_root = Path(__file__).resolve().parents[3]
    pyproject = tomllib.loads(
        (project_root / "pyproject.toml").read_text(encoding="utf-8")
    )
    return pyproject["tool"]["pytest"]["ini_options"]


def test_recognition_tests_are_declared_in_default_testpaths() -> None:
    """Guard the recognition root from the independently collected eval tree."""
    testpaths = _pytest_ini()["testpaths"]
    assert "recognition/tests" in testpaths


def test_scripts_remain_excluded_from_broad_pytest_recursion() -> None:
    """Keep non-test service scripts out of broad pytest recursion."""
    assert (
        "apps/prototype-description-service/scripts"
        in _pytest_ini()["norecursedirs"]
    )


@pytest.fixture(scope="session")
def nested_default_collection(tmp_path_factory, nested_collection_runner):
    project_root = Path(__file__).resolve().parents[3]
    receipt_path = tmp_path_factory.mktemp("r6d2-default") / "receipt.json"
    return nested_collection_runner(project_root, receipt_path)


@pytest.fixture(scope="session")
def nested_broad_collection(tmp_path_factory, nested_collection_runner):
    project_root = Path(__file__).resolve().parents[3]
    receipt_path = tmp_path_factory.mktemp("r6d2-broad") / "receipt.json"
    return nested_collection_runner(project_root, receipt_path, ".")


def _is_under(item_path: str, root: Path, project_root: Path) -> bool:
    path = Path(item_path.split("::", maxsplit=1)[0])
    if not path.is_absolute():
        path = project_root / path
    return path.resolve().is_relative_to(root.resolve())


@pytest.mark.integration
def test_eval_harness_tests_are_on_default_testpaths(
    nested_default_collection: tuple[tuple[str, ...], str],
) -> None:
    """The default gate must collect this tree through pytest's public interface."""
    items, output = nested_default_collection

    assert any(item.startswith("scripts/eval_harness/tests/") for item in items), output


@pytest.mark.integration
def test_scripts_norecursedirs_still_blocks_unrelated_script_trees(
    nested_default_collection: tuple[tuple[str, ...], str],
    nested_broad_collection: tuple[tuple[str, ...], str],
) -> None:
    """Keep service scripts out of broad collection while default tests stay reachable."""
    project_root = Path(__file__).resolve().parents[3]
    script_root = project_root / "scripts"
    default_items, default_output = nested_default_collection
    assert any(
        item.startswith("scripts/eval_harness/tests/") for item in default_items
    ), default_output

    broad_items, broad_output = nested_broad_collection
    unrelated = [
        item
        for item in broad_items
        if _is_under(item, script_root, project_root)
    ]
    assert not unrelated, f"collected service script items: {unrelated}\n{broad_output}"
