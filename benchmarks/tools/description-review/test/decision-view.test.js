'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {view, render, asciiSummary} = require('../operator-decision.js');

function result(status = 'decided') {
  const value = {
    schema: 'description-model-decision/v1', status,
    coverage: {
      decision_cells: 86, reviewed: 86, pending_keys: [],
      missing: [{physical_model_id: 'model-alpha', image_id: 'c081'}], generation_errors: 0
    },
    models: [
      {
        physical_model_id: 'model-alpha', label: 'Alpha quality model', images: 29, cells: 28,
        accepted: 28, accepted_rate: 28 / 29, accepted_rate_bounds: [28 / 29, 1],
        major_or_worse: 0, major_or_worse_rate: 0,
        latency: {profile_sha256: 'abcdef012345' + 'a'.repeat(52), n: 17, p50_seconds: 12.5,
          other_profiles: [{profile_sha256: 'fedcba987654' + 'b'.repeat(52), n: 11, p50_seconds: 8}]},
        timing_missing: [], seconds_per_accepted: 12.5 / (28 / 29)
      },
      {
        physical_model_id: 'model-beta', label: 'Beta fast model', images: 29, cells: 29,
        accepted: 27, accepted_rate: 27 / 29, accepted_rate_bounds: [27 / 29, 27 / 29],
        major_or_worse: 1, major_or_worse_rate: 1 / 29,
        latency: {profile_sha256: '012345abcdef' + 'c'.repeat(52), n: 29, p50_seconds: 2.25,
          other_profiles: []}, timing_missing: [], seconds_per_accepted: 2.25 / (27 / 29)
      },
      {
        physical_model_id: 'model-gamma', label: 'Gamma untimed model', images: 29, cells: 29,
        accepted: 0, accepted_rate: 0, accepted_rate_bounds: [0, 0],
        major_or_worse: 9, major_or_worse_rate: 9 / 29, latency: null,
        timing_missing: ['c001'], seconds_per_accepted: null
      }
    ],
    comparisons: [
      {a: 'model-alpha', b: 'model-beta', n_images: 29, accepted_delta: 1 / 29,
        accepted_delta_ci95: [0.001, 0.08], major_delta: -1 / 29, major_delta_ci95: [-0.08, 0]},
      {a: 'model-alpha', b: 'model-gamma', n_images: 29, accepted_delta: 28 / 29,
        accepted_delta_ci95: [0.8, 1], major_delta: -9 / 29, major_delta_ci95: [-0.5, -0.1]},
      {a: 'model-beta', b: 'model-gamma', n_images: 29, accepted_delta: 27 / 29,
        accepted_delta_ci95: [0.7, 1], major_delta: -8 / 29, major_delta_ci95: [-0.4, -0.1]}
    ],
    quality: {winner: 'model-alpha', verdict: 'winner', reason: 'Quality interval clears both rivals.'},
    performance: {winner: 'model-beta', leader: 'model-alpha', verdict: 'winner',
      reason: 'Fastest eligible model under both guardrails.'},
    power: [
      {a: 'model-alpha', b: 'model-beta', ci_half_width: 0.0395, images_needed: 5},
      {a: 'model-alpha', b: 'model-gamma', ci_half_width: 0.1, images_needed: 29},
      {a: 'model-beta', b: 'model-gamma', ci_half_width: 0.15, images_needed: 66}
    ],
    notes: ['model-alpha has a missing cell; Alpha quality model has multiple timing profiles.']
  };
  if (status === 'insufficient_reviews') {
    value.coverage.reviewed = 84;
    value.coverage.pending_keys = ['model-beta:pending', 'model-gamma:pending'];
    for (const model of value.models) {
      for (const key of ['accepted', 'accepted_rate', 'accepted_rate_bounds',
        'major_or_worse', 'major_or_worse_rate', 'seconds_per_accepted']) model[key] = null;
    }
    for (const key of ['comparisons', 'quality', 'performance', 'power']) value[key] = null;
  } else if (status === 'undecided') {
    value.quality = {winner: null, verdict: 'undecided', reason: 'Quality intervals overlap.'};
  } else if (status === 'coverage_sensitive') {
    value.quality.reason = 'Quality changes under optimistic missing-cell imputation.';
    value.performance.reason = 'Performance changes under optimistic missing-cell imputation.';
  }
  return value;
}

class Element {
  constructor(ownerDocument, tagName) {
    this.ownerDocument = ownerDocument;
    this.tagName = tagName;
    this.children = [];
    this.attributes = {};
    this.listeners = {};
    this._text = '';
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(' '); }
  appendChild(child) { this.children.push(child); return child; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  click() { if (this.listeners.click) this.listeners.click(); }
}

function host() {
  const document = {createElement: tag => new Element(document, tag)};
  return new Element(document, 'details');
}
function elements(node) { return [node, ...node.children.flatMap(elements)]; }
function serializedDOM(node) {
  return JSON.stringify({tag: node.tagName, attributes: node.attributes, text: node._text,
    children: node.children.map(child => JSON.parse(serializedDOM(child)))});
}
function noDisclosure(text, data) {
  for (const model of data.models) {
    assert.ok(!text.includes(model.physical_model_id), text);
    assert.ok(!text.includes(model.label), text);
    if (model.latency) assert.ok(!text.includes(model.latency.profile_sha256.slice(0, 12)), text);
  }
  assert.doesNotMatch(text, /winner|accepted|rate|latency|p50|profile|ci95|confidence|interval|96\.55|12\.500000/i);
}
function stubMetrics(t, data, opts = {}) {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'OperatorMetrics');
  const calls = [];
  globalThis.OperatorMetrics = {decide(...args) { calls.push(args); return data; }};
  t.after(() => {
    if (previous) Object.defineProperty(globalThis, 'OperatorMetrics', previous);
    else delete globalThis.OperatorMetrics;
  });
  const options = {manifest: {}, state: {}, perf: {}, rule: {}, contract: {}, ...opts};
  return {options, calls};
}

for (const status of ['insufficient_reviews', 'decided', 'undecided', 'coverage_sensitive']) {
  test(`sealed ${status} view and DOM expose only coverage`, t => {
    const data = result(status);
    const {options} = stubMetrics(t, data, {unsealed: false});
    const panel = view(data, false);
    assert.deepEqual(Object.keys(panel).sort(), ['coverage_line', 'headline', 'notes', 'rows', 'sealed', 'status']);
    assert.equal(panel.sealed, true);
    assert.deepEqual(panel.rows, []);
    assert.deepEqual(panel.notes, []);
    assert.match(panel.headline, status === 'insufficient_reviews' ? /2.*cells.*remain/i : /0.*cells.*remain/i);
    assert.match(panel.coverage_line, status === 'insufficient_reviews' ? /84\s*\/\s*86/ : /86\s*\/\s*86/);
    noDisclosure(JSON.stringify(panel), data);
    const target = host();
    render(target, options);
    noDisclosure(serializedDOM(target), data);
    assert.equal(elements(target).filter(el => el.tagName === 'button').length,
      status === 'insufficient_reviews' ? 0 : 1);
  });
}

test('insufficient reviews stay sealed even when asked to unseal', t => {
  const data = result('insufficient_reviews');
  const {options} = stubMetrics(t, data, {unsealed: true});
  assert.equal(view(data, true).sealed, true);
  noDisclosure(JSON.stringify(view(data, true)), data);
  const target = host();
  render(target, options);
  noDisclosure(serializedDOM(target), data);
  assert.equal(elements(target).filter(el => el.tagName === 'button').length, 0);
});

test('sealed completed views conceal which verdict was reached', () => {
  assert.deepEqual(view(result('decided'), false), view(result('undecided'), false));
  assert.deepEqual(view(result('decided'), false), view(result('coverage_sensitive'), false));
});

test('unsealed decided view exposes both winners and bounded, profile-specific metrics', () => {
  const panel = view(result(), true);
  assert.equal(panel.sealed, false);
  assert.equal(panel.status, 'decided');
  assert.equal(panel.rows.length, 3);
  const text = JSON.stringify(panel);
  assert.match(text, /Quality winner[^]*Alpha quality model/);
  assert.match(text, /Performance winner[^]*Beta fast model/);
  for (const model of result().models) {
    assert.ok(text.includes(model.label));
    assert.ok(text.includes(model.physical_model_id));
  }
  assert.match(text, /96\.55%[^]*96\.55%[^]*100\.00%/);
  assert.match(text, /p50 12\.500000 s/);
  assert.match(text, /profile abcdef012345/);
  assert.match(text, /n=17/);
  assert.match(text, /12\.946429 s/);
  assert.ok(!text.includes('abcdef012345' + 'a'.repeat(52)));
});

for (const status of ['decided', 'undecided', 'coverage_sensitive']) {
  test(`unsealed ${status} DOM has reasons, icon, text label and one status region`, t => {
    const data = result(status);
    const {options, calls} = stubMetrics(t, data, {unsealed: true});
    const target = host();
    render(target, options);
    assert.deepEqual(calls, [[options.manifest, options.state, options.perf, options.rule, options.contract]]);
    const all = elements(target);
    const statuses = all.filter(el => el.attributes.role === 'status');
    assert.equal(statuses.length, 1);
    assert.equal(statuses[0].attributes['aria-live'], 'polite');
    assert.match(statuses[0].textContent, /[✓?!⚠🔒]/u);
    assert.match(statuses[0].textContent, status === 'coverage_sensitive' ? /coverage.sensitive/i : new RegExp(status, 'i'));
    assert.ok(target.textContent.includes(data.quality.reason));
    assert.ok(target.textContent.includes(data.performance.reason));
    assert.ok(target.textContent.includes('Alpha quality model'));
    assert.ok(target.textContent.includes('12.500000 s'));
    assert.ok(target.textContent.includes('abcdef012345'));
    assert.ok(target.textContent.includes('n=17'));
    assert.ok(target.textContent.includes('12.946429 s'));
    assert.equal(all.filter(el => el.tagName === 'button').length, 0);
    assert.equal(all.filter(el => el.tagName === 'table').length, 1);
    assert.ok(all.filter(el => el.tagName === 'th').every(el => el.attributes.scope === 'col'));
  });
}

test('Unseal decision calls the callback without revealing data until rerendered', t => {
  let unseals = 0;
  const data = result();
  const {options} = stubMetrics(t, data, {unsealed: false, onUnseal() { unseals++; }});
  const target = host();
  render(target, options);
  const button = elements(target).find(el => el.tagName === 'button');
  assert.equal(button.textContent, 'Unseal decision');
  assert.equal(button.attributes.type, 'button');
  button.click();
  assert.equal(unseals, 1);
  noDisclosure(serializedDOM(target), data);
  options.unsealed = true;
  render(target, options);
  assert.ok(target.textContent.includes('Alpha quality model'));
  options.unsealed = false;
  render(target, options);
  noDisclosure(serializedDOM(target), data);
  assert.equal(elements(target).filter(el => el.attributes.role === 'status').length, 1);
});

test('generation errors do not block Unseal after all reviewable cells are complete', t => {
  const data = result();
  data.coverage.generation_errors = 1;
  data.coverage.reviewed = 85;
  const {options} = stubMetrics(t, data, {unsealed: false, onUnseal() {}});
  const target = host();
  render(target, options);
  assert.equal(elements(target).filter(el => el.tagName === 'button').length, 1);
  assert.match(target.textContent, /generation errors: 1/i);
});

test('null latency, zero rates and no performance winner render as explicit unavailable values', t => {
  const data = result('undecided');
  data.performance = {winner: null, leader: 'model-alpha', verdict: 'none', reason: 'No joined timing rows.'};
  const {options} = stubMetrics(t, data, {unsealed: true});
  const target = host();
  render(target, options);
  assert.match(target.textContent, /Performance[^]*none/i);
  assert.match(target.textContent, /No joined timing rows/);
  assert.match(target.textContent, /0\.00%/);
  assert.match(target.textContent, /N\/A/);
  assert.doesNotMatch(target.textContent, /NaN|Infinity|undefined|\bnull\b/);
});

test('model labels and notes are text, including HTML-like content', t => {
  const data = result();
  data.models[0].label = '<script>model label</script>';
  data.notes = ['<img src=x onerror=alert(1)>'];
  const {options} = stubMetrics(t, data, {unsealed: true});
  const target = host();
  render(target, options);
  assert.ok(target.textContent.includes(data.models[0].label));
  assert.ok(target.textContent.includes(data.notes[0]));
  assert.equal(elements(target).filter(el => ['script', 'img'].includes(el.tagName)).length, 0);
});

test('view and asciiSummary are deterministic and do not mutate the decision result', () => {
  function freeze(value) {
    if (value && typeof value === 'object') {
      Object.values(value).forEach(freeze);
      Object.freeze(value);
    }
    return value;
  }
  for (const status of ['insufficient_reviews', 'decided', 'undecided', 'coverage_sensitive']) {
    const data = freeze(result(status));
    const before = JSON.stringify(data);
    assert.deepEqual(view(data, true), view(data, true));
    assert.equal(asciiSummary(data), asciiSummary(structuredClone(data)));
    assert.equal(JSON.stringify(data), before);
  }
});

test('asciiSummary lists every model, metrics, verdicts, comparisons and power in a plain-text table', () => {
  const text = asciiSummary(result());
  const lines = text.split('\n');
  assert.match(text, /Accepted rate.*bounds/i);
  assert.match(text, /Major.*rate/i);
  assert.match(text, /Seconds per accepted/i);
  const modelLines = result().models.map(model => {
    const line = lines.find(line => line.includes(model.label));
    assert.ok(line, model.label);
    assert.ok(line.includes(model.physical_model_id));
    assert.ok(line.includes('|'));
    return line;
  });
  assert.match(modelLines[0], /96\.55%.*\[96\.55%, 100\.00%\].*0\.00%.*p50 12\.500000 s.*abcdef012345.*n=17.*12\.946429 s/);
  assert.match(modelLines[1], /93\.10%.*3\.45%.*p50 2\.250000 s.*012345abcdef.*n=29.*2\.416667 s/);
  assert.match(modelLines[2], /0\.00%.*31\.03%.*N\/A.*N\/A/);
  assert.match(text, /Quality winner: Alpha quality model \(model-alpha\)/);
  assert.match(text, /Performance winner: Beta fast model \(model-beta\)/);
  assert.match(text, /Quality interval clears both rivals/);
  assert.match(text, /Fastest eligible model under both guardrails/);
  assert.match(text, /CI95/);
  assert.match(text, /Power/);
  for (const power of result().power) {
    assert.ok(lines.some(line => line.includes(power.a) && line.includes(power.b) &&
      line.includes(String(power.images_needed))));
  }
  assert.match(text, /0\.039500/);
  assert.doesNotMatch(text, /\u001b|NaN|Infinity|undefined/);
});

test('insufficient-review asciiSummary handles null quality fields but retains every model and timing', () => {
  const data = result('insufficient_reviews');
  const text = asciiSummary(data);
  for (const model of data.models) assert.ok(text.includes(model.physical_model_id));
  assert.match(text, /Quality[^\n]*pending/i);
  assert.match(text, /Performance[^\n]*pending/i);
  assert.match(text, /p50 12\.500000 s/);
  assert.doesNotMatch(text, /NaN|Infinity|undefined|\bnull\b/);
});
