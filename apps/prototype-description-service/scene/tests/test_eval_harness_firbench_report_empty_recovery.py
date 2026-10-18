"""UX-05 browser regression through the real files-only report producer.

Only public synthetic interchange fixtures are read. No images, inference, DB,
classification substitutes, or patched UI/producer functions are used.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts.eval_harness import firbench_report as report

FIXTURES = Path(__file__).parent / "fixtures" / "firbench_interchange_v1"
PLAYWRIGHT = "/home/gate/firbench-1-context/browser-tools/node_modules/playwright-core"
CHROME = "/home/gate/.cache/ms-playwright/chromium-1248/chrome-linux-arm64/chrome"


def _render(tmp_path: Path, *, inventory: bool) -> Path:
    run = tmp_path / "repo/benchmarks/private/firbench/runs" / ("inventory" if inventory else "empty")
    run.mkdir(parents=True)
    scores = json.loads((FIXTURES / "scores-v1.json").read_text())
    scores.pop("face_outcomes", None)  # Real legacy producer path: classification unavailable.
    (run / "scores.json").write_text(json.dumps(scores))
    if inventory:
        (run / "frame.json").write_bytes((FIXTURES / "frame-v1.json").read_bytes())
    return report.render_report(run, out_dir=run / "report", include_crops=False)


_BROWSER = r"""
const assert = require('node:assert/strict');
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.env.FIR_REPORT_PLAYWRIGHT);
(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.FIR_REPORT_CHROME,
    args: ['--no-sandbox', '--disable-dev-shm-usage']});
  try {
    const width = Number(process.argv[3]);
    const page = await browser.newPage({viewport: {width, height: 900}, hasTouch: width <= 390});
    const errors = [], requests = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => { if (/^https?:/.test(request.url())) requests.push(request.url()); });
    await page.goto(pathToFileURL(process.argv[1]).href);
    const scope = page.locator('#failure-scope'), sort = page.locator('#failure-sort');
    const tableRows = page.locator('#failure-table tbody tr');
    const summary = page.locator('#failure-counts');
    assert.equal(await scope.inputValue(), 'default');
    assert.equal(await tableRows.count(), 0);
    assert.match(await summary.innerText(), /Inventory: 2 rows\./);
    assert.match(await summary.innerText(), /Selected: 0 rows, 0 faces, 0 images/);
    assert.equal(await summary.getAttribute('aria-live'), 'polite');
    const inspect = page.locator('#inspect-available-inventory');
    assert.equal(await inspect.count(), 1,
      'UX-05: empty primary scope with 2 inventory rows must offer Inspect available inventory');
    assert(await inspect.isVisible());
    assert.equal(await inspect.evaluate(el => el.tagName), 'BUTTON');
    assert.equal(await inspect.getAttribute('type'), 'button');
    assert.equal(await inspect.innerText(), 'Inspect available inventory');
    const clear = page.locator('#clear-changed-filters');
    assert.equal(await clear.innerText(), 'Clear changed filters');
    assert.equal(await clear.evaluate(el => el.tagName), 'BUTTON');
    assert.match(await page.locator('#reset-filters').innerText(), /Reset to primary scope/);
    assert.match(await page.locator('#failure-table').innerText(), /primary scope/i);
    assert.match(await page.locator('#failure-table').innerText(), /does not establish absence of failures/);
    // Inspect clears a conflicting filter, retains sort, and selects actual all-inventory scope.
    await page.locator('#filter-leg_key').selectOption({index: 1});
    await sort.selectOption('face');
    if (width <= 390) await inspect.tap();
    else { await inspect.focus(); await page.keyboard.press('Enter'); }
    assert.equal(await scope.inputValue(), 'all');
    assert.equal(await sort.inputValue(), 'face');
    assert(await page.locator('[data-filter]').evaluateAll(els => els.every(el => el.value === '*')));
    assert.equal(await tableRows.count(), 2);
    assert.match(await summary.innerText(), /Selected: 2 rows, 1 faces, 1 images/);
    assert.match(await summary.innerText(), /All GT inventory/);
    assert(await tableRows.evaluateAll(els => els.every(el => el.textContent.includes('unclassified'))));
    assert(!/all clear|no failures/i.test(await summary.innerText()));
    // Clear only changed predicates. In particular, never silently return to primary scope.
    await page.locator('#filter-leg_key').selectOption({index: 1});
    assert.equal(await tableRows.count(), 1);
    await clear.focus(); await page.keyboard.press('Space');
    assert.equal(await scope.inputValue(), 'all');
    assert.equal(await sort.inputValue(), 'face');
    assert.equal(await tableRows.count(), 2);
    assert(await clear.evaluate(el => el === document.activeElement));
    // A real source inspection preserves selected scope, changed filters, focus and scroll on Escape.
    await page.locator('#filter-leg_key').selectOption({index: 1});
    const source = page.locator('#failure-table [data-source]').first();
    await source.scrollIntoViewIfNeeded(); await source.focus();
    const before = await page.evaluate(() => ({x: scrollX, y: scrollY,
      values: [...document.querySelectorAll('#failure-filters select')].map(el => el.value)}));
    await page.keyboard.press('Enter');
    assert(await page.locator('#source-inspector').isVisible());
    assert(!(await page.locator('#inspector-body').innerText()).includes('Source unavailable'));
    await page.keyboard.press('Escape');
    assert(await source.evaluate(el => el === document.activeElement));
    assert.deepEqual(await page.evaluate(() => ({x: scrollX, y: scrollY,
      values: [...document.querySelectorAll('#failure-filters select')].map(el => el.value)})), before);
    await page.locator('#reset-filters').focus(); await page.keyboard.press('Enter');
    assert.equal(await scope.inputValue(), 'default');
    assert.equal(await sort.inputValue(), 'image');
    assert(await page.locator('[data-filter]').evaluateAll(els => els.every(el => el.value === '*')));
    assert.equal(await tableRows.count(), 0);
    assert(await inspect.isVisible());
    // A genuinely empty producer pool has a useful existing evidence path, no fake recovery.
    await page.goto(pathToFileURL(process.argv[2]).href);
    assert.equal(await tableRows.count(), 0);
    assert.match(await summary.innerText(), /Inventory: 0 rows\./);
    const empty = await page.locator('#failure-table').innerText();
    assert.match(empty, /No GT inventory rows were supplied/);
    assert.match(empty, /Inspect the supplied source evidence/);
    assert.match(empty, /does not establish absence of failures/);
    assert(!(await inspect.isVisible()));
    assert(!(await clear.isVisible()));
    const evidence = page.locator('#verdict [data-source]').first();
    await evidence.focus(); await page.keyboard.press('Enter');
    assert(await page.locator('#source-inspector').isVisible());
    assert(!(await page.locator('#inspector-body').innerText()).includes('Source unavailable'));
    await page.keyboard.press('Escape');
    assert(await evidence.evaluate(el => el === document.activeElement));
    assert.deepEqual(errors, []); assert.deepEqual(requests, []);
    console.log(JSON.stringify({width, inventoryRows: 2, selectedFaces: 1, selectedImages: 1,
      zeroPoolRows: 0, keyboard: true, touch: width <= 390, sourceEscapeRestored: true, errors, requests}));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
"""


@pytest.mark.parametrize("width", [1440, 768, 390, 320])
def test_empty_primary_scope_recovers_real_inventory(tmp_path: Path, width: int) -> None:
    populated = _render(tmp_path, inventory=True)
    empty = _render(tmp_path, inventory=False)
    result = subprocess.run(
        ["node", "-e", _BROWSER, str(populated), str(empty), str(width)],
        env={
            **os.environ,
            "FIR_REPORT_PLAYWRIGHT": PLAYWRIGHT,
            "FIR_REPORT_CHROME": CHROME,
        },
        capture_output=True,
        text=True,
        timeout=90,
    )
    print(result.stdout, end="")
    assert result.returncode == 0, result.stdout + result.stderr
