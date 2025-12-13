import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

import { useClusterMediaMap } from '../useClusterMediaMap';
import type { ClusterSummary } from '../../../../api/recognition';
import { fetchMediaMeta } from '../../utils/mediaMeta';
import * as mediaMeta from '../../utils/mediaMeta';

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useClusterMediaMap', () => {
  it('fetches missing media metadata', async () => {
    vi.spyOn(mediaMeta, 'fetchMediaMeta').mockResolvedValue({ url: 'https://example.com/foo.jpg' });

    const clusters: ClusterSummary[] = [
      {
        id: 'cluster-1',
        label: 'cluster-1',
        identity_count: 1,
        member_ids: ['identity-1'],
        representative_identity: { media_id: 1, bbox: { x: 0, y: 0, width: 10, height: 10 } },
        sample_identities: [
          {
            identity_id: 'identity-1',
            media_id: 1,
            similarity: 0.9,
            confidence: 0.8,
            bbox: { x: 0, y: 0, width: 10, height: 10 },
          },
        ],
      },
    ];

    const { result } = renderHook(() => useClusterMediaMap(clusters));

    await waitFor(() => expect(fetchMediaMeta).toHaveBeenCalledWith(1));
    await waitFor(() => expect(result.current[1]?.url).toBe('https://example.com/foo.jpg'));
  });

  it('fetches metadata for drawer-only identities', async () => {
    vi.spyOn(mediaMeta, 'fetchMediaMeta').mockResolvedValue({ url: 'https://example.com/extra.jpg' });

    const clusters: ClusterSummary[] = [
      {
        id: 'cluster-1',
        label: 'cluster-1',
        identity_count: 0,
        member_ids: ['identity-1'],
        representative_identity: { media_id: null, bbox: { x: 0, y: 0, width: 0, height: 0 } },
        sample_identities: [],
      },
    ];

    renderHook(() => useClusterMediaMap(clusters, [42]));

    await waitFor(() => expect(fetchMediaMeta).toHaveBeenCalledWith(42));
  });
});
