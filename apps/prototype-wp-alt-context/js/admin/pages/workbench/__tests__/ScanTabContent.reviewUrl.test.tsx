import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useSearchParams } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ClusterPanelProvider } from '../ClusterPanelContext';
import { ScanTabContent } from '../ScanTabContent';

/**
 * UXW2-4 / A4 — the review panel is a legible place, not a hidden slot swap:
 * (a) visible "← Back to Review Suggestions" affordance + visible heading,
 * (b) mode persisted in the hash as panel=review&cluster=<id> (NAV-11),
 * (c) role="status" announcement while reviewing (A11Y-21).
 *
 * Real MemoryRouter + real ClusterPanelProvider + real ClusterReviewPanel;
 * only the queue and unrelated chrome are stubbed.
 */

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (format: string, ...args: (string | number)[]) => {
    let index = 0;
    return format.replace(/%[sd]/g, () => String(args[index++] ?? ''));
  },
}));

vi.mock('../../../../components/ErrorBoundary', () => ({
  ErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('../../../hooks/useScrollRestoration', () => ({
  useScrollRestoration: () => undefined,
}));

vi.mock('../../../hooks/useWorkbenchFilters', () => ({
  useWorkbenchFilters: () => ({
    queueState: { index: 0, kind: 'all', band: 'all' },
    setQueueState: vi.fn(),
  }),
}));

vi.mock('../Panels', () => ({
  ScanActionPanel: () => <div data-testid="scan-action-panel" />,
}));

vi.mock('../JobTimeline', () => ({
  JobTimeline: () => <div data-testid="job-timeline" />,
}));

vi.mock('../identity-clusters/useShowAllClusterMembers', () => ({
  useShowAllClusterMembers: () => ({
    members: [],
    isLoading: false,
    isError: false,
    truncated: false,
    total: 0,
    isFullyLoaded: true,
    isExpanding: false,
    expandError: null,
    showAll: vi.fn(),
    refetch: vi.fn(),
  }),
}));

vi.mock('../identity-clusters/useOpenReviewTargetLifecycle', () => ({
  useOpenReviewTargetLifecycle: ({ requestedClusterId }: { requestedClusterId: string | null }) => ({
    reviewClusterId: requestedClusterId,
  }),
}));

vi.mock('../JobPipelineContext', () => ({
  useJobPipeline: () => ({
    scanRun: { isScanning: false, progress: null },
    status: {
      scanProgress: null,
      clusterProgress: null,
      currentPhase: 'idle',
      projectionSyncState: 'idle',
    },
    history: { activeJobIds: [], jobId: null },
    cancelScan: vi.fn(),
    retryScanStream: vi.fn(),
  }),
}));

vi.mock('../WorkbenchMediaContext', () => ({
  useWorkbenchMediaContext: () => ({ mediaQueue: { hasIdentities: true } }),
}));

vi.mock('../ReviewSurfaceContext', () => ({
  useReviewSurface: () => ({ cardPrimaryPresent: false, setCardPrimaryPresent: vi.fn() }),
}));

interface ReviewQueueStubProps {
  onReview?: (clusterId: string) => void;
}

vi.mock('../identity-clusters', async () => {
  const actual = await vi.importActual<typeof import('../identity-clusters')>('../identity-clusters');
  const ReviewQueueStub = React.forwardRef<unknown, ReviewQueueStubProps>(function ReviewQueueStub(props) {
    return (
      <div data-testid="review-queue">
        <h3 id="acx-workbench-queue-heading">Review Suggestions</h3>
        <button type="button" onClick={() => props.onReview?.('cluster-42')}>
          Review
        </button>
      </div>
    );
  });
  return {
    ...actual,
    ReviewQueue: ReviewQueueStub,
    ClusterLabelingPanel: () => <div data-testid="label-panel" />,
    WorkbenchFindingsPanel: () => <div data-testid="findings-panel" />,
  };
});

const RouteProbe = (): React.JSX.Element => {
  const [searchParams] = useSearchParams();
  return <div data-testid="route-probe">{searchParams.toString()}</div>;
};

const renderScanTab = (initialEntry: string): void => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <ClusterPanelProvider>
          <ScanTabContent />
          <RouteProbe />
        </ClusterPanelProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

describe('ScanTabContent — UXW2-4 review panel legibility', () => {
  afterEach(cleanup);

  it('opening review persists panel=review&cluster=<id> in the URL', async () => {
    const user = userEvent.setup();
    renderScanTab('/workbench?tab=scan');

    await user.click(screen.getByRole('button', { name: 'Review' }));

    expect(screen.getByTestId('route-probe').textContent).toContain('panel=review');
    expect(screen.getByTestId('route-probe').textContent).toContain('cluster=cluster-42');
    const heading = screen.getByRole('heading', { level: 2, name: /review these faces/i });
    expect(heading).toBeInTheDocument();
    expect(heading.textContent ?? '').not.toMatch(/cluster|face group/i);
    expect(screen.getByRole('button', { name: '← Back to Review Suggestions' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /close face-group review/i })).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(
      'Reviewing faces — press Back to return to suggestions',
    );
    expect(screen.queryByTestId('review-queue')).not.toBeInTheDocument();
    expect(screen.getByTestId('route-probe').textContent).toContain('tab=scan');
  });

  it('mounting at panel=review&cluster=<id> restores the review panel', () => {
    renderScanTab('/workbench?tab=scan&panel=review&cluster=cluster-42');

    expect(screen.getByRole('heading', { level: 2, name: /review these faces/i })).toBeInTheDocument();
    expect(screen.queryByTestId('review-queue')).not.toBeInTheDocument();
  });

  it('Back returns to the queue and clears both params in one write', async () => {
    const user = userEvent.setup();
    renderScanTab('/workbench?tab=scan&rq=all.all.0&panel=review&cluster=cluster-42');

    await user.click(screen.getByRole('button', { name: '← Back to Review Suggestions' }));

    expect(screen.getByTestId('review-queue')).toBeInTheDocument();
    expect(screen.getByTestId('route-probe').textContent).not.toContain('panel=');
    expect(screen.getByTestId('route-probe').textContent).not.toContain('cluster=');
    expect(screen.getByTestId('route-probe').textContent).toContain('tab=scan');
    expect(screen.getByTestId('route-probe').textContent).toContain('rq=all.all.0');
    expect(screen.getByRole('status')).toHaveTextContent('Returned to review suggestions');
  });

  it('cluster= without panel=review stays on the queue', () => {
    renderScanTab('/workbench?tab=scan&cluster=cluster-42');

    expect(screen.getByTestId('review-queue')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 2, name: /review these faces/i })).not.toBeInTheDocument();
  });

  it('panel=conflicts is not treated as review and survives', () => {
    renderScanTab('/workbench?tab=scan&panel=conflicts&cluster=x');

    expect(screen.getByTestId('review-queue')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 2, name: /review these faces/i })).not.toBeInTheDocument();
    expect(screen.getByTestId('route-probe').textContent).toContain('panel=conflicts');
  });

  it('panel=review without cluster stays on the queue', () => {
    renderScanTab('/workbench?tab=scan&panel=review');

    expect(screen.getByTestId('review-queue')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 2, name: /review these faces/i })).not.toBeInTheDocument();
  });
});
