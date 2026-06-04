import path from 'node:path';

import { config as loadEnv } from 'dotenv';
import { defineConfig } from '@playwright/test';

const appRoot = __dirname;
const taskRef = process.env.ACX_PLAYWRIGHT_TASK_REF ?? 'E15-6';
const adminUrl = process.env.ACX_E2E_BASE_URL ?? 'http://localhost:10010/wp-admin/';
const artifactRoot = path.resolve(appRoot, 'local', 'playwright', taskRef);
const storageStatePath = path.resolve(appRoot, 'tests', 'e2e', '.auth', 'storageState.json');

loadEnv({ path: path.resolve(appRoot, '.env.local') });

export default defineConfig({
  testDir: path.resolve(appRoot, 'tests', 'e2e'),
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: [['list']],
  outputDir: path.join(artifactRoot, 'test-results'),
  use: {
    baseURL: adminUrl,
    ignoreHTTPSErrors: true,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'auth-setup',
      testMatch: /auth-setup\/.*\.setup\.ts/,
      use: {
        headless: false,
        storageState: undefined,
      },
    },
    {
      name: 'evidence',
      dependencies: ['auth-setup'],
      testMatch: /evidence\/.*\.spec\.ts/,
      use: {
        headless: false,
        storageState: storageStatePath,
      },
    },
    {
      name: 'smoke',
      dependencies: ['auth-setup'],
      testMatch: /smoke\/.*\.spec\.ts/,
      use: {
        storageState: storageStatePath,
      },
    },
    {
      name: 'a11y',
      dependencies: ['auth-setup'],
      testMatch: /a11y\/.*\.spec\.ts/,
      use: {
        storageState: storageStatePath,
      },
    },
  ],
});