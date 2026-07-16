import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import * as recognitionApi from '../../api/recognition';
import {
  _resetForTests,
  gateRefetchInterval,
  noteRateLimited,
} from '../../utils/rateLimitCooldown';
import { useSyncHealth } from '../useSyncHealth';

vi.mock('../../api/recognition', async () => {
  const actual = await vi.importActual<typeof recognitionApi>('../../api/recognition');
  return {
    ...actual,
    fetchSyncHealth: vi.fn(),
  };
});

const wrapper = ({ children }: { children: React.ReactNode }) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
};

/** Matches SYNC_HEALTH_REFETCH_MS in useSyncHealth (representative poller). */
const SYNC_HEALTH_REFETCH_MS = 15_000;

describe('useSyncHealth', () => {
  it('polls sync health with at least 15s stale time', async () => {
    const fetchSyncHealthMock = vi.mocked(recognitionApi.fetchSyncHealth);
    fetchSyncHealthMock.mockResolvedValue({
      breaker: { state: 'closed', base_url: 'http://localhost:8000', opened_at: null },
      outbox: { pending: 0, failed: 0 },
      conflicts: { open: 0 },
      replays: { failed: null, source: 'unavailable_local' },
      last_pull: { at: null, ok: true },
      warnings: [],
    });

    const { result } = renderHook(() => useSyncHealth(), { wrapper });

    await waitFor(() => expect(fetchSyncHealthMock).toHaveBeenCalled());
    expect(result.current.data?.breaker.state).toBe('closed');
  });

  describe('429 cooldown gate (representative poller)', () => {
    beforeEach(() => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date('2026-07-15T12:00:00.000Z'));
      _resetForTests();
    });

    afterEach(() => {
      _resetForTests();
      vi.useRealTimers();
    });

    it('composed refetchInterval yields false during cooldown then resumes base interval', () => {
      // Same composition as useSyncHealth: gateRefetchInterval(SYNC_HEALTH_REFETCH_MS)
      const refetchInterval = gateRefetchInterval(SYNC_HEALTH_REFETCH_MS);

      expect(refetchInterval()).toBe(SYNC_HEALTH_REFETCH_MS);

      noteRateLimited(10);
      expect(refetchInterval()).toBe(false);

      vi.advanceTimersByTime(10_000);
      expect(refetchInterval()).toBe(SYNC_HEALTH_REFETCH_MS);
    });
  });
});
