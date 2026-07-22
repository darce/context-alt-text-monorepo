import { describe, expect, it, vi } from 'vitest';

import type { SyncHealthResponse, SyncHealthWarning } from '../../../api/recognition/types/sync';

/**
 * UXP-4 Slice 1 primary proof ([TEST-15]): module-mock sentinel discrimination.
 * Red against pre-slice inline literals (they ignore the module); green only when
 * consumers actually read SYNC_VOCABULARY. Do not use === against real export
 * values — that is vacuous when literals are already byte-duplicates.
 */
const SENTINELS = {
  offlineBannerTitle: 'SENTINEL_OFFLINE_TITLE',
  attentionBannerTitle: 'SENTINEL_ATTENTION_TITLE',
  offlineDetail: 'SENTINEL_OFFLINE_DETAIL',
  healthySummary: 'SENTINEL_HEALTHY_SUMMARY',
  queuedSummary: 'SENTINEL_QUEUED_SUMMARY',
  conflictsSummary: 'SENTINEL_CONFLICTS_SUMMARY',
  failuresSummary: 'SENTINEL_FAILURES_SUMMARY',
  offlineSummary: 'SENTINEL_OFFLINE_SUMMARY',
  staleSummary: 'SENTINEL_STALE_SUMMARY',
  attentionSummary: 'SENTINEL_ATTENTION_SUMMARY',
} as const;

vi.mock('../syncVocabulary', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../syncVocabulary')>();
  return {
    SYNC_VOCABULARY: {
      ...actual.SYNC_VOCABULARY,
      ...SENTINELS,
    },
  };
});

const {
  getDashboardSyncHealthSummary,
  getDegradedBannerMessage,
  getDegradedBannerTitle,
} = await import('../degradedModeBannerLogic');

const buildEnvelope = (overrides: Partial<SyncHealthResponse> = {}): SyncHealthResponse => ({
  breaker: { state: 'closed', base_url: 'http://localhost:8000', opened_at: null },
  outbox: { pending: 0, failed: 0 },
  conflicts: { open: 0 },
  replays: { failed: null, source: 'unavailable_local' },
  last_pull: { at: '2026-06-11T12:00:00Z', ok: true },
  warnings: [],
  ...overrides,
});

describe('degradedModeBannerLogic vocabulary single-source (UXP-4 S1)', () => {
  it('getDegradedBannerTitle reads offlineBannerTitle from SYNC_VOCABULARY', () => {
    const offline = buildEnvelope({
      breaker: { state: 'open', base_url: 'http://localhost:8000', opened_at: null },
    });
    expect(getDegradedBannerTitle(offline)).toBe(SENTINELS.offlineBannerTitle);
  });

  it('getDegradedBannerTitle reads attentionBannerTitle from SYNC_VOCABULARY', () => {
    expect(getDegradedBannerTitle(buildEnvelope())).toBe(SENTINELS.attentionBannerTitle);
  });

  it('getDegradedBannerMessage reads offlineDetail from SYNC_VOCABULARY', () => {
    expect(getDegradedBannerMessage()).toBe(SENTINELS.offlineDetail);
  });

  it.each([
    ['healthy', SENTINELS.healthySummary],
    ['queued', SENTINELS.queuedSummary],
    ['conflicts', SENTINELS.conflictsSummary],
    ['failures', SENTINELS.failuresSummary],
    ['offline', SENTINELS.offlineSummary],
    ['stale', SENTINELS.staleSummary],
  ] as const)(
    'getDashboardSyncHealthSummary(%s) reads the matching SYNC_VOCABULARY key',
    (health, sentinel) => {
      expect(getDashboardSyncHealthSummary(health, buildEnvelope())).toBe(sentinel);
    },
  );

  it('getDashboardSyncHealthSummary falls back to attentionSummary from SYNC_VOCABULARY', () => {
    // hasSyncHealthWarnings is true (length > 0) but warnings[0] is missing so
    // getDegradedWarningMessage returns null and the ?? fallback must fire.
    const envelope = buildEnvelope({
      warnings: [undefined as unknown as SyncHealthWarning],
    });
    expect(getDashboardSyncHealthSummary('healthy', envelope)).toBe(SENTINELS.attentionSummary);
  });
});
