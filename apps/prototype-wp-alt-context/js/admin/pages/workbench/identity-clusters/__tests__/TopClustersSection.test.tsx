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
import { TopClustersSection } from '../TopClustersSection';
import type { TopUnlabeledCluster } from '../../../../api/recognition/types';

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

describe('TopClustersSection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.AltContextAdmin = {
      nonce: 'test-nonce',
      tenant_id: 'tenant-1',
      endpoints: {
        recognitionClusters: 'http://localhost/recognition/clusters',
      },
    } as unknown as NonNullable<Window['AltContextAdmin']>;
    resetConfigCache();
  });

  it('renders cluster cards when top-unlabeled query succeeds', async () => {
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue([clusterWithSuggestion()]);
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
        new Promise<TopUnlabeledCluster[]>((resolve) => {
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

  it('supports confirming suggested labels', async () => {
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue([clusterWithSuggestion()]);
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
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue([clusterWithSuggestion()]);
    renderSection();

    await waitFor(() => {
      expect(fetchTopUnlabeledClusters).toHaveBeenCalled();
    });

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'No' }));

    expect(dismissCluster).toHaveBeenCalledWith('cluster-1');
  });
});
