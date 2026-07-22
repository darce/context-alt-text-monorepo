/**
 * UXP-4 Slice 4 — advanced-drawer confirm tab copy (sr-007).
 * Human-facing strings; banned-vocabulary tests assert these stay jargon-free.
 */

/** Closed-by-default disclosure summary for the clustering explainer. */
export const CLUSTERING_DISCLOSURE_SUMMARY = 'What does clustering do?';

/**
 * Disclosure body — operator language, no "embeddings" / tutorial jargon.
 * Renders only when the disclosure is open.
 */
export const CLUSTERING_DISCLOSURE_BODY =
  'Clustering groups similar faces found during a scan so you can name a whole group at once instead of labeling every photo.';

/**
 * ConfirmPanel zero state when no recognition job has been selected/run.
 * Replaces the fabricated "Status — Pending" pair.
 */
export const CONFIRM_NO_JOB_ZERO_STATE =
  'No scan has run yet — run a scan from the Media step first.';
