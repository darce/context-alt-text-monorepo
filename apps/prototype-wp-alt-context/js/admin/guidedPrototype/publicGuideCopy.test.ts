import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { GUIDED_COPY, interpolateGuidedCopy } from './copy';
import {
  CASE_STUDY_URL,
  PUBLIC_GUIDE_FALLBACK,
  PUBLIC_GUIDE_LOADING,
  PUBLIC_GUIDED_COPY,
  guidedCopy,
} from './publicGuideCopy';

const here = dirname(fileURLToPath(import.meta.url));
const GENERATED_COPY = resolve(here, 'copy.ts');
const PUBLIC_COPY = resolve(here, 'publicGuideCopy.ts');

const PUBLIC_KEYS = [
  'entry.title.public',
  'entry.intro.public',
  'scope.public',
  'names.scope.public',
  'feedback.choices.public',
  'context.source.summary.public',
  'context.source.comparison_boundary.public',
  'draft.origin.public',
  'draft.context.public',
  'outcome.scope.public',
  'outcome.next_batch.public',
  'outcome.kept_body.public',
] as const;

const PUBLIC_SCOPE =
  'This is a supplied example roster with recorded drafts. Your choices change only the demo copy in this tab; they do not update WordPress or a server roster.';

describe('public guide copy overlay', () => {
  it('keeps public keys and CASE_STUDY_URL out of the generated catalog file', () => {
    const generated = readFileSync(GENERATED_COPY, 'utf8');
    const overlay = readFileSync(PUBLIC_COPY, 'utf8');

    expect(generated).toMatch(/Generated from/);
    expect(overlay).not.toMatch(/Generated from/);
    expect(generated).not.toContain('CASE_STUDY_URL');
    expect(generated).not.toContain('darce.github.io');
    expect(Object.keys(PUBLIC_GUIDED_COPY).sort()).toEqual([...PUBLIC_KEYS].sort());
    expect(Object.keys(PUBLIC_GUIDED_COPY).every((key) => key.endsWith('.public'))).toBe(true);

    for (const key of PUBLIC_KEYS) {
      expect(GUIDED_COPY).not.toHaveProperty(key);
      expect(generated).not.toContain(`"${key}"`);
      expect(overlay).toContain(key);
    }
  });

  it('exports the documented case-study URL and public scope copy', () => {
    expect(CASE_STUDY_URL).toBe('https://darce.xyz/projects/altcontext/');
    expect(PUBLIC_GUIDED_COPY['entry.title.public']).toBe('Review a recorded alt text example');
    expect(PUBLIC_GUIDED_COPY['entry.intro.public']).toContain('Inspect the festival photo');
    expect(guidedCopy('scope.public')).toBe(PUBLIC_SCOPE);
    expect(guidedCopy('entry.read_case_study')).toBe('Read the case study');
    expect(guidedCopy('notes.recorded_public')).not.toMatch(/Live generation/);
    expect(guidedCopy('nav.leave')).toBe('Leave the walkthrough');
    expect(PUBLIC_GUIDE_FALLBACK).toMatch(/Reload the page/);
    expect(PUBLIC_GUIDE_FALLBACK).toBe('The walkthrough could not load. Reload the page and try again.');
    expect(PUBLIC_GUIDE_LOADING).toBe('Loading the walkthrough.');
    expect(guidedCopy('page.start')).toBe('Start the walkthrough');
  });

  it('uses the catalog interpolator and a single overlay copy helper', () => {
    const overlay = readFileSync(PUBLIC_COPY, 'utf8');
    const notes = readFileSync(resolve(here, '../pages/guided/GuidedDesignNotes.tsx'), 'utf8');

    expect(overlay).not.toMatch(/const PLACEHOLDER/);
    expect(overlay).toMatch(/interpolateGuidedCopy/);
    expect(notes).not.toMatch(/guidedPrototype\/copy['"]/);
    expect(notes).toMatch(/guidedPrototype\/publicGuideCopy['"]/);
    expect(interpolateGuidedCopy('demo.key', 'Hello {name}', { name: 'Ada' })).toBe('Hello Ada');
    expect(guidedCopy('names.include', { name: 'Ada' })).toBe('Use Ada');
  });
});
