/**
 * GPFACE-1-V-03: the guided credit strings in state.ts and the CREDITS.md ledger are one
 * contract. state.test.ts only inspects the strings, so the file-page links, licence
 * attribution and modification notes could rot without a failing test.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { createGuidedScenario } from './state';

const CREDITS_PATH = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../assets/guided/CREDITS.md');

interface CreditRow {
  file: string;
  subject: string;
  source: string;
  author: string;
  licence: string;
  changes: string;
}

const loadCreditRows = (): CreditRow[] =>
  readFileSync(CREDITS_PATH, 'utf8')
    .split('\n')
    .filter((line) => line.trim().startsWith('| `'))
    .map((line) => {
      const [file, subject, source, author, licence, changes] = line
        .split('|')
        .slice(1, 7)
        .map((cell) => cell.trim());
      return { file: file.replaceAll('`', ''), subject, source, author, licence, changes };
    });

const bundledPhotos = () => {
  const scenario = createGuidedScenario();
  return [
    { src: scenario.pressPhoto.src, credit: scenario.pressPhoto.credit },
    ...scenario.people.flatMap((person) =>
      person.galleryPhotos.map((photo) => ({ src: photo.src, credit: photo.credit })),
    ),
  ];
};

describe('guided demo CREDITS.md contract', () => {
  it('lists exactly the bundled photos, one row each', () => {
    const rows = loadCreditRows();
    const photos = bundledPhotos();

    expect(rows).toHaveLength(photos.length);
    for (const row of rows) {
      expect(photos.filter((photo) => photo.src.includes(row.file))).toHaveLength(1);
    }
  });

  it('gives every row a Commons file-page link, an author and a modification note', () => {
    for (const row of loadCreditRows()) {
      expect(row.subject.trim()).not.toBe('');
      expect(row.source).toMatch(/https:\/\/commons\.wikimedia\.org\/wiki\/File:/);
      expect(row.author.trim()).not.toBe('');
      expect(row.changes).toMatch(/resized/i);
    }
  });

  it('keeps each state.ts credit consistent with its CREDITS.md row', () => {
    const rows = loadCreditRows();

    for (const photo of bundledPhotos()) {
      const row = rows.find((candidate) => photo.src.includes(candidate.file));
      expect(row, `no CREDITS.md row for ${photo.src}`).toBeDefined();

      const licence = row!.licence;
      if (licence.startsWith('EU reuse licence')) {
        // The Commons author is the European Commission; the reuse notice the plugin renders
        // credits the European Union as rights holder, per Commission Decision 2011/833/EU.
        expect(photo.credit).toContain('European Union');
        expect(photo.credit).toContain('EU reuse licence');
      } else {
        expect(photo.credit.startsWith(row!.author)).toBe(true);
        expect(photo.credit).toContain(licence);
      }

      // Attribution licences must carry the modification note; public domain does not.
      expect(/, resized$/.test(photo.credit)).toBe(licence !== 'public domain');
    }
  });
});
