import type { Page } from '@playwright/test';

export interface WpRestContext {
  root: string;
  nonce: string;
}

export interface AcxSettingsSnapshot {
  url: string;
  recognition_source: 'service' | 'local';
  recognition_source_source: string;
  api_key_set: boolean;
}

const normalizeRestRoot = (root: string): string => root.replace(/\/$/, '');

export const readWpRestContext = async (page: Page): Promise<WpRestContext> => {
  const context = await page.evaluate(() => {
    const root = window.wpApiSettings?.root ?? `${window.location.origin}/wp-json`;
    const nonce = window.wpApiSettings?.nonce ?? window.AltContextAdmin?.nonce ?? '';

    return { root, nonce };
  });

  if (!context.nonce) {
    throw new Error('WP REST nonce missing on admin page; auth bootstrap may be stale.');
  }

  return {
    root: normalizeRestRoot(context.root),
    nonce: context.nonce,
  };
};

export const fetchAcxSettings = async (page: Page): Promise<AcxSettingsSnapshot> => {
  const { root, nonce } = await readWpRestContext(page);

  return page.evaluate(
    async ({ settingsUrl, restNonce }) => {
      const response = await fetch(settingsUrl, {
        headers: {
          'X-WP-Nonce': restNonce,
        },
      });

      if (!response.ok) {
        throw new Error(`GET settings failed with status ${response.status}`);
      }

      return response.json() as Promise<AcxSettingsSnapshot>;
    },
    {
      settingsUrl: `${root}/acx/v1/settings`,
      restNonce: nonce,
    },
  );
};

export interface SaveAcxSettingsInput {
  url?: string;
  recognition_source?: 'service' | 'local';
  api_key?: string;
}

export const saveAcxSettings = async (page: Page, input: SaveAcxSettingsInput): Promise<string[]> => {
  const { root, nonce } = await readWpRestContext(page);

  return page.evaluate(
    async ({ settingsUrl, restNonce, payload }) => {
      const response = await fetch(settingsUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-WP-Nonce': restNonce,
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        throw new Error(`POST settings failed with status ${response.status}`);
      }

      const body = (await response.json()) as { saved?: string[] };
      return body.saved ?? [];
    },
    {
      settingsUrl: `${root}/acx/v1/settings`,
      restNonce: nonce,
      payload: input,
    },
  );
};

const isOptionOwnedSource = (source: string): boolean => source === 'option' || source === 'default';

export interface EnsureServiceRecognitionOptions {
  recognitionUrl: string;
  recognitionApiKey?: string;
  enabled?: boolean;
}

export const probeAcxConnection = async (page: Page): Promise<string> => {
  const { root, nonce } = await readWpRestContext(page);

  return page.evaluate(
    async ({ testUrl, restNonce }) => {
      const response = await fetch(testUrl, {
        method: 'POST',
        headers: {
          'X-WP-Nonce': restNonce,
        },
      });

      if (!response.ok) {
        return `http_${response.status}`;
      }

      const body = (await response.json()) as { outcome?: string };
      return typeof body.outcome === 'string' ? body.outcome : 'unknown';
    },
    {
      testUrl: `${root}/acx/v1/settings/test`,
      restNonce: nonce,
    },
  );
};

export const ensureServiceRecognitionTarget = async (
  page: Page,
  options: EnsureServiceRecognitionOptions,
): Promise<{ changed: boolean; before: AcxSettingsSnapshot; after: AcxSettingsSnapshot }> => {
  if (options.enabled === false) {
    const snapshot = await fetchAcxSettings(page);
    return { changed: false, before: snapshot, after: snapshot };
  }

  const before = await fetchAcxSettings(page);

  if (!isOptionOwnedSource(before.recognition_source_source)) {
    return { changed: false, before, after: before };
  }

  const needsSource = before.recognition_source !== 'service';
  const needsUrl = before.url.trim() !== options.recognitionUrl.trim();
  const needsApiKey = Boolean(options.recognitionApiKey?.trim()) && !before.api_key_set;

  if (!needsSource && !needsUrl && !needsApiKey) {
    return { changed: false, before, after: before };
  }

  const payload: SaveAcxSettingsInput = {
    recognition_source: 'service',
    url: options.recognitionUrl,
  };

  if (options.recognitionApiKey?.trim()) {
    payload.api_key = options.recognitionApiKey.trim();
  }

  await saveAcxSettings(page, payload);
  const after = await fetchAcxSettings(page);

  return { changed: true, before, after };
};

export const ensureLocalRecognitionWhenProbeFails = async (
  page: Page,
): Promise<{ restored: boolean; before: AcxSettingsSnapshot; after: AcxSettingsSnapshot; probeOutcome: string }> => {
  const before = await fetchAcxSettings(page);
  const probeOutcome = await probeAcxConnection(page);

  if (probeOutcome === 'connected' || before.recognition_source !== 'service') {
    return { restored: false, before, after: before, probeOutcome };
  }

  if (!isOptionOwnedSource(before.recognition_source_source)) {
    return { restored: false, before, after: before, probeOutcome };
  }

  await saveAcxSettings(page, { recognition_source: 'local' });
  const after = await fetchAcxSettings(page);

  return { restored: true, before, after, probeOutcome };
};

export const restoreRecognitionSourceIfNeeded = async (page: Page, before: AcxSettingsSnapshot): Promise<boolean> => {
  if (!isOptionOwnedSource(before.recognition_source_source)) {
    return false;
  }

  const current = await fetchAcxSettings(page);
  if (current.recognition_source === before.recognition_source && current.url.trim() === before.url.trim()) {
    return false;
  }

  const payload: SaveAcxSettingsInput = {
    recognition_source: before.recognition_source,
    url: before.url,
  };

  await saveAcxSettings(page, payload);
  return true;
};
