/**
 * UXP-4 Slice 4 — advanced-drawer confirm tab copy (sr-007).
 * Human-facing strings; banned-vocabulary tests assert these stay jargon-free.
 * __() at declaration sites so gettext extraction can see literals.
 */
import { __ } from '@wordpress/i18n';

/** Closed-by-default disclosure summary for the clustering explainer. */
export const CLUSTERING_DISCLOSURE_SUMMARY = __('What does clustering do?', 'alt-context');

/**
 * Disclosure body — operator language, no "embeddings" / tutorial jargon.
 * Renders only when the disclosure is open.
 */
export const CLUSTERING_DISCLOSURE_BODY = __(
  'Clustering groups similar faces found during a scan so you can name a whole group at once instead of labeling every photo.',
  'alt-context',
);

/**
 * ConfirmPanel intro — operator language, no "embeddings".
 */
export const CONFIRM_PANEL_INTRO = __(
  'Review the most recent recognition job and group similar faces found during the scan.',
  'alt-context',
);

/**
 * ConfirmPanel zero state when no recognition job has been selected/run.
 * Replaces the fabricated "Status — Pending" pair.
 */
export const CONFIRM_NO_JOB_ZERO_STATE = __(
  'No scan has run yet — run a scan from the Media step first.',
  'alt-context',
);
