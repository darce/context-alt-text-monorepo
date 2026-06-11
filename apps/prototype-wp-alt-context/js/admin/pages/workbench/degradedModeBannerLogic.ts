import { __ } from '@wordpress/i18n';

import type { SyncHealthResponse } from '../../api/recognition/types/sync';

export const shouldShowDegradedBanner = (health: SyncHealthResponse): boolean =>
  health.breaker.state === 'open' || health.last_pull.ok === false || health.warnings.length > 0;

export const getDegradedBannerMessage = (): string =>
  __('Showing your local copy; changes will sync when the service returns.', 'alt-context');

export const getDegradedWarningMessage = (health: SyncHealthResponse): string | null => {
  const warning = health.warnings[0];
  if (!warning) {
    return null;
  }

  return warning.message;
};

export const getDegradedDebtLinks = (
  health: SyncHealthResponse,
): { failedOutboxHref: string | null; conflictsHref: string | null } => ({
  failedOutboxHref: health.outbox.failed > 0 ? '#/workbench?tab=scan&panel=dead-letter' : null,
  conflictsHref: health.conflicts.open > 0 ? '#/workbench?tab=scan&panel=conflicts' : null,
});