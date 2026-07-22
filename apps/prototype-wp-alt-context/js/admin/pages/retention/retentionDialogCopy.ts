/**
 * UXP-4 — purge-dialog scope option copy (sr-007).
 * Human-facing strings; banned-vocabulary tests assert these stay jargon-free.
 */
import { __ } from '@wordpress/i18n';

export const PURGE_SCOPE_DISPOSED_LABEL = __('Disposed only', 'alt-context');
export const PURGE_SCOPE_DISPOSED_DESCRIPTION = __(
  'Delete rows already marked disposed after acknowledgement.',
  'alt-context',
);

export const PURGE_SCOPE_ALL_LABEL = __('All machine data', 'alt-context');
/** Operator language — no "machine state" / embeddings jargon. */
export const PURGE_SCOPE_ALL_DESCRIPTION = __(
  'Delete everything the recognition service stored for this site — face data, groups, and sync records.',
  'alt-context',
);

export const PURGE_SCOPE_OPTIONS: { value: 'disposed' | 'all'; label: string; description: string }[] = [
  {
    value: 'disposed',
    label: PURGE_SCOPE_DISPOSED_LABEL,
    description: PURGE_SCOPE_DISPOSED_DESCRIPTION,
  },
  {
    value: 'all',
    label: PURGE_SCOPE_ALL_LABEL,
    description: PURGE_SCOPE_ALL_DESCRIPTION,
  },
];
