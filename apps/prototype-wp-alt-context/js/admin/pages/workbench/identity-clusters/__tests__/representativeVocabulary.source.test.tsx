import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { BoundingBox } from '../../../../api/recognition/types/identity';
import type { DetectedIdentity } from '../../../../api/recognition';
import type { PendingMergeSuggestion, TopUnlabeledCluster } from '../../../../api/recognition/types';
import { NEXT_ACTION_KIND, NONE_REASON } from '../reviewQueueDriver';

/**
 * E21-20-REV1-06 / REV2-06 / TEST-15: module-mock sentinel discrimination.
 * Red against any surface that hardcodes the missing-representative string
 * or the gated-cluster phrasing instead of reading this module.
 */
const SENTINEL = 'SENTINEL_REPRESENTATIVE_IMAGE_UNAVAILABLE';
const SENTINEL_GATED = 'SENTINEL_GATED_CLUSTER_COPY';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (template: string, ...args: (string | number)[]) => {
    let index = 0;
    return template.replace(/%(\d+\$)?[sd]/g, () => String(args[index++] ?? ''));
  },
}));

vi.mock('../representativeVocabulary', () => ({
  REPRESENTATIVE_VOCABULARY: {
    imageUnavailable: SENTINEL,
  },
  gatedClusterCopy: () => SENTINEL_GATED,
}));

vi.mock('../useWorkbenchFindings', async () => {
  const actual = await vi.importActual<typeof import('../useWorkbenchFindings')>('../useWorkbenchFindings');
  return {
    ...actual,
    useWorkbenchFindings: vi.fn(),
  };
});

vi.mock('../useSuggestionReviewQueries', () => ({
  useSuggestionReviewQueries: vi.fn(() => ({
    assignmentQuery: { refetch: vi.fn() },
    mergeQuery: { refetch: vi.fn() },
    nameQuery: { refetch: vi.fn() },
    topUnlabeledQuery: { refetch: vi.fn() },
  })),
}));

const { ClusterPreview } = await import('../ClusterPreview');
const { TopClusterCard } = await import('../TopClusterCard');
const { SuggestionCard } = await import('../SuggestionCards');
const { MergeSuggestionCard } = await import('../MergeSuggestionCard');
const { WorkbenchFindingsPanel } = await import('../WorkbenchFindingsPanel');
const { useWorkbenchFindings } = await import('../useWorkbenchFindings');

const BBOX: BoundingBox = { x: 12, y: 24, width: 80, height: 96 };

const buildCluster = (): TopUnlabeledCluster => ({
  id: 'cluster-1',
  tenant_id: 'tenant-1',
  label: null,
  is_labeled: false,
  is_auto_label: false,
  identity_count: 1,
  user_confirmed: false,
  suggested_label: null,
  suggested_label_source: null,
  suggested_label_confidence: null,
  suggested_target_cluster_id: null,
  representatives: [
    {
      id: 'rep-1',
      media_id: 10,
      thumb_url: null,
      media_url: null,
      bbox: null,
      is_pinned: false,
    },
  ],
});

const buildPreviewRep = (): DetectedIdentity => ({
  identity_id: 'identity-1',
  representative_id: 'rep-1',
  media_id: 101,
  cluster_id: 'cluster-1',
  cluster_label: 'Known Person',
  is_auto_label: false,
  is_pinned: false,
  bbox: BBOX,
  confidence: 0.98,
  similarity: null,
  thumb_url: 'https://example.test/thumb.jpg',
  media_url: null,
});

const missingMerge: PendingMergeSuggestion = {
  id: 'merge-1',
  cluster_a_id: 'cluster-a',
  cluster_b_id: 'cluster-b',
  similarity: 0.87,
  status: 'pending',
};

describe('missing-representative vocabulary source', () => {
  afterEach(() => {
    cleanup();
  });

  it('TopClusterCard and ClusterPreview both render the REPRESENTATIVE_VOCABULARY sentinel', () => {
    render(<TopClusterCard cluster={buildCluster()} onLabel={() => undefined} />);
    expect(screen.getByRole('img', { name: SENTINEL })).toBeInTheDocument();
    cleanup();

    render(<ClusterPreview representative={buildPreviewRep()} memberCount={1} />);
    expect(screen.getByRole('img', { name: SENTINEL })).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'No image' })).not.toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'Representative image unavailable' })).not.toBeInTheDocument();
  });

  it('REV2-06: SuggestionCard, MergeSuggestionCard, and findings preview use the sentinel', () => {
    render(
      <SuggestionCard
        suggestion={{
          suggestionId: 'sugg-1',
          identityId: 'identity-1',
          clusterId: 'cluster-1',
          label: 'Alex',
          similarity: 0.9,
          identityCount: 3,
        }}
        onAccept={() => undefined}
        onReject={() => undefined}
        isPending={false}
        lowConfidenceThreshold={0.5}
      />,
    );
    expect(screen.getAllByRole('img', { name: SENTINEL })).toHaveLength(2);
    expect(screen.queryByRole('img', { name: 'No image' })).not.toBeInTheDocument();
    cleanup();

    render(
      <MergeSuggestionCard
        suggestion={missingMerge}
        onAccept={() => undefined}
        onReject={() => undefined}
        isPending={false}
      />,
    );
    expect(screen.getAllByRole('img', { name: SENTINEL })).toHaveLength(2);
    expect(screen.queryByRole('img', { name: 'No image' })).not.toBeInTheDocument();
    cleanup();

    vi.mocked(useWorkbenchFindings).mockReturnValue({
      counts: { assignments: 1, merges: 0, names: 0, unlabeledClusters: 0, total: 1 },
      previews: [
        {
          key: 'assignment-s1',
          thumbUrl: null,
          mediaUrl: null,
          label: null,
          labelIsSuggested: false,
          bbox: null,
        },
      ],
      zeroEvidenceClusterCount: 0,
      hasFindings: true,
      isLoading: false,
      isError: false,
      isTopUnlabeledError: false,
      isAssignmentError: false,
      isUnavailable: false,
      isReadOnly: false,
      queueSettled: true,
      nextAction: {
        kind: NEXT_ACTION_KIND.ASSIGNMENT,
        suggestionId: 's1',
        clusterId: 'c1',
        label: null,
      },
      queue: [],
    });
    render(<WorkbenchFindingsPanel />);
    expect(screen.getByRole('img', { name: SENTINEL })).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'Preview image unavailable' })).not.toBeInTheDocument();
  });

  it('REV2-06: findings repair row uses gatedClusterCopy sentinel', () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue({
      counts: { assignments: 1, merges: 0, names: 0, unlabeledClusters: 1, total: 2 },
      previews: [],
      zeroEvidenceClusterCount: 2,
      hasFindings: true,
      isLoading: false,
      isError: false,
      isTopUnlabeledError: false,
      isAssignmentError: false,
      isUnavailable: false,
      isReadOnly: false,
      queueSettled: true,
      nextAction: {
        kind: NEXT_ACTION_KIND.ASSIGNMENT,
        suggestionId: 's1',
        clusterId: 'c1',
        label: 'Ada',
      },
      queue: [],
    });

    render(<WorkbenchFindingsPanel />);
    expect(screen.getByText(SENTINEL_GATED)).toBeInTheDocument();
    expect(screen.queryByText('2 groups missing face data')).not.toBeInTheDocument();
    expect(screen.queryByText('2 clusters need face data resync')).not.toBeInTheDocument();
  });
});
