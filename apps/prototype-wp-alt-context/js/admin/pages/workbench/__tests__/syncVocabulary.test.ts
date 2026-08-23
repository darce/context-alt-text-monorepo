import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

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

interface GlossaryRow {
  say: string;
  dontSay: string[];
}

/**
 * Parses `docs/ux/glossary.md`'s Say/Don't-say table at test time (BR-34) so
 * this test has one source of truth for banned terms instead of a hand-typed
 * second copy that can drift from the glossary.
 */
const parseGlossaryRows = (markdown: string): GlossaryRow[] => {
  const rows: GlossaryRow[] = [];
  for (const line of markdown.split('\n')) {
    if (!line.trim().startsWith('|')) {
      continue;
    }
    const cells = line
      .split('|')
      .slice(1, -1)
      .map((cell) => cell.trim());
    if (cells.length < 3 || cells[0] === 'Concept' || /^-+$/.test(cells[1])) {
      continue;
    }
    const say = cells[1].replace(/\*\*/g, '').trim();
    const dontSay = cells[2]
      .split(',')
      .map((term) => term.trim())
      .filter(Boolean);
    if (say && dontSay.length > 0) {
      rows.push({ say, dontSay });
    }
  }
  return rows;
};

const glossaryPath = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../../../../../docs/ux/glossary.md',
);
const allGlossaryRows = parseGlossaryRows(readFileSync(glossaryPath, 'utf8'));

/**
 * Wave 2 renamed exactly these five admin-menu destinations (pinned in
 * MenuTest.php). Scoped to this set — not the full glossary table — because
 * rows 6-9 (face group/cluster, Scan/Confirm/Review) are process-vocabulary
 * for a separate, later wave (glossary Rule 3/4) and their bare "cluster"
 * term legitimately appears in this file's phase/status prose (e.g.
 * `phaseClustering`, `clusteringHeadline`). Extending this set is a BR-34-style
 * decision, not a mechanical add — do it deliberately.
 */
const WAVE_2_DESTINATION_NAMES = new Set([
  'Overview',
  'Review Queue',
  'People',
  'Description Runs',
  'Data Retention',
]);
const destinationRows = allGlossaryRows.filter((row) => WAVE_2_DESTINATION_NAMES.has(row.say));

/**
 * Keys deliberately left unfixed by this task, exempted by name (not by
 * loosening the pattern) so the exemption is visible and reviewable:
 * - backendRegressionWarning: BR-36, deferred. Roster-conflict recovery copy
 *   is Rule-4-exempt status/error prose (non-navigational), not a
 *   cross-reference, so Rule 2 doesn't reach it. Revisit when BR-36 lands.
 */
const WAVE_2_EXEMPT_KEYS = new Set<keyof typeof SYNC_VOCABULARY>(['backendRegressionWarning']);

/**
 * True if `text` contains one of `row.dontSay`'s bare terms. If a Don't-say
 * term is itself a substring of the Say phrase (e.g. "Retention" inside "Data
 * Retention"), legitimate Say-phrase occurrences are masked out first so a
 * correct destination name is never a false positive (BR-33/BR-34 masking).
 */
const findDontSayHit = (text: string, row: GlossaryRow): string | undefined => {
  const lowerText = text.toLowerCase();
  const lowerSay = row.say.toLowerCase();
  for (const term of row.dontSay) {
    const lowerTerm = term.toLowerCase();
    const haystack = lowerSay.includes(lowerTerm)
      ? lowerText.split(lowerSay).join(' '.repeat(lowerSay.length))
      : lowerText;
    if (haystack.includes(lowerTerm)) {
      return term;
    }
  }
  return undefined;
};

describe('SYNC_VOCABULARY', () => {
  it('contains no banned ops-dialect phrases', () => {
    for (const [key, value] of Object.entries(SYNC_VOCABULARY)) {
      expect(value, `SYNC_VOCABULARY.${key}`).not.toMatch(BANNED_VOCAB_PATTERN);
    }
  });

  it('contains no wave-2 destination Don’t-say terms outside the BR-36 exemption (BR-34)', () => {
    for (const [key, value] of Object.entries(SYNC_VOCABULARY)) {
      if (WAVE_2_EXEMPT_KEYS.has(key as keyof typeof SYNC_VOCABULARY)) {
        continue;
      }
      for (const row of destinationRows) {
        const hit = findDontSayHit(value, row);
        expect(hit, `SYNC_VOCABULARY.${key} = ${JSON.stringify(value)} contains Don't-say term "${hit}"`).toBeUndefined();
      }
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
