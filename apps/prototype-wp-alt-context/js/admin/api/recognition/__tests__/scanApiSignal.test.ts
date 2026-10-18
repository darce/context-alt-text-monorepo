import { beforeEach, describe, expect, it, vi } from 'vitest';

import { fetchScanStatus } from '../scanApi';
import type { HTTPOptions } from '../../../utils/http';

const fetchRequiredApiMock = vi.fn();

vi.mock('../../../utils/http', () => ({
  fetchRequiredApi: (endpoint: string, options?: HTTPOptions) => fetchRequiredApiMock(endpoint, options),
}));

vi.mock('../../config', () => ({
  getEndpoint: () => 'https://example.test/jobs',
  getConfig: () => ({ nonce: 'nonce-123' }),
}));

describe('fetchScanStatus cancellation', () => {
  beforeEach(() => {
    fetchRequiredApiMock.mockReset();
    fetchRequiredApiMock.mockResolvedValue({ status: 'running' });
  });

  it('threads the caller signal into the timed HTTP boundary', async () => {
    const controller = new AbortController();

    await fetchScanStatus('split-job-1', controller.signal);

    expect(fetchRequiredApiMock).toHaveBeenCalledWith(
      'https://example.test/jobs/split-job-1',
      expect.objectContaining({
        signal: controller.signal,
        timeoutMs: 15_000,
      }),
    );
  });
});
