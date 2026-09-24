import { devices, expect, test, type Locator, type Page, type Request } from '@playwright/test';

import {
  PUBLIC_GUIDE_FALLBACK,
  guidedCopy as publicGuideCopy,
} from '../../../js/admin/guidedPrototype/publicGuideCopy';
import { classifyAcxRequest, isAcxRestRequest, type AcxRequestRecord } from '../fixtures/guided-recording';

/**
 * GUIDEROUTE-1: signed-out public guide acceptance.
 *
 * Runs under the `public-guide` Playwright project (no auth-setup). Skips when
 * ACX_PUBLIC_GUIDE_URL is unset. Wire it with `npm run e2e:public-guide` or
 * `make demo-public-guide-e2e SITE_URL=...` (not implied by deploy-enable).
 * Desktop 1440×900 and mobile 390×844 check the delivered layout, then
 * complete name choice → edit → use → undo from the keyboard with zero
 * privileged acx/v1 traffic and zero describe calls.
 */

const PUBLIC_SCOPE = publicGuideCopy('scope.public');
const PUBLIC_TITLE = publicGuideCopy('entry.title.public');
const PUBLIC_DOCUMENT_TITLE = `Demo: ${PUBLIC_TITLE} | AltContext`;
const PUBLIC_CONTEXT_PURPOSE = publicGuideCopy('context.purpose');
const PUBLIC_START = publicGuideCopy('entry.start.public');
const PUBLIC_CASE_STUDY = publicGuideCopy('entry.read_case_study');
const PUBLIC_COMPARE_PHOTOS = publicGuideCopy('names.compare.public');
const PUBLIC_DRAFT_LABEL = publicGuideCopy('draft.field_label.public');
const PUBLIC_LEAVE_UNNAMED = publicGuideCopy('names.omit.public');
const APPLY_SUBMIT = publicGuideCopy('description.use.public');
const APPLY_UNDO = publicGuideCopy('description.undo.public');
const WALKTHROUGH_PHOTO_KEY = 'tribeca';
const FALLBACK = PUBLIC_GUIDE_FALLBACK;
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
  const describeCalls = records.filter((row) =>
    /\/(?:public\/)?demo\/describe(?:[/?#]|$)|\/describe(?:[/?#]|$)/i.test(row.url),
  );
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
  await pressControl(
    walkthroughPhoto.getByTestId(`name-choice-${WALKTHROUGH_PHOTO_KEY}-left`).getByRole('radio').first(),
    'Space',
  );
  await pressControl(
    walkthroughPhoto
      .getByTestId(`name-choice-${WALKTHROUGH_PHOTO_KEY}-right`)
      .getByRole('radio', { name: PUBLIC_LEAVE_UNNAMED }),
    'Space',
  );

  const appliedText = walkthroughReview
    .getByTestId(`guided-current-alt-${WALKTHROUGH_PHOTO_KEY}`)
    .locator('[data-applied-text]');
  const before = (await appliedText.textContent()) ?? '';
  const draft = walkthroughReview
    .getByTestId(`guided-draft-field-${WALKTHROUGH_PHOTO_KEY}`)
    .getByRole('textbox', { name: PUBLIC_DRAFT_LABEL });
  await expect(draft).toBeVisible({ timeout: STEP_TIMEOUT_MS });
  await draft.focus();
  await page.keyboard.press('End');
  await page.keyboard.type(' Edited in the public guide.');

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

const assertResponsiveLayout = async (page: Page, viewportName: string): Promise<void> => {
  const root = page.getByTestId('guided-demo-root');
  const rootBox = await root.boundingBox();
  expect(rootBox, 'public guide root box').not.toBeNull();

  const layout = await page.locator('.acx-guided-entrance').evaluate((entrance) => {
    const content = entrance.querySelector('.acx-guided-entrance__content');
    const plan = entrance.querySelector('.acx-guided-entrance__plan');
    const samplePhoto = document.querySelector('[data-testid="guided-photo-tribeca"]');
    const image = samplePhoto?.querySelector('.acx-guided-page__image-wrap');
    const faces = samplePhoto?.querySelector('.acx-guided-page__faces');
    if (
      content === null ||
      plan === null ||
      image === null ||
      image === undefined ||
      faces === null ||
      faces === undefined
    ) {
      throw new Error('Public guide layout landmarks are missing');
    }
    const contentBox = content.getBoundingClientRect();
    const planBox = plan.getBoundingClientRect();
    const imageBox = image.getBoundingClientRect();
    const facesBox = faces.getBoundingClientRect();
    return {
      contentLeft: contentBox.left,
      contentRight: contentBox.right,
      planLeft: planBox.left,
      imageRight: imageBox.right,
      facesLeft: facesBox.left,
    };
  });

  if (viewportName === 'desktop 1440x900') {
    expect(layout.planLeft).toBeGreaterThan(layout.contentRight);
    expect(layout.facesLeft).toBeGreaterThan(layout.imageRight);
    return;
  }

  expect(layout.contentLeft - (rootBox?.x ?? 0)).toBeCloseTo(16, 0);
  const firstPhotoFrame = await page
    .getByTestId('guided-photo-tribeca')
    .locator('.acx-guided-page__image-wrap')
    .boundingBox();
  if (firstPhotoFrame === null) {
    throw new Error('The first sample photo image frame is missing');
  }
  expect(firstPhotoFrame.y).toBeLessThan(844 - 120);

  await page.getByTestId('guided-photo-tribeca').getByRole('button', { name: PUBLIC_COMPARE_PHOTOS }).first().click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  const referenceTiles = await dialog.locator('.acx-guided-face__lightbox-gallery img').evaluateAll((images) =>
    images.slice(0, 2).map((image) => {
      const bounds = image.getBoundingClientRect();
      return { width: bounds.width, top: bounds.top };
    }),
  );
  expect(referenceTiles).toHaveLength(2);
  expect(referenceTiles[0].width).toBeGreaterThanOrEqual(158);
  expect(referenceTiles[0].width).toBeLessThanOrEqual(160);
  expect(referenceTiles[1].width).toBe(referenceTiles[0].width);
  expect(Math.abs(referenceTiles[0].top - referenceTiles[1].top)).toBeLessThan(1);
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
};

test.describe('public guide signed-out', () => {
  test.skip(
    configuredUrl === '',
    'ACX_PUBLIC_GUIDE_URL is unset; run npm run e2e:public-guide or make demo-public-guide-e2e',
  );
  test.setTimeout(120_000);

  // defaultBrowserType is worker-scoped and cannot be set in a nested describe.
  const { defaultBrowserType: _defaultBrowserType, ...pixel7 } = devices['Pixel 7'];
  const viewports = [
    { name: 'desktop 1440x900', use: { viewport: { width: 1440, height: 900 } } },
    { name: 'mobile 390x844', use: { ...pixel7, viewport: { width: 390, height: 844 } } },
  ] as const;

  for (const viewport of viewports) {
    test.describe(viewport.name, () => {
      test.use({
        ...viewport.use,
        storageState: { cookies: [], origins: [] },
      });

      test('signed-out /guide/ is 200 with canonical, scope copy, keyboard name choice/use/undo, and no REST', async ({
        page,
      }) => {
        const acxRequests = attachAcxCounter(page);
        const response = await page.goto(guideUrl, { waitUntil: 'domcontentloaded' });
        expect(response, 'navigation response').not.toBeNull();
        expect(response?.status()).toBe(200);

        await expect(page.locator('link[rel="canonical"]')).toHaveAttribute('href', /\/guide\/?$/);
        await expect(page.getByTestId('guided-scope')).toHaveText(PUBLIC_SCOPE);
        await expect(page.getByRole('heading', { level: 1, name: PUBLIC_TITLE })).toBeVisible();
        expect.soft(await page.locator('title').count()).toBe(1);
        expect.soft(await page.locator('title').allTextContents()).toEqual([PUBLIC_DOCUMENT_TITLE]);
        await expect(page.getByText(PUBLIC_CONTEXT_PURPOSE)).toBeVisible();
        await expect(page.getByTestId('guided-photo-tribeca')).toBeVisible();
        await expect(page.getByTestId('guided-photo-coachella')).toBeVisible();
        await expect(page.getByRole('button', { name: PUBLIC_START })).toBeVisible();
        await expect(page.getByRole('link', { name: PUBLIC_CASE_STUDY })).toBeVisible();

        await assertResponsiveLayout(page, viewport.name);
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
        await page.route(
          (url) => /\/guide-(?!watch-)[^/]+\.js$/.test(url.pathname),
          (route) => route.abort(),
        );
        const acxRequests = attachAcxCounter(page);
        const response = await page.goto(guideUrl, { waitUntil: 'domcontentloaded' });
        expect(response?.status()).toBe(200);
        await expect(page.getByRole('alert')).toContainText(FALLBACK, { timeout: STEP_TIMEOUT_MS });
        await expect(page.locator('link[rel="canonical"]')).toHaveAttribute('href', /\/guide\/?$/);
        assertNoPrivilegedOrDescribe(acxRequests);
      });
    });
  }
});
