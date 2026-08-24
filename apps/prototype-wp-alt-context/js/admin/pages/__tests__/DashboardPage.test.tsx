import { fireEvent, render, screen } from '@testing-library/react';

import { DashboardPage } from '../DashboardPage';
import type { DashboardStats } from '../../api/dashboardApi';
import type { SyncHealthResponse } from '../../api/recognition';
import { useIdentityStats } from '../../hooks/useIdentityStats';
import { useMediaStats } from '../../hooks/useMediaStats';
import { useRecognitionJobHistory } from '../../hooks/useRecognitionJobHistory';
import { useResetMirror } from '../../hooks/useSyncTrigger';
import { useSyncStatus } from '../../hooks/useSyncStatus';
import { useSyncHealth } from '../../hooks/useSyncHealth';
import { useRetentionStatus } from '../../hooks/useRetentionStatus';
import {
  RETENTION_CARD_ERROR_BODY,
  RETENTION_CARD_HEADING,
  RETENTION_CARD_LINK_HREF,
} from '../dashboard/retentionCardCopy';
import { createMockMutation, createMockQuery } from '../../test-utils/mockHooks';

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

vi.mock('../../hooks/useDescribeMedia', () => ({
  useDescribeMedia: () => ({ mutate: vi.fn(), isPending: false, data: undefined, error: null, reset: vi.fn() }),
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

vi.mock('../../hooks/useSyncHealth', () => ({
  useSyncHealth: vi.fn(),
}));

vi.mock('../../hooks/useSyncTrigger', () => ({
  useResetMirror: vi.fn(),
}));

vi.mock('../../hooks/useRetentionStatus', () => ({
  useRetentionStatus: vi.fn(),
}));

describe('DashboardPage', () => {
  const mockedUseMediaStats = vi.mocked(useMediaStats);
  const mockedUseRecognitionJobHistory = vi.mocked(useRecognitionJobHistory);
  const mockedUseIdentityStats = vi.mocked(useIdentityStats);
  const mockedUseSyncStatus = vi.mocked(useSyncStatus);
  const mockedUseSyncHealth = vi.mocked(useSyncHealth);
  const mockedUseResetMirror = vi.mocked(useResetMirror);
  const mockedUseRetentionStatus = vi.mocked(useRetentionStatus);

  const expectBefore = (first: HTMLElement, second: HTMLElement) => {
    expect(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
  };

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
      recentActivity: [],
      historySource: 'durable',
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
    mockedUseSyncHealth.mockReturnValue(createMockQuery<SyncHealthResponse>({ data: undefined }));
    mockedUseResetMirror.mockReturnValue(createMockMutation());
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

  it('renders a landing summary describing what the product does, not operator chores', () => {
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

    expect(
      screen.getByText('It finds the people in your media library and writes alt text that names them.'),
    ).toBeInTheDocument();
    expect(
      screen.queryByText('Monitor your library coverage and manage identity recognition jobs.'),
    ).not.toBeInTheDocument();
  });

  it('renders the page heading as "Overview", matching the renamed admin menu label', () => {
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

    // The visible hero title is now a <p> (WordPress shell owns the page's only
    // <h1>, ORCH-UX-UI-BR-23); assert via the section's accessible name so the
    // test still fails if the preserved id/aria-labelledby link is broken.
    expect(screen.getByRole('region', { name: 'Overview' })).toBeInTheDocument();
    expect(screen.queryByText('Alt Context Dashboard')).not.toBeInTheDocument();
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
    expect(screen.getByRole('link', { name: 'Go to Review Queue' })).toHaveAttribute(
      'href',
      '#/workbench?advanced=open',
    );
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
          progress: { completed: 24, total: 24, images_processed: 24 },
          started_at: '2026-03-04T10:00:00.000Z',
          finished_at: '2026-03-04T10:02:05.000Z',
          message: null,
        },
      },
      recentActivity: [
        {
          id: 'run-1',
          jobId: 'job-1',
          runId: 'run-1',
          provenance: 'durable_batch_run',
          statusText: 'completed',
        },
      ],
      historySource: 'durable',
      jobId: 'job-1',
      rememberJob: vi.fn(),
      selectJob: vi.fn(),
      forgetJob: vi.fn(),
      clearHistory: vi.fn(),
    });

    render(<DashboardPage />);

    expect(screen.getByText('Duration: 2m 05s')).toBeInTheDocument();
    expect(screen.getByText('Durable batch run')).toBeInTheDocument();
    expect(screen.getByText(/Scan finished · 24 images ·/)).toBeInTheDocument();
    expect(screen.queryByText('job-1')).not.toBeInTheDocument();
    expect(screen.queryByText('run-1')).not.toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'View Results' });
    expect(link).toHaveAttribute('href', '#/workbench?advanced=open');
  });

  it('labels browser-local fallback activity explicitly', () => {
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
      jobHistory: ['job-local-1'],
      jobStatuses: { 'job-local-1': 'Unknown' },
      jobDetails: {},
      recentActivity: [
        {
          id: 'job-local-1',
          jobId: 'job-local-1',
          runId: null,
          provenance: 'browser_local_fallback',
          statusText: 'Remembered in this browser only',
        },
      ],
      historySource: 'browser_local_fallback',
      jobId: 'job-local-1',
      rememberJob: vi.fn(),
      selectJob: vi.fn(),
      forgetJob: vi.fn(),
      clearHistory: vi.fn(),
    });

    render(<DashboardPage />);

    expect(screen.getByText('Showing jobs remembered in this browser only.')).toBeInTheDocument();
    expect(screen.getByText('Current browser memory')).toBeInTheDocument();
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
      recentActivity: [
        {
          id: 'job-unavailable',
          jobId: 'job-unavailable',
          runId: null,
          provenance: 'browser_local_fallback',
          statusText: 'Status unavailable. Refresh to retry.',
        },
      ],
      historySource: 'browser_local_fallback',
      jobId: 'job-unavailable',
      rememberJob: vi.fn(),
      selectJob: vi.fn(),
      forgetJob: vi.fn(),
      clearHistory: vi.fn(),
    });

    render(<DashboardPage />);

    expect(screen.getByText('Status unavailable. Refresh to retry.')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'View Results' });
    expect(link).toHaveAttribute('href', '#/workbench?advanced=open');
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

    expect(screen.getByText('3 persons have no assigned face groups.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Review 3 unassigned persons' })).toHaveAttribute(
      'href',
      '#/roster?personFilter=unassigned',
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

  it('shows retention summary heading and links to the retention page', () => {
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

    expect(screen.getByText(RETENTION_CARD_HEADING)).toBeInTheDocument();
    expect(screen.getByText('Dispose after ack')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open Data Retention/ })).toHaveAttribute('href', RETENTION_CARD_LINK_HREF);
  });

  it('does not render the Batch Operations panel', () => {
    mockedUseRecognitionJobHistory.mockReturnValue({
      jobHistory: ['job-batch-9'],
      jobStatuses: { 'job-batch-9': 'completed' },
      jobDetails: {},
      recentActivity: [
        {
          id: 'run-batch-9',
          jobId: 'job-batch-9',
          runId: 'run-batch-9',
          provenance: 'durable_batch_run',
          statusText: 'completed',
        },
      ],
      historySource: 'durable',
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

    expect(screen.queryByRole('heading', { name: 'Batch Operations' })).not.toBeInTheDocument();
    expect(screen.queryByText(/Most recent batch job:/)).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Analysis Queue/ })).not.toBeInTheDocument();
  });

  it('keeps orientation above telemetry for a pre-seeded viewer until a person is named', () => {
    mockedUseIdentityStats.mockReturnValue(
      createMockQuery<DashboardStats>({
        data: {
          people_count: 3,
          assigned_clusters_count: 0,
          pending_clusters_count: 3,
          media_with_faces_count: 5,
          unassigned_persons_count: 0,
        },
        refetch: vi.fn(),
      }),
    );

    const { unmount } = render(<DashboardPage />);

    const orientationHeading = screen.getByRole('heading', { name: 'Getting Started with Identity Recognition' });
    expect(orientationHeading).toBeInTheDocument();
    expectBefore(
      orientationHeading.closest('section')!,
      screen.getByRole('heading', { name: 'Sync Health' }).closest('section')!,
    );
    unmount();

    mockedUseIdentityStats.mockReturnValue(
      createMockQuery<DashboardStats>({
        data: {
          people_count: 3,
          assigned_clusters_count: 1,
          pending_clusters_count: 0,
          media_with_faces_count: 5,
          unassigned_persons_count: 0,
        },
        refetch: vi.fn(),
      }),
    );

    render(<DashboardPage />);

    expect(
      screen.queryByRole('heading', { name: 'Getting Started with Identity Recognition' }),
    ).not.toBeInTheDocument();
  });

  it('gives an absent identity response a named unknown state with retry without promoting it', () => {
    const refetch = vi.fn();
    mockedUseIdentityStats.mockReturnValue(
      createMockQuery<DashboardStats>({ status: 'success', data: undefined, refetch }),
    );

    render(<DashboardPage />);

    const syncHeading = screen.getByRole('heading', { name: 'Sync Health' });
    const identityHeading = screen.getByRole('heading', { name: 'Identity Recognition' });
    expectBefore(syncHeading.closest('section')!, identityHeading.closest('section')!);
    expect(screen.getByText('Identity stats are unavailable.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry identity stats' }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it('links Library Coverage to workbench missing-status filter', () => {
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

    expect(screen.getByRole('link', { name: 'Fix missing descriptions' })).toHaveAttribute(
      'href',
      '#/workbench?status=missing',
    );
  });

  it('does not render the DescribePanel hero on the dashboard', () => {
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

    expect(screen.queryByRole('heading', { name: /AI Image Description/i })).not.toBeInTheDocument();
  });

  it('does not render the retention panel when the endpoint is not configured', () => {
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

    expect(screen.queryByText(RETENTION_CARD_HEADING)).not.toBeInTheDocument();
    expect(screen.queryByText(RETENTION_CARD_ERROR_BODY)).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Open Data Retention/ })).not.toBeInTheDocument();
  });

  it('shows remediation copy and retention link when retention status fails to load', () => {
    mockedUseRetentionStatus.mockReturnValue(
      createMockQuery({
        status: 'error',
        isError: true,
        error: new Error('retention fetch failed'),
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

    expect(screen.getByText(RETENTION_CARD_HEADING)).toBeInTheDocument();
    expect(screen.getByText(RETENTION_CARD_ERROR_BODY)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open Data Retention/ })).toHaveAttribute('href', RETENTION_CARD_LINK_HREF);
  });

  it('does not render the retention panel while retention status is loading', () => {
    mockedUseRetentionStatus.mockReturnValue(
      createMockQuery({
        status: 'pending',
        isLoading: true,
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

    expect(screen.queryByText(RETENTION_CARD_HEADING)).not.toBeInTheDocument();
    expect(screen.queryByText(RETENTION_CARD_ERROR_BODY)).not.toBeInTheDocument();
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

    expect(screen.getByText(RETENTION_CARD_HEADING)).toBeInTheDocument();
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

    expect(screen.getByText(RETENTION_CARD_HEADING)).toBeInTheDocument();
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

    expect(screen.getByText('Conflict resolution is blocking part of the sync queue.')).toBeInTheDocument();
    expect(screen.getByText('Pending changes')).toBeInTheDocument();
    expect(screen.getByText('Conflicts')).toBeInTheDocument();
    expect(screen.getByText('Failed operations')).toBeInTheDocument();
    expect(screen.getByText('4 waiting, 1 failed, 2 need review')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open Conflict Inbox/ })).toHaveAttribute(
      'href',
      '#/workbench?tab=scan&panel=conflicts',
    );
    expect(screen.getByRole('link', { name: /Open Failed Sync Queue/ })).toHaveAttribute(
      'href',
      '#/workbench?tab=scan&panel=dead-letter',
    );
  });

  it('renders source-backed replay recency details when conflicts and failures are present', () => {
    const expectedConflictDate = new Date('2026-03-07T02:15:00Z').toLocaleDateString();
    const expectedFailureDate = new Date('2026-03-07T02:25:00Z').toLocaleDateString();

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
          last_curation_conflict_at: '2026-03-07T02:15:00Z',
          last_curation_failed_at: '2026-03-07T02:25:00Z',
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

    expect(screen.getByText(`Last conflict: ${expectedConflictDate}`)).toBeInTheDocument();
    expect(screen.getByText(`Last failure: ${expectedFailureDate}`)).toBeInTheDocument();
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

    expect(screen.getByText('Everything is saved and up to date.')).toBeInTheDocument();
    expect(screen.getByText('Pending changes')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Open Conflict Inbox/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Open Failed Sync Queue/ })).not.toBeInTheDocument();
  });

  it('renders sync health before review work when sync needs attention', () => {
    mockedUseSyncStatus.mockReturnValue(
      createMockQuery({
        data: {
          last_snapshot_version: 1,
          last_synced_at: '2026-03-10T10:00:00Z',
          is_stale: false,
          sync_health: 'conflicts',
          last_sync_result: 'ok',
          pending_curation_operations: 2,
          conflict_count: 1,
          failed_curation_operations: 0,
        },
      }),
    );
    mockedUseIdentityStats.mockReturnValue(
      createMockQuery<DashboardStats>({
        data: {
          people_count: 4,
          assigned_clusters_count: 2,
          pending_clusters_count: 3,
          media_with_faces_count: 10,
          unassigned_persons_count: 0,
        },
        refetch: vi.fn(),
      }),
    );

    render(<DashboardPage />);

    expectBefore(
      screen.getByRole('heading', { name: 'Sync Health' }),
      screen.getByRole('heading', { name: 'Identity Recognition' }),
    );
    expect(
      screen.queryByRole('heading', { name: 'Getting Started with Identity Recognition' }),
    ).not.toBeInTheDocument();
  });

  it('renders review work before sync health when sync is healthy', () => {
    mockedUseIdentityStats.mockReturnValue(
      createMockQuery<DashboardStats>({
        data: {
          people_count: 4,
          assigned_clusters_count: 2,
          pending_clusters_count: 3,
          media_with_faces_count: 10,
          unassigned_persons_count: 0,
        },
        refetch: vi.fn(),
      }),
    );

    render(<DashboardPage />);

    expectBefore(
      screen.getByRole('heading', { name: 'Identity Recognition' }),
      screen.getByRole('heading', { name: 'Sync Health' }),
    );
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

    expect(
      screen.getByText('Your changes are saved here and will sync when the service is available.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Pending changes')).toBeInTheDocument();
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

    expect(screen.getByText('This view may be out of date — sync now to refresh it.')).toBeInTheDocument();
  });

  it('renders a stale-mirror banner when the backend snapshot is empty but local clusters remain', () => {
    mockedUseSyncStatus.mockReturnValue(
      createMockQuery({
        data: {
          last_snapshot_version: 0,
          last_synced_at: '2026-03-10T10:00:00Z',
          is_stale: true,
          sync_health: 'stale',
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
          pending_clusters_count: 3,
          media_with_faces_count: 10,
          unassigned_persons_count: 0,
        },
        refetch: vi.fn(),
      }),
    );

    render(<DashboardPage />);

    expect(
      screen.getByText('Mirror is out of sync with the backend — 7 stale face groups, 2 failed sync events.'),
    ).toBeInTheDocument();
  });

  it('renders a reset mirror action for stale backend-empty divergence and triggers it on click', () => {
    const mutate = vi.fn();

    mockedUseSyncStatus.mockReturnValue(
      createMockQuery({
        data: {
          last_snapshot_version: 0,
          last_synced_at: '2026-03-10T10:00:00Z',
          is_stale: true,
          sync_health: 'stale',
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
          pending_clusters_count: 3,
          media_with_faces_count: 10,
          unassigned_persons_count: 0,
        },
        refetch: vi.fn(),
      }),
    );
    mockedUseResetMirror.mockReturnValue(
      createMockMutation({
        mutate,
      }),
    );

    render(<DashboardPage />);

    const banner = screen.getByRole('status');
    expect(banner).toHaveClass('acx-dashboard__mirror-warning');

    const resetButton = screen.getByRole('button', { name: 'Reset mirror' });
    fireEvent.click(resetButton);

    expect(mutate).toHaveBeenCalledTimes(1);
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

    expect(screen.getByText('Some sync operations failed and need operator attention.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open Failed Sync Queue/ })).toBeInTheDocument();
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
