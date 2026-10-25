// UXREC-1 WB_CONTROL actual-browser acceptance.
// Bundles the real WorkbenchPage provider tree (entry.tsx) and compiled main.scss from the
// tree under test, intercepts only HTTP transport with producer-shaped data, and drives
// headless Chromium. No component, hook, guard or style is substituted.
//
// node acceptance.mjs <source-root> <label> <out-dir>
// BROWSER_HOST_INPUTS must name the pinned immutable WordPress host manifest.
// WB_CONTROL_PREFLIGHT_ONLY=1 validates transport/host inputs without launching Chrome.
import { createHash } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import console from 'node:console';
import { setTimeout as sleep } from 'node:timers/promises';
import { URL, URLSearchParams, fileURLToPath, pathToFileURL } from 'node:url';
// Browser globals below are only referenced inside page.evaluate/addInitScript callbacks.
/* global window, document, location, getComputedStyle, innerWidth, innerHeight, scrollY, MouseEvent, Response */

const here = path.dirname(fileURLToPath(import.meta.url));
const runnerApp = path.resolve(here, '../../../../../..');
const load = (specifier) => import(pathToFileURL(path.join(runnerApp, 'node_modules', specifier)).href);
const { build } = await load('esbuild/lib/main.js');
const sass = await load('sass/sass.node.mjs');
const { chromium } = await load('playwright-core/index.mjs');
const { default: Ajv } = await load('ajv/lib/ajv.js');

const [sourceArg, label = 'run', outArg] = process.argv.slice(2);
if (!sourceArg || !outArg) {
  throw new Error('usage: node acceptance.mjs <source-root> <label> <out-dir>');
}
const source = path.resolve(sourceArg);
const out = path.resolve(outArg);
const app = path.join(source, 'apps/prototype-wp-alt-context');
await fs.mkdir(out, { recursive: true });

const sha256 = (buffer) => createHash('sha256').update(buffer).digest('hex');
const TUPLE_FILES = [
  'apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx',
  'apps/prototype-wp-alt-context/js/admin/pages/workbench/ScanTabContent.tsx',
  'apps/prototype-wp-alt-context/js/admin/styles/components/_workbench.scss',
  'apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx',
  'apps/prototype-wp-alt-context/js/admin/styles/components/_media-selection.scss',
  'apps/prototype-wp-alt-context/js/admin/pages/workbench/ActivityStatusStrip.tsx',
  'apps/prototype-wp-alt-context/js/admin/pages/workbench/Panels.tsx',
  'apps/prototype-wp-alt-context/js/admin/pages/__tests__/fixtures/wb-control/entry.tsx',
  'apps/prototype-wp-alt-context/js/admin/pages/__tests__/fixtures/wb-control/acceptance.mjs',
  'apps/prototype-wp-alt-context/js/admin/pages/__tests__/fixtures/wb-control/index.html',
  'apps/prototype-wp-alt-context/js/admin/pages/__tests__/WorkbenchPage.control-composition.test.tsx',
  'apps/prototype-wp-alt-context/js/admin/pages/__tests__/WorkbenchPage.library-lifecycle.test.tsx',
  'apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/RecognitionPolicyControl.test.tsx',
  'apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/ScanTabContent.control-composition.test.tsx',
  'apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/WorkbenchPage.integration.test.tsx',
  'apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/WorkbenchPage.test.tsx',
  'apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/MediaSelection.actionSurface.test.tsx',
  'apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/action-progress-browser/acceptance.mjs',
  'apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/action-progress-browser/fixture.tsx',
];
const tuple = {};
for (const file of TUPLE_FILES) {
  tuple[file] = sha256(await fs.readFile(path.join(source, file)));
}

// ---- Producer-shaped transport (PHP REST keys and shared run schema checked below) ----
const origin = 'https://wb-control-acceptance.invalid';
const tenant = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee';
const runId = 'bbbbbbbb-cccc-4ddd-8eee-ffffffffffff';
const endpointNames = [
  'workbenchMedia',
  'workbenchMediaDetail',
  'recognitionMediaIdentities',
  'recognitionSuggestions',
  'recognitionMergeSuggestions',
  'recognitionNameSuggestions',
  'recognitionClusters',
  'recognitionBatchRuns',
  'recognitionJobs',
  'recognitionSyncHealth',
  'recognitionSyncStatus',
  'recognitionDescribeHistory',
  'recognitionDescribeRuns',
  'settings',
  'recognitionGpuStatus',
];
const endpoints = Object.fromEntries(endpointNames.map((name) => [name, `${origin}/mock/${name}`]));
const image =
  'data:image/svg+xml,' +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300"><rect width="300" height="300" fill="#dde5ed"/></svg>',
  );
const items = Array.from({ length: 10 }, (_, i) => ({
  id: i + 1,
  title: `Tall media ${i + 1}`,
  status: 'complete',
  thumbnailUrl: image,
  thumbnailSrcset: null,
  thumbnailSizes: null,
  thumbnailDimensions: { width: 300, height: 300 },
  altText: 'Long existing media evidence. '.repeat(60),
  isDecorative: false,
  editUrl: null,
  tags: [],
}));
const settings = {
  url: origin,
  url_source: 'option',
  url_rejection_reason: null,
  url_rejection_source: null,
  url_rejection_value: null,
  effective_target_url: origin,
  effective_target_mode: 'service',
  recognition_source: 'service',
  recognition_source_source: 'default',
  api_key_set: true,
  api_key_last4: '****test',
  key_source: 'option',
  api_key_storage_notice: null,
  tenant_id: tenant,
  tenant_id_source: 'option',
  tenant_paired: true,
  alt_style: 'alt_only',
  context_categories: ['attachment'],
  context_categories_error: null,
  recognition_enabled: false,
  development_face_scan_available: false,
  allow_person_names: true,
  allow_person_names_error: null,
  allow_person_names_status: 200,
  allow_person_names_code: null,
  description_service_title: 'Description Service',
  description_budget: {
    max_attempts: 3,
    usage: { attempts: 0, successes: 0, failures: 0, cost_total: 0 },
    recent_errors: [],
  },
};
const runPayload = (run) => ({
  tenant_id: tenant,
  run_id: runId,
  status: run.status,
  phase: run.phase,
  completed: run.completed,
  failed: 0,
  skipped: 0,
  total: 10,
  cancel_requested: run.cancelling,
  eta_seconds: null,
  gpu_state: 'ready',
  recognition_enabled: false,
});

const preflight = { checks: [], items_responses: [] };
const HOST_MANIFEST_SHA256 = '0ca7ab4bbbb08f9c79e5573a66f3ef4b6c4c8c62dc554e1ff056edd288b9ce6a';
const failPreflight = async () => {
  preflight.pass = false;
  await fs.writeFile(
    path.join(out, 'results.json'),
    JSON.stringify(
      { label, source, tuple, status: 'FAIL', stage: 'preflight', browser_launched: false, preflight },
      null,
      2,
    ) + '\n',
  );
  throw new Error('WB acceptance preflight failed before Chromium; see results.json');
};
let host;
const hostAssets = [];
try {
  if (!process.env.BROWSER_HOST_INPUTS) {
    throw new Error('BROWSER_HOST_INPUTS is required; isolated geometry is not acceptance');
  }
  const manifestPath = path.resolve(process.env.BROWSER_HOST_INPUTS);
  const bytes = await fs.readFile(manifestPath);
  if (sha256(bytes) !== HOST_MANIFEST_SHA256) {
    throw new Error('WordPress host manifest digest differs from the pinned immutable input');
  }
  host = JSON.parse(bytes);
  if (
    host.wordpress_version !== '7.1.3' ||
    host.html_classes !== 'wp-toolbar' ||
    !host.body_classes.split(' ').includes('wp-admin') ||
    !host.body_classes.split(' ').includes('wp-core-ui') ||
    !host.root_html.includes('class="wrap alt-context-admin"') ||
    !host.root_html.includes('id="root" class="alt-context-workbench"') ||
    !host.root_html.includes('id="wpbody-content"') ||
    host.assets.length !== 27
  ) {
    throw new Error('WordPress host version, classes, native PHP wrapper or ordered 27-asset cascade is missing');
  }
  for (const [index, asset] of host.assets.entries()) {
    const assetBytes = await fs.readFile(asset.path);
    if (sha256(assetBytes) !== asset.sha256) {
      throw new Error(`WordPress host asset digest mismatch: ${asset.path}`);
    }
    hostAssets.push({ ...asset, href: `/wp-host/${index}.css`, bytes: assetBytes });
  }
  preflight.host = {
    manifestPath,
    sha256: sha256(bytes),
    wordpress_version: host.wordpress_version,
    html_classes: host.html_classes,
    body_classes: host.body_classes,
    root_html: host.root_html,
    assets: host.assets.map((asset, index) => ({ ...asset, href: hostAssets[index].href })),
    cascade: '27 verified WordPress assets in manifest order, then candidate main.scss',
    limits: host.limits,
  };
  preflight.checks.push({ name: 'pinned WordPress host inputs verified', pass: true });
} catch (error) {
  preflight.checks.push({ name: 'pinned WordPress host inputs verified', pass: false, error: String(error) });
  await failPreflight();
}
{
  const php = await fs.readFile(path.join(app, 'src/api/class-api.php'), 'utf8');
  const rowStart = php.indexOf("\t\t\t\t\t'id'           => $attachment_id");
  const rowEnd = php.indexOf('\n\t\t\t\t);', rowStart);
  const phpKeys = [...php.slice(rowStart, rowEnd).matchAll(/^\t{5}'([^']+)'\s*=>/gm)].map((m) => m[1]).sort();
  preflight.checks.push({
    name: 'media rows use exact WorkbenchMedia PHP keys',
    pass: rowStart > 0 && items.every((row) => JSON.stringify(Object.keys(row).sort()) === JSON.stringify(phpKeys)),
    expected: phpKeys,
  });
  const settingsPhp = await fs.readFile(path.join(app, 'src/api/class-settings-controller.php'), 'utf8');
  const getSettings = settingsPhp.slice(
    settingsPhp.indexOf('public function get_settings('),
    settingsPhp.indexOf('public function save_settings('),
  );
  const settingKeys = [...getSettings.matchAll(/^\t{4}'([^']+)'\s*=>/gm)].map((m) => m[1]).sort();
  preflight.checks.push({
    name: 'settings use exact SettingsController::get_settings keys',
    pass: JSON.stringify(Object.keys(settings).sort()) === JSON.stringify(settingKeys),
    expected: settingKeys,
  });
  const schemaPath = path.join(source, 'packages/shared-contracts/schemas/scene-describe-run.schema.json');
  const schema = await fs.readFile(schemaPath, 'utf8').catch(() => null);
  if (schema === null) {
    preflight.checks.push({ name: 'describe run schema available', pass: false, path: schemaPath });
  } else {
    const contractSchema = JSON.parse(schema);
    const ajv = new Ajv({ allErrors: true });
    ajv.addSchema(contractSchema);
    const validate = ajv.getSchema(contractSchema.$id);
    const validateItems = ajv.getSchema(`${contractSchema.$id}#/definitions/items`);
    preflight.schema_sha256 = sha256(schema);
    // Run the real frontend boundary as well as the stricter producer schema.
    // registerConfig and fetch are fixture-local; no request can reach a live service.
    const apiFile = path.join(out, 'preflight-api.mjs');
    await build({
      stdin: {
        contents: `export { parseDescribeRunResponse, fetchDescribeRunItems } from ${JSON.stringify(path.join(app, 'js/admin/api/describeApi.ts'))};\nexport { registerConfig } from ${JSON.stringify(path.join(app, 'js/admin/api/config.ts'))};`,
        resolveDir: app,
      },
      bundle: true,
      platform: 'node',
      format: 'esm',
      outfile: apiFile,
      define: { 'import.meta.env': '{"DEV":false,"PROD":true,"MODE":"test","BASE_URL":"./"}' },
      logLevel: 'error',
    });
    const api = await import(pathToFileURL(apiFile).href);
    api.registerConfig({ nonce: 'offline-fixture', ajaxUrl: '/mock/ajax', tenant_id: tenant, endpoints });
    for (const run of [
      { phase: 'queued', status: 'running', completed: 0, cancelling: false },
      { phase: 'warming', status: 'running', completed: 0, cancelling: false },
      { phase: 'describing', status: 'running', completed: 0, cancelling: false },
      { phase: 'describing', status: 'running', completed: 3, cancelling: false },
      { phase: 'describing', status: 'running', completed: 0, cancelling: true },
      { phase: 'cancelled', status: 'cancelled', completed: 0, cancelling: true },
      { phase: 'complete', status: 'completed', completed: 10, cancelling: false },
    ]) {
      preflight.checks.push({
        name: `run payload ${run.phase}/${run.status}/cancel=${run.cancelling} matches shared schema`,
        pass: validate(runPayload(run)),
        errors: validate.errors ?? null,
      });
      const transport = makeTransport({ ...run, submitted: true });
      const status = (await transport(`recognitionDescribeRuns/${runId}`, 'GET')).body;
      api.parseDescribeRunResponse(status);
      const response = (await transport(`recognitionDescribeRuns/${runId}/items`, 'GET')).body;
      preflight.items_responses.push({ phase: run.phase, status: run.status, completed: run.completed, response });
      // PHP preserves the upstream envelope and enriches only these item keys.
      const upstream = globalThis.structuredClone(response);
      for (const item of upstream.items) {
        delete item.existing_alt;
        delete item.thumbnail_url;
        delete item.thumbnail_srcset;
      }
      preflight.checks.push({
        name: `actual GET items ${run.phase}/${run.status}/${run.completed} matches #/definitions/items`,
        pass: validateItems(upstream),
        errors: globalThis.structuredClone(validateItems.errors),
      });
      preflight.checks.push({
        name: `actual GET items ${run.phase}/${run.status}/${run.completed} matches accepted identity/counts and WP annotations`,
        pass:
          response.tenant_id === status.tenant_id &&
          response.run_id === status.run_id &&
          response.items.length === status.total &&
          response.items.filter((item) => item.status === 'completed' && item.alt_text_draft !== null).length ===
            status.completed &&
          response.items.every(
            (item, index) =>
              item.media_id === items[index].id &&
              item.existing_alt === true &&
              item.thumbnail_url === items[index].thumbnailUrl &&
              item.thumbnail_srcset === null,
          ),
      });
      const originalFetch = globalThis.fetch;
      try {
        globalThis.fetch = async (url, options) => {
          if (String(url) !== `${endpoints.recognitionDescribeRuns}/${runId}/items` || options?.method !== 'GET') {
            throw new Error(`Unexpected preflight request: ${options?.method} ${url}`);
          }
          const actual = await transport(`recognitionDescribeRuns/${runId}/items`, 'GET');
          return new Response(JSON.stringify(actual.body), { status: actual.status ?? 200 });
        };
        const parsed = await api.fetchDescribeRunItems(runId);
        preflight.checks.push({
          name: `actual GET items ${run.phase}/${run.status}/${run.completed} accepted by real frontend boundary`,
          pass: JSON.stringify(parsed) === JSON.stringify(response),
        });
      } finally {
        globalThis.fetch = originalFetch;
      }
      // [TEST-15] Escaped fixture defects must be rejected by the same schema check.
      const missingTenant = globalThis.structuredClone(upstream);
      delete missingTenant.tenant_id;
      preflight.checks.push({
        name: `items ${run.phase}/${run.completed} rejects missing tenant_id`,
        pass:
          !validateItems(missingTenant) &&
          validateItems.errors.some((error) => error.params.missingProperty === 'tenant_id'),
      });
      for (let index = 0; index < upstream.items.length; index += 1) {
        const missingTiming = globalThis.structuredClone(upstream);
        delete missingTiming.items[index].processing_ms;
        preflight.checks.push({
          name: `items ${run.phase}/${run.completed} rejects missing processing_ms at item ${index + 1}`,
          pass:
            !validateItems(missingTiming) &&
            validateItems.errors.some((error) => error.params.missingProperty === 'processing_ms'),
        });
      }
    }
    const unaccepted = makeTransport({ submitted: false });
    for (const key of [`recognitionDescribeRuns/${runId}`, `recognitionDescribeRuns/${runId}/items`]) {
      preflight.checks.push({
        name: `unaccepted GET ${key} stays unavailable`,
        pass: (await unaccepted(key, 'GET')).status === 404,
      });
    }
    const transport = makeTransport({ submitted: true });
    for (const [method, key] of [
      ['DELETE', `recognitionDescribeRuns/${runId}`],
      ['GET', `recognitionDescribeRuns/${runId}/cancel`],
      ['POST', `recognitionDescribeRuns/${runId}/items`],
      ['GET', 'recognitionDescribeRuns/unknown/items'],
    ]) {
      preflight.checks.push({
        name: `unexpected ${method} ${key} fails closed`,
        pass: (await transport(key, method)) === null,
      });
    }
  }
  preflight.pass = preflight.checks.every((check) => check.pass);
}
await fs.writeFile(path.join(out, 'preflight.json'), JSON.stringify(preflight, null, 2) + '\n');
if (!preflight.pass) {
  await failPreflight();
}
if (process.env.WB_CONTROL_PREFLIGHT_ONLY === '1') {
  await fs.writeFile(
    path.join(out, 'results.json'),
    JSON.stringify({ label, source, tuple, status: 'PREFLIGHT_PASS', browser_launched: false, preflight }, null, 2) +
      '\n',
  );
  console.log(JSON.stringify({ status: 'PREFLIGHT_PASS', checks: preflight.checks.length, browser_launched: false }));
  process.exit(0);
}

// ---- Bundle actual components and production styles from the tree under test ----
const bundleDir = path.join(out, 'bundle');
await fs.mkdir(bundleDir, { recursive: true });
await build({
  entryPoints: [path.join(app, 'js/admin/pages/__tests__/fixtures/wb-control/entry.tsx')],
  bundle: true,
  format: 'esm',
  jsx: 'automatic',
  outfile: path.join(bundleDir, 'fixture.js'),
  nodePaths: [path.join(runnerApp, 'node_modules')],
  logLevel: 'error',
  define: {
    'process.env.NODE_ENV': '"test"',
    'import.meta.hot': 'undefined',
    'import.meta.env': '{"MODE":"test","DEV":false,"PROD":false,"BASE_URL":"./"}',
  },
  plugins: [
    {
      name: 'production-scss',
      setup(b) {
        b.onLoad({ filter: /\.scss$/ }, (args) => ({
          contents: sass.compile(args.path, { silenceDeprecations: ['import', 'global-builtin', 'color-functions'] })
            .css,
          loader: 'css',
        }));
      },
    },
  ],
});
const bundle = await fs.readFile(path.join(bundleDir, 'fixture.js'), 'utf8');
const css = await fs.readFile(path.join(bundleDir, 'fixture.css'), 'utf8');
const html =
  `<!doctype html><html lang="en" class="${host.html_classes}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">` +
  hostAssets.map((asset) => `<link rel="stylesheet" href="${asset.href}">`).join('') +
  `<link rel="stylesheet" href="/fixture.css"></head><body class="${host.body_classes}">${host.root_html}<script type="module" src="/fixture.js"></script></body></html>`;

const report = {
  label,
  source,
  tuple,
  preflight,
  mocked: 'HTTP transport/data only; every request intercepted; external origins blocked',
  components: 'Actual WorkbenchPage provider tree (entry.tsx) and compiled main.scss from the tree under test',
  browser: null,
  viewports: [],
  checks: [],
  // Non-gating: measured composition facts owned by a peer lane, reported rather than hidden.
  observations: [],
  screenshots: [],
};

const executablePath =
  process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ??
  '/home/gate/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux-arm64/chrome-headless-shell';
const browser = await chromium
  .launch({ executablePath, headless: true, chromiumSandbox: true })
  .catch(async (error) => {
    await fs.writeFile(
      path.join(out, 'results.json'),
      JSON.stringify(
        { ...report, status: 'BROWSER_UNAVAILABLE', browser_launched: false, error: String(error) },
        null,
        2,
      ) + '\n',
    );
    throw error;
  });
report.browser = { executablePath, version: browser.version() };

const VIEWPORTS = [
  { width: 1440, height: 1000 },
  { width: 719, height: 960 },
];

const check = (viewport, state, name, pass, evidence) =>
  report.checks.push({ viewport: `${viewport.width}x${viewport.height}`, state, name, pass: Boolean(pass), evidence });

const observe = (viewport, state, name, owner, pass, evidence) =>
  report.observations.push({
    viewport: `${viewport.width}x${viewport.height}`,
    state,
    name,
    owner,
    pass: Boolean(pass),
    evidence,
  });

const waitUntil = async (probe, timeoutMs = 8000) => {
  const end = Date.now() + timeoutMs;
  let last;
  while (Date.now() < end) {
    last = await probe();
    if (last) {
      return last;
    }
    await sleep(100);
  }
  return last;
};

const newPage = async (viewport, record, transport) => {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  page.on('pageerror', (error) => record.errors.push(`pageerror: ${error.message}`));
  await page.addInitScript(
    ({ endpoints: configured, tenant: tenantId }) => {
      window.AltContextAdmin = {
        nonce: 'offline-fixture',
        ajaxUrl: '/mock/ajax',
        tenant_id: tenantId,
        endpoints: configured,
        recognitionSource: 'service',
        effectiveTargetUrl: 'offline data fixture',
        recognitionPolicy: { enabled: false, canManage: false },
      };
    },
    { endpoints, tenant },
  );
  await page.route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== origin) {
      if (url.protocol === 'data:' || url.protocol === 'blob:') {
        return route.continue();
      }
      record.errors.push(`blocked external ${url.href}`);
      return route.abort();
    }
    if (url.pathname === '/fixture.js') {
      return route.fulfill({ contentType: 'application/javascript', body: bundle });
    }
    if (url.pathname === '/fixture.css') {
      return route.fulfill({ contentType: 'text/css', body: css });
    }
    const hostAsset = hostAssets.find((asset) => asset.href === url.pathname);
    if (hostAsset && request.method() === 'GET') {
      return route.fulfill({ contentType: 'text/css', body: hostAsset.bytes });
    }
    if (request.method() === 'GET' && ['/fixture', '/terminal', '/reopen'].includes(url.pathname)) {
      return route.fulfill({ contentType: 'text/html', body: html });
    }
    if (!url.pathname.startsWith('/mock/')) {
      record.errors.push(`unmocked ${request.method()} ${url.pathname}`);
      return route.abort();
    }
    const key = url.pathname.slice('/mock/'.length);
    const method = request.method();
    record.requests.push({ key, method });
    const response = await transport(key, method);
    if (response === null) {
      record.errors.push(`unmocked ${method} ${key}`);
      return route.abort();
    }
    return route.fulfill({
      status: response.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(response.body),
    });
  });
  return { context, page };
};

function makeTransport(run) {
  return async (key, method) => {
    if (
      method !== 'GET' &&
      !(method === 'POST' && (key === 'recognitionDescribeRuns' || key === `recognitionDescribeRuns/${runId}/cancel`))
    ) {
      return null;
    }
    if (key.startsWith(`recognitionDescribeRuns/${runId}`) && !run.submitted) {
      return {
        status: 404,
        body: { code: 'fixture_run_not_accepted', message: 'Run has not been accepted', data: { status: 404 } },
      };
    }
    if (key === 'settings') {
      if (run.settingsDelayMs > 0) {
        await sleep(run.settingsDelayMs);
      }
      return { body: settings };
    }
    if (key === 'workbenchMedia') {
      return { body: { items, total: 10, totalPages: 1 } };
    }
    if (key === 'workbenchMediaDetail') {
      return { body: { details_by_media: {}, limit: 100, total: 0, truncated: false } };
    }
    if (key === 'recognitionMediaIdentities') {
      return { body: { identities_by_media: {}, data_source: 'local_projection' } };
    }
    if (key === 'recognitionClusters/top-unlabeled') {
      return {
        body: {
          clusters: [],
          limit: 20,
          total: 0,
          truncated: false,
          repair_pending: false,
          singleton_count: 0,
          has_clusters: false,
          data_source: 'local_projection',
          projection_status: 'available',
        },
      };
    }
    if (/^recognition(Suggestions|MergeSuggestions|NameSuggestions)$/.test(key)) {
      return { body: { suggestions: [], limit: 25, offset: 0, total: 0, data_source: 'local_projection' } };
    }
    if (key === 'recognitionBatchRuns') {
      return { body: { items: [], limit: 5 } };
    }
    if (key === 'recognitionDescribeHistory') {
      return { body: { items: [], total: 0, limit: 50, offset: 0, has_more: false } };
    }
    if (key === 'recognitionDescribeRuns' && method === 'POST') {
      run.submitted = true;
      return { body: runPayload(run) };
    }
    if (key === `recognitionDescribeRuns/${runId}/cancel` && method === 'POST') {
      run.cancelling = true;
      await new Promise((resolve) => {
        run.releaseCancel = resolve;
      });
      return { body: runPayload(run) };
    }
    if (key === `recognitionDescribeRuns/${runId}`) {
      return run.failPoll
        ? {
            status: 400,
            body: { code: 'fixture_poll_error', message: 'Offline fixture poll failed', data: { status: 400 } },
          }
        : { body: runPayload(run) };
    }
    if (key === `recognitionDescribeRuns/${runId}/items`) {
      return {
        body: {
          tenant_id: runPayload(run).tenant_id,
          run_id: runId,
          items: items.map((item, index) => ({
            media_id: item.id,
            status: index < run.completed ? 'completed' : 'queued',
            alt_text_draft: index < run.completed ? `Draft ${item.id}` : null,
            caption: null,
            provenance: null,
            tier: null,
            result_generation: 1,
            processing_ms: null,
            existing_alt: true,
            thumbnail_url: item.thumbnailUrl,
            thumbnail_srcset: item.thumbnailSrcset,
          })),
        },
      };
    }
    if (key === 'recognitionDescribeRuns') {
      return { body: { items: [], total: 0, next_offset: null } };
    }
    if (key === 'recognitionGpuStatus') {
      return {
        body: {
          gpu_state: {
            state: 'ready',
            instance_id: null,
            written_at: 1792872000,
            reason: null,
            since: null,
            intent: 'auto',
            intent_expires_at: null,
            intent_status: 'none',
            honoured_nonce: null,
            lease_expires_at: null,
            instance_running_since: null,
            last_transition_reason: 'unknown',
          },
          snapshot_age_seconds: 0,
          snapshot_fresh: true,
          intent: null,
          load: { has_work: run.submitted, written_at: 1792872000, fresh: true },
          server_time: '2026-10-24T20:00:00Z',
        },
      };
    }
    if (key === 'recognitionSyncHealth') {
      return {
        body: {
          breaker: { state: 'closed', base_url: origin, opened_at: null },
          outbox: { state: 'ok', pending: 0, failed: 0, dead_lettered: 0, oldest_age_seconds: 0 },
          conflicts: { open: 0 },
          replays: { failed: 0, source: 'fixture' },
          last_pull: { at: '2026-10-24T20:00:00Z', ok: true },
          warnings: [],
        },
      };
    }
    if (key === 'recognitionSyncStatus') {
      return {
        body: {
          last_snapshot_version: 1,
          last_synced_at: '2026-10-24T20:00:00Z',
          is_stale: false,
          sync_health: 'healthy',
          last_sync_result: 'ok',
          reclaimer: null,
        },
      };
    }
    return null;
  };
}

// Geometry of the outer Library owner and the inner MediaSelection groups it bounds.
const measureGeometry = (page) =>
  page.evaluate(() => {
    const rect = (element) => {
      if (!element) {
        return null;
      }
      const r = element.getBoundingClientRect();
      return {
        top: r.top,
        bottom: r.bottom,
        left: r.left,
        right: r.right,
        height: r.height,
        width: r.width,
        scrollHeight: element.scrollHeight,
        clientHeight: element.clientHeight,
        scrollWidth: element.scrollWidth,
        clientWidth: element.clientWidth,
      };
    };
    const library = document.querySelector('.acx-workbench__two-pane-library');
    const media = document.querySelector('.acx-media-selection');
    const libraryStyle = library ? getComputedStyle(library) : null;
    const strips = [...document.querySelectorAll('.acx-activity-status-strip')];
    const cta = [...document.querySelectorAll('button')].find((button) =>
      /^Describe (selected|\d+ selected)$/.test(button.textContent.trim()),
    );
    return {
      viewport: { width: innerWidth, height: innerHeight, scrollY },
      pageScrollWidth: document.documentElement.scrollWidth,
      layout: document.querySelector('.acx-workbench__two-pane')?.dataset.layout ?? null,
      library: rect(library),
      libraryContentBottom: library
        ? library.getBoundingClientRect().bottom -
          parseFloat(libraryStyle.paddingBottom) -
          parseFloat(libraryStyle.borderBottomWidth)
        : null,
      libraryOverflowY: libraryStyle?.overflowY ?? null,
      control: rect(document.querySelector('.acx-workbench__two-pane-control')),
      media: rect(media),
      availableHeight: media
        ? getComputedStyle(media).getPropertyValue('--acx-media-selection-available-height').trim()
        : '',
      toolbar: rect(document.querySelector('.acx-media-selection__toolbar')),
      actions: rect(document.querySelector('.acx-media-selection__actions')),
      rows: rect(document.querySelector('.acx-media-selection__rows')),
      rowsOverflowY: (() => {
        const rows = document.querySelector('.acx-media-selection__rows');
        return rows ? getComputedStyle(rows).overflowY : null;
      })(),
      pagination: rect(document.querySelector('.acx-media-selection__pagination-region')),
      cta: rect(cta),
      strips: strips.map((strip) => ({
        rect: rect(strip),
        kind: strip.dataset.activityKind,
        inLibrary: Boolean(strip.closest('.acx-workbench__two-pane-library')),
        inActionGroup: Boolean(strip.closest('.acx-media-selection__actions')),
        hiddenAncestor: strip.closest('[hidden]')?.className ?? null,
      })),
    };
  });

const inViewport = (r, vp) => r !== null && r.top >= -0.5 && r.bottom <= vp.height + 0.5 && r.height > 0;

const libraryChecks = (viewport, state, g, { expectStatus }) => {
  check(viewport, state, 'primary Describe action is in the viewport', inViewport(g.cta, viewport), g.cta);
  check(viewport, state, 'no horizontal page overflow', g.pageScrollWidth <= viewport.width, g.pageScrollWidth);
  check(
    viewport,
    state,
    'outer Library binds --acx-media-selection-available-height',
    g.availableHeight !== '',
    g.availableHeight,
  );
  check(
    viewport,
    state,
    'outer Library has no nested scroll surface',
    g.library !== null && g.library.scrollHeight - g.library.clientHeight <= 1,
    g.library && {
      scrollHeight: g.library.scrollHeight,
      clientHeight: g.library.clientHeight,
      overflowY: g.libraryOverflowY,
    },
  );
  check(
    viewport,
    state,
    'inner MediaSelection fits the remaining Library slot',
    g.media !== null && g.media.bottom <= g.libraryContentBottom + 0.5 && g.media.top >= g.library.top,
    { media: g.media, libraryContentBottom: g.libraryContentBottom },
  );
  check(viewport, state, 'action group is visible in the viewport', inViewport(g.actions, viewport), g.actions);
  check(viewport, state, 'pagination is visible in the viewport', inViewport(g.pagination, viewport), g.pagination);
  check(
    viewport,
    state,
    'only the tall rows scroll',
    g.rows !== null &&
      g.rowsOverflowY === 'auto' &&
      g.rows.scrollHeight > g.rows.clientHeight &&
      g.rows.clientHeight > 0,
    g.rows && { scrollHeight: g.rows.scrollHeight, clientHeight: g.rows.clientHeight, overflowY: g.rowsOverflowY },
  );
  observe(
    viewport,
    state,
    'rows scrollport keeps a 96px usability floor inside the bounded slot',
    'ACTION_PROGRESS inner density (toolbar/actions/pagination); coordinator-known narrow scrollport defect',
    g.rows !== null && g.rows.clientHeight >= 96,
    g.rows && {
      rowsClientHeight: g.rows.clientHeight,
      toolbar: g.toolbar?.height,
      actions: g.actions?.height,
      pagination: g.pagination?.height,
      slotBottom: g.libraryContentBottom,
      mediaTop: g.media?.top,
    },
  );
  if (expectStatus) {
    const [strip] = g.strips;
    check(
      viewport,
      state,
      'one shared run status is visible in the Library action group',
      g.strips.length === 1 &&
        strip.inLibrary &&
        strip.inActionGroup &&
        strip.hiddenAncestor === null &&
        inViewport(strip.rect, viewport),
      g.strips,
    );
  }
};

const screenshot = async (page, viewport, state) => {
  const file = `${viewport.width}-${state}.png`;
  const buffer = await page.screenshot({ path: path.join(out, file) });
  report.screenshots.push({ file, sha256: sha256(buffer) });
};

const measure = async (page, viewport, record, state, options = { expectStatus: true }) => {
  const g = await measureGeometry(page);
  record.measurements.push({ state, geometry: g });
  libraryChecks(viewport, state, g, options);
  await screenshot(page, viewport, state);
  return g;
};

const stripLocator = (page) => page.locator('.acx-workbench__two-pane-library .acx-activity-status-strip');
const stripKind = async (page) =>
  (await stripLocator(page).count()) === 1 ? stripLocator(page).getAttribute('data-activity-kind') : null;
const ctaLocator = (page) => page.getByRole('button', { name: /^Describe (selected|\d+ selected)$/ });
const cancelInLibrary = (page) =>
  page.locator('.acx-workbench__two-pane-library').getByRole('button', { name: 'Cancel run', exact: true });

const qualifyHost = async (page, viewport, record) => {
  const computed = await page.evaluate(() => {
    const body = getComputedStyle(document.body);
    const utility = document.querySelector('#acx-page-title');
    const hidden = utility && getComputedStyle(utility);
    const button = document.querySelector('.acx-media-selection button.button');
    const control = button && getComputedStyle(button);
    return {
      htmlClasses: document.documentElement.className,
      bodyClasses: document.body.className,
      fontFamily: body.fontFamily,
      fontSize: body.fontSize,
      nativeRoot: document.querySelectorAll(
        '#wpwrap #wpcontent #wpbody #wpbody-content > .wrap.alt-context-admin > #root.alt-context-workbench',
      ).length,
      stylesheets: [...document.querySelectorAll('link[rel="stylesheet"]')].map((link) => link.getAttribute('href')),
      screenReader: hidden && {
        width: hidden.width,
        height: hidden.height,
        position: hidden.position,
        clip: hidden.clip,
        clipPath: hidden.clipPath,
        overflow: hidden.overflow,
      },
      button: control && {
        fontFamily: control.fontFamily,
        fontSize: control.fontSize,
        minHeight: control.minHeight,
        lineHeight: control.lineHeight,
        padding: control.padding,
      },
    };
  });
  record.host = computed;
  check(
    viewport,
    'host',
    'verified WordPress cascade precedes candidate main.scss in native PHP shell',
    computed.htmlClasses === host.html_classes &&
      computed.bodyClasses === host.body_classes &&
      computed.nativeRoot === 1 &&
      JSON.stringify(computed.stylesheets) ===
        JSON.stringify([...hostAssets.map((asset) => asset.href), '/fixture.css']),
    computed,
  );
  check(
    viewport,
    'host',
    'actual WordPress body typography is 13px system type',
    computed.fontSize === '13px' && computed.fontFamily.includes('-apple-system'),
    computed,
  );
  check(
    viewport,
    'host',
    'WordPress screen-reader utility is visually hidden',
    computed.screenReader?.width === '1px' &&
      computed.screenReader?.position === 'absolute' &&
      computed.screenReader?.overflow === 'hidden' &&
      // Check the actual clipping mechanism: product heading typography can grow
      // the box while WordPress inset(50%) still clips its entire painted area.
      (computed.screenReader?.clipPath === 'inset(50%)' || computed.screenReader?.clip === 'rect(1px, 1px, 1px, 1px)'),
    computed.screenReader,
  );
};

const lifecycle = async (viewport, record) => {
  const run = {
    phase: 'queued',
    status: 'running',
    completed: 0,
    cancelling: false,
    failPoll: false,
    submitted: false,
    settingsDelayMs: 1500,
    releaseCancel: null,
  };
  const { context, page } = await newPage(viewport, record, makeTransport(run));
  const posts = () => record.requests.filter((r) => r.method === 'POST' && r.key === 'recognitionDescribeRuns').length;
  try {
    await page.goto(`${origin}/fixture#/workbench`);
    const last = page.getByRole('checkbox', { name: 'Select media item Tall media 10', exact: true });
    await last.waitFor({ state: 'attached' });
    await ctaLocator(page).waitFor({ state: 'attached' });
    await qualifyHost(page, viewport, record);

    check(
      viewport,
      'zero',
      'zero selection keeps a focusable aria-disabled primary',
      (await ctaLocator(page).getAttribute('aria-disabled')) === 'true' &&
        !(await ctaLocator(page).evaluate((e) => e.disabled)),
    );
    await measure(page, viewport, record, 'zero');
    await ctaLocator(page).focus();
    await page.keyboard.press('Enter');
    check(viewport, 'zero', 'guarded primary sends no POST', posts() === 0, posts());

    await page.getByRole('checkbox', { name: 'Select media item Tall media 1', exact: true }).click();
    await sleep(1700);
    run.settingsDelayMs = 0;
    check(
      viewport,
      'one',
      'one selection is ready',
      (await ctaLocator(page).textContent()).trim() === 'Describe 1 selected' &&
        (await ctaLocator(page).getAttribute('aria-disabled')) !== 'true',
    );
    await measure(page, viewport, record, 'one');

    await page.getByRole('checkbox', { name: 'Select all items on this page', exact: true }).click();
    check(
      viewport,
      'ten',
      'ten selection is ready',
      (await ctaLocator(page).textContent()).trim() === 'Describe 10 selected',
    );
    const ten = await measure(page, viewport, record, 'ten');

    await last.focus();
    const focus = await last.evaluate((element) => {
      const rows = element.closest('.acx-media-selection__rows') ?? document.scrollingElement;
      const r = element.getBoundingClientRect();
      const rr = rows.getBoundingClientRect();
      return {
        focused: document.activeElement === element,
        top: r.top,
        bottom: r.bottom,
        rowsTop: rr.top,
        rowsBottom: rr.bottom,
        inRowsRegion: Boolean(element.closest('.acx-media-selection__rows')),
      };
    });
    check(
      viewport,
      'row10-focus',
      'focused row 10 is visible inside the rows region, not under actions or pagination',
      focus.focused &&
        focus.inRowsRegion &&
        focus.top >= focus.rowsTop - 0.5 &&
        focus.bottom <= focus.rowsBottom + 0.5 &&
        focus.top >= 0 &&
        focus.bottom <= viewport.height,
      focus,
    );
    const focused = await measure(page, viewport, record, 'row10-focus');
    check(
      viewport,
      'row10-focus',
      'action group and pagination stay put while rows scroll',
      ten.actions !== null &&
        focused.actions !== null &&
        Math.abs(ten.actions.top - focused.actions.top) <= 1 &&
        Math.abs(ten.pagination.top - focused.pagination.top) <= 1,
      {
        before: { actions: ten.actions, pagination: ten.pagination },
        after: { actions: focused.actions, pagination: focused.pagination },
      },
    );
    await page.keyboard.press('Tab');
    const preview = await page.evaluate(() => {
      const active = document.activeElement;
      const rows = active?.closest('.acx-media-selection__rows');
      const r = active?.getBoundingClientRect();
      const rr = rows?.getBoundingClientRect();
      return {
        tag: active?.tagName,
        label: active?.getAttribute('aria-label'),
        rect: r && { top: r.top, bottom: r.bottom, left: r.left, right: r.right, height: r.height, width: r.width },
        rows: rr && { top: rr.top, bottom: rr.bottom, left: rr.left, right: rr.right },
      };
    });
    check(
      viewport,
      'row10-preview-focus',
      'Tab reaches the whole row 10 preview link inside the rows viewport',
      preview.tag === 'A' &&
        preview.label === 'Edit Tall media 10' &&
        preview.rows &&
        preview.rect &&
        preview.rect.height > 0 &&
        preview.rect.width > 0 &&
        preview.rect.top >= preview.rows.top - 0.5 &&
        preview.rect.bottom <= preview.rows.bottom + 0.5 &&
        preview.rect.left >= preview.rows.left - 0.5 &&
        preview.rect.right <= preview.rows.right + 0.5 &&
        preview.rect.top >= 0 &&
        preview.rect.bottom <= viewport.height,
      preview,
    );
    const previewFocused = await measure(page, viewport, record, 'row10-preview-focus');
    check(
      viewport,
      'row10-preview-focus',
      'actions and pagination stay fixed through checkbox-to-preview keyboard traversal',
      ten.actions !== null &&
        previewFocused.actions !== null &&
        ten.pagination !== null &&
        previewFocused.pagination !== null &&
        Math.abs(ten.actions.top - previewFocused.actions.top) <= 1 &&
        Math.abs(ten.pagination.top - previewFocused.pagination.top) <= 1,
      {
        before: { actions: ten.actions, pagination: ten.pagination },
        after: { actions: previewFocused.actions, pagination: previewFocused.pagination },
      },
    );
    const previews = await page.locator('.acx-media-selection__rows img').evaluateAll((images) =>
      images.map((image) => {
        const rect = image.getBoundingClientRect();
        return { width: rect.width, height: rect.height };
      }),
    );
    check(
      viewport,
      'row10-preview-focus',
      'all ten previews remain readable within the 80..300px range',
      previews.length === 10 &&
        previews.every((rect) => rect.width >= 80 && rect.height >= 80 && rect.width <= 300 && rect.height <= 300),
      previews,
    );

    await ctaLocator(page).click();
    await waitUntil(
      async () => (await stripLocator(page).count()) === 1 && (await cancelInLibrary(page).count()) === 1,
    );
    check(viewport, 'queued', 'Cancel run is accessible once in Library', (await cancelInLibrary(page).count()) === 1);
    check(
      viewport,
      'queued',
      'exactly one Cancel run control exists',
      (await page.getByRole('button', { name: 'Cancel run', exact: true }).count()) === 1,
    );
    await measure(page, viewport, record, 'queued');

    run.phase = 'warming';
    await waitUntil(async () => (await stripKind(page)) === 'warming');
    check(
      viewport,
      'warming',
      'warming status and Cancel stay visible in Library',
      (await stripKind(page)) === 'warming' && (await cancelInLibrary(page).count()) === 1,
    );
    await measure(page, viewport, record, 'warming');

    run.phase = 'describing';
    await waitUntil(async () => (await stripKind(page)) === 'describing');
    check(
      viewport,
      'describing',
      'describing status and Cancel stay visible in Library',
      (await stripKind(page)) === 'describing' && (await cancelInLibrary(page).count()) === 1,
    );
    await measure(page, viewport, record, 'describing');
    check(viewport, 'describing', 'one submit only', posts() === 1, posts());

    await page.reload();
    await last.waitFor({ state: 'attached' });
    await waitUntil(async () => (await cancelInLibrary(page).count()) === 1);
    check(
      viewport,
      'reload',
      'reload resumes the run with Cancel in Library',
      (await cancelInLibrary(page).count()) === 1,
    );
    check(viewport, 'reload', 'reload never resubmits', posts() === 1, posts());
    await measure(page, viewport, record, 'reload');

    run.failPoll = true;
    const retry = () =>
      page
        .locator('.acx-workbench__two-pane-library .acx-activity-status-strip')
        .getByRole('button', { name: 'Retry', exact: true });
    await waitUntil(async () => (await retry().count()) === 1);
    check(viewport, 'poll-error', 'poll error keeps Retry in the Library status', (await retry().count()) === 1);
    await measure(page, viewport, record, 'poll-error');
    run.failPoll = false;
    if ((await retry().count()) === 1) {
      await retry().click();
    }
    await waitUntil(async () => (await cancelInLibrary(page).count()) === 1);
    if ((await cancelInLibrary(page).count()) === 1) {
      await cancelInLibrary(page).click();
      await page.getByRole('dialog').getByRole('button', { name: 'Cancel run', exact: true }).click();
      const cancels = () => record.requests.filter((r) => r.key.endsWith('/cancel')).length;
      await waitUntil(async () => cancels() === 1);
      await sleep(300);
      check(viewport, 'cancelling', 'confirmed Cancel sends one cancel request', cancels() === 1, cancels());
      check(
        viewport,
        'cancelling',
        'run status stays visible in Library while cancel is pending, with no second Cancel control',
        (await stripLocator(page).count()) === 1 &&
          (await page.getByRole('button', { name: 'Cancel run', exact: true }).count()) <= 1,
        { kind: await stripKind(page) },
      );
      const pendingCancelLabel = await page
        .locator('.acx-workbench__two-pane-library')
        .getByRole('button', { name: 'Cancelling…', exact: true })
        .count();
      observe(
        viewport,
        'cancelling',
        'pending cancel is labelled Cancelling…',
        'GPU_STATUS ActivityStatusStrip/useActivityStatus (onCancel is null while isCancelling)',
        pendingCancelLabel === 1,
        { pendingCancelLabel, headline: await stripLocator(page).textContent() },
      );
      await measure(page, viewport, record, 'cancelling');
    } else {
      check(viewport, 'cancelling', 'cancel flow reachable', false, 'No accessible Cancel run in Library');
    }

    // The authoritative cancel acknowledgement is terminal evidence for this run.
    run.status = 'cancelled';
    run.phase = 'cancelled';
    if (run.releaseCancel) {
      run.releaseCancel();
    }
    await waitUntil(async () => (await stripKind(page)) === 'failed');
    check(
      viewport,
      'cancelled',
      'cancelled terminal state stays visible in Library',
      (await stripKind(page)) === 'failed' && /Run cancelled/.test((await stripLocator(page).textContent()) ?? ''),
      await stripLocator(page)
        .textContent()
        .catch(() => null),
    );
    await measure(page, viewport, record, 'cancelled');
    check(viewport, 'cancelled', 'single submit preserved', posts() === 1, posts());
    check(
      viewport,
      'cancelled',
      'single cancellation executed',
      record.requests.filter((r) => r.key.endsWith('/cancel')).length === 1,
    );
  } catch (error) {
    check(viewport, 'lifecycle', 'lifecycle completed without a runner exception', false, String(error));
    await screenshot(page, viewport, 'lifecycle-error');
  } finally {
    await context.close();
  }
};

// A separate run that completes: its terminal Review drafts link must stay in Library.
const completedRun = async (viewport, record) => {
  const run = {
    phase: 'describing',
    status: 'running',
    completed: 0,
    cancelling: false,
    failPoll: false,
    submitted: false,
    settingsDelayMs: 0,
  };
  const { context, page } = await newPage(viewport, record, makeTransport(run));
  const posts = () => record.requests.filter((r) => r.method === 'POST' && r.key === 'recognitionDescribeRuns').length;
  try {
    const before = posts();
    await page.goto(`${origin}/terminal#/workbench`);
    await page
      .getByRole('checkbox', { name: 'Select media item Tall media 10', exact: true })
      .waitFor({ state: 'attached' });
    await page.getByRole('checkbox', { name: 'Select all items on this page', exact: true }).click();
    await waitUntil(async () => (await ctaLocator(page).textContent()).trim() === 'Describe 10 selected');
    await ctaLocator(page).click();
    await waitUntil(async () => (await stripKind(page)) === 'describing');
    run.status = 'completed';
    run.phase = 'complete';
    run.completed = 10;
    const review = () =>
      page.locator('.acx-workbench__two-pane-library').getByRole('link', { name: 'Review 10 drafts', exact: true });
    await waitUntil(async () => (await review().count()) === 1, 10000);
    check(
      viewport,
      'terminal',
      'terminal Review drafts link is visible in Library for the actual run',
      (await review().count()) === 1 && (await review().getAttribute('href')).includes(runId),
      await stripLocator(page)
        .textContent()
        .catch(() => null),
    );
    await measure(page, viewport, record, 'terminal');
    check(viewport, 'terminal', 'completed run was submitted once', posts() - before === 1, posts() - before);
    await review().click();
    await waitUntil(async () => (await page.locator('.acx-media-selection__rows tbody tr').count()) === 10);
    const draftFilter = {
      rows: await page.locator('.acx-media-selection__rows tbody tr').count(),
      posts: posts() - before,
      url: page.url(),
      runLabel: await page.locator('.acx-media-selection__run-filter').textContent(),
      hasDraft: await page.getByRole('checkbox', { name: 'Has draft', exact: true }).getAttribute('aria-checked'),
      itemRequests: record.requests.filter(
        (request) => request.method === 'GET' && request.key === `recognitionDescribeRuns/${runId}/items`,
      ).length,
    };
    const filterParams = new URLSearchParams(new URL(draftFilter.url).hash.split('?')[1] ?? '');
    check(
      viewport,
      'terminal-filter',
      'real terminal draft filter shows all ten accepted items without resubmission',
      draftFilter.rows === 10 &&
        draftFilter.posts === 1 &&
        draftFilter.runLabel.includes(runId) &&
        draftFilter.hasDraft === 'true' &&
        draftFilter.itemRequests > 0 &&
        filterParams.get('run') === runId &&
        filterParams.get('hasDraft') === '1',
      draftFilter,
    );
    await measure(page, viewport, record, 'terminal-filter');
  } catch (error) {
    check(viewport, 'terminal', 'completed-run flow finished without a runner exception', false, String(error));
    await screenshot(page, viewport, 'terminal-error');
  } finally {
    await context.close();
  }
};

const searchFocus = (page) =>
  page.evaluate(() => {
    const search = document.getElementById('acx-media-search');
    return {
      focused: search !== null && document.activeElement === search,
      hiddenAncestor: Boolean(search?.closest('[hidden]')),
      activeElement: document.activeElement?.outerHTML.slice(0, 160) ?? null,
      panes: document.querySelector('.acx-workbench__two-pane')?.dataset.panes ?? null,
      hash: location.hash,
    };
  });

const reopenAndFocus = async (viewport, record) => {
  const run = {
    phase: 'queued',
    status: 'running',
    completed: 0,
    cancelling: false,
    failPoll: false,
    submitted: false,
    settingsDelayMs: 0,
  };
  const { context, page } = await newPage(viewport, record, makeTransport(run));
  const openCollapsed = async () => {
    await page.goto(`${origin}/reopen#/workbench?panes=library-collapsed`);
    await page.waitForFunction(
      () => document.querySelector('.acx-workbench__two-pane')?.dataset.panes === 'library-collapsed',
    );
    return page.getByTestId('workbench-two-pane-control').getByRole('link', { name: 'Go to Scan', exact: true });
  };
  try {
    for (const mode of ['pointer', 'keyboard']) {
      const link = await openCollapsed();
      check(
        viewport,
        `reopen-${mode}`,
        'precondition Library is collapsed',
        (await page.getByRole('region', { name: 'Library', exact: true }).count()) === 0,
      );
      if (mode === 'pointer') {
        await link.click();
      } else {
        await link.focus();
        await page.keyboard.press('Enter');
      }
      const result = await waitUntil(async () => {
        const state = await searchFocus(page);
        return state.focused ? state : null;
      }, 3000);
      const final = result ?? (await searchFocus(page));
      check(
        viewport,
        `reopen-${mode}`,
        'empty next step reopens Library through ?panes= and focuses its real search',
        final.focused && !final.hiddenAncestor && final.panes === 'both' && !final.hash.includes('panes='),
        final,
      );
      await screenshot(page, viewport, `reopen-${mode}`);
    }

    await openCollapsed();
    const modifier = await page.evaluate(() => {
      const link = [...document.querySelectorAll('a')].find((a) => a.textContent.trim() === 'Go to Scan');
      const before = document.querySelector('.acx-workbench__two-pane')?.dataset.panes;
      let handlerPrevented = null;
      // Document bubble runs after React's root listener: read its decision, then stop the
      // synthetic navigation so this page stays on the collapsed state for inspection.
      document.addEventListener(
        'click',
        (event) => {
          handlerPrevented = event.defaultPrevented;
          event.preventDefault();
        },
        { once: true },
      );
      link.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, ctrlKey: true, button: 0 }));
      return { before, handlerPrevented };
    });
    await sleep(300);
    const afterModifier = await searchFocus(page);
    check(
      viewport,
      'reopen-modifier',
      'modifier activation keeps the link route fallback and does not force focus',
      modifier.handlerPrevented === false && afterModifier.panes === 'library-collapsed' && !afterModifier.focused,
      { modifier, afterModifier },
    );

    // Completed request must not re-fire on later pane changes; splitter keeps its own focus.
    const link = await openCollapsed();
    await link.click();
    await waitUntil(async () => (await searchFocus(page)).focused, 3000);
    const splitter = page.getByRole('separator');
    await splitter.focus();
    if (viewport.width <= 719) {
      check(
        viewport,
        'splitter',
        'stacked splitter is a section toggle',
        (await splitter.getAttribute('data-mode')) === 'section-toggle',
      );
    } else {
      const before = Number(await splitter.getAttribute('aria-valuenow'));
      await page.keyboard.press('ArrowRight');
      check(
        viewport,
        'splitter',
        'keyboard resize preserved with focus on splitter',
        Number(await splitter.getAttribute('aria-valuenow')) === before + 5 &&
          (await splitter.evaluate((e) => document.activeElement === e)),
      );
    }
    const cycle = [];
    for (const next of ['control-collapsed', 'library-collapsed', 'both']) {
      await page.keyboard.press('Enter');
      await page.waitForFunction(
        (expected) => document.querySelector('.acx-workbench__two-pane')?.dataset.panes === expected,
        next,
      );
      await sleep(150);
      cycle.push({ panes: next, splitterFocused: await splitter.evaluate((e) => document.activeElement === e) });
    }
    check(
      viewport,
      'splitter',
      'pane toggles keep focus on the splitter (no stale search focus)',
      cycle.every((step) => step.splitterFocused),
      cycle,
    );

    const other = viewport.width <= 719 ? { width: 1440, height: 1000 } : { width: 719, height: 960 };
    await page.setViewportSize(other);
    await sleep(200);
    const layout = await page.locator('.acx-workbench__two-pane').getAttribute('data-layout');
    check(
      viewport,
      'reflow',
      'layout responds to viewport change',
      layout === (other.width <= 719 ? 'stacked' : 'side-by-side'),
      layout,
    );
    const reflowed = await measureGeometry(page);
    check(
      viewport,
      'reflow',
      'no horizontal page overflow after reflow',
      reflowed.pageScrollWidth <= other.width,
      reflowed.pageScrollWidth,
    );
  } catch (error) {
    check(viewport, 'reopen', 'focus/reflow flow completed without a runner exception', false, String(error));
    await screenshot(page, viewport, 'reopen-error');
  } finally {
    await context.close();
  }
};

try {
  for (const viewport of VIEWPORTS) {
    const record = { viewport, errors: [], requests: [], measurements: [] };
    report.viewports.push(record);
    await lifecycle(viewport, record);
    await completedRun(viewport, record);
    await reopenAndFocus(viewport, record);
    check(
      viewport,
      'all',
      'no runtime errors or unmocked/external requests',
      record.errors.length === 0,
      record.errors,
    );
  }
} finally {
  await browser.close();
}

report.status = preflight.pass && report.checks.every((c) => c.pass) ? 'PASS' : 'FAIL';
report.counts = {
  passed: report.checks.filter((c) => c.pass).length,
  failed: report.checks.filter((c) => !c.pass).length,
  observations_failed: report.observations.filter((o) => !o.pass).length,
  measured_states: report.viewports.reduce((n, v) => n + v.measurements.length, 0),
  screenshots: report.screenshots.length,
};
await fs.writeFile(path.join(out, 'results.json'), JSON.stringify(report, null, 2) + '\n');
console.log(
  JSON.stringify(
    {
      label,
      status: report.status,
      preflight: preflight.pass,
      counts: report.counts,
      failures: report.checks.filter((c) => !c.pass).map((c) => `${c.viewport} ${c.state}: ${c.name}`),
      peer_observations_failed: report.observations
        .filter((o) => !o.pass)
        .map((o) => `${o.viewport} ${o.state}: ${o.name}`),
    },
    null,
    2,
  ),
);
process.exitCode = report.status === 'PASS' ? 0 : 1;
