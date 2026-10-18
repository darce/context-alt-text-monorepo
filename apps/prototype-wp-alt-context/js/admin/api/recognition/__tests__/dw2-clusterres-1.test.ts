// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../utils/http', () => ({
  fetchRequiredApi: vi.fn(),
  stripTrailingSlash: (value: string) => value.replace(/\/+$/, ''),
}));

vi.mock('../../config', () => ({
  getEndpoint: () => '/wp-json/recognition/clusters',
  getConfig: () => ({ nonce: 'nonce' }),
}));

import { fetchRequiredApi } from '../../../utils/http';
import { listRecognitionClusters } from '../clusterApiQueries';

describe('cluster export metadata response', () => {
  beforeEach(() => {
    vi.mocked(fetchRequiredApi).mockReset();
  });

  it('preserves persisted export fields through the client cluster list API', async () => {
    const cluster = {
      id: 'cluster-export',
      label: 'Ada',
      identity_count: 0,
      member_ids: [],
      representative_identity: {},
      sample_identities: [],
      representative_quality: 0.82,
      quality_components: {
        confidence: 0.91,
        bbox_area: 0.12,
        sharpness: 0.77,
        occlusion_severity: null,
      },
      representative_media_id: 501,
      undoable_merge_receipt_id: 'b9e2c4a1-7d6f-4a8b-9c31-2e5f0a7b8d44',
    };
    vi.mocked(fetchRequiredApi).mockResolvedValueOnce({
      clusters: [cluster],
      limit: 20,
      total: 1,
      truncated: false,
    } as never);

    const response = await listRecognitionClusters();

    expect(response.clusters[0]).toMatchObject({
      representative_quality: 0.82,
      quality_components: cluster.quality_components,
      representative_media_id: 501,
      undoable_merge_receipt_id: 'b9e2c4a1-7d6f-4a8b-9c31-2e5f0a7b8d44',
    });
  });
});
