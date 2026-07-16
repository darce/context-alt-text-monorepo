import type { SyncHealthResponse } from '../../../api/recognition/types/sync';
import {
  getDashboardSyncHealthSummary,
  resolveEffectiveSyncHealth,
  shouldShowDegradedBanner,
  translateSyncHealthWarning,
} from '../degradedModeBannerLogic';

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

describe('backend_roster_regressed warning (E15-35 Slice 3)', () => {
  const regressionWarning = {
    code: 'backend_roster_regressed',
    message: 'raw server message',
    count: 1,
    threshold: 1,
  };

  it('translates the aggregate warning into the degraded-mode banner copy', () => {
    expect(translateSyncHealthWarning(regressionWarning)).toContain('roster looks rolled back');
    expect(translateSyncHealthWarning(regressionWarning)).toContain('local curation is preserved');
  });

  it('shows the degraded banner while the aggregate warning is open', () => {
    expect(shouldShowDegradedBanner(buildEnvelope({ warnings: [regressionWarning] }))).toBe(true);
    expect(shouldShowDegradedBanner(buildEnvelope())).toBe(false);
  });
});
