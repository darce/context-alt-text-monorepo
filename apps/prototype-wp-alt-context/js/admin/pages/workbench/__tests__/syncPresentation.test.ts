import { describe, expect, it } from 'vitest';

import type { SyncHealthResponse } from '../../../api/recognition/types/sync';
import {
  SYNC_PRESENTATION_STATUS,
  SYNC_VOCABULARY,
  buildSyncPresentation,
  formatSyncJobPhase,
  getSyncPresentationSummary,
} from '../syncPresentation';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (format: string, ...args: (string | number)[]) => {
    let sequentialIndex = 0;
    return format.replace(/%((\d+)\$)?[sd]/g, (_match, _positional, explicitIndex) => {
      if (explicitIndex) {
        return String(args[Number(explicitIndex) - 1] ?? '');
      }
      return String(args[sequentialIndex++] ?? '');
    });
  },
}));

const onlineEnvelope = (overrides: Partial<SyncHealthResponse> = {}): SyncHealthResponse => ({
  breaker: { state: 'closed', base_url: 'http://localhost:8000', opened_at: null },
  outbox: { pending: 0, failed: 0 },
  conflicts: { open: 0 },
  replays: { failed: null, source: 'unavailable_local' },
  last_pull: { at: '2026-06-11T12:00:00Z', ok: true },
  warnings: [],
  ...overrides,
});

const offlineEnvelope = (): SyncHealthResponse =>
  onlineEnvelope({
    breaker: { state: 'open', base_url: 'http://localhost:8000', opened_at: null },
  });

/** Banned jargon must never appear in any presentation headline/detail/badge. */
const BANNED = [
  /topology/i,
  /replay/i,
  /projection/i,
  /dead-letter/i,
  /curation acknowledgement/i,
  /Source version/i,
  /projected instances/i,
  /Curriculum/i,
];

const assertPlainLanguage = (text: string | null | undefined): void => {
  if (!text) {
    return;
  }
  for (const pattern of BANNED) {
    expect(text).not.toMatch(pattern);
  }
};

describe('buildSyncPresentation state matrix', () => {
  const healthStates = ['healthy', 'queued', 'stale', 'conflicts', 'failures', 'offline'] as const;
  const uiStates = ['loading', 'empty', 'error', 'offline'] as const;
  const activities = ['idle', 'scan', 'cluster', 'describe'] as const;

  it.each(uiStates)('maps ui state %s with plain language', (ui) => {
    if (ui === 'loading') {
      const p = buildSyncPresentation({ isLoading: true });
      expect(p.status).toBe(SYNC_PRESENTATION_STATUS.LOADING);
      assertPlainLanguage(p.headline);
      return;
    }
    if (ui === 'error') {
      const p = buildSyncPresentation({ isError: true, legacySyncHealth: 'healthy' });
      expect(p.status).toBe(SYNC_PRESENTATION_STATUS.ERROR);
      assertPlainLanguage(p.headline);
      return;
    }
    if (ui === 'empty') {
      const p = buildSyncPresentation({
        legacySyncHealth: 'healthy',
        lastSyncedAt: null,
        syncHealthEnvelope: onlineEnvelope(),
      });
      expect(p.headline).toBe(SYNC_VOCABULARY.empty);
      assertPlainLanguage(p.headline);
      return;
    }
    const p = buildSyncPresentation({
      legacySyncHealth: 'healthy',
      syncHealthEnvelope: offlineEnvelope(),
    });
    expect(p.status).toBe(SYNC_PRESENTATION_STATUS.OFFLINE);
    assertPlainLanguage(p.headline);
    assertPlainLanguage(p.detail);
  });

  it.each(healthStates)('maps idle health %s without banned jargon', (health) => {
    const p = buildSyncPresentation({
      legacySyncHealth: health,
      lastSyncedAt: '2026-02-14T12:00:00Z',
      syncHealthEnvelope: onlineEnvelope(),
    });
    assertPlainLanguage(p.headline);
    assertPlainLanguage(p.detail);
    assertPlainLanguage(p.badge);
    expect(p.icon).toBeTruthy();
    expect(p.tone).toBeTruthy();
  });

  it.each(activities)('maps job activity %s with plain language', (activity) => {
    const p = buildSyncPresentation({
      legacySyncHealth: 'healthy',
      lastSyncedAt: '2026-02-14T12:00:00Z',
      jobActivity: activity,
      pipelinePhase: activity === 'scan' ? 'scanning' : activity === 'cluster' ? 'clustering' : 'idle',
      syncHealthEnvelope: onlineEnvelope(),
    });
    assertPlainLanguage(p.headline);
    if (activity === 'scan') {
      expect(p.status).toBe(SYNC_PRESENTATION_STATUS.SCANNING);
    } else if (activity === 'cluster') {
      expect(p.status).toBe(SYNC_PRESENTATION_STATUS.CLUSTERING);
    } else if (activity === 'describe') {
      expect(p.status).toBe(SYNC_PRESENTATION_STATUS.DESCRIBING);
    }
  });

  it('prioritizes results-ready over stale idle health', () => {
    const p = buildSyncPresentation({
      legacySyncHealth: 'stale',
      isStale: true,
      pipelinePhase: 'projecting',
      resultsSyncState: 'ready',
      lastSyncedAt: '2026-02-14T12:00:00Z',
    });
    expect(p.status).toBe(SYNC_PRESENTATION_STATUS.RESULTS_READY);
    expect(p.headline).toBe(SYNC_VOCABULARY.resultsReadyHeadline);
    assertPlainLanguage(p.headline);
  });

  it('overrides healthy legacy health when envelope is offline', () => {
    const p = buildSyncPresentation({
      legacySyncHealth: 'healthy',
      lastSyncedAt: '2026-02-14T12:00:00Z',
      syncHealthEnvelope: offlineEnvelope(),
    });
    expect(p.status).toBe(SYNC_PRESENTATION_STATUS.OFFLINE);
    expect(p.badge).toBe(SYNC_VOCABULARY.offlineBadge);
  });

  it('exposes retry action on results sync error', () => {
    const p = buildSyncPresentation({
      legacySyncHealth: 'stale',
      resultsSyncState: 'error',
      resultsError: SYNC_VOCABULARY.resultsErrorHeadline,
    });
    expect(p.action?.kind).toBe('retry_results');
    expect(p.headline).toBe(SYNC_VOCABULARY.resultsErrorHeadline);
    expect(p.headline).not.toBe('Waiting for service…');
  });

  it('shows connected-empty when trigger returns no_remote_data', () => {
    const p = buildSyncPresentation({
      legacySyncHealth: 'stale',
      isStale: true,
      triggerSuccess: true,
      triggerSynced: true,
      triggerReason: 'no_remote_data',
    });
    expect(p.status).toBe(SYNC_PRESENTATION_STATUS.CONNECTED_EMPTY);
    assertPlainLanguage(p.headline);
  });
});

describe('getSyncPresentationSummary', () => {
  it('uses plain language for every health code', () => {
    for (const health of ['healthy', 'queued', 'stale', 'conflicts', 'failures', 'offline'] as const) {
      const summary = getSyncPresentationSummary(health, onlineEnvelope());
      assertPlainLanguage(summary);
    }
  });

  it('prefers warning copy over healthy when envelope has warnings', () => {
    const summary = getSyncPresentationSummary(
      'healthy',
      onlineEnvelope({
        warnings: [
          {
            code: 'open_conflicts_high',
            message: 'Too many conflicts',
            count: 9,
            threshold: 5,
          },
        ],
      }),
    );
    expect(summary).toMatch(/warning threshold/i);
    assertPlainLanguage(summary);
  });
});

describe('formatSyncJobPhase', () => {
  it('maps awaiting_projection without banned jargon', () => {
    expect(formatSyncJobPhase('awaiting_projection')).toBe(SYNC_VOCABULARY.phaseSyncingResults);
    assertPlainLanguage(formatSyncJobPhase('awaiting_projection'));
  });
});

describe('vocabulary completeness', () => {
  it('exports only plain-language user-facing strings', () => {
    for (const value of Object.values(SYNC_VOCABULARY)) {
      assertPlainLanguage(value);
    }
  });
});
