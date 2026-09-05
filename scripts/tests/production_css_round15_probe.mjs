// TEST-15: accepts a pre-fix source path to prove each regression discriminates.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';
import { resolve, dirname } from 'node:path';
const path = resolve(process.argv[2] ?? 'apps/prototype-wp-alt-context/js/admin/styles/components/__tests__/productionCssBundle.ts');
const source = `const __dirname = ${JSON.stringify(dirname(path))};\n` + stripTypeScriptTypes(readFileSync(path, 'utf8'));
const fixture = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const originalKill = process.kill;
let failures = 0;
const check = (name, test) => {
  try { test(); console.log(`PASS ${name}`); }
  catch (error) { failures++; console.error(`FAIL ${name}: ${error.message}`); }
};
try {
  process.kill = (_pid, signal) => {
    if (signal === 0) throw Object.assign(new Error('probe denied'), { code: 'EPERM' });
  };
  const options = listProcesses => ({
    timeoutMs: 1, terminationGraceMs: 0, killConfirmationMs: 60,
    processGroupStartToken: 'leader', readProcessStartToken: () => 'leader',
    readExitCode: () => 42, listProcesses,
  });
  check('unrelated malformed line with zombie-only group', () => {
    assert.equal(fixture.waitForProcessGroup(2468, options(() => 'unrelated ???\n1 1 S\n12 2468 Z+\n')), 42);
  });
  for (const listing of ['live', 'malformed', 'empty', 'failed']) {
    check(`final confirmation diagnostics: ${listing}`, () => {
      let time = 0;
      let polls = 0;
      const opts = options(() => {
        polls++;
        if (listing === 'failed') throw Object.assign(new Error('listing denied'), { code: 'EACCES' });
        if (listing === 'empty') return '';
        if (listing === 'malformed') return 'bad listing';
        return `${polls} 2468 S?\n1 1 S\n`;
      });
      assert.throws(() => fixture.waitForProcessGroup(2468, {
        ...opts, now: () => time, sleep: ms => { assert.ok(ms <= 50); time += ms; },
      }), error => {
        assert.ok(error instanceof fixture.ProductionCssBuildTeardownError);
        assert.match(error.message, /signal probe: EPERM/);
        if (listing === 'live') assert.ok(error.message.includes(`${polls} 2468 S?`));
        if (listing === 'malformed') assert.match(error.message, /zero lines.*bad listing/);
        if (listing === 'empty') assert.match(error.message, /zero lines/);
        if (listing === 'failed') assert.match(error.message, /listing failed: EACCES/);
        assert.ok(polls >= 4, 'must refresh listing on every confirmation poll');
        return true;
      });
    });
  }
  check('group dies late in confirmation window', () => {
    let time = 0;
    assert.equal(fixture.waitForProcessGroup(2468, {
      ...options(() => `12 2468 ${time >= 50 ? 'Z' : 'S'}\n`),
      now: () => time, sleep: ms => { time += ms; },
    }), 42);
    assert.equal(time, 50);
  });
} finally { process.kill = originalKill; }
process.exitCode = failures ? 1 : 0;
