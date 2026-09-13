/**
 * Public-guide copy that must survive `scripts/generate_guided_copy.py`.
 * The catalog at docs/assessments/current/demo/altcontext_guided_demo_qm_v1/copy.en.json
 * remains the source of truth for admin guided copy (`copy.ts`).
 */

import { guidedCopy as catalogCopy, interpolateGuidedCopy, type GuidedCopyKey } from './copy';

export const CASE_STUDY_URL = 'https://darce.xyz/projects/altcontext/';

export const PUBLIC_GUIDE_FALLBACK =
  'The walkthrough could not load. Reload the page and try again.';

export const PUBLIC_GUIDE_LOADING = 'Loading the walkthrough.';

export const PUBLIC_GUIDED_COPY = {
  'entry.title.public': "Who's in the photo belongs in the alt text.",
  'entry.intro.public':
    'Compare descriptions of two photos, choose which names to include, then edit and apply each draft.',
  'entry.eyebrow.public': 'Guided prototype',
  'entry.start.public': 'Choose names',
  'scope.public':
    'Recorded example. Changes stay in this tab; WordPress and the server roster are unchanged.',
  'step.names.public': 'Choose names',
  'step.review.public': 'Review and apply',
  'guide.current.public': 'Step {stepNumber} of {stepCount}: {stepTitle}',
  'names.scope.public':
    'Choose inclusion or omission for each saved suggestion. The recorded draft loads after both choices are made.',
  'feedback.choices.public': 'Current name choices: {leftName}: {leftChoice}; {rightName}: {rightChoice}.',
  'context.source.summary.public':
    'Two recorded examples, not a benchmark. AltText.ai was run without names or keywords.',
  'context.source.comparison_boundary.public':
    'These comparisons include both roster names. Your choices affect only the editable drafts.',
  'context.source.face_recency.public':
    'Face matches recorded 10 September 2026; recognition is not running here.',
  'comparison.altcontext.public': 'AltContext — with people roster',
  'comparison.alttextai.public': 'AltText.ai — no names or keywords',
  'faces.title.public': 'Names suggested by AltContext',
  'context.next.public': 'Review drafts',
  'choices.help.public': 'Choose an option for each name to continue. Either name can be left out.',
  'draft.origin.public':
    'Recorded altcontext.com draft from 9 September 2026, using the supplied page context and your selected names. This is not a new request.',
  'draft.context.public':
    'These recorded samples use the supplied page title and context shown above; editing here changes only this tab.',
  'draft.field_label.public': 'Alt text to apply',
  'draft.current_alt_label.public': 'Current alt text',
  'draft.apply_scope.public': 'Applies only to this demo image.',
  'outcome.scope.public':
    'This result applies only to the demo copy in this tab. It does not update WordPress media, a server roster, or a saved library.',
  'outcome.next_batch.public':
    'A next batch would use another supplied image and page context; this example does not save your choices or roster data.',
  'outcome.kept_body.public':
    'You kept the current alt text, so the demo copy is unchanged. Return to the draft if you want to try another local edit.',
  'outcome.applied_image.public': 'Applied to this demo image.',
  'outcome.undone_image.public': 'Previous alt text restored.',
  'error.empty_draft.public': 'Enter alt text before applying.',
  'error.unchanged_draft.public': 'This demo image already uses this text.',
  'error.no_recorded_draft.public': 'No recorded draft is available for these choices.',
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
