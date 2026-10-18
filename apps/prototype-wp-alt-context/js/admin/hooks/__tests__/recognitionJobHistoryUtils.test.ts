import { describe, expect, it, vi } from 'vitest';

import { fetchScanStatus } from '../../api/recognition';
import { HTTPError } from '../../utils/http';
import { fetchRecognitionStatusEntries } from '../recognitionJobHistoryUtils';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

vi.mock('../../api/recognition', () => ({
  fetchRecentBatchRuns: vi.fn(),
  fetchScanStatus: vi.fn(),
}));

const fetchScanStatusMock = vi.mocked(fetchScanStatus);

const notFoundHttpError = (jobId: string): HTTPError =>
  new HTTPError({
    status: 404,
    retryAfterSeconds: undefined,
    endpoint: `/recognition/jobs/${jobId}`,
    bodyPreview: 'not-found-body',
    message: 'Not found',
  });

describe('fetchRecognitionStatusEntries', () => {
  it('marks HTTP 404 as notFound via isHttpStatus, not a message sniff', async () => {
    fetchScanStatusMock.mockRejectedValueOnce(notFoundHttpError('job-404'));
    fetchScanStatusMock.mockRejectedValueOnce(new Error('Request failed (404): Not found'));

    const entries = await fetchRecognitionStatusEntries(['job-404', 'job-sniff']);

    expect(entries).toEqual([
      { id: 'job-404', status: 'Unknown', detail: null, notFound: true },
      { id: 'job-sniff', status: 'Unknown', detail: null, notFound: false },
    ]);
  });

  it('marks a pre-classified AppError 404 as notFound (E-02)', async () => {
    fetchScanStatusMock.mockRejectedValueOnce({
      _tag: 'http',
      status: 404,
      endpoint: '/recognition/jobs/job-app',
      message: 'Not found',
      cause: null,
    });

    const entries = await fetchRecognitionStatusEntries(['job-app']);

    expect(entries).toEqual([{ id: 'job-app', status: 'Unknown', detail: null, notFound: true }]);
  });
});
