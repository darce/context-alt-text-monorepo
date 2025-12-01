import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as httpModule from '../../utils/http';
import {
  fetchMediaIdentities,
  fetchIdentitySuggestions,
  mergeCluster,
  revertMergeCluster,
  scanFaces,
  updateClusterLabel,
} from '../recognition';

vi.mock('../config', () => ({
  getEndpoint: vi.fn((...keys: string[]) => `https://example.com/${keys[0] ?? 'default'}`),
  getConfig: vi.fn(() => ({ nonce: 'nonce-123', endpoints: {}, devMode: false })),
  isDevMode: vi.fn(() => false),
}));

vi.mock('../../utils/http', () => ({
  fetchApi: vi.fn(),
  stripTrailingSlash: (value: string) => (value.endsWith('/') ? value.slice(0, -1) : value),
}));

describe('recognitionApi', () => {
  const fetchApiMock = vi.mocked(httpModule.fetchApi);

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('passes media IDs to fetchMediaIdentities', async () => {
    fetchApiMock.mockResolvedValue({ identities_by_media: {} });
    await fetchMediaIdentities([1, 2]);
    expect(fetchApiMock).toHaveBeenCalledTimes(1);
    const [endpoint] = fetchApiMock.mock.calls[0] ?? [];
    const url = new URL(endpoint);
    expect(url.searchParams.getAll('media_ids[]')).toEqual(['1', '2']);
    expect(fetchApiMock).toHaveBeenCalledWith(expect.any(String), {
      method: 'GET',
      restNonce: 'nonce-123',
    });
  });

  it('sends nonce when fetching media identities', async () => {
    fetchApiMock.mockResolvedValue({ identities_by_media: {} });
    await fetchMediaIdentities([99]);
    expect(fetchApiMock).toHaveBeenCalledWith(expect.any(String), {
      method: 'GET',
      restNonce: 'nonce-123',
    });
  });

  it('calls updateClusterLabel with PATCH', async () => {
    fetchApiMock.mockResolvedValue({});
    await updateClusterLabel('cluster-1', 'New Label');
    const [, options] = fetchApiMock.mock.calls[0] ?? [];
    expect(fetchApiMock).toHaveBeenCalledWith(expect.stringContaining('/cluster-1'), expect.any(Object));
    expect(options).toMatchObject({ method: 'PATCH', body: { label: 'New Label' }, restNonce: 'nonce-123' });
  });

  it('calls mergeCluster with POST', async () => {
    fetchApiMock.mockResolvedValue({});
    await mergeCluster('source', 'target');
    const [, options] = fetchApiMock.mock.calls[0] ?? [];
    expect(fetchApiMock).toHaveBeenCalledWith(expect.stringContaining('/source/merge'), expect.any(Object));
    expect(options).toMatchObject({ method: 'POST', body: { target_label: 'target' }, restNonce: 'nonce-123' });
  });

  it('fetches identity suggestions with tenant nonce', async () => {
    fetchApiMock.mockResolvedValue({ matches: [] });
    await fetchIdentitySuggestions('identity-123', 3, 0.7);
    const call = fetchApiMock.mock.calls[0];
    expect(call[0]).toContain('/identity-123/suggestions');
    expect(call[0]).toContain('top_k=3');
    expect(call[0]).toContain('threshold=0.7');
    expect(call[1]).toMatchObject({ method: 'GET', restNonce: 'nonce-123' });
  });

  it('posts revert merge payload', async () => {
    fetchApiMock.mockResolvedValue({});
    await revertMergeCluster({
      targetClusterId: 'target-1',
      movedIdentityIds: ['id-1', 'id-2'],
      sourceLabel: 'Alice',
    });
    expect(fetchApiMock).toHaveBeenCalledWith(expect.any(String), {
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
    fetchApiMock.mockResolvedValue({
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
