import { __ } from '@wordpress/i18n';

import type { SyncHealth, SyncHealthResponse, SyncHealthWarning } from '../../api/recognition/types/sync';

import { SCAN_CONFLICTS_HREF, SCAN_DEAD_LETTER_HREF } from './workbenchOverlayLinks';

export const isSyncOffline = (health: SyncHealthResponse): boolean =>
  health.breaker.state === 'open' || health.last_pull.ok === false;

export const resolveEffectiveSyncHealth = (
  legacySyncHealth: SyncHealth,
  syncHealthEnvelope: SyncHealthResponse | null | undefined,
): SyncHealth => (syncHealthEnvelope && isSyncOffline(syncHealthEnvelope) ? 'offline' : legacySyncHealth);

export const getDashboardSyncHealthSummary = (
  effectiveSyncHealth: SyncHealth,
  syncHealthEnvelope: SyncHealthResponse | null | undefined,
): string => {
  if (syncHealthEnvelope && hasSyncHealthWarnings(syncHealthEnvelope) && effectiveSyncHealth === 'healthy') {
    return getDegradedWarningMessage(syncHealthEnvelope) ?? __('Sync attention needed.', 'alt-context');
  }

  switch (effectiveSyncHealth) {
    case 'healthy':
      return __('Machine sync is healthy and curation replay is caught up.', 'alt-context');
    case 'queued':
      return __('Local curation changes are queued for replay.', 'alt-context');
    case 'conflicts':
      return __('Conflict resolution is blocking part of the replay queue.', 'alt-context');
    case 'failures':
      return __('Some replay operations failed and need operator attention.', 'alt-context');
    case 'offline':
      return __('The recognition backend is currently unreachable.', 'alt-context');
    case 'stale':
    default:
      return __('Machine state is stale and should be refreshed.', 'alt-context');
  }
};

export const hasSyncHealthWarnings = (health: SyncHealthResponse): boolean => health.warnings.length > 0;

export const shouldShowDegradedBanner = (health: SyncHealthResponse): boolean =>
  isSyncOffline(health) || hasSyncHealthWarnings(health);

export const getDegradedBannerTitle = (health: SyncHealthResponse): string =>
  isSyncOffline(health) ? __('Working offline', 'alt-context') : __('Sync attention needed', 'alt-context');

export const getDegradedBannerMessage = (): string =>
  __('Showing your local copy; changes will sync when the service returns.', 'alt-context');

export const translateSyncHealthWarning = (warning: SyncHealthWarning): string => {
  switch (warning.code) {
    case 'open_conflicts_high':
      return __('Open sync conflicts exceed the configured warning threshold.', 'alt-context');
    default:
      return warning.message;
  }
};

export const getDegradedWarningMessage = (health: SyncHealthResponse): string | null => {
  const warning = health.warnings[0];
  if (!warning) {
    return null;
  }

  return translateSyncHealthWarning(warning);
};

export const getDegradedDebtLinks = (
  health: SyncHealthResponse,
): { failedOutboxHref: string | null; conflictsHref: string | null } => ({
  failedOutboxHref: health.outbox.failed > 0 ? SCAN_DEAD_LETTER_HREF : null,
  conflictsHref: health.conflicts.open > 0 ? SCAN_CONFLICTS_HREF : null,
});
