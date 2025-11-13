import { renderHook, waitFor } from '@testing-library/react';
import { vi } from 'vitest';

import { useClusterMediaMap } from '../useClusterMediaMap';
import type { ClusterSummary } from '../../../api/recognitionApi';
import { fetchMediaMeta } from '../../utils/mediaMeta';
import * as mediaMeta from '../../utils/mediaMeta';

describe('useClusterMediaMap', () => {
  it('fetches missing media metadata', async () => {
    vi.spyOn(mediaMeta, 'fetchMediaMeta').mockResolvedValue({ url: 'https://example.com/foo.jpg' });

    const clusters: ClusterSummary[] = [
      {
        id: 'cluster-1',
        label: 'cluster-1',
        face_count: 1,
        member_ids: ['face-1'],
        representative_face: { media_id: 1, bbox: { x: 0, y: 0, width: 10, height: 10 } },
        sample_faces: [
          { id: 'face-1', media_id: 1, similarity: 0.9, confidence: 0.8, bbox: { x: 0, y: 0, width: 10, height: 10 } },
        ],
      },
    ];

    const { result } = renderHook(() => useClusterMediaMap(clusters));

    await waitFor(() => expect(fetchMediaMeta).toHaveBeenCalledWith(1));
    await waitFor(() => expect(result.current[1]?.url).toBe('https://example.com/foo.jpg'));
  });
});
