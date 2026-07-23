import React, { useState } from 'react';
import { act, cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

import { ScanTabContent } from '../ScanTabContent';

/**
 * E21-10 Slice 3 — media-table expand state as URL param.
 *
 * Discriminating cases:
 * - media=expanded deep-link renders expanded (full table, not summary bar)
 * - absent media + hasFindings → collapsed summary
 * - findings-arrival auto-collapse clears media=expanded from the URL
 * - onExpand writes media=expanded
 */

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, _plural: string, n: number) => (n === 1 ? single : _plural),
  sprintf: (fmt: string, ...args: unknown[]) => {
    let i = 0;
    return fmt.replace(/%[ds]/g, () => String(args[i++]));
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
  isClusteringActive: () => false,
}));

vi.mock('../JobTimeline', () => ({
  JobTimeline: () => <div data-testid="job-timeline" />,
}));

vi.mock('../identity-clusters', () => ({
  ClusterLabelingPanel: () => <div data-testid="label-panel" />,
  ClusterReviewPanel: () => <div data-testid="review-panel" />,
  ReviewQueue: React.forwardRef<unknown, Record<string, unknown>>(function ReviewQueueStub() {
    return <div data-testid="review-queue" />;
  }),
  WorkbenchFindingsPanel: () => <div data-testid="findings-panel" />,
}));

const findingsState = {
  hasFindings: true,
  isLoading: false,
  isError: false,
  isUnavailable: false,
};

vi.mock('../identity-clusters/useWorkbenchFindings', () => ({
  useWorkbenchFindings: () => ({ ...findingsState }),
}));

vi.mock('../identity-clusters/useAriaAnnounce', () => ({
  useAriaAnnounce: () => ({ message: '', seq: 0, announce: vi.fn() }),
}));

vi.mock('../identity-clusters/useOpenReviewTargetLifecycle', () => ({
  useOpenReviewTargetLifecycle: () => ({ reviewClusterId: null }),
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

vi.mock('../ClusterPanelContext', () => ({
  useClusterPanel: () => ({
    clusterPanel: { mode: 'none', clusterId: null },
    dispatchClusterPanel: vi.fn(),
  }),
}));

vi.mock('../WorkbenchMediaContext', () => ({
  useWorkbenchMediaContext: () => ({
    mediaQueue: {
      hasIdentities: true,
      mediaQuery: {
        data: { total: 3, items: [] },
        itemsWithIdentities: [],
        isPending: false,
        isFetching: false,
        isError: false,
      },
    },
    selection: {
      selectedMedia: [],
      selection: new Set(),
      toggleRow: vi.fn(),
      toggleAll: vi.fn(),
      isPageFullySelected: false,
    },
    filters: {
      searchQuery: '',
      currentPage: 1,
      perPage: 10,
      statusFilter: 'all',
      setCurrentPage: vi.fn(),
      setPerPage: vi.fn(),
      handleSearchChange: vi.fn(),
      handleStatusChange: vi.fn(),
      normalizedSearch: '',
    },
  }),
}));

vi.mock('../MediaSelection', () => ({
  MediaSelection: ({
    collapsed,
    onExpand,
  }: {
    collapsed?: boolean;
    onExpand?: () => void;
  }) =>
    collapsed ? (
      <div data-testid="media-collapsed">
        <button type="button" onClick={onExpand}>
          Show media table
        </button>
      </div>
    ) : (
      <div data-testid="media-expanded">Media table</div>
    ),
}));

const LocationProbe = (): React.JSX.Element => {
  const location = useLocation();
  return <output data-testid="location-search">{location.search}</output>;
};

/** Inner route element: tick re-renders ScanTabContent without remounting the router. */
const WorkbenchProbe = (): React.JSX.Element => {
  const [, setTick] = useState(0);
  return (
    <>
      <button type="button" data-testid="force-rerender" onClick={() => setTick((t) => t + 1)}>
        rerender
      </button>
      <ScanTabContent />
      <LocationProbe />
    </>
  );
};

const ScanHarness = ({ initialEntry }: { initialEntry: string }): React.JSX.Element => (
  <MemoryRouter initialEntries={[initialEntry]}>
    <Routes>
      <Route path="/workbench" element={<WorkbenchProbe />} />
    </Routes>
  </MemoryRouter>
);

describe('ScanTabContent — media expand URL state (E21-10 Slice 3)', () => {
  beforeEach(() => {
    findingsState.hasFindings = true;
    findingsState.isLoading = false;
    findingsState.isError = false;
    findingsState.isUnavailable = false;
  });

  afterEach(cleanup);

  it('collapses media when findings exist and media param is absent', () => {
    render(<ScanHarness initialEntry="/workbench" />);
    expect(screen.getByTestId('media-collapsed')).toBeInTheDocument();
    expect(screen.queryByTestId('media-expanded')).not.toBeInTheDocument();
  });

  it('renders expanded when deep-linked with media=expanded', () => {
    render(<ScanHarness initialEntry="/workbench?media=expanded" />);
    expect(screen.getByTestId('media-expanded')).toBeInTheDocument();
    expect(screen.queryByTestId('media-collapsed')).not.toBeInTheDocument();
  });

  it('onExpand writes media=expanded into the URL', async () => {
    const user = userEvent.setup();
    render(<ScanHarness initialEntry="/workbench" />);

    await user.click(screen.getByRole('button', { name: 'Show media table' }));

    expect(screen.getByTestId('media-expanded')).toBeInTheDocument();
    expect(screen.getByTestId('location-search')).toHaveTextContent('media=expanded');
  });

  it('findings-arrival auto-collapse clears media=expanded from the URL', async () => {
    const user = userEvent.setup();
    findingsState.hasFindings = false;
    render(<ScanHarness initialEntry="/workbench?media=expanded" />);

    expect(screen.getByTestId('media-expanded')).toBeInTheDocument();
    expect(screen.getByTestId('location-search')).toHaveTextContent('media=expanded');

    // Rising edge: findings go from absent → present while media=expanded is set.
    findingsState.hasFindings = true;
    await act(async () => {
      await user.click(screen.getByTestId('force-rerender'));
    });

    expect(screen.getByTestId('location-search').textContent ?? '').not.toContain('media=expanded');
    expect(screen.getByTestId('media-collapsed')).toBeInTheDocument();
  });
});
