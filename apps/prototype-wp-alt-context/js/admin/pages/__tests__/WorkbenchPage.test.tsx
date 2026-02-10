import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ConfirmPanel, RecentJobsPanel, mediaEditUrl } from '../workbench/Panels';

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

    const button = screen.getByRole('button', { name: 'Open clusters in roster' });
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

    const button = screen.getByRole('button', { name: 'Open clusters in roster' });
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
    await userEvent.click(screen.getByRole('button', { name: 'Open clusters in roster' }));

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
