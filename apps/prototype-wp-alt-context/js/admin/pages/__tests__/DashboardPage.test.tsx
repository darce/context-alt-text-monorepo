import { render, screen } from '@testing-library/react';

import { DashboardPage } from '../DashboardPage';
import type { DashboardStats } from '../../api/dashboardApi';
import { useIdentityStats } from '../../hooks/useIdentityStats';
import { useMediaStats } from '../../hooks/useMediaStats';
import { useRecognitionJobHistory } from '../../hooks/useRecognitionJobHistory';
import { createMockQuery } from '../../test-utils/mockHooks';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (format: string, ...args: (string | number)[]) => {
    let index = 0;
    return format.replace(/%(s|d)/g, () => String(args[index++]));
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

vi.mock('../dashboard/OrientationCard', () => ({
  OrientationCard: () => <div>Orientation</div>,
}));

describe('DashboardPage', () => {
  const mockedUseMediaStats = vi.mocked(useMediaStats);
  const mockedUseRecognitionJobHistory = vi.mocked(useRecognitionJobHistory);
  const mockedUseIdentityStats = vi.mocked(useIdentityStats);

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
      clearHistory: vi.fn(),
    });
  });

  it('renders identity stats and pending-review guidance', () => {
    mockedUseIdentityStats.mockReturnValue(createMockQuery<DashboardStats>({
      data: {
        people_count: 10,
        assigned_clusters_count: 7,
        pending_clusters_count: 3,
        media_with_faces_count: 22,
        unassigned_persons_count: 0,
      },
      refetch: vi.fn(),
    }));

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
    mockedUseIdentityStats.mockReturnValue(createMockQuery<DashboardStats>({
      data: {
        people_count: 0,
        assigned_clusters_count: 0,
        pending_clusters_count: 0,
        media_with_faces_count: 0,
        unassigned_persons_count: 0,
      },
      refetch: vi.fn(),
    }));

    render(<DashboardPage />);

    expect(screen.getByText('Start by scanning your media library for faces.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Go to Scan tab' })).toHaveAttribute('href', '#/workbench?tab=scan');
  });

  it('shows all-caught-up guidance when no pending review remains', () => {
    mockedUseIdentityStats.mockReturnValue(createMockQuery<DashboardStats>({
      data: {
        people_count: 4,
        assigned_clusters_count: 4,
        pending_clusters_count: 0,
        media_with_faces_count: 10,
        unassigned_persons_count: 0,
      },
      refetch: vi.fn(),
    }));

    render(<DashboardPage />);

    expect(screen.getByText('All caught up. New faces will appear here for review.')).toBeInTheDocument();
  });

  it('renders recent activity duration and results link when timing is available', () => {
    mockedUseIdentityStats.mockReturnValue(createMockQuery<DashboardStats>({
      data: {
        people_count: 4,
        assigned_clusters_count: 4,
        pending_clusters_count: 0,
        media_with_faces_count: 10,
        unassigned_persons_count: 0,
      },
      refetch: vi.fn(),
    }));
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
      clearHistory: vi.fn(),
    });

    render(<DashboardPage />);

    expect(screen.getByText('Duration: 2m 05s')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'View Results' });
    expect(link).toHaveAttribute('href', '#/workbench?tab=confirm&jobId=job-1');
  });

  it('shows status unavailable copy and keeps results link when job details are missing', () => {
    mockedUseIdentityStats.mockReturnValue(createMockQuery<DashboardStats>({
      data: {
        people_count: 4,
        assigned_clusters_count: 4,
        pending_clusters_count: 0,
        media_with_faces_count: 10,
        unassigned_persons_count: 0,
      },
      refetch: vi.fn(),
    }));
    mockedUseRecognitionJobHistory.mockReturnValue({
      jobHistory: ['job-unavailable'],
      jobStatuses: {},
      jobDetails: {},
      jobId: 'job-unavailable',
      rememberJob: vi.fn(),
      selectJob: vi.fn(),
      clearHistory: vi.fn(),
    });

    render(<DashboardPage />);

    expect(screen.getByText('Status unavailable. Refresh to retry.')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'View Results' });
    expect(link).toHaveAttribute('href', '#/workbench?tab=confirm&jobId=job-unavailable');
  });

  it('shows unassigned-person guidance when there are unassigned persons', () => {
    mockedUseIdentityStats.mockReturnValue(createMockQuery<DashboardStats>({
      data: {
        people_count: 8,
        assigned_clusters_count: 5,
        pending_clusters_count: 0,
        media_with_faces_count: 21,
        unassigned_persons_count: 3,
      },
      refetch: vi.fn(),
    }));

    render(<DashboardPage />);

    expect(screen.getByText('3 persons have no assigned clusters.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Review unassigned persons' })).toHaveAttribute(
      'href',
      '#/roster?tab=entries&personFilter=unassigned',
    );
  });

  it('renders zero for media-with-faces when no faces are detected', () => {
    mockedUseIdentityStats.mockReturnValue(createMockQuery<DashboardStats>({
      data: {
        people_count: 2,
        assigned_clusters_count: 1,
        pending_clusters_count: 0,
        media_with_faces_count: 0,
        unassigned_persons_count: 1,
      },
      refetch: vi.fn(),
    }));

    render(<DashboardPage />);

    const mediaLabel = screen.getByText('Media with faces');
    const mediaStat = mediaLabel.closest('.acx-dashboard__stat');
    expect(mediaStat).not.toBeNull();
    expect(mediaStat).toHaveTextContent('0');
  });

  it('shows identity error state with retry action', () => {
    const refetch = vi.fn();
    mockedUseIdentityStats.mockReturnValue(createMockQuery<DashboardStats>({
      status: 'error',
      isError: true,
      error: new Error('Unable to load identity stats.'),
      refetch,
    }));

    render(<DashboardPage />);

    expect(screen.getByText('Unable to load identity stats.')).toBeInTheDocument();
    expect(screen.queryByText('Loading identity stats…')).not.toBeInTheDocument();
    const retryButton = screen.getByRole('button', { name: 'Retry' });
    retryButton.click();
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});
