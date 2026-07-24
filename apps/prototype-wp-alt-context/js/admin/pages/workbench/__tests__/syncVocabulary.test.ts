import { describe, expect, it } from 'vitest';

import { SYNC_VOCABULARY } from '../syncVocabulary';

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

/** Retired ops dialect must not re-enter the canonical vocabulary module. */
const BANNED_VOCAB_PATTERN = /machine sync|machine state|delta sync|sync backlog/i;

describe('SYNC_VOCABULARY', () => {
  it('contains no banned ops-dialect phrases', () => {
    for (const [key, value] of Object.entries(SYNC_VOCABULARY)) {
      expect(value, `SYNC_VOCABULARY.${key}`).not.toMatch(BANNED_VOCAB_PATTERN);
    }
  });

  it('exposes the slice-2 operator copy and pending-work key names', () => {
    expect(SYNC_VOCABULARY.healthySummary).toBe('Everything is saved and up to date.');
    expect(SYNC_VOCABULARY.staleSummary).toBe('This view may be out of date — sync now to refresh it.');
    expect(SYNC_VOCABULARY.queuedBadge).toBe('Waiting to sync');
    expect(SYNC_VOCABULARY.queuedHeadline).toBe(
      'Your changes are saved here and will sync when the service is available.',
    );
    expect(SYNC_VOCABULARY.queuedSummary).toBe(
      'Your changes are saved here and will sync when the service is available.',
    );
    expect(SYNC_VOCABULARY.offlineHeadline).toBe(
      'Recognition service unreachable — showing your local copy.',
    );
    expect(SYNC_VOCABULARY.resultsErrorHeadline).toBe(
      'Recognition service unreachable — showing your local copy.',
    );
    expect(SYNC_VOCABULARY.pendingWorkSummary).toBe(
      '%1$d waiting, %2$d synced, %3$d failed, %4$d need review',
    );
    expect(SYNC_VOCABULARY.pendingWorkSummaryShort).toBe('%1$d waiting, %2$d failed, %3$d need review');
    expect(SYNC_VOCABULARY).not.toHaveProperty('syncBacklog');
    expect(SYNC_VOCABULARY).not.toHaveProperty('syncBacklogShort');
    expect(SYNC_VOCABULARY).not.toHaveProperty('syncModeDelta');
    expect(SYNC_VOCABULARY).not.toHaveProperty('syncModeFull');
  });
});
