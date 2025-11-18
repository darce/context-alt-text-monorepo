import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as httpModule from '../../utils/http';
import {
  fetchMediaIdentities,
  mergeCluster,
  updateClusterLabel,
} from '../recognitionApi';

vi.mock('../config', () => ({
  getEndpoint: vi.fn((...keys: string[]) => `https://example.com/${keys[0] ?? 'default'}`),
  getConfig: vi.fn(() => ({ nonce: 'nonce-123', endpoints: {} })),
}));

vi.mock('../../utils/http', () => ({
  fetchApi: vi.fn(),
}));

describe('recognitionApi', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('passes media IDs to fetchMediaIdentities', async () => {
    (httpModule.fetchApi as vi.Mock).mockResolvedValue({ identities_by_media: {} });
    await fetchMediaIdentities([1, 2]);
    expect(httpModule.fetchApi).toHaveBeenCalledTimes(1);
    const url = new URL((httpModule.fetchApi as vi.Mock).mock.calls[0][0]);
    expect(url.searchParams.getAll('media_ids[]')).toEqual(['1', '2']);
  });

  it('sends nonce when fetching media identities', async () => {
    (httpModule.fetchApi as vi.Mock).mockResolvedValue({ identities_by_media: {} });
    await fetchMediaIdentities([99]);
    expect(httpModule.fetchApi).toHaveBeenCalledWith(expect.any(String), {
      method: 'GET',
      restNonce: 'nonce-123',
    });
  });

  it('calls updateClusterLabel with PATCH', async () => {
    (httpModule.fetchApi as vi.Mock).mockResolvedValue({});
    await updateClusterLabel('cluster-1', 'New Label');
    expect(httpModule.fetchApi).toHaveBeenCalledWith(expect.stringContaining('/cluster-1'), {
      method: 'PATCH',
      body: { label: 'New Label' },
      restNonce: expect.any(String),
    });
  });

  it('calls mergeCluster with POST', async () => {
    (httpModule.fetchApi as vi.Mock).mockResolvedValue({});
    await mergeCluster('source', 'target');
    expect(httpModule.fetchApi).toHaveBeenCalledWith(expect.stringContaining('/source/merge'), {
      method: 'POST',
      body: { target_label: 'target' },
      restNonce: expect.any(String),
    });
  });
});
