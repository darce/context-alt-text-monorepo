/**
 * E21-5 Slice 3 — person-commit card chrome copy (sr-007 + HAI-05).
 * Human-facing strings; banned-vocabulary tests assert these stay jargon-free.
 *
 * UXW2-3: naming a face always creates/binds a roster person, so the copy says
 * "Save name" — the roster is a consequence, not a decision. The misleading
 * "Just label — don't add to roster" tertiary path is retired (INT-06).
 */

import { __ } from '@wordpress/i18n';

import { toRoster, toRosterPerson } from '../../../navigation/appLinks';

/** HAI-05 model-output disclosure — plain copy, never dresses a guess as fact. */
export const MODEL_OUTPUT_DISCLOSURE =
  __('Suggested by face matching based on similarity — confirm before treating it as fact.', 'alt-context');

/** Success confirm affordance — person deep-link when a uuid is known. */
export const VIEW_IN_ROSTER_COPY = 'View in roster →';

export const viewInRosterHref = (personUuid?: string | null): string =>
  personUuid ? toRosterPerson(personUuid) : toRoster();

export const PERSON_COMMIT_CONFIRM_COPY = 'Save name';

export const PERSON_COMMIT_COMMITTING_COPY = 'Saving name…';

export const PERSON_COMMIT_FAILURE_COPY =
  'Could not save the name. Retry to try again.';

export const PERSON_COMMIT_SUCCESS_COPY = 'Name saved.';

export const PERSON_COMMIT_COMBOBOX_ARIA = 'Name this person';

export const PERSON_COMMIT_PLACEHOLDER = 'Type a name…';
