import { __ } from '@wordpress/i18n';

import type { SyncHealth, SyncHealthResponse, SyncHealthWarning } from '../../api/recognition/types/sync';

import { SYNC_VOCABULARY } from './syncVocabulary';
import { SCAN_CONFLICTS_HREF, SCAN_DEAD_LETTER_HREF } from './workbenchOverlayLinks';

// "Offline" means the recognition service is *currently unreachable*, which is
// the breaker's job (2-failure threshold, self-healing / 60s auto-expire).
// `last_pull.ok` is a LATCHED historical sync-outcome: a single transient pull
// blip writes it false and it stays false until the next *successful* background
// pull — the 15s health poll never repairs it. Treating that as "offline" showed
// "Working offline" on a fully reachable backend (false positive). A failed pull
// with a closed breaker is at most advisory (surfaced via warnings), not offline.
export const isSyncOffline = (health: SyncHealthResponse): boolean =>
  health.breaker.state === 'open';

export const resolveEffectiveSyncHealth = (
  legacySyncHealth: SyncHealth,
  syncHealthEnvelope: SyncHealthResponse | null | undefined,
): SyncHealth => (syncHealthEnvelope && isSyncOffline(syncHealthEnvelope) ? 'offline' : legacySyncHealth);

/**
 * Plain-language dashboard summary. Kept free of syncPresentation imports to
 * avoid a circular dependency (syncPresentation consumes resolveEffectiveSyncHealth).
 * Copy must stay in lockstep with getSyncPresentationSummary.
 */
export const getDashboardSyncHealthSummary = (
  effectiveSyncHealth: SyncHealth,
  syncHealthEnvelope: SyncHealthResponse | null | undefined,
): string => {
  if (syncHealthEnvelope && hasSyncHealthWarnings(syncHealthEnvelope) && effectiveSyncHealth === 'healthy') {
    return getDegradedWarningMessage(syncHealthEnvelope) ?? __('Sync attention needed.', 'alt-context');
  }

  switch (effectiveSyncHealth) {
    case 'healthy':
      return __('Machine sync is healthy and local changes are caught up.', 'alt-context');
    case 'queued':
      return __('Local changes are waiting to sync.', 'alt-context');
    case 'conflicts':
      return __('Conflict resolution is blocking part of the sync queue.', 'alt-context');
    case 'failures':
      return __('Some sync operations failed and need operator attention.', 'alt-context');
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
    case 'backend_roster_regressed':
      return SYNC_VOCABULARY.backendRegressionWarning;
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
