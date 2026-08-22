import type { UseQueryResult } from '@tanstack/react-query';
import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { SyncHealthResponse } from '../../api/recognition';
import { createMockQuery } from '../../test-utils/mockHooks';
import { useSyncOffline } from '../useSyncOffline';

const useSyncHealthMock = vi.fn(
  (): UseQueryResult<SyncHealthResponse, Error> => createMockQuery<SyncHealthResponse>({}),
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

  it.each([
    ['online', createMockQuery<SyncHealthResponse>({ data: baseHealth('closed') }), false],
    ['offline', createMockQuery<SyncHealthResponse>({ data: baseHealth('open') }), true],
    ['unknown', createMockQuery<SyncHealthResponse>({}), true],
    ['unavailable', createMockQuery<SyncHealthResponse>({ isError: true, error: new Error('unavailable') }), true],
  ] as const)('maps %s health to the expected remote-compute gate', (_status, query, expected) => {
    useSyncHealthMock.mockReturnValue(query);

    const { result } = renderHook(() => useSyncOffline());

    expect(result.current).toBe(expected);
  });
});
