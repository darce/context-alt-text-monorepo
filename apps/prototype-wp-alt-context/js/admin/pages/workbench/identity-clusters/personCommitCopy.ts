/**
 * E21-5 Slice 3 — person-commit card chrome copy (sr-007 + HAI-05).
 * Human-facing strings; banned-vocabulary tests assert these stay jargon-free.
 */

/** HAI-05 model-output disclosure — plain copy, never dresses a guess as fact. */
export const MODEL_OUTPUT_DISCLOSURE =
  'Suggested by face matching based on similarity — confirm before treating it as fact.';

/** Tertiary label-only path (routes open_label → ClusterLabelingPanel). */
export const JUST_LABEL_COPY = "Just label — don't add to roster";

/** Success confirm affordance — generic #/roster (no ?person= deep-link; E21-10 owns that). */
export const VIEW_IN_ROSTER_COPY = 'View in roster →';

export const VIEW_IN_ROSTER_HREF = '#/roster';

export const PERSON_COMMIT_CONFIRM_COPY = 'Add to roster';

export const PERSON_COMMIT_COMMITTING_COPY = 'Adding to roster…';

export const PERSON_COMMIT_FAILURE_COPY =
  'Could not add to roster. Retry to try again.';

export const PERSON_COMMIT_COMBOBOX_ARIA = 'Commit to roster entry';

export const PERSON_COMMIT_PLACEHOLDER = 'Choose or create a person…';
