import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  RouterProvider,
  createMemoryRouter,
  useSearchParams,
} from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { fetchClusterMembers } from '../../../api/recognition';
import { HTTPError } from '../../../utils/http';
import { ClusterPanelProvider } from '../ClusterPanelContext';
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
  const ReviewQueueStub = React.forwardRef<unknown, ReviewQueueStubProps>(function ReviewQueueStub(props, _ref) {
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

const clusterNotFound = (clusterId: string): HTTPError =>
  new HTTPError({
    status: 404,
    retryAfterSeconds: undefined,
    endpoint: `/acx/v1/recognition/clusters/${clusterId}/members`,
    bodyPreview: 'cluster_not_found',
    message: 'cluster not found',
  });

const functionalWrites = (): Array<[(prev: URLSearchParams) => URLSearchParams, unknown?]> =>
  setSearchParamsSpy.mock.calls.filter((call) => typeof call[0] === 'function') as Array<
    [(prev: URLSearchParams) => URLSearchParams, unknown?]
  >;

/** status live regions are unnamed; pin role + text via the `name` callback. */
const statusNamed =
  (text: string) =>
  (_accessibleName: string, element: Element): boolean =>
    (element.textContent ?? '').trim() === text;

const queryClients: QueryClient[] = [];

const renderScanTab = (initialEntry: string) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  queryClients.push(client);
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

  afterEach(async () => {
    const clients = queryClients.splice(0);
    await Promise.all(clients.map((client) => client.cancelQueries()));
    clients.forEach((client) => client.clear());
    cleanup();
  });

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
    expect(
      screen.getByRole('status', {
        name: statusNamed('Reviewing faces — press Back to return to suggestions'),
      }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId('review-queue')).not.toBeInTheDocument();
    expect(screen.getByTestId('route-probe').textContent).toContain('tab=scan');
    const writes = functionalWrites();
    expect(writes).toHaveLength(1);
    const opened = writes[0]?.[0](new URLSearchParams('tab=scan'));
    expect(opened.get('panel')).toBe('review');
    expect(opened.get('cluster')).toBe('cluster-42');
    expect(writes[0]?.[1]).toEqual({ replace: true });
  });

  it('mounting at panel=review&cluster=<id> restores the review panel', async () => {
    renderScanTab('/workbench?tab=scan&panel=review&cluster=cluster-42');

    expect(await screen.findByRole('heading', { level: 2, name: /review these faces/i })).toBeInTheDocument();
    expect(screen.queryByTestId('review-queue')).not.toBeInTheDocument();
  });

  it('Back returns to the queue, restores focus, and keeps rq=/tab=', async () => {
    const user = userEvent.setup();
    const router = renderScanTab('/workbench?tab=scan&rq=assignment.all.0');

    await user.click(screen.getByRole('button', { name: 'Review' }));
    await waitFor(() => {
      expect(screen.getByTestId('route-probe').textContent).toContain('panel=review');
    });

    setSearchParamsSpy.mockClear();
    await user.click(await screen.findByRole('button', { name: '← Back to Review Suggestions' }));

    expect(screen.getByTestId('review-queue')).toBeInTheDocument();
    expect(screen.getByTestId('route-probe').textContent).not.toContain('panel=');
    expect(screen.getByTestId('route-probe').textContent).not.toContain('cluster=');
    expect(screen.getByTestId('route-probe').textContent).toContain('tab=scan');
    expect(screen.getByTestId('route-probe').textContent).toContain('rq=assignment.all.0');
    expect(
      screen.getByRole('status', { name: statusNamed('Returned to review suggestions') }),
    ).toBeInTheDocument();

    const closeWrites = functionalWrites();
    expect(closeWrites).toHaveLength(1);
    const closed = closeWrites[0]?.[0](
      new URLSearchParams('tab=scan&rq=assignment.all.0&panel=review&cluster=cluster-42'),
    );
    expect(closed.get('panel')).toBeNull();
    expect(closed.get('cluster')).toBeNull();
    expect(closed.get('rq')).toBe('assignment.all.0');
    expect(closed.get('tab')).toBe('scan');

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Review' })).toHaveFocus();
    });

    await act(async () => {
      await router.navigate(-1);
    });
    expect(screen.getByTestId('review-queue')).toBeInTheDocument();
    expect(screen.getByTestId('route-probe').textContent).not.toContain('panel=review');
  });

  it('same-tick open then retire-close does not leave panel=review in the URL', async () => {
    vi.mocked(fetchClusterMembers).mockRejectedValue(clusterNotFound('cluster-42'));
    const user = userEvent.setup();
    renderScanTab('/workbench?tab=scan');

    await user.click(screen.getByRole('button', { name: 'Review' }));

    await waitFor(() => {
      expect(screen.getByTestId('route-probe').textContent).not.toContain('panel=review');
    });
    expect(screen.getByTestId('route-probe').textContent).not.toContain('cluster=cluster-42');
    expect(screen.getByTestId('review-queue')).toBeInTheDocument();
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
