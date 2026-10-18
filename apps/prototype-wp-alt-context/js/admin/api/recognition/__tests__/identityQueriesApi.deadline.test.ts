// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { fetchRequiredApi } from '../../../utils/http';
import {
  fetchMediaIdentities,
  fetchPendingSuggestions,
  fetchPendingMergeSuggestions,
  fetchPendingNameSuggestions,
} from '../identityQueriesApi';

vi.mock('../../config', () => ({
  getEndpoint: (key: string) => `https://example.test/${key}`,
  getConfig: () => ({ nonce: 'nonce' }),
  isDevMode: () => false,
}));
vi.mock('../../../utils/http', () => ({
  fetchRequiredApi: vi.fn(),
  stripTrailingSlash: (value: string) => value.replace(/\/$/, ''),
}));

const reads = [
  {
    name: 'face assignments',
    read: () => fetchPendingSuggestions(),
    payload: { suggestions: [], limit: 10, offset: 0, data_source: 'backend_proxy' },
  },
  {
    name: 'merge candidates',
    read: () => fetchPendingMergeSuggestions(),
    payload: { suggestions: [], limit: 10, offset: 0, data_source: 'backend_proxy' },
  },
  {
    name: 'suggested names',
    read: () => fetchPendingNameSuggestions(),
    payload: { suggestions: [], limit: 25, offset: 0, data_source: 'backend_proxy' },
  },
  {
    name: 'media identities',
    read: () => fetchMediaIdentities([1]),
    payload: { identities_by_media: {}, data_source: 'backend_proxy' },
  },
];

beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(AbortSignal, 'timeout').mockImplementation((ms) => {
    const controller = new AbortController();
    setTimeout(() => controller.abort(new DOMException('Request timed out', 'TimeoutError')), ms);
    return controller.signal;
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe('recognition reads through the WordPress proxy', () => {
  it.each(reads)('loads $name when a healthy proxy takes three seconds', async ({ read, payload }) => {
    vi.mocked(fetchRequiredApi).mockImplementation(
      (_url, options) =>
        new Promise((resolve, reject) => {
          options?.signal?.addEventListener(
            'abort',
            () => {
              const reason: unknown = options.signal?.reason;
              reject(reason instanceof Error || reason instanceof DOMException ? reason : new Error('Request aborted'));
            },
            { once: true },
          );
          setTimeout(() => resolve(payload), 3_000);
        }),
    );
    const request = read();
    const result = request.then(
      (value) => ({ value }),
      (error: unknown) => ({ error }),
    );
    await vi.advanceTimersByTimeAsync(3_000);
    expect(await result).toMatchObject({ value: payload });
  });

  it.each(reads)('bounds a stalled $name read and preserves the failure', async ({ read }) => {
    vi.mocked(fetchRequiredApi).mockImplementation(
      (_url, options) =>
        new Promise((_resolve, reject) => {
          options?.signal?.addEventListener(
            'abort',
            () => {
              const reason: unknown = options.signal?.reason;
              reject(reason instanceof Error || reason instanceof DOMException ? reason : new Error('Request aborted'));
            },
            { once: true },
          );
        }),
    );
    const result = expect(read()).rejects.toMatchObject({ name: 'TimeoutError' });
    await vi.advanceTimersByTimeAsync(10_000);
    await result;
  });
});
