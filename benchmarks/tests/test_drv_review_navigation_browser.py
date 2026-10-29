"""Optional browser regression: uv run --no-project --with pytest --with playwright python -m pytest benchmarks/tests/test_drv_review_navigation_browser.py -q."""
from pathlib import Path
import json
import re

import pytest

playwright = pytest.importorskip('playwright.sync_api')
ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / 'benchmarks/reports/qwen-high-precision-20261025/review-decision-v3/index.html'


def test_lexicon_ab_and_historical_navigation_preserve_reviews(tmp_path):
    chrome = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(**({'executable_path': str(chrome)} if chrome.exists() else {}))
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(REPORT.as_uri(), wait_until='domcontentloaded', timeout=120000)
        page.get_by_text('How to evaluate each model', exact=True).click()
        guide = page.locator('#operator-evaluation-guide')
        assert guide.is_visible()
        for text in ['Inspect the image first', 'Factual support', 'Essential coverage', 'OCR', 'Purpose and effort', 'Historical comparisons']:
            assert text in guide.inner_text()
        assert guide.get_by_role('link', name='Evaluation method and research').get_attribute('href') == 'evaluation-method.html'
        with page.expect_popup() as popup:
            guide.get_by_role('link', name='Evaluation method and research').click()
        method = popup.value
        method.wait_for_load_state()
        assert method.title() == 'Image-description evaluation method'
        assert 'Canon v0.26.2' in method.locator('body').inner_text()
        method.close()

        page.get_by_role('button', name='Three-model blind review (A/B/C)', exact=True).click()
        assert page.locator('.description-table th:visible').count() == 86
        assert page.locator('.operator-pairs select:visible').count() == 0
        assert set(page.locator('.description-table th:visible').all_text_contents()) == {'Candidate A', 'Candidate B', 'Candidate C'}
        choices = page.locator('.operator-model-preferences select:visible')
        assert choices.count() == 29
        model_choice = page.locator('.operator-model-preferences').first.get_by_role('combobox', name='Preferred description (A/B/C)', exact=True)
        model_choice.select_option(label='Candidate C')
        with page.expect_download() as download:
            page.get_by_role('button', name='Export ranking JSON', exact=True).click()
        assert re.match(r'^description-ranking-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}[+-]\d{4}\.json$', download.value.suggested_filename)
        download.value.save_as(tmp_path / 'ranking.json')
        ranking = json.loads((tmp_path / 'ranking.json').read_text())
        assert ranking['schema'] == 'description-review-ranking/v1'
        ballot = ranking['annotations']['model_preferences']['ballots'][0]
        assert ballot['selected_key'] == ballot['candidate_keys'][2]
        assert len(ballot['candidate_keys']) == 3
        assert ranking['preference_ranking']['status'] == 'descriptive'
        assert any(m['wins'] == 1 for g in ranking['preference_ranking']['groups'] for m in g['models'])
        assert len(ranking['annotations']['pairs']) == 0
        with page.expect_download() as raw_download:
            page.get_by_role('button', name='Export JSON', exact=True).click()
        raw_download.value.save_as(tmp_path / 'annotations.json')
        raw = json.loads((tmp_path / 'annotations.json').read_text())
        assert raw['model_preferences']['ballots'] == ranking['annotations']['model_preferences']['ballots']
        page.reload(wait_until='domcontentloaded')
        page.get_by_role('button', name='Three-model blind review (A/B/C)', exact=True).click()
        assert page.locator('.operator-model-preferences').first.get_by_role('combobox', name='Preferred description (A/B/C)', exact=True).input_value() == ballot['selected_key']

        page.get_by_role('button', name='Lexicon A/B preference', exact=True).click()
        pair = page.locator('.operator-pairs select:visible').first
        assert pair.count() == 1
        pair.select_option('tie')
        saved = page.evaluate("JSON.parse(localStorage.getItem(Object.keys(localStorage).find(k=>k.startsWith('operator-review:'))))")
        assert saved['pairs'][0]['choice'] == 'tie'
        before = json.dumps(saved, sort_keys=True)
        page.get_by_role('button', name='Show historical reviews', exact=True).click()
        assert not page.locator('body').evaluate("e=>e.classList.contains('operator-blind')")
        historical = page.locator('.historical-cell:visible')
        assert historical.count() > 0
        assert historical.first.evaluate('e=>{const r=e.getBoundingClientRect();return r.right>0&&r.x<innerWidth&&r.bottom>0&&r.y<innerHeight;}')
        text = ' '.join(page.locator('.description-table th:visible').all_text_contents())
        for model in ['MiMo', 'JoyCaption', 'Florence', 'Qwen']:
            assert model in text
        after = page.evaluate("JSON.parse(localStorage.getItem(Object.keys(localStorage).find(k=>k.startsWith('operator-review:'))))")
        assert json.dumps(after, sort_keys=True) == before
        assert not errors
        browser.close()
