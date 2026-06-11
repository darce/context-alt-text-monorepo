import { describe, expect, expectTypeOf, it } from 'vitest';

import type { SyncHealthResponse } from '../recognition/types/sync';

const SYNC_HEALTH_KEYS = ['breaker', 'outbox', 'conflicts', 'replays', 'last_pull', 'warnings'] as const;

describe('sync health response contract', () => {
  const fixture: SyncHealthResponse = {
    breaker: {
      state: 'closed',
      base_url: 'http://localhost:8000',
      opened_at: null,
    },
    outbox: { pending: 0, failed: 0 },
    conflicts: { open: 0 },
    replays: { failed: null, source: 'unavailable_local' },
    last_pull: { at: null, ok: true },
    warnings: [],
  };

  it('matches GET /acx/v1/recognition/sync/health envelope', () => {
    expectTypeOf(fixture).toMatchTypeOf<SyncHealthResponse>();
    expect(Object.keys(fixture).sort()).toEqual([...SYNC_HEALTH_KEYS].sort());
    expect(fixture.replays.source).toBe('unavailable_local');
  });
});