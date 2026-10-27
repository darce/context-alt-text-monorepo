import { QueryClient } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { queryKeys } from '../../api/queryKeys';
import { createAppQueryClient } from '../appQueryClient';
import { AuthExpiredError, HTTPError } from '../http';
import { _resetCooldownForTests, cooldownRemainingMs, isCoolingDown } from '../recognitionCooldown';
import { installTopUnlabeledErrorLatch } from '../topUnlabeledErrorLatch';

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

describe('createAppQueryClient top-unlabeled error latch (UXREC-1-DEMOQ-G3-F1)', () => {
  const authExpired = (): AuthExpiredError =>
    new AuthExpiredError({ endpoint: '/acx/v1/recognition/clusters/top-unlabeled', status: 403 });

  // TEST-15: a client that installs lazily (round 5) cannot recover the class
  // here — by install time the no-data refetch has already reset the query.
  it('latches a top-unlabeled error settled before any hook renders', async () => {
    const client = createAppQueryClient();
    const error = authExpired();
    const key = queryKeys.clusters.topUnlabeled('tenant-a');
    await expect(
      client.fetchQuery({ queryKey: key, queryFn: () => Promise.reject(error), retry: false }),
    ).rejects.toBe(error);
    const otherKey = queryKeys.clusters.list();
    const otherError = authExpired();
    await expect(
      client.fetchQuery({ queryKey: otherKey, queryFn: () => Promise.reject(otherError), retry: false }),
    ).rejects.toBe(otherError);

    let release!: () => void;
    const refetch = client.fetchQuery({
      queryKey: key,
      queryFn: () =>
        new Promise((resolve) => {
          release = () => resolve({ clusters: [] });
        }),
    });
    expect(client.getQueryState(key)).toMatchObject({ status: 'pending', fetchStatus: 'fetching', error: null });

    const queryCache = client.getQueryCache();
    const query = queryCache.find({ queryKey: key, exact: true });
    expect(query).toBeDefined();
    const settledErrors = installTopUnlabeledErrorLatch(client);
    expect(settledErrors.get(query!)).toBe(error);
    expect(settledErrors.get(queryCache.find({ queryKey: otherKey, exact: true })!)).toBeUndefined();
    expect(installTopUnlabeledErrorLatch(client)).toBe(settledErrors);

    release();
    await refetch;
    expect(settledErrors.get(query!)).toBeUndefined();
    client.clear();
  });

  it('adds no second cache subscription on a repeat install', () => {
    const appClient = createAppQueryClient();
    const appSubscribe = vi.spyOn(appClient.getQueryCache(), 'subscribe');
    installTopUnlabeledErrorLatch(appClient);
    expect(appSubscribe).not.toHaveBeenCalled();

    const plainClient = new QueryClient();
    const plainSubscribe = vi.spyOn(plainClient.getQueryCache(), 'subscribe');
    const settledErrors = installTopUnlabeledErrorLatch(plainClient);
    expect(installTopUnlabeledErrorLatch(plainClient)).toBe(settledErrors);
    expect(plainSubscribe).toHaveBeenCalledTimes(1);
  });

  it('seeds a lazily installed client from top-unlabeled errors already settled in its cache', async () => {
    const client = new QueryClient();
    const error = authExpired();
    const key = queryKeys.clusters.topUnlabeled('tenant-b');
    await expect(
      client.fetchQuery({ queryKey: key, queryFn: () => Promise.reject(error), retry: false }),
    ).rejects.toBe(error);
    const otherKey = queryKeys.clusters.list();
    const otherError = authExpired();
    await expect(
      client.fetchQuery({ queryKey: otherKey, queryFn: () => Promise.reject(otherError), retry: false }),
    ).rejects.toBe(otherError);

    const queryCache = client.getQueryCache();
    const settledErrors = installTopUnlabeledErrorLatch(client);
    expect(settledErrors.get(queryCache.find({ queryKey: key, exact: true })!)).toBe(error);
    expect(settledErrors.get(queryCache.find({ queryKey: otherKey, exact: true })!)).toBeUndefined();
    client.clear();
  });
});
