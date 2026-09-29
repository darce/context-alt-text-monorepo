from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def test_nested_collection_does_not_replace_outer_receipt(
    tmp_path: Path, monkeypatch, nested_collection_runner
) -> None:
    project_root = tmp_path / "project"
    tests_a = project_root / "tests_a"
    tests_b = project_root / "tests_b"
    tests_a.mkdir(parents=True)
    tests_b.mkdir()
    (tests_a / "test_a.py").write_text("def test_a(): assert True\n", encoding="utf-8")
    (tests_b / "test_b.py").write_text("def test_b(): assert True\n", encoding="utf-8")

    outer_receipt = tmp_path / "prototype-description-service-pytest-collection-scope.json"
    nested_receipt = tmp_path / "nested-receipt.json"
    outer_receipt.write_text("outer receipt\n", encoding="utf-8")
    outer_contents = outer_receipt.read_bytes()
    outer_mtime = outer_receipt.stat().st_mtime_ns
    (project_root / "pytest.ini").write_text(
        "[pytest]\n"
        "testpaths = tests_a tests_b\n"
        f"collection_scope_receipt = {outer_receipt}\n",
        encoding="utf-8",
    )
    service_root = Path(__file__).resolve().parents[3]
    conftest_source = (service_root / "conftest.py").read_text(encoding="utf-8")
    receipt_directory = '_RECEIPT_DIRECTORY = Path("/tmp")'
    assert conftest_source.count(receipt_directory) == 1
    (project_root / "conftest.py").write_text(
        conftest_source.replace(receipt_directory, f"_RECEIPT_DIRECTORY = Path({str(tmp_path)!r})"),
        encoding="utf-8",
    )
    monkeypatch.setenv("ACX_STRICT_GATE", "1")

    items, output = nested_collection_runner(
        project_root, nested_receipt, "tests_a/test_a.py"
    )

    assert outer_receipt.read_bytes() == outer_contents, output
    assert outer_receipt.stat().st_mtime_ns == outer_mtime, output
    assert nested_receipt.exists(), output
    assert json.loads(nested_receipt.read_text(encoding="utf-8"))["scope"] == "narrowed"
    assert any(item.startswith("tests_a/test_a.py::") for item in items), output


def test_every_script_test_module_is_collected_once(
    nested_default_collection: tuple[tuple[str, ...], str],
) -> None:
    collected_items, output = nested_default_collection
    project_root = Path(__file__).resolve().parents[3]
    scripts_root = project_root / "recognition" / "tests" / "scripts"
    expected_modules = {
        path.relative_to(project_root).as_posix()
        for path in scripts_root.rglob("*.py")
        if path.name.startswith("test_") or path.name.endswith("_test.py")
    }

    script_root = scripts_root.resolve()
    script_items: list[str] = []
    for line in collected_items:
        module_path, test_name = line.strip().split("::", 1)
        module = Path(module_path)
        if not module.is_absolute():
            module = project_root / module
        try:
            relative_module = module.resolve().relative_to(script_root)
        except ValueError:
            continue
        script_items.append(
            f"{(scripts_root / relative_module).relative_to(project_root).as_posix()}::{test_name}"
        )

    collected_modules = {item.split("::", 1)[0] for item in script_items}
    assert collected_modules == expected_modules, (
        f"missing script test modules: {sorted(expected_modules - collected_modules)}; "
        f"unexpected script test modules: {sorted(collected_modules - expected_modules)}\n{output}"
    )

    duplicate_items = sorted(item for item, count in Counter(script_items).items() if count > 1)
    assert not duplicate_items, f"script tests collected more than once: {duplicate_items}"
