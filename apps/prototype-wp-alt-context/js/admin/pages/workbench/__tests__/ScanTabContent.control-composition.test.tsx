import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ScanTabContent } from '../ScanTabContent';

/**
 * E21-18 S1 — control-pane reorder:
 * (a) active-job strip only while a job runs
 * (b) review queue first
 * (c) findings demoted
 * (d) full scan panel + timeline last
 *
 * L3R-01/02 pins: strip is not a live region; only one progressbar while strip owns chrome.
 */

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

const panelState = { mode: 'none' as 'none' | 'label' | 'review', clusterId: null as string | null };
const lifecycleState = { reviewClusterId: null as string | null };
const pipelineState = {
  isScanning: false,
  currentPhase: 'idle' as string,
  errorMessage: null as string | null,
};

vi.mock('../../../../components/ErrorBoundary', () => ({
  ErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('../../../hooks/useScrollRestoration', () => ({
  useScrollRestoration: () => undefined,
}));

vi.mock('../../../hooks/useWorkbenchFilters', () => ({
  useWorkbenchFilters: () => ({
    queueState: { index: 0, kind: 'all', band: 'all' },
    dispatchQueue: vi.fn(),
  }),
}));

vi.mock('../Panels', () => ({
  ScanActionPanel: ({ variant, suppressPrimaryChrome }: { variant?: string; suppressPrimaryChrome?: boolean }) => (
    <div data-testid={variant === 'compact' ? 'scan-action-panel-compact' : 'scan-action-panel'}>
      {/* Compact always owns a progressbar; default suppresses it while strip is mounted (L3R-02). */}
      {(variant === 'compact' || !suppressPrimaryChrome) && (
        <div
          role="progressbar"
          aria-label="Scan progress"
          data-testid={variant === 'compact' ? 'progress-compact' : 'progress-full'}
        />
      )}
    </div>
  ),
  isClusteringActive: () => false,
}));

vi.mock('../JobTimeline', () => ({
  JobTimeline: ({ compact }: { compact?: boolean }) => (
    <div data-testid={compact ? 'job-timeline-compact' : 'job-timeline'} />
  ),
}));

vi.mock('../identity-clusters', () => ({
  ClusterLabelingPanel: () => <div data-testid="label-panel" />,
  ClusterReviewPanel: () => (
    <div data-testid="review-panel">
      <h2 id="acx-workbench-queue-heading">Review these faces</h2>
    </div>
  ),
  ReviewQueue: React.forwardRef<unknown, Record<string, unknown>>(function ReviewQueueStub() {
    return (
      <div data-testid="review-queue">
        <h3 id="acx-workbench-queue-heading">Review Suggestions</h3>
      </div>
    );
  }),
  WorkbenchFindingsPanel: () => (
    <div data-testid="findings-panel">
      <h3 id="acx-workbench-findings-heading">Recognition findings</h3>
    </div>
  ),
}));

vi.mock('../identity-clusters/useAriaAnnounce', () => ({
  useAriaAnnounce: () => ({ message: '', seq: 0, announce: vi.fn() }),
}));

vi.mock('../identity-clusters/useOpenReviewTargetLifecycle', () => ({
  useOpenReviewTargetLifecycle: () => ({ reviewClusterId: lifecycleState.reviewClusterId }),
}));

vi.mock('../JobPipelineContext', () => ({
  useJobPipeline: () => ({
    scanRun: { isScanning: pipelineState.isScanning, progress: null, errorMessage: pipelineState.errorMessage },
    status: {
      scanProgress: null,
      clusterProgress: null,
      currentPhase: pipelineState.currentPhase,
      projectionSyncState: 'idle',
    },
    history: { activeJobIds: [], jobId: null },
    cancelScan: vi.fn(),
    retryScanStream: vi.fn(),
  }),
}));

vi.mock('../ClusterPanelContext', () => ({
  useClusterPanel: () => ({
    clusterPanel: panelState,
    dispatchClusterPanel: vi.fn(),
  }),
}));

vi.mock('../WorkbenchMediaContext', () => ({
  useWorkbenchMediaContext: () => ({ mediaQueue: { hasIdentities: true } }),
}));

vi.mock('../ReviewSurfaceContext', () => ({
  useReviewSurface: () => ({ cardPrimaryPresent: false, setCardPrimaryPresent: vi.fn() }),
}));

const findings = {
  hasFindings: false,
  repairPending: false,
  isReadOnly: false,
  queueSettled: true,
  isUnavailable: false,
  isError: false,
  isAssignmentError: false,
  isTopUnlabeledError: false,
};
const queries = {
  assignmentQuery: { isSuccess: true },
  mergeQuery: { isSuccess: true },
  nameQuery: { isSuccess: true },
  topUnlabeledQuery: { isSuccess: true },
};
vi.mock('../identity-clusters/useWorkbenchFindings', () => ({ useWorkbenchFindings: () => findings }));
vi.mock('../identity-clusters/useSuggestionReviewQueries', () => ({ useSuggestionReviewQueries: () => queries }));

describe('UXREC-1 compact recognition composition', () => {
  beforeEach(() => {
    panelState.mode = 'none';
    panelState.clusterId = null;
    lifecycleState.reviewClusterId = null;
    pipelineState.isScanning = false;
    pipelineState.currentPhase = 'idle';
    pipelineState.errorMessage = null;
    findings.hasFindings = false;
    findings.repairPending = false;
    findings.isReadOnly = false;
    findings.queueSettled = true;
    findings.isUnavailable = false;
    findings.isError = false;
    findings.isAssignmentError = false;
    findings.isTopUnlabeledError = false;
    Object.values(queries).forEach((q) => {
      q.isSuccess = true;
    });
  });
  afterEach(cleanup);

  it('collapses only confirmed empty secondary reviews and idle scan chrome', () => {
    render(<ScanTabContent compactEmptySections />);
    expect(screen.getByTestId('review-queue')).not.toBeVisible();
    expect(screen.getByTestId('findings-panel')).not.toBeVisible();
    expect(screen.getByTestId('scan-action-panel')).not.toBeVisible();
    expect(document.querySelector('.acx-review-lifecycle-announce')).toBeVisible();
  });

  it.each(['assignmentQuery', 'mergeQuery', 'nameQuery', 'topUnlabeledQuery'] as const)(
    'keeps incomplete or failed %s visible rather than treating it as empty',
    (key) => {
      queries[key].isSuccess = false;
      render(<ScanTabContent compactEmptySections />);
      expect(screen.getByTestId('review-queue')).toBeVisible();
      expect(screen.getByTestId('findings-panel')).toBeVisible();
    },
  );

  it.each([
    'hasFindings',
    'repairPending',
    'isReadOnly',
    'isUnavailable',
    'isError',
    'isAssignmentError',
    'isTopUnlabeledError',
  ] as const)('keeps %s evidence open', (key) => {
    findings[key] = true;
    render(<ScanTabContent compactEmptySections />);
    expect(screen.getByTestId('review-queue')).toBeVisible();
    expect(screen.getByTestId('findings-panel')).toBeVisible();
  });

  it('preserves the current review target even when summary queues drain', () => {
    panelState.mode = 'review';
    panelState.clusterId = 'group-42';
    lifecycleState.reviewClusterId = 'group-42';
    render(<ScanTabContent compactEmptySections />);
    expect(screen.getByTestId('review-panel')).toBeVisible();
  });

  it('keeps real scan failures and active progress visible', () => {
    pipelineState.errorMessage = 'Recognition failed';
    const { rerender } = render(<ScanTabContent compactEmptySections />);
    expect(screen.getByTestId('scan-action-panel')).toBeVisible();
    pipelineState.isScanning = true;
    pipelineState.currentPhase = 'scanning';
    rerender(<ScanTabContent compactEmptySections />);
    expect(screen.getByTestId('active-job-strip')).toBeVisible();
    expect(screen.getAllByRole('progressbar')).toHaveLength(1);
  });

  it('moves focus to Library search when an empty review section collapses', () => {
    findings.hasFindings = true;
    const { rerender } = render(
      <>
        <input id="acx-media-search" aria-label="Search media" />
        <ScanTabContent compactEmptySections />
      </>,
    );
    const anchor = document.querySelector<HTMLElement>('.acx-findings-detail-anchor')!;
    anchor.focus();
    expect(anchor).toHaveFocus();
    findings.hasFindings = false;
    rerender(
      <>
        <input id="acx-media-search" aria-label="Search media" />
        <ScanTabContent compactEmptySections />
      </>,
    );
    expect(screen.getByRole('textbox', { name: 'Search media' })).toHaveFocus();
    expect(screen.getByTestId('review-queue')).toBeInTheDocument();
  });
});

describe('UXREC-1 shared run status is left to the Library composition (finding 19874)', () => {
  beforeEach(() => {
    panelState.mode = 'none';
    panelState.clusterId = null;
    lifecycleState.reviewClusterId = null;
    pipelineState.isScanning = false;
    pipelineState.currentPhase = 'idle';
    pipelineState.errorMessage = null;
    findings.hasFindings = false;
  });
  afterEach(cleanup);

  it('mounts no Control run status while idle and still collapses idle recognition chrome', () => {
    render(<ScanTabContent compactEmptySections externalActivityStatus />);
    expect(screen.queryByTestId('scan-action-panel-compact')).toBeNull();
    expect(screen.queryAllByRole('progressbar', { hidden: true })).toHaveLength(0);
    expect(screen.getByTestId('scan-action-panel')).not.toBeVisible();
  });

  it('keeps the compact recognition timeline without a second run status while scanning', () => {
    pipelineState.isScanning = true;
    pipelineState.currentPhase = 'scanning';
    render(<ScanTabContent compactEmptySections externalActivityStatus />);
    expect(screen.getByTestId('active-job-strip')).toBeVisible();
    expect(screen.getByTestId('job-timeline-compact')).toBeVisible();
    expect(screen.queryByTestId('scan-action-panel-compact')).toBeNull();
    expect(screen.queryAllByRole('progressbar', { hidden: true })).toHaveLength(0);
  });

  it('keeps recognition failure detail visible in Control', () => {
    pipelineState.errorMessage = 'Recognition failed';
    render(<ScanTabContent compactEmptySections externalActivityStatus />);
    expect(screen.getByTestId('scan-action-panel')).toBeVisible();
    expect(screen.queryAllByRole('progressbar', { hidden: true })).toHaveLength(0);
  });
});
