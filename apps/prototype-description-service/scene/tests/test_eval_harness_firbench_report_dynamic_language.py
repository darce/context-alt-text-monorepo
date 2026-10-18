"""UX-READER-01: real page/DOM language across initial and updated states.

Public wire specimens and explicit UI binding rows exercise presentation only;
they do not claim a scored run. No producer or browser function is mocked.
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


def _view_page(*, empty_primary: bool) -> str:
    scores = json.loads((FIXTURES / "scores-v1.json").read_text())
    keys = [leg["leg_key"] for leg in scores["legs"]]
    keys.append('unrecorded<em data-probe="inert">&__native__opaque')
    cell = scores["cells"][0]
    rows = [
        {
            "image_id": "synthetic-image<&>", "face_id": f"synthetic-face-{i}",
            "leg_key": key, "stage": "embedded", "outcome": "rejected",
            "outcome_available": True, "outcome_reason": None,
            "outcome_ref": f"scores.json#/face_outcomes/{i}", "ref": f"records.jsonl#/{i}",
            "top1_identity": "synthetic-identity<&>", "top1_score": 0.2, "fold": 0,
            "fold_role": "fit" if i == 2 else "test", "sampling_arm": "probability",
            "arm": "native", "cell": cell["query_occluder"] + " / " + cell["enrolled_occluder"],
            "annotation_tier": None, "identity_status": "named", "mated": True,
            "qualified": True, "is_failure": True, "default_visible": i < 2 and not empty_primary,
        }
        for i, key in enumerate(keys)
    ]
    scores["face_outcomes"] = [{"evidence": f"synthetic outcome {i}"} for i in range(len(rows))]
    sections = {
        "failures": report._failures_html(None, rows, 0, include_crops=False),
        "pair-cells": report._cells_html(scores),
    }
    return report._page(
        "Synthetic dynamic language",
        [(sid, sections.get(sid, "")) for sid, _ in report._SECTIONS],
        "",
        view_data={"failure_rows": rows, "files": {
            "scores.json": scores,
            "records.jsonl": [{"evidence": f"synthetic search {i}"} for i in range(len(rows))],
        }},
    )


_BROWSER = r"""
const assert = require('node:assert/strict');
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.env.FIR_REPORT_PLAYWRIGHT);
(async () => {
  const width = Number(process.argv[3]), scheme = process.argv[4];
  const browser = await chromium.launch({headless: true, executablePath: process.env.FIR_REPORT_CHROME,
    args: ['--no-sandbox', '--disable-dev-shm-usage']});
  try {
    const page = await browser.newPage({viewport: {width, height: 900}, colorScheme: scheme});
    const errors = [], requests = [], states = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('request', r => { if (/^https?:/.test(r.url())) requests.push(r.url()); });
    await page.goto(pathToFileURL(process.argv[1]).href);
    const table = page.locator('#failure-table'), scope = page.locator('#failure-scope');
    const sort = page.locator('#failure-sort'), role = page.locator('#filter-fold_role');
    const checkLanguage = async (state, count) => {
      assert.deepEqual(await table.locator('th').allTextContents(),
        ['Image identifier (image_id)', 'Face identifier (face_id)', 'Model', 'Search stage',
         'Outcome / reason', 'Top-ranked identity', 'top-1 score', 'Fold', 'Fold role', 'Cell', 'Label tier', 'Source'],
        'UX-READER-01: preferred failure-table headers must survive ' + state);
      const rows = table.locator('tbody tr');
      assert.equal(await rows.count(), count);
      const supplied = await page.locator('#report-view-data').evaluate(el => JSON.parse(el.textContent).failure_rows);
      for (const tr of await rows.all()) {
        const cells = tr.locator('td');
        const face = await cells.nth(1).innerText();
        const record = supplied.find(r => r.face_id === face);
        assert(record, 'DOM row must come from supplied view data');
        const model = cells.nth(2), parts = record.leg_key.split('__');
        const name = ({sface: 'SFace', auraface: 'AuraFace', insightface: 'InsightFace'})[parts[0]] || parts[0];
        assert.equal(await model.locator('strong').innerText(), name, 'readable recorded model is primary');
        assert(await model.locator('strong').isVisible());
        assert.equal(await model.locator('.note').innerText(), parts.slice(1, 3).join(' · '));
        const details = model.locator('details'), summary = details.locator('summary');
        assert.equal(await summary.innerText(), 'Leg contract');
        assert.equal(await details.evaluate(el => el.open), false);
        assert(!(await model.innerText()).includes(record.leg_key), 'full raw key must be secondary');
        await summary.focus(); await page.keyboard.press('Enter');
        assert.equal(await details.evaluate(el => el.open), true);
        assert((await details.innerText()).includes(record.leg_key));
        await page.keyboard.press('Enter');
        assert.equal(await details.evaluate(el => el.open), false);
        assert.equal(await cells.nth(0).innerText(), record.image_id);
        assert.equal(await cells.nth(5).innerText(), record.top1_identity);
      }
      assert.equal(await table.locator('[data-probe], img').count(), 0, 'row values must remain inert text');
      states.push(state);
    };
    const inspectBoth = async () => {
      const tr = table.locator('tbody tr').first(), sources = tr.locator('[data-source]');
      const face = await tr.locator('td').nth(1).innerText(), i = Number(face.split('-').at(-1));
      assert.deepEqual(await sources.evaluateAll(els => els.map(el => el.dataset.source)),
        [`scores.json#/face_outcomes/${i}`, `records.jsonl#/${i}`]);
      for (const [n, label] of ['Outcome source', 'Search source'].entries()) {
        const action = sources.nth(n);
        assert((await action.innerText()).includes(label));
        assert((await action.getAttribute('aria-label')).includes(label));
        await action.scrollIntoViewIfNeeded(); await action.focus();
        const snapshot = () => page.evaluate(() => ({x: scrollX, y: scrollY,
          values: [...document.querySelectorAll('#failure-filters select')].map(el => el.value)}));
        const before = await snapshot();
        await page.keyboard.press('Enter');
        assert(await page.locator('#source-inspector').isVisible());
        const body = await page.locator('#inspector-body').innerText();
        assert(body.includes(`synthetic ${n === 0 ? 'outcome' : 'search'} ${i}`));
        assert(!body.includes(`synthetic ${n === 0 ? 'search' : 'outcome'} ${i}`));
        if (n === 0) await page.keyboard.press('Escape');
        else await page.locator('#close-inspector').press('Enter');
        assert(await action.evaluate(el => el === document.activeElement));
        assert.deepEqual(await snapshot(), before);
      }
    };
    await checkLanguage('initial load', 2); await inspectBoth();
    await page.locator('#filter-leg_key').selectOption('sface__native__ab12cd__cv4.10.0__ort1.18.0');
    await sort.selectOption('face'); await role.selectOption('test');
    await checkLanguage('changed filter', 1); await inspectBoth();
    const handoff = page.locator('#pair-cells button').filter({hasText: 'Open failures'}).first();
    await handoff.scrollIntoViewIfNeeded(); await handoff.focus();
    const beforeBack = await page.evaluate(() => ({x: scrollX, y: scrollY}));
    await page.keyboard.press('Enter');
    await checkLanguage('cell handoff', 1); await inspectBoth();
    await page.locator('#back-to-origin').press('Enter');
    assert(await handoff.evaluate(el => el === document.activeElement));
    assert.deepEqual(await page.evaluate(() => ({x: scrollX, y: scrollY})), beforeBack);
    assert.equal(await sort.inputValue(), 'face'); assert.equal(await role.inputValue(), 'test');
    await checkLanguage('Back', 1);
    await role.selectOption('fit');
    await checkLanguage('empty changed filter', 0);
    await page.locator('#inspect-available-inventory').press('Enter');
    assert.equal(await scope.inputValue(), 'all'); assert.equal(await sort.inputValue(), 'face');
    assert(await page.locator('[data-filter]').evaluateAll(els => els.every(el => el.value === '*')));
    await checkLanguage('Inspect available inventory', 3); await inspectBoth();
    await page.locator('#reset-filters').press('Enter');
    await checkLanguage('reset', 2);
    await page.goto(pathToFileURL(process.argv[2]).href);
    await checkLanguage('empty primary load', 0);
    await page.locator('#inspect-available-inventory').press('Enter');
    assert.equal(await scope.inputValue(), 'all');
    await checkLanguage('primary recovery', 3); await inspectBoth();
    assert.deepEqual(errors, []); assert.deepEqual(requests, []);
    console.log(JSON.stringify({width, scheme, states, sources: true, keyboard: true,
      Escape: true, Back: true, focus: true, scroll: true, errors, requests}));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
"""


@pytest.mark.parametrize("width", [1440, 768, 390, 320])
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_dynamic_failure_language_survives_redraws(tmp_path: Path, width: int, scheme: str) -> None:
    pages = []
    for empty in (False, True):
        page = tmp_path / f"dynamic-language-{empty}.html"
        page.write_text(_view_page(empty_primary=empty))
        pages.append(str(page))
    result = subprocess.run(
        ["node", "-e", _BROWSER, *pages, str(width), scheme],
        env={**os.environ, "FIR_REPORT_PLAYWRIGHT": PLAYWRIGHT, "FIR_REPORT_CHROME": CHROME},
        capture_output=True, text=True, timeout=90,
    )
    print(result.stdout, end="")
    assert result.returncode == 0, result.stdout + result.stderr
