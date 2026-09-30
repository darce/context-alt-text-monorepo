/**
 * Public-guide copy that must survive `scripts/generate_guided_copy.py`.
 * The catalog at docs/assessments/current/demo/altcontext_guided_demo_qm_v1/copy.en.json
 * remains the source of truth for admin guided copy (`copy.ts`).
 */

import { guidedCopy as catalogCopy, interpolateGuidedCopy, type GuidedCopyKey } from './copy';

export const CASE_STUDY_URL = 'https://darce.xyz/projects/altcontext/';

export const PUBLIC_GUIDE_FALLBACK = 'The walkthrough could not load. Reload the page and try again.';

export const PUBLIC_GUIDE_LOADING = 'Loading the walkthrough.';

export const PUBLIC_GUIDED_COPY = {
  'entry.title.public': "Names change a photo's meaning",
  'entry.intro.public':
    'See how AltContext suggests image descriptions (alt text) and possible names, ' +
    'and how you decide which names to use.',
  'entry.eyebrow.public': 'DEMO',
  'entry.start.public': 'Start the demo',
  'nav.leave.public': 'Page links',
  'scope.public':
    'The names and descriptions were suggested by AI in advance. ' +
    'Your changes stay on this page and clear when you reload.',
  'step.names.public': 'Check the suggested names',
  'step.review.public': 'Check and use the suggested description',
  'guide.current.public': 'Step {stepNumber} of {stepCount}: {stepTitle}',
  'names.scope.public': 'Use a name only if you agree. Not sure? Leave the person unnamed.',
  'feedback.choices.public': 'Name choices: {leftName}: {leftChoice}; {rightName}: {rightChoice}.',
  'context.source.summary.public':
    'AltText.ai was given no names or keywords. This comparison is for reference only, ' +
    'not a test of which tool is better.',
  'context.source.comparison_boundary.public': 'For comparison only. This is not a benchmark.',
  'context.source.face_recency.public':
    'Names were suggested on 10 September 2026. Face matching is not running on this page.',
  'comparison.altcontext.public': 'AltContext, using the people list',
  'comparison.alttextai.public': 'AltText.ai, no names or keywords',
  'faces.title.public': 'Suggested names',
  'context.next.public': 'Check the suggested names',
  'choices.help.public': 'Choose an option for both people above to see the suggested description.',
  'draft.origin.public': 'Written by AI in advance from the photo, the page it appears on, and the names you chose.',
  'draft.context.public':
    'This description was written by AI in advance from the photo, its page, and the names you chose.',
  'draft.field_label.public': 'Suggested description',
  'draft.current_alt_label.public': 'Current description',
  'draft.apply_scope.public': 'Only the demo image on this page changes.',
  'outcome.scope.public': 'Nothing was saved or published. Your changes clear when you reload.',
  'outcome.next_batch.public': 'In real use, you would review each new photo the same way.',
  'outcome.kept_body.public': 'You kept the current description.',
  'outcome.applied_image.public': 'The demo image now uses this description.',
  'outcome.undone_image.public': 'The previous description is back.',
  'error.empty_draft.public': 'Enter a description before you use it.',
  'error.unchanged_draft.public': 'The current and suggested descriptions are the same.',
  'error.no_recorded_draft.public': 'No suggested description is ready for these names. Try again.',
  'steps.title.public': "What you'll do",
  'steps.names.public': '1. Check the names suggested for each photo.',
  'steps.description.public': '2. Read and edit the suggested description.',
  'steps.use.public': '3. Use it on the demo image, or keep the current one.',
  'photos.title.public': 'Two photos to check',
  'photo.count.public': 'Photo {photoNumber} of 2',
  'names.heading.public': '1. Check the suggested names',
  'names.guidance.public':
    'Naming people helps readers when you are sure who they are. ' +
    'Leaving someone unnamed is always a valid choice.',
  'names.compare.public': 'Compare photos',
  'names.use.public': 'Use {name}',
  'names.omit.public': 'Leave unnamed',
  'names.strong.public': '{similarity} match',
  'names.weak.public': '{similarity} match. Weak match',
  'description.heading.public': '2. Check the suggested description',
  'description.written.public':
    'Written by AI in advance from the photo, the page it appears on, ' + 'and the names you chose.',
  'description.current.public': 'Current description',
  'description.suggested.public': 'Suggested description',
  'description.edit_help.public': 'Edit anything that is wrong or that you would not publish.',
  'description.help.public': 'Choose an option for both people above to see the suggested description.',
  'description.scope.public': 'Only the demo image on this page changes.',
  'description.use.public': 'Use this description',
  'description.keep.public': 'Keep the current description',
  'description.undo.public': 'Undo this change',
  'description.applied.public': 'The demo image now uses this description.',
  'description.kept.public': 'You kept the current description.',
  'reset.title.public': 'Start over?',
  'reset.body.public': 'This clears your name choices and edits, and puts back the original descriptions.',
  'reset.keep.public': 'Keep my work',
  'reset.confirm.public': 'Start over',
  'reset.success.public': 'Started over. The original descriptions are back.',
  'name_change.title.public': 'Replace your edits?',
  'name_change.body.public':
    'Changing a name loads a new suggested description for this photo. ' + 'Your edits to it will be replaced.',
  'name_change.keep.public': 'Keep my edits',
  'name_change.confirm.public': 'Change the name',
  'outcome.title.public': 'You checked both photos',
  'outcome.applied.public': '{photoName}: uses the new description.',
  'outcome.kept.public': '{photoName}: kept the current description.',
  'outcome.provenance.public':
    'AltContext suggested these names and descriptions on 9–10 September 2026. ' +
    'Nothing on this page compares faces.',
  'comparison.title.public': 'Compare how two tools describe this photo',
  'comparison.note.public': 'For comparison only, not a benchmark. AltText.ai was given no names or keywords.',
  'lightbox.title.public': 'Compare with photos of {name}',
  'lightbox.close.public': 'Close',
  'lightbox.current.public': 'In this photo',
  'lightbox.references.public': 'Reference photos of {name}',
} as const;

export type PublicGuidedCopyKey = keyof typeof PUBLIC_GUIDED_COPY;
export type GuideCopyKey = GuidedCopyKey | PublicGuidedCopyKey;

const isPublicGuidedCopyKey = (key: GuideCopyKey): key is PublicGuidedCopyKey =>
  Object.prototype.hasOwnProperty.call(PUBLIC_GUIDED_COPY, key);

export const guidedCopy = (key: GuideCopyKey, values: Record<string, string | number> = {}): string => {
  if (isPublicGuidedCopyKey(key)) {
    return interpolateGuidedCopy(key, PUBLIC_GUIDED_COPY[key], values);
  }
  return catalogCopy(key, values);
};
