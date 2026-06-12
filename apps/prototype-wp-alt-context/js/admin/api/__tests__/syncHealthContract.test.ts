import { describe, expect, expectTypeOf, it } from 'vitest';

import type { SyncHealthResponse } from '../recognition/types/sync';
import syncHealthFixture from '../../../../tests/fixtures/sync-health/debt-and-breaker-envelope.json';

const SYNC_HEALTH_KEYS = ['breaker', 'outbox', 'conflicts', 'replays', 'last_pull', 'warnings'] as const;

describe('sync health response contract', () => {
  const fixture = syncHealthFixture as SyncHealthResponse;

  it('matches GET /acx/v1/recognition/sync/health envelope', () => {
    expectTypeOf(fixture).toMatchTypeOf<SyncHealthResponse>();
    expect(Object.keys(fixture).sort()).toEqual([...SYNC_HEALTH_KEYS].sort());
    expect(fixture.replays.source).toBe('unavailable_local');
    expect(fixture.breaker.state).toBe('closed');
    expect(fixture.outbox).toEqual({ pending: 5, failed: 2 });
    expect(fixture.conflicts).toEqual({ open: 3 });
    expect(fixture.last_pull).toEqual({ at: '2026-06-11 12:00:00', ok: true });
    expect(fixture.warnings).toEqual([]);
  });
});
