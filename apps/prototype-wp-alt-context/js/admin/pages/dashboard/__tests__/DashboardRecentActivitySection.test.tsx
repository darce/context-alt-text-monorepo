import { render, screen } from '@testing-library/react';

import { buildActivitySummary, DashboardRecentActivitySection } from '../DashboardRecentActivitySection';
import type { JobStatusResponse } from '../../../api/recognition/types/scan';
import type { RecognitionActivityItem } from '../../../hooks/recognitionJobHistoryUtils';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (format: string, ...args: (string | number)[]) => {
    let sequentialIndex = 0;
    return format.replace(/%((\d+)\$)?([sd])/g, (_match, _position, explicitIndex) => {
      if (explicitIndex) {
        return String(args[Number(explicitIndex) - 1] ?? '');
      }
      return String(args[sequentialIndex++] ?? '');
    });
  },
}));

const UUID = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890';

describe('buildActivitySummary', () => {
  it('builds verb + counts + relative time without raw identifiers', () => {
    const item: RecognitionActivityItem = {
      id: UUID,
      jobId: UUID,
      runId: 'run-' + UUID,
      provenance: 'durable_batch_run',
      statusText: 'completed',
    };
    const jobDetail: JobStatusResponse = {
      id: UUID,
      type: 'analyze',
      status: 'completed',
      progress: { completed: 24, total: 24, images_processed: 24 },
      started_at: '2026-03-04T08:00:00.000Z',
      finished_at: '2026-03-04T10:00:00.000Z',
      message: null,
    };
    const now = new Date('2026-03-04T12:00:00.000Z').getTime();

    const summary = buildActivitySummary(item, jobDetail, 'completed', now);

    expect(summary).toBe('Scan finished · 24 images · 2 hours ago');
    expect(summary).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}/i);
    expect(summary).not.toContain(UUID);
  });

  it('uses a short verb when status is unavailable long copy', () => {
    const item: RecognitionActivityItem = {
      id: 'job-unavailable',
      jobId: 'job-unavailable',
      runId: null,
      provenance: 'browser_local_fallback',
      statusText: 'Status unavailable. Refresh to retry.',
    };

    const summary = buildActivitySummary(item, undefined, 'Status unavailable. Refresh to retry.');

    expect(summary).toBe('Recognition job');
    expect(summary).not.toContain('Status unavailable');
  });
});

describe('DashboardRecentActivitySection', () => {
  it('offers a scan action when recent activity is empty', () => {
    render(
      <DashboardRecentActivitySection
        historySource="durable"
        recentActivity={[]}
        jobStatuses={{}}
        jobDetails={{}}
      />,
    );

    expect(screen.getByRole('link', { name: 'Run a scan' })).toHaveAttribute('href', '#/workbench?tab=scan');
  });

  // DUX-W2D6C-RV-06 / A11Y-21 / TEST-15: announceState={false} with no host
  // status channel leaves empty/unavailable transitions silent.
  it('DUX-W2D6C-RV-06: empty recent activity announces via exactly one live region', () => {
    render(
      <DashboardRecentActivitySection
        historySource="durable"
        recentActivity={[]}
        jobStatuses={{}}
        jobDetails={{}}
      />,
    );

    const liveRegions = screen.getAllByRole('status');
    expect(liveRegions).toHaveLength(1);
    expect(screen.getByTestId('acx-empty-state-live-region')).toBe(liveRegions[0]);
  });

  it('DUX-W2D6C-RV-06: unavailable recent activity announces via exactly one live region', () => {
    render(
      <DashboardRecentActivitySection
        historySource="unavailable"
        recentActivity={[]}
        jobStatuses={{}}
        jobDetails={{}}
      />,
    );

    const liveRegions = screen.getAllByRole('status');
    expect(liveRegions).toHaveLength(1);
    expect(screen.getByTestId('acx-empty-state-live-region')).toBe(liveRegions[0]);
  });

  it('does not render raw job or run identifiers in visible text', () => {
    const jobId = '550e8400-e29b-41d4-a716-446655440000';
    const runId = '660e8400-e29b-41d4-a716-446655440000';

    render(
      <DashboardRecentActivitySection
        historySource="durable"
        jobStatuses={{ [jobId]: 'completed' }}
        jobDetails={{
          [jobId]: {
            id: jobId,
            type: 'analyze',
            status: 'completed',
            progress: { completed: 10, total: 10, images_processed: 10 },
            started_at: '2026-03-04T10:00:00.000Z',
            finished_at: '2026-03-04T10:05:00.000Z',
            message: null,
          },
        }}
        recentActivity={[
          {
            id: runId,
            jobId,
            runId,
            provenance: 'durable_batch_run',
            statusText: 'completed',
          },
        ]}
      />,
    );

    const list = screen.getByRole('list');
    expect(list.textContent).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i);
    expect(screen.getByText(/Scan finished · 10 images ·/)).toBeInTheDocument();
    expect(screen.getByText('Durable batch run')).toBeInTheDocument();
    // Dead jobId param dropped (E21-10); link opens advanced workbench only.
    expect(screen.getByRole('link', { name: 'View Results' })).toHaveAttribute(
      'href',
      '#/workbench?advanced=open',
    );
  });
});
