import { act, renderHook, waitFor } from '@testing-library/react';

import { fetchScanStatus } from '../../api/recognition';
import { useRecognitionJobHistory } from '../useRecognitionJobHistory';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

vi.mock('../../api/recognition', () => ({
  fetchScanStatus: vi.fn(),
}));

describe('useRecognitionJobHistory', () => {
  const fetchScanStatusMock = vi.mocked(fetchScanStatus);

  beforeEach(() => {
    window.localStorage.clear();
    fetchScanStatusMock.mockReset();
  });

  it('records jobs and fetches their statuses', async () => {
    fetchScanStatusMock.mockResolvedValue({
      id: 'job-1',
      type: 'analyze',
      status: 'completed',
      progress: { completed: 1, total: 1 },
      started_at: '2025-01-01T00:00:00Z',
      finished_at: '2025-01-01T00:00:01Z',
    });
    const { result } = renderHook(() => useRecognitionJobHistory());

    act(() => {
      result.current.rememberJob('job-1');
    });

    expect(result.current.jobId).toBe('job-1');
    expect(result.current.jobHistory).toEqual(['job-1']);

    await waitFor(() => {
      expect(result.current.jobStatuses['job-1']).toBe('completed');
    });
  });

  it('hydrates from stored history and supports job selection', async () => {
    window.localStorage.setItem('acx-recognition-jobs', JSON.stringify(['stored-job']));
    const { result } = renderHook(() => useRecognitionJobHistory());

    await waitFor(() => {
      expect(result.current.jobHistory).toEqual(['stored-job']);
      expect(result.current.jobId).toBe('stored-job');
    });

    act(() => {
      result.current.selectJob('another-job');
    });

    expect(result.current.jobId).toBe('another-job');
  });
});
