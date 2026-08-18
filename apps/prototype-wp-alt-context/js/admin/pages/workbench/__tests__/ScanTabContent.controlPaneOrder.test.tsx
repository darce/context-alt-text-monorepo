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
    setQueueState: vi.fn(),
  }),
}));

vi.mock('../Panels', () => ({
  ScanActionPanel: ({
    variant,
    suppressPrimaryChrome,
  }: {
    variant?: string;
    suppressPrimaryChrome?: boolean;
  }) => (
    <div data-testid={variant === 'compact' ? 'scan-action-panel-compact' : 'scan-action-panel'}>
      {/* Compact always owns a progressbar; default suppresses it while strip is mounted (L3R-02). */}
      {(variant === 'compact' || !suppressPrimaryChrome) && (
        <div role="progressbar" aria-label="Scan progress" data-testid={variant === 'compact' ? 'progress-compact' : 'progress-full'} />
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
      <h2 id="acx-workbench-queue-heading">Review this face group</h2>
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
    scanRun: { isScanning: pipelineState.isScanning, progress: null },
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

const testIdOrder = (container: HTMLElement): string[] =>
  Array.from(container.querySelectorAll('[data-testid]')).map((el) => (el as HTMLElement).dataset.testid ?? '');

describe('ScanTabContent — E21-18 S1 control-pane reorder', () => {
  beforeEach(() => {
    panelState.mode = 'none';
    panelState.clusterId = null;
    lifecycleState.reviewClusterId = null;
    pipelineState.isScanning = false;
    pipelineState.currentPhase = 'idle';
  });

  afterEach(cleanup);

  it('renders queue before findings and scan chrome when idle', () => {
    const { container } = render(<ScanTabContent />);
    const order = testIdOrder(container);

    expect(order).toEqual([
      'review-queue',
      'findings-panel',
      'scan-action-panel',
      'progress-full',
      'job-timeline',
    ]);
    expect(screen.queryByTestId('active-job-strip')).toBeNull();
    expect(screen.queryByTestId('scan-action-panel-compact')).toBeNull();
  });

  it('renders the compact active-job strip only while a job is running', () => {
    pipelineState.isScanning = true;
    pipelineState.currentPhase = 'scanning';

    const { container, rerender } = render(<ScanTabContent />);
    expect(screen.getByTestId('active-job-strip')).toBeTruthy();
    expect(screen.getByTestId('scan-action-panel-compact')).toBeTruthy();
    expect(screen.getByTestId('job-timeline-compact')).toBeTruthy();

    const order = testIdOrder(container);
    // Strip first, then queue, findings, demoted full scan section.
    expect(order.indexOf('active-job-strip')).toBe(0);
    expect(order.indexOf('review-queue')).toBeLessThan(order.indexOf('findings-panel'));
    expect(order.indexOf('findings-panel')).toBeLessThan(order.indexOf('scan-action-panel'));

    pipelineState.isScanning = false;
    pipelineState.currentPhase = 'idle';
    rerender(<ScanTabContent />);
    expect(screen.queryByTestId('active-job-strip')).toBeNull();
    expect(screen.queryByTestId('scan-action-panel-compact')).toBeNull();
  });

  it('keeps the demoted scan section reachable from zero state', () => {
    const { container } = render(<ScanTabContent />);
    const scanSection = container.querySelector('.acx-workbench-control-scan');
    expect(scanSection).toBeTruthy();
    expect(scanSection?.querySelector('[data-testid="scan-action-panel"]')).toBeTruthy();
    expect(scanSection?.querySelector('[data-testid="job-timeline"]')).toBeTruthy();
    expect(scanSection?.querySelector('#acx-workbench-scan-heading')?.textContent).toBe('Scan');
  });

  it('L3R-01: active-job strip container is not a polite live region', () => {
    pipelineState.isScanning = true;
    pipelineState.currentPhase = 'scanning';
    render(<ScanTabContent />);

    const strip = screen.getByTestId('active-job-strip');
    expect(strip.getAttribute('role')).not.toBe('status');
    expect(strip.getAttribute('aria-live')).toBeNull();
  });

  it('L3R-02: while strip is mounted, only one progressbar and no second JobTimeline', () => {
    pipelineState.isScanning = true;
    pipelineState.currentPhase = 'scanning';
    render(<ScanTabContent />);

    const progressbars = screen.getAllByRole('progressbar', { name: 'Scan progress' });
    expect(progressbars).toHaveLength(1);
    expect(screen.getByTestId('progress-compact')).toBeTruthy();
    expect(screen.queryByTestId('progress-full')).toBeNull();
    expect(screen.getByTestId('job-timeline-compact')).toBeTruthy();
    expect(screen.queryByTestId('job-timeline')).toBeNull();
  });

  it('L3R-03: strip stays mounted during projecting after isScanning ends', () => {
    pipelineState.isScanning = false;
    pipelineState.currentPhase = 'projecting';
    render(<ScanTabContent />);

    expect(screen.getByTestId('active-job-strip')).toBeTruthy();
    expect(screen.getByTestId('scan-action-panel-compact')).toBeTruthy();
    expect(screen.queryByTestId('job-timeline')).toBeNull();
  });

  it('L3R-04: queue and findings are named regions via aria-labelledby', () => {
    const { container } = render(<ScanTabContent />);

    const queueSection = container.querySelector(
      'section.acx-workbench-control-queue[aria-labelledby="acx-workbench-queue-heading"]',
    );
    const findingsSection = container.querySelector(
      'section.acx-workbench-control-findings[aria-labelledby="acx-workbench-findings-heading"]',
    );
    const scanSection = container.querySelector(
      'section.acx-workbench-control-scan[aria-labelledby="acx-workbench-scan-heading"]',
    );

    expect(queueSection).toBeTruthy();
    expect(findingsSection).toBeTruthy();
    expect(scanSection).toBeTruthy();
    expect(queueSection?.querySelector('#acx-workbench-queue-heading')).toBeTruthy();
    expect(findingsSection?.querySelector('#acx-workbench-findings-heading')).toBeTruthy();
  });

  it('L3R-08: queue region heading exists when ClusterReviewPanel replaces ReviewQueue', () => {
    lifecycleState.reviewClusterId = 'cluster-42';
    const { container } = render(<ScanTabContent />);

    const queueSection = container.querySelector(
      'section.acx-workbench-control-queue[aria-labelledby="acx-workbench-queue-heading"]',
    );
    expect(queueSection).toBeTruthy();
    expect(screen.getByTestId('review-panel')).toBeTruthy();
    expect(screen.queryByTestId('review-queue')).toBeNull();
    const heading = queueSection?.querySelector('#acx-workbench-queue-heading');
    expect(heading).toBeTruthy();
    expect(heading?.textContent).toBe('Review this face group');
  });

  it('L3R-08: queue region heading exists when ClusterLabelingPanel replaces ReviewQueue', () => {
    panelState.mode = 'label';
    panelState.clusterId = 'cluster-9';
    const { container } = render(<ScanTabContent />);

    const queueSection = container.querySelector(
      'section.acx-workbench-control-queue[aria-labelledby="acx-workbench-queue-heading"]',
    );
    expect(queueSection).toBeTruthy();
    expect(screen.getByTestId('label-panel')).toBeTruthy();
    expect(screen.queryByTestId('review-queue')).toBeNull();
    const heading = queueSection?.querySelector('#acx-workbench-queue-heading');
    expect(heading).toBeTruthy();
    expect(heading?.textContent).toBe('Name this person');
  });
});
