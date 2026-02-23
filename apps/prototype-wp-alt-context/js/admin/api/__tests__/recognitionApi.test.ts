import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as httpModule from '../../utils/http';
import {
  fetchPendingMergeSuggestions,
  fetchPendingSuggestions,
  fetchMediaIdentities,
  fetchIdentitySuggestions,
  fetchSyncStatus,
  fetchTopUnlabeledClusters,
  getRecognitionCluster,
  listRecognitionClusters,
  mergeCluster,
  revertMergeCluster,
  scanFaces,
  triggerSync,
  undismissCluster,
  updateClusterLabel,
} from '../recognition';

vi.mock('../config', () => ({
  getEndpoint: vi.fn((...keys: string[]) => `https://example.com/${keys[0] ?? 'default'}`),
  getConfig: vi.fn(() => ({ nonce: 'nonce-123', endpoints: {}, devMode: false })),
  isDevMode: vi.fn(() => false),
}));

vi.mock('../../utils/http', () => {
  const requestMock = vi.fn();
  return {
    fetchApi: requestMock,
    fetchRequiredApi: requestMock,
    stripTrailingSlash: (value: string) => (value.endsWith('/') ? value.slice(0, -1) : value),
  };
});

describe('recognitionApi', () => {
  const fetchApiMock = vi.mocked(httpModule.fetchRequiredApi);
  const fetchMutationMock = vi.mocked(httpModule.fetchApi);

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
    expect(fetchApiMock).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        method: 'GET',
        restNonce: 'nonce-123',
      }),
    );
  });

  it('sends nonce when fetching media identities', async () => {
    fetchApiMock.mockResolvedValue({ identities_by_media: {} });
    await fetchMediaIdentities([99]);
    expect(fetchApiMock).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        method: 'GET',
        restNonce: 'nonce-123',
      }),
    );
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
    await mergeCluster('source', 'target-cluster-id', 'Target Label');
    const [, options] = fetchApiMock.mock.calls[0] ?? [];
    expect(fetchApiMock).toHaveBeenCalledWith(expect.stringContaining('/source/merge'), expect.any(Object));
    expect(options).toMatchObject({
      method: 'POST',
      body: { target_cluster_id: 'target-cluster-id', target_label: 'Target Label' },
      restNonce: 'nonce-123',
    });
  });

  it('fetches identity suggestions with tenant nonce', async () => {
    fetchApiMock.mockResolvedValue({ matches: [] });
    await fetchIdentitySuggestions('identity-123', 3);
    const call = fetchApiMock.mock.calls[0];
    expect(call[0]).toContain('/identity-123/suggestions');
    expect(call[0]).toContain('top_k=3');
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

  it('returns job response from backend', async () => {
    const mockResponse = {
      id: 'job-1',
      type: 'analyze',
      status: 'pending',
      progress: { completed: 0, total: 20 },
      started_at: '2025-01-01T00:00:00Z',
      finished_at: null,
    };
    fetchApiMock.mockResolvedValue(mockResponse);

    const result = await scanFaces({ mediaIds: [1, 2] });
    expect(result.id).toBe('job-1');
    expect(result.status).toBe('pending');
    expect(result.progress?.total).toBe(20);
  });

  it('normalizes legacy pending suggestion array payloads', async () => {
    fetchApiMock.mockResolvedValue([
      {
        id: 's-1',
        identity_id: 'identity-1',
        cluster_id: 'cluster-1',
        rep_similarity: 0.87,
        member_similarity: null,
        status: 'pending',
      },
    ]);

    const result = await fetchPendingSuggestions(10, 5);

    expect(result.total).toBe(1);
    expect(result.limit).toBe(10);
    expect(result.offset).toBe(5);
    expect(result.suggestions[0]).toMatchObject({
      id: 's-1',
      identity_id: 'identity-1',
      suggested_cluster_id: 'cluster-1',
      representative_similarity: 0.87,
      avg_member_similarity: 0.87,
      confidence_score: 0.87,
    });
  });

  it('normalizes legacy pending merge suggestion array payloads', async () => {
    fetchApiMock.mockResolvedValue([
      {
        id: 'm-1',
        cluster_a_id: 'cluster-a',
        cluster_b_id: 'cluster-b',
        similarity: 0.93,
        status: 'pending',
      },
    ]);

    const result = await fetchPendingMergeSuggestions(25, 0);

    expect(result.total).toBe(1);
    expect(result.limit).toBe(25);
    expect(result.offset).toBe(0);
    expect(result.suggestions[0]).toMatchObject({
      id: 'm-1',
      cluster_a_id: 'cluster-a',
      cluster_b_id: 'cluster-b',
      similarity: 0.93,
      status: 'pending',
      cluster_a_label: null,
      cluster_b_label: null,
    });
  });

  it('builds cluster list query params through URLSearchParams', async () => {
    fetchApiMock.mockResolvedValue([]);

    await listRecognitionClusters({
      limit: 20,
      offset: 5,
      labeled_only: true,
      search: 'Alex Carter',
    });

    expect(fetchApiMock).toHaveBeenCalledTimes(1);
    const [endpoint, options] = fetchApiMock.mock.calls[0] ?? [];
    const url = new URL(endpoint);

    expect(url.searchParams.get('limit')).toBe('20');
    expect(url.searchParams.get('offset')).toBe('5');
    expect(url.searchParams.get('labeled_only')).toBe('true');
    expect(url.searchParams.get('search')).toBe('Alex Carter');
    expect(options).toMatchObject({ method: 'GET', restNonce: 'nonce-123' });
  });

  it('requests a single cluster detail from the canonical cluster endpoint', async () => {
    fetchApiMock.mockResolvedValue({
      id: 'cluster-9',
      label: 'Cluster 9',
      identity_count: 1,
      member_ids: ['identity-1'],
      representative_identity: { media_id: 1, bbox: { x: 0, y: 0, width: 1, height: 1 } },
      sample_identities: [],
    });

    await getRecognitionCluster('cluster-9');

    expect(fetchApiMock).toHaveBeenCalledWith(expect.stringContaining('/cluster-9'), {
      method: 'GET',
      restNonce: 'nonce-123',
    });
  });

  it('normalizes top-unlabeled representative thumbnail fields', async () => {
    fetchApiMock.mockResolvedValue([
      {
        id: 'cluster-1',
        tenant_id: 'tenant-1',
        label: null,
        is_labeled: false,
        is_auto_label: false,
        identity_count: 2,
        user_confirmed: false,
        representatives: [
          {
            id: 'rep-1',
            media_id: 101,
            is_pinned: false,
            thumb_url: 'http://example.test/thumb-101.jpg',
            media_url: ' ',
            bbox: null,
          },
          {
            id: 'rep-2',
            media_id: 202,
            is_pinned: false,
            thumb_url: 'http://example.test/thumb-202.jpg',
            media_url: 'http://example.test/media-202.jpg',
            bbox: null,
          },
        ],
      },
    ]);

    const result = await fetchTopUnlabeledClusters('tenant-1', 3);

    expect(result[0]?.representatives[0]).toMatchObject({
      thumb_url: 'http://example.test/thumb-101.jpg',
      media_url: null,
    });
    expect(result[0]?.representatives[1]).toMatchObject({
      thumb_url: 'http://example.test/thumb-202.jpg',
      media_url: 'http://example.test/media-202.jpg',
    });

    const [endpoint] = fetchApiMock.mock.calls[0] ?? [];
    const url = new URL(endpoint);
    expect(url.searchParams.get('tenant_id')).toBe('tenant-1');
    expect(url.searchParams.get('limit')).toBe('3');
  });

  it('fetches sync status with nonce', async () => {
    fetchApiMock.mockResolvedValue({
      last_snapshot_version: 10,
      last_synced_at: '2026-02-14 00:00:00',
      is_stale: false,
    });

    await fetchSyncStatus();

    expect(fetchApiMock).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        method: 'GET',
        restNonce: 'nonce-123',
      }),
    );
  });

  it('keeps undismiss cluster operation on the DELETE contract', async () => {
    fetchMutationMock.mockResolvedValue(undefined);

    await undismissCluster('cluster-42');

    expect(fetchMutationMock).toHaveBeenCalledWith(expect.stringContaining('/cluster-42/dismiss'), {
      method: 'DELETE',
      restNonce: 'nonce-123',
      signal: undefined,
    });
  });

  it('triggers sync with POST method', async () => {
    fetchApiMock.mockResolvedValue({
      synced: true,
      reason: 'ok',
      last_snapshot_version: 1,
      last_synced_at: '2026-02-18 10:00:00',
      is_stale: false,
    });

    await triggerSync();

    expect(fetchApiMock).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        method: 'POST',
        restNonce: 'nonce-123',
      }),
    );
  });
});
