'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('crypto');
const fixture = require('./fixture.js');
const metrics = require('../operator-metrics.js');
const { manifest, state, contract } = fixture.loadReport();
const rule = fixture.loadRule();
const perf = fixture.loadPerf();
const [incumbent, small, large] = rule.candidates;
const clone = x => JSON.parse(JSON.stringify(x));
const cells = manifest.cells.filter(c => Object.entries(rule.filter).every(([k, v]) => c[k] === v));
const imageIds = manifest.images.map(image => image.image_id);
const review = (cell, fields = {}) => ({
  output_sha256: cell.output_sha256, image_id: cell.image_id, input_sha256: cell.input_sha256,
  reviewed: true, severity: 'none', ocr: 'not_applicable', issues: [], ...fields,
});
function complete(annotate = () => ({})) {
  const result = clone(state);
  result.reviewer_id = 'decision test reviewer';
  for (const cell of cells) result.reviews[cell.key] = review(cell, annotate(cell));
  return result;
}
const rejected = { severity: 'major', issues: ['unsupported'] };
const minorRejection = { severity: 'minor', issues: ['unsupported'] };
const decide = (reviews, timings = perf, m = manifest, r = rule, c = contract) =>
  metrics.decide(m, reviews, timings, r, c);
function fasterLarge() {
  const timings = clone(perf);
  for (const row of timings.rows) if (row.physical_model_id === large) row.summed_stage_seconds = 1;
  return timings;
}
function model(result, id) { return result.models.find(m => m.physical_model_id === id); }

test('summarize initial-state bytes match the hash recorded before implementation', () => {
  const hash = crypto.createHash('sha256').update(JSON.stringify(metrics.summarize(manifest, state))).digest('hex');
  assert.equal(hash, 'da87af7e311a1173acd7ed56813a6cd42f2878603edc4e4cebdc5be9167d3012');
});

test('initial decision is sealed with pinned coverage and separate latency profiles', () => {
  assert.deepEqual(metrics.decisionCells(manifest, rule), cells);
  const result = decide(state);
  assert.equal(result.schema, 'description-model-decision/v1');
  assert.equal(result.status, 'insufficient_reviews');
  assert.deepEqual(result.coverage, {
    decision_cells: 86, reviewed: 0, pending_keys: cells.map(c => c.key),
    missing: [{ physical_model_id: incumbent, image_id: 'c081' }], generation_errors: 0,
  });
  assert.deepEqual(result.models.map(m => m.physical_model_id), rule.candidates);
  const expected = [
    ['144645d2c679', 17, 145.029086, [['bfd8dbe5eefe', 11, 90.825025]]],
    ['147571bcacad', 29, 14.781613, []],
    ['cc8a63650812', 21, 295.545954, [['fc3d3cc68863', 5, 185.232701]]],
  ];
  for (const [i, m] of result.models.entries()) {
    assert.equal(m.label, rule.candidate_labels[m.physical_model_id]);
    assert.equal(m.images, 29);
    assert.equal(m.cells, i === 0 ? 28 : 29);
    const [profile, n, p50, other] = expected[i];
    assert.equal(m.latency.profile_sha256.slice(0, 12), profile);
    assert.equal(m.latency.n, n);
    assert.ok(Math.abs(m.latency.p50_seconds - p50) < 1e-9);
    assert.deepEqual(m.latency.other_profiles.map(p => [p.profile_sha256.slice(0, 12), p.n]), other.map(p => p.slice(0, 2)));
    for (const [j, profile] of m.latency.other_profiles.entries()) {
      assert.ok(Math.abs(profile.p50_seconds - other[j][2]) < 1e-9);
    }
    for (const key of ['accepted', 'accepted_rate', 'accepted_rate_bounds', 'major_or_worse',
      'major_or_worse_rate', 'seconds_per_accepted']) assert.equal(m[key], null, key);
  }
  assert.equal(result.models.reduce((n, m) => n + m.latency.n + m.latency.other_profiles.reduce((s, p) => s + p.n, 0), 0), 83);
  assert.deepEqual(model(result, incumbent).timing_missing, []);
  assert.deepEqual(model(result, small).timing_missing, []);
  assert.deepEqual([...model(result, large).timing_missing].sort(), ['c009', 'c053', 'c081']);
  assert.ok(result.notes.some(n => n.includes('c009')));
  for (const key of ['comparisons', 'quality', 'performance', 'power']) assert.equal(result[key], null, key);
});

test('complete reviews select a clear quality winner and price accepted output', () => {
  const result = decide(complete(c => c.physical_model_id === small ? {} : rejected));
  assert.equal(result.status, 'decided');
  assert.equal(result.coverage.reviewed, 86);
  assert.deepEqual(result.coverage.pending_keys, []);
  assert.equal(result.quality.winner, small);
  assert.equal(result.quality.verdict, 'winner');
  assert.equal(result.performance.winner, small);
  assert.equal(result.performance.leader, small);
  assert.equal(result.performance.verdict, 'winner');
  assert.equal(model(result, small).accepted, 29);
  assert.equal(model(result, small).accepted_rate, 1);
  assert.equal(model(result, small).seconds_per_accepted, 14.781613);
  assert.equal(model(result, incumbent).seconds_per_accepted, null);
  assert.deepEqual(model(result, incumbent).accepted_rate_bounds, [0, 1 / 29]);
  assert.equal(model(result, incumbent).major_or_worse, 29);
  assert.equal(model(result, incumbent).major_or_worse_rate, 1);
});

test('identical observed models leave quality undecided', () => {
  const result = decide(complete());
  assert.equal(result.status, 'undecided');
  assert.equal(result.quality.winner, null);
  assert.equal(result.quality.verdict, 'undecided');
  assert.equal(result.performance.winner, small);
  assert.deepEqual(model(result, incumbent).accepted_rate_bounds, [28 / 29, 1]);
  assert.equal(model(result, incumbent).accepted, 28);
});

test('a faster model within the paired acceptance margin wins performance', () => {
  const result = decide(complete(c => c.physical_model_id === incumbent ? rejected : {}), fasterLarge());
  assert.equal(result.status, 'undecided');
  assert.equal(result.performance.leader, small);
  assert.equal(result.performance.winner, large);
  assert.equal(model(result, large).seconds_per_accepted, 1);
});

test('major-delta upper bound at least delta excludes an otherwise equivalent fast model', () => {
  const badImage = 'c002';
  const reviews = complete(c => c.physical_model_id === incumbent ? rejected :
    c.image_id !== badImage ? {} : c.physical_model_id === large ? rejected : minorRejection);
  const result = decide(reviews, fasterLarge());
  assert.equal(result.performance.leader, small);
  assert.equal(result.performance.winner, small);
  const paired = result.comparisons.find(p => p.a === small && p.b === large);
  assert.deepEqual(paired.accepted_delta_ci95, [0, 0]);
  assert.ok(metrics.ci(imageIds.map(id => Number(id === badImage)))[1] >= rule.delta);
});

test('missing incumbent c081 can flip a verdict and yields coverage_sensitive', () => {
  const reviews = complete(c => c.physical_model_id === large ? rejected :
    c.physical_model_id === small && c.image_id === 'c081' ? minorRejection : {});
  const result = decide(reviews);
  assert.equal(result.status, 'coverage_sensitive');
  assert.equal(result.quality.winner, null);
  assert.equal(result.performance.leader, incumbent);
  assert.equal(result.performance.winner, small);
  assert.deepEqual(model(result, incumbent).accepted_rate_bounds, [28 / 29, 1]);
});

test('decision-reviewed enforces bindings, enums, explicit OCR, reviewer and issue consistency', () => {
  const cell = cells[0], good = review(cell);
  assert.equal(metrics.decisionReviewed(cell, good, contract, 'reviewer'), true);
  assert.equal(metrics.accepted(cell, good, rule), true);
  for (const changed of [null, { ...good, reviewed: false }, { ...good, reviewed: 1 },
    ...['output_sha256', 'image_id', 'input_sha256'].map(k => ({ ...good, [k]: 'different' })),
    { ...good, severity: 'not_assessed' }, { ...good, severity: 'invalid' },
    { ...good, ocr: 'not_assessed' }, { ...good, ocr: 'invalid' },
    { ...good, issues: ['salient_omission'] }]) {
    assert.equal(metrics.decisionReviewed(cell, changed, contract, 'reviewer'), false);
    assert.equal(metrics.accepted(cell, changed, rule), false);
  }
  assert.equal(metrics.decisionReviewed(cell, good, contract, '  '), false);
  for (const fields of [{ severity: 'major' }, { severity: 'critical' }, { severity: 'uncertain' },
    { severity: 'minor', issues: ['unsupported'] }, { ocr: 'wrong' }, { ocr: 'uncertain' }]) {
    assert.equal(metrics.accepted(cell, review(cell, fields), rule), false);
  }
  assert.equal(metrics.accepted(cell, review(cell, { severity: 'minor', issues: ['salient_omission'], ocr: 'omitted' }), rule), true);
  const modifiedContract = { ...contract, ocr: ['accurate'] };
  assert.equal(metrics.decisionReviewed(cell, good, modifiedContract, 'reviewer'), false);
});

test('OCR pending and none-with-issues reseal an otherwise completed decision', () => {
  for (const fields of [{ ocr: 'not_assessed' }, { severity: 'none', issues: ['unsupported'] }]) {
    const reviews = complete();
    reviews.reviews[cells[0].key] = review(cells[0], fields);
    const result = decide(reviews);
    assert.equal(result.status, 'insufficient_reviews');
    assert.equal(result.coverage.reviewed, 85);
    assert.deepEqual(result.coverage.pending_keys, [cells[0].key]);
    assert.equal(result.quality, null);
  }
  const reviews = complete();
  reviews.reviewer_id = '';
  assert.equal(decide(reviews).coverage.reviewed, 0);
});

test('generation errors are never accepted or pending and are not labelled major', () => {
  const changedManifest = clone(manifest);
  const cell = changedManifest.cells.find(c => c.key === cells[0].key);
  cell.generation_error = true;
  assert.equal(metrics.decisionReviewed(cell, review(cell), contract, 'reviewer'), false);
  assert.equal(metrics.accepted(cell, review(cell), rule), false);
  const reviews = complete();
  delete reviews.reviews[cell.key];
  const result = decide(reviews, perf, changedManifest);
  assert.equal(result.coverage.generation_errors, 1);
  assert.equal(result.coverage.reviewed, 85);
  assert.deepEqual(result.coverage.pending_keys, []);
  assert.equal(model(result, cell.physical_model_id).accepted, 28);
  assert.equal(model(result, cell.physical_model_id).major_or_worse, 0);
});

test('deterministic comparisons use per-image paired differences and the existing ci verbatim', () => {
  const reviews = complete(c => {
    const i = imageIds.indexOf(c.image_id), candidate = rule.candidates.indexOf(c.physical_model_id);
    return (i + candidate) % 4 === 0 ? rejected : {};
  });
  const before = JSON.stringify([manifest, reviews, perf, rule, contract]);
  const result = decide(reviews);
  assert.deepEqual(decide(reviews), result);
  assert.equal(JSON.stringify([manifest, reviews, perf, rule, contract]), before);
  const indicator = (id, image, kind) => {
    const cell = cells.find(c => c.physical_model_id === id && c.image_id === image);
    if (!cell) return kind === 'accepted' ? 0 : 1;
    const r = reviews.reviews[cell.key];
    return kind === 'accepted' ? Number(metrics.accepted(cell, r, rule)) : Number(rule.major_or_worse.includes(r.severity));
  };
  assert.deepEqual(result.comparisons.map(p => [p.a, p.b]), [[incumbent, small], [incumbent, large], [small, large]]);
  for (const [i, comparison] of result.comparisons.entries()) {
    assert.equal(comparison.n_images, 29);
    for (const kind of ['accepted', 'major']) {
      const deltas = imageIds.map(image => indicator(comparison.a, image, kind) - indicator(comparison.b, image, kind));
      assert.equal(comparison[kind + '_delta'], deltas.reduce((a, b) => a + b, 0) / 29);
      assert.deepEqual(comparison[kind + '_delta_ci95'], metrics.ci(deltas));
    }
    const [lo, hi] = comparison.accepted_delta_ci95, half = (hi - lo) / 2;
    assert.deepEqual(result.power[i], { a: comparison.a, b: comparison.b,
      ci_half_width: half, images_needed: Math.ceil(29 * (half / rule.delta) ** 2) });
  }
});

test('latency joins reject ambiguity and response mismatch; ties use the slower profile median', () => {
  const timings = clone(perf);
  const cell = cells.find(c => c.physical_model_id === small);
  const row = timings.rows.find(r => r.physical_model_id === small && r.image_id === cell.image_id && !r.E && !r.W);
  timings.rows.push({ ...row });
  const duplicate = decide(state, timings);
  assert.ok(model(duplicate, small).timing_missing.includes(cell.image_id));
  assert.equal(model(duplicate, small).latency.n, 28);
  const changedManifest = clone(manifest);
  changedManifest.cells.find(c => c.key === cell.key).response_sha256 = 'wrong-response';
  assert.ok(model(decide(state, perf, changedManifest), small).timing_missing.includes(cell.image_id));
  const noSmall = { ...perf, rows: perf.rows.filter(r => r.physical_model_id !== small) };
  assert.equal(model(decide(state, noSmall), small).latency, null);
  const tiePerf = { ...perf, rows: cells.filter(c => c.physical_model_id === small).slice(0, 4).map((c, i) => ({
    physical_model_id: small, image_id: c.image_id, E: false, W: false,
    profile_sha256: i < 2 ? 'slow' : 'fast', summed_stage_seconds: [10, 20, 2, 4][i],
    response_sha256: c.response_sha256,
  })) };
  assert.deepEqual(model(decide(state, tiePerf), small).latency, {
    profile_sha256: 'slow', n: 2, p50_seconds: 15,
    other_profiles: [{ profile_sha256: 'fast', n: 2, p50_seconds: 3 }],
  });
  const noTimings = decide(complete(), { ...perf, rows: [] });
  assert.equal(noTimings.performance.winner, null);
  assert.equal(noTimings.performance.verdict, 'none');
});

test('dataset, manifest and rubric mismatches fail closed', () => {
  for (const field of ['dataset_id', 'manifest_sha256', 'rubric_version']) {
    assert.throws(() => decide({ ...state, [field]: 'wrong' }), /mismatch/i);
    assert.throws(() => decide(state, perf, { ...manifest, [field]: 'wrong' }), /mismatch/i);
    assert.throws(() => decide(state, perf, manifest, { ...rule, [field]: 'wrong' }), /mismatch/i);
  }
});
