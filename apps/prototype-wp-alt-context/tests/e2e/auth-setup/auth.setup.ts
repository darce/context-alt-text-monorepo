import fs from 'node:fs/promises';
import path from 'node:path';

import { expect, test } from '@playwright/test';

const authSetupDir = __dirname;
const storageStatePath = path.resolve(authSetupDir, '..', '.auth', 'storageState.json');

const username = (process.env.ACX_E2E_WP_ADMIN_USER ?? '').trim();
const password = (process.env.ACX_E2E_WP_ADMIN_PASS ?? '').trim();
const isCI = Boolean(process.env.CI);

test('bootstrap WordPress admin auth state', async ({ page, baseURL }) => {
  if (!baseURL) {
    throw new Error('baseURL must be set on the playwright config for auth bootstrap.');
  }

  await page.goto(baseURL);

  if (page.url().includes('wp-login.php')) {
    if (username && password) {
      const usernameField = page.locator('#user_login');
      const passwordField = page.locator('#user_pass');

      await usernameField.fill(username);
      await expect(usernameField).toHaveValue(username);

      await passwordField.fill(password);
      await expect(passwordField).toHaveValue(password);

      await page.locator('#rememberme').check();

      await Promise.all([
        page.waitForURL(/\/wp-admin\//, { waitUntil: 'domcontentloaded' }),
        page.locator('#wp-submit').click(),
      ]);
    } else {
      if (isCI) {
        throw new Error(
          'ACX_E2E_WP_ADMIN_USER and ACX_E2E_WP_ADMIN_PASS are required in CI; interactive page.pause() is not supported.',
        );
      }
      await page.pause();
      await page.waitForURL(/\/wp-admin\//);
    }
  }

  await expect(page).toHaveURL(/\/wp-admin\//);
  await fs.mkdir(path.dirname(storageStatePath), { recursive: true });
  await page.context().storageState({ path: storageStatePath });
});
