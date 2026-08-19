import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  RouterProvider,
  createMemoryRouter,
  useSearchParams,
} from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { fetchClusterMembers } from '../../../api/recognition';
import { ClusterPanelProvider, useClusterPanel } from '../ClusterPanelContext';
import { MergeSurvivorProvider } from '../identity-clusters/MergeSurvivorContext';
import { ScanTabContent } from '../ScanTabContent';

/**
 * UXW2-4 / A4 — review panel is a legible place:
 * (a) visible Back + "Review these faces" heading,
 * (b) mode persisted as panel=review&cluster=<id> (NAV-11),
 * (c) role="status" announcement (A11Y-21),
 * (d) real router history: replace on close so Back does not reopen.
 *
 * Real createMemoryRouter + ClusterPanelProvider + ClusterReviewPanel +
 * useOpenReviewTargetLifecycle + useWorkbenchFilters. Members fetch is mocked.
 */

const setSearchParamsSpy = vi.fn();

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
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

vi.mock('../../../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../../../api/recognition')>(
    '../../../api/recognition',
  );
  return {
    ...actual,
    fetchClusterMembers: vi.fn(),
  };
});

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

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useSearchParams: () => {
      const [params, set] = actual.useSearchParams();
      const wrapped: typeof set = (...args: Parameters<typeof set>) => {
        setSearchParamsSpy(...args);
        return set(...args);
      };
      return [params, wrapped];
    },
  };
});

interface ReviewQueueStubProps {
  onReview?: (clusterId: string) => void;
}

vi.mock('../identity-clusters', async () => {
  const actual = await vi.importActual<typeof import('../identity-clusters')>('../identity-clusters');
  const ReviewQueueStub = React.forwardRef<unknown, ReviewQueueStubProps>(function ReviewQueueStub(props) {
    return (
      <div data-testid="review-queue">
        <h3 id="acx-workbench-queue-heading">Review Suggestions</h3>
        <button type="button" data-acx-review-trigger="true" onClick={() => props.onReview?.('cluster-42')}>
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

const SameTickDriver = (): React.JSX.Element => {
  const { dispatchClusterPanel } = useClusterPanel();
  return (
    <button
      type="button"
      onClick={() => {
        dispatchClusterPanel({ type: 'open_review', clusterId: 'c-same' });
        dispatchClusterPanel({ type: 'close' });
      }}
    >
      same-tick
    </button>
  );
};

const renderScanTab = (initialEntry: string) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [
      {
        path: '*',
        element: (
          <QueryClientProvider client={client}>
            <MergeSurvivorProvider>
              <ClusterPanelProvider>
                <ScanTabContent />
                <RouteProbe />
                <SameTickDriver />
              </ClusterPanelProvider>
            </MergeSurvivorProvider>
          </QueryClientProvider>
        ),
      },
    ],
    { initialEntries: [initialEntry] },
  );
  render(<RouterProvider router={router} />);
  return router;
};

describe('ScanTabContent — UXW2-4 review panel legibility', () => {
  beforeEach(() => {
    setSearchParamsSpy.mockClear();
    vi.mocked(fetchClusterMembers).mockResolvedValue({
      members: [],
      limit: 1,
      total: 0,
      truncated: false,
    });
  });

  afterEach(cleanup);

  it('opening review persists panel=review&cluster=<id> in the URL', async () => {
    const user = userEvent.setup();
    renderScanTab('/workbench?tab=scan');

    await user.click(screen.getByRole('button', { name: 'Review' }));

    await waitFor(() => {
      expect(screen.getByTestId('route-probe').textContent).toContain('panel=review');
    });
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
    const writes = setSearchParamsSpy.mock.calls.filter((call) => typeof call[0] === 'function');
    expect(writes.length).toBeGreaterThanOrEqual(1);
    expect(writes[writes.length - 1]?.[1]).toEqual({ replace: true });
  });

  it('mounting at panel=review&cluster=<id> restores the review panel', async () => {
    renderScanTab('/workbench?tab=scan&panel=review&cluster=cluster-42');

    expect(await screen.findByRole('heading', { level: 2, name: /review these faces/i })).toBeInTheDocument();
    expect(screen.queryByTestId('review-queue')).not.toBeInTheDocument();
  });

  it('Back returns to the queue, restores focus, and keeps rq=/tab=', async () => {
    const user = userEvent.setup();
    const router = renderScanTab('/workbench?tab=scan&rq=assignment.all.0&panel=review&cluster=cluster-42');

    await user.click(await screen.findByRole('button', { name: '← Back to Review Suggestions' }));

    expect(screen.getByTestId('review-queue')).toBeInTheDocument();
    expect(screen.getByTestId('route-probe').textContent).not.toContain('panel=');
    expect(screen.getByTestId('route-probe').textContent).not.toContain('cluster=');
    expect(screen.getByTestId('route-probe').textContent).toContain('tab=scan');
    expect(screen.getByTestId('route-probe').textContent).toContain('rq=assignment.all.0');
    expect(screen.getByRole('status')).toHaveTextContent('Returned to review suggestions');
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Review' })).toHaveFocus();
    });

    await router.navigate(-1);
    expect(screen.getByTestId('review-queue')).toBeInTheDocument();
    expect(screen.getByTestId('route-probe').textContent).not.toContain('panel=review');
  });

  it('same-tick open then retire-close does not leave panel=review in the URL', async () => {
    const user = userEvent.setup();
    renderScanTab('/workbench?tab=scan');

    await user.click(screen.getByRole('button', { name: 'same-tick' }));

    expect(screen.getByTestId('route-probe').textContent).not.toContain('panel=review');
    expect(screen.getByTestId('route-probe').textContent).not.toContain('cluster=c-same');
  });

  it('opening review over an overlay restores that overlay on close', async () => {
    const user = userEvent.setup();
    renderScanTab('/workbench?tab=scan&panel=conflicts');

    await user.click(screen.getByRole('button', { name: 'Review' }));
    await waitFor(() => {
      expect(screen.getByTestId('route-probe').textContent).toContain('panel=review');
    });

    await user.click(screen.getByRole('button', { name: '← Back to Review Suggestions' }));

    expect(screen.getByTestId('route-probe').textContent).toContain('panel=conflicts');
    expect(screen.getByTestId('route-probe').textContent).not.toContain('cluster=');
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
