/**
 * UXPNET2-BR-03 — ReviewQueue auth-expired notice on the head item's existence probe.
 * Reuses the mounting/mocking harness from ReviewQueue.test.tsx.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  fetchClusterMembers,
  fetchPendingMergeSuggestions,
  fetchPendingNameSuggestions,
  fetchPendingSuggestions,
  fetchTopUnlabeledClusters,
} from '../../../../api/recognition';
import { resetConfigCache } from '../../../../api/config';
import { listRosterEntries, commitClusterToRosterEntry } from '../../../../api/rosterApi';
import { MergeSurvivorProvider } from '../MergeSurvivorContext';
import { ReviewQueue, type ReviewQueueHandle } from '../ReviewQueue';
import { AuthExpiredError } from '../../../../utils/http';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, number: number) => (number === 1 ? single : plural),
  sprintf: (format: string, ...args: (string | number)[]) => {
    let i = 0;
    return format.replace(/%(\d+)\$[sd]|%[sd]/g, () => String(args[i++]));
  },
}));

vi.mock('@radix-ui/react-avatar', async () => {
  const ReactMod = await import('react');
  return {
    Root: ReactMod.forwardRef(function MockRoot({ children, ...props }: Record<string, unknown>, ref: unknown) {
      return ReactMod.createElement(
        'span',
        { ...props, ref } as React.HTMLAttributes<HTMLSpanElement>,
        children as React.ReactNode,
      );
    }),
    Image: ReactMod.forwardRef(function MockImage(props: Record<string, unknown>, ref: unknown) {
      return ReactMod.createElement('img', { ...props, ref } as React.ImgHTMLAttributes<HTMLImageElement>);
    }),
    Fallback: ReactMod.forwardRef(function MockFallback() {
      return null;
    }),
  };
});

vi.mock('../../../../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../../../../api/recognition')>('../../../../api/recognition');
  return {
    ...actual,
    fetchPendingSuggestions: vi.fn(),
    fetchPendingMergeSuggestions: vi.fn(),
    fetchPendingNameSuggestions: vi.fn(),
    acceptSuggestion: vi.fn(),
    acceptMergeSuggestion: vi.fn(),
    acceptNameSuggestion: vi.fn(),
    rejectSuggestion: vi.fn(),
    rejectMergeSuggestion: vi.fn(),
    rejectNameSuggestion: vi.fn(),
    bulkAcceptSuggestions: vi.fn(),
    fetchClusterMembers: vi.fn().mockResolvedValue({
      members: [],
      limit: 25,
      total: 0,
      truncated: false,
    }),
    fetchTopUnlabeledClusters: vi.fn(),
    dismissCluster: vi.fn().mockResolvedValue(undefined),
    mergeCluster: vi.fn().mockResolvedValue(undefined),
    updateClusterLabel: vi.fn().mockResolvedValue(undefined),
  };
});

vi.mock('../../../../api/rosterApi', () => ({
  commitClusterToRosterEntry: vi.fn().mockResolvedValue({
    cluster_id: 'cluster-1',
    person_id: 7,
    person_uuid: 'person-uuid-7',
    person_name: 'Alex',
    updated_at: '2026-01-01T00:00:00Z',
  }),
  listRosterEntries: vi.fn().mockResolvedValue([
    {
      id: 7,
      person_uuid: 'person-uuid-7',
      name: 'Alex',
      tags: [],
      cluster_count: 0,
      clusters: [],
      queue_memberships: [],
      updated_at: '2026-01-01T00:00:00Z',
      source_version: 1,
      projection_status: 'current',
      projection_refreshed_at: null,
    },
  ]),
}));

interface HarnessProps {
  initialIndex?: number;
  queueRef?: React.RefObject<ReviewQueueHandle>;
}

const ReviewQueueHarness = ({ initialIndex = 0, queueRef }: HarnessProps): React.JSX.Element => {
  const [index, setIndex] = React.useState(initialIndex);
  const [kind, setKind] = React.useState<'all' | 'assignment' | 'merge'>('all');
  const [band, setBand] = React.useState<'all' | 'strong' | 'weaker'>('all');
  const [selectedIds, setSelectedIds] = React.useState<Set<string>>(() => new Set());
  return (
    <ReviewQueue
      ref={queueRef}
      index={index}
      onIndexChange={(next) => setIndex(Math.max(0, next))}
      onClampIndex={(next) => setIndex(Math.max(0, next))}
      onStepIndex={(delta, length) => {
        setIndex((prev) => {
          if (length <= 0) {
            return 0;
          }
          const clamped = Math.min(Math.max(0, prev), length - 1);
          return Math.min(Math.max(0, clamped + delta), length - 1);
        });
      }}
      kind={kind}
      onKindChange={(next) => {
        setKind(next);
        setIndex(0);
      }}
      band={band}
      onBandChange={(next) => {
        setBand(next);
        setIndex(0);
      }}
      onClearFilters={() => {
        setKind('all');
        setBand('all');
        setIndex(0);
      }}
      selectedIds={selectedIds}
      onSelectedIdsChange={setSelectedIds}
    />
  );
};

const withQueueProviders = (queryClient: QueryClient, children: React.ReactNode) => (
  <QueryClientProvider client={queryClient}>
    <MergeSurvivorProvider>{children}</MergeSurvivorProvider>
  </QueryClientProvider>
);

const renderQueue = (props: HarnessProps = {}) => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, retryDelay: 0 },
    },
  });

  const utils = render(withQueueProviders(queryClient, <ReviewQueueHarness {...props} />));

  return { queryClient, ...utils };
};

describe('ReviewQueue auth-expired notice (UXPNET2-BR-03)', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  beforeEach(() => {
    window.AltContextAdmin = {
      nonce: 'test-nonce',
      ajaxUrl: '/wp-admin/admin-ajax.php',
      endpoints: {
        recognitionSuggestions: 'http://localhost/recognition/suggestions',
        recognitionMergeSuggestions: 'http://localhost/recognition/suggestions/merge',
        recognitionNameSuggestions: 'http://localhost/recognition/suggestions/name',
        recognitionBulkAcceptSuggestions: 'http://localhost/recognition/suggestions/bulk-accept',
        recognitionClusters: 'http://localhost/recognition/clusters',
      },
      tenant_id: 'test-tenant-id',
    };

    vi.mocked(fetchPendingNameSuggestions).mockResolvedValue({ suggestions: [], limit: 25, offset: 0 });
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue({
      clusters: [],
      limit: 20,
      total: 0,
      truncated: false,
      singleton_count: 0,
    } as never);
    vi.mocked(fetchPendingMergeSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    vi.mocked(listRosterEntries).mockResolvedValue([
      {
        id: 7,
        person_uuid: 'person-uuid-7',
        name: 'Alex',
        tags: [],
        cluster_count: 0,
        clusters: [],
        queue_memberships: [],
        updated_at: '2026-01-01T00:00:00Z',
        source_version: 1,
        projection_status: 'current',
        projection_refreshed_at: null,
      },
    ]);
    vi.mocked(commitClusterToRosterEntry).mockResolvedValue({
      cluster_id: 'cluster-1',
      person_id: 7,
      person_uuid: 'person-uuid-7',
      person_name: 'Alex',
      updated_at: '2026-01-01T00:00:00Z',
    });
    resetConfigCache();

    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [
        {
          id: 'sugg-1',
          identity_id: 'identity-1',
          suggested_cluster_id: 'cluster-1',
          representative_similarity: 0.9,
          avg_member_similarity: 0.85,
          cluster_label: 'Alex',
          cluster_identity_count: 3,
        },
      ],
      limit: 10,
      offset: 0,
    });
  });

  it('head item existence-probe AuthExpiredError renders auth-expired notice, queue stays mounted (INT-11)', async () => {
    vi.mocked(fetchClusterMembers).mockRejectedValue(
      new AuthExpiredError({ endpoint: '/acx/v1/clusters/cluster-1/members', status: 401 }),
    );

    renderQueue();

    await screen.findByTestId('acx-review-card');

    const notice = await waitFor(() => {
      const el = document.querySelector('.acx-review-queue')?.querySelector('[data-testid="acx-user-facing-error"]');
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });

    expect(notice).toHaveAttribute('data-error-kind', 'auth-expired');
    expect(screen.getByText('Review Suggestions')).toBeInTheDocument();
  });

  it('healthy probe: no acx-user-facing-error element renders', async () => {
    vi.mocked(fetchClusterMembers).mockResolvedValue({
      members: [],
      limit: 1,
      total: 0,
      truncated: false,
    });

    renderQueue();

    await screen.findByTestId('acx-review-card');
    expect(screen.queryByTestId('acx-user-facing-error')).not.toBeInTheDocument();
    expect(screen.getByText('Review Suggestions')).toBeInTheDocument();
  });
});
