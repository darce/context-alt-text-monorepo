import type { UseQueryResult } from '@tanstack/react-query';
import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { SyncHealthResponse } from '../../api/recognition';
import { createMockQuery } from '../../test-utils/mockHooks';
import {
  getSyncHealthAvailability,
  SYNC_HEALTH_AVAILABILITY,
  useSyncOffline,
} from '../useSyncOffline';

const useSyncHealthMock = vi.fn((): UseQueryResult<SyncHealthResponse, Error> =>
  createMockQuery<SyncHealthResponse>({}),
);

vi.mock('../useSyncHealth', () => ({
  useSyncHealth: () => useSyncHealthMock(),
}));

const baseHealth = (breakerState: 'open' | 'closed'): SyncHealthResponse => ({
  breaker: { state: breakerState, base_url: 'http://localhost:8000', opened_at: null },
  outbox: { pending: 0, failed: 0 },
  conflicts: { open: 0 },
  replays: { failed: null, source: 'unavailable_local' },
  last_pull: { at: '2026-06-11T12:00:00Z', ok: true },
  warnings: [],
});

describe('useSyncOffline', () => {
  beforeEach(() => {
    useSyncHealthMock.mockReset();
  });

  it('gates controls until the initial health request proves online', () => {
    useSyncHealthMock.mockReturnValue(
      createMockQuery<SyncHealthResponse>({ isLoading: true }),
    );

    const { result, rerender } = renderHook(() => useSyncOffline());

    expect(result.current).toBe(true);
    useSyncHealthMock.mockReturnValue(
      createMockQuery<SyncHealthResponse>({ data: baseHealth('closed'), isLoading: false }),
    );
    rerender();
    expect(result.current).toBe(false);
  });

  it('gates controls when health settles as unknown (data undefined)', () => {
    useSyncHealthMock.mockReturnValue(
      createMockQuery<SyncHealthResponse>({ status: 'error', isLoading: false }),
    );

    const { result } = renderHook(() => useSyncOffline());

    expect(result.current).toBe(true);
    expect(getSyncHealthAvailability(undefined)).toBe(SYNC_HEALTH_AVAILABILITY.UNKNOWN);
  });

  it('returns true when breaker state is open', () => {
    useSyncHealthMock.mockReturnValue(
      createMockQuery<SyncHealthResponse>({ data: baseHealth('open') }),
    );

    const { result } = renderHook(() => useSyncOffline());

    expect(result.current).toBe(true);
  });

  it('returns false when breaker state is closed', () => {
    useSyncHealthMock.mockReturnValue(
      createMockQuery<SyncHealthResponse>({ data: baseHealth('closed') }),
    );

    const { result } = renderHook(() => useSyncOffline());

    expect(result.current).toBe(false);
  });
});
