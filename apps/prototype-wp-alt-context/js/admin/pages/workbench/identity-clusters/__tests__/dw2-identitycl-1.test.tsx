import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as recognitionApi from '../../../../api/recognition';
import type { DetectedIdentity } from '../../../../api/recognition';
import { IdentityClusterItem } from '../IdentityClusterItem';
import type { ProjectedSuggestion } from '../suggestionProjection';
import { useInlineSuggestionBatch } from '../useInlineSuggestionBatch';
import type { ClusterGroup } from '../types';
import { unlabeledSuggestionBatchIds } from '../utils';

vi.mock('../../../../api/recognition', () => ({
  fetchIdentitiesSuggestions: vi.fn(),
  listRecognitionClusters: vi.fn(),
}));

vi.mock('../useClusterSuggestions', () => ({
  useClusterSuggestions: () => ({
    options: [],
    isLoading: false,
    collisionsByLabel: new Map(),
    findClusterByLabel: vi.fn(),
    atRestTotal: 0,
    atRestTruncated: false,
    isAtRestMode: false,
  }),
}));

vi.mock('../useClusterMutations', () => ({
  useClusterMutations: () => ({
    isPending: false,
    isReverting: false,
    merge: vi.fn(),
    assignToCluster: vi.fn(),
    rename: vi.fn(),
    createClusterForIdentity: vi.fn(),
    reassign: vi.fn(),
    split: vi.fn(),
    revertMerge: vi.fn(),
    rejectSuggestion: vi.fn(),
    splitGate: { disabled: false, title: undefined, 'aria-disabled': false },
  }),
}));

const createWrapper = () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { wrapper, queryClient };
};

const match = (label: string, cluster_id = `cluster-${label}`) => ({
  cluster_id,
  label,
  similarity: 0.9,
  identity_count: 2,
});

const member = (overrides: Partial<DetectedIdentity> = {}): DetectedIdentity => ({
  identity_id: 'id-1',
  representative_id: 'rep-1',
  media_id: 1,
  cluster_id: 'cluster-a',
  cluster_label: null,
  is_auto_label: false,
  is_pinned: false,
  bbox: { x: 0, y: 0, width: 1, height: 1 },
  confidence: 1,
  similarity: 1,
  detected_at: '',
  ...overrides,
});

const renderItem = (cluster: ClusterGroup, inlineSuggestionMatch?: ProjectedSuggestion) => {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <IdentityClusterItem cluster={cluster} canLabel canMutate inlineSuggestionMatch={inlineSuggestionMatch} />
    </QueryClientProvider>,
  );
};

describe('DEFWAVE-2 identity cluster regressions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('chunks inline suggestion requests at 100 ids and keeps successful chunks when one fails', async () => {
    const fetchMock = vi.mocked(recognitionApi.fetchIdentitiesSuggestions);
    fetchMock.mockImplementation(async (ids) => {
      if (ids[0] === 'identity-100') {
        throw new Error('chunk unavailable');
      }
      const firstId = ids[0];
      if (!firstId) {
        throw new Error('Expected a non-empty batch');
      }
      return {
        matches: {
          [firstId]: [match(firstId === 'identity-0' ? 'Ada' : 'Grace')],
        },
      };
    });

    const identityIds = Array.from({ length: 201 }, (_, index) => `identity-${index}`);
    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useInlineSuggestionBatch(identityIds), { wrapper });

    await waitFor(() => {
      expect(result.current.getMatch('identity-0')?.label).toBe('Ada');
      expect(result.current.getMatch('identity-200')?.label).toBe('Grace');
    });

    const batches = fetchMock.mock.calls.map(([ids]) => ids);
    expect(batches).toHaveLength(3);
    expect(batches.map((ids) => ids.length)).toEqual([100, 100, 1]);
    expect(batches[0]).toEqual(identityIds.slice(0, 100));
    expect(batches[1]).toEqual(identityIds.slice(100, 200));
    expect(batches[2]).toEqual(identityIds.slice(200));
    expect(result.current.getMatch('identity-100')).toBeUndefined();
  });

  it('includes auto-labeled clusters in inline suggestion batch ids', () => {
    const autoLabeled: ClusterGroup = {
      key: 'cluster:auto',
      clusterId: 'cluster-auto',
      label: 'cluster-generated',
      isAutoLabel: true,
      clusteringPending: false,
      members: [member({ identity_id: 'auto-id' })],
    };
    const humanLabeled: ClusterGroup = {
      ...autoLabeled,
      key: 'cluster:human',
      clusterId: 'cluster-human',
      label: 'Ada Lovelace',
      isAutoLabel: false,
      members: [member({ identity_id: 'human-id' })],
    };

    expect(unlabeledSuggestionBatchIds([autoLabeled, humanLabeled])).toEqual(['auto-id']);
  });

  it('shows the inline confirmation prompt for an auto-labeled cluster', () => {
    const cluster: ClusterGroup = {
      key: 'cluster:auto',
      clusterId: 'cluster-auto',
      label: 'cluster-generated',
      isAutoLabel: true,
      clusteringPending: false,
      members: [member({ identity_id: 'auto-id' })],
    };

    renderItem(cluster, {
      identityId: 'auto-id',
      clusterId: 'cluster-ada',
      label: 'Ada Lovelace',
      similarity: 0.92,
      identityCount: 3,
    });

    expect(screen.getByText('Ada Lovelace')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Yes' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'No' })).toBeInTheDocument();
  });

  it('uses representative face imagery first and attachment imagery as the fallback for split groups', () => {
    const members = [
      member({
        identity_id: 'id-a1',
        media_id: 1,
        cluster_id: 'cluster-a',
        media_url: 'https://example.test/non-representative.jpg',
        representative_face: {
          identity_id: 'rep-a',
          media_id: 10,
          media_url: 'https://example.test/representative.jpg',
          bbox: { x: 10, y: 10, width: 20, height: 20 },
        },
      }),
      member({ identity_id: 'id-a2', media_id: 2, cluster_id: 'cluster-a' }),
      member({
        identity_id: 'id-b1',
        media_id: 3,
        cluster_id: 'cluster-b',
        media_url: null,
        attachment_url: 'https://example.test/attachment.jpg',
        representative_face: {
          identity_id: 'rep-b',
          media_id: 11,
          media_url: null,
          attachment_url: null,
          bbox: null,
        },
      }),
      member({ identity_id: 'id-b2', media_id: 4, cluster_id: 'cluster-b' }),
    ];
    const cluster: ClusterGroup = {
      key: 'person:1',
      clusterId: 'cluster-a',
      personId: '1',
      clusterIds: ['cluster-a', 'cluster-b'],
      identityClusterIds: {
        'id-a1': 'cluster-a',
        'id-a2': 'cluster-a',
        'id-b1': 'cluster-b',
        'id-b2': 'cluster-b',
      },
      label: 'Ada Lovelace',
      isAutoLabel: false,
      clusteringPending: false,
      members,
    };

    renderItem(cluster);
    fireEvent.click(screen.getByRole('button', { name: /split group/i }));

    const firstGroupImage = screen
      .getByRole('radio', { name: 'Face group 1 · 2 faces' })
      .closest('label')
      ?.querySelector('img');
    const secondGroupImage = screen
      .getByRole('radio', { name: 'Face group 2 · 2 faces' })
      .closest('label')
      ?.querySelector('img');
    expect(firstGroupImage).toHaveAttribute('src', 'https://example.test/representative.jpg');
    expect(secondGroupImage).toHaveAttribute('src', 'https://example.test/attachment.jpg');
  });
});
