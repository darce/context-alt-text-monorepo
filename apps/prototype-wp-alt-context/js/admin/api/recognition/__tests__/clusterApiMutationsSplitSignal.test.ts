import { beforeEach, describe, expect, it, vi } from 'vitest';

import { dismissCluster, splitCluster } from '../clusterApiMutations';
import type { HTTPOptions } from '../../../utils/http';

/**
 * FEBT2-W2-LANE-05: split was the last signal-deaf mutation in this module.
 *
 * As with revert (FEBT2-W2-R-01), the risk is not an unbounded wait — `utils/http`
 * already applies `DEFAULT_FETCH_TIMEOUT_MS` to every call. It is a *superseded write
 * landing*: the operator moves past a split, the caller aborts, and a split that never
 * received the signal still re-partitions the cluster for an outcome nobody is waiting
 * on (RES-10 — lapsed authority must not still be able to write). Split is the heaviest
 * write here, so the blast radius is the largest in the module.
 *
 * Threading a parameter is worthless if it is dropped between the signature and the
 * request, so these assertions read the option the transport actually received, not the
 * argument the function was called with.
 */

const mockConfig = {
  nonce: 'nonce-123',
  tenant_id: 'tenant-1',
  endpoints: {
    recognitionClusters: 'https://example.com/clusters',
  } as Record<string, string>,
};

vi.mock('../../config', () => ({
  getEndpoint: vi.fn((primary: string) => mockConfig.endpoints[primary] ?? `https://example.com/${primary}`),
  getConfig: vi.fn(() => mockConfig),
  isDevMode: vi.fn(() => false),
}));

const fetchMock = vi.fn<(endpoint: string, options?: HTTPOptions) => Promise<unknown>>();

vi.mock('../../../utils/http', () => ({
  fetchApi: (endpoint: string, options?: HTTPOptions) => fetchMock(endpoint, options),
  fetchRequiredApi: (endpoint: string, options?: HTTPOptions) => fetchMock(endpoint, options),
  stripTrailingSlash: (value: string) => (value.endsWith('/') ? value.slice(0, -1) : value),
}));

const requestUrl = (callIndex = 0): string | undefined => fetchMock.mock.calls[callIndex]?.[0];
const requestOptions = (callIndex = 0): HTTPOptions | undefined => fetchMock.mock.calls[callIndex]?.[1];

describe('splitCluster abort signal (FEBT2-W2-LANE-05)', () => {
  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockResolvedValue({ clusters: [] });
  });

  it('hands the caller signal to the transport, so an aborted split never reaches the server', async () => {
    const controller = new AbortController();

    await splitCluster('cluster-1', { nClusters: 2 }, controller.signal);

    // Identity, not truthiness: a `signal` forwarded from some other controller would
    // abort the wrong request and still satisfy a `toBeDefined()` assertion.
    expect(requestOptions()?.signal).toBe(controller.signal);
  });

  it('still posts the split body, nonce and endpoint when a signal is supplied', async () => {
    const controller = new AbortController();

    await splitCluster(
      'cluster-1',
      { nClusters: 3, anchorIdentityId: 'identity-9', splitMode: 'forced', mode: 'async' },
      controller.signal,
    );

    expect(requestUrl()).toBe('https://example.com/clusters/cluster-1/split');
    expect(requestOptions()).toMatchObject({
      method: 'POST',
      restNonce: 'nonce-123',
      body: {
        tenant_id: 'tenant-1',
        n_clusters: 3,
        anchor_identity_id: 'identity-9',
        split_mode: 'forced',
        mode: 'async',
      },
    });
  });

  it('an omitted signal stays omitted — the parameter is optional, not defaulted', async () => {
    await splitCluster('cluster-1', { nClusters: 2 });

    expect(requestOptions()?.signal).toBeUndefined();
  });

  it('keeps the request default intact when called with only a cluster id', async () => {
    await splitCluster('cluster-1');

    expect(requestOptions()).toMatchObject({ body: { tenant_id: 'tenant-1', n_clusters: 0 } });
    expect(requestOptions()?.signal).toBeUndefined();
  });

  it('matches the shape its siblings already use', async () => {
    const controller = new AbortController();

    await dismissCluster('cluster-1', controller.signal);

    expect(requestOptions()?.signal).toBe(controller.signal);
  });
});
