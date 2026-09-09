import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { GUIDED_COPY, interpolateGuidedCopy } from './copy';
import {
  CASE_STUDY_URL,
  PUBLIC_GUIDE_FALLBACK,
  PUBLIC_GUIDED_COPY,
  RECORDING_URL,
  guidedCopy,
} from './publicGuideCopy';

const here = dirname(fileURLToPath(import.meta.url));
const GENERATED_COPY = resolve(here, 'copy.ts');
const PUBLIC_COPY = resolve(here, 'publicGuideCopy.ts');

const PUBLIC_KEYS = [
  'scope.public',
  'entry.watch',
  'entry.read_case_study',
  'nav.leave',
  'nav.home',
  'nav.case_study',
  'notes.recorded_public',
] as const;

const PUBLIC_SCOPE =
  'Try the review workflow using a recorded example. Your changes affect only the demo copy in this tab.';

describe('public guide copy overlay', () => {
  it('keeps public keys and CASE_STUDY_URL out of the generated catalog file', () => {
    const generated = readFileSync(GENERATED_COPY, 'utf8');
    const overlay = readFileSync(PUBLIC_COPY, 'utf8');

    expect(generated).toMatch(/Generated from/);
    expect(overlay).not.toMatch(/Generated from/);
    expect(generated).not.toContain('CASE_STUDY_URL');
    expect(generated).not.toContain('darce.github.io');

    for (const key of PUBLIC_KEYS) {
      expect(GUIDED_COPY).not.toHaveProperty(key);
      expect(generated).not.toContain(`"${key}"`);
      expect(overlay).toContain(key);
    }
  });

  it('exports the documented case-study URL and public scope copy', () => {
    expect(CASE_STUDY_URL).toBe('https://darce.xyz/projects/altcontext/');
    expect(RECORDING_URL).toBe(`${CASE_STUDY_URL}#recording`);
    expect(RECORDING_URL).not.toBe(CASE_STUDY_URL);
    expect(guidedCopy('scope.public')).toBe(PUBLIC_SCOPE);
    expect(PUBLIC_GUIDED_COPY['entry.watch']).toBe('Watch the recording');
    expect(PUBLIC_GUIDED_COPY['entry.read_case_study']).toBe('Read the case study');
    expect(PUBLIC_GUIDED_COPY['notes.recorded_public']).not.toMatch(/Live generation/);
    expect(guidedCopy('nav.leave')).toBe('Leave the walkthrough');
    expect(PUBLIC_GUIDE_FALLBACK).toMatch(/Reload the page/);
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
