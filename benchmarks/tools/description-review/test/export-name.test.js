'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const review = require('../operator-review.js');
const modulePath = path.resolve(__dirname, '../operator-review.js');
const source = fs.readFileSync(modulePath, 'utf8');
const bases = ['operator-reviews', 'unmatched-prior-preferences'];
const safeName = /^[A-Za-z0-9.+-]+$/;

function stubDate({year=2026, month=9, day=28, hour=6, minute=5, second=9, offset=240}={}) {
 return {
  getFullYear: () => year,
  getMonth: () => month,
  getDate: () => day,
  getHours: () => hour,
  getMinutes: () => minute,
  getSeconds: () => second,
  getTimezoneOffset: () => offset
 };
}

test('exportFileName is exposed through CommonJS and the browser API', () => {
 assert.equal(typeof review.exportFileName, 'function');
 assert.equal(review.exportFileName, globalThis.OperatorReview.exportFileName);
});

for (const [offset, suffix] of [[240,'-0400'], [300,'-0500'], [0,'+0000'], [-60,'+0100'],
 [-330,'+0530'], [-345,'+0545'], [210,'-0330']]) {
 test('exportFileName formats local fields with offset '+offset, () => {
  for (const base of bases) {
   const result = review.exportFileName(base, stubDate({offset}));
   assert.equal(result, base+'-2026-10-28T06-05-09'+suffix+'.json');
   assert.match(result, safeName);
  }
 });
}

test('exportFileName pads the year and every local date/time field', () => {
 for (const base of bases) {
  for (const [month, expected] of [[0,'01'], [11,'12']]) {
   const date = stubDate({year:7, month, day:1, hour:0, minute:5, second:9, offset:0});
   const result = review.exportFileName(base, date);
   assert.equal(result, base+'-0007-'+expected+'-01T00-05-09+0000.json');
   assert.match(result, safeName);
  }
 }
});

const childScript = "const {exportFileName}=require(process.argv[1]); process.stdout.write(exportFileName('operator-reviews',new Date(Number(process.argv[2]))));";
for (const [TZ, instant, expected] of [
 ['America/Toronto', Date.UTC(2026,9,28,10,5,9), 'operator-reviews-2026-10-28T06-05-09-0400.json'],
 ['Asia/Kolkata', Date.UTC(2026,9,28,10,5,9), 'operator-reviews-2026-10-28T15-35-09+0530.json'],
 ['America/Toronto', Date.UTC(2026,0,15,12,0,0), 'operator-reviews-2026-01-15T07-00-00-0500.json']
]) {
 test('real Date uses '+TZ+' at '+instant, () => {
  const run = spawnSync(process.execPath, ['-e', childScript, modulePath, String(instant)], {
   encoding:'utf8', env:{...process.env, TZ}
  });
  assert.ifError(run.error);
  assert.equal(run.status, 0, run.stdout+run.stderr);
  assert.equal(run.stdout, expected);
  assert.match(run.stdout, safeName);
 });
}

test('both export click handlers compute their filename at export time', () => {
 for (const base of bases) {
  assert.ok(!source.includes("'"+base+".json'"), 'old filename: '+base);
  assert.match(source, new RegExp("download:\\s*exportFileName\\(\\s*'"+base+"'\\s*,\\s*new Date\\(\\)\\s*\\)"));
 }
});

test('operator-review.js passes node --check', () => {
 const run = spawnSync(process.execPath, ['--check', modulePath], {encoding:'utf8'});
 assert.ifError(run.error);
 assert.equal(run.status, 0, run.stdout+run.stderr);
});
