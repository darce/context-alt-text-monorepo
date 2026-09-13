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
  'entry.eyebrow.public',
  'entry.start.public',
  'scope.public',
  'step.names.public',
  'step.review.public',
  'guide.current.public',
  'names.scope.public',
  'feedback.choices.public',
  'context.source.summary.public',
  'context.source.comparison_boundary.public',
  'context.source.face_recency.public',
  'comparison.altcontext.public',
  'comparison.alttextai.public',
  'faces.title.public',
  'context.next.public',
  'choices.help.public',
  'draft.origin.public',
  'draft.context.public',
  'draft.field_label.public',
  'draft.current_alt_label.public',
  'draft.apply_scope.public',
  'outcome.scope.public',
  'outcome.next_batch.public',
  'outcome.kept_body.public',
  'outcome.applied_image.public',
  'outcome.undone_image.public',
  'error.empty_draft.public',
  'error.unchanged_draft.public',
  'error.no_recorded_draft.public',
] as const;

const PUBLIC_SCOPE =
  'Recorded example. Changes stay in this tab; WordPress and the server roster are unchanged.';

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
    expect(PUBLIC_GUIDED_COPY['entry.title.public']).toBe("Who's in the photo belongs in the alt text.");
    expect(PUBLIC_GUIDED_COPY['entry.intro.public']).toContain('Compare descriptions of two photos');
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
