import { describe, expect, it, vi } from 'vitest';

import type { ReclaimerStatus } from '../../../api/recognition/types/sync';
import { RECLAIMER_VOCABULARY } from '../../../api/recognition/types/sync';
import {
  buildSyncPresentation,
  SYNC_PRESENTATION_STATUS,
  SYNC_VOCABULARY,
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

const breachReclaimer: ReclaimerStatus = {
  state: RECLAIMER_VOCABULARY.state.BREACH,
  scheduler_mode: RECLAIMER_VOCABULARY.scheduler_mode.ACTION_SCHEDULER,
  effective_period_seconds: 3600,
  last_attempt_at: '2026-09-22T12:00:00Z',
  last_success_at: '2026-09-22T11:59:00Z',
  last_outcome: RECLAIMER_VOCABULARY.last_outcome.SUCCESS,
  last_purged_count: 4,
  backlog_remaining: 2,
  backlog_oldest_age_seconds: 7200,
  batch_cap_reached: true,
};

describe('DEFWAVE-2 idle reclaimer overlays', () => {
  it.each([
    { health: 'stale' as const, action: 'sync_now', label: SYNC_VOCABULARY.syncNow },
    { health: 'offline' as const, action: 'retry', label: SYNC_VOCABULARY.retry },
    { health: 'failures' as const, action: 'open_failures', label: SYNC_VOCABULARY.failuresBadge },
    { health: 'conflicts' as const, action: 'open_conflicts', label: SYNC_VOCABULARY.conflictsBadge },
  ])('keeps the $health base control when a breach takes the headline', ({ health, action, label }) => {
    const p = buildSyncPresentation({
      legacySyncHealth: health,
      lastSyncedAt: '2026-09-22T12:00:00Z',
      reclaimer: breachReclaimer,
    });

    expect(p.status).toBe(SYNC_PRESENTATION_STATUS.RECLAIMER_BREACH);
    expect(p.action).toMatchObject({ kind: action, label });
    if (health === 'failures' || health === 'conflicts') {
      expect(p.badgeHref).toBeTruthy();
      expect(p.action?.href).toBe(p.badgeHref);
    }
  });
});
