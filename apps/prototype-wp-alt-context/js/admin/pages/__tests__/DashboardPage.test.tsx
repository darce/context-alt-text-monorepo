import { render, screen } from '@testing-library/react';

import { DashboardPage } from '../DashboardPage';
import { useIdentityStats } from '../../hooks/useIdentityStats';
import { useMediaStats } from '../../hooks/useMediaStats';
import { useRecognitionJobHistory } from '../../hooks/useRecognitionJobHistory';

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
      stats: { total: 100, missing: 20, coverage: 80 },
      isLoading: false,
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
    mockedUseIdentityStats.mockReturnValue({
      data: { people_count: 10, assigned_clusters_count: 7, pending_clusters_count: 3 },
      isLoading: false,
    } as ReturnType<typeof useIdentityStats>);

    render(<DashboardPage />);

    expect(screen.getByText('10')).toBeInTheDocument();
    expect(screen.getByText('7')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('3 faces are waiting for names.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Go to Workbench' })).toBeInTheDocument();
  });

  it('shows first-use guidance when roster is empty and nothing pending', () => {
    mockedUseIdentityStats.mockReturnValue({
      data: { people_count: 0, assigned_clusters_count: 0, pending_clusters_count: 0 },
      isLoading: false,
    } as ReturnType<typeof useIdentityStats>);

    render(<DashboardPage />);

    expect(screen.getByText('Start by scanning your media library for faces.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Go to Scan tab' })).toBeInTheDocument();
  });

  it('shows all-caught-up guidance when no pending review remains', () => {
    mockedUseIdentityStats.mockReturnValue({
      data: { people_count: 4, assigned_clusters_count: 4, pending_clusters_count: 0 },
      isLoading: false,
    } as ReturnType<typeof useIdentityStats>);

    render(<DashboardPage />);

    expect(screen.getByText('All caught up. New faces will appear here for review.')).toBeInTheDocument();
  });

  it('renders recent activity duration and results link when timing is available', () => {
    mockedUseIdentityStats.mockReturnValue({
      data: { people_count: 4, assigned_clusters_count: 4, pending_clusters_count: 0 },
      isLoading: false,
    } as ReturnType<typeof useIdentityStats>);
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
});
