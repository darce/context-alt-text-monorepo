// Standalone TEST-15 probes; no frontend dependencies or child-process spawning required.
// Pass a pre-fix fixture path as argv[2] to verify that the regressions discriminate.
// --mutate-reader and --mutate-teardown independently restore the unsafe behavior in memory.
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';

const fixturePath = resolve('apps/prototype-wp-alt-context/js/admin/styles/components/__tests__/productionCssBundle.ts');
const mode = process.argv[2];
let fixtureSource = fs.readFileSync(mode?.startsWith('--mutate-') ? fixturePath : mode ?? fixturePath, 'utf8');
if (mode === '--mutate-reader') {
  fixtureSource = fixtureSource
    .replace('[...bundle.manifestSources]', 'readManifestBuildSources(bundle.outDir)')
    .replace('return bundle.artifactStamp;', 'return readStampedFingerprint(join(bundle.outDir, STAMP_FILE));');
} else if (mode === '--mutate-teardown') {
  fixtureSource = fixtureSource.replace('if (!isGroupAlive()) return;\n      throw', 'throw');
}
const source = `const __dirname = ${JSON.stringify(dirname(fixturePath))};\n` + stripTypeScriptTypes(fixtureSource);
const fixture = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
let failures = 0;
const check = (name, test) => {
  try { test(); console.log(`PASS ${name}`); }
  catch (error) { failures++; console.error(`FAIL ${name}: ${error.message}`); }
};

for (const timing of ['waiting', 'reading']) {
  check(`D5-R11-01 existing reader during ${timing}`, () => {
    const root = fs.mkdtempSync(join(tmpdir(), 'acx-round12-reader-'));
    const state = fingerprint => ({ fingerprint, generation: fingerprint });
    const create = fingerprint => {
      const outDir = join(root, fingerprint);
      fs.mkdirSync(join(outDir, 'assets'), { recursive: true });
      fs.mkdirSync(join(outDir, '.vite'), { recursive: true });
      fs.writeFileSync(join(outDir, 'assets/admin.css'), fingerprint);
      fs.writeFileSync(join(outDir, '.vite/manifest.json'), JSON.stringify({ main: { src: 'js/admin/main.tsx' } }));
      fs.writeFileSync(join(outDir, 'build-stamp.json'), JSON.stringify({ fingerprint }));
      return outDir;
    };
    try {
      const oldDir = create('A');
      const reader = fixture.readProductionCssArtifact(oldDir, 'A');
      let current = timing === 'waiting' ? 'B' : 'A';
      const result = fixture.loadFingerprintStableArtifact(state('A'), () => state(current), {
        artifactDirForFingerprint: fingerprint => join(root, fingerprint),
        prepareArtifact: () => {},
        readStampedFingerprint: outDir => fs.existsSync(join(outDir, 'build-stamp.json'))
          ? JSON.parse(fs.readFileSync(join(outDir, 'build-stamp.json'))).fingerprint : null,
        touchArtifact: () => {},
        discardArtifact: outDir => fs.rmSync(outDir, { recursive: true, force: true }),
        buildArtifact: outDir => create(outDir.split('/').at(-1)),
        stampArtifact: () => {},
        readArtifact: (outDir, fingerprint) => {
          const bundle = fixture.readProductionCssArtifact(outDir, fingerprint);
          current = 'B';
          return bundle;
        },
      });
      assert.equal(result.fingerprint, 'B');
      assert.ok(fs.existsSync(oldDir), 'a fingerprint change must retain a stamped artifact');
      // Subsequent bounded cache eviction must also be harmless to a returned reader.
      fs.rmSync(oldDir, { recursive: true });
      assert.equal(fixture.readArtifactStamp(reader), 'A');
      assert.deepEqual(fixture.manifestBuildSources(reader), ['js/admin/main.tsx']);
      assert.equal(reader.css, 'A');
    } finally { fs.rmSync(root, { recursive: true, force: true }); }
  });
}

for (const signal of ['SIGTERM', 'SIGKILL']) {
  for (const survives of [false, true]) {
    check(`D5-R11-02 leader disappears before ${signal}, group survives=${survives}`, () => {
      let reads = 0;
      let alive = true;
      const signals = [];
      const wait = () => fixture.waitForProcessGroup(2468, {
        timeoutMs: 100, terminationGraceMs: 0, readExitCode: () => 42,
        processGroupStartToken: 'leader',
        readProcessStartToken: () => {
          // groupState, TERM identity, grace liveness, KILL liveness, KILL identity.
          if (++reads >= (signal === 'SIGTERM' ? 2 : 5)) {
            alive = survives;
            return null;
          }
          return 'leader';
        },
        isProcessGroupAlive: () => alive,
        sendSignal: (_pid, sent) => signals.push(sent),
      });
      if (survives) assert.throws(wait, fixture.ProductionCssBuildTeardownError);
      else assert.equal(wait(), 42);
      assert.deepEqual(signals, signal === 'SIGTERM' ? [] : ['SIGTERM']);
    });
  }
}
process.exitCode = failures ? 1 : 0;
