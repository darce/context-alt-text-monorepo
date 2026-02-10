import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ConfirmPanel, RecentJobsPanel, mediaEditUrl } from '../workbench/Panels';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string, ...args: (string | number)[]) => {
    let index = 0;
    return format.replace(/%s/g, () => String(args[index++]));
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

// Follow-up coverage tracked in docs/tasks/4.0/4.13.0/review-69ab3b4-gaps.md#g-7.
test.todo('[ACX-4130-G7-WB-1] Workbench provides a Rescan with sensitivity option once a job is selected');
test.todo('[ACX-4130-G7-WB-2] Workbench clusters panel shows summary cards after clustering runs');
