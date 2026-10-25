import { build, createServer } from 'vite';
import { chromium, expect } from '@playwright/test';
import Ajv from 'ajv';
import { createHash } from 'node:crypto';
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { URL, URLSearchParams } from 'node:url';
import process from 'node:process';
import console from 'node:console';
import { setTimeout } from 'node:timers';

const stage = process.env.ACCEPTANCE_STAGE ?? 'GREEN';
const artifacts = path.resolve(process.env.ACCEPTANCE_OUT ?? `../../source3-evidence/browser-${stage}`);
await mkdir(artifacts, { recursive: true });
const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');
// Frozen coordinator input, including native PHP shell with root-ID substitution
// only. Core bytes are served in place, never copied into the source/artifact tree.
const hostManifestPath = process.env.UXREC_HOST_INPUTS;
const hostAssets = new Map();
let host;
try {
  if (!hostManifestPath) {
    throw new Error('UXREC_HOST_INPUTS must name the pinned WordPress host manifest');
  }
  const bytes = await readFile(hostManifestPath);
  host = JSON.parse(bytes.toString('utf8'));
  if (
    host.wordpress_version !== '7.1.3' ||
    host.html_classes !== 'wp-toolbar' ||
    !host.body_classes?.includes('wp-admin wp-core-ui') ||
    !host.body_classes?.includes('admin-bar') ||
    !host.provenance ||
    host.assets?.length !== 27 ||
    !host.root_html?.includes('class="wrap alt-context-admin"') ||
    !host.root_html?.includes('id="root" class="alt-context-workbench"') ||
    !host.root_html?.includes('id="wpbody-content"') ||
    !host.root_html?.includes('class="screen-reader-text"')
  ) {
    throw new Error('Incomplete WordPress host markers');
  }
  if (sha256(bytes) !== '0ca7ab4bbbb08f9c79e5573a66f3ef4b6c4c8c62dc554e1ff056edd288b9ce6a') {
    throw new Error('Pinned WordPress host manifest digest mismatch');
  }
  for (const [index, asset] of host.assets.entries()) {
    const css = await readFile(asset.path);
    if (sha256(css) !== asset.sha256) {
      throw new Error(`WordPress host asset digest mismatch: ${asset.path}`);
    }
    hostAssets.set(`/acx-host/${index}.css`, css);
  }
} catch (error) {
  await writeFile(
    path.join(artifacts, 'geometry.json'),
    JSON.stringify({ stage, verdict: 'FAIL', browser_assertions_executed: 0, host_failure: String(error) }, null, 2) +
      '\n',
  );
  throw error;
}
// TEST-22: record the actual source combination exercised, without inventing a
// merged commit identity for this scoped native assembly.
const sourceTupleFiles = [
  'apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx',
  'apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/MediaSelection.actionSurface.test.tsx',
  'apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/action-progress-browser/acceptance.mjs',
  'apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/action-progress-browser/fixture.tsx',
  'apps/prototype-wp-alt-context/js/admin/styles/components/_media-selection.scss',
  'apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx',
  'apps/prototype-wp-alt-context/js/admin/pages/__tests__/WorkbenchPage.control-composition.test.tsx',
  'apps/prototype-wp-alt-context/js/admin/pages/__tests__/WorkbenchPage.library-lifecycle.test.tsx',
  'apps/prototype-wp-alt-context/js/admin/pages/__tests__/fixtures/wb-control/acceptance.mjs',
  'apps/prototype-wp-alt-context/js/admin/pages/__tests__/fixtures/wb-control/entry.tsx',
  'apps/prototype-wp-alt-context/js/admin/pages/__tests__/fixtures/wb-control/index.html',
  'apps/prototype-wp-alt-context/js/admin/pages/workbench/ScanTabContent.tsx',
  'apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/RecognitionPolicyControl.test.tsx',
  'apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/ScanTabContent.control-composition.test.tsx',
  'apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/WorkbenchPage.integration.test.tsx',
  'apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/WorkbenchPage.test.tsx',
  'apps/prototype-wp-alt-context/js/admin/styles/components/_workbench.scss',
];
const sourceTuple = {
  integration_base: 'aacec8779fd8bb9e70758e0fbc73a6f6a81b1ccd',
  action_original_source2_tip: '70aa52f3ad7e976d7fb0bdfb7aacbce4875813b2',
  frozen_wb_source2_tip: '67f0d037df194ce954b9eb7a8560641d0d914323',
  actual_files: Object.fromEntries(
    await Promise.all(
      sourceTupleFiles.map(async (file) => [file, sha256(await readFile(path.resolve('../..', file)))]),
    ),
  ),
};
const bundle = path.join(artifacts, 'bundle');
const fixtureEntry = 'js/admin/pages/workbench/__tests__/action-progress-browser/fixture.tsx';
// Same build as `npm run build`: the app's own config in production mode, only the
// entry and outDir replaced. A build.lib bundle skips Vite's process.env substitution.
await build({
  configFile: path.resolve('vite.config.ts'),
  mode: 'production',
  logLevel: 'error',
  build: { outDir: bundle, emptyOutDir: true, rollupOptions: { input: path.resolve(fixtureEntry) } },
});
const manifest = JSON.parse(await readFile(path.join(bundle, '.vite/manifest.json'), 'utf8'));
// ViteManifest::entry_assets: entry chunk plus recursively imported CSS, imports first.
const collectCss = (key, visited = new Set(), seen = new Set()) => {
  if (visited.has(key) || manifest[key] === undefined) {
    return [];
  }
  visited.add(key);
  const css = (manifest[key].imports ?? []).flatMap((name) => collectCss(name, visited, seen));
  for (const file of manifest[key].css ?? []) {
    if (!seen.has(file)) {
      seen.add(file);
      css.push(file);
    }
  }
  return css;
};
const origin = 'https://action-progress-fixture.invalid';
// The bundle is served from the site origin, like the plugin's enqueued module assets.
const appBase = `${origin}/acx-fixture/`;
const runId = '6d3f1c2a-8b4e-4f7a-9c5d-2e1b0a9f8e7d';
const endpointNames = [
  'settings',
  'workbenchMedia',
  'workbenchMediaDetail',
  'recognitionMediaIdentities',
  'recognitionDescribeRuns',
  'recognitionDescribeHistory',
  'recognitionGpuStatus',
  'recognitionSyncHealth',
  'recognitionSyncStatus',
  'recognitionBatchRuns',
  'recognitionJobs',
  'recognitionClusters',
  'recognitionSyncTrigger',
  'recognitionSuggestions',
  'recognitionMergeSuggestions',
  'recognitionNameSuggestions',
];
// TenantIdentity::derive_site_url_tenant_id for the fixture site URL.
const deriveSiteTenantId = (siteUrl) => {
  const hash = createHash('sha1')
    .update(`acx-site-tenant:${siteUrl.toLowerCase().replace(/\/+$/, '')}`)
    .digest('hex');
  const timeHi = (parseInt(hash.slice(12, 16), 16) & 0x0fff) | 0x5000;
  const clockSeq = (parseInt(hash.slice(16, 20), 16) & 0x3fff) | 0x8000;
  return `${hash.slice(0, 8)}-${hash.slice(8, 12)}-${timeHi.toString(16).padStart(4, '0')}-${clockSeq.toString(16).padStart(4, '0')}-${hash.slice(20, 32)}`;
};
const tenantId = deriveSiteTenantId(origin);
const config = {
  nonce: 'offline-fixture',
  ajaxUrl: '/fixture-api/ajax',
  tenant_id: tenantId,
  recognitionSource: 'service',
  effectiveTargetUrl: origin,
  recognitionPolicy: { enabled: false, canManage: false },
  endpoints: Object.fromEntries(endpointNames.map((name) => [name, `${origin}/fixture-api/${name}`])),
};
const entry = manifest[fixtureEntry];
await writeFile(
  path.join(bundle, 'index.html'),
  `<!doctype html><html lang="en" class="${host.html_classes}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ACTION_PROGRESS</title>${[...hostAssets.keys()].map((file) => `<link rel="stylesheet" href="${file}">`).join('')}${collectCss(
    fixtureEntry,
  )
    .map((file) => `<link rel="stylesheet" href="./${file}">`)
    .join(
      '',
    )}<script type="application/json" id="acx-fixture-config">${JSON.stringify(config).replaceAll('<', '\\u003c')}</script></head><body class="${host.body_classes}">${host.root_html}<script type="module" src="./${entry?.file}"></script></body></html>`,
);
const url = `${appBase}index.html#/workbench`;
const contentTypes = {
  '.html': 'text/html',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
};

const image =
  'data:image/svg+xml,' +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300"><rect width="300" height="300" fill="#dde5ed"/><circle cx="150" cy="130" r="65" fill="#728da5"/><text x="85" y="250" font-size="22">Test media</text></svg>',
  );
const items = Array.from({ length: 10 }, (_, i) => ({
  id: i + 1,
  title: `Tall fixture photo ${i + 1}`,
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
const gpu = {
  gpu_state: {
    state: 'ready',
    instance_id: null,
    written_at: 1792843200,
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
  load: { has_work: false, written_at: 1792843200, fresh: true },
  server_time: '2026-10-24T12:00:00Z',
};

// Lowercase UUID: the stored run-id regex in class-describe-controller.php, and the
// tenant shape TenantIdentity::resolve publishes.
const LOWERCASE_UUID = /^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/;
const IDEMPOTENCY_KEY = /^[A-Za-z0-9_-]{16,128}$/;
const json = (status, body) => ({ status, body });
const wpError = (status, code, message) => json(status, { code, message, data: { status } });

// HTTP transport/data only, typed by registered method and route. Returns null for
// an unmocked route so callers fail closed.
const createTransport = () => {
  const state = {
    phase: 'queued',
    status: 'pending',
    completed: 0,
    failPoll: false,
    cancelRequested: false,
    settingsMode: 'off',
    submitted: null,
    cancelHold: null,
    holdCancel: false,
  };
  const run = () => ({
    tenant_id: tenantId,
    run_id: runId,
    status: state.status,
    phase: state.phase,
    completed: state.completed,
    failed: 0,
    skipped: 0,
    total: state.submitted.mediaIds.length,
    cancel_requested: state.cancelRequested,
    eta_seconds: null,
    gpu_state: 'ready',
    recognition_enabled: false,
  });
  const routes = new Map([
    [
      'GET settings',
      async () => {
        if (state.settingsMode === 'pending') {
          await new Promise((resolve) => setTimeout(resolve, 1500));
        }
        return json(200, { recognition_enabled: state.settingsMode === 'on', development_face_scan_available: false });
      },
    ],
    [
      'GET workbenchMedia',
      ({ query }) => {
        const visible = query.get('status') === 'missing' || query.get('search') === 'no-matching-fixture' ? [] : items;
        return json(200, { items: visible, total: visible.length, totalPages: 1 });
      },
    ],
    ['GET workbenchMediaDetail', () => json(200, { details_by_media: {}, limit: 100, total: 10, truncated: false })],
    ['GET recognitionMediaIdentities', () => json(200, { identities_by_media: {}, data_source: 'local_projection' })],
    ['GET recognitionDescribeHistory', () => json(200, { items: [], total: 0, limit: 50, offset: 0, has_more: false })],
    ['GET recognitionGpuStatus', () => json(200, gpu)],
    ['GET recognitionBatchRuns', () => json(200, { items: [] })],
    [
      'GET recognitionClusters/top-unlabeled',
      () =>
        json(200, {
          clusters: [],
          limit: 20,
          total: 0,
          truncated: false,
          repair_pending: false,
          singleton_count: 0,
          has_clusters: false,
          data_source: 'local_projection',
          projection_status: 'available',
        }),
    ],
    ...['recognitionSuggestions', 'recognitionMergeSuggestions', 'recognitionNameSuggestions'].map((name) => [
      `GET ${name}`,
      () => json(200, { suggestions: [], limit: 25, offset: 0, total: 0, data_source: 'local_projection' }),
    ]),
    [
      'GET recognitionSyncHealth',
      () =>
        json(200, {
          breaker: { state: 'closed', base_url: origin, opened_at: null },
          outbox: { state: 'ok', pending: 0, failed: 0, dead_lettered: 0, oldest_age_seconds: 0 },
          conflicts: { open: 0 },
          replays: { failed: 0, source: 'fixture' },
          last_pull: { at: '2026-10-24T12:00:00Z', ok: true },
          warnings: [],
        }),
    ],
    [
      'GET recognitionSyncStatus',
      () =>
        json(200, {
          last_snapshot_version: 1,
          last_synced_at: '2026-10-24T12:00:00Z',
          is_stale: false,
          sync_health: 'healthy',
          last_sync_result: 'ok',
          reclaimer: null,
        }),
    ],
    // submit_describe_run: validated key and ids; the backend answers 202 with the new run.
    [
      'POST recognitionDescribeRuns',
      ({ body }) => {
        if (typeof body?.idempotency_key !== 'string' || !IDEMPOTENCY_KEY.test(body.idempotency_key)) {
          return wpError(400, 'invalid_idempotency_key', 'A valid idempotency_key is required.');
        }
        const mediaIds = Array.isArray(body.media_ids) ? [...new Set(body.media_ids)] : [];
        if (mediaIds.length === 0 || !mediaIds.every((id) => Number.isSafeInteger(id) && id > 0)) {
          return wpError(400, 'missing_media_ids', 'Please provide one or more media IDs to describe.');
        }
        state.submitted = { mediaIds, createdAt: Math.floor(Date.now() / 1000) };
        return json(202, run());
      },
    ],
    // list_describe_runs_for_media: local accepted-run directory, newest first.
    [
      'GET recognitionDescribeRuns',
      ({ query }) => {
        const wanted = query.getAll('media_ids[]').map(Number);
        if (wanted.length === 0 || wanted.length > 100 || !wanted.every((id) => Number.isSafeInteger(id) && id > 0)) {
          return wpError(400, 'invalid_media_ids', 'Provide between 1 and 100 attachment IDs.');
        }
        const limit = Math.min(10, Math.max(1, Number(query.get('limit') ?? 5)));
        const offset = Math.max(0, Number(query.get('offset') ?? 0));
        const mediaIds = wanted.filter((id) => state.submitted?.mediaIds.includes(id));
        const records =
          mediaIds.length > 0 ? [{ run_id: runId, created_at: state.submitted.createdAt, media_ids: mediaIds }] : [];
        return json(200, {
          items: records.slice(offset, offset + limit),
          total: records.length,
          next_offset: offset + limit < records.length ? offset + limit : null,
        });
      },
    ],
    [
      `GET recognitionDescribeRuns/${runId}`,
      () => (state.failPoll ? wpError(400, 'fixture_poll_error', 'Offline fixture poll failed') : json(200, run())),
    ],
    [
      `POST recognitionDescribeRuns/${runId}/cancel`,
      async () => {
        state.cancelRequested = true;
        if (state.holdCancel) {
          await new Promise((resolve) => {
            state.cancelHold = resolve;
          });
        }
        return json(200, run());
      },
    ],
    // Backend _run_items_response rows, annotated by WP get_describe_run_items.
    [
      `GET recognitionDescribeRuns/${runId}/items`,
      () =>
        json(200, {
          tenant_id: tenantId,
          run_id: runId,
          items: state.submitted.mediaIds.map((mediaId, index) => {
            const done = index < state.completed;
            return {
              media_id: mediaId,
              status: done ? 'completed' : 'queued',
              alt_text_draft: done ? `Fixture draft for media ${mediaId}` : null,
              caption: null,
              error: null,
              provenance: null,
              tier: done ? 'final_gpu' : null,
              result_generation: done ? 1 : 0,
              processing_ms: done ? 1200 : null,
              existing_alt: true,
              thumbnail_url: image,
              thumbnail_srcset: null,
            };
          }),
        }),
    ],
  ]);
  const dispatch = async ({ method, key, query, body }) => {
    const handler = routes.get(`${method} ${key}`);
    if (handler === undefined) {
      return null;
    }
    // The backend 404s run routes until a run has been accepted.
    if (key.startsWith('recognitionDescribeRuns/') && state.submitted === null) {
      return wpError(404, 'describe_run_not_found', 'describe run not found');
    }
    return handler({ query, body });
  };
  return { state, dispatch };
};

// Producer contract preflight: no browser state is trusted until the served build,
// identities, envelopes and routes match the application and its producers.
const contractFailures = [];
const contract = (ok, message) => {
  if (!ok) {
    contractFailures.push(message);
  }
};
contract(typeof entry?.file === 'string', `build: manifest has no entry for ${fixtureEntry}`);
const emittedJs = (await readdir(bundle, { recursive: true })).filter((name) => name.endsWith('.js'));
for (const name of emittedJs) {
  const references = (await readFile(path.join(bundle, name), 'utf8')).match(/\bprocess\.env\b/g)?.length ?? 0;
  contract(
    references === 0,
    `build: ${name} keeps ${references} process.env references the application build substitutes`,
  );
}
contract(
  LOWERCASE_UUID.test(config.tenant_id),
  `identity: config tenant_id ${config.tenant_id} is not a lowercase UUID`,
);
contract(LOWERCASE_UUID.test(runId), `identity: run_id ${runId} does not match the WordPress run route`);
const schema = JSON.parse(
  await readFile(path.resolve('../../packages/shared-contracts/schemas/scene-describe-run.schema.json'), 'utf8'),
);
const ajv = new Ajv({ allErrors: true });
ajv.addSchema(schema);
const validateRun = ajv.getSchema(schema.$id);
const validateItems = ajv.getSchema(`${schema.$id}#/definitions/items`);
const viteServer = await createServer({
  configFile: path.resolve('vite.config.ts'),
  logLevel: 'error',
  appType: 'custom',
  server: { middlewareMode: true, hmr: false, ws: false },
  optimizeDeps: { noDiscovery: true, include: [] },
});
const describeApi = await viteServer
  .ssrLoadModule(path.resolve('js/admin/api/describeApi.ts'))
  .finally(() => viteServer.close());
const checkRun = (label, response) => {
  contract(response?.status >= 200 && response?.status < 300, `${label}: HTTP ${response?.status ?? 'unmocked'}`);
  try {
    describeApi.parseDescribeRunResponse(response?.body);
  } catch (error) {
    contract(false, `${label}: real parser rejected envelope: ${String(error)}`);
  }
  contract(validateRun(response?.body), `${label}: producer schema ${ajv.errorsText(validateRun.errors)}`);
  contract(response?.body?.tenant_id === config.tenant_id, `${label}: tenant_id differs from served config`);
};
// WP adds exactly these keys to each backend item; the rest is the producer envelope.
const checkItems = (label, response, run) => {
  contract(response?.status === 200, `${label}: HTTP ${response?.status ?? 'unmocked'}`);
  const upstream = {
    ...response?.body,
    items: (response?.body?.items ?? []).map(({ existing_alt, thumbnail_url, thumbnail_srcset, ...item }) => {
      contract(
        typeof existing_alt === 'boolean' &&
          (thumbnail_url === null || typeof thumbnail_url === 'string') &&
          (thumbnail_srcset === null || typeof thumbnail_srcset === 'string'),
        `${label}: media ${item.media_id} lacks the WP existing_alt/thumbnail annotation`,
      );
      return item;
    }),
  };
  contract(validateItems(upstream), `${label}: producer schema ${ajv.errorsText(validateItems.errors)}`);
  // Escaped producer regression: schema preflight must reject each missing field,
  // even though the deliberately tolerant frontend consumer may accept it.
  const noTenant = { ...upstream };
  delete noTenant.tenant_id;
  contract(!validateItems(noTenant), `${label}: schema failed to detect a missing tenant_id`);
  const noProcessing = { ...upstream, items: upstream.items.map((item) => ({ ...item })) };
  delete noProcessing.items[0].processing_ms;
  contract(!validateItems(noProcessing), `${label}: schema failed to detect a missing processing_ms`);
  const completed = upstream.items.filter((item) => item.status === 'completed' && item.alt_text_draft !== null);
  contract(
    upstream.tenant_id === run.tenant_id &&
      upstream.run_id === run.run_id &&
      upstream.items.length === run.total &&
      completed.length === run.completed,
    `${label}: items disagree with the accepted run (${completed.length}/${upstream.items.length} vs ${run.completed}/${run.total})`,
  );
};
// Mirrors list_describe_runs_for_media: items/total/next_offset, local accepted runs only.
const checkDirectory = (label, response, wanted) => {
  const body = response?.body;
  contract(response?.status === 200, `${label}: HTTP ${response?.status ?? 'unmocked'}`);
  contract(
    body != null && Object.keys(body).sort().join() === 'items,next_offset,total',
    `${label}: envelope keys ${body == null ? 'none' : Object.keys(body).sort().join()}`,
  );
  contract(Number.isInteger(body?.total) && Array.isArray(body?.items), `${label}: total/items malformed`);
  contract(body?.next_offset === null || Number.isInteger(body?.next_offset), `${label}: next_offset malformed`);
  for (const record of body?.items ?? []) {
    contract(LOWERCASE_UUID.test(record.run_id), `${label}: run_id ${record.run_id} is not a stored run id`);
    contract(Number.isInteger(record.created_at), `${label}: created_at malformed`);
    contract(
      record.media_ids.length > 0 && record.media_ids.every((id) => wanted.includes(id)),
      `${label}: media_ids not limited to requested ids`,
    );
  }
};
const directoryQuery = (mediaIds) => {
  const params = new URLSearchParams({ limit: '5', offset: '0' });
  for (const id of mediaIds) {
    params.append('media_ids[]', String(id));
  }
  return params;
};
{
  const probe = createTransport();
  const ids = items.map((item) => item.id);
  const call = (method, key, body = null, query = new URLSearchParams()) =>
    probe.dispatch({ method, key, query, body });
  checkDirectory(
    'GET directory before submit',
    await call('GET', 'recognitionDescribeRuns', null, directoryQuery(ids)),
    ids,
  );
  checkRun(
    'POST submit',
    await call('POST', 'recognitionDescribeRuns', { media_ids: ids, idempotency_key: 'fixture-contract-key-0001' }),
  );
  checkDirectory(
    'GET directory after submit',
    await call('GET', 'recognitionDescribeRuns', null, directoryQuery(ids)),
    ids,
  );
  for (const phase of ['queued', 'warming', 'describing']) {
    Object.assign(probe.state, { status: phase === 'queued' ? 'pending' : 'running', phase });
    const status = await call('GET', `recognitionDescribeRuns/${runId}`);
    checkRun(`GET status ${phase}`, status);
    checkItems(`GET items ${phase}`, await call('GET', `recognitionDescribeRuns/${runId}/items`), status.body);
  }
  checkRun('POST cancel', await call('POST', `recognitionDescribeRuns/${runId}/cancel`));
  Object.assign(probe.state, { status: 'completed', phase: 'complete', completed: 10 });
  const terminal = await call('GET', `recognitionDescribeRuns/${runId}`);
  checkRun('GET status terminal', terminal);
  checkItems('GET items terminal', await call('GET', `recognitionDescribeRuns/${runId}/items`), terminal.body);
  // Registered WordPress routes are method-typed; anything else must stay unmocked.
  for (const [method, key] of [
    ['DELETE', `recognitionDescribeRuns/${runId}`],
    ['GET', `recognitionDescribeRuns/${runId}/cancel`],
    ['POST', `recognitionDescribeRuns/${runId}/items`],
  ]) {
    contract((await call(method, key)) === null, `route: ${method} ${key} is not a registered producer route`);
  }
}
if (contractFailures.length > 0) {
  await writeFile(
    path.join(artifacts, 'geometry.json'),
    JSON.stringify(
      { stage, verdict: 'FAIL', browser_assertions_executed: 0, contract_failures: contractFailures },
      null,
      2,
    ) + '\n',
  );
  console.log(JSON.stringify({ verdict: 'FAIL', states: 0, contract_failures: contractFailures, artifacts }, null, 2));
  process.exit(1);
}

let browser;
try {
  browser = await chromium.launch({
    headless: true,
    chromiumSandbox: true,
    executablePath:
      process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ??
      '/home/gate/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux-arm64/chrome-headless-shell',
  });
} catch (error) {
  await writeFile(
    path.join(artifacts, 'geometry.json'),
    JSON.stringify(
      {
        stage,
        verdict: 'BLOCKED',
        browser_assertions_executed: 0,
        actual_components_bundled: true,
        source_tuple: sourceTuple,
        host_inputs: { path: hostManifestPath, sha256: sha256(await readFile(hostManifestPath)), host },
        producer_contract_failures: contractFailures,
        error: String(error),
        reason: 'Browser startup denied; no geometry or screenshot PASS claimed.',
      },
      null,
      2,
    ) + '\n',
  );
  throw error;
}
const results = [];
const errors = [];

// Exact joined Library budgets are supplied by frozen WB_CONTROL production CSS.
// The earlier isolated default/bound runs remain historical evidence only.
const scenarios = [{ viewport: { width: 1440, height: 1000 } }, { viewport: { width: 719, height: 960 } }];

try {
  for (const { viewport } of scenarios) {
    const context = await browser.newContext({ viewport });
    const page = await context.newPage();
    const runtimeErrors = [];
    const requests = [];
    const transport = createTransport();
    const fixture = transport.state;
    fixture.holdCancel = true;
    page.on('pageerror', (error) => runtimeErrors.push(String(error)));
    // Block every remote network request; built assets and intercepted data only.
    await page.route('**/*', async (route) => {
      const request = route.request();
      const parsed = new URL(request.url());
      if (['about:', 'data:', 'blob:'].includes(parsed.protocol)) {
        return route.continue();
      }
      if (parsed.origin !== origin) {
        runtimeErrors.push(`Unexpected external request ${request.url()}`);
        return route.abort();
      }
      if (request.method() === 'GET' && hostAssets.has(parsed.pathname)) {
        return route.fulfill({ status: 200, contentType: 'text/css', body: hostAssets.get(parsed.pathname) });
      }
      if (parsed.pathname.startsWith('/acx-fixture/')) {
        const file = path.resolve(bundle, decodeURIComponent(parsed.pathname.slice('/acx-fixture/'.length)));
        const asset =
          request.method() === 'GET' && file.startsWith(bundle + path.sep)
            ? await readFile(file).catch(() => null)
            : null;
        if (asset === null) {
          runtimeErrors.push(`Unserved fixture asset ${request.method()} ${parsed.pathname}`);
          return route.abort();
        }
        return route.fulfill({
          status: 200,
          contentType: contentTypes[path.extname(file)] ?? 'application/octet-stream',
          body: asset,
        });
      }
      if (!parsed.pathname.startsWith('/fixture-api/')) {
        runtimeErrors.push(`Unexpected fixture-origin request ${request.method()} ${parsed.pathname}`);
        return route.abort();
      }
      const key = parsed.pathname.slice('/fixture-api/'.length);
      const body = request.postDataJSON();
      requests.push({ method: request.method(), key, query: parsed.search, body });
      const response = await transport.dispatch({ method: request.method(), key, query: parsed.searchParams, body });
      if (response === null) {
        runtimeErrors.push(`Unmocked fixture route ${request.method()} ${key}`);
        return route.abort();
      }
      await route.fulfill({
        status: response.status,
        contentType: 'application/json',
        body: JSON.stringify(response.body),
      });
    });
    const dimensions = `${viewport.width}x${viewport.height}`;
    const scenarioUrl = url;
    let checks = 0;
    const geometry = async (state) => {
      const action = page.getByRole('region', { name: 'Selected media actions' });
      const scroller = page.getByRole('region', { name: 'Media library', exact: true });
      await expect(action).toBeVisible();
      await expect(page.getByRole('button', { name: /^Describe/ })).toHaveCount(1);
      await expect(page.locator('.acx-activity-status-strip')).toHaveCount(1);
      await expect(action.locator('.acx-activity-status-strip')).toHaveCount(1);
      const measure = await page.evaluate(() => {
        const rect = (selector) => {
          const node = typeof selector === 'string' ? document.querySelector(selector) : selector;
          const r = node.getBoundingClientRect();
          return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom };
        };
        return {
          actions: rect('.acx-media-selection__actions'),
          rows: rect('.acx-media-selection__rows'),
          pagination: rect('.acx-media-selection__pagination-region'),
          preview: rect('.acx-media-selection__thumb'),
          media: rect('.acx-media-selection'),
          toolbar: rect('.acx-media-selection__toolbar'),
          library: rect('.acx-workbench__two-pane-library'),
          outerScroll: (() => {
            const library = document.querySelector('.acx-workbench__two-pane-library');
            return {
              clientHeight: library.clientHeight,
              scrollHeight: library.scrollHeight,
              scrollTop: library.scrollTop,
              overflow: getComputedStyle(library).overflowY,
            };
          })(),
          host: {
            htmlClass: document.documentElement.className,
            bodyClass: document.body.className,
            bodyFont: getComputedStyle(document.body).fontFamily,
            bodySize: getComputedStyle(document.body).fontSize,
            buttonSize: getComputedStyle(document.querySelector('.acx-media-selection__bulk-describe-actions button'))
              .fontSize,
            screenReaderPosition: getComputedStyle(document.querySelector('.screen-reader-text')).position,
            hostLinks: [...document.querySelectorAll('link[rel="stylesheet"]')].map(
              (link) => new URL(link.href).pathname,
            ),
          },
          disclosures: [...document.querySelectorAll('.acx-media-selection__bulk-describe-disclosure')].map((node) => ({
            rect: rect(node),
            clientHeight: node.clientHeight,
            scrollHeight: node.scrollHeight,
          })),
          pageWidth: document.documentElement.scrollWidth,
          viewportWidth: innerWidth,
          scrollHeight: document.querySelector('.acx-media-selection__rows').scrollHeight,
        };
      });
      expect(measure.actions.y).toBeGreaterThanOrEqual(0);
      expect(measure.actions.bottom).toBeLessThanOrEqual(viewport.height);
      expect(measure.actions.right).toBeLessThanOrEqual(viewport.width);
      expect(measure.outerScroll.scrollHeight - measure.outerScroll.clientHeight).toBeLessThanOrEqual(1);
      expect(measure.outerScroll.scrollTop).toBe(0);
      expect(measure.media.bottom).toBeLessThanOrEqual(measure.library.bottom);
      expect(measure.pagination.bottom).toBeLessThanOrEqual(measure.media.bottom + 1);
      expect(measure.host.htmlClass).toBe(host.html_classes);
      expect(measure.host.bodyClass).toBe(host.body_classes);
      expect(measure.host.bodySize).toBe('13px');
      expect(measure.host.bodyFont).toContain('sans-serif');
      expect(measure.host.screenReaderPosition).toBe('absolute');
      expect(measure.host.hostLinks.slice(0, 27)).toEqual([...hostAssets.keys()]);
      expect(measure.host.hostLinks.length).toBeGreaterThan(27);
      expect(measure.disclosures).toHaveLength(2);
      for (const disclosure of measure.disclosures) {
        expect(disclosure.rect.y).toBeGreaterThanOrEqual(measure.actions.y);
        expect(disclosure.rect.bottom).toBeLessThanOrEqual(measure.actions.bottom);
        expect(disclosure.scrollHeight).toBeLessThanOrEqual(disclosure.clientHeight + 1);
      }
      expect(measure.rows.y).toBeGreaterThanOrEqual(measure.actions.bottom);
      expect(measure.rows.height).toBeGreaterThan(100);
      expect(measure.pagination.y).toBeGreaterThanOrEqual(measure.rows.bottom - 1);
      expect(measure.pagination.bottom).toBeLessThanOrEqual(viewport.height);
      expect(measure.pageWidth).toBeLessThanOrEqual(measure.viewportWidth);
      // Ten tall rows span several scrollports; previews stay between the 80px
      // thumb token and the 300px media-selection token.
      expect(measure.scrollHeight).toBeGreaterThan(5 * measure.rows.height);
      expect(measure.preview.height).toBeGreaterThanOrEqual(80);
      expect(measure.preview.height).toBeLessThanOrEqual(300);
      const before = await action.boundingBox();
      const beforePagination = await page.locator('.acx-media-selection__pagination-region').boundingBox();
      await scroller.evaluate((node) => {
        node.scrollTop = node.scrollHeight;
      });
      const after = await action.boundingBox();
      expect(after.y).toBe(before.y);
      const last = page.getByRole('checkbox', { name: 'Select media item Tall fixture photo 10', exact: true });
      await last.focus();
      await expect(last).toBeFocused();
      const focus = await last.boundingBox();
      expect(focus.y).toBeGreaterThanOrEqual(measure.rows.y);
      expect(focus.y + focus.height).toBeLessThanOrEqual(measure.rows.bottom);
      await page.keyboard.press('Tab');
      const focused = await page.evaluate(() => {
        const r = document.activeElement.getBoundingClientRect();
        const style = getComputedStyle(document.activeElement);
        const image = document.activeElement.querySelector('img').getBoundingClientRect();
        return {
          y: r.y,
          bottom: r.bottom,
          tag: document.activeElement.tagName,
          label: document.activeElement.getAttribute('aria-label'),
          outlineStyle: style.outlineStyle,
          outlineWidth: style.outlineWidth,
          previewTop: image.top,
          previewBottom: image.bottom,
        };
      });
      expect(focused.tag).toBe('A');
      expect(focused.label).toBe('Edit Tall fixture photo 10');
      expect(focused.y).toBeGreaterThanOrEqual(measure.rows.y);
      expect(focused.bottom).toBeLessThanOrEqual(measure.rows.bottom);
      expect(focused.previewTop).toBeGreaterThanOrEqual(measure.rows.y);
      expect(focused.previewBottom).toBeLessThanOrEqual(measure.rows.bottom);
      expect(focused.outlineStyle).not.toBe('none');
      expect(parseFloat(focused.outlineWidth)).toBeGreaterThan(0);
      const afterKeyboard = await action.boundingBox();
      const afterPagination = await page.locator('.acx-media-selection__pagination-region').boundingBox();
      expect(afterKeyboard.y).toBe(before.y);
      expect(afterPagination.y).toBe(beforePagination.y);
      expect(await page.locator('.acx-workbench__two-pane-library').evaluate((node) => node.scrollTop)).toBe(0);
      await scroller.evaluate((node) => {
        node.scrollTop = 0;
        node.scrollLeft = 0;
      });
      await page.screenshot({ path: path.join(artifacts, `${dimensions}-${state}.png`), fullPage: true });
      results.push({ viewport, state, measure, focus, focused, afterKeyboard, afterPagination, checks: ++checks });
    };
    const emptyGeometry = async (state) => {
      await expect(page.getByRole('heading', { name: 'No media matches your search.' })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Clear search', exact: true })).toBeVisible();
      const measure = await page.evaluate(() => {
        const box = (selector) => {
          const node = document.querySelector(selector);
          const rect = node.getBoundingClientRect();
          return {
            top: rect.top,
            bottom: rect.bottom,
            height: rect.height,
            clientHeight: node.clientHeight,
            scrollHeight: node.scrollHeight,
          };
        };
        return {
          library: box('.acx-workbench__two-pane-library'),
          actions: box('.acx-media-selection__actions'),
          rows: box('.acx-media-selection__rows'),
          pagination: box('.acx-media-selection__pagination-region'),
        };
      });
      expect(measure.library.scrollHeight - measure.library.clientHeight).toBeLessThanOrEqual(1);
      expect(measure.actions.top).toBeGreaterThanOrEqual(0);
      expect(measure.actions.bottom).toBeLessThanOrEqual(viewport.height);
      expect(measure.rows.height).toBeGreaterThan(100);
      expect(measure.pagination.bottom).toBeLessThanOrEqual(viewport.height);
      expect(measure.pagination.bottom).toBeLessThanOrEqual(measure.library.bottom);
      await page.screenshot({ path: path.join(artifacts, `${dimensions}-${state}.png`), fullPage: true });
      results.push({ viewport, state, measure, checks: ++checks });
    };
    try {
      await page.goto(scenarioUrl);
      await expect(
        page.getByRole('checkbox', { name: 'Select media item Tall fixture photo 10', exact: true }),
      ).toBeAttached();
      const submit = page.getByRole('button', { name: /^Describe/ });
      await expect(submit).toHaveText('Describe selected');
      await expect(submit).toHaveAttribute('aria-disabled', 'true');
      await submit.focus();
      await page.keyboard.press('Enter');
      expect(requests.filter((r) => r.method === 'POST')).toHaveLength(0);
      await geometry('zero-selection');
      await page.getByRole('checkbox', { name: 'Select media item Tall fixture photo 1', exact: true }).click();
      await expect(submit).toHaveText('Describe 1 selected');
      await geometry('one-selection');
      await page.getByRole('checkbox', { name: 'Select all items on this page' }).click();
      await expect(submit).toHaveText('Describe 10 selected');
      await geometry('ten-selection');
      // A filtered empty page keeps its recovery and persistent controls. Restoring
      // the filter must preserve the selection and must never submit a job.
      await page.getByRole('searchbox', { name: 'Search media' }).fill('no-matching-fixture');
      await emptyGeometry('search-empty');
      await page.getByRole('button', { name: 'Clear search', exact: true }).click();
      await expect(
        page.getByRole('checkbox', { name: 'Select media item Tall fixture photo 10', exact: true }),
      ).toBeAttached();
      await expect(submit).toHaveText('Describe 10 selected');
      expect(requests.filter((r) => r.method === 'POST')).toHaveLength(0);
      await geometry('filter-restored');
      await submit.click();
      await expect(submit).toBeDisabled();
      await expect(page.getByRole('button', { name: 'Cancel run', exact: true })).toHaveCount(1);
      await geometry('queued');
      for (const next of ['warming', 'describing']) {
        Object.assign(fixture, { status: 'running', phase: next });
        await page.evaluate(() => window.actionProgressHarness.refetch());
        await expect(page.locator('.acx-activity-status-strip')).toHaveAttribute('data-activity-kind', next);
        await geometry(next);
      }
      const postCount = () => requests.filter((r) => r.method === 'POST' && r.key === 'recognitionDescribeRuns').length;
      expect(postCount()).toBe(1);
      await page.reload();
      await expect(page.getByRole('button', { name: 'Cancel run', exact: true })).toHaveCount(1);
      expect(postCount()).toBe(1);
      await geometry('reload-resumed');
      fixture.failPoll = true;
      await page.evaluate(() => window.actionProgressHarness.refetch());
      await expect(page.getByRole('button', { name: 'Retry', exact: true })).toHaveCount(1);
      await geometry('poll-error');
      fixture.failPoll = false;
      await page.getByRole('button', { name: 'Retry', exact: true }).click();
      await expect(page.getByRole('button', { name: 'Cancel run', exact: true })).toHaveCount(1);
      await page.getByRole('button', { name: 'Cancel run', exact: true }).click();
      await page.getByRole('dialog').getByRole('button', { name: 'Cancel run', exact: true }).click();
      // Existing useActivityStatus withdraws onCancel while the one cancel is in flight
      // (its own tests pin this), so the strip offers no second Cancel control.
      await expect(page.getByRole('dialog')).toHaveCount(0);
      await expect(page.getByRole('button', { name: /^Cancel/ })).toHaveCount(0);
      await expect.poll(() => requests.filter((r) => r.method === 'POST' && r.key.endsWith('/cancel')).length).toBe(1);
      await expect(page.locator('.acx-activity-status-strip')).toHaveAttribute('data-activity-kind', 'describing');
      await geometry('cancelling');
      fixture.cancelHold();
      Object.assign(fixture, { status: 'completed', phase: 'complete', completed: 10 });
      await page.evaluate(() => window.actionProgressHarness.refetch());
      await expect(page.locator('.acx-activity-status-strip')).toHaveAttribute('data-activity-kind', 'done');
      await expect(page.getByRole('link', { name: 'Review 10 drafts', exact: true })).toHaveAttribute(
        'href',
        new RegExp(`run=${runId}`),
      );
      // Terminal status precedes the URL-owned draft filter effect. Wait for its
      // real controls and items before measuring focus stability in that state.
      await expect(page.getByRole('button', { name: 'Clear run filter', exact: true })).toBeVisible();
      await expect(page.getByText('Fixture draft for media 10', { exact: true })).toBeAttached();
      await geometry('terminal');
      await expect(
        page.getByRole('checkbox', { name: 'Select media item Tall fixture photo 10', exact: true }),
      ).toBeAttached();
      expect(postCount()).toBe(1);
      expect(requests.filter((r) => r.key.endsWith('/cancel'))).toHaveLength(1);
      expect(runtimeErrors).toEqual([]);
    } catch (error) {
      await page.screenshot({ path: path.join(artifacts, `${dimensions}-FAILURE.png`), fullPage: true });
      errors.push({
        viewport,
        error: String(error),
        stack: error.stack,
        runtimeErrors,
        body: (await page.locator('body').innerText()).slice(0, 7000),
        requests,
      });
    } finally {
      await context.close();
    }
  }
} finally {
  await browser.close();
}
const report = {
  stage,
  source_tuple: sourceTuple,
  actual_components: true,
  real_providers_and_styles: true,
  mocked: 'HTTP transport/data only, all remote requests blocked',
  host_inputs: { path: hostManifestPath, sha256: sha256(await readFile(hostManifestPath)), host },
  browser: { version: browser.version(), chromiumSandbox: true },
  results,
  errors,
  verdict: errors.length ? 'FAIL' : 'PASS',
  limitations: [
    'Actual joined Workbench provider tree with immutable offline WordPress7.1.3 CSS, html/body classes and native PHP shell. No live WordPress, GPU, inference or deployment acceptance.',
  ],
};
await writeFile(path.join(artifacts, 'geometry.json'), JSON.stringify(report, null, 2) + '\n');
console.log(
  JSON.stringify(
    {
      verdict: report.verdict,
      states: results.length,
      failures: errors.map((e) => ({
        viewport: e.viewport,
        error: e.error,
        runtimeErrors: e.runtimeErrors,
      })),
      artifacts,
    },
    null,
    2,
  ),
);
process.exitCode = errors.length ? 1 : 0;
/* global document, innerWidth, window, getComputedStyle */
