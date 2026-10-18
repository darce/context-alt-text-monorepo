"""FIRBENCH-1 comparison explorer: the ``explore`` CLI command renders a populated static page.

The export is built from the public legacy aggregate values below. They are copied verbatim from the
committed safe aggregate (``.task-state/firbench-1/ux/legacy-schema-aggregate.json``), with that file's
own sha256 values, so this module needs no file outside the test. Clustering and unknown-rejection values
are not in that aggregate, so the export leaves them null and the page must show them as not recorded.

Tests drive the real ``firbench_cli.main`` and never import the explorer module directly, so a RED run fails
on the behaviour, not on setup.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
from pathlib import Path

import pytest

from scripts.eval_harness import firbench_cli as cli

EXPORT_SCHEMA = "firbench/comparison-explorer-export-v1"
EXPORT_NAME = "comparison-explorer-export.json"
PAGE_NAME = "index.html"
PLAYWRIGHT_CORE = "/home/gate/firbench-1-context/browser-tools/node_modules/playwright-core"
CHROMIUM = "/home/gate/.cache/ms-playwright/chromium-1248/chrome-linux-arm64/chrome"

# (artifact_id, file_sha256) in source order, as listed by the legacy aggregate. Two entries share one hash.
_SOURCES = (
    ("golden150-fir-baseline-20260723", "c05fa6a7cc7b779fddee6def9e3ec5796424fd678a67c66ea7edd239ebfc3d98"),
    ("golden150-fir-buffalo-20260723", "84ed7fb3bb3211b5f3e52d2ec6bd1e1763924af93342af988616f64c2b7a4b24"),
    ("golden150-fir-buffalo-baseline-20260723", "84ed7fb3bb3211b5f3e52d2ec6bd1e1763924af93342af988616f64c2b7a4b24"),
    ("golden150-fir-final-20260723", "af3c3baa16aa039ffdc006505aec5ed493e256814cd7fbc89fac1bb0f0a03f8e"),
    ("golden150-fir-v2-20260723", "ff9dbaad7346cd63111061a870ea2a6694deb2d6a327200779a73c07674fe892"),
)
_SFACE_VALUES = {
    "model_id": "ort-yunet-sface",
    "embedding_dim": 128,
    "counts": {"total": 150, "scored": 150, "failed": 0, "matched_faces": 189, "named_matched": 100, "stranger_matched": 89},
    "detection": {"tp": 189, "fp": 0, "fn": 186, "precision": 1.0, "recall": 0.504},
}
_BUFFALO_VALUES = {
    "model_id": "buffalo_l",
    "embedding_dim": 512,
    "counts": {"total": 150, "scored": 150, "failed": 0, "matched_faces": 373, "named_matched": 166, "stranger_matched": 207},
    "detection": {"tp": 373, "fp": 2, "fn": 2, "precision": 0.9946666666666667, "recall": 0.9946666666666667},
}
_VALUES_BY_SHA = {
    "c05fa6a7cc7b779fddee6def9e3ec5796424fd678a67c66ea7edd239ebfc3d98": _SFACE_VALUES,
    "84ed7fb3bb3211b5f3e52d2ec6bd1e1763924af93342af988616f64c2b7a4b24": _BUFFALO_VALUES,
    "af3c3baa16aa039ffdc006505aec5ed493e256814cd7fbc89fac1bb0f0a03f8e": _SFACE_VALUES,
    "ff9dbaad7346cd63111061a870ea2a6694deb2d6a327200779a73c07674fe892": _SFACE_VALUES,
}
_MODEL_PIPELINES = {"ort-yunet-sface": "sface", "buffalo_l": "insightface"}
_SLICE_SECTIONS = (
    "clustering",
    "demographic",
    "full_corpus_identification",
    "headline_identification",
    "occlusion",
    "unknown_rejection",
)


def _public_export() -> dict:
    """The public legacy values in the explorer wire root. Nothing here is generated or estimated."""
    sources = [
        {
            "artifact_id": artifact_id,
            "file_sha256": sha,
            "kind": "report-json",
            "manifest_hash_kind": None,
            "manifest_sha256": None,
            "qualification": "partial",
            "source_sha": None,
        }
        for artifact_id, sha in sorted(_SOURCES)
    ]
    dedup = []
    reports = []
    for sha in sorted(_VALUES_BY_SHA):
        aliases = sorted(artifact_id for artifact_id, source_sha in _SOURCES if source_sha == sha)
        dedup.append({"file_sha256": sha, "artifact_ids": aliases})
        values = _VALUES_BY_SHA[sha]
        reports.append(
            {
                "artifact_id": aliases[0],
                "file_sha256": sha,
                "pipeline": _MODEL_PIPELINES[values["model_id"]],
                "model_id": values["model_id"],
                "embedding_dim": values["embedding_dim"],
                "counts": dict(values["counts"]),
                "detection": dict(values["detection"]),
                "unknown_rejection": None,
                "clustering": None,
                "identification": None,
                "slice_sections": list(_SLICE_SECTIONS),
                "compatibility": "unknown",
                "qualification": "partial",
            }
        )
    return {"schema": EXPORT_SCHEMA, "schema_version": 1, "sources": sources, "dedup": dedup, "reports": reports}


def _write_export(directory: Path, export: dict) -> Path:
    path = directory / EXPORT_NAME
    path.write_text(json.dumps(export, sort_keys=True), encoding="utf-8")
    return path


def _cli(argv: list[str], capsys) -> tuple[object, str, str]:
    try:
        code = cli.main(argv)
    except SystemExit as exc:
        code = exc.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _render(tmp_path: Path, capsys, data: Path) -> tuple[object, str, str, Path]:
    out = tmp_path / "explorer"
    code, stdout, stderr = _cli(["explore", "--data", str(data), "--out", str(out)], capsys)
    return code, stdout, stderr, out


def test_explore_cli_renders_populated_historical_comparison_from_public_export(tmp_path: Path, capsys) -> None:
    data = _write_export(tmp_path, _public_export())

    code, stdout, stderr, out = _render(tmp_path, capsys, data)

    assert code == 0, stderr
    index = out / "index.html"
    assert stdout.strip() == str(index)
    page = index.read_text(encoding="utf-8")
    assert "Historical results" in page
    for column in ("Metric", "AuraFace", "SFace", "InsightFace"):
        assert column in page
    assert "189" in page, "matched-face count copied from the public export must be on the first screen"
    assert "not recorded" in page, "clustering and unknown-rejection values are absent and must not show as zero"


def test_explore_cli_refuses_unsupported_export_version_with_exit_2(tmp_path: Path, capsys) -> None:
    export = _public_export()
    export["schema_version"] = 2
    data = _write_export(tmp_path, export)

    code, _stdout, stderr, out = _render(tmp_path, capsys, data)

    assert code == 2
    assert "unsupported export schema_version" in stderr
    assert not out.exists()


def test_explore_cli_never_overwrites_an_existing_output_directory(tmp_path: Path, capsys) -> None:
    data = _write_export(tmp_path, _public_export())
    out = tmp_path / "explorer"
    out.mkdir()
    keep = out / "index.html"
    keep.write_text("keep me", encoding="utf-8")

    code, _stdout, stderr = _cli(["explore", "--data", str(data), "--out", str(out)], capsys)

    assert code == 2
    assert "already exists" in stderr
    assert keep.read_text(encoding="utf-8") == "keep me"


def test_successful_explore_leaves_only_the_requested_directory(tmp_path: Path, capsys) -> None:
    data = _write_export(tmp_path, _public_export())

    code, _stdout, stderr, out = _render(tmp_path, capsys, data)

    assert code == 0, stderr
    assert {path.name for path in tmp_path.iterdir()} == {"explorer", EXPORT_NAME}
    assert [path.name for path in out.iterdir()] == ["index.html"]


def test_page_names_the_missing_auraface_result_and_the_intake_command(tmp_path: Path, capsys) -> None:
    data = _write_export(tmp_path, _public_export())

    code, _stdout, stderr, out = _render(tmp_path, capsys, data)

    assert code == 0, stderr
    page = (out / "index.html").read_text(encoding="utf-8")
    assert "No AuraFace result in the selected set" in page
    assert "evidence register" in page
    assert "Compatibility unknown" in page


def test_page_is_offline_and_leaks_no_local_path_or_browser_storage(tmp_path: Path, capsys) -> None:
    data = _write_export(tmp_path, _public_export())

    code, _stdout, stderr, out = _render(tmp_path, capsys, data)

    assert code == 0, stderr
    page = (out / "index.html").read_text(encoding="utf-8")
    assert "http://" not in page and "https://" not in page
    assert "localStorage" not in page and "sessionStorage" not in page
    assert str(tmp_path) not in page


def _raw_export(export: dict) -> str:
    return json.dumps(export, sort_keys=True)


def _with_extra_path(export: dict) -> str:
    export["reports"][0]["path"] = "/home/gate/private/fir/report.json"
    return _raw_export(export)


def _with_unknown_pipeline(export: dict) -> str:
    export["reports"][0]["pipeline"] = "mystery-pipeline"
    return _raw_export(export)


def _with_html_artifact_id(export: dict) -> str:
    export["reports"][0]["artifact_id"] = "<script>alert(1)</script>"
    return _raw_export(export)


def _with_boolean_count(export: dict) -> str:
    export["reports"][0]["counts"]["matched_faces"] = True
    return _raw_export(export)


def _with_nan_precision(export: dict) -> str:
    export["reports"][0]["detection"]["precision"] = math.nan
    return _raw_export(export)


def _with_duplicate_key(export: dict) -> str:
    return _raw_export(export).replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1', 1)


def _oversized(_export: dict) -> str:
    return " " * (2 * 1024 * 1024 + 1)


@pytest.mark.parametrize(
    "make_text",
    [
        _with_extra_path,
        _with_unknown_pipeline,
        _with_html_artifact_id,
        _with_boolean_count,
        _with_nan_precision,
        _with_duplicate_key,
        _oversized,
    ],
    ids=lambda func: func.__name__,
)
def test_explore_cli_refuses_invalid_exports_with_a_sanitized_message(tmp_path: Path, capsys, make_text) -> None:
    data = tmp_path / EXPORT_NAME
    data.write_text(make_text(_public_export()), encoding="utf-8")

    code, _stdout, stderr, out = _render(tmp_path, capsys, data)

    assert code == 2
    assert "error: invalid explorer export" in stderr
    assert "/home/gate" not in stderr
    assert "<script>" not in stderr
    assert not out.exists()


def _palette(block: str) -> dict[str, str]:
    return dict(re.findall(r"--([a-z-]+): (#[0-9a-f]{6});", block))


def _luminance(hex_color: str) -> float:
    channels = []
    for start in (1, 3, 5):
        value = int(hex_color[start : start + 2], 16) / 255
        channels.append(value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(first: str, second: str) -> float:
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_palette_meets_contrast_for_text_and_ui_in_light_and_dark(tmp_path: Path, capsys) -> None:
    data = _write_export(tmp_path, _public_export())
    code, _stdout, stderr, out = _render(tmp_path, capsys, data)
    assert code == 0, stderr
    css = (out / "index.html").read_text(encoding="utf-8").split("<style>", 1)[1].split("</style>", 1)[0]
    light = _palette(css.split("}", 1)[0])
    dark = _palette(css.split("prefers-color-scheme: dark) { :root {", 1)[1].split("}", 1)[0])
    for palette in (light, dark):
        for text_on in ("fg", "muted"):
            assert _contrast(palette[text_on], palette["bg"]) >= 4.5, text_on
        assert _contrast(palette["fg"], palette["sel"]) >= 4.5
        assert _contrast(palette["line"], palette["bg"]) >= 3.0
        assert _contrast(palette["accent"], palette["bg"]) >= 3.0


_BROWSER = r"""
const [htmlPath, shotDir, playwrightPath, chromePath] = process.argv.slice(1);
const path = require("path");
const { pathToFileURL } = require("url");
const { chromium } = require(playwrightPath);
(async () => {
  const browser = await chromium.launch({
    executablePath: chromePath,
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  const result = { widths: {}, requests: new Set(), console: [], interactions: {} };
  const url = pathToFileURL(path.resolve(htmlPath)).href;
  try {
    for (const width of [1440, 768, 390, 320]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      page.on("request", (req) => result.requests.add(req.url().split(":")[0] + ":"));
      page.on("console", (msg) => result.console.push(msg.type() + ": " + msg.text()));
      page.on("pageerror", (err) => result.console.push("pageerror: " + err.message));
      await page.goto(url);
      result.widths[width] = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      }));
      await page.screenshot({ path: path.join(shotDir, `full-${width}.png`), fullPage: true });
      await page.close();
    }
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await page.goto(url);
    const variants = await page.$$eval("#variant-sface option", (opts) => opts.map((o) => o.value));
    await page.selectOption("#variant-sface", variants[1]);
    result.interactions.variantUrl = page.url().split("?")[1] || "";
    await page.selectOption("#metric-focus", "grouping");
    result.interactions.groupingStatus = await page.textContent("#status");
    await page.selectOption("#metric-focus", "all");
    await page.fill("#term-search", "zzzz-no-term");
    result.interactions.emptyNoteShown = !(await page.$eval("#term-empty", (el) => el.hidden));
    await page.click("#clear-filters");
    result.interactions.searchAfterClear = await page.inputValue("#term-search");
    result.interactions.focusAfterClear = await page.evaluate(() => document.activeElement.id);
    await page.click("a[href='#term-faces-missed']");
    result.interactions.hash = await page.evaluate(() => window.location.hash);
    result.interactions.targetVisible = await page.$eval("#term-faces-missed", (el) => !el.hidden);
    await page.close();
  } finally {
    await browser.close();
  }
  result.requests = [...result.requests];
  process.stdout.write(JSON.stringify(result));
})().catch((err) => {
  process.stderr.write(String(err && err.stack ? err.stack : err));
  process.exit(1);
});
"""


@pytest.mark.skipif(
    os.environ.get("FIR_EXPLORER_BROWSER") != "1",
    reason="browser check runs on a normal VM: set FIR_EXPLORER_BROWSER=1 (node, playwright-core, chromium)",
)
def test_rendered_page_fits_four_widths_and_its_controls_work(tmp_path: Path, capsys) -> None:
    data = _write_export(tmp_path, _public_export())
    code, _stdout, stderr, out = _render(tmp_path, capsys, data)
    assert code == 0, stderr
    shots = tmp_path / "shots"
    shots.mkdir()
    playwright = os.environ.get("FIR_EXPLORER_PLAYWRIGHT", PLAYWRIGHT_CORE)
    chrome = os.environ.get("FIR_EXPLORER_CHROME", CHROMIUM)
    run = subprocess.run(
        ["node", "-e", _BROWSER, str(out / PAGE_NAME), str(shots), playwright, chrome],
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    for width, metrics in result["widths"].items():
        assert metrics["scrollWidth"] <= metrics["clientWidth"], f"page overflows horizontally at {width}"
    assert result["requests"] == ["file:"], "the page must not fetch anything but its own file"
    assert result["console"] == []
    assert sorted(path.name for path in shots.iterdir()) == [f"full-{w}.png" for w in (1440, 320, 390, 768)]
    interactions = result["interactions"]
    assert interactions["variantUrl"].startswith("variant-sface=golden150-fir-final-20260723")
    assert interactions["groupingStatus"].startswith("Showing 6 of 16 metric rows")
    assert interactions["emptyNoteShown"] is True
    assert interactions["searchAfterClear"] == ""
    assert interactions["focusAfterClear"] == "metric-focus"
    assert interactions["hash"] == "#term-faces-missed"
    assert interactions["targetVisible"] is True
