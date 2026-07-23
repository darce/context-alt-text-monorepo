import { __ } from '@wordpress/i18n';

import type { SyncHealth, SyncHealthResponse, SyncHealthWarning } from '../../api/recognition/types/sync';

import { SYNC_VOCABULARY } from './syncVocabulary';
import { SCAN_CONFLICTS_HREF, SCAN_DEAD_LETTER_HREF } from '../../navigation/appLinks';

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
 * All copy reads from SYNC_VOCABULARY (single declaration site).
 */
export const getDashboardSyncHealthSummary = (
  effectiveSyncHealth: SyncHealth,
  syncHealthEnvelope: SyncHealthResponse | null | undefined,
): string => {
  if (syncHealthEnvelope && hasSyncHealthWarnings(syncHealthEnvelope) && effectiveSyncHealth === 'healthy') {
    return getDegradedWarningMessage(syncHealthEnvelope) ?? SYNC_VOCABULARY.attentionSummary;
  }

  switch (effectiveSyncHealth) {
    case 'healthy':
      return SYNC_VOCABULARY.healthySummary;
    case 'queued':
      return SYNC_VOCABULARY.queuedSummary;
    case 'conflicts':
      return SYNC_VOCABULARY.conflictsSummary;
    case 'failures':
      return SYNC_VOCABULARY.failuresSummary;
    case 'offline':
      return SYNC_VOCABULARY.offlineSummary;
    case 'stale':
    default:
      return SYNC_VOCABULARY.staleSummary;
  }
};

export const hasSyncHealthWarnings = (health: SyncHealthResponse): boolean => health.warnings.length > 0;

export const shouldShowDegradedBanner = (health: SyncHealthResponse): boolean =>
  isSyncOffline(health) || hasSyncHealthWarnings(health);

export const getDegradedBannerTitle = (health: SyncHealthResponse): string =>
  isSyncOffline(health) ? SYNC_VOCABULARY.offlineBannerTitle : SYNC_VOCABULARY.attentionBannerTitle;

export const getDegradedBannerMessage = (): string => SYNC_VOCABULARY.offlineDetail;

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
