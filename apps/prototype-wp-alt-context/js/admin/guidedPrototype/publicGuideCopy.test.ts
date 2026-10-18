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
  'nav.leave.public',
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
  'steps.title.public',
  'steps.names.public',
  'steps.description.public',
  'steps.use.public',
  'photos.title.public',
  'photo.count.public',
  'names.heading.public',
  'names.guidance.public',
  'names.compare.public',
  'names.use.public',
  'names.omit.public',
  'names.strong.public',
  'names.weak.public',
  'description.heading.public',
  'description.written.public',
  'description.current.public',
  'description.suggested.public',
  'description.edit_help.public',
  'description.help.public',
  'description.scope.public',
  'description.use.public',
  'description.keep.public',
  'description.undo.public',
  'description.applied.public',
  'description.kept.public',
  'reset.title.public',
  'reset.body.public',
  'reset.keep.public',
  'reset.confirm.public',
  'reset.success.public',
  'name_change.title.public',
  'name_change.body.public',
  'name_change.keep.public',
  'name_change.confirm.public',
  'outcome.title.public',
  'outcome.applied.public',
  'outcome.kept.public',
  'outcome.provenance.public',
  'comparison.title.public',
  'comparison.note.public',
  'lightbox.title.public',
  'lightbox.close.public',
  'lightbox.current.public',
  'lightbox.references.public',
] as const;

const PUBLIC_SCOPE =
  'The names and descriptions were suggested by AI in advance. ' +
  'Your changes stay on this page and clear when you reload.';

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
    expect(PUBLIC_GUIDED_COPY['entry.title.public']).toBe("Names change a photo's meaning");
    expect(PUBLIC_GUIDED_COPY['entry.intro.public']).toBe(
      'See how AltContext suggests image descriptions (alt text) and possible names, ' +
        'and how you decide which names to use.',
    );
    expect(PUBLIC_GUIDED_COPY['entry.eyebrow.public']).toBe('DEMO');
    expect(guidedCopy('entry.start.public')).toBe('Start the demo');
    expect(guidedCopy('nav.leave.public')).toBe('Page links');
    expect(guidedCopy('scope.public')).toBe(PUBLIC_SCOPE);
    expect(guidedCopy('steps.title.public')).toBe("What you'll do");
    expect(guidedCopy('photo.count.public', { photoNumber: 1 })).toBe('Photo 1 of 2');
    expect(guidedCopy('names.strong.public', { similarity: '89.4%' })).toBe('89.4% match');
    expect(guidedCopy('names.weak.public', { similarity: '56.7%' })).toBe('56.7% match. Weak match');
    expect(guidedCopy('description.use.public')).toBe('Use this description');
    expect(guidedCopy('description.keep.public')).toBe('Keep the current description');
    expect(guidedCopy('description.undo.public')).toBe('Undo this change');
    expect(guidedCopy('reset.keep.public')).toBe('Keep my work');
    expect(guidedCopy('reset.confirm.public')).toBe('Start over');
    expect(guidedCopy('name_change.keep.public')).toBe('Keep my edits');
    expect(guidedCopy('name_change.confirm.public')).toBe('Change the name');
    expect(guidedCopy('lightbox.title.public', { name: 'Ada' })).toBe('Compare with photos of Ada');
    expect(guidedCopy('lightbox.close.public')).toBe('Close');
    expect(guidedCopy('entry.read_case_study')).toBe('Read the case study');
    expect(guidedCopy('notes.recorded_public')).not.toMatch(/Live generation/);
    expect(guidedCopy('nav.leave')).toBe('Leave the walkthrough');
    expect(PUBLIC_GUIDE_FALLBACK).toMatch(/Reload the page/);
    expect(PUBLIC_GUIDE_FALLBACK).toBe('The walkthrough could not load. Reload the page and try again.');
    expect(PUBLIC_GUIDE_LOADING).toBe('Loading the walkthrough.');
    expect(guidedCopy('page.start')).toBe('Start the walkthrough');
  });

  it('uses image description throughout and reserves alt text for the hero explanation', () => {
    const publicStrings = Object.values(PUBLIC_GUIDED_COPY);
    const altTextStrings = publicStrings.filter((value) => /\balt text\b/i.test(value));

    expect(altTextStrings).toEqual([PUBLIC_GUIDED_COPY['entry.intro.public']]);
    for (const value of publicStrings) {
      expect(value).not.toMatch(/\b(?:draft|roster|prototype)\b/i);
      expect(value).not.toMatch(/\b\d+(?:\.\d+)?\s?%/);
    }
    expect(guidedCopy('comparison.altcontext.public')).toBe('AltContext, using the people list');
    expect(guidedCopy('comparison.alttextai.public')).toBe('AltText.ai, no names or keywords');
    expect(guidedCopy('comparison.title.public')).toBe('Compare how two tools describe this photo');
    expect(guidedCopy('comparison.note.public')).toContain('For comparison only');
    expect(guidedCopy('outcome.provenance.public')).toContain('Nothing on this page compares faces.');
    expect(guidedCopy('error.unchanged_draft.public')).toBe('The current and suggested descriptions are the same.');
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
