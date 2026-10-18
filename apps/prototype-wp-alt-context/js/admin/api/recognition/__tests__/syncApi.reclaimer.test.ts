import { beforeEach, describe, expect, it, vi } from 'vitest';

import { fetchSyncStatus } from '../syncApi';
import { UnknownBoundaryError, type HTTPOptions } from '../../../utils/http';

const fetchRequiredApiMock = vi.fn();

vi.mock('../../../utils/http', async (importOriginal) => ({
  ...await importOriginal<typeof import('../../../utils/http')>(),
  fetchRequiredApi: (endpoint: string, options?: HTTPOptions) => fetchRequiredApiMock(endpoint, options),
}));

vi.mock('../../config', () => ({
  getEndpoint: () => 'https://example.test/sync-status',
  getConfig: () => ({ nonce: 'nonce-123' }),
}));

const validReclaimer = {
  state: 'healthy',
  scheduler_mode: 'action_scheduler',
  effective_period_seconds: 3600,
  last_attempt_at: '2026-09-22T12:00:00Z',
  last_success_at: '2026-09-22T11:59:00Z',
  last_outcome: 'success',
  last_purged_count: 4,
  backlog_remaining: 2,
  backlog_oldest_age_seconds: 30,
  batch_cap_reached: true,
};

const validStatus = {
  last_snapshot_version: 3,
  last_synced_at: '2026-09-22T12:00:00Z',
  is_stale: false,
  sync_health: 'healthy',
  last_sync_result: 'ok',
  reclaimer: validReclaimer,
};

describe('fetchSyncStatus reclaimer boundary normalization', () => {
  beforeEach(() => {
    fetchRequiredApiMock.mockReset();
    fetchRequiredApiMock.mockResolvedValue(validStatus);
  });

  it('preserves an exact valid reclaimer contract object', async () => {
    const result = await fetchSyncStatus();

    expect(result.reclaimer).toEqual(validReclaimer);
  });

  it('rejects a literal null envelope with UnknownBoundaryError', async () => {
    fetchRequiredApiMock.mockResolvedValue(null);

    await expect(fetchSyncStatus()).rejects.toBeInstanceOf(UnknownBoundaryError);
  });

  it.each([
    ['absent', () => {
      const { reclaimer: _reclaimer, ...status } = validStatus;
      return status;
    }],
    ['null', () => ({ ...validStatus, reclaimer: null })],
    ['malformed', () => ({ ...validStatus, reclaimer: { state: 'healthy' } })],
    ['unknown state', () => ({ ...validStatus, reclaimer: { ...validReclaimer, state: 'retired' } })],
    ['unknown scheduler mode', () => ({ ...validStatus, reclaimer: { ...validReclaimer, scheduler_mode: 'wp_queue' } })],
    ['unknown last outcome', () => ({ ...validStatus, reclaimer: { ...validReclaimer, last_outcome: 'timed_out' } })],
  ])('normalizes %s reclaimer data to an explicit unknown value', async (_name, payload) => {
    fetchRequiredApiMock.mockResolvedValue(payload());

    const result = await fetchSyncStatus();

    expect(result.reclaimer).toBeNull();
  });
});
