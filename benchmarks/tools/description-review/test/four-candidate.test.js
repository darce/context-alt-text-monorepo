'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fixture = require('./fixture.js');
const review = require('../operator-review.js');
const metrics = require('../operator-metrics.js');
const cross = require('../operator-crossmodel.js');

// Inline extension, using the actual report's cell/review/performance contracts.
// No generated descriptions or human quality judgments are added to frozen data.
function panel(n = 4, imageCount = 20) {
  const source = fixture.loadReport(), rule = structuredClone(fixture.loadRule());
  rule.candidates = ['incumbent-q4km', ...rule.candidates].slice(0, n);
  rule.candidate_labels['incumbent-q4km'] = 'Served Q4 build';
  rule.dataset_id = 'inline-four-candidate';
  rule.manifest_sha256 = '4'.repeat(64);
  rule.images = imageCount;
  const manifest = {schema: source.manifest.schema, dataset_id: rule.dataset_id,
    manifest_sha256: rule.manifest_sha256, rubric_version: rule.rubric_version,
    images: [], cells: []};
  const perf = {schema: 'description-model-perf/v1', rows: []};
  const template = source.manifest.cells.find(c => Object.entries(rule.filter).every(([k,v]) => c[k] === v));
  for (let i = 0; i < imageCount; i++) {
    const image_id = 'inline-' + i, input_sha256 = crypto.createHash('sha256').update(image_id).digest('hex');
    manifest.images.push({image_id, input_sha256});
    for (const [index, id] of rule.candidates.entries()) {
      const output_sha256 = crypto.createHash('sha256').update(image_id + id).digest('hex');
      const cell = {...structuredClone(template), image_id, input_sha256, output_sha256,
        physical_model_id: id, model_key: id, model_label: rule.candidate_labels[id],
        generation_error: false, response_sha256: output_sha256,
        key: [input_sha256, id, rule.filter.arm, rule.filter.scope, output_sha256].join(':')};
      manifest.cells.push(cell);
      perf.rows.push({physical_model_id: id, image_id, E: false, W: false,
        profile_sha256: 'a'.repeat(64), summed_stage_seconds: index + 1, response_sha256: output_sha256});
    }
  }
  const state = review.empty(manifest, 'panel-1');
  state.reviewer_id = 'Synthetic contract test';
  for (const cell of manifest.cells) state.reviews[cell.key] = {
    ...review.fresh(cell), reviewed: true, severity: 'none', ocr: 'not_applicable'
  };
  return {manifest, state, rule, perf, contract: source.contract};
}
const decide = p => metrics.decide(p.manifest, p.state, p.perf, p.rule, p.contract);

test('panel labels and roster follow the rule, not manifest column order', () => {
  for (const n of [2, 3, 4, 5]) {
    const p = panel(4);
    p.rule.candidates = Array.from({length: n}, (_, i) => 'model-' + i);
    assert.deepEqual(review.panelCandidates(p.rule), p.rule.candidates.map((id, i) => ({id, label: 'Candidate ' + (i + 1)})));
  }
  const p = panel(), before = JSON.stringify(p);
  const orders = review.panelOrders(p.manifest, p.rule, p.state.blind_seed);
  assert.deepEqual(orders, cross.order(p.manifest, p.rule, p.state.blind_seed));
  assert.equal(JSON.stringify(p), before);
  p.manifest.cells[0].physical_model_id = 'not-in-rule';
  assert.throws(() => review.panelOrders(p.manifest, p.rule, p.state.blind_seed), /candidate/i);
});

test('four-candidate order varies positions, is deterministic, and preserves ballot provenance', () => {
  const p = panel(), byKey = new Map(p.manifest.cells.map(c => [c.key, c]));
  const seen = new Map();
  for (let seed = 0; seed < 80; seed++) {
    const order = review.panelOrders(p.manifest, p.rule, 'seed-' + seed);
    assert.deepEqual(review.panelOrders(p.manifest, p.rule, 'seed-' + seed), order);
    for (const [id, keys] of Object.entries(order)) {
      assert.equal(new Set(keys).size, 4);
      keys.forEach((key, index) => {
        const k = id + ':' + byKey.get(key).physical_model_id;
        if (!seen.has(k)) seen.set(k, new Set());
        seen.get(k).add(index);
      });
    }
  }
  for (const positions of seen.values()) assert.deepEqual([...positions].sort(), [0, 1, 2, 3]);
  const [id, keys] = Object.entries(review.panelOrders(p.manifest, p.rule, p.state.blind_seed))[0];
  cross.setPreference(p.manifest, p.rule, p.state, id, keys[3]);
  assert.deepEqual(p.state.model_preferences.ballots[0].candidate_keys, keys);
  assert.equal(p.state.model_preferences.ballots[0].selected_key, keys[3]);
  assert.deepEqual(review.importState(p.manifest, p.contract, review.empty(p.manifest, p.state.blind_seed),
    cross.rankingExport(p.manifest, p.rule, p.state)), p.state);
});

test('two immutable pins load independently and refuse unknown, stale, or mixed hashes', () => {
  const p = panel(), pin = {data: p.manifest.dataset_id, sha: p.manifest.manifest_sha256};
  const configured = metrics.withPins([pin]);
  const source = fixture.loadReport();
  const before = metrics.summarize(source.manifest, source.state);
  assert.deepEqual(configured.summarize(source.manifest, source.state), before);
  assert.equal(configured.summarize(p.manifest, p.state).arms.length, 4);
  pin.sha = '0'.repeat(64);
  assert.equal(configured.summarize(p.manifest, p.state).arms.length, 4);
  assert.ok(Object.isFrozen(configured.PINS));
  assert.ok(configured.PINS.every(Object.isFrozen));
  assert.throws(() => { configured.PINS[1].sha = pin.sha; }, TypeError);
  assert.throws(() => metrics.summarize(p.manifest, p.state), /mismatch/i);
  for (const target of ['manifest', 'state']) {
    const bad = structuredClone(p); bad[target].manifest_sha256 = 'f'.repeat(64);
    assert.throws(() => configured.summarize(bad.manifest, bad.state), /mismatch/i);
  }
  const mixed = structuredClone(p.state);
  mixed.dataset_id = source.state.dataset_id; mixed.manifest_sha256 = source.state.manifest_sha256;
  assert.throws(() => configured.summarize(p.manifest, mixed), /mismatch/i);
  assert.throws(() => metrics.withPins([{data: 'x', sha: 'not-a-sha'}]), /pin/i);
});

test('four-candidate decisions retain delta 0.10, six paired intervals, and both guardrails', () => {
  const p = panel(), q4 = p.rule.candidates[0];
  assert.equal(p.rule.delta, 0.10);
  const result = decide(p);
  assert.deepEqual(result.models.map(m => m.physical_model_id), p.rule.candidates);
  assert.equal(result.comparisons.length, 6);
  assert.ok(result.comparisons.every(c => c.n_images === 20 && c.accepted_delta_ci95.length === 2));
  assert.equal(result.quality.winner, null);
  assert.equal(result.performance.winner, q4);
  // One out of twenty lowers the paired lower bound to -0.15, outside delta.
  const c = p.manifest.cells.find(c => c.physical_model_id === q4);
  p.state.reviews[c.key].severity = 'minor'; p.state.reviews[c.key].issues = ['unsupported'];
  assert.notEqual(decide(p).performance.winner, q4);
  p.rule.delta = 0.20;
  assert.equal(decide(p).performance.winner, q4);
  p.rule.delta = 0.10;
  // Equal acceptance cannot hide the major-error upper guardrail.
  p.state.reviews[c.key].severity = 'major';
  for (const other of p.manifest.cells.filter(x => x.image_id === c.image_id && x.key !== c.key)) {
    p.state.reviews[other.key].severity = 'minor'; p.state.reviews[other.key].issues = ['unsupported'];
  }
  // Tied acceptance chooses the first rule candidate as reference; keep Q4 as the challenger.
  [p.rule.candidates[0], p.rule.candidates[1]] = [p.rule.candidates[1], p.rule.candidates[0]];
  assert.notEqual(decide(p).performance.winner, q4);
});

test('four-candidate pending, generation failure, missing cells and timing mismatches remain explicit', () => {
  const p = panel(), first = p.manifest.cells[0];
  p.state.reviews[first.key].ocr = 'not_assessed';
  const pending = decide(p);
  assert.equal(pending.status, 'insufficient_reviews');
  assert.deepEqual(pending.coverage.pending_keys, [first.key]);
  assert.equal(pending.comparisons, null);
  first.generation_error = true;
  assert.equal(decide(p).coverage.generation_errors, 1);
  assert.equal(decide(p).models[0].accepted, 19);
  p.manifest.cells.shift();
  const missing = decide(p);
  assert.deepEqual(missing.coverage.missing, [{physical_model_id: first.physical_model_id, image_id: first.image_id}]);
  assert.deepEqual(missing.models[0].accepted_rate_bounds, [0.95, 1]);
  p.perf.rows[1].response_sha256 = 'stale';
  assert.deepEqual(decide(p).models[1].timing_missing, [first.image_id]);
});

test('frozen three-candidate reviews keep all 192 records and the prior metrics digest', () => {
  const {manifest, state, contract} = fixture.loadReport(), rule = fixture.loadRule();
  const before = JSON.stringify(state);
  assert.equal(Object.keys(state.reviews).length, 192);
  assert.equal(review.validate(manifest, contract, structuredClone(state)).schema, state.schema);
  assert.deepEqual(review.panelOrders(manifest, rule, state.blind_seed), cross.order(manifest, rule, state.blind_seed));
  assert.equal(crypto.createHash('sha256').update(JSON.stringify(metrics.summarize(manifest, state))).digest('hex'),
    'da87af7e311a1173acd7ed56813a6cd42f2878603edc4e4cebdc5be9167d3012');
  assert.equal(JSON.stringify(state), before);
});
