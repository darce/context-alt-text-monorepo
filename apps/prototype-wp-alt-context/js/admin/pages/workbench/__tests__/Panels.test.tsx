import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { JobProgress } from '../../../api/recognition/types/scan';
import { CONFIRM_NO_JOB_ZERO_STATE } from '../confirmTabCopy';
import type { ScanRunViewModel } from '../JobPipelineContext';
import { buildCoarseJobAnnouncement, ConfirmPanel, ScanActionPanel } from '../Panels';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, _plural: string, count: number) => (count === 1 ? single : _plural),
  sprintf: (fmt: string, ...args: (string | number)[]) => {
    let i = 0;
    return fmt.replace(/%[sd]/g, () => String(args[i++]));
  },
}));

// ---------------------------------------------------------------------------
// ScanActionPanel
// ---------------------------------------------------------------------------

describe('ScanActionPanel', () => {
  const baseScanRun: ScanRunViewModel = {
    isScanning: false,
  };

  it('does not render progress section when total is 0', () => {
    const progress: JobProgress = { completed: 0, total: 0 };
    render(<ScanActionPanel scanRun={{ ...baseScanRun, progress }} onCancelScan={vi.fn()} />);
    expect(screen.queryByRole('progressbar')).toBeNull();
  });

  it('renders progress bar and image count when progress is active', () => {
    const progress: JobProgress = { completed: 4, total: 10, images_processed: 4, faces_found: 2 };
    render(<ScanActionPanel scanRun={{ ...baseScanRun, progress }} onCancelScan={vi.fn()} />);
    expect(screen.getByRole('progressbar')).toBeTruthy();
    expect(screen.getByText('Processed 4/10 images · 2 faces found')).toBeTruthy();
  });

  it('renders phase label using formatJobPhase mapping', () => {
    const progress: JobProgress = { completed: 1, total: 5, phase: 'detecting' };
    render(<ScanActionPanel scanRun={{ ...baseScanRun, progress }} onCancelScan={vi.fn()} />);
    expect(screen.getByText('Phase: Detecting')).toBeTruthy();
  });

  it('renders "Failed" phase label', () => {
    const progress: JobProgress = { completed: 2, total: 5, phase: 'failed' };
    render(<ScanActionPanel scanRun={{ ...baseScanRun, progress }} onCancelScan={vi.fn()} />);
    expect(screen.getByText('Phase: Failed')).toBeTruthy();
  });

  it('renders ETA when etaSeconds is provided', () => {
    const progress: JobProgress = { completed: 5, total: 10 };
    render(<ScanActionPanel scanRun={{ ...baseScanRun, progress, etaSeconds: 90 }} onCancelScan={vi.fn()} />);
    expect(screen.getByText('Remaining: 1 min 30 sec')).toBeTruthy();
  });

  it('renders synced marker when isSynced is true', () => {
    const progress: JobProgress = { completed: 10, total: 10 };
    render(<ScanActionPanel scanRun={{ ...baseScanRun, progress, isSynced: true }} onCancelScan={vi.fn()} />);
    expect(screen.getByText('Synced')).toBeTruthy();
  });

  it('renders error message', () => {
    render(
      <ScanActionPanel scanRun={{ ...baseScanRun, errorMessage: 'Something went wrong' }} onCancelScan={vi.fn()} />,
    );
    expect(screen.getByText('Something went wrong')).toBeTruthy();
  });

  it('renders Retry clustering when onRetryClustering is provided after auto-retry ceiling', async () => {
    const onRetryClustering = vi.fn();
    render(
      <ScanActionPanel
        scanRun={{
          ...baseScanRun,
          errorMessage: 'Clustering failed after rate-limit retries. Use Retry clustering to try again.',
          onRetryClustering,
        }}
        onCancelScan={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Retry clustering' }));
    expect(onRetryClustering).toHaveBeenCalledOnce();
  });

  it('renders cancel button and calls handler', async () => {
    const onCancelScan = vi.fn();
    render(<ScanActionPanel scanRun={{ ...baseScanRun, isScanning: true }} onCancelScan={onCancelScan} />);
    await userEvent.click(screen.getByRole('button', { name: 'Cancel scan' }));
    expect(onCancelScan).toHaveBeenCalledOnce();
  });

  it('hides cancel when idle and shows scan region description (L3R-05)', () => {
    render(<ScanActionPanel scanRun={{ ...baseScanRun, isScanning: false }} onCancelScan={vi.fn()} />);
    expect(screen.queryByRole('button', { name: 'Cancel scan' })).toBeNull();
    expect(
      screen.getByText(
        'Scan your library for images that still need descriptive metadata, filtering by status or search term.',
      ),
    ).toBeTruthy();
  });

  it('suppresses cancel and progress bar when suppressPrimaryChrome is set (L3R-02)', () => {
    const progress: JobProgress = { completed: 4, total: 10, phase: 'detecting' };
    render(
      <ScanActionPanel
        scanRun={{ ...baseScanRun, isScanning: true, progress, statusText: 'working' }}
        onCancelScan={vi.fn()}
        suppressPrimaryChrome
      />,
    );
    expect(screen.queryByRole('button', { name: 'Cancel scan' })).toBeNull();
    expect(screen.queryByRole('progressbar')).toBeNull();
    expect(screen.getByText(/Job pending: working/)).toBeTruthy();
    expect(screen.getByText('Processed 4/10 images')).toBeTruthy();
  });

  it('L3R-01 residual: live region stays phase-stable while per-tick statusText updates visually', () => {
    const progress: JobProgress = { completed: 1, total: 10, phase: 'detecting' };
    const { rerender } = render(
      <ScanActionPanel
        scanRun={{
          ...baseScanRun,
          isScanning: true,
          progress,
          statusText: 'Processed 1/10 images',
          jobId: 'job-1',
        }}
        onCancelScan={vi.fn()}
      />,
    );

    const announce = screen.getByTestId('scan-status-announce');
    expect(announce.getAttribute('role')).toBe('status');
    expect(announce.textContent).toBe('Job job-1: Detecting');
    const visual = screen.getByTestId('scan-status-visual');
    expect(visual.textContent).toBe('Job job-1: Processed 1/10 images');
    // L3V-02: visual status must not be a live region (mutation: re-add role=status on <p>).
    expect(visual.getAttribute('role')).toBeNull();
    expect(visual.getAttribute('aria-live')).toBeNull();

    // Per-tick count change: visual updates, live region does not.
    rerender(
      <ScanActionPanel
        scanRun={{
          ...baseScanRun,
          isScanning: true,
          progress: { completed: 5, total: 10, phase: 'detecting' },
          statusText: 'Processed 5/10 images',
          jobId: 'job-1',
        }}
        onCancelScan={vi.fn()}
      />,
    );
    expect(screen.getByTestId('scan-status-visual').textContent).toBe('Job job-1: Processed 5/10 images');
    expect(screen.getByTestId('scan-status-announce').textContent).toBe('Job job-1: Detecting');

    // Phase change: live region updates.
    rerender(
      <ScanActionPanel
        scanRun={{
          ...baseScanRun,
          isScanning: true,
          progress: { completed: 10, total: 10, phase: 'clustering' },
          statusText: 'Processed 10/10 identities',
          jobId: 'job-1',
        }}
        onCancelScan={vi.fn()}
      />,
    );
    expect(screen.getByTestId('scan-status-announce').textContent).toBe('Job job-1: Clustering');
  });

  it('buildCoarseJobAnnouncement ignores count-bearing statusText without a phase', () => {
    expect(
      buildCoarseJobAnnouncement({
        jobId: 'j1',
        statusText: 'Processed 3/8 images',
        progressPhase: null,
      }),
    ).toBeNull();
    expect(
      buildCoarseJobAnnouncement({
        jobId: 'j1',
        statusText: 'completed',
        progressPhase: null,
      }),
    ).toBe('Job j1: completed');
  });

  it('L3V-03: countdown statusText ticks do not change the announce region when phase is null', () => {
    expect(
      buildCoarseJobAnnouncement({
        jobId: 'j1',
        statusText: 'Clustering queued — starting in 5s',
        progressPhase: null,
      }),
    ).toBeNull();
    expect(
      buildCoarseJobAnnouncement({
        jobId: 'j1',
        statusText: 'Clustering queued — starting in 4s',
        progressPhase: null,
      }),
    ).toBeNull();

    const { rerender } = render(
      <ScanActionPanel
        scanRun={{
          ...baseScanRun,
          isScanning: true,
          statusText: 'Clustering queued — starting in 5s',
          jobId: 'job-1',
        }}
        onCancelScan={vi.fn()}
      />,
    );

    expect(screen.queryByTestId('scan-status-announce')).toBeNull();
    expect(screen.getByTestId('scan-status-visual').textContent).toBe(
      'Job job-1: Clustering queued — starting in 5s',
    );

    rerender(
      <ScanActionPanel
        scanRun={{
          ...baseScanRun,
          isScanning: true,
          statusText: 'Clustering queued — starting in 4s',
          jobId: 'job-1',
        }}
        onCancelScan={vi.fn()}
      />,
    );

    // Announce region stays absent/stable; only visual countdown advances.
    expect(screen.queryByTestId('scan-status-announce')).toBeNull();
    expect(screen.getByTestId('scan-status-visual').textContent).toBe(
      'Job job-1: Clustering queued — starting in 4s',
    );
  });

  it('L3R-07: stall Cancel is suppressed when suppressPrimaryChrome is set', () => {
    render(
      <ScanActionPanel
        scanRun={{ ...baseScanRun, isScanning: true, stallSeconds: 31 }}
        onCancelScan={vi.fn()}
        onRetryStream={vi.fn()}
        suppressPrimaryChrome
      />,
    );

    expect(screen.getByText('Stuck - last update 31 seconds ago')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy();
    // Primary Cancel is on the strip; stall block must not add a second "Cancel".
    expect(screen.queryByRole('button', { name: 'Cancel' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Cancel scan' })).toBeNull();
  });

  it('disables cancel button while cancelling', () => {
    render(
      <ScanActionPanel scanRun={{ ...baseScanRun, isScanning: true, isCancelling: true }} onCancelScan={vi.fn()} />,
    );
    expect(screen.getByRole('button', { name: 'Cancelling…' })).toBeDisabled();
  });

  it('renders the stuck badge and retries the stream', async () => {
    const onRetryStream = vi.fn();
    const onCancelScan = vi.fn();

    render(
      <ScanActionPanel
        scanRun={{ ...baseScanRun, isScanning: true, stallSeconds: 31 }}
        onRetryStream={onRetryStream}
        onCancelScan={onCancelScan}
      />,
    );

    expect(screen.getByText('Stuck - last update 31 seconds ago')).toBeTruthy();

    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetryStream).toHaveBeenCalledOnce();
  });

  it('shows identity-based progress count during clustering phase', () => {
    const progress: JobProgress = { completed: 75, total: 150, phase: 'clustering' };
    render(<ScanActionPanel scanRun={{ ...baseScanRun, progress }} onCancelScan={vi.fn()} />);
    expect(screen.getByText('Processed 75/150 identities')).toBeTruthy();
    expect(screen.queryByText(/images/i)).toBeNull();
  });

  it('shows retry count and last error code when clustering is retrying', () => {
    const progress: JobProgress = {
      completed: 40,
      total: 150,
      phase: 'clustering',
      retry_count: 2,
      last_error_code: 'TIMEOUT',
    };
    render(<ScanActionPanel scanRun={{ ...baseScanRun, progress }} onCancelScan={vi.fn()} />);
    expect(screen.getByText(/Retry 2/)).toBeTruthy();
    expect(screen.getByText(/last error: TIMEOUT/)).toBeTruthy();
  });

  it('shows "Clustering progress" aria-label on progress bar during clustering phase', () => {
    const progress: JobProgress = { completed: 50, total: 150, phase: 'clustering' };
    render(<ScanActionPanel scanRun={{ ...baseScanRun, progress }} onCancelScan={vi.fn()} />);
    expect(screen.getByRole('progressbar', { name: 'Clustering progress' })).toBeTruthy();
  });

  it('renders compact variant as a single-row strip with progress and cancel', async () => {
    const onCancelScan = vi.fn();
    const progress: JobProgress = { completed: 42, total: 100, phase: 'clustering' };
    const { container } = render(
      <ScanActionPanel
        variant="compact"
        scanRun={{ ...baseScanRun, isScanning: true, progress }}
        onCancelScan={onCancelScan}
      />,
    );

    expect(container.querySelector('[data-variant="compact"]')).toBeTruthy();
    expect(screen.getByRole('progressbar')).toBeTruthy();
    // L3R-06: leading verb derived from phase (clustering), not hardcoded Scanning…
    expect(screen.getByText(/Clustering…/)).toBeTruthy();
    expect(screen.getByText(/42%/)).toBeTruthy();
    expect(screen.getByText(/phase: Clustering/i)).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCancelScan).toHaveBeenCalledOnce();
  });

  it('derives compact leading verb from currentPhase (L3R-06)', () => {
    const progress: JobProgress = { completed: 10, total: 100, phase: 'detecting' };
    render(
      <ScanActionPanel
        variant="compact"
        currentPhase="projecting"
        scanRun={{ ...baseScanRun, isScanning: false, progress }}
        onCancelScan={vi.fn()}
      />,
    );
    expect(screen.getByText(/Syncing results…/)).toBeTruthy();
    expect(screen.queryByText(/^Scanning…/)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// ConfirmPanel
// ---------------------------------------------------------------------------

describe('ConfirmPanel', () => {
  const baseProps = {
    jobId: 'job-123',
    status: 'completed',
    onCluster: vi.fn(),
    isClustering: false,
    onViewClusters: vi.fn(),
  };

  it('renders job id and status', () => {
    render(<ConfirmPanel {...baseProps} />);
    const items = screen.getAllByRole('listitem');
    expect(items[0].textContent).toContain('job-123');
    expect(items[1].textContent).toContain('completed');
    expect(items[1].textContent).toContain('Status');
  });

  it('shows honest zero state and no Pending when jobId is null', () => {
    render(<ConfirmPanel {...baseProps} jobId={null} status={undefined} />);
    expect(screen.getByText(CONFIRM_NO_JOB_ZERO_STATE)).toBeTruthy();
    expect(screen.queryByText(/Pending/)).toBeNull();
    expect(screen.queryByText(/Status/)).toBeNull();
    expect(screen.queryByRole('listitem')).toBeNull();
  });

  it('renders Status row only when a job exists', () => {
    render(<ConfirmPanel {...baseProps} jobId="job-abc" status="running" />);
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(items[1].textContent).toContain('Status');
    expect(items[1].textContent).toContain('running');
  });

  it('enables cluster button when not clustering', () => {
    render(<ConfirmPanel {...baseProps} />);
    expect(screen.getByRole('button', { name: 'Cluster the latest job results' })).not.toBeDisabled();
  });

  it('shows clustering label and disables button during clustering', () => {
    render(<ConfirmPanel {...baseProps} isClustering />);
    expect(screen.getByRole('button', { name: 'Clustering faces…' })).toBeDisabled();
  });

  it('calls onCluster when button clicked', async () => {
    const onCluster = vi.fn();
    render(<ConfirmPanel {...baseProps} onCluster={onCluster} />);
    await userEvent.click(screen.getByRole('button', { name: 'Cluster the latest job results' }));
    expect(onCluster).toHaveBeenCalledOnce();
  });

  it('disables open-roster button when jobId is null', () => {
    render(<ConfirmPanel {...baseProps} jobId={null} />);
    expect(screen.getByRole('button', { name: 'Open roster' })).toBeDisabled();
  });

  it('does not render progress section when total is 0', () => {
    const progress: JobProgress = { completed: 0, total: 0 };
    render(<ConfirmPanel {...baseProps} progress={progress} />);
    expect(screen.queryByRole('progressbar')).toBeNull();
  });

  it('renders identity progress bar and count', () => {
    const progress: JobProgress = { completed: 300, total: 937 };
    render(<ConfirmPanel {...baseProps} progress={progress} />);
    expect(screen.getByRole('progressbar')).toBeTruthy();
    expect(screen.getByText('Processed 300/937 identities')).toBeTruthy();
  });

  it('renders clusters_created when present', () => {
    const progress: JobProgress = { completed: 100, total: 200, clusters_created: 12 };
    render(<ConfirmPanel {...baseProps} progress={progress} />);
    expect(screen.getByText('Clusters created: 12')).toBeTruthy();
  });

  it('does not render retry line when retry_count is 0', () => {
    const progress: JobProgress = { completed: 100, total: 200, retry_count: 0 };
    render(<ConfirmPanel {...baseProps} progress={progress} />);
    expect(screen.queryByText(/Retry/)).toBeNull();
  });

  it('renders retry count when retry_count > 0', () => {
    const progress: JobProgress = { completed: 100, total: 200, retry_count: 2 };
    render(<ConfirmPanel {...baseProps} progress={progress} />);
    expect(screen.getByText('Retry 2')).toBeTruthy();
  });

  it('renders retry count with last error code', () => {
    const progress: JobProgress = {
      completed: 100,
      total: 200,
      retry_count: 1,
      last_error_code: 'integrity_violation',
    };
    render(<ConfirmPanel {...baseProps} progress={progress} />);
    expect(screen.getByText('Retry 1 (last error: integrity_violation)')).toBeTruthy();
  });

  it('renders ETA when etaSeconds is provided', () => {
    const progress: JobProgress = { completed: 50, total: 200 };
    render(<ConfirmPanel {...baseProps} progress={progress} etaSeconds={60} />);
    expect(screen.getByText('Remaining: 1 minute')).toBeTruthy();
  });

  it('renders phase label for clustering phase', () => {
    const progress: JobProgress = { completed: 10, total: 100, phase: 'clustering' };
    render(<ConfirmPanel {...baseProps} progress={progress} />);
    expect(screen.getByText('Phase: Clustering')).toBeTruthy();
  });

  it('renders phase label for awaiting_projection phase', () => {
    const progress: JobProgress = { completed: 100, total: 100, phase: 'awaiting_projection' };
    render(<ConfirmPanel {...baseProps} progress={progress} />);
    expect(screen.getByText('Phase: Syncing results')).toBeTruthy();
  });

  it('renders phase label for failed phase', () => {
    const progress: JobProgress = { completed: 50, total: 200, phase: 'failed' };
    render(<ConfirmPanel {...baseProps} progress={progress} />);
    expect(screen.getByText('Phase: Failed')).toBeTruthy();
  });

  it('renders clusterMessage when provided', () => {
    render(<ConfirmPanel {...baseProps} clusterMessage="Clustering completed successfully" />);
    expect(screen.getByText('Clustering completed successfully')).toBeTruthy();
  });

  it('disables cluster button with offline reason when remoteActionDisabled', () => {
    render(
      <ConfirmPanel
        {...baseProps}
        remoteActionDisabled
        remoteActionAriaDisabled
        remoteActionTitle="Unavailable while the recognition service is offline"
      />,
    );
    const button = screen.getByRole('button', { name: 'Cluster the latest job results' });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('title', 'Unavailable while the recognition service is offline');
    expect(button).toHaveAttribute('aria-disabled', 'true');
  });

  it('keeps cluster button enabled online without remote gate props', () => {
    render(<ConfirmPanel {...baseProps} />);
    const button = screen.getByRole('button', { name: 'Cluster the latest job results' });
    expect(button).not.toBeDisabled();
    expect(button).not.toHaveAttribute('title');
  });
});
