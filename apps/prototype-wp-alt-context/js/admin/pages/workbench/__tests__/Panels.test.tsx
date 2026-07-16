import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { JobProgress } from '../../../api/recognition/types/scan';
import type { ScanRunViewModel } from '../JobPipelineContext';
import { ConfirmPanel, ScanActionPanel } from '../Panels';

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
  });

  it('shows "No job yet" when jobId is null', () => {
    render(<ConfirmPanel {...baseProps} jobId={null} />);
    const items = screen.getAllByRole('listitem');
    expect(items[0].textContent).toContain('No job yet');
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

  it('disables view-clusters button when jobId is null', () => {
    render(<ConfirmPanel {...baseProps} jobId={null} />);
    expect(screen.getByRole('button', { name: 'Open clusters in roster' })).toBeDisabled();
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
