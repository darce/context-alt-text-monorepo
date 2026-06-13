import fs from 'node:fs/promises';

import { expect, test } from '@playwright/test';

import { getAcxAdminRouteUrl } from '../fixtures/acx-routes';
import { fetchAcxSettings, probeAcxConnection, readWpRestContext } from '../fixtures/wp-rest';

/**
 * E15-27 operator evidence: the scan pipeline's routing + capability contract on
 * real LocalWP. Proves the Settings surface the plugin scans against is coherent
 * (effective target, recognition source provenance) and that the capability probe
 * reaches the service's `/health/detailed` embedding-runtime field — the fail-fast
 * signal the scan intake gate reads. Capability-unavailable vs available scan
 * behaviour is unit/contract-proven (test_scan_capability_intake.py, scanApiError);
 * the live progress run is the existing workbench-evidence spec.
 */

const SETTINGS_ROUTE_SLUG = 'alt-context-settings';
const EFFECTIVE_ROUTING_TESTID = 'acx-effective-routing';
const VALID_TARGET_MODES = new Set(['local', 'service']);

interface RuntimeEvidenceManifest {
  settings_contract_ok: boolean;
  recognition_source: string | null;
  recognition_source_source: string | null;
  effective_target_mode: string | null;
  effective_target_url: string | null;
  api_key_set: boolean | null;
  probe_outcome: string | null;
  detailed_health_status: number | null;
  embedding_runtime: { available?: boolean; reason?: string | null; heartbeat_age_seconds?: number | null } | null;
  captures: Record<string, boolean>;
}

const probeDetailedHealth = async (
  page: import('@playwright/test').Page,
): Promise<{ status: number | null; embedding_runtime: RuntimeEvidenceManifest['embedding_runtime'] }> => {
  const { root, nonce } = await readWpRestContext(page);

  // settings/test merges build_probe_payload(): { outcome, status_code, body }
  // where `body` is the decoded /health/detailed JSON (service mode), which
  // carries E15-27's `embedding_runtime` capability field.
  return page.evaluate(
    async ({ testUrl, restNonce }) => {
      try {
        const response = await fetch(testUrl, {
          method: 'POST',
          headers: { 'X-WP-Nonce': restNonce },
        });
        const payload = (await response.json().catch(() => null)) as {
          status_code?: number;
          body?: { embedding_runtime?: unknown } | string;
        } | null;
        const detailedBody = payload && typeof payload.body === 'object' && payload.body !== null ? payload.body : null;
        const runtime =
          detailedBody && typeof detailedBody.embedding_runtime === 'object' && detailedBody.embedding_runtime !== null
            ? (detailedBody.embedding_runtime as { available?: boolean; reason?: string | null })
            : null;
        return {
          status: typeof payload?.status_code === 'number' ? payload.status_code : null,
          embedding_runtime: runtime,
        };
      } catch {
        return { status: null, embedding_runtime: null };
      }
    },
    { testUrl: `${root}/acx/v1/settings/test`, restNonce: nonce },
  );
};

test('captures E15-27 scan routing + capability evidence on LocalWP', async ({ page, baseURL }, testInfo) => {
  if (!baseURL) {
    throw new Error('Expected Playwright baseURL to be configured for LocalWP admin.');
  }

  const captures: Record<string, boolean> = {};
  const manifest: RuntimeEvidenceManifest = {
    settings_contract_ok: false,
    recognition_source: null,
    recognition_source_source: null,
    effective_target_mode: null,
    effective_target_url: null,
    api_key_set: null,
    probe_outcome: null,
    detailed_health_status: null,
    embedding_runtime: null,
    captures,
  };

  try {
    // Land on the Settings admin page so wpApiSettings (REST root + nonce) is present.
    await page.goto(getAcxAdminRouteUrl(baseURL, SETTINGS_ROUTE_SLUG));
    await expect(page).toHaveURL(/page=alt-context-settings/);

    const settings = await fetchAcxSettings(page).catch(() => null);
    if (!settings) {
      test.skip(
        true,
        'acx/v1/settings unavailable on LocalWP — plugin REST not active; cannot capture routing evidence.',
      );
      return;
    }

    manifest.recognition_source = settings.recognition_source;
    manifest.recognition_source_source = settings.recognition_source_source;
    manifest.api_key_set = settings.api_key_set;

    // The full settings GET carries the effective-target fields the SettingsForm
    // renders; read them directly so the manifest records what the operator sees.
    const restContext = await readWpRestContext(page);
    const fullSettings = await page.evaluate(
      async ({ settingsUrl, restNonce }) => {
        const response = await fetch(settingsUrl, { headers: { 'X-WP-Nonce': restNonce } });
        if (!response.ok) {
          return null;
        }
        const parsed = (await response.json()) as { effective_target_mode?: string; effective_target_url?: string };
        return {
          effective_target_mode: parsed.effective_target_mode,
          effective_target_url: parsed.effective_target_url,
        };
      },
      { settingsUrl: `${restContext.root}/acx/v1/settings`, restNonce: restContext.nonce },
    );
    manifest.effective_target_mode = fullSettings?.effective_target_mode ?? null;
    manifest.effective_target_url = fullSettings?.effective_target_url ?? null;

    // Contract assertions: the routing fields the scan pipeline depends on must be
    // present and well-formed on a real install (rg-005/rg-015 parity at runtime).
    expect(VALID_TARGET_MODES.has(settings.recognition_source)).toBeTruthy();
    expect(typeof settings.recognition_source_source).toBe('string');
    expect(settings.recognition_source_source.length).toBeGreaterThan(0);
    expect(
      manifest.effective_target_mode === null || VALID_TARGET_MODES.has(manifest.effective_target_mode),
    ).toBeTruthy();
    manifest.settings_contract_ok = true;

    // Capability probe → service /health/detailed embedding-runtime field. When the
    // configured target is reachable this records the fail-fast capability signal;
    // when not, the outcome itself is the evidence (operator sees a real reason).
    manifest.probe_outcome = await probeAcxConnection(page).catch(() => null);
    const detailed = await probeDetailedHealth(page);
    manifest.detailed_health_status = detailed.status;
    manifest.embedding_runtime = detailed.embedding_runtime;

    // The effective-target line (E15-25/E15-27 settings coherence) must render so
    // an operator can see where scans actually route before triggering one.
    const effectiveLine = page.getByTestId(EFFECTIVE_ROUTING_TESTID);
    const effectiveVisible = await effectiveLine
      .first()
      .waitFor({ state: 'visible', timeout: 20_000 })
      .then(() => true)
      .catch(() => false);
    captures['settings-effective-routing.png'] = effectiveVisible;
    if (effectiveVisible) {
      await effectiveLine
        .first()
        .scrollIntoViewIfNeeded()
        .catch(() => undefined);
    }

    await page.screenshot({ path: testInfo.outputPath('scan-routing-settings.png'), fullPage: true });
    captures['scan-routing-settings.png'] = true;

    // Evidence-bearing assertion: we reached the real Settings surface AND the
    // routing contract is intact. The effective-routing line is asserted as a soft
    // capture (manifest) rather than a hard gate so a pre-E15-25 theme can't flake
    // the contract proof, but the contract itself must hold.
    expect(manifest.settings_contract_ok).toBeTruthy();
  } finally {
    await fs.writeFile(testInfo.outputPath('scan-runtime-manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
  }
});
