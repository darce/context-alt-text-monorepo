import { devices, expect, test, type Locator, type Page, type Request } from '@playwright/test';

import {
  classifyAcxRequest,
  isAcxRestRequest,
  type AcxRequestRecord,
} from '../fixtures/guided-recording';

/**
 * GUIDEROUTE-1: signed-out public guide acceptance.
 *
 * Runs under the `public-guide` Playwright project (no auth-setup). Skips when
 * ACX_PUBLIC_GUIDE_URL is unset. Wire it with `npm run e2e:public-guide` or
 * `make demo-public-guide-e2e SITE_URL=...` (not implied by deploy-enable).
 * Desktop 1440×900 and mobile Pixel 7 both complete choose → edit →
 * preview → apply → undo from the keyboard only, with zero privileged acx/v1
 * traffic and zero describe calls.
 */

const PUBLIC_SCOPE =
  'Try the review workflow using a recorded example. Your changes affect only the demo copy in this tab.';
const FALLBACK =
  'The walkthrough could not load. Reload the page, or watch the recorded video on the case study page.';
const STEP_TIMEOUT_MS = 20_000;

const configuredUrl = (process.env.ACX_PUBLIC_GUIDE_URL ?? '').trim();

const resolveGuideUrl = (raw: string): string => {
  const trimmed = raw.replace(/\/+$/, '');
  return trimmed.endsWith('/guide') ? `${trimmed}/` : `${trimmed}/guide/`;
};

const guideUrl = configuredUrl === '' ? '/guide/' : resolveGuideUrl(configuredUrl);

const attachAcxCounter = (page: Page): AcxRequestRecord[] => {
  const records: AcxRequestRecord[] = [];
  page.on('request', (request: Request) => {
    const url = request.url();
    if (!isAcxRestRequest(url)) {
      return;
    }
    records.push({
      method: request.method(),
      url,
      classification: classifyAcxRequest(request.method(), url, request.headers()),
    });
  });
  return records;
};

const assertNoPrivilegedOrDescribe = (records: readonly AcxRequestRecord[]): void => {
  const privileged = records.filter((row) => row.classification === 'privileged');
  const describeCalls = records.filter((row) => /\/(?:public\/)?demo\/describe(?:[/?#]|$)|\/describe(?:[/?#]|$)/i.test(row.url));
  expect(privileged, JSON.stringify(privileged)).toEqual([]);
  expect(describeCalls, JSON.stringify(describeCalls)).toEqual([]);
};

const pressControl = async (locator: Locator, key: 'Enter' | 'Space' = 'Enter'): Promise<void> => {
  await locator.focus();
  await locator.press(key);
};

const completeKeyboardWalkthrough = async (page: Page): Promise<void> => {
  const appliedText = page.locator('#guided-section-apply [data-applied-text]');
  const before = (await appliedText.textContent()) ?? '';

  await pressControl(page.getByRole('button', { name: 'Start the walkthrough' }));
  await expect(page.getByTestId('guided-demo-stepper')).toContainText('Step 1 of 4', { timeout: STEP_TIMEOUT_MS });

  await pressControl(page.getByRole('button', { name: 'Review name suggestions' }));
  await expect(page.getByTestId('guided-demo-stepper')).toContainText('Step 2 of 4', { timeout: STEP_TIMEOUT_MS });

  await pressControl(page.getByTestId('name-choice-left').getByRole('radio', { name: /^Use / }), 'Space');
  await pressControl(page.getByTestId('name-choice-right').getByRole('radio', { name: /^Use / }), 'Space');
  await pressControl(page.getByRole('button', { name: 'Review the draft' }));
  await expect(page.getByTestId('guided-demo-stepper')).toContainText('Step 3 of 4', { timeout: STEP_TIMEOUT_MS });

  const draft = page.getByRole('textbox', { name: /Alt text draft/i });
  await draft.focus();
  await page.keyboard.press('End');
  await page.keyboard.type(' ');
  await pressControl(page.getByRole('button', { name: 'Preview the change' }));
  await expect(page.getByTestId('guided-demo-stepper')).toContainText('Step 4 of 4', { timeout: STEP_TIMEOUT_MS });

  await pressControl(page.getByRole('button', { name: 'Apply to demo copy' }));
  await expect(appliedText).not.toHaveText(before, { timeout: STEP_TIMEOUT_MS });
  const afterApply = (await appliedText.textContent()) ?? '';
  expect(afterApply.length).toBeGreaterThan(0);

  await pressControl(page.getByRole('button', { name: 'Undo last application' }));
  await expect(appliedText).toHaveText(before, { timeout: STEP_TIMEOUT_MS });
};

test.describe('public guide signed-out', () => {
  test.skip(
    configuredUrl === '',
    'ACX_PUBLIC_GUIDE_URL is unset; run npm run e2e:public-guide or make demo-public-guide-e2e',
  );
  test.setTimeout(120_000);

  const viewports = [
    { name: 'desktop 1440x900', use: { viewport: { width: 1440, height: 900 } } },
    { name: 'mobile Pixel 7', use: devices['Pixel 7'] },
  ] as const;

  for (const viewport of viewports) {
    test.describe(viewport.name, () => {
      test.use({
        ...viewport.use,
        storageState: { cookies: [], origins: [] },
      });

      test('signed-out /guide/ is 200 with canonical, scope copy, keyboard apply/undo, and no REST', async ({
        page,
      }) => {
        const acxRequests = attachAcxCounter(page);
        const response = await page.goto(guideUrl, { waitUntil: 'domcontentloaded' });
        expect(response, 'navigation response').not.toBeNull();
        expect(response?.status()).toBe(200);

        await expect(page.locator('link[rel="canonical"]')).toHaveAttribute('href', /\/guide\/?$/);
        await expect(page.getByTestId('guided-scope')).toHaveText(PUBLIC_SCOPE);
        await expect(page.getByRole('button', { name: 'Start the walkthrough' })).toBeVisible();
        await expect(page.getByRole('link', { name: 'Watch the recording' })).toBeVisible();
        await expect(page.getByRole('link', { name: 'Read the case study' })).toBeVisible();

        await completeKeyboardWalkthrough(page);
        assertNoPrivilegedOrDescribe(acxRequests);
      });

      test('direct reload of /guide/ keeps the page working', async ({ page }) => {
        const acxRequests = attachAcxCounter(page);
        const first = await page.goto(guideUrl, { waitUntil: 'domcontentloaded' });
        expect(first?.status()).toBe(200);
        await expect(page.getByTestId('guided-demo-root')).toBeVisible({ timeout: STEP_TIMEOUT_MS });

        const reloaded = await page.reload({ waitUntil: 'domcontentloaded' });
        expect(reloaded?.status()).toBe(200);
        await expect(page.getByTestId('guided-demo-root')).toBeVisible({ timeout: STEP_TIMEOUT_MS });
        await expect(page.getByTestId('guided-scope')).toHaveText(PUBLIC_SCOPE);
        await expect(page.getByRole('button', { name: 'Start the walkthrough' })).toBeVisible();
        assertNoPrivilegedOrDescribe(acxRequests);
      });

      test('route-blocked guide bundle shows the fallback paragraph', async ({ page }) => {
        await page.route('**/*.js', (route) => route.abort());
        await page.route('**/*.mjs', (route) => route.abort());
        const acxRequests = attachAcxCounter(page);
        const response = await page.goto(guideUrl, { waitUntil: 'domcontentloaded' });
        expect(response?.status()).toBe(200);
        await expect(page.getByRole('alert')).toContainText(FALLBACK);
        await expect(page.locator('link[rel="canonical"]')).toHaveAttribute('href', /\/guide\/?$/);
        assertNoPrivilegedOrDescribe(acxRequests);
      });
    });
  }
});
