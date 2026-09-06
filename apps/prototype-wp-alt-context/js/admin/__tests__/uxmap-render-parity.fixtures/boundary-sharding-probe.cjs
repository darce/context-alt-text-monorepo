const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const file = process.argv[2];
const source = fs.readFileSync(file, 'utf8');
const start = source.indexOf("describe('ux-map generated-render provenance', () => {") + "describe('ux-map generated-render provenance', () => {".length;
const end = source.indexOf("  it('executes the sanctioned renderer", start);
const body = source.slice(start, end).replace(': unknown', '').replace('(testId: string)', '(testId)');
const ids = ['test_render_ux_maps.RendererBoundaryTests.test_first', 'test_render_ux_maps.RendererBoundaryTests.test_second'];
const calls = [];
const budgets = [];
const it = (name, fn, budget) => { budgets.push(budget); fn(); };
it.each = rows => (name, fn, budget) => rows.forEach(row => it(name, () => fn(row), budget));
vm.runInNewContext(body, {
  it, uxMapPython: '/usr/bin/python3', uxMapsDir: '/maps',
  BOUNDARY_SUITE_DEADLINE_MS: 300000, BOUNDARY_SHARD_DEADLINE_MS: 120000,
  vitestBudget: ms => ms + Math.max(5000, ms / 10),
  spawnSync: (python, args, options) => {
    if (args[0] === '-c') return {status: 0, stdout: JSON.stringify(ids), stderr: ''};
    calls.push({args: Array.from(args), options});
    return {status: 0, stdout: '', stderr: ''};
  },
  expect: status => ({toBe: expected => assert.equal(status, expected)}),
});
assert.equal(calls.length, ids.length, 'each discovered mutation needs an independent process');
for (const [index, call] of calls.entries()) {
  assert.deepEqual(call.args, ['-m', 'unittest', ids[index]]);
  assert.equal(call.options.timeout, 120000);
  assert.equal(call.options.cwd, '/maps');
  assert.equal(budgets[index], 132000);
}
console.log('independent subprocesses and shared deadline budgets verified');
