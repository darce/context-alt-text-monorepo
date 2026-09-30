from __future__ import annotations

def test_pytest_testpaths_include_script_test_suites(
    nested_default_collection: tuple[tuple[str, ...], str],
) -> None:
    items, output = nested_default_collection
    collected = [
        item
        for item in items
        if item.startswith("recognition/tests/scripts/")
    ]

    assert collected, output
