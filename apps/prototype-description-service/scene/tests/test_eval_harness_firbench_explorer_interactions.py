"""UX-RENDER05: exercise the CLI's offline page in an actual browser.

The public synthetic wire below deliberately uses schema-supported null clustering.
It isolates navigation state; it is not evidence for non-null producer interop.
No task-state artifacts, database, private corpus, or network are needed.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts.eval_harness import firbench_cli as cli


PLAYWRIGHT_CORE = "/home/gate/firbench-1-context/browser-tools/node_modules/playwright-core"
CHROMIUM = "/home/gate/.cache/ms-playwright/chromium-1248/chrome-linux-arm64/chrome"


def _navigation_export() -> dict:
    """Self-contained public synthetic v1 input, with two selectable SFace reports."""
    sources, dedup, reports = [], [], []
    for index, pipeline, model_id, dimension in (
        (1, "sface", "ort-yunet-sface", 128),
        (2, "sface", "ort-yunet-sface", 128),
        (3, "insightface", "buffalo_l", 512),
    ):
        artifact_id, digest = f"synthetic-navigation-{index}", str(index) * 64
        sources.append({
            "artifact_id": artifact_id, "file_sha256": digest, "kind": "report-json",
            "manifest_hash_kind": None, "manifest_sha256": None,
            "qualification": "partial", "source_sha": None,
        })
        dedup.append({"file_sha256": digest, "artifact_ids": [artifact_id]})
        reports.append({
            "artifact_id": artifact_id, "file_sha256": digest, "pipeline": pipeline,
            "model_id": model_id, "embedding_dim": dimension,
            "counts": {"total": 2, "scored": 2, "failed": 0, "matched_faces": 1,
                       "named_matched": 1, "stranger_matched": 0},
            "detection": {"tp": 1, "fp": 1, "fn": 1, "precision": 0.5, "recall": 0.5},
            "unknown_rejection": None, "clustering": None, "identification": None,
            "slice_sections": [], "compatibility": "unknown", "qualification": "partial",
        })
    return {"schema": "firbench/comparison-explorer-export-v1", "schema_version": 1,
            "sources": sources, "dedup": dedup, "reports": reports}


_BROWSER = r"""
const [htmlPath, playwrightPath, chromePath] = process.argv.slice(1);
const assert = require("node:assert/strict");
const { pathToFileURL } = require("node:url");
const { chromium } = require(playwrightPath);
const url = pathToFileURL(htmlPath).href;
const callerSelector = "tr[data-metric] a[href='#term-faces-missed']";
const targetSelector = "#term-faces-missed";
const log = [];

async function settle(page) {
  await page.evaluate(() => new Promise(resolve =>
    requestAnimationFrame(() => requestAnimationFrame(resolve))));
}
async function state(page) {
  return page.evaluate(() => ({
    variant: document.getElementById("variant-sface").value,
    focus: document.getElementById("metric-focus").value,
    methods: document.getElementById("method-filter").value,
    q: document.getElementById("term-search").value,
    params: Object.fromEntries(new URLSearchParams(location.search)),
  }));
}
async function activate(locator, touch) {
  if (touch) { await locator.tap(); }
  else { await locator.focus(); await locator.press("Enter"); }
}
async function openHelp(page, touch) {
  const caller = page.locator(callerSelector);
  await caller.scrollIntoViewIfNeeded();
  await caller.focus();
  const scroll = await page.evaluate(() => ({ x: scrollX, y: scrollY }));
  assert.equal(await page.locator(targetSelector).isVisible(), false,
    "setup: the query must hide the row's glossary target");
  await activate(caller, touch);
  await page.waitForFunction(() => location.hash === "#term-faces-missed");
  await settle(page);
  assert.equal(await page.locator(targetSelector).isVisible(), true,
    "UX-RENDER05: following a row definition must reveal its hidden target");
  return scroll;
}
async function explicitReturn(page, touch) {
  const back = page.locator(targetSelector).getByRole("link", { name: /Back|Return/i });
  await activate(back, touch);
  await settle(page);
}
async function assertReturned(page, before, scroll, label) {
  const after = await state(page);
  assert.equal(after.q, before.q,
    `UX-RENDER05: ${label} must restore temporarily cleared glossary query`);
  assert.deepEqual(after, before, `UX-RENDER05: ${label} must preserve selections and URL state`);
  assert.equal(await page.locator(callerSelector).evaluate(el => document.activeElement === el), true,
    `UX-RENDER05: ${label} must focus the invoking row link`);
  const position = await page.evaluate(() => ({ x: scrollX, y: scrollY }));
  assert.ok(Math.abs(position.x - scroll.x) <= 2 && Math.abs(position.y - scroll.y) <= 2,
    `UX-RENDER05: ${label} must restore caller scroll: ${JSON.stringify({ scroll, position })}`);
}

(async () => {
  const browser = await chromium.launch({ executablePath: chromePath,
    args: ["--no-sandbox", "--disable-dev-shm-usage"] });
  try {
    for (const width of [1440, 768, 390, 320]) {
      for (const colorScheme of ["light", "dark"]) {
        const touch = width <= 390;
        const context = await browser.newContext({ viewport: { width, height: 900 },
          colorScheme, hasTouch: touch, isMobile: touch });
        const page = await context.newPage();
        const errors = [];
        page.on("pageerror", error => errors.push(error.message));
        await page.goto(url);
        const variants = await page.locator("#variant-sface option").evaluateAll(opts => opts.map(o => o.value));
        assert.ok(variants.length >= 2, "setup: real CLI page must offer a nondefault variant");
        await page.selectOption("#variant-sface", variants[1]);
        await page.selectOption("#metric-focus", "detection");
        await page.selectOption("#method-filter", "other");
        await page.fill("#term-search", "precision");
        const before = await state(page);
        assert.equal(before.params["variant-sface"], variants[1]);
        assert.equal(before.params.focus, "detection");
        assert.equal(before.params.methods, "other");
        assert.equal(before.params.q, "precision");

        let scroll = await openHelp(page, touch);
        await explicitReturn(page, touch);
        await assertReturned(page, before, scroll, "explicit return");

        scroll = await openHelp(page, touch);
        await page.goBack();
        await settle(page);
        await assertReturned(page, before, scroll, "browser Back");

        // Native hash navigation out of help also ends the temporary reveal.
        await openHelp(page, touch);
        await page.evaluate(() => { window.location.hash = "#results"; });
        await settle(page);
        assert.deepEqual(await state(page), before,
          "UX-RENDER05: native hash navigation must end temporary search reveal");

        // New choices made while consulting help take precedence over old state.
        await openHelp(page, touch);
        await page.selectOption("#variant-sface", variants[0]);
        await page.selectOption("#metric-focus", "strangers");
        await page.selectOption("#method-filter", "in-tree");
        await page.fill("#term-search", "missed");
        const changed = await state(page);
        await explicitReturn(page, touch);
        assert.deepEqual(await state(page), changed,
          "UX-RENDER05: returning must retain new manual choices made during help");
        // The original detection caller is now filtered out: use a visible fallback.
        assert.equal(await page.evaluate(() => {
          const el = document.activeElement;
          return el !== document.body && el.getClientRects().length > 0 && !el.closest("[hidden]");
        }), true, "UX-RENDER05: a now-hidden caller must use a visible focus fallback");

        await page.locator("#clear-filters").click();
        const cleared = await state(page);
        assert.equal(cleared.variant, variants[0], "Clear filters must retain the model variant");
        assert.equal(cleared.focus, "all");
        assert.equal(cleared.methods, "all");
        assert.equal(cleared.q, "");
        assert.equal(await page.evaluate(() => document.activeElement.id), "metric-focus");

        // Initial URL hash needs the same hidden-target reveal without a caller.
        await page.goto(url + "?variant-sface=" + encodeURIComponent(variants[1]) +
          "&focus=detection&methods=other&q=precision#term-faces-missed");
        await settle(page);
        assert.equal(await page.locator(targetSelector).isVisible(), true,
          "UX-RENDER05: direct entry must reveal a query-hidden definition");
        await explicitReturn(page, touch);
        assert.deepEqual(await state(page), before,
          "UX-RENDER05: direct-entry fallback must retain the URL's selections and query");
        assert.equal(await page.evaluate(() => {
          const el = document.activeElement;
          return el !== document.body && el.closest("#results") !== null && !el.closest("[hidden]");
        }), true, "UX-RENDER05: direct-entry fallback must focus a visible results control");

        // Native links remain usable when script is unavailable.
        const native = await browser.newContext({ javaScriptEnabled: false,
          viewport: { width, height: 900 }, colorScheme });
        const fallback = await native.newPage();
        await fallback.goto(url);
        await fallback.locator(callerSelector).click();
        assert.equal(new URL(fallback.url()).hash, "#term-faces-missed");
        await fallback.locator(targetSelector).getByRole("link", { name: /Back|Return/i }).click();
        assert.equal(new URL(fallback.url()).hash, "#results");
        await native.close();
        assert.deepEqual(errors, [], "help navigation must not raise browser errors");
        log.push({ width, colorScheme, input: touch ? "touch" : "keyboard", result: "PASS" });
        await context.close();
      }
    }
    process.stdout.write(JSON.stringify(log));
  } finally { await browser.close(); }
})().catch(error => { process.stderr.write(String(error.stack || error)); process.exit(1); });
"""


@pytest.mark.skipif(
    os.environ.get("FIR_EXPLORER_BROWSER") != "1",
    reason="set FIR_EXPLORER_BROWSER=1 on a VM with node, playwright-core and Chromium",
)
def test_glossary_returns_to_caller_without_losing_view_state(tmp_path: Path, capsys) -> None:
    data = tmp_path / "navigation-export.json"
    data.write_text(json.dumps(_navigation_export(), sort_keys=True), encoding="utf-8")
    out = tmp_path / "explorer"
    code = cli.main(["explore", "--data", str(data), "--out", str(out)])
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert captured.out.strip() == str(out / "index.html")
    run = subprocess.run(
        ["node", "-e", _BROWSER, str(out / "index.html"),
         os.environ.get("FIR_EXPLORER_PLAYWRIGHT", PLAYWRIGHT_CORE),
         os.environ.get("FIR_EXPLORER_CHROME", CHROMIUM)],
        capture_output=True, text=True, timeout=240,
    )
    assert run.returncode == 0, run.stderr
    observed = json.loads(run.stdout)
    assert [(item["width"], item["colorScheme"], item["input"], item["result"]) for item in observed] == [
        (width, color, "touch" if width <= 390 else "keyboard", "PASS")
        for width in (1440, 768, 390, 320) for color in ("light", "dark")
    ]
    print("Actual browser results: " + run.stdout)
