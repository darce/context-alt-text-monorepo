import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ConfirmPanel, RecentJobsPanel, mediaEditUrl } from '../workbench/Panels';
import { WorkbenchStepMap, WORKBENCH_STEP_IDS, deriveActiveWorkbenchStep } from '../WorkbenchPage';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string, ...args: (string | number)[]) => {
    let index = 0;
    return format.replace(/%(s|d)/g, () => String(args[index++]));
  },
}));

describe('Workbench helpers', () => {
  it('builds media edit URLs', () => {
    expect(mediaEditUrl(123)).toContain('post=123');
    expect(mediaEditUrl(123)).toContain('action=edit');
  });
});

describe('ConfirmPanel', () => {
  it('disables roster link when no job is selected', () => {
    render(
      <ConfirmPanel
        jobId={null}
        status="pending"
        onCluster={vi.fn()}
        isClustering={false}
        clusterMessage={null}
        onViewClusters={vi.fn()}
      />,
    );

    const button = screen.getByRole('button', { name: 'Open roster' });
    expect(button).toBeDisabled();
  });

  it('fires roster link callback when job exists', async () => {
    const viewClusters = vi.fn();
    render(
      <ConfirmPanel
        jobId="job-123"
        status="completed"
        onCluster={vi.fn()}
        isClustering={false}
        clusterMessage={null}
        onViewClusters={viewClusters}
      />,
    );

    const button = screen.getByRole('button', { name: 'Open roster' });
    await userEvent.click(button);
    expect(viewClusters).toHaveBeenCalled();
  });
});

describe('RecentJobsPanel', () => {
  it('lists recent jobs and handles selection', async () => {
    const onSelect = vi.fn();
    const onClear = vi.fn();
    render(
      <RecentJobsPanel
        jobs={['job-a']}
        statuses={{ 'job-a': 'completed' }}
        activeJobId={null}
        onSelect={onSelect}
        onClear={onClear}
      />,
    );

    const jobButton = screen.getByRole('button', { name: /job-a/i });
    await userEvent.click(jobButton);
    expect(onSelect).toHaveBeenCalledWith('job-a');
  });
});

describe('Workbench follow-up coverage', () => {
  it('[ACX-4130-G7-WB-1] surfaces clustering progress and sync state for selected jobs', async () => {
    const onCluster = vi.fn();
    const onViewClusters = vi.fn();

    render(
      <ConfirmPanel
        jobId="job-42"
        status="running"
        onCluster={onCluster}
        isClustering={false}
        clusterMessage={null}
        onViewClusters={onViewClusters}
        progress={{
          completed: 2,
          total: 10,
          phase: 'clustering',
          clusters_created: 1,
        }}
        etaSeconds={45}
        isSynced
      />,
    );

    expect(screen.getByText('Phase: Clustering')).toBeInTheDocument();
    expect(screen.getByText('Processed 2/10 identities')).toBeInTheDocument();
    expect(screen.getByText('Clusters created: 1')).toBeInTheDocument();
    expect(screen.getByText('Remaining: 45 seconds')).toBeInTheDocument();
    expect(screen.getByText('Synced')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Cluster the latest job results' }));
    await userEvent.click(screen.getByRole('button', { name: 'Open roster' }));

    expect(onCluster).toHaveBeenCalledTimes(1);
    expect(onViewClusters).toHaveBeenCalledTimes(1);
  });

  it('[ACX-4130-G7-WB-2] shows clustering summary details after a clustering run', () => {
    render(
      <ConfirmPanel
        jobId="job-99"
        status="completed"
        onCluster={vi.fn()}
        isClustering={false}
        clusterMessage="Created 3 clusters for 18 identities."
        onViewClusters={vi.fn()}
        progress={{
          completed: 10,
          total: 10,
          phase: 'complete',
          clusters_created: 3,
        }}
      />,
    );

    expect(screen.getByText('Phase: Complete')).toBeInTheDocument();
    expect(screen.getByText('Processed 10/10 identities')).toBeInTheDocument();
    expect(screen.getByText('Clusters created: 3')).toBeInTheDocument();
    expect(screen.getByText('Created 3 clusters for 18 identities.')).toBeInTheDocument();
  });
});

describe('deriveActiveWorkbenchStep', () => {
  it('defaults to scan when the advanced drawer is closed and no cluster is under review', () => {
    expect(deriveActiveWorkbenchStep({ isAdvancedOpen: false, isReviewingCluster: false })).toBe(
      WORKBENCH_STEP_IDS.scan,
    );
  });

  it('reports confirm when the advanced (clustering) drawer is open', () => {
    expect(deriveActiveWorkbenchStep({ isAdvancedOpen: true, isReviewingCluster: false })).toBe(
      WORKBENCH_STEP_IDS.confirm,
    );
  });

  it('reports review when a cluster is open for review, regardless of the drawer', () => {
    expect(deriveActiveWorkbenchStep({ isAdvancedOpen: false, isReviewingCluster: true })).toBe(
      WORKBENCH_STEP_IDS.review,
    );
    expect(deriveActiveWorkbenchStep({ isAdvancedOpen: true, isReviewingCluster: true })).toBe(
      WORKBENCH_STEP_IDS.review,
    );
  });
});

describe('WorkbenchStepMap', () => {
  it('renders all three step names, in order, numbered 1-3', () => {
    render(<WorkbenchStepMap activeStep="scan" onSelectScan={vi.fn()} onSelectConfirm={vi.fn()} />);

    const steps = screen.getAllByRole('listitem');
    expect(steps).toHaveLength(3);
    expect(steps[0]).toHaveTextContent('1');
    expect(steps[0]).toHaveTextContent('Scan');
    expect(steps[1]).toHaveTextContent('2');
    expect(steps[1]).toHaveTextContent('Confirm');
    expect(steps[2]).toHaveTextContent('3');
    expect(steps[2]).toHaveTextContent('Review');
  });

  it('exposes an accessible name on the step list', () => {
    render(<WorkbenchStepMap activeStep="scan" onSelectScan={vi.fn()} onSelectConfirm={vi.fn()} />);

    expect(screen.getByRole('navigation', { name: 'Progress' })).toBeInTheDocument();
  });

  it('marks the current step with aria-current="step" and no others', () => {
    render(<WorkbenchStepMap activeStep="confirm" onSelectScan={vi.fn()} onSelectConfirm={vi.fn()} />);

    expect(screen.getByTestId('acx-workbench-step-confirm')).toHaveAttribute('aria-current', 'step');
    expect(screen.getByTestId('acx-workbench-step-scan')).not.toHaveAttribute('aria-current');
    expect(screen.getByTestId('acx-workbench-step-review')).not.toHaveAttribute('aria-current');
  });

  it('moves aria-current="step" to the new step when the active step changes (not hardcoded to step 1)', () => {
    const { rerender } = render(
      <WorkbenchStepMap activeStep="scan" onSelectScan={vi.fn()} onSelectConfirm={vi.fn()} />,
    );
    expect(screen.getByTestId('acx-workbench-step-scan')).toHaveAttribute('aria-current', 'step');

    rerender(<WorkbenchStepMap activeStep="review" onSelectScan={vi.fn()} onSelectConfirm={vi.fn()} />);

    expect(screen.getByTestId('acx-workbench-step-review')).toHaveAttribute('aria-current', 'step');
    expect(screen.getByTestId('acx-workbench-step-scan')).not.toHaveAttribute('aria-current');
    expect(screen.getByTestId('acx-workbench-step-confirm')).not.toHaveAttribute('aria-current');
  });

  it('communicates current/complete state with text as well as styling, not colour alone', () => {
    render(<WorkbenchStepMap activeStep="review" onSelectScan={vi.fn()} onSelectConfirm={vi.fn()} />);

    // scan + confirm are both before the active "review" step -> completed chip
    expect(screen.getByTestId('acx-workbench-step-scan')).toHaveTextContent('Completed');
    expect(screen.getByTestId('acx-workbench-step-confirm')).toHaveTextContent('Completed');
    expect(screen.getByTestId('acx-workbench-step-review')).toHaveTextContent('Current');
  });

  it('keeps scan and confirm reachable as click targets, and does not gate review behind a selection', async () => {
    const onSelectScan = vi.fn();
    const onSelectConfirm = vi.fn();
    const user = userEvent.setup();
    render(<WorkbenchStepMap activeStep="review" onSelectScan={onSelectScan} onSelectConfirm={onSelectConfirm} />);

    await user.click(screen.getByRole('button', { name: /Scan/ }));
    expect(onSelectScan).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: /Confirm/ }));
    expect(onSelectConfirm).toHaveBeenCalledTimes(1);

    // Review has no generic entry point in the current UI (it always needs a
    // clusterId from the queue) -- it must not render as a disabled/fake button.
    expect(screen.queryByRole('button', { name: /Review/ })).not.toBeInTheDocument();
  });
});
