// UXREC-1 WB_CONTROL actual-browser acceptance.
// Bundles the real WorkbenchPage provider tree (entry.tsx) and compiled main.scss from the
// tree under test, intercepts only HTTP transport with producer-shaped data, and drives
// headless Chromium. No component, hook, guard or style is substituted.
//
// node acceptance.mjs <source-root> <label> <out-dir>
import { createHash } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import console from 'node:console';
import { setTimeout as sleep } from 'node:timers/promises';
import { URL, fileURLToPath, pathToFileURL } from 'node:url';
// Browser globals below are only referenced inside page.evaluate/addInitScript callbacks.
/* global window, document, location, getComputedStyle, innerWidth, innerHeight, scrollY, MouseEvent */

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

const preflight = { checks: [] };
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
    const validate = new Ajv({ allErrors: true }).compile(JSON.parse(schema));
    for (const run of [
      { phase: 'queued', status: 'running', completed: 0, cancelling: false },
      { phase: 'warming', status: 'running', completed: 0, cancelling: false },
      { phase: 'describing', status: 'running', completed: 0, cancelling: false },
      { phase: 'describing', status: 'running', completed: 0, cancelling: true },
      { phase: 'cancelled', status: 'cancelled', completed: 0, cancelling: true },
      { phase: 'complete', status: 'completed', completed: 10, cancelling: false },
    ]) {
      preflight.checks.push({
        name: `run payload ${run.phase}/${run.status}/cancel=${run.cancelling} matches shared schema`,
        pass: validate(runPayload(run)),
        errors: validate.errors ?? null,
      });
    }
  }
  preflight.pass = preflight.checks.every((check) => check.pass);
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
  '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
  '<link rel="stylesheet" href="/fixture.css"><div id="root" class="acx-admin"></div><script type="module" src="/fixture.js"></script></html>';

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
const browser = await chromium.launch({ executablePath, headless: true, args: ['--no-sandbox'] });
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
    if (!url.pathname.startsWith('/mock/')) {
      return route.fulfill({ contentType: 'text/html', body: html });
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

const makeTransport = (run) => async (key, method) => {
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
  if (key === `recognitionDescribeRuns/${runId}/cancel`) {
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
        run_id: runId,
        items: items.map((item) => ({
          media_id: item.id,
          status: run.completed ? 'completed' : 'queued',
          alt_text_draft: run.completed ? `Draft ${item.id}` : null,
          caption: null,
          provenance: null,
          tier: null,
          result_generation: 1,
          existing_alt: true,
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
