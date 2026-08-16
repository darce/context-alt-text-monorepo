import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import type { SyncHealthResponse } from '../../../api/recognition/types/sync';
import { LAST_SYNC_RESULT } from '../../../api/recognition/types/sync';
import {
  SYNC_PRESENTATION_STATUS,
  SYNC_VOCABULARY,
  buildSyncPresentation,
  formatSyncJobPhase,
  getSyncPresentationSummary,
  syncPresentationInputFromStatus,
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

  /**
   * HARM-BR-04: RESYNC_REQUIRED escalation is driven solely by last_sync_result.
   * The phantom top-level failed: string[] field is not a producer contract and
   * must not be an alternate escalation arm.
   */
  it('escalates to resync_required solely from last_sync_result even when health is healthy', () => {
    const p = buildSyncPresentation({
      legacySyncHealth: 'healthy',
      lastSyncedAt: '2026-02-14T12:00:00Z',
      lastSyncResult: LAST_SYNC_RESULT.RESYNC_REQUIRED,
      syncHealthEnvelope: onlineEnvelope(),
    });
    expect(p.status).toBe(SYNC_PRESENTATION_STATUS.RESYNC_REQUIRED);
    expect(p.headline).toBe(SYNC_VOCABULARY.resyncRequiredHeadline);
    expect(p.detail).toBe(SYNC_VOCABULARY.resyncRequiredSummary);
    expect(p.badge).toBe(SYNC_VOCABULARY.resyncRequiredBadge);
    expect(p.tone).toBe('warning');
    expect(p.action).toEqual({ label: SYNC_VOCABULARY.syncNow, kind: 'sync_now' });
    assertPlainLanguage(p.headline);
    assertPlainLanguage(p.detail);
    assertPlainLanguage(p.badge);
  });

  it('does not escalate to resync_required when last_sync_result is ok', () => {
    const p = buildSyncPresentation({
      legacySyncHealth: 'healthy',
      lastSyncedAt: '2026-02-14T12:00:00Z',
      lastSyncResult: LAST_SYNC_RESULT.OK,
      syncHealthEnvelope: onlineEnvelope(),
    });
    expect(p.status).toBe(SYNC_PRESENTATION_STATUS.HEALTHY);
    expect(p.status).not.toBe(SYNC_PRESENTATION_STATUS.RESYNC_REQUIRED);
  });

  it('outranks pipeline activity when last_sync_result is resync_required', () => {
    const p = buildSyncPresentation({
      legacySyncHealth: 'healthy',
      lastSyncResult: LAST_SYNC_RESULT.RESYNC_REQUIRED,
      jobActivity: 'scan',
      pipelinePhase: 'scanning',
      syncHealthEnvelope: onlineEnvelope(),
    });
    expect(p.status).toBe(SYNC_PRESENTATION_STATUS.RESYNC_REQUIRED);
    expect(p.action?.kind).toBe('sync_now');
  });
});

describe('HARM-BR-04 phantom failed field deleted from sync contract', () => {
  const workbenchDir = path.dirname(fileURLToPath(import.meta.url));
  const syncTypesSource = readFileSync(
    path.resolve(workbenchDir, '../../../api/recognition/types/sync.ts'),
    'utf8',
  );
  const presentationSource = readFileSync(path.resolve(workbenchDir, '../syncPresentation.ts'), 'utf8');
  const indicatorSource = readFileSync(
    path.resolve(workbenchDir, '../SyncStatusIndicator.tsx'),
    'utf8',
  );

  /**
   * Static pin: SyncStatusResponse must not re-declare the deleted settings-graft
   * `failed` string-array field under any common TypeScript spelling
   * (optional / readonly / Array<> / union-with-undefined). TopologyCommandStatus.failed
   * (number) and LAST_SYNC_RESULT.FAILED remain valid outside this interface body.
   */
  it('SyncStatusResponse does not declare a top-level failed string[] (settings graft)', () => {
    const bodyMatch = /export interface SyncStatusResponse \{([\s\S]*?)\n\}/.exec(
      syncTypesSource,
    );
    expect(bodyMatch).not.toBeNull();
    const body = bodyMatch?.[1] ?? '';
    // Property name is exactly `failed` (not failed_curation_* / last_curation_failed_at).
    // Optional `readonly` prefix must be in scope so `readonly failed?: string[]`
    // cannot re-enter under the pin [TEST-17].
    const failedProp = /(?:^|\n)\s*(?:readonly\s+)?failed\s*\??\s*:/g;
    const hits: string[] = [];
    let m: RegExpExecArray | null;
    while ((m = failedProp.exec(body)) !== null) {
      hits.push(m[0].trim());
    }
    // No property named `failed` may exist on SyncStatusResponse at all.
    expect(hits, 'SyncStatusResponse must not declare a top-level failed field').toEqual([]);
    expect(syncTypesSource).not.toMatch(
      /Names the fields whose writes did not land/,
    );

    // Scratch-string proof: the pin matches the readonly spelling the old
    // regex missed (do not mutate sync.ts to exercise this).
    const readonlyScratch = '\n  readonly failed?: string[];';
    expect(
      /(?:^|\n)\s*(?:readonly\s+)?failed\s*\??\s*:/g.test(readonlyScratch),
      'source pin must match readonly failed?: string[] under the claimed spellings',
    ).toBe(true);
  });

  /**
   * Behavioural: a wire payload carrying a phantom `failed: string[]` must not
   * surface through the status→presentation mapper. Assert the mapper output
   * directly — comparing buildSyncPresentation results is self-fulfilling
   * because the mapper already strips unknown keys [TEST-06].
   *
   * Mutation that turns this red: adding `failedFields: data?.failed` (or any
   * graft of the phantom array) to syncPresentationInputFromStatus.
   */
  it('ignores a phantom failed string[] on the status payload when building presentation', () => {
    const baseStatus = {
      last_snapshot_version: 1,
      last_synced_at: '2026-02-14T12:00:00Z',
      is_stale: false,
      sync_health: 'healthy' as const,
      last_sync_result: LAST_SYNC_RESULT.OK,
    };
    const withPhantomFailed = {
      ...baseStatus,
      failed: ['title', 'slug'],
    };
    expect(
      syncPresentationInputFromStatus(
        withPhantomFailed as Parameters<typeof syncPresentationInputFromStatus>[0],
      ),
      'mapper must not surface a phantom wire failed[] as any presentation input field',
    ).toEqual(syncPresentationInputFromStatus(baseStatus));
    expect(
      buildSyncPresentation({
        ...syncPresentationInputFromStatus(
          withPhantomFailed as Parameters<typeof syncPresentationInputFromStatus>[0],
        ),
        syncHealthEnvelope: onlineEnvelope(),
      }).status,
      'phantom failed[] must leave presentation status healthy',
    ).toBe(SYNC_PRESENTATION_STATUS.HEALTHY);
  });

  it('buildSyncPresentation has no failedFields input or escalation arm', () => {
    // Historical defect escalated via `failedFields` on the presentation input —
    // never via data?.failed (that lived only on the indicator/mapper seam).
    expect(presentationSource).not.toMatch(/\bfailedFields\b/);
    expect(presentationSource).not.toMatch(
      /Array\.isArray\(\s*failedFields\s*\)\s*&&\s*failedFields\.length\s*>\s*0/,
    );
    // Sole remaining escalation trigger must be last_sync_result === resync_required.
    expect(presentationSource).toMatch(
      /lastSyncResult\s*===\s*LAST_SYNC_RESULT\.RESYNC_REQUIRED/,
    );
  });

  /**
   * Behavioural replacement for the dead data?.failed source pin: reintroducing
   * failedFields escalation on the presentation input must change status. Today
   * a grafted failedFields array is ignored.
   */
  it('does not escalate to resync_required from failedFields on the presentation input', () => {
    const base = {
      legacySyncHealth: 'healthy' as const,
      lastSyncedAt: '2026-02-14T12:00:00Z',
      lastSyncResult: LAST_SYNC_RESULT.OK,
      syncHealthEnvelope: onlineEnvelope(),
    };
    const without = buildSyncPresentation(base);
    const withFailedFields = buildSyncPresentation({
      ...base,
      ...{ failedFields: ['title', 'slug'] },
    });
    expect(withFailedFields).toEqual(without);
    expect(withFailedFields.status).toBe(SYNC_PRESENTATION_STATUS.HEALTHY);
  });

  it('SyncStatusIndicator does not pass data?.failed into presentation', () => {
    expect(indicatorSource).not.toMatch(/\bfailedFields\b/);
    expect(indicatorSource).not.toMatch(/data\?\.failed\b/);
  });

  it('syncPresentationInputFromStatus does not surface a failedFields key', () => {
    const input = syncPresentationInputFromStatus({
      last_snapshot_version: 1,
      last_synced_at: '2026-02-14T12:00:00Z',
      is_stale: false,
      sync_health: 'healthy',
      last_sync_result: LAST_SYNC_RESULT.OK,
    });
    expect(input).not.toHaveProperty('failedFields');
    expect(Object.keys(input)).not.toContain('failedFields');

    // Grafted wire `failed` array must not surface as failedFields either.
    const grafted = syncPresentationInputFromStatus({
      last_snapshot_version: 1,
      last_synced_at: '2026-02-14T12:00:00Z',
      is_stale: false,
      sync_health: 'healthy',
      last_sync_result: LAST_SYNC_RESULT.OK,
      failed: ['title', 'slug'],
    } as Parameters<typeof syncPresentationInputFromStatus>[0]);
    expect(grafted).not.toHaveProperty('failedFields');
    expect(grafted).not.toHaveProperty('failed');
    expect(Object.keys(grafted)).not.toContain('failedFields');
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
