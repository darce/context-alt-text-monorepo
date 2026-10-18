"""Pure view and real-browser S5 checks; no fabricated outcome computation.

The typed wire fixtures are synthetic descriptive artifacts. Enriched row flags
below are explicit binding-interface inputs, not a classifier or statistical oracle.
Run browser checks with FIR_REPORT_PLAYWRIGHT pointing to playwright-core.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts.eval_harness import firbench_report as report

FIXTURES = Path(__file__).parent / "fixtures" / "firbench_interchange_v1"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _view_page(*, frame_state: str = "unsealed") -> str:
    scores = _load("scores-v1.json")
    frame = _load("frame-v1.json")
    clusters = _load("clusters-v1.json")
    # Deliberately hostile pseudonymous aliases exercise script and DOM boundaries.
    alias = '</script><img src="https://invalid.example/pixel" onerror="alert(1)">\u2028&'
    # Independent wire specimens supply chart values. The explicit binding rows
    # exercise view states only; they do not claim a coherent producer/scoring run.
    # GT aliases for path inspection are present, including a hostile pseudonym.
    face = frame["faces"][0]
    frame["faces"] = []
    for index, face_id in enumerate(["face-0001", "face-0002", "face-0003", "face-0004", alias, "face-fit"]):
        item = copy.deepcopy(face)
        item.update(face_id=face_id, identity_id=f"id-{index + 1:04d}")
        frame["faces"].append(item)
    if frame_state == "sealed":
        frame["sealed"] = True
    elif frame_state == "diagnostic":
        frame["admissibility"] = scores["admissibility"] = "diagnostic"
    elif frame_state == "no-points":
        scores["curves"] = []
    rows = []
    for index, (visible, outcome) in enumerate(
        [
            (True, report.FaceOutcome.rejected),
            (False, report.FaceOutcome.correct),
            (False, None),
        ]
    ):
        rows.append(
            {
                "image_id": "image-0001",
                "face_id": [alias, "face-0002", "face-fit"][index],
                "leg_key": scores["legs"][0]["leg_key"],
                "stage": "embedded",
                "top1_identity": ["id-0005", "id-0002", "id-0006"][index],
                "top1_score": [0.2, 0.9, 0.8][index],
                "fold": 0,
                "cell": "clear / unknown",
                "ref": "scores.json#/legs/0",
                "outcome": outcome,
                "outcome_available": outcome is not None,
                "outcome_reason": "fit_fold_not_scored" if outcome is None else None,
                "sampling_arm": "probability",
                "fold_role": "fit" if index == 2 else "test",
                "arm": "native",
                "identity_status": "named",
                "mated": True,
                "annotation_tier": None,
                "qualified": True,
                "qualification_reason": None,
                "is_failure": visible if outcome is not None else None,
                "default_visible": visible,
            }
        )
    sections = [(sid, "") for sid, _ in report._SECTIONS]
    contents = {
        "curves": report._curves_html(scores, unratified=False),
        "failures": report._failures_html(frame, rows, 2, include_crops=False),
        "clusters": report._chaining_html(0, clusters["legs"][0]),
        "pair-cells": report._cells_html(scores),
        "stages": report._stages_html(scores),
    }
    sections = [(sid, contents.get(sid, content)) for sid, content in sections]
    files = {"scores.json": scores, "clusters.json": clusters, "rows.jsonl": [{"a/b": {"~key": alias}}]}
    if frame_state != "missing":
        files["frame.json"] = frame
    return report._page(
        "synthetic view",
        sections,
        report._leg_table(scores),
        view_data={
            "files": files,
            "failure_rows": rows,
            "failure_pool": report._pool(frame, rows, include_crops=False),
            "background": 2,
        },
    )


def test_page_inline_data_is_inert_and_round_trips() -> None:
    page = _view_page()
    assert '<img src="https:' not in page
    payload = page.split('<script type="application/json" id="report-view-data">', 1)[1].split("</script>", 1)[0]
    assert "<" not in payload and "\u2028" not in payload
    assert json.loads(payload)["failure_rows"][0]["face_id"].startswith("</script>")


def test_controls_and_focus_targets_are_visible_in_static_html() -> None:
    page = _view_page()
    assert 'id="verdict" tabindex="-1"' in page
    assert "data-source=" in page
    assert 'id="failure-scope"' in page
    assert 'id="explore-tau"' in page
    assert 'id="source-inspector"' in page
    assert "data-inspect-pair=" in page
    assert ":focus-visible" in page


def test_legacy_rows_do_not_become_classified_failures() -> None:
    page = report._failures_html(None, [], 0, include_crops=False)
    assert "classification unavailable" in page
    assert "No failure row" not in page


_BROWSER_CHECK = r"""
const assert = require('node:assert/strict');
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.env.FIR_REPORT_PLAYWRIGHT);
(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.FIR_REPORT_CHROME,
    args: ['--no-sandbox', '--disable-dev-shm-usage']});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}, colorScheme: process.argv[2]});
    const requests = [], errors = [];
    page.on('request', r => { if (/^https?:/.test(r.url())) requests.push(r.url()); });
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    await page.goto(pathToFileURL(process.argv[1]).href);
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.className), 'skip');
    await page.keyboard.press('Enter');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'verdict');
    // Start again to check map tab order before jumping to its target.
    await page.reload(); await page.keyboard.press('Tab');
    for (const id of ['curves','pair-cells','stages','failures','clusters','compare','frames-power']) {
      await page.keyboard.press('Tab');
      assert.equal(await page.evaluate(() => document.activeElement.getAttribute('href')), '#' + id);
    }
    await page.keyboard.press('Enter');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'frames-power');
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    assert.equal(await page.evaluate(() => getComputedStyle(document.body).backgroundColor),
      process.argv[2] === 'dark' ? 'rgb(22, 23, 26)' : 'rgb(251, 251, 248)');
    assert(await page.locator('#verdict th').evaluateAll(cells => cells.every(c => c.getBoundingClientRect().right <= innerWidth)));
    assert((await page.locator('#verdict').innerText()).includes('0.410'));
    assert((await page.locator('#verdict').innerText()).includes('95%'));
    const panels = page.locator('#curves svg');
    assert.equal(await panels.count(), 2);
    for (const panel of await panels.all()) {
      assert(await panel.evaluate(el => el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().width <= 760));
      assert((await panel.getAttribute('aria-label')).includes('native curves'));
    }
    assert(await page.locator('#verdict tbody tr').first().evaluate(el => el.getBoundingClientRect().height < 200));
    const frozen = await page.locator('#curves table').allTextContents();
    const frozenVerdict = await page.locator('#verdict').innerText();
    // Both leg charts share one frozen at-τ evidence table. Check every leg's
    // recorded point and source, rather than treating table count as coverage.
    assert.equal(frozen.length, 1);
    assert.deepEqual(await page.locator('#curves table th').allTextContents(),
      ['Leg', 'Scope', 'τ', 'FPIR', 'FNIR', 'JSON path']);
    const frozenRows = page.locator('#curves table tbody tr');
    const expectedPoints = [
      ['sface__native__ab12cd__cv4.10.0__ort1.18.0', 0.41, '0.0', '0.5'],
      ['auraface__native__ef34ab__cv4.10.0__ort1.18.0', 0.67, '0.0', '0.2'],
    ];
    assert.equal(await frozenRows.count(), expectedPoints.length);
    for (const [index, [leg, tau, fpir, fnir]] of expectedPoints.entries()) {
      const cells = frozenRows.nth(index).locator('td');
      assert.equal(await cells.count(), 6);
      assert.equal(await cells.nth(0).innerText(), leg);
      assert.equal(await cells.nth(1).innerText(), 'probability · native');
      assert.equal(await cells.nth(2).innerText(), `τ = ${tau} (frozen on calibration folds)`);
      assert.equal(await cells.nth(3).innerText(), fpir);
      assert.equal(await cells.nth(4).innerText(), fnir);
      assert.equal(await cells.nth(5).locator('[data-source]').getAttribute('data-source'),
        `scores.json#/curves/${index}/points/0`);
      const panel = panels.nth(index);
      assert((await panel.getAttribute('aria-label')).startsWith(leg + ':'));
      assert.equal(await panel.locator('circle[data-point]').count(), 1);
      assert.equal(await panel.locator('circle[data-point]').getAttribute('data-point'), '0');
      assert.equal(Number(await panel.locator('circle[data-point]').getAttribute('data-fpir')), Number(fpir));
      assert((await panel.locator('circle title').textContent()).includes(`threshold ${tau}, FPIR ${fpir}, FNIR ${fnir}`));
      assert.equal(await panel.locator('polygon.tau').getAttribute('data-threshold'), String(tau));
    }
    const enter = page.locator('#explore-tau');
    await enter.focus();
    assert.notEqual(await enter.evaluate(el => getComputedStyle(el).outlineStyle), 'none');
    await page.keyboard.press('Enter');
    assert(await page.locator('#tau-explorer').isVisible());
    assert((await page.locator('#tau-explorer').innerText()).includes('Nothing is saved'));
    assert.equal(await page.locator('#explore-leg option').count(), expectedPoints.length);
    for (const [index, [leg, tau, fpir, fnir]] of expectedPoints.entries()) {
      await page.locator('#explore-leg').selectOption(String(index));
      assert.equal(await page.locator('#explore-point option').count(), 1);
      await page.locator('#explore-point').selectOption('0');
      assert.equal(await page.locator('#explore-readout').innerText(),
        `Recorded descriptive point · ${leg} · τ ${tau} · FNIR ${Number(fnir)} · FPIR ${Number(fpir)}. Support and intervals: frozen evidence above; no new inference.`);
      assert.deepEqual(await page.locator('#curves table').allTextContents(), frozen);
      assert.equal(await page.locator('#verdict').innerText(), frozenVerdict);
    }
    await page.keyboard.press('Escape');
    assert(!(await page.locator('#tau-explorer').isVisible()));
    assert.equal(await page.evaluate(() => document.activeElement.id), 'explore-tau');
    assert.equal(await page.locator('#explore-leg').inputValue(), '0');
    assert.deepEqual(await page.locator('#curves table').allTextContents(), frozen);
    assert.equal(await page.locator('#verdict').innerText(), frozenVerdict);
    await enter.press('Space'); await page.locator('#exit-explore').press('Enter');
    assert(!(await page.locator('#tau-explorer').isVisible()));
    assert.equal(await page.evaluate(() => document.activeElement.id), 'explore-tau');
    assert.deepEqual(await page.locator('#curves table').allTextContents(), frozen);
    assert.equal(await page.locator('#verdict').innerText(), frozenVerdict);
    // Default flags come from binding. All inventory reveals the fit-only named null.
    assert.equal(await page.locator('#failure-table tbody tr').count(), 1);
    await page.locator('#failure-scope').selectOption('all');
    assert.equal(await page.locator('#failure-table tbody tr').count(), 3);
    assert((await page.locator('#failure-table').innerText()).includes('fit_fold_not_scored'));
    await page.locator('#filter-fold_role').selectOption('test');
    await page.locator('#failure-sort').selectOption('face');
    assert.equal(await page.locator('#failure-table tbody tr').count(), 2);
    assert((await page.locator('#failure-counts').innerText()).includes('omitted 1 inventory rows'));
    assert.equal(await page.locator('img').count(), 0);
    // JSONPointer escapes and JSONL arrays resolve without loading a file.
    await page.evaluate(() => {
      const b = document.createElement('button'); b.id = 'pointer-probe';
      b.dataset.source = 'rows.jsonl#/0/a~1b/~0key'; b.textContent = 'Inspect escaped pointer'; document.body.append(b);
    });
    await page.locator('#pointer-probe').focus(); await page.keyboard.press('Enter');
    assert((await page.locator('#inspector-body').innerText()).includes('</script>'));
    assert.equal(await page.locator('#inspector-body img').count(), 0);
    await page.keyboard.press('Escape');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'pointer-probe');
    await page.locator('#pointer-probe').evaluate(el => { el.dataset.source = 'absent.json#/no-value'; });
    await page.keyboard.press('Enter');
    assert((await page.locator('#inspector-body').innerText()).includes('Source unavailable'));
    await page.keyboard.press('Escape');
    const source = page.locator('#failure-table [data-source]').first();
    await source.focus(); const beforeScroll = await page.evaluate(() => scrollY);
    await page.keyboard.press('Enter');
    assert((await page.locator('#inspector-body').innerText()).includes('operating_point'));
    await page.locator('#close-inspector').press('Enter');
    assert(await source.evaluate(el => el === document.activeElement));
    assert.equal(await page.evaluate(() => scrollY), beforeScroll);
    assert.equal(await page.locator('#failure-sort').inputValue(), 'face');
    assert.equal(await page.locator('#filter-fold_role').inputValue(), 'test');
    // Existing mapped handoff returns the original filters and originating button.
    const handoff = page.locator('#pair-cells button').filter({hasText: 'Open failures'}).first();
    await handoff.focus(); await page.keyboard.press('Enter');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'failures');
    await page.locator('#back-to-origin').press('Enter');
    assert(await handoff.evaluate(el => el === document.activeElement));
    assert.equal(await page.locator('#filter-fold_role').inputValue(), 'test');
    assert.equal(await page.locator('#failure-sort').inputValue(), 'face');
    const stage = page.locator('#stages button').filter({hasText: 'Open failures'}).first();
    await stage.focus(); await page.keyboard.press('Enter');
    await page.locator('#back-to-origin').press('Enter');
    assert(await stage.evaluate(el => el === document.activeElement));
    // Pair path uses recorded ordering and actual edges; nested source returns to path.
    const pair = page.locator('[data-inspect-pair]').first();
    await pair.focus(); await page.keyboard.press('Enter');
    const pathRows = page.locator('[data-zone="neighbour-table"] tbody tr');
    assert.equal(await pathRows.count(), 3);
    assert((await pathRows.nth(1).innerText()).includes('id-0002'));
    assert((await pathRows.nth(1).innerText()).includes('image-0001'));
    assert((await pathRows.nth(1).innerText()).includes('third identity'));
    assert((await page.locator('#inspector-body').innerText()).includes('0.85'));
    const pathText = await page.locator('#inspector-body').innerText();
    await page.locator('#inspector-body [data-source]').press('Enter');
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#inspector-body').innerText(), pathText);
    await page.keyboard.press('Escape');
    assert(await pair.evaluate(el => el === document.activeElement));
    await page.screenshot({path: process.argv[3], fullPage: true});
    // Separate pure view pages exercise each unavailable state without changing product data.
    for (const path of JSON.parse(process.argv[4])) {
      await page.goto(pathToFileURL(path).href);
      assert(await page.locator('#explore-tau').isDisabled());
      assert((await page.locator('#explore-status').innerText()).includes('unavailable'));
    }
    assert.deepEqual(requests, []); assert.deepEqual(errors, []);
    console.log(JSON.stringify({scheme: process.argv[2], httpRequests: requests, pageErrors: errors}));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
"""


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_actual_browser_interactions(tmp_path: Path, scheme: str) -> None:
    playwright = os.environ.get("FIR_REPORT_PLAYWRIGHT")
    assert playwright, "Browser gate requires FIR_REPORT_PLAYWRIGHT pointing to installed playwright-core"
    chrome = os.environ.get(
        "FIR_REPORT_CHROME", str(Path.home() / ".cache/ms-playwright/chromium-1248/chrome-linux-arm64/chrome")
    )
    page = tmp_path / "interaction.html"
    page.write_text(_view_page())
    variants = []
    for state in ("sealed", "diagnostic", "missing", "no-points"):
        variant = tmp_path / f"{state}.html"
        variant.write_text(_view_page(frame_state=state))
        variants.append(str(variant))
    result = subprocess.run(
        ["node", "-e", _BROWSER_CHECK, str(page), scheme, str(tmp_path / f"{scheme}.png"), json.dumps(variants)],
        env={**os.environ, "FIR_REPORT_CHROME": chrome},
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
