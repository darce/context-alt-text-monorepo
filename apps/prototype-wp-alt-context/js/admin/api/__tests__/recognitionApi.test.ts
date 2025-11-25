import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as httpModule from '../../utils/http';
import {
  fetchMediaIdentities,
  fetchIdentitySuggestions,
  mergeCluster,
  revertMergeCluster,
  scanFaces,
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
    expect(httpModule.fetchApi).toHaveBeenCalledWith(expect.any(String), {
      method: 'GET',
      restNonce: 'nonce-123',
    });
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

  it('fetches identity suggestions with tenant nonce', async () => {
    (httpModule.fetchApi as vi.Mock).mockResolvedValue({ matches: [] });
    await fetchIdentitySuggestions('identity-123', 3, 0.7);
    const call = (httpModule.fetchApi as vi.Mock).mock.calls[0];
    expect(call[0]).toContain('/identity-123/suggestions');
    expect(call[0]).toContain('top_k=3');
    expect(call[0]).toContain('threshold=0.7');
    expect(call[1]).toMatchObject({ method: 'GET', restNonce: 'nonce-123' });
  });

  it('posts revert merge payload', async () => {
    (httpModule.fetchApi as vi.Mock).mockResolvedValue({});
    await revertMergeCluster({
      targetClusterId: 'target-1',
      movedIdentityIds: ['id-1', 'id-2'],
      sourceLabel: 'Alice',
    });
    expect(httpModule.fetchApi).toHaveBeenCalledWith(expect.any(String), {
      method: 'POST',
      body: {
        target_cluster_id: 'target-1',
        moved_identity_ids: ['id-1', 'id-2'],
        source_label: 'Alice',
      },
      restNonce: 'nonce-123',
    });
  });

  it('normalizes job_id from job_ids array', async () => {
    (httpModule.fetchApi as vi.Mock).mockResolvedValue({
      job_id: null,
      job_ids: ['job-1', 'job-2'],
      status: 'queued',
      total_media: 20,
    });

    const result = await scanFaces({ mediaIds: [1, 2] });
    expect(result.job_id).toBe('job-1');
    expect(result.job_ids).toEqual(['job-1', 'job-2']);
  });
});
