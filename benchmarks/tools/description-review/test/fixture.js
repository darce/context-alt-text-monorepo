'use strict';
// Shared read-only loader for the pinned v2 report fixture. Never cat index.v2.html (4.3 MB): read it through here.
const fs = require('fs');
const path = require('path');

const DIR = path.join(__dirname, '..');
const FIXTURE = path.join(DIR, 'fixtures', 'qwen-high-precision-20261025');

function block(html, id) {
  const open = '<script type="application/json" id="' + id + '">';
  const start = html.indexOf(open);
  if (start < 0) return null;
  const end = html.indexOf('</script>', start + open.length);
  if (end < 0) throw new Error('Unterminated JSON block ' + id);
  return JSON.parse(html.slice(start + open.length, end));
}

let cached = null;
function loadReport() {
  if (cached) return cached;
  const html = fs.readFileSync(path.join(FIXTURE, 'index.v2.html'), 'utf8');
  cached = {
    manifest: block(html, 'operator-review-manifest'),
    state: block(html, 'operator-review-initial-state'),
    contract: block(html, 'operator-review-contract'),
    previous: block(html, 'operator-review-previous-manifests'),
  };
  return cached;
}

function loadJSON(name) {
  const local = path.join(DIR, name);
  return JSON.parse(fs.readFileSync(fs.existsSync(local) ? local : path.join(FIXTURE, name), 'utf8'));
}

module.exports = {
  DIR,
  FIXTURE,
  block,
  loadReport,
  loadRule: () => loadJSON('decision-rule.json'),
  loadPerf: () => loadJSON('decision-performance.json'),
};
