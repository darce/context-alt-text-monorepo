import { beforeEach, describe, expect, it, vi } from 'vitest';

import { mergeCluster, revertMergeCluster } from '../clusterApiMutations';
import type { HTTPOptions } from '../../../utils/http';

/**
 * FEBT2-W2-R-01: revert-merge must be signal-deaf no longer.
 *
 * The risk this pins is NOT an unbounded wait — `utils/http` already applies
 * `DEFAULT_FETCH_TIMEOUT_MS` to every call, so a revert cannot hang forever. It is a
 * *superseded write landing*: the operator moves past an undo, the caller aborts, and a
 * revert that never received the signal still commits and still invalidates caches for an
 * outcome nobody is waiting on (RES-10 — lapsed authority must not still be able to write).
 *
 * Threading a parameter is worthless if it is dropped on the floor between the signature
 * and the request, so these assertions read the option the transport actually received,
 * not the argument the function was called with.
 */

const mockConfig = {
  nonce: 'nonce-123',
  tenant_id: 'tenant-1',
  endpoints: {
    recognitionRevertMerge: 'https://example.com/revert-merge',
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

const requestOptions = (callIndex = 0): HTTPOptions | undefined => fetchMock.mock.calls[callIndex]?.[1];

describe('revertMergeCluster abort signal (FEBT2-W2-R-01)', () => {
  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockResolvedValue({});
  });

  it('hands the caller signal to the transport, so an aborted revert never reaches the server', async () => {
    const controller = new AbortController();

    await revertMergeCluster(
      {
        targetClusterId: 'target-1',
        movedIdentityIds: ['id-1', 'id-2'],
        sourceLabel: 'Alice',
      },
      controller.signal,
    );

    // Identity, not truthiness: a `signal` forwarded from some other controller would abort
    // the wrong request and still satisfy a `toBeDefined()` assertion.
    expect(requestOptions()?.signal).toBe(controller.signal);
  });

  it('still sends the revert body and nonce when a signal is supplied', async () => {
    const controller = new AbortController();

    await revertMergeCluster(
      {
        targetClusterId: 'target-1',
        movedIdentityIds: ['id-1', 'id-2'],
        sourceLabel: 'Alice',
      },
      controller.signal,
    );

    expect(requestOptions()).toMatchObject({
      method: 'POST',
      restNonce: 'nonce-123',
      body: {
        target_cluster_id: 'target-1',
        moved_identity_ids: ['id-1', 'id-2'],
        source_label: 'Alice',
      },
    });
  });

  it('an omitted signal stays omitted — the parameter is optional, not defaulted', async () => {
    await revertMergeCluster({
      targetClusterId: 'target-1',
      movedIdentityIds: [],
      sourceLabel: null,
    });

    expect(requestOptions()?.signal).toBeUndefined();
  });

  it('matches the shape its siblings already use', async () => {
    const controller = new AbortController();

    await mergeCluster('source-1', 'target-1', 'Target', controller.signal);

    expect(requestOptions()?.signal).toBe(controller.signal);
  });
});
