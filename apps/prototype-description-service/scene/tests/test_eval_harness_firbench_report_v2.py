"""H2-REP strict finite report input and emission (sole-owned new suite).

Covers the part of the lane that needs no sibling producer: every loaded JSON value is
finite-checked before any report output is created, and inline and report.json JSON are
emitted strictly. Version-aware scores-v2 loading and v2 hypothesis display need
H2-CON-S, H2-CON-M and H2-SIO and are not exercised here.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness.firbench_report import _binding_json, render_report

FIXTURES = Path(__file__).parent / "fixtures" / "firbench_interchange_v1"
RUN_ID = "run-0001"
OVERFLOW_REASON = "H2-REP: overflowing JSON metadata must be refused before report output"
REFUSED_MANIFESTS = (
    '{"synthetic_extra": 1e999}',
    '{"synthetic_extra": -1e999}',
    '{"synthetic_extra": {"deep": [1, {"x": 1E400}]}}',
    '{"synthetic_extra": NaN}',
    '{"synthetic_extra": Infinity}',
    '{"synthetic_extra": -Infinity}',
    '{"synthetic_extra": 1, "synthetic_extra": 2}',
)
_INLINE_JSON = re.compile(r'<script type="application/json" id="report-view-data">(.*?)</script>', re.S)


def _refuses(call: Callable[[], object]) -> bool:
    """True only for the documented contract refusal; any other exception propagates."""
    try:
        call()
    except fc.FrameContractError:
        return True
    return False


def _assert_finite(value: Any) -> None:
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, float):
            assert math.isfinite(item), f"non-finite number emitted: {item}"
        elif isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def _strict_loads(text: str) -> Any:
    def refuse(token: str) -> None:
        raise AssertionError(f"non-finite JSON constant emitted: {token}")

    value = json.loads(text, parse_constant=refuse)
    _assert_finite(value)
    return value


def _run(tmp_path: Path, manifest: str | None) -> Path:
    run = tmp_path / "repo" / "benchmarks" / "private" / "firbench" / "runs" / RUN_ID
    run.mkdir(parents=True)
    scores = json.loads((FIXTURES / "scores-v1.json").read_text(encoding="utf-8"))
    scores.pop("face_outcomes", None)
    (run / "scores.json").write_text(json.dumps(scores, sort_keys=True), encoding="utf-8")
    clusters = (FIXTURES / "clusters-v1.json").read_text(encoding="utf-8")
    (run / "clusters.json").write_text(clusters, encoding="utf-8")
    if manifest is not None:
        (run / "manifest.json").write_text(manifest, encoding="utf-8")
    return run


def _render(run: Path, out: Path) -> Path:
    return render_report(run, out_dir=out, include_crops=False)


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {p.relative_to(directory).as_posix(): p.read_bytes() for p in sorted(directory.rglob("*")) if p.is_file()}


def test_report_refuses_overflow_metadata_before_output(tmp_path: Path) -> None:
    # Executable v1 baseline: v2 producers are not landed. Finite/null metadata renders first;
    # exponent overflow must then be refused by the parser and by a full render that leaves
    # the existing report bytes unchanged and creates no fresh output directory.
    run = _run(tmp_path, '{"synthetic_extra": {"finite": 1.5, "null": null}}')
    out = run / "report"
    _render(run, out)
    before = _snapshot(out)
    assert _refuses(lambda: _binding_json(b'{"synthetic_extra": 1e999}', "manifest.json")), OVERFLOW_REASON
    (run / "manifest.json").write_text('{"synthetic_extra": 1e999}', encoding="utf-8")
    assert _refuses(lambda: _render(run, out)), OVERFLOW_REASON
    assert _snapshot(out) == before
    fresh = run / "fresh"
    assert _refuses(lambda: _render(run, fresh)), OVERFLOW_REASON
    assert not fresh.exists()


@pytest.mark.parametrize("raw", [b'{"x": NaN}', b'{"x": Infinity}', b'{"x": -Infinity}', b"[1, -Infinity]"])
def test_literal_nonfinite_json_constants_refuse(raw: bytes) -> None:
    with pytest.raises(fc.FrameContractError, match="non-finite JSON constant"):
        _binding_json(raw, "manifest.json")


def test_duplicate_json_keys_refuse() -> None:
    with pytest.raises(fc.FrameContractError, match="duplicate JSON key"):
        _binding_json(b'{"x": 1, "x": 2}', "manifest.json")


@pytest.mark.parametrize(
    "raw",
    [
        b'{"synthetic_extra": 1e999}',
        b'{"synthetic_extra": -1e999}',
        b'{"synthetic_extra": {"deep": [1, {"x": 1E400}]}}',
        b'[{"a": [-1e999]}]',
    ],
)
def test_exponent_overflow_refuses_at_any_depth(raw: bytes) -> None:
    with pytest.raises(fc.FrameContractError, match="non-finite JSON number"):
        _binding_json(raw, "manifest.json")


def test_finite_and_null_json_values_parse_unchanged() -> None:
    raw = b'{"a": 1.5, "b": null, "c": [-0.0, 1e-300, 12345678901234567890]}'
    assert _binding_json(raw, "manifest.json") == {"a": 1.5, "b": None, "c": [-0.0, 1e-300, 12345678901234567890]}


@pytest.mark.parametrize("manifest", REFUSED_MANIFESTS)
def test_full_render_refuses_nonfinite_metadata_without_creating_output(tmp_path: Path, manifest: str) -> None:
    run = _run(tmp_path, manifest)
    fresh = run / "fresh"
    assert _refuses(lambda: _render(run, fresh)), "non-finite or duplicate metadata must be refused before output"
    assert not fresh.exists()


@pytest.mark.parametrize("manifest", REFUSED_MANIFESTS)
def test_refused_render_leaves_existing_report_bytes_identical(tmp_path: Path, manifest: str) -> None:
    run = _run(tmp_path, '{"synthetic_extra": null}')
    out = run / "report"
    _render(run, out)
    before = _snapshot(out)
    (run / "manifest.json").write_text(manifest, encoding="utf-8")
    assert _refuses(lambda: _render(run, out)), "refused metadata must not reach existing report outputs"
    assert _snapshot(out) == before


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ('{"synthetic_extra": 1.5}', 1.5),
        ('{"synthetic_extra": null}', None),
        ('{"synthetic_extra": [0, -2.5, 1e-300]}', [0, -2.5, 1e-300]),
    ],
)
def test_finite_and_null_metadata_emits_strict_inline_and_report_json(
    tmp_path: Path, metadata: str, expected: Any
) -> None:
    run = _run(tmp_path, metadata)
    index = _render(run, run / "report")
    inline = _INLINE_JSON.search(index.read_text(encoding="utf-8"))
    assert inline is not None
    assert _strict_loads(inline.group(1))["files"]["manifest.json"]["synthetic_extra"] == expected
    report = _strict_loads((index.parent / "report.json").read_text(encoding="utf-8"))
    assert "manifest.json" in report["inputs"]
