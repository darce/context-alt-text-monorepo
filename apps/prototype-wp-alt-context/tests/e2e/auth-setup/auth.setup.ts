import fs from 'node:fs/promises';
import path from 'node:path';

import { expect, test } from '@playwright/test';
import { config as loadEnv } from 'dotenv';

const authSetupDir = __dirname;
const appRoot = path.resolve(authSetupDir, '..', '..', '..');
const storageStatePath = path.resolve(authSetupDir, '..', '.auth', 'storageState.json');

loadEnv({ path: path.resolve(appRoot, '.env.local') });

const adminUrl = process.env.ACX_E2E_BASE_URL ?? 'http://localhost:10010/wp-admin/';
const username = process.env.ACX_E2E_WP_ADMIN_USER?.trim() ?? '';
const password = process.env.ACX_E2E_WP_ADMIN_PASS?.trim() ?? '';

test('bootstrap WordPress admin auth state', async ({ page }) => {
  await page.goto(adminUrl);

  if (page.url().includes('wp-login.php')) {
    if (username && password) {
      const usernameField = page.locator('#user_login');
      const passwordField = page.locator('#user_pass');

      await usernameField.fill(username);
      await expect(usernameField).toHaveValue(username);

      await passwordField.click();
      await passwordField.pressSequentially(password);
      await expect(passwordField).toHaveValue(password);

      await page.locator('#rememberme').check();

      await Promise.all([
        page.waitForURL(/\/wp-admin\//, { waitUntil: 'domcontentloaded' }),
        page.getByRole('button', { name: /^log in$/i }).click(),
      ]);
    } else {
      await page.pause();
      await page.waitForURL(/\/wp-admin\//);
    }
  }

  await expect(page).toHaveURL(/\/wp-admin\//);
  await fs.mkdir(path.dirname(storageStatePath), { recursive: true });
  await page.context().storageState({ path: storageStatePath });
});