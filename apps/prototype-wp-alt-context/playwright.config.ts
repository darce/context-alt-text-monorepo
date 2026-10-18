import path from 'node:path';

import { config as loadEnv } from 'dotenv';
import { defineConfig } from '@playwright/test';

const appRoot = __dirname;

loadEnv({ path: path.resolve(appRoot, '.env.local') });

const taskRef = process.env.ACX_PLAYWRIGHT_TASK_REF ?? 'adhoc';
const wpBaseUrl = process.env.WP_BASE_URL ?? process.env.ACX_E2E_BASE_URL ?? 'http://localhost:10010';
const artifactRoot = path.resolve(appRoot, 'local', 'playwright', taskRef);
const storageStatePath = path.resolve(appRoot, 'tests', 'e2e', '.auth', 'storageState.json');

const resolveAdminUrl = (baseUrl: string): string => {
  const url = new URL(baseUrl);
  const pathname = url.pathname.endsWith('/') ? url.pathname : `${url.pathname}/`;

  url.pathname = pathname.includes('/wp-admin/') ? pathname : `${pathname}wp-admin/`;

  return url.toString();
};

export default defineConfig({
  testDir: path.resolve(appRoot, 'tests', 'e2e'),
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: [['list']],
  use: {
    baseURL: resolveAdminUrl(wpBaseUrl),
    ignoreHTTPSErrors: true,
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'auth-setup',
      testMatch: /auth-setup\/.*\.setup\.ts/,
      outputDir: path.join(artifactRoot, 'auth-setup'),
      use: {
        headless: false,
        storageState: undefined,
        trace: 'retain-on-failure',
      },
    },
    {
      name: 'evidence',
      dependencies: ['auth-setup'],
      testMatch: /evidence\/(?!(?:guided-walkthrough|public-guide)\.spec\.ts$).*\.spec\.ts/,
      outputDir: path.join(artifactRoot, 'evidence'),
      use: {
        headless: false,
        launchOptions: {
          slowMo: 200,
        },
        storageState: storageStatePath,
        trace: 'on',
        video: 'on',
      },
    },
    {
      // GUIDESEED-1: headless recording of the guided prototype for the public
      // case-study video. Fixed viewport so recordVideo.size matches the page; no
      // cursor is rendered headless, so the caption track (VTT) carries the narration.
      name: 'guided-recording',
      dependencies: ['auth-setup'],
      testMatch: /evidence\/guided-walkthrough\.spec\.ts/,
      outputDir: path.join(artifactRoot, 'guided-recording'),
      retries: 0,
      use: {
        headless: true,
        viewport: { width: 1440, height: 900 },
        launchOptions: {
          slowMo: 350,
        },
        storageState: storageStatePath,
        trace: 'retain-on-failure',
        video: { mode: 'on', size: { width: 1440, height: 900 } },
      },
    },
    {
      // GUIDEROUTE-1: signed-out public guide at /guide/. No auth-setup; desktop
      // 1440×900 is the project default and the spec also covers Pixel 7.
      // Export ACX_PUBLIC_GUIDE_URL via `npm run e2e:public-guide` or
      // `make demo-public-guide-e2e SITE_URL=...`. Spec skips if unset.
      name: 'public-guide',
      testMatch: /evidence\/public-guide\.spec\.ts/,
      outputDir: path.join(artifactRoot, 'public-guide'),
      retries: 0,
      use: {
        baseURL: (process.env.ACX_PUBLIC_GUIDE_URL ?? wpBaseUrl).replace(/\/guide\/?$/, ''),
        headless: true,
        storageState: { cookies: [], origins: [] },
        viewport: { width: 1440, height: 900 },
        trace: 'retain-on-failure',
      },
    },
    {
      name: 'smoke',
      dependencies: ['auth-setup'],
      testMatch: /smoke\/.*\.spec\.ts/,
      outputDir: path.join(artifactRoot, 'smoke'),
      use: {
        storageState: storageStatePath,
        trace: 'retain-on-failure',
      },
    },
    {
      name: 'a11y',
      dependencies: ['auth-setup'],
      testMatch: /a11y\/.*\.spec\.ts/,
      outputDir: path.join(artifactRoot, 'a11y'),
      use: {
        storageState: storageStatePath,
        trace: 'retain-on-failure',
      },
    },
    {
      name: 'visual',
      dependencies: ['auth-setup'],
      testMatch: /visual\/.*\.spec\.ts/,
      outputDir: path.join(artifactRoot, 'visual'),
      // Visual snapshots are deterministic; never retry. The global retries=2 on CI would otherwise
      // mask a missing baseline (attempt 1 writes an unreviewed snapshot + fails, retry reuses it + passes),
      // silently auto-accepting whatever renders. With retries=0 a missing/changed baseline fails loudly.
      retries: 0,
      snapshotPathTemplate: '{testDir}/{testFileDir}/{testFileName}-snapshots/{arg}{ext}',
      use: {
        storageState: storageStatePath,
        trace: 'retain-on-failure',
      },
    },
  ],
});
