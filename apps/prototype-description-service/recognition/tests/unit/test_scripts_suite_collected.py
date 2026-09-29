from __future__ import annotations

import subprocess
import sys
from collections import Counter
from pathlib import Path


def test_every_script_test_module_is_collected_once() -> None:
    project_root = Path(__file__).resolve().parents[3]
    scripts_root = project_root / "recognition" / "tests" / "scripts"
    expected_modules = {
        path.relative_to(project_root).as_posix()
        for path in scripts_root.rglob("*.py")
        if path.name.startswith("test_") or path.name.endswith("_test.py")
    }

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    script_root = scripts_root.resolve()
    collected_items: list[str] = []
    for line in result.stdout.splitlines():
        if "::" not in line:
            continue
        module_path, test_name = line.strip().split("::", 1)
        module = Path(module_path)
        if not module.is_absolute():
            module = project_root / module
        try:
            relative_module = module.resolve().relative_to(script_root)
        except ValueError:
            continue
        collected_items.append(
            f"{(scripts_root / relative_module).relative_to(project_root).as_posix()}::{test_name}"
        )

    collected_modules = {item.split("::", 1)[0] for item in collected_items}
    assert collected_modules == expected_modules, (
        f"missing script test modules: {sorted(expected_modules - collected_modules)}; "
        f"unexpected script test modules: {sorted(collected_modules - expected_modules)}\n"
        f"{result.stdout}{result.stderr}"
    )

    duplicate_items = sorted(item for item, count in Counter(collected_items).items() if count > 1)
    assert not duplicate_items, f"script tests collected more than once: {duplicate_items}"
