from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


TOOLS = Path(__file__).resolve().parents[1] / "tools"
BUILDER = TOOLS / "build_decision_report.py"
ASSETS = TOOLS / "description-review"
FIXTURE = ASSETS / "fixtures" / "qwen-high-precision-20261025"
RULE = ASSETS / "decision-rule.json"
EXISTING_BLOCKS = (
    "operator-review-contract",
    "operator-review-initial-state",
    "operator-review-manifest",
    "operator-review-previous-manifests",
)
ASSET_NAMES = (
    "operator-metrics.js",
    "operator-crossmodel.js",
    "operator-decision.js",
    "operator-review.js",
    "operator-review.css",
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def blocks(path: Path) -> dict[str, bytes]:
    # Stream the large fixture rather than loading its entire HTML for assertions.
    result = {}
    pending = b""
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            pending += chunk
            while True:
                opening = re.search(
                    rb'<script type="application/json" id="([^"]+)">', pending
                )
                if opening is None:
                    pending = pending[-256:]
                    break
                closing = pending.find(b"</script>", opening.end())
                if closing < 0:
                    pending = pending[opening.start():]
                    break
                result[opening[1].decode()] = pending[opening.end():closing]
                pending = pending[closing + len(b"</script>"):]
    return result


@pytest.fixture
def assets(tmp_path: Path) -> Path:
    directory = tmp_path / "assets"
    directory.mkdir()
    for name in ("operator-metrics.js", "operator-review.js", "operator-review.css", "evaluation-method.html", "evaluation-research.json", "ranking-verification.json"):
        shutil.copyfile(ASSETS / name, directory / name)
    for name in ("operator-crossmodel.js", "operator-decision.js"):
        (directory / name).write_text("'use strict';\n", encoding="utf-8")
    return directory


def build(assets: Path, out: Path, *extra: str, rule: Path = RULE):
    return subprocess.run(
        [sys.executable, str(BUILDER), "--source", str(FIXTURE / "index.v2.html"),
         "--gpu-performance", str(FIXTURE / "gpu-performance.json"),
         "--rule", str(rule), "--assets", str(assets), "--out", str(out), *extra],
        capture_output=True, text=True, check=False,
    )


def output_bytes(directory: Path) -> dict[str, bytes]:
    return {str(p.relative_to(directory)): p.read_bytes()
            for p in directory.rglob("*") if p.is_file()}


def test_build_preserves_blocks_hashes_assets_and_is_deterministic(tmp_path, assets):
    out = tmp_path / "first"
    result = build(assets, out)
    assert result.returncode == 0, result.stderr
    original = blocks(FIXTURE / "index.v2.html")
    actual = blocks(out / "index.html")
    assert set(actual) == {*EXISTING_BLOCKS, "operator-decision-rule", "operator-decision-performance"}
    for name in EXISTING_BLOCKS:
        assert actual[name] == original[name]
    assert actual["operator-decision-rule"].replace(b"<\\/", b"</") == RULE.read_bytes()
    assert actual["operator-decision-performance"].replace(b"<\\/", b"</") == (
        FIXTURE / "decision-performance.json"
    ).read_bytes()

    for guide in ("evaluation-method.html", "evaluation-research.json", "ranking-verification.json"):
        assert (out / guide).read_bytes() == (assets / guide).read_bytes()

    html = (out / "index.html").read_text(encoding="utf-8")
    filenames = {}
    for name in ASSET_NAMES:
        stem, ext = name.rsplit(".", 1)
        data = (assets / name).read_bytes()
        hashed = f"{stem}.{sha(data)[:12]}.{ext}"
        filenames[name] = hashed
        assert (out / hashed).read_bytes() == data
        if ext == "js":
            assert f'<script defer src="{hashed}"></script>' in html
        else:
            assert f'<link rel="stylesheet" href="{hashed}">' in html
    scripts = re.findall(r'<script\b[^>]*\bsrc="([^"]+)"', html)
    assert scripts == [filenames[name] for name in ASSET_NAMES if name.endswith(".js")]
    receipt = json.loads((out / "decision-build-receipt.json").read_bytes())
    assert receipt["counts"] == {"decision_cells": 86, "perf_rows": 315, "timing_joins": 83}
    assert receipt["inputs"] == {
        "source": sha((FIXTURE / "index.v2.html").read_bytes()),
        "gpu_performance": sha((FIXTURE / "gpu-performance.json").read_bytes()),
        "rule": sha(RULE.read_bytes()),
        "assets": {name: sha((assets / name).read_bytes()) for name in ASSET_NAMES},
    }
    assert receipt["blocks"] == {name: sha(data) for name, data in actual.items()}
    assert receipt["outputs"] == {
        name: sha(data) for name, data in output_bytes(out).items()
        if name != "decision-build-receipt.json"
    }
    other = tmp_path / "second"
    result = build(assets, other)
    assert result.returncode == 0, result.stderr
    assert output_bytes(other) == output_bytes(out)
    assert build(assets, out).returncode == 0
    assert output_bytes(other) == output_bytes(out)


@pytest.mark.parametrize("field", ["manifest_sha256", "dataset_id", "rubric_version"])
def test_mismatched_rule_fails_before_writing(tmp_path, assets, field):
    rule = json.loads(RULE.read_bytes())
    rule[field] = "mismatched"
    changed = tmp_path / "rule.json"
    changed.write_text(json.dumps(rule), encoding="utf-8")
    out = tmp_path / "out"
    result = build(assets, out, rule=changed)
    assert result.returncode == 2
    assert field in result.stderr and "mismatch" in result.stderr.lower()
    assert not out.exists()


def test_copy_from_preserves_outputs_and_copies_linked_siblings(tmp_path, assets):
    source = tmp_path / "copy"
    (source / "images" / "nested").mkdir(parents=True)
    (source / "images" / "nested" / "example.jpg").write_bytes(b"image")
    (source / "generation-results.json").write_bytes(b"{}\n")
    out = tmp_path / "out"
    assert build(assets, out).returncode == 0
    built = output_bytes(out)
    for name in built:
        (source / name).write_bytes(b"must not overwrite generated output")
    result = build(assets, out, "--copy-from", str(source))
    assert result.returncode == 0, result.stderr
    for name, data in built.items():
        if name != "decision-build-receipt.json":
            assert (out / name).read_bytes() == data
    assert (out / "images" / "nested" / "example.jpg").read_bytes() == b"image"
    assert (out / "generation-results.json").read_bytes() == b"{}\n"
    receipt = json.loads((out / "decision-build-receipt.json").read_bytes())
    assert receipt["outputs"] == {
        name: sha(data) for name, data in output_bytes(out).items()
        if name != "decision-build-receipt.json"
    }


def test_new_json_blocks_escape_script_end_tags(tmp_path, assets):
    rule = json.loads(RULE.read_bytes())
    rule["note"] = "</script><script>alert('x')</script>"
    changed = tmp_path / "rule.json"
    raw = (json.dumps(rule, ensure_ascii=False) + "\n").encode()
    changed.write_bytes(raw)
    out = tmp_path / "out"
    result = build(assets, out, rule=changed)
    assert result.returncode == 0, result.stderr
    embedded = blocks(out / "index.html")["operator-decision-rule"]
    assert b"</" not in embedded
    assert embedded.replace(b"<\\/", b"</") == raw
