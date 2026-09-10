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
  'entry.title.public': 'Review a recorded alt text example',
  'entry.intro.public':
    'Inspect the festival photo and its page context, choose which saved names to include, then edit, preview, and apply the draft to a demo copy.',
  'scope.public':
    'This is a supplied example roster with recorded drafts. Your choices change only the demo copy in this tab; they do not update WordPress or a server roster.',
  'entry.read_case_study': 'Read the case study',
  'nav.leave': 'Leave the walkthrough',
  'nav.home': 'Home',
  'nav.case_study': 'Case study',
  'roster.explainer.title': 'Supplied example roster',
  'roster.explainer.body':
    'The saved people and reference photos below belong to this example. Compare the available references before deciding which names, if any, belong in the alt text.',
  'roster.explainer.purpose':
    'Your choice is an editorial inclusion decision for this demo. Leaving someone unnamed is valid; it does not change a server roster or verify an identity.',
  'names.scope.public':
    'Choose inclusion or omission for each saved suggestion. The recorded draft loads after both choices are made.',
  'feedback.choices.public': 'Current name choices: {leftName}: {leftChoice}; {rightName}: {rightChoice}.',
  'context.source.summary.public':
    'The AltText.ai comparison captions below were captured in its free web demo on 10 September 2026, with no names or keywords supplied. They are cached comparison text, separate from the recorded AltContext drafts.',
  'context.source.comparison_boundary.public': 'This is one recorded sample, not a benchmark; its wording is unedited.',
  'context.photo.credit_label': 'Photo credit',
  'context.photo.alttextai_title': 'AltText.ai comparison caption',
  'context.photo.altcontext_title': 'AltContext cached descriptions',
  'context.photo.altcontext_no_context': 'Without names',
  'context.photo.altcontext_with_names': 'With names',
  'context.photo.captured': 'Captured {date}.',
  'context.photo.generated': 'Generated {date} by {system}.',
  'context.photo.model': 'Model: {model} ({quantization}).',
  'context.photo.revision': 'Model revision: {revision}.',
  'context.photo.no_caption': 'No AltText.ai comparison caption has been captured for this photo yet.',
  'context.external_link': '{label} (opens in a new window)',
  'names.threshold': 'The displayed recognition threshold is {threshold}.',
  'names.photo.tribeca': 'Tribeca press photo',
  'names.photo.coachella': 'Coachella press photo',
  'names.match': '{image}: {similarity} ({strength}).',
  'names.match.strong': 'strong',
  'names.match.weak': 'weak',
  'names.match.cluster_anchor': 'cluster anchor',
  'names.match.unavailable': 'similarity unavailable',
  'names.crop_alt_image': 'Detected {position} face in {image}',
  'names.match.below_threshold':
    'This match fell below the displayed {threshold} threshold; the production clusterer grouped it anyway.',
  'names.match.weak_icon': 'Weak match warning',
  'draft.origin.public':
    'Recorded Qwen3-VL GPU draft from 9 September 2026, using the supplied page context and your selected names. This is not a new request.',
  'draft.context.public':
    'These recorded samples use the supplied page title and context shown above; editing here changes only this tab.',
  'outcome.scope.public':
    'This result applies only to the demo copy in this tab. It does not update WordPress media, a server roster, or a saved library.',
  'outcome.next_batch.public':
    'A next batch would use another supplied image and page context; this example does not save your choices or roster data.',
  'outcome.kept_body.public':
    'You kept the current alt text, so the demo copy is unchanged. Return to the draft if you want to try another local edit.',
  'notes.recorded_public':
    'Recorded recognition keeps the core walkthrough repeatable so you can review the same example every time.',
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
