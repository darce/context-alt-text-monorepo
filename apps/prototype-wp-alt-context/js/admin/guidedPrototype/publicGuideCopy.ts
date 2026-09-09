/**
 * Public-guide copy that must survive `scripts/generate_guided_copy.py`.
 * The catalog at docs/assessments/current/demo/altcontext_guided_demo_qm_v1/copy.en.json
 * remains the source of truth for admin guided copy (`copy.ts`).
 */

import { guidedCopy as catalogCopy, type GuidedCopyKey } from './copy';

export const CASE_STUDY_URL = 'https://darce.xyz/projects/altcontext/';

export const PUBLIC_GUIDE_FALLBACK =
  'The walkthrough could not load. Reload the page, or watch the recorded video on the case study page.';

export const PUBLIC_GUIDED_COPY = {
  'scope.public':
    'Try the review workflow using a recorded example. Your changes affect only the demo copy in this tab.',
  'entry.watch': 'Watch the recording',
  'entry.read_case_study': 'Read the case study',
  'nav.leave': 'Leave the walkthrough',
  'nav.home': 'Home',
  'nav.case_study': 'Case study',
} as const;

export type PublicGuidedCopyKey = keyof typeof PUBLIC_GUIDED_COPY;
export type GuideCopyKey = GuidedCopyKey | PublicGuidedCopyKey;

const PLACEHOLDER = /\{(\w+)\}/g;

const interpolate = (key: string, template: string, values: Record<string, string | number>): string =>
  template.replace(PLACEHOLDER, (_match, name: string) => {
    const value = values[name];
    if (value === undefined) {
      throw new Error(`Unresolved guided copy placeholder {${name}} in ${key}`);
    }
    return String(value);
  });

const isPublicGuidedCopyKey = (key: GuideCopyKey): key is PublicGuidedCopyKey =>
  Object.prototype.hasOwnProperty.call(PUBLIC_GUIDED_COPY, key);

export const guidedCopy = (key: GuideCopyKey, values: Record<string, string | number> = {}): string => {
  if (isPublicGuidedCopyKey(key)) {
    return interpolate(key, PUBLIC_GUIDED_COPY[key], values);
  }
  return catalogCopy(key, values);
};
