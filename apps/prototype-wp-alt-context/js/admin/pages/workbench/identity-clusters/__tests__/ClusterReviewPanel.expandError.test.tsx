import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ClusterReviewPanel } from '../ClusterReviewPanel';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string, ...args: (string | number)[]) => {
    let index = 0;
    return format.replace(/%(s|d)/g, () => String(args[index++]));
  },
}));

vi.mock('../useShowAllClusterMembers', () => ({
  useShowAllClusterMembers: () => ({
    members: [],
    isLoading: false,
    isError: false,
    truncated: true,
    total: 4,
    isFullyLoaded: false,
    isExpanding: false,
    expandError: 'network down',
    showAll: vi.fn(),
    refetch: vi.fn(),
  }),
}));

vi.mock('../../ClusterPanelContext', () => ({
  useClusterPanel: () => ({
    clusterPanel: { mode: 'review', clusterId: 'cluster-1' },
    dispatchClusterPanel: vi.fn(),
  }),
}));

describe('W3-C-06 ClusterReviewPanel expandError', () => {
  it('pins expand-error copy', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ClusterReviewPanel clusterId="cluster-1" onClose={() => undefined} />
      </QueryClientProvider>,
    );
    expect(screen.getByText('Could not load every face in this group.')).toBeInTheDocument();
  });
});
