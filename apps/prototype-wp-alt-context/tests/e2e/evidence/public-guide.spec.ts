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
 * apply → undo from the keyboard only, with zero privileged acx/v1
 * traffic and zero describe calls.
 */

const PUBLIC_SCOPE = 'Recorded example. Changes stay in this tab; WordPress and the server roster are unchanged.';
const PUBLIC_TITLE = "Who's in the photo belongs in the alt text.";
const PUBLIC_CONTEXT_PURPOSE =
  'Names can be useful in this gallery when the editor has enough evidence to include them. ' +
  'Leaving someone unnamed is also a valid choice.';
const PUBLIC_START = 'Start the walkthrough';
const PUBLIC_REVIEW_DRAFTS = 'Review drafts';
const PUBLIC_DRAFT_LABEL = 'Alt text to apply';
const APPLY_SUBMIT = 'Apply to demo copy';
const APPLY_UNDO = 'Undo last application';
const WALKTHROUGH_PHOTO_KEY = 'tribeca';
const FALLBACK = 'The walkthrough could not load. Reload the page and try again.';
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
  const walkthroughPhoto = page.getByTestId(`guided-photo-${WALKTHROUGH_PHOTO_KEY}`);
  const walkthroughReview = page.getByTestId(`guided-description-review-${WALKTHROUGH_PHOTO_KEY}`);

  await pressControl(page.getByRole('button', { name: PUBLIC_START }));
  await expect(page.getByTestId('guided-demo-stepper')).toContainText('Step 1 of 2', { timeout: STEP_TIMEOUT_MS });

  await pressControl(
    walkthroughPhoto.getByTestId(`name-choice-${WALKTHROUGH_PHOTO_KEY}-left`).getByRole('radio', { name: /^Use / }),
    'Space',
  );
  await pressControl(
    walkthroughPhoto.getByTestId(`name-choice-${WALKTHROUGH_PHOTO_KEY}-right`).getByRole('radio', { name: /^Use / }),
    'Space',
  );
  await pressControl(page.getByRole('button', { name: PUBLIC_REVIEW_DRAFTS }));
  await expect(page.getByTestId('guided-demo-stepper')).toContainText('Step 2 of 2', { timeout: STEP_TIMEOUT_MS });

  const appliedText = walkthroughReview.locator('[data-applied-text]');
  const before = (await appliedText.textContent()) ?? '';
  const draft = walkthroughReview
    .getByTestId(`guided-draft-field-${WALKTHROUGH_PHOTO_KEY}`)
    .getByRole('textbox', { name: PUBLIC_DRAFT_LABEL });
  await draft.focus();
  await page.keyboard.press('End');
  await page.keyboard.type(' ');

  const applyButton = walkthroughReview.getByTestId(`demo-apply-${WALKTHROUGH_PHOTO_KEY}`);
  await expect(applyButton).toHaveAccessibleName(APPLY_SUBMIT);
  await pressControl(applyButton);
  await expect(appliedText).not.toHaveText(before, { timeout: STEP_TIMEOUT_MS });
  const afterApply = (await appliedText.textContent()) ?? '';
  expect(afterApply.length).toBeGreaterThan(0);

  const undoButton = walkthroughReview.getByTestId(`demo-undo-${WALKTHROUGH_PHOTO_KEY}`);
  await expect(undoButton).toHaveAccessibleName(APPLY_UNDO);
  await pressControl(undoButton);
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
        await expect(page.getByRole('heading', { level: 1, name: PUBLIC_TITLE })).toBeVisible();
        await expect(page.getByText(PUBLIC_CONTEXT_PURPOSE)).toBeVisible();
        await expect(page.getByTestId('guided-photo-tribeca')).toBeVisible();
        await expect(page.getByTestId('guided-photo-coachella')).toBeVisible();
        await expect(page.getByRole('button', { name: PUBLIC_START })).toBeVisible();
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
        await expect(page.getByRole('button', { name: PUBLIC_START })).toBeVisible();
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
