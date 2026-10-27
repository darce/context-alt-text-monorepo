import { describe, expect, it, vi } from 'vitest';
import { fetchRequiredApi } from '../../../utils/http';
import { fetchRetentionStatus } from '../retentionApi';

vi.mock('../../../utils/http', () => ({ fetchRequiredApi: vi.fn() }));
vi.mock('../../config', () => ({ getConfig: () => ({
  endpoints: { retentionStatus: '/retention/status' }, nonce: 'nonce',
}) }));

describe('retention status contract', () => {
  it('preserves the live unavailable envelope without normalization', async () => {
    const payload = { available: false, policy: null, recent_audit_events: [],
      unavailable: { service: 'recognition', reason: 'upstream_5xx', http_status: 500,
        retry_after_seconds: null, checked_at: '2026-10-27T02:58:00Z' } };
    vi.mocked(fetchRequiredApi).mockResolvedValue(payload);
    expect(await fetchRetentionStatus()).toEqual(payload);
  });
});
