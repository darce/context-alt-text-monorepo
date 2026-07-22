/**
 * UXP-4 Slice 3 — dashboard retention card copy (sr-007).
 * Human-facing strings; banned-vocabulary tests assert these stay jargon-free.
 * __() at declaration sites so gettext extraction can see literals.
 */
import { __ } from '@wordpress/i18n';

/** Card heading — replaces jargon "Retention posture". */
export const RETENTION_CARD_HEADING = __('Your data & retention', 'alt-context');

/**
 * Endpoint configured but fetch failed (`useRetentionStatus().isError`).
 * Points operator to Settings; `#/retention` link is retained at the call site.
 */
export const RETENTION_CARD_ERROR_BODY = __(
  'Retention status could not load. Check the connection on the Settings page.',
  'alt-context',
);

/** Designed action for the error state — existing retention route. */
export const RETENTION_CARD_LINK_HREF = '#/retention';
