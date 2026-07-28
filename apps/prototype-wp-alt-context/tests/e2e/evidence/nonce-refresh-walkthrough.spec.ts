import { expect, test } from '@playwright/test';

import { getAcxAdminRouteUrl } from '../fixtures/acx-routes';

/**
 * UXP-NET-2 live rest-nonce refresh wire (LocalWP evidence).
 *
 * Automates the manual walkthrough gate against the deployed feature build:
 * validates the real WordPress nonce wire that unit tests mock. The nonce
 * check runs pre-dispatch (rest_cookie_check_errors) so a stale/garbage nonce
 * is rejected before the route callback executes — the acx write is therefore
 * non-executed (safe to probe). Recovery uses core admin-ajax ?action=rest-nonce
 * (GET, raw-string body). Fresh-nonce acceptance is proven against a no-op
 * wp/v2/settings POST to avoid any acx side effect.
 *
 * Anchors: http.ts sends X-WP-Nonce on writes only (:127); 403 nonce-refresh +
 * single retry (:238-268). window.AltContextAdmin.nonce = wp_create_nonce('wp_rest').
 */

// acx write route: nonce-gated; garbage nonce -> pre-dispatch reject, trigger_sync never runs.
const ACX_WRITE_PATH = '/wp-json/acx/v1/recognition/sync/trigger';
// core no-op write: empty body updates nothing; proves a fresh wp_rest nonce clears the gate.
const CORE_NOOP_WRITE_PATH = '/wp-json/wp/v2/settings';
const STALE_NONCE = 'stale-invalid-e2e';

test.describe('UXP-NET-2 live rest-nonce refresh wire', () => {
  test('deployed feature build localizes a rest nonce', async ({ page, baseURL }) => {
    if (!baseURL) throw new Error('baseURL required');
    await page.goto(getAcxAdminRouteUrl(baseURL, 'alt-context-dashboard'));
    await expect(page.locator('.acx-dashboard__shell')).toBeVisible();
    const nonce = await page.evaluate(
      () => (window as unknown as { AltContextAdmin?: { nonce?: string } }).AltContextAdmin?.nonce ?? null,
    );
    expect(nonce, 'AltContextAdmin.nonce present in deployed build').toBeTruthy();
  });

  test('stale nonce -> real WP 403 non-executed -> admin-ajax refresh -> fresh nonce accepted', async ({
    page,
    baseURL,
  }) => {
    if (!baseURL) throw new Error('baseURL required');
    await page.goto(getAcxAdminRouteUrl(baseURL, 'alt-context-dashboard'));
    await expect(page.locator('.acx-dashboard__shell')).toBeVisible();

    const r = await page.evaluate(
      async ({ acxWrite, coreWrite, stale }) => {
        const origin = window.location.origin;
        const admin = (window as unknown as { AltContextAdmin?: { ajaxUrl?: string } }).AltContextAdmin;
        const ajaxUrl = admin?.ajaxUrl ?? '';

        // 1) stale nonce on an acx WRITE -> pre-dispatch nonce rejection (non-executed)
        const bad = await fetch(origin + acxWrite, {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'X-WP-Nonce': stale, 'Content-Type': 'application/json' },
          body: '{}',
        });
        const badBody = await bad.text();

        // 2) refresh via core admin-ajax rest-nonce (GET, raw-string body)
        const refreshUrl = ajaxUrl + (ajaxUrl.includes('?') ? '&' : '?') + 'action=rest-nonce';
        const refresh = await fetch(refreshUrl, { method: 'GET', credentials: 'same-origin' });
        const fresh = (await refresh.text()).trim();

        // 3) fresh nonce on a core no-op WRITE -> nonce accepted (no acx side effect)
        const retry = await fetch(origin + coreWrite, {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'X-WP-Nonce': fresh, 'Content-Type': 'application/json' },
          body: '{}',
        });
        const retryBody = await retry.text();

        return {
          badStatus: bad.status,
          badBody,
          refreshStatus: refresh.status,
          fresh,
          retryStatus: retry.status,
          retryBody,
        };
      },
      { acxWrite: ACX_WRITE_PATH, coreWrite: CORE_NOOP_WRITE_PATH, stale: STALE_NONCE },
    );

    // Stale nonce: WP core rejects pre-dispatch — guaranteed non-executed.
    expect(r.badStatus, 'stale nonce must 403').toBe(403);
    expect(r.badBody, 'stale nonce must be the WP nonce error code').toContain('rest_cookie_invalid_nonce');

    // Refresh source: admin-ajax returns a fresh raw nonce string.
    expect(r.refreshStatus).toBe(200);
    expect(r.fresh.length, 'fresh nonce is a non-trivial string').toBeGreaterThanOrEqual(8);
    expect(r.fresh).not.toBe(STALE_NONCE);
    expect(r.fresh, 'refresh body must be a raw nonce, not HTML/JSON').not.toContain('<');

    // Retry with the fresh nonce clears the pre-dispatch nonce gate.
    const retryRejectedByNonce = r.retryStatus === 403 && r.retryBody.includes('rest_cookie_invalid_nonce');
    expect(retryRejectedByNonce, 'fresh nonce must clear the nonce gate').toBe(false);
    expect(r.retryStatus, 'core no-op write with fresh nonce succeeds').toBe(200);
  });

  test('deployed bundle ships the auth-expired session copy', async ({ page, baseURL }) => {
    if (!baseURL) throw new Error('baseURL required');
    await page.goto(getAcxAdminRouteUrl(baseURL, 'alt-context-dashboard'));
    await expect(page.locator('.acx-dashboard__shell')).toBeVisible();
    const present = await page.evaluate(async () => {
      const srcs = Array.from(document.querySelectorAll('script[src]'))
        .map((s) => (s as HTMLScriptElement).src)
        .filter((src) => /assets\/.*\.js/.test(src));
      for (const src of srcs) {
        try {
          const txt = await (await fetch(src, { credentials: 'same-origin' })).text();
          if (txt.includes('Your session expired')) return true;
        } catch {
          /* ignore unreachable chunk */
        }
      }
      return false;
    });
    expect(present, 'session-expired copy present in the deployed feature bundle').toBe(true);
  });
});
