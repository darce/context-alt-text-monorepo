import { render, screen } from '@testing-library/react';

import { DashboardPage } from '../DashboardPage';
import type { DashboardStats } from '../../api/dashboardApi';
import { useIdentityStats } from '../../hooks/useIdentityStats';
import { useMediaStats } from '../../hooks/useMediaStats';
import { useRecognitionJobHistory } from '../../hooks/useRecognitionJobHistory';
import { useSyncStatus } from '../../hooks/useSyncStatus';
import { useRetentionStatus } from '../../hooks/useRetentionStatus';
import { createMockQuery } from '../../test-utils/mockHooks';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
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

vi.mock('../../hooks/useMediaStats', () => ({
  useMediaStats: vi.fn(),
}));

vi.mock('../../hooks/useRecognitionJobHistory', () => ({
  useRecognitionJobHistory: vi.fn(),
}));

vi.mock('../../hooks/useIdentityStats', () => ({
  useIdentityStats: vi.fn(),
}));

vi.mock('../../hooks/useSyncStatus', () => ({
  useSyncStatus: vi.fn(),
}));

vi.mock('../../hooks/useRetentionStatus', () => ({
  useRetentionStatus: vi.fn(),
}));

vi.mock('../dashboard/OrientationCard', () => ({
  OrientationCard: () => <div>Orientation</div>,
}));

describe('DashboardPage', () => {
  const mockedUseMediaStats = vi.mocked(useMediaStats);
  const mockedUseRecognitionJobHistory = vi.mocked(useRecognitionJobHistory);
  const mockedUseIdentityStats = vi.mocked(useIdentityStats);
  const mockedUseSyncStatus = vi.mocked(useSyncStatus);
  const mockedUseRetentionStatus = vi.mocked(useRetentionStatus);

  beforeEach(() => {
    vi.clearAllMocks();
    mockedUseMediaStats.mockReturnValue({
      stats: { total: 100, missing: 20, complete: 80, coverage: 80 },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    mockedUseRecognitionJobHistory.mockReturnValue({
      jobHistory: [],
      jobStatuses: {},
      jobDetails: {},
      jobId: null,
      rememberJob: vi.fn(),
      selectJob: vi.fn(),
      forgetJob: vi.fn(),
      clearHistory: vi.fn(),
    });
    mockedUseSyncStatus.mockReturnValue(
      createMockQuery({
        data: {
          last_snapshot_version: 1,
          last_synced_at: '2026-03-10T10:00:00Z',
          is_stale: false,
          sync_health: 'healthy',
          last_sync_result: 'ok',
          conflict_count: 0,
          failed_curation_operations: 0,
        },
      }),
    );
    mockedUseRetentionStatus.mockReturnValue(
      createMockQuery({
        data: {
          available: true,
          policy: {
            retention_mode: 'dispose_after_ack',
            last_export_at: '2026-03-08T10:00:00Z',
            last_purge_at: null,
            retention_updated_at: '2026-03-07T09:00:00Z',
          },
          recent_audit_events: [],
        },
      }),
    );
  });

  it('renders identity stats and pending-review guidance', () => {
    mockedUseIdentityStats.mockReturnValue(
      createMockQuery<DashboardStats>({
        data: {
          people_count: 10,
          assigned_clusters_count: 7,
          pending_clusters_count: 3,
          media_with_faces_count: 22,
          unassigned_persons_count: 0,
        },
        refetch: vi.fn(),
      }),
    );

    render(<DashboardPage />);

    expect(screen.getByText('10')).toBeInTheDocument();
    expect(screen.getByText('7')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('22')).toBeInTheDocument();
    expect(screen.getByText('Media with faces')).toBeInTheDocument();
    expect(screen.getByText('3 faces are waiting for names.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Go to Workbench' })).toHaveAttribute('href', '#/workbench?tab=confirm');
  });

  it('shows first-use guidance when roster is empty and nothing pending', () => {
    mockedUseIdentityStats.mockReturnValue(
      createMockQuery<DashboardStats>({
        data: {
          people_count: 0,
          assigned_clusters_count: 0,
          pending_clusters_count: 0,
          media_with_faces_count: 0,
          unassigned_persons_count: 0,
        },
        refetch: vi.fn(),
      }),
    );

    render(<DashboardPage />);

    expect(screen.getByText('Start by scanning your media library for faces.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Go to Scan tab' })).toHaveAttribute('href', '#/workbench?tab=scan');
  });

  it('shows all-caught-up guidance when no pending review remains', () => {
    mockedUseIdentityStats.mockReturnValue(
      createMockQuery<DashboardStats>({
        data: {
          people_count: 4,
          assigned_clusters_count: 4,
          pending_clusters_count: 0,
          media_with_faces_count: 10,
          unassigned_persons_count: 0,
        },
        refetch: vi.fn(),
      }),
    );

    render(<DashboardPage />);

    expect(screen.getByText('All caught up. New faces will appear here for review.')).toBeInTheDocument();
  });

  it('renders recent activity duration and results link when timing is available', () => {
    mockedUseIdentityStats.mockReturnValue(
      createMockQuery<DashboardStats>({
        data: {
          people_count: 4,
          assigned_clusters_count: 4,
          pending_clusters_count: 0,
          media_with_faces_count: 10,
          unassigned_persons_count: 0,
        },
        refetch: vi.fn(),
      }),
    );
    mockedUseRecognitionJobHistory.mockReturnValue({
      jobHistory: ['job-1'],
      jobStatuses: { 'job-1': 'completed' },
      jobDetails: {
        'job-1': {
          id: 'job-1',
          type: 'analyze',
          status: 'completed',
          progress: null,
          started_at: '2026-03-04T10:00:00.000Z',
          finished_at: '2026-03-04T10:02:05.000Z',
          message: null,
        },
      },
      jobId: 'job-1',
      rememberJob: vi.fn(),
      selectJob: vi.fn(),
      forgetJob: vi.fn(),
      clearHistory: vi.fn(),
    });

    render(<DashboardPage />);

    expect(screen.getByText('Duration: 2m 05s')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'View Results' });
    expect(link).toHaveAttribute('href', '#/workbench?tab=confirm&jobId=job-1');
  });

  it('shows status unavailable copy and keeps results link when job details are missing', () => {
    mockedUseIdentityStats.mockReturnValue(
      createMockQuery<DashboardStats>({
        data: {
          people_count: 4,
          assigned_clusters_count: 4,
          pending_clusters_count: 0,
          media_with_faces_count: 10,
          unassigned_persons_count: 0,
        },
        refetch: vi.fn(),
      }),
    );
    mockedUseRecognitionJobHistory.mockReturnValue({
      jobHistory: ['job-unavailable'],
      jobStatuses: {},
      jobDetails: {},
      jobId: 'job-unavailable',
      rememberJob: vi.fn(),
      selectJob: vi.fn(),
      forgetJob: vi.fn(),
      clearHistory: vi.fn(),
    });

    render(<DashboardPage />);

    expect(screen.getByText('Status unavailable. Refresh to retry.')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'View Results' });
    expect(link).toHaveAttribute('href', '#/workbench?tab=confirm&jobId=job-unavailable');
  });

  it('shows unassigned-person guidance when there are unassigned persons', () => {
    mockedUseIdentityStats.mockReturnValue(
      createMockQuery<DashboardStats>({
        data: {
          people_count: 8,
          assigned_clusters_count: 5,
          pending_clusters_count: 0,
          media_with_faces_count: 21,
          unassigned_persons_count: 3,
        },
        refetch: vi.fn(),
      }),
    );

    render(<DashboardPage />);

    expect(screen.getByText('3 persons have no assigned clusters.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Review 3 unassigned persons' })).toHaveAttribute(
      'href',
      '#/roster?tab=entries&personFilter=unassigned',
    );
    expect(screen.getByText('3', { selector: '.acx-dashboard__guidance-count' })).toBeInTheDocument();
  });

  it('renders zero for media-with-faces when no faces are detected', () => {
    mockedUseIdentityStats.mockReturnValue(
      createMockQuery<DashboardStats>({
        data: {
          people_count: 2,
          assigned_clusters_count: 1,
          pending_clusters_count: 0,
          media_with_faces_count: 0,
          unassigned_persons_count: 1,
        },
        refetch: vi.fn(),
      }),
    );

    render(<DashboardPage />);

    const mediaLabel = screen.getByText('Media with faces');
    const mediaStat = mediaLabel.closest('.acx-dashboard__stat');
    expect(mediaStat).not.toBeNull();
    expect(mediaStat).toHaveTextContent('0');
  });

  it('shows retention posture summary and links to the retention page', () => {
    mockedUseIdentityStats.mockReturnValue(
      createMockQuery<DashboardStats>({
        data: {
          people_count: 4,
          assigned_clusters_count: 4,
          pending_clusters_count: 0,
          media_with_faces_count: 10,
          unassigned_persons_count: 0,
        },
        refetch: vi.fn(),
      }),
    );

    render(<DashboardPage />);

    expect(screen.getByText('Retention posture')).toBeInTheDocument();
    expect(screen.getByText('Dispose after ack')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open Retention Controls/ })).toHaveAttribute('href', '#/retention');
  });

  it('surfaces batch operations from the dashboard with latest-job follow-up', () => {
    mockedUseRecognitionJobHistory.mockReturnValue({
      jobHistory: ['job-batch-9'],
      jobStatuses: { 'job-batch-9': 'completed' },
      jobDetails: {},
      jobId: 'job-batch-9',
      rememberJob: vi.fn(),
      selectJob: vi.fn(),
      forgetJob: vi.fn(),
      clearHistory: vi.fn(),
    });
    mockedUseIdentityStats.mockReturnValue(
      createMockQuery<DashboardStats>({
        data: {
          people_count: 4,
          assigned_clusters_count: 4,
          pending_clusters_count: 0,
          media_with_faces_count: 10,
          unassigned_persons_count: 0,
        },
        refetch: vi.fn(),
      }),
    );

    render(<DashboardPage />);

    expect(screen.getByText('Batch Operations')).toBeInTheDocument();
    expect(
      screen.getByText(
        'Start new recognition batches from Dashboard, then jump back into scan, review, or roster cleanup from the same landing page.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByText('Most recent batch job: job-batch-9')).toBeInTheDocument();
    expect(screen.getByText('Latest batch status: completed')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'View latest results' })).toHaveAttribute(
      'href',
      '#/workbench?tab=confirm&jobId=job-batch-9',
    );
    expect(screen.getByRole('link', { name: /Analysis Queue/ })).toHaveAttribute('href', '#/workbench?tab=scan');
    expect(screen.getByRole('link', { name: /Review Hub/ })).toHaveAttribute('href', '#/workbench?tab=confirm');
  });

  it('shows retention unavailable copy when the retention proxy is degraded', () => {
    mockedUseRetentionStatus.mockReturnValue(
      createMockQuery({
        data: {
          available: false,
          policy: null,
          recent_audit_events: [],
        },
      }),
    );
    mockedUseIdentityStats.mockReturnValue(
      createMockQuery<DashboardStats>({
        data: {
          people_count: 4,
          assigned_clusters_count: 4,
          pending_clusters_count: 0,
          media_with_faces_count: 10,
          unassigned_persons_count: 0,
        },
        refetch: vi.fn(),
      }),
    );

    render(<DashboardPage />);

    expect(screen.getByText('Retention posture')).toBeInTheDocument();
    expect(screen.getByText('Retention status is unavailable right now.')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Open Retention Controls/ })).not.toBeInTheDocument();
  });

  it('shows the purge-on-demand retention label when configured', () => {
    mockedUseRetentionStatus.mockReturnValue(
      createMockQuery({
        data: {
          available: true,
          policy: {
            retention_mode: 'purge_on_demand',
            last_export_at: '2026-03-08T10:00:00Z',
            last_purge_at: null,
            retention_updated_at: '2026-03-07T09:00:00Z',
          },
          recent_audit_events: [],
        },
      }),
    );
    mockedUseIdentityStats.mockReturnValue(
      createMockQuery<DashboardStats>({
        data: {
          people_count: 4,
          assigned_clusters_count: 4,
          pending_clusters_count: 0,
          media_with_faces_count: 10,
          unassigned_persons_count: 0,
        },
        refetch: vi.fn(),
      }),
    );

    render(<DashboardPage />);

    expect(screen.getByText('Retention posture')).toBeInTheDocument();
    expect(screen.getByText('Purge on demand')).toBeInTheDocument();
  });

  it('shows the retain-all retention label when configured', () => {
    mockedUseRetentionStatus.mockReturnValue(
      createMockQuery({
        data: {
          available: true,
          policy: {
            retention_mode: 'retain_all',
            last_export_at: '2026-03-08T10:00:00Z',
            last_purge_at: null,
            retention_updated_at: '2026-03-07T09:00:00Z',
          },
          recent_audit_events: [],
        },
      }),
    );
    mockedUseIdentityStats.mockReturnValue(
      createMockQuery<DashboardStats>({
        data: {
          people_count: 4,
          assigned_clusters_count: 4,
          pending_clusters_count: 0,
          media_with_faces_count: 10,
          unassigned_persons_count: 0,
        },
        refetch: vi.fn(),
      }),
    );

    render(<DashboardPage />);

    expect(screen.getByText('Retention posture')).toBeInTheDocument();
    expect(screen.getByText('Retain all')).toBeInTheDocument();
  });

  it('shows identity error state with retry action', () => {
    const refetch = vi.fn();
    mockedUseIdentityStats.mockReturnValue(
      createMockQuery<DashboardStats>({
        status: 'error',
        isError: true,
        error: new Error('Unable to load identity stats.'),
        refetch,
      }),
    );

    render(<DashboardPage />);

    expect(screen.getByText('Unable to load identity stats.')).toBeInTheDocument();
    expect(screen.queryByText('Loading identity stats…')).not.toBeInTheDocument();
    const retryButton = screen.getByRole('button', { name: 'Retry' });
    retryButton.click();
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it('shows dashboard sync links for conflicts and dead-letter work', () => {
    mockedUseSyncStatus.mockReturnValue(
      createMockQuery({
        data: {
          last_snapshot_version: 1,
          last_synced_at: '2026-03-10T10:00:00Z',
          is_stale: false,
          sync_health: 'conflicts',
          last_sync_result: 'ok',
          pending_curation_operations: 3,
          conflict_count: 2,
          failed_curation_operations: 1,
          topology_commands: {
            pending: 4,
            applied: 0,
            failed: 1,
            conflict: 2,
            last_reconciled_at: null,
          },
        },
      }),
    );
    mockedUseIdentityStats.mockReturnValue(
      createMockQuery<DashboardStats>({
        data: {
          people_count: 4,
          assigned_clusters_count: 4,
          pending_clusters_count: 0,
          media_with_faces_count: 10,
          unassigned_persons_count: 0,
        },
        refetch: vi.fn(),
      }),
    );

    render(<DashboardPage />);

    expect(screen.getByText('Conflict resolution is blocking part of the replay queue.')).toBeInTheDocument();
    expect(screen.getByText('Pending Replay')).toBeInTheDocument();
    expect(screen.getByText('Conflicts')).toBeInTheDocument();
    expect(screen.getByText('Failed Replay')).toBeInTheDocument();
    expect(screen.getByText('Topology backlog: pending 4, failed 1, conflicts 2')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open Conflict Inbox/ })).toHaveAttribute(
      'href',
      '#/workbench?tab=scan&panel=conflicts',
    );
    expect(screen.getByRole('link', { name: /Open Dead-Letter Queue/ })).toHaveAttribute(
      'href',
      '#/workbench?tab=scan&panel=dead-letter',
    );
  });

  it('renders healthy sync summary copy without conflict or dead-letter links when counts are zero', () => {
    mockedUseIdentityStats.mockReturnValue(
      createMockQuery<DashboardStats>({
        data: {
          people_count: 4,
          assigned_clusters_count: 4,
          pending_clusters_count: 0,
          media_with_faces_count: 10,
          unassigned_persons_count: 0,
        },
        refetch: vi.fn(),
      }),
    );

    render(<DashboardPage />);

    expect(screen.getByText('Machine sync is healthy and curation replay is caught up.')).toBeInTheDocument();
    expect(screen.getByText('Pending Replay')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Open Conflict Inbox/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Open Dead-Letter Queue/ })).not.toBeInTheDocument();
  });

  it('renders queued sync summary copy with pending replay count', () => {
    mockedUseSyncStatus.mockReturnValue(
      createMockQuery({
        data: {
          last_snapshot_version: 1,
          last_synced_at: '2026-03-10T10:00:00Z',
          is_stale: false,
          sync_health: 'queued',
          last_sync_result: 'ok',
          pending_curation_operations: 5,
          conflict_count: 0,
          failed_curation_operations: 0,
        },
      }),
    );
    mockedUseIdentityStats.mockReturnValue(
      createMockQuery<DashboardStats>({
        data: {
          people_count: 4,
          assigned_clusters_count: 4,
          pending_clusters_count: 0,
          media_with_faces_count: 10,
          unassigned_persons_count: 0,
        },
        refetch: vi.fn(),
      }),
    );

    render(<DashboardPage />);

    expect(screen.getByText('Local curation changes are queued for replay.')).toBeInTheDocument();
    expect(screen.getByText('Pending Replay')).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
  });

  it('renders stale sync summary copy', () => {
    mockedUseSyncStatus.mockReturnValue(
      createMockQuery({
        data: {
          last_snapshot_version: 1,
          last_synced_at: '2026-03-10T10:00:00Z',
          is_stale: true,
          sync_health: 'stale',
          last_sync_result: 'ok',
          conflict_count: 0,
          failed_curation_operations: 0,
        },
      }),
    );
    mockedUseIdentityStats.mockReturnValue(
      createMockQuery<DashboardStats>({
        data: {
          people_count: 4,
          assigned_clusters_count: 4,
          pending_clusters_count: 0,
          media_with_faces_count: 10,
          unassigned_persons_count: 0,
        },
        refetch: vi.fn(),
      }),
    );

    render(<DashboardPage />);

    expect(screen.getByText('Machine state is stale and should be refreshed.')).toBeInTheDocument();
  });

  it('renders failures sync summary copy', () => {
    mockedUseSyncStatus.mockReturnValue(
      createMockQuery({
        data: {
          last_snapshot_version: 1,
          last_synced_at: '2026-03-10T10:00:00Z',
          is_stale: false,
          sync_health: 'failures',
          last_sync_result: 'failed',
          conflict_count: 0,
          failed_curation_operations: 2,
        },
      }),
    );
    mockedUseIdentityStats.mockReturnValue(
      createMockQuery<DashboardStats>({
        data: {
          people_count: 4,
          assigned_clusters_count: 4,
          pending_clusters_count: 0,
          media_with_faces_count: 10,
          unassigned_persons_count: 0,
        },
        refetch: vi.fn(),
      }),
    );

    render(<DashboardPage />);

    expect(screen.getByText('Some replay operations failed and need operator attention.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open Dead-Letter Queue/ })).toBeInTheDocument();
  });

  it('renders offline sync summary copy', () => {
    mockedUseSyncStatus.mockReturnValue(
      createMockQuery({
        data: {
          last_snapshot_version: 1,
          last_synced_at: '2026-03-10T10:00:00Z',
          is_stale: false,
          sync_health: 'offline',
          last_sync_result: 'unreachable',
          conflict_count: 0,
          failed_curation_operations: 0,
        },
      }),
    );
    mockedUseIdentityStats.mockReturnValue(
      createMockQuery<DashboardStats>({
        data: {
          people_count: 4,
          assigned_clusters_count: 4,
          pending_clusters_count: 0,
          media_with_faces_count: 10,
          unassigned_persons_count: 0,
        },
        refetch: vi.fn(),
      }),
    );

    render(<DashboardPage />);

    expect(screen.getByText('The recognition backend is currently unreachable.')).toBeInTheDocument();
  });
});
