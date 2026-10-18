"""UX-04: real report rendering of documented synthetic UI binding inputs.

These rows supply classification flags explicitly; they are not classifier
results or a benchmark run. No private corpus, images, DB, or inference is used.
"""

from __future__ import annotations

import json
import os
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

from scripts.eval_harness import firbench_report as report

OUTCOME = "scores.json#/face_outcomes/0"
SEARCH = "records.jsonl#/0"
FIXTURES = Path(__file__).parent / "fixtures" / "firbench_interchange_v1"


def _row(**updates: object) -> dict:
    row = {
        "image_id": "synthetic-image",
        "face_id": "synthetic-face",
        "leg_key": "synthetic__native__contract",
        "stage": "embedded",
        "outcome": "rejected",
        "outcome_available": True,
        "outcome_reason": None,
        "outcome_ref": OUTCOME,
        "ref": SEARCH,
        "top1_identity": "synthetic-identity",
        "top1_score": 0.2,
        "fold": 0,
        "fold_role": "test",
        "sampling_arm": "probability",
        "arm": "native",
        "cell": "clear / clear",
        "annotation_tier": None,
        "identity_status": "named",
        "mated": True,
        "qualified": True,
        "is_failure": True,
        "default_visible": True,
    }
    row.update(updates)
    return row


class _Actions(HTMLParser):
    def __init__(self, markup: str) -> None:
        super().__init__()
        self.actions: list[dict[str, str]] = []
        self.text: list[str] = []
        self.current: dict[str, str] | None = None
        self.feed(markup)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "button" and "data-source" in values:
            self.current = {"path": values["data-source"], "name": values.get("aria-label", ""), "text": ""}
            self.actions.append(self.current)

    def handle_endtag(self, tag: str) -> None:
        if tag == "button":
            self.current = None

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if self.current is not None:
            self.current["text"] += data


@pytest.mark.parametrize(
    ("updates", "expected", "missing"),
    [
        ({}, [("Outcome source", OUTCOME), ("Search source", SEARCH)], []),
        (
            {"outcome_ref": None, "outcome_available": False, "outcome": None, "outcome_reason": "legacy"},
            [("Search source", SEARCH)],
            ["Classification evidence unavailable"],
        ),
        ({"ref": None}, [("Outcome source", OUTCOME)], ["Search evidence unavailable"]),
        (
            {"ref": None, "outcome_ref": None, "outcome_available": False, "outcome": None},
            [],
            ["Classification evidence unavailable", "Search evidence unavailable"],
        ),
        (
            {"outcome_ref": 'scores.json#/face_outcomes/<synthetic>&"'},
            [("Outcome source", 'scores.json#/face_outcomes/<synthetic>&"'), ("Search source", SEARCH)],
            [],
        ),
    ],
    ids=["distinct-pointers", "legacy-search-only", "outcome-only", "no-sources", "escaped-pointer"],
)
def test_static_failure_sources(updates: dict, expected: list[tuple[str, str]], missing: list[str]) -> None:
    parsed = _Actions(report._ui_failure_table([_row(**updates)]))
    actual = [(action["text"].removeprefix("↗ "), action["path"]) for action in parsed.actions]
    assert actual == expected, "Source cell must distinguish classification evidence from search evidence"
    for action, (label, path) in zip(parsed.actions, expected, strict=True):
        assert label in action["name"] and path in action["name"]
    for message in missing:
        assert message in "".join(parsed.text)


def test_static_legacy_row_with_absent_pointer_keys() -> None:
    row = _row(outcome_available=False, outcome=None)
    del row["outcome_ref"], row["ref"]
    parsed = _Actions(report._ui_failure_table([row]))
    assert parsed.actions == []
    assert "Classification evidence unavailable" in "".join(parsed.text)
    assert "Search evidence unavailable" in "".join(parsed.text)


def _view_page() -> str:
    scores = json.loads((FIXTURES / "scores-v1.json").read_text())
    # Wire specimen supplies cell rendering only. Explicit UI rows below do not
    # assert a coherent scored run or actual FaceOutcome production.
    scores["face_outcomes"] = [{"outcome": "rejected", "evidence": "synthetic outcome evidence"}]
    cell = scores["cells"][0]
    common = {"leg_key": cell["leg_key"], "cell": cell["query_occluder"] + " / " + cell["enrolled_occluder"]}
    rows = [
        _row(**common),
        _row(
            **common,
            face_id="synthetic-legacy",
            outcome_ref=None,
            outcome=None,
            outcome_available=False,
            outcome_reason="legacy",
            default_visible=False,
            is_failure=None,
        ),
        _row(
            **common,
            face_id="synthetic-no-sources",
            outcome_ref=None,
            ref=None,
            outcome=None,
            outcome_available=False,
            outcome_reason="legacy",
            default_visible=False,
            is_failure=None,
        ),
        _row(**common, face_id="synthetic-outcome-only", ref=None, default_visible=False),
    ]
    sections = {
        "failures": report._failures_html(None, rows, 0, include_crops=False),
        "pair-cells": report._cells_html(scores),
    }
    return report._page(
        "Synthetic evidence wiring",
        [(sid, sections.get(sid, "")) for sid, _ in report._SECTIONS],
        "",
        view_data={
            "failure_rows": rows,
            "files": {"scores.json": scores, "records.jsonl": [{"evidence": "synthetic search evidence"}]},
        },
    )


_BROWSER_CHECK = r"""
const assert = require('node:assert/strict');
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.env.FIR_REPORT_PLAYWRIGHT);
(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.FIR_REPORT_CHROME,
    args: ['--no-sandbox', '--disable-dev-shm-usage']});
  try {
    const page = await browser.newPage({viewport: {width: Number(process.argv[2]), height: 900}});
    const errors = [], requests = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('request', r => { if (/^https?:/.test(r.url())) requests.push(r.url()); });
    await page.goto(pathToFileURL(process.argv[1]).href);
    const table = page.locator('#failure-table');
    const firstSources = table.locator('tbody tr').first().locator('td').last().locator('[data-source]');
    const expected = ['scores.json#/face_outcomes/0', 'records.jsonl#/0'];
    const checkSources = async () => {
      assert.deepEqual(await firstSources.evaluateAll(nodes => nodes.map(n => n.dataset.source)), expected,
        'drawFailures must keep distinct Outcome and Search evidence after regeneration');
      for (const [i, label] of ['Outcome source', 'Search source'].entries()) {
        assert((await firstSources.nth(i).innerText()).includes(label));
        assert((await firstSources.nth(i).getAttribute('aria-label')).includes(label));
      }
    };
    const inspectBoth = async () => {
      for (const [i, evidence] of ['synthetic outcome evidence', 'synthetic search evidence'].entries()) {
        const action = firstSources.nth(i);
        await action.focus();
        const before = await page.evaluate(() => ({x: scrollX, y: scrollY}));
        await page.keyboard.press('Enter');
        assert((await page.locator('#inspector-body').innerText()).includes(evidence));
        const wrong = i === 0 ? 'synthetic search evidence' : 'synthetic outcome evidence';
        assert(!(await page.locator('#inspector-body').innerText()).includes(wrong));
        if (i === 0) await page.keyboard.press('Escape');
        else await page.locator('#close-inspector').press('Enter');
        assert(await action.evaluate(el => el === document.activeElement));
        assert.deepEqual(await page.evaluate(() => ({x: scrollX, y: scrollY})), before);
      }
    };
    assert.equal(await table.locator('tbody tr').count(), 1);
    await checkSources(); await inspectBoth();
    await page.locator('#failure-sort').selectOption('face');
    await page.locator('#filter-fold_role').selectOption('test');
    await checkSources(); await inspectBoth();
    assert.equal(await page.locator('#failure-sort').inputValue(), 'face');
    assert.equal(await page.locator('#filter-fold_role').inputValue(), 'test');
    const handoff = page.locator('#pair-cells button').filter({hasText: 'Open failures'}).first();
    await handoff.focus(); await page.keyboard.press('Enter');
    await checkSources(); await inspectBoth();
    await page.locator('#back-to-origin').press('Enter');
    assert(await handoff.evaluate(el => el === document.activeElement));
    assert.equal(await page.locator('#failure-sort').inputValue(), 'face');
    assert.equal(await page.locator('#filter-fold_role').inputValue(), 'test');
    await page.locator('#failure-scope').selectOption('all');
    assert.equal(await table.locator('tbody tr').count(), 4);
    const byFace = id => table.locator('tbody tr').filter({has: page.getByRole('cell', {name: id, exact: true})});
    const legacy = byFace('synthetic-legacy');
    assert((await legacy.innerText()).includes('Classification evidence unavailable'));
    assert((await legacy.innerText()).includes('unclassified'));
    assert.deepEqual(await legacy.locator('[data-source]').evaluateAll(nodes => nodes.map(n => n.dataset.source)),
      ['records.jsonl#/0']);
    await legacy.locator('[data-source]').focus(); await page.keyboard.press('Enter');
    assert((await page.locator('#inspector-body').innerText()).includes('synthetic search evidence'));
    await page.keyboard.press('Escape');
    const absent = byFace('synthetic-no-sources');
    assert.equal(await absent.locator('[data-source]').count(), 0);
    assert((await absent.innerText()).includes('Classification evidence unavailable'));
    assert((await absent.innerText()).includes('Search evidence unavailable'));
    const outcomeOnly = byFace('synthetic-outcome-only');
    assert.deepEqual(await outcomeOnly.locator('[data-source]').evaluateAll(nodes => nodes.map(n => n.dataset.source)),
      ['scores.json#/face_outcomes/0']);
    assert((await outcomeOnly.innerText()).includes('Search evidence unavailable'));
    assert.deepEqual(errors, []); assert.deepEqual(requests, []);
    console.log(JSON.stringify({width: Number(process.argv[2]), sourceActions: expected,
      regeneration: true, inspectorReturn: true, backToOrigin: true, legacyAndAbsent: true,
      pageErrors: errors, httpRequests: requests}));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
"""


@pytest.mark.parametrize("width", [1440, 768, 390, 320])
def test_browser_failure_evidence_actions(tmp_path: Path, width: int) -> None:
    assert os.environ.get("FIR_REPORT_PLAYWRIGHT"), "Set FIR_REPORT_PLAYWRIGHT to installed playwright-core"
    assert os.environ.get("FIR_REPORT_CHROME"), "Set FIR_REPORT_CHROME to the explicit Chromium executable"
    page = tmp_path / "evidence-links.html"
    page.write_text(_view_page())
    result = subprocess.run(
        ["node", "-e", _BROWSER_CHECK, str(page), str(width)],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout.strip())
