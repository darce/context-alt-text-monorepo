import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createAppQueryClient } from '../appQueryClient';
import { HTTPError } from '../http';
import { _resetCooldownForTests, cooldownRemainingMs, isCoolingDown } from '../recognitionCooldown';

const httpError = (status: number, retryAfterSeconds?: number): HTTPError =>
  new HTTPError({
    status,
    retryAfterSeconds,
    endpoint: '/acx/v1/recognition/jobs/1',
    bodyPreview: '',
    message: `failed (${status})`,
  });

describe('createAppQueryClient default options', () => {
  it('pins refetchOnWindowFocus: false (load-bearing for partial-correction rows)', () => {
    // A partial has alt text, so the server drops it from status=missing.
    // Refetch-on-focus would remove the row mid-review under the operator.
    const appQueryClient = createAppQueryClient();
    expect(appQueryClient.getDefaultOptions().queries?.refetchOnWindowFocus).toBe(false);
    appQueryClient.clear();
  });
});

describe('createAppQueryClient cooldown arming', () => {
  beforeEach(() => {
    _resetCooldownForTests();
  });

  afterEach(() => {
    _resetCooldownForTests();
  });

  it('arms the cooldown when a query fails with 429 — including retry:false queries', async () => {
    const client = createAppQueryClient();

    await expect(
      client.fetchQuery({
        queryKey: ['cooldown-arm-429'],
        queryFn: () => Promise.reject(httpError(429, 42)),
        retry: false,
      }),
    ).rejects.toBeInstanceOf(HTTPError);

    expect(isCoolingDown()).toBe(true);
    expect(cooldownRemainingMs()).toBeGreaterThan(41_000);
    expect(cooldownRemainingMs()).toBeLessThanOrEqual(42_000);
    client.clear();
  });

  it('arms on the FIRST 429 sighting via the default retry path, before retries drain', async () => {
    vi.useFakeTimers();
    try {
      const client = createAppQueryClient();
      const queryFn = vi.fn(() => Promise.reject(httpError(429, 30)));
      const result = client.fetchQuery({ queryKey: ['cooldown-first-sighting'], queryFn });
      result.catch(() => undefined); // consumed after timers drain

      await vi.advanceTimersByTimeAsync(0);
      // First failure seen; retries (Retry-After-delayed) still pending.
      expect(queryFn).toHaveBeenCalledTimes(1);
      expect(isCoolingDown()).toBe(true);

      await vi.advanceTimersByTimeAsync(120_000);
      await expect(result).rejects.toBeInstanceOf(HTTPError);
      client.clear();
    } finally {
      vi.useRealTimers();
    }
  });

  it('arms the cooldown when a mutation fails with 503 + Retry-After', async () => {
    const client = createAppQueryClient();
    const mutation = client.getMutationCache().build(client, {
      mutationFn: () => Promise.reject(httpError(503, 15)),
    });

    await expect(mutation.execute(undefined)).rejects.toBeInstanceOf(HTTPError);
    expect(isCoolingDown()).toBe(true);
    client.clear();
  });

  it('does not arm on non-signal failures (404, bare 503)', async () => {
    const client = createAppQueryClient();

    await expect(
      client.fetchQuery({
        queryKey: ['cooldown-404'],
        queryFn: () => Promise.reject(httpError(404)),
        retry: false,
      }),
    ).rejects.toBeInstanceOf(HTTPError);

    await expect(
      client.fetchQuery({
        queryKey: ['cooldown-bare-503'],
        queryFn: () => Promise.reject(httpError(503)),
        retry: false,
      }),
    ).rejects.toBeInstanceOf(HTTPError);

    expect(isCoolingDown()).toBe(false);
    client.clear();
  });
});
