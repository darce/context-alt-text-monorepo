import { act, renderHook, waitFor } from '@testing-library/react';

import { fetchScanStatus } from '../../api/recognitionApi';
import { useRecognitionJobHistory } from '../useRecognitionJobHistory';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

vi.mock('../../api/recognitionApi', () => ({
  fetchScanStatus: vi.fn(),
}));

describe('useRecognitionJobHistory', () => {
  const mockedFetchScanStatus = fetchScanStatus as vi.MockedFunction<typeof fetchScanStatus>;

  beforeEach(() => {
    window.localStorage.clear();
    mockedFetchScanStatus.mockReset();
  });

  it('records jobs and fetches their statuses', async () => {
    mockedFetchScanStatus.mockResolvedValue({ status: 'completed' } as { status: string });
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
