import type { SyncHealthResponse } from '../../../api/recognition/types/sync';
import { getDashboardSyncHealthSummary, resolveEffectiveSyncHealth } from '../degradedModeBannerLogic';

const buildEnvelope = (overrides: Partial<SyncHealthResponse> = {}): SyncHealthResponse => ({
  breaker: { state: 'closed', base_url: 'http://localhost:8000', opened_at: null },
  outbox: { pending: 0, failed: 0 },
  conflicts: { open: 0 },
  replays: { failed: null, source: 'unavailable_local' },
  last_pull: { at: '2026-06-11T12:00:00Z', ok: true },
  warnings: [],
  ...overrides,
});

describe('resolveEffectiveSyncHealth', () => {
  it('overrides healthy legacy sync-status when the envelope reports offline', () => {
    const envelope = buildEnvelope({
      breaker: { state: 'open', base_url: 'http://localhost:8000', opened_at: null },
    });

    expect(resolveEffectiveSyncHealth('healthy', envelope)).toBe('offline');
  });

  it('keeps legacy sync-status when the envelope is online', () => {
    expect(resolveEffectiveSyncHealth('conflicts', buildEnvelope())).toBe('conflicts');
  });
});

describe('getDashboardSyncHealthSummary', () => {
  it('shows offline copy when effective health is offline', () => {
    expect(getDashboardSyncHealthSummary('offline', buildEnvelope())).toContain('unreachable');
  });

  it('shows warning copy instead of healthy when the envelope has warnings', () => {
    const envelope = buildEnvelope({
      warnings: [
        {
          code: 'open_conflicts_high',
          message: 'Too many conflicts',
          count: 9,
          threshold: 5,
        },
      ],
    });

    expect(getDashboardSyncHealthSummary('healthy', envelope)).toContain('warning threshold');
  });
});
