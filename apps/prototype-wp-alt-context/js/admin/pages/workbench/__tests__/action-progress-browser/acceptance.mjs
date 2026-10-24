import { build } from 'vite';
import react from '@vitejs/plugin-react';
import { chromium, expect } from '@playwright/test';
import { mkdir, readdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { URL, pathToFileURL } from 'node:url';
import process from 'node:process';
import console from 'node:console';
import { setTimeout } from 'node:timers';

const stage = process.env.ACCEPTANCE_STAGE ?? 'GREEN';
const artifacts = path.resolve('../../artifacts/action-progress/browser', stage);
await mkdir(artifacts, { recursive: true });
const bundle = path.join(artifacts, 'bundle');
await build({
  configFile: false,
  root: process.cwd(),
  plugins: [react()],
  publicDir: false,
  base: './',
  logLevel: 'error',
  build: {
    outDir: bundle,
    emptyOutDir: true,
    minify: false,
    lib: {
      entry: path.resolve('js/admin/pages/workbench/__tests__/action-progress-browser/fixture.tsx'),
      formats: ['iife'],
      name: 'ActionProgressFixture',
      fileName: () => 'fixture.js',
    },
  },
});
const css = (await readdir(bundle)).filter((name) => name.endsWith('.css'));
await writeFile(
  path.join(bundle, 'index.html'),
  `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ACTION_PROGRESS</title>${css.map((name) => `<link rel="stylesheet" href="./${name}">`).join('')}<div id="root"></div><script src="./fixture.js"></script></html>`,
);
const origin = 'https://action-progress-fixture.invalid';
const url = pathToFileURL(path.join(bundle, 'index.html')).href;
let browser;
try {
  browser = await chromium.launch({
    headless: true,
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
const image =
  'data:image/svg+xml,' +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300"><rect width="300" height="300" fill="#dde5ed"/><circle cx="150" cy="130" r="65" fill="#728da5"/><text x="85" y="250" font-size="22">Test media</text></svg>',
  );
const items = Array.from({ length: 10 }, (_, i) => ({
  id: i + 1,
  title: `Tall fixture photo ${i + 1}`,
  status: 'missing',
  thumbnailUrl: image,
  altText: null,
  isDecorative: false,
  editUrl: '#edit',
  tags: ['Fixture'],
  mimeType: 'image/jpeg',
  updatedAt: '2026-10-24T12:00:00Z',
  dimensions: { width: 300, height: 300 },
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

try {
  for (const viewport of [
    { width: 1440, height: 1000 },
    { width: 719, height: 960 },
  ]) {
    const context = await browser.newContext({ viewport });
    const page = await context.newPage();
    const runtimeErrors = [];
    const requests = [];
    let phase = 'queued';
    let status = 'running';
    let completed = 0;
    let failPoll = false;
    let cancelRequested = false;
    let settingsMode = 'off';
    let selectedAtSubmit = 0;
    let cancelHold;
    const run = () => ({
      tenant_id: 'action-progress-fixture',
      run_id: 'run-fixture',
      status,
      phase,
      completed,
      failed: 0,
      skipped: 0,
      total: selectedAtSubmit,
      cancel_requested: cancelRequested,
      eta_seconds: null,
      gpu_state: 'ready',
      recognition_enabled: false,
    });
    page.on('pageerror', (error) => runtimeErrors.push(String(error)));
    // Block every remote network request; loopback assets and intercepted data only.
    await page.route('**/*', async (route) => {
      const request = route.request();
      const parsed = new URL(request.url());
      if (parsed.origin !== origin && !['file:', 'about:', 'data:', 'blob:'].includes(parsed.protocol)) {
        runtimeErrors.push(`Unexpected external request ${request.url()}`);
        return route.abort();
      }
      if (!parsed.pathname.startsWith('/fixture-api/')) {
        return route.continue();
      }
      const key = parsed.pathname.slice('/fixture-api/'.length);
      requests.push({ method: request.method(), key, body: request.postDataJSON() });
      let body;
      let code = 200;
      if (key === 'settings') {
        if (settingsMode === 'pending') {
          await new Promise((resolve) => setTimeout(resolve, 1500));
        }
        body = { recognition_enabled: settingsMode === 'on', development_face_scan_available: false };
      } else if (key === 'workbenchMedia') {
        body = { items, total: 10, totalPages: 2 };
      } else if (key === 'workbenchMediaDetail') {
        body = { details_by_media: {}, limit: 100, total: 10, truncated: false };
      } else if (key === 'recognitionMediaIdentities') {
        body = { identities_by_media: {}, data_source: 'local_projection' };
      } else if (key === 'recognitionDescribeHistory') {
        body = { items: [], total: 0, limit: 50, offset: 0, has_more: false };
      } else if (key === 'recognitionGpuStatus') {
        body = gpu;
      } else if (key.startsWith('recognitionBatchRuns')) {
        body = { items: [] };
      } else if (key === 'recognitionSyncHealth') {
        body = {
          breaker: { state: 'closed', base_url: origin, opened_at: null },
          outbox: { state: 'ok', pending: 0, failed: 0, dead_lettered: 0, oldest_age_seconds: 0 },
          conflicts: { open: 0 },
          replays: { failed: 0, source: 'fixture' },
          last_pull: { at: '2026-10-24T12:00:00Z', ok: true },
          warnings: [],
        };
      } else if (key === 'recognitionSyncStatus') {
        body = {
          last_snapshot_version: 1,
          last_synced_at: '2026-10-24T12:00:00Z',
          is_stale: false,
          sync_health: 'healthy',
          last_sync_result: 'ok',
          reclaimer: null,
        };
      } else if (key === 'recognitionDescribeRuns' && request.method() === 'POST') {
        selectedAtSubmit = request.postDataJSON().media_ids.length;
        body = run();
      } else if (key === 'recognitionDescribeRuns/run-fixture/cancel') {
        cancelRequested = true;
        await new Promise((resolve) => {
          cancelHold = resolve;
        });
        body = run();
      } else if (key === 'recognitionDescribeRuns/run-fixture') {
        body = failPoll ? { code: 'fixture_poll_error', message: 'Offline fixture poll failed' } : run();
        code = failPoll ? 400 : 200;
      } else if (key === 'recognitionDescribeRuns/run-fixture/items') {
        body = { run_id: 'run-fixture', items: [] };
      } else {
        runtimeErrors.push(`Unmocked fixture route ${request.method()} ${key}`);
        return route.abort();
      }
      await route.fulfill({ status: code, contentType: 'application/json', body: JSON.stringify(body) });
    });
    const dimensions = `${viewport.width}x${viewport.height}`;
    let checks = 0;
    const geometry = async (state) => {
      const action = page.getByRole('region', { name: 'Selected media actions' });
      const scroller = page.getByRole('region', { name: 'Media library', exact: true });
      await expect(action).toBeVisible();
      const measure = await page.evaluate(() => {
        const rect = (selector) => {
          const node = document.querySelector(selector);
          const r = node.getBoundingClientRect();
          return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom };
        };
        return {
          actions: rect('.acx-media-selection__actions'),
          rows: rect('.acx-media-selection__rows'),
          pagination: rect('.acx-media-selection__pagination-region'),
          pageWidth: document.documentElement.scrollWidth,
          viewportWidth: innerWidth,
          scrollHeight: document.querySelector('.acx-media-selection__rows').scrollHeight,
        };
      });
      expect(measure.actions.y).toBeGreaterThanOrEqual(0);
      expect(measure.actions.bottom).toBeLessThanOrEqual(viewport.height);
      expect(measure.actions.right).toBeLessThanOrEqual(viewport.width);
      expect(measure.rows.y).toBeGreaterThanOrEqual(measure.actions.bottom);
      expect(measure.rows.height).toBeGreaterThan(100);
      expect(measure.pagination.y).toBeGreaterThanOrEqual(measure.rows.bottom - 1);
      expect(measure.pagination.bottom).toBeLessThanOrEqual(viewport.height);
      expect(measure.pageWidth).toBeLessThanOrEqual(measure.viewportWidth);
      expect(measure.scrollHeight).toBeGreaterThan(3000);
      const before = await action.boundingBox();
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
        return { y: r.y, bottom: r.bottom };
      });
      expect(focused.y).toBeGreaterThanOrEqual(measure.rows.y);
      expect(focused.bottom).toBeLessThanOrEqual(measure.rows.bottom);
      await scroller.evaluate((node) => {
        node.scrollTop = 0;
        node.scrollLeft = 0;
      });
      await page.screenshot({ path: path.join(artifacts, `${dimensions}-${state}.png`), fullPage: true });
      results.push({ viewport, state, measure, focus, checks: ++checks });
    };
    try {
      await page.goto(url);
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
      await submit.click();
      await expect(submit).toBeDisabled();
      await expect(page.getByRole('button', { name: 'Cancel run', exact: true })).toHaveCount(1);
      await geometry('queued');
      for (const next of ['warming', 'describing']) {
        phase = next;
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
      failPoll = true;
      await page.evaluate(() => window.actionProgressHarness.refetch());
      await expect(page.getByRole('button', { name: 'Retry', exact: true })).toHaveCount(1);
      await geometry('poll-error');
      failPoll = false;
      await page.getByRole('button', { name: 'Retry', exact: true }).click();
      await expect(page.getByRole('button', { name: 'Cancel run', exact: true })).toHaveCount(1);
      await page.getByRole('button', { name: 'Cancel run', exact: true }).click();
      await page.getByRole('dialog').getByRole('button', { name: 'Cancel run', exact: true }).click();
      await expect(page.getByRole('button', { name: 'Cancelling…', exact: true })).toHaveCount(1);
      await geometry('cancelling');
      cancelHold();
      status = 'completed';
      phase = 'complete';
      completed = 10;
      await page.evaluate(() => window.actionProgressHarness.refetch());
      await expect(page.locator('.acx-activity-status-strip')).toHaveAttribute('data-activity-kind', 'done');
      await expect(page.getByRole('link', { name: 'Review 10 drafts', exact: true })).toHaveAttribute(
        'href',
        /run=run-fixture/,
      );
      await geometry('terminal');
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
  actual_components: true,
  real_providers_and_styles: true,
  mocked: 'HTTP transport/data only, all remote requests blocked',
  results,
  errors,
  verdict: errors.length ? 'FAIL' : 'PASS',
  limitations: [
    'Bounded MediaSelection slot harness; joined WB_CONTROL outer composition is separate. No live WordPress, GPU, inference or deployment acceptance.',
  ],
};
await writeFile(path.join(artifacts, 'geometry.json'), JSON.stringify(report, null, 2) + '\n');
console.log(
  JSON.stringify(
    {
      verdict: report.verdict,
      states: results.length,
      failures: errors.map((e) => ({ viewport: e.viewport, error: e.error, runtimeErrors: e.runtimeErrors })),
      artifacts,
    },
    null,
    2,
  ),
);
process.exitCode = errors.length ? 1 : 0;
/* global document, innerWidth, window */
