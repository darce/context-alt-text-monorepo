/**
 * SyncPresentation — single status view-model for admin pages.
 *
 * Derives plain-language status truth from resolveEffectiveSyncHealth plus
 * job/run state. All user-facing status strings live in the vocabulary maps
 * below (sr-007). Surfaces must render this object; they must not re-derive
 * health or invent status copy.
 */
import { __, sprintf } from '@wordpress/i18n';

import type { SyncHealth, SyncHealthResponse, SyncStatusResponse } from '../../api/recognition/types/sync';
import type { PipelinePhase } from '../../hooks/jobStateMachineUtils';
import type { ProjectionSyncState } from '../../hooks/useJobStateMachineEffects';
import { resolveEffectiveSyncHealth } from './degradedModeBannerLogic';
import { buildWorkbenchOverlayHref } from './workbenchOverlayLinks';
import type { WorkbenchTab } from './WorkbenchContext';

/** Canonical status codes for the status strip (sr-007). */
export const SYNC_PRESENTATION_STATUS = {
  LOADING: 'loading',
  EMPTY: 'empty',
  ERROR: 'error',
  OFFLINE: 'offline',
  HEALTHY: 'healthy',
  QUEUED: 'queued',
  STALE: 'stale',
  CONFLICTS: 'conflicts',
  FAILURES: 'failures',
  SYNCING: 'syncing',
  SCANNING: 'scanning',
  CLUSTERING: 'clustering',
  DESCRIBING: 'describing',
  RESULTS_READY: 'results_ready',
  RESULTS_SYNCING: 'results_syncing',
  CONNECTED_EMPTY: 'connected_empty',
  ATTENTION: 'attention',
} as const;

export type SyncPresentationStatus =
  (typeof SYNC_PRESENTATION_STATUS)[keyof typeof SYNC_PRESENTATION_STATUS];

/** Visual tone tokens — map to --acx-* CSS classes, never hex (sr-004). */
export const SYNC_PRESENTATION_TONE = {
  NEUTRAL: 'neutral',
  INFO: 'info',
  SUCCESS: 'success',
  WARNING: 'warning',
  DANGER: 'danger',
  SYNCING: 'syncing',
} as const;

export type SyncPresentationTone = (typeof SYNC_PRESENTATION_TONE)[keyof typeof SYNC_PRESENTATION_TONE];

/** Icon tokens for the strip (icon + color + word). */
export const SYNC_PRESENTATION_ICON = {
  SPINNER: 'spinner',
  CHECK: 'check',
  WARNING: 'warning',
  ERROR: 'error',
  INFO: 'info',
  OFFLINE: 'offline',
  IDLE: 'idle',
} as const;

export type SyncPresentationIcon = (typeof SYNC_PRESENTATION_ICON)[keyof typeof SYNC_PRESENTATION_ICON];

export type SyncPresentationActionKind =
  | 'retry'
  | 'sync_now'
  | 'retry_results'
  | 'open_conflicts'
  | 'open_failures';

export interface SyncPresentationAction {
  label: string;
  kind: SyncPresentationActionKind;
  href?: string;
}

export interface SyncPresentation {
  status: SyncPresentationStatus;
  headline: string;
  detail: string | null;
  icon: SyncPresentationIcon;
  tone: SyncPresentationTone;
  action?: SyncPresentationAction;
  /** Short word badge shown beside the headline (icon + color + word). */
  badge?: string;
  badgeHref?: string;
}

/**
 * All user-facing status vocabulary. Plain language only — no topology /
 * replay / projection / dead-letter jargon.
 */
export const SYNC_VOCABULARY = {
  loading: __('Checking sync…', 'alt-context'),
  empty: __('No sync recorded yet', 'alt-context'),
  error: __('Sync status unavailable', 'alt-context'),
  offlineHeadline: __('Waiting for service…', 'alt-context'),
  offlineBadge: __('Offline', 'alt-context'),
  offlineDetail: __('Showing your local copy; changes will sync when the service returns.', 'alt-context'),
  offlineBannerTitle: __('Working offline', 'alt-context'),
  attentionBannerTitle: __('Sync attention needed', 'alt-context'),
  healthyHeadline: __('Last sync: %s', 'alt-context'),
  healthyBadge: __('Fresh', 'alt-context'),
  healthySummary: __('Machine sync is healthy and local changes are caught up.', 'alt-context'),
  queuedHeadline: __('Local changes are waiting to sync.', 'alt-context'),
  queuedBadge: __('Queued', 'alt-context'),
  queuedSummary: __('Local changes are waiting to sync.', 'alt-context'),
  staleHeadline: __('Last sync: %s', 'alt-context'),
  staleBadge: __('Stale', 'alt-context'),
  staleSummary: __('Machine state is stale and should be refreshed.', 'alt-context'),
  conflictsHeadline: __('Conflict resolution is required before sync can catch up.', 'alt-context'),
  conflictsBadge: __('Conflicts', 'alt-context'),
  conflictsSummary: __('Conflict resolution is blocking part of the sync queue.', 'alt-context'),
  failuresHeadline: __('Some sync operations need attention.', 'alt-context'),
  failuresBadge: __('Failures', 'alt-context'),
  failuresSummary: __('Some sync operations failed and need operator attention.', 'alt-context'),
  syncingHeadline: __('Syncing…', 'alt-context'),
  syncingBadge: __('In Progress', 'alt-context'),
  scanningHeadline: __('Scanning…', 'alt-context'),
  clusteringHeadline: __('Clustering…', 'alt-context'),
  describingHeadline: __('Describing…', 'alt-context'),
  resultsReadyHeadline: __('Results ready for review.', 'alt-context'),
  resultsReadyBadge: __('Ready', 'alt-context'),
  resultsSyncingHeadline: __('Syncing results…', 'alt-context'),
  resultsAcknowledgingHeadline: __('Confirming results…', 'alt-context'),
  resultsErrorHeadline: __('Waiting for service…', 'alt-context'),
  connectedEmptyHeadline: __('Service connected — no clusters yet', 'alt-context'),
  syncCompletedHeadline: __('Sync completed: %s', 'alt-context'),
  syncCompletedBare: __('Sync completed', 'alt-context'),
  retry: __('Retry', 'alt-context'),
  retrySync: __('Retry sync', 'alt-context'),
  syncNow: __('Sync now', 'alt-context'),
  pendingChanges: __('Pending changes: %d', 'alt-context'),
  failedOps: __('Failed operations: %d', 'alt-context'),
  conflictsCount: __('Conflicts: %d', 'alt-context'),
  lastChangeConfirmed: __('Last change confirmed: %s', 'alt-context'),
  lastConflict: __('Last conflict: %s', 'alt-context'),
  lastFailure: __('Last failure: %s', 'alt-context'),
  syncBacklog: __('Sync backlog: pending %1$d, applied %2$d, failed %3$d, conflicts %4$d', 'alt-context'),
  syncBacklogShort: __('Sync backlog: pending %1$d, failed %2$d, conflicts %3$d', 'alt-context'),
  pendingChangesLabel: __('Pending changes', 'alt-context'),
  failedOpsLabel: __('Failed operations', 'alt-context'),
  conflictsLabel: __('Conflicts', 'alt-context'),
  reviewFailedOps: __('Review failed sync operations', 'alt-context'),
  resolveConflicts: __('Resolve sync conflicts', 'alt-context'),
  openWorkbenchDetail: __('Inspect sync status, scans, and queued sync work.', 'alt-context'),
  openFailedOpsDetail: __('Retry or discard failed sync operations.', 'alt-context'),
  scanComplete: __('Scan complete', 'alt-context'),
  clusteringComplete: __('Clustering complete', 'alt-context'),
  clusteringFailed: __('Clustering failed', 'alt-context'),
  resultsSyncFailed: __('Results sync failed', 'alt-context'),
  resultsSynced: __('Results synced', 'alt-context'),
  phaseQueued: __('Queued', 'alt-context'),
  phaseDetecting: __('Detecting', 'alt-context'),
  phaseClustering: __('Clustering', 'alt-context'),
  phaseRetrying: __('Retrying', 'alt-context'),
  phaseSyncingResults: __('Syncing results', 'alt-context'),
  phaseFailed: __('Failed', 'alt-context'),
  phaseComplete: __('Complete', 'alt-context'),
  describeStarting: __('Starting describe run…', 'alt-context'),
  describeLost: __('Lost connection to the describe run.', 'alt-context'),
  describeQueued: __('Queued', 'alt-context'),
  describeRunning: __('Describing', 'alt-context'),
  describeCompleted: __('Completed', 'alt-context'),
  describeCompletedWithErrors: __('Completed with errors', 'alt-context'),
  describeFailed: __('Failed', 'alt-context'),
  describeCancelled: __('Cancelled', 'alt-context'),
  // Person workspace vocabulary covered by this task (E21-9 owns full rewrite).
  dataVersion: __('Data version: %d', 'alt-context'),
  matchedFaces: __('%d matched faces', 'alt-context'),
  reviewQueues: __('Review queues', 'alt-context'),
  updateStatus: __('Update status: %s', 'alt-context'),
  lastUpdated: __('Last updated: %s', 'alt-context'),
  afterNextRefresh: __('after the next refresh', 'alt-context'),
  retentionDispose: __('Retention: Dispose after confirm', 'alt-context'),
  retentionPurge: __('Retention: Purge on demand', 'alt-context'),
  retentionRetain: __('Retention: Retain all', 'alt-context'),
  syncModeDelta: __('Delta sync', 'alt-context'),
  syncModeFull: __('Full sync', 'alt-context'),
  attentionSummary: __('Sync attention needed.', 'alt-context'),
  offlineSummary: __('The recognition backend is currently unreachable.', 'alt-context'),
} as const;

export type JobActivity = 'idle' | 'scan' | 'cluster' | 'describe';

export interface SyncPresentationInput {
  isLoading?: boolean;
  isError?: boolean;
  legacySyncHealth?: SyncHealth | null;
  syncHealthEnvelope?: SyncHealthResponse | null;
  lastSyncedAt?: string | null;
  isStale?: boolean;
  /** Transient sync-trigger UI state. */
  triggerPending?: boolean;
  triggerSuccess?: boolean;
  triggerError?: boolean;
  triggerSynced?: boolean;
  triggerReason?: 'ok' | 'sync_failed' | 'sync_unavailable' | 'no_remote_data' | null;
  triggerLastSyncedAt?: string | null;
  pipelinePhase?: PipelinePhase;
  resultsSyncState?: ProjectionSyncState;
  resultsError?: string | null;
  jobActivity?: JobActivity;
  activeSection?: WorkbenchTab;
  pendingChanges?: number;
  failedOps?: number;
  conflictCount?: number;
}

const formatTimestamp = (value: string | null | undefined): string | null => {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  return parsed.toLocaleString();
};

const toneClassFor = (tone: SyncPresentationTone): string => {
  switch (tone) {
    case SYNC_PRESENTATION_TONE.WARNING:
      return 'acx-sync-status--warning';
    case SYNC_PRESENTATION_TONE.INFO:
      return 'acx-sync-status--info';
    case SYNC_PRESENTATION_TONE.SUCCESS:
      return 'acx-sync-status--success';
    case SYNC_PRESENTATION_TONE.SYNCING:
      return 'acx-sync-status--syncing';
    case SYNC_PRESENTATION_TONE.DANGER:
      return 'acx-sync-status--warning';
    case SYNC_PRESENTATION_TONE.NEUTRAL:
    default:
      return '';
  }
};

/** CSS modifier class for the status strip (token-backed via SCSS). */
export const syncPresentationToneClass = (tone: SyncPresentationTone): string => toneClassFor(tone);

/** Icon glyph for the strip (paired with tone + word; not color-only). */
export const syncPresentationIconGlyph = (icon: SyncPresentationIcon): string => {
  switch (icon) {
    case SYNC_PRESENTATION_ICON.SPINNER:
      return '⟳';
    case SYNC_PRESENTATION_ICON.CHECK:
      return '✓';
    case SYNC_PRESENTATION_ICON.WARNING:
      return '!';
    case SYNC_PRESENTATION_ICON.ERROR:
      return '✕';
    case SYNC_PRESENTATION_ICON.OFFLINE:
      return '◌';
    case SYNC_PRESENTATION_ICON.INFO:
      return 'i';
    case SYNC_PRESENTATION_ICON.IDLE:
    default:
      return '●';
  }
};

const presentation = (
  partial: Omit<SyncPresentation, 'detail'> & { detail?: string | null },
): SyncPresentation => ({
  detail: null,
  ...partial,
});

/**
 * Build the single SyncPresentation view-model from health + job/run inputs.
 * Order mirrors prior SyncStatusIndicator priority: results error → pipeline
 * activity → trigger states → idle health.
 */
export const buildSyncPresentation = (input: SyncPresentationInput): SyncPresentation => {
  const {
    isLoading = false,
    isError = false,
    legacySyncHealth = null,
    syncHealthEnvelope = null,
    lastSyncedAt = null,
    isStale = false,
    triggerPending = false,
    triggerSuccess = false,
    triggerError = false,
    triggerSynced = false,
    triggerReason = null,
    triggerLastSyncedAt = null,
    pipelinePhase = 'idle',
    resultsSyncState = 'idle',
    resultsError = null,
    jobActivity = 'idle',
    activeSection = 'scan',
  } = input;

  if (isLoading) {
    return presentation({
      status: SYNC_PRESENTATION_STATUS.LOADING,
      headline: SYNC_VOCABULARY.loading,
      icon: SYNC_PRESENTATION_ICON.SPINNER,
      tone: SYNC_PRESENTATION_TONE.SYNCING,
    });
  }

  if (isError || legacySyncHealth === null) {
    return presentation({
      status: SYNC_PRESENTATION_STATUS.ERROR,
      headline: SYNC_VOCABULARY.error,
      icon: SYNC_PRESENTATION_ICON.ERROR,
      tone: SYNC_PRESENTATION_TONE.WARNING,
    });
  }

  if (resultsSyncState === 'error') {
    return presentation({
      status: SYNC_PRESENTATION_STATUS.ERROR,
      headline: resultsError ?? SYNC_VOCABULARY.resultsErrorHeadline,
      icon: SYNC_PRESENTATION_ICON.WARNING,
      tone: SYNC_PRESENTATION_TONE.SYNCING,
      action: { label: SYNC_VOCABULARY.retrySync, kind: 'retry_results' },
    });
  }

  if (pipelinePhase === 'projecting') {
    if (resultsSyncState === 'ready') {
      return presentation({
        status: SYNC_PRESENTATION_STATUS.RESULTS_READY,
        headline: SYNC_VOCABULARY.resultsReadyHeadline,
        badge: SYNC_VOCABULARY.resultsReadyBadge,
        icon: SYNC_PRESENTATION_ICON.CHECK,
        tone: SYNC_PRESENTATION_TONE.SUCCESS,
      });
    }
    const acknowledging = resultsSyncState === 'acknowledging';
    return presentation({
      status: SYNC_PRESENTATION_STATUS.RESULTS_SYNCING,
      headline: acknowledging
        ? SYNC_VOCABULARY.resultsAcknowledgingHeadline
        : SYNC_VOCABULARY.resultsSyncingHeadline,
      badge: SYNC_VOCABULARY.syncingBadge,
      icon: SYNC_PRESENTATION_ICON.SPINNER,
      tone: SYNC_PRESENTATION_TONE.SYNCING,
    });
  }

  if (jobActivity === 'scan' || pipelinePhase === 'scanning') {
    return presentation({
      status: SYNC_PRESENTATION_STATUS.SCANNING,
      headline: SYNC_VOCABULARY.scanningHeadline,
      badge: SYNC_VOCABULARY.syncingBadge,
      icon: SYNC_PRESENTATION_ICON.SPINNER,
      tone: SYNC_PRESENTATION_TONE.SYNCING,
    });
  }

  if (jobActivity === 'cluster' || pipelinePhase === 'clustering') {
    return presentation({
      status: SYNC_PRESENTATION_STATUS.CLUSTERING,
      headline: SYNC_VOCABULARY.clusteringHeadline,
      badge: SYNC_VOCABULARY.syncingBadge,
      icon: SYNC_PRESENTATION_ICON.SPINNER,
      tone: SYNC_PRESENTATION_TONE.SYNCING,
    });
  }

  if (jobActivity === 'describe') {
    return presentation({
      status: SYNC_PRESENTATION_STATUS.DESCRIBING,
      headline: SYNC_VOCABULARY.describingHeadline,
      badge: SYNC_VOCABULARY.syncingBadge,
      icon: SYNC_PRESENTATION_ICON.SPINNER,
      tone: SYNC_PRESENTATION_TONE.SYNCING,
    });
  }

  if (isStale && triggerPending) {
    return presentation({
      status: SYNC_PRESENTATION_STATUS.SYNCING,
      headline: SYNC_VOCABULARY.syncingHeadline,
      badge: SYNC_VOCABULARY.syncingBadge,
      icon: SYNC_PRESENTATION_ICON.SPINNER,
      tone: SYNC_PRESENTATION_TONE.SYNCING,
    });
  }

  if (triggerSuccess && triggerSynced && triggerReason === 'no_remote_data') {
    return presentation({
      status: SYNC_PRESENTATION_STATUS.CONNECTED_EMPTY,
      headline: SYNC_VOCABULARY.connectedEmptyHeadline,
      icon: SYNC_PRESENTATION_ICON.INFO,
      tone: SYNC_PRESENTATION_TONE.INFO,
    });
  }

  if (triggerSuccess && triggerSynced) {
    const syncedAt = formatTimestamp(triggerLastSyncedAt);
    return presentation({
      status: SYNC_PRESENTATION_STATUS.HEALTHY,
      headline: syncedAt
        ? sprintf(SYNC_VOCABULARY.syncCompletedHeadline, syncedAt)
        : SYNC_VOCABULARY.syncCompletedBare,
      badge: SYNC_VOCABULARY.healthyBadge,
      icon: SYNC_PRESENTATION_ICON.CHECK,
      tone: SYNC_PRESENTATION_TONE.SUCCESS,
    });
  }

  if (isStale && ((triggerSuccess && !triggerSynced) || triggerError)) {
    return presentation({
      status: SYNC_PRESENTATION_STATUS.OFFLINE,
      headline: SYNC_VOCABULARY.offlineHeadline,
      icon: SYNC_PRESENTATION_ICON.OFFLINE,
      tone: SYNC_PRESENTATION_TONE.SYNCING,
      action: { label: SYNC_VOCABULARY.retry, kind: 'retry' },
    });
  }

  const effective = resolveEffectiveSyncHealth(legacySyncHealth, syncHealthEnvelope);
  const formatted = formatTimestamp(lastSyncedAt);
  const lastSyncLabel = formatted
    ? sprintf(SYNC_VOCABULARY.healthyHeadline, formatted)
    : SYNC_VOCABULARY.empty;
  const conflictsHref = buildWorkbenchOverlayHref(activeSection, 'conflicts');
  const failuresHref = buildWorkbenchOverlayHref(activeSection, 'dead-letter');

  switch (effective) {
    case 'offline':
      return presentation({
        status: SYNC_PRESENTATION_STATUS.OFFLINE,
        headline: SYNC_VOCABULARY.offlineHeadline,
        detail: SYNC_VOCABULARY.offlineDetail,
        badge: SYNC_VOCABULARY.offlineBadge,
        icon: SYNC_PRESENTATION_ICON.OFFLINE,
        tone: SYNC_PRESENTATION_TONE.WARNING,
        action: { label: SYNC_VOCABULARY.retry, kind: 'retry' },
      });
    case 'failures':
      return presentation({
        status: SYNC_PRESENTATION_STATUS.FAILURES,
        headline: SYNC_VOCABULARY.failuresHeadline,
        badge: SYNC_VOCABULARY.failuresBadge,
        badgeHref: failuresHref,
        icon: SYNC_PRESENTATION_ICON.WARNING,
        tone: SYNC_PRESENTATION_TONE.WARNING,
        action: { label: SYNC_VOCABULARY.failuresBadge, kind: 'open_failures', href: failuresHref },
      });
    case 'conflicts':
      return presentation({
        status: SYNC_PRESENTATION_STATUS.CONFLICTS,
        headline: SYNC_VOCABULARY.conflictsHeadline,
        badge: SYNC_VOCABULARY.conflictsBadge,
        badgeHref: conflictsHref,
        icon: SYNC_PRESENTATION_ICON.WARNING,
        tone: SYNC_PRESENTATION_TONE.WARNING,
        action: { label: SYNC_VOCABULARY.conflictsBadge, kind: 'open_conflicts', href: conflictsHref },
      });
    case 'queued':
      return presentation({
        status: SYNC_PRESENTATION_STATUS.QUEUED,
        headline: SYNC_VOCABULARY.queuedHeadline,
        badge: SYNC_VOCABULARY.queuedBadge,
        icon: SYNC_PRESENTATION_ICON.INFO,
        tone: SYNC_PRESENTATION_TONE.INFO,
      });
    case 'stale':
      return presentation({
        status: SYNC_PRESENTATION_STATUS.STALE,
        headline: lastSyncLabel,
        badge: SYNC_VOCABULARY.staleBadge,
        icon: SYNC_PRESENTATION_ICON.WARNING,
        tone: SYNC_PRESENTATION_TONE.WARNING,
        action: { label: SYNC_VOCABULARY.syncNow, kind: 'sync_now' },
      });
    case 'healthy':
    default:
      return presentation({
        status: SYNC_PRESENTATION_STATUS.HEALTHY,
        headline: lastSyncLabel,
        badge: SYNC_VOCABULARY.healthyBadge,
        icon: SYNC_PRESENTATION_ICON.CHECK,
        tone: SYNC_PRESENTATION_TONE.NEUTRAL,
      });
  }
};

/** Dashboard / summary copy from effective health (plain language). */
export const getSyncPresentationSummary = (
  effectiveSyncHealth: SyncHealth,
  syncHealthEnvelope: SyncHealthResponse | null | undefined,
): string => {
  if (
    syncHealthEnvelope &&
    syncHealthEnvelope.warnings.length > 0 &&
    effectiveSyncHealth === 'healthy'
  ) {
    const warning = syncHealthEnvelope.warnings[0];
    if (warning?.code === 'open_conflicts_high') {
      return __('Open sync conflicts exceed the configured warning threshold.', 'alt-context');
    }
    return warning?.message ?? SYNC_VOCABULARY.attentionSummary;
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

/** Map job progress phase codes to plain-language labels. */
export const formatSyncJobPhase = (phase: string): string => {
  switch (phase) {
    case 'queued':
      return SYNC_VOCABULARY.phaseQueued;
    case 'detecting':
      return SYNC_VOCABULARY.phaseDetecting;
    case 'clustering':
      return SYNC_VOCABULARY.phaseClustering;
    case 'retrying':
      return SYNC_VOCABULARY.phaseRetrying;
    case 'awaiting_projection':
      return SYNC_VOCABULARY.phaseSyncingResults;
    case 'failed':
      return SYNC_VOCABULARY.phaseFailed;
    case 'complete':
      return SYNC_VOCABULARY.phaseComplete;
    default:
      return phase;
  }
};

export const formatRetentionModeLabel = (mode: string): string => {
  switch (mode) {
    case 'dispose_after_ack':
      return SYNC_VOCABULARY.retentionDispose;
    case 'purge_on_demand':
      return SYNC_VOCABULARY.retentionPurge;
    default:
      return SYNC_VOCABULARY.retentionRetain;
  }
};

export const formatSyncModeLabel = (mode: 'delta' | 'full'): string =>
  mode === 'delta' ? SYNC_VOCABULARY.syncModeDelta : SYNC_VOCABULARY.syncModeFull;

/** Build presentation inputs from a SyncStatusResponse + UI flags. */
export const syncPresentationInputFromStatus = (
  data: SyncStatusResponse | null | undefined,
  extras: Omit<SyncPresentationInput, 'legacySyncHealth' | 'lastSyncedAt' | 'isStale' | 'pendingChanges' | 'failedOps' | 'conflictCount'> = {},
): SyncPresentationInput => ({
  ...extras,
  legacySyncHealth: data?.sync_health ?? null,
  lastSyncedAt: data?.last_synced_at ?? null,
  isStale: data?.is_stale ?? false,
  pendingChanges: data?.pending_curation_operations,
  failedOps: data?.failed_curation_operations,
  conflictCount: data?.conflict_count,
});
