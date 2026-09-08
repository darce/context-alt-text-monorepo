/**
 * UXP-4 Slice 3 — dashboard retention card copy (sr-007).
 * Human-facing strings; banned-vocabulary tests assert these stay jargon-free.
 * __() at declaration sites so gettext extraction can see literals.
 */
import { __ } from '@wordpress/i18n';

import { toRetention } from '../../navigation/appLinks';

/** Card heading — replaces jargon "Retention posture"; names the destination page (glossary rule 2). */
export const RETENTION_CARD_HEADING = __('Data Retention', 'alt-context');

/**
 * Endpoint configured but fetch failed (`useRetentionStatus().isError`).
 * Points operator to Settings; retention route link is retained at the call site.
 */
export const RETENTION_CARD_ERROR_BODY = __(
  'Retention status could not load. Check the connection on the Settings page.',
  'alt-context',
);

/** Designed action for the error state — existing retention route. */
export const RETENTION_CARD_LINK_HREF = toRetention();

/** Action-card heading shared by retention error and success panels — names the destination as the sidebar names it (glossary rule 2). */
export const RETENTION_CARD_ACTION_HEADING = __('Open Data Retention', 'alt-context');

/** Action-card body shared by retention error and success panels. */
export const RETENTION_CARD_ACTION_BODY = __(
  'Review policy, run exports, and inspect recent audit events.',
  'alt-context',
);
