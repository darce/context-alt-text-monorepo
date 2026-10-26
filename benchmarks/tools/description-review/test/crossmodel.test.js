'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const fixture = require('./fixture.js');
const {manifest, state, contract} = fixture.loadReport();
const rule = fixture.loadRule();
const decisionCells = manifest.cells.filter(c => Object.entries(rule.filter).every(([k,v]) => c[k] === v));
const source = fs.readFileSync(path.join(fixture.DIR, 'operator-review.js'), 'utf8');
const css = fs.readFileSync(path.join(fixture.DIR, 'operator-review.css'), 'utf8');
const crossmodel = () => require('../operator-crossmodel.js');

test('order contains exactly each image\'s decision keys, including the incomplete image', () => {
 const before = JSON.stringify({manifest, rule});
 const order = crossmodel().order(manifest, rule, 'review-1');
 const ids = [...new Set(decisionCells.map(c => c.image_id))];
 assert.equal(decisionCells.length, 86);
 assert.equal(ids.length, 29);
 assert.deepEqual(Object.keys(order).sort(), ids.sort());
 for (const id of ids) {
  assert.deepEqual(order[id].slice().sort(), decisionCells.filter(c => c.image_id === id).map(c => c.key).sort());
 }
 assert.equal(order.c081.length, 2);
 assert.equal(JSON.stringify({manifest, rule}), before);
});

test('order is deterministic, seed-sensitive, and matches the review FNV-1a hash', () => {
 const api = crossmodel();
 const first = api.order(manifest, rule, 'review-1');
 assert.deepEqual(api.order(manifest, rule, 'review-1'), first);
 assert.notDeepEqual(api.order(manifest, rule, 'review-2'), first);
 // Pin the same FNV-1a operation and separators as the frozen interface.
 function hash(s) { let h=2166136261; for (const ch of s) { h^=ch.charCodeAt(0); h=Math.imul(h,16777619); } return h>>>0; }
 for (const [id, keys] of Object.entries(first)) {
  const expected = keys.slice().sort((a,b) => hash('review-1|'+id+'|'+a)-hash('review-1|'+id+'|'+b) || a.localeCompare(b));
  assert.deepEqual(keys, expected);
 }
 assert.deepEqual(api.order({cells:[]}, rule, 'empty'), {});
});

test('all candidates take first position for each complete image across 40 seeds (EVAL-14)', () => {
 const api = crossmodel();
 const byKey = new Map(decisionCells.map(c => [c.key,c]));
 const firsts = new Map();
 for (let seed=0; seed<40; seed++) {
  for (const [id, keys] of Object.entries(api.order(manifest, rule, 'seed-'+seed))) {
   if (!firsts.has(id)) firsts.set(id, new Set());
   firsts.get(id).add(byKey.get(keys[0]).physical_model_id);
  }
 }
 for (const [id, models] of firsts) {
  assert.deepEqual([...models].sort(), [...new Set(decisionCells.filter(c => c.image_id === id).map(c => c.physical_model_id))].sort(), id);
 }
});

test('progress delegates the decision-reviewed predicate and preserves pending manifest order', () => {
 const seen = [];
 const before = JSON.stringify(state);
 const result = crossmodel().progress(manifest, rule, state, contract, (cell, review, rubric, reviewerId) => {
  seen.push(cell);
  assert.equal(review, state.reviews[cell.key]);
  assert.equal(rubric, contract);
  assert.equal(reviewerId, state.reviewer_id);
  return cell.image_id === 'c009';
 });
 assert.deepEqual(seen, decisionCells);
 const pending = decisionCells.filter(c => c.image_id !== 'c009').map(c => c.key);
 assert.deepEqual(result, {done:86-pending.length,total:86,pending_keys:pending});
 assert.deepEqual(crossmodel().progress(manifest, rule, state, contract, () => true), {done:86,total:86,pending_keys:[]});
 assert.deepEqual(crossmodel().progress({cells:[]}, rule, state, contract, () => false), {done:0,total:0,pending_keys:[]});
 assert.equal(JSON.stringify(state), before);
});

test('progress uses OperatorMetrics.decisionReviewed when supplied by the host', () => {
 const prior = globalThis.OperatorMetrics;
 try {
  globalThis.OperatorMetrics = {decisionReviewed: () => false};
  assert.deepEqual(crossmodel().progress(manifest, rule, state, contract), {done:0,total:86,pending_keys:decisionCells.map(c => c.key)});
  globalThis.OperatorMetrics.decisionReviewed = () => true;
  assert.equal(crossmodel().progress(manifest, rule, state, contract).done, 86);
 } finally {
  if (prior === undefined) delete globalThis.OperatorMetrics;
  else globalThis.OperatorMetrics = prior;
 }
});

test('review source wires blind ordering, progress, assessment gate, and sealed decision mount', () => {
 for (const text of ['OperatorCrossModel.order', 'OperatorCrossModel.progress', 'OperatorDecision.render',
  'Cross-model blind review', 'Candidate 1', 'Candidate 2', 'Candidate 3', 'Decision reviewed',
  'Decision panel unavailable', 'operator-decision-rule', 'operator-decision-performance',
  'operator-decision', 'onUnseal', 'unsealed', 'clone(state)']) assert.ok(source.includes(text), text);
 for (const selector of ['.state', '.model-meta', '.timing', '.run-accounting', '.provenance-details', '.operator-pairs']) {
  assert.ok(css.includes(selector), selector);
 }
 assert.match(css, /operator-crossmodel[^{}]*\s+a\b[^{}]*\{[^}]*display\s*:\s*none/);
 for (const property of ['--model-hue', '--model-saturation']) assert.ok(css.includes(property));
 assert.match(source, /check\.disabled\s*=/);
 assert.match(source, /crossBlind[^;\n]*r\.ocr\s*===\s*'not_assessed'/);
 assert.match(source, /if\s*\(blind\s*\|\|\s*crossBlind\)\s*unsealed\s*=\s*false/);
 assert.match(source, /function persist\([\s\S]*?renderDecision\(\)/);
 assert.match(source, /function build\([\s\S]*?renderDecision\(\)/);
 assert.match(source, /const\s+TEXT\s*=/);
});

test('review and cross-model modules pass node --check', () => {
 for (const name of ['operator-review.js', 'operator-crossmodel.js']) {
  const run = spawnSync(process.execPath, ['--check', path.join(fixture.DIR,name)], {encoding:'utf8'});
  assert.equal(run.status, 0, run.stdout+run.stderr);
 }
});
