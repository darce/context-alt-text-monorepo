import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { resetConfigCache } from '../../../../api/config';
import {
  dismissCluster,
  fetchTopUnlabeledClusters,
  mergeCluster,
  updateClusterLabel,
} from '../../../../api/recognition';
import { DATA_SOURCE, PROJECTION_STATUS } from '../../../../api/recognition/types';
import { TopClustersSection } from '../TopClustersSection';
import type { TopUnlabeledCluster, TopUnlabeledClustersResponse } from '../../../../api/recognition/types';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (template: string, ...args: (string | number)[]) => {
    let index = 0;
    return template.replace(/%d/g, () => String(args[index++]));
  },
}));

vi.mock('../../../../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../../../../api/recognition')>('../../../../api/recognition');
  return {
    ...actual,
    mergeCluster: vi.fn().mockResolvedValue(undefined),
    updateClusterLabel: vi.fn().mockResolvedValue(undefined),
    fetchTopUnlabeledClusters: vi.fn(),
    dismissCluster: vi.fn().mockResolvedValue(undefined),
  };
});

const renderSection = (onLabel = vi.fn(), onReview = vi.fn()) => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return {
    onLabel,
    onReview,
    ...render(
      <QueryClientProvider client={queryClient}>
        <TopClustersSection tenantId="tenant-1" onLabel={onLabel} onReview={onReview} />
      </QueryClientProvider>,
    ),
  };
};

const clusterWithSuggestion = (): TopUnlabeledCluster => ({
  id: 'cluster-1',
  tenant_id: 'tenant-1',
  label: null,
  is_labeled: false,
  is_auto_label: false,
  identity_count: 3,
  user_confirmed: false,
  suggested_label: 'Maria Correonero',
  suggested_label_source: 'similar_cluster',
  suggested_label_confidence: 0.62,
  suggested_target_cluster_id: 'cluster-target',
  representatives: [
    {
      id: 'rep-1',
      media_id: 10,
      thumb_url: 'http://example.test/thumb-1.jpg',
      is_pinned: false,
    },
  ],
});

const topUnlabeledResponse = (
  clusters: TopUnlabeledCluster[],
  singletonCount = 0,
  hasClusters = true,
): TopUnlabeledClustersResponse => ({
  clusters,
  limit: 20,
  total: clusters.length,
  truncated: false,
  singleton_count: singletonCount,
  has_clusters: hasClusters,
  data_source: DATA_SOURCE.LOCAL_PROJECTION,
});

describe('TopClustersSection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.AltContextAdmin = {
      nonce: 'test-nonce',
      tenant_id: 'tenant-1',
      endpoints: {
        recognitionClusters: 'http://localhost/recognition/clusters',
      },
    };
    resetConfigCache();
  });

  it('renders cluster cards when top-unlabeled query succeeds', async () => {
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue(topUnlabeledResponse([clusterWithSuggestion()]));
    const { onReview } = renderSection();

    await waitFor(() => {
      expect(fetchTopUnlabeledClusters).toHaveBeenCalledWith('tenant-1', 20);
    });

    expect(screen.getByText('Name These People')).toBeInTheDocument();
    expect(screen.getByText('Is this Maria Correonero?')).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Review' }));
    expect(onReview).toHaveBeenCalledWith('cluster-1');
  });

  it('returns null while loading and on query error', async () => {
    vi.mocked(fetchTopUnlabeledClusters).mockImplementationOnce(
      () =>
        new Promise<TopUnlabeledClustersResponse>((resolve) => {
          void resolve;
        }),
    );
    const { container, unmount } = renderSection();
    expect(container.firstChild).toBeNull();
    unmount();

    vi.mocked(fetchTopUnlabeledClusters).mockRejectedValueOnce(new Error('boom'));
    const rendered = renderSection();

    await waitFor(() => {
      expect(fetchTopUnlabeledClusters).toHaveBeenCalled();
    });

    expect(rendered.container.firstChild).toBeNull();
  });

  it('renders an informational message when only singleton clusters are returned', async () => {
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue(topUnlabeledResponse([], 1));
    renderSection();

    await waitFor(() => {
      expect(fetchTopUnlabeledClusters).toHaveBeenCalled();
    });

    expect(screen.getByText('Name These People')).toBeInTheDocument();
    expect(
      screen.getByText(
        'All detected groups contain only a single photo. Groups with multiple photos will appear here.',
      ),
    ).toBeInTheDocument();
  });

  it('renders explicit zero-pending guidance when all recognized groups are already labeled', async () => {
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue(topUnlabeledResponse([], 0, true));

    renderSection();

    await waitFor(() => {
      expect(fetchTopUnlabeledClusters).toHaveBeenCalled();
    });

    expect(screen.getByText('Name These People')).toBeInTheDocument();
    expect(
      screen.getByText('Everyone already has a label. New unlabeled groups will appear here after future scans.'),
    ).toBeInTheDocument();
  });

  it('renders explicit empty-backend guidance when no projected clusters exist yet', async () => {
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue(topUnlabeledResponse([], 0, false));

    renderSection();

    await waitFor(() => {
      expect(fetchTopUnlabeledClusters).toHaveBeenCalled();
    });

    expect(screen.getByText('Name These People')).toBeInTheDocument();
    expect(
      screen.getByText('No recognized people are available yet. Run a scan to build the naming queue.'),
    ).toBeInTheDocument();
  });

  it('renders a retryable warning when top-unlabeled data is unavailable', async () => {
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue({
      ...topUnlabeledResponse([]),
      data_source: DATA_SOURCE.UNAVAILABLE,
      projection_status: PROJECTION_STATUS.BOOTSTRAPPING,
    });
    renderSection();

    await waitFor(() => {
      expect(fetchTopUnlabeledClusters).toHaveBeenCalled();
    });

    expect(screen.getByText('Local identities are still syncing')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('supports confirming suggested labels', async () => {
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue(topUnlabeledResponse([clusterWithSuggestion()]));
    renderSection();

    await waitFor(() => {
      expect(fetchTopUnlabeledClusters).toHaveBeenCalled();
    });

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Yes' }));

    expect(mergeCluster).toHaveBeenCalledWith('cluster-1', 'cluster-target', 'Maria Correonero');
    expect(updateClusterLabel).not.toHaveBeenCalled();
  });

  it('supports dismissing suggested labels', async () => {
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue(topUnlabeledResponse([clusterWithSuggestion()]));
    renderSection();

    await waitFor(() => {
      expect(fetchTopUnlabeledClusters).toHaveBeenCalled();
    });

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'No' }));

    expect(dismissCluster).toHaveBeenCalledWith('cluster-1');
  });

  it('renders backend-fallback clusters as read-only until local sync completes', async () => {
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue({
      ...topUnlabeledResponse([clusterWithSuggestion()]),
      data_source: DATA_SOURCE.BACKEND_PROXY,
    });

    renderSection();

    await waitFor(() => {
      expect(fetchTopUnlabeledClusters).toHaveBeenCalled();
    });

    expect(
      screen.getByText(
        'These clusters are visible while local sync catches up. Curation stays disabled until projected results are available locally.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Yes' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'No' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Review' })).not.toBeInTheDocument();
  });
});
