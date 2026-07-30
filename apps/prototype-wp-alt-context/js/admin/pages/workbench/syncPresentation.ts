/**
 * SyncPresentation — single status view-model for admin pages.
 *
 * Derives plain-language status truth from resolveEffectiveSyncHealth plus
 * job/run state. All user-facing status strings live in the vocabulary maps
 * below (sr-007). Surfaces must render this object; they must not re-derive
 * health or invent status copy.
 */
import { __, sprintf } from '@wordpress/i18n';

import type {
  LastSyncResult,
  SyncHealth,
  SyncHealthResponse,
  SyncStatusResponse,
} from '../../api/recognition/types/sync';
import { LAST_SYNC_RESULT } from '../../api/recognition/types/sync';
import type { PipelinePhase } from '../../hooks/jobStateMachineUtils';
import type { ProjectionSyncState } from '../../hooks/useJobStateMachineEffects';
import { resolveEffectiveSyncHealth } from './degradedModeBannerLogic';
import { JOB_PHASE_PRESENTATION, type JobPhase } from './phasePresentation';
import { SYNC_VOCABULARY } from './syncVocabulary';
import { buildWorkbenchOverlayHref } from '../../navigation/appLinks';
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
  RESYNC_REQUIRED: 'resync_required',
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

// SYNC_VOCABULARY lives in ./syncVocabulary (leaf module) so the phase
// strategy map can build entries from it while this file reads the map for
// formatSyncJobPhase — no circular import. Re-exported to keep the E21-1
// surface unchanged.
export { SYNC_VOCABULARY } from './syncVocabulary';

export type JobActivity = 'idle' | 'scan' | 'cluster' | 'describe';

export interface SyncPresentationInput {
  isLoading?: boolean;
  isError?: boolean;
  legacySyncHealth?: SyncHealth | null;
  syncHealthEnvelope?: SyncHealthResponse | null;
  lastSyncedAt?: string | null;
  isStale?: boolean;
  /**
   * Wire last_sync_result. R23-BR-23: when resync_required, the strip must not
   * render healthy solely from sync_health.
   */
  lastSyncResult?: LastSyncResult | null;
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
    lastSyncResult = null,
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

  // R23-BR-23: durable resync marker must outrank a stale "healthy" sync_health
  // so the operator sees the real state. last_sync_result is the sole trigger —
  // the producer never emits a top-level failed: string[] (HARM-BR-04).
  if (lastSyncResult === LAST_SYNC_RESULT.RESYNC_REQUIRED) {
    return presentation({
      status: SYNC_PRESENTATION_STATUS.RESYNC_REQUIRED,
      headline: SYNC_VOCABULARY.resyncRequiredHeadline,
      detail: SYNC_VOCABULARY.resyncRequiredSummary,
      badge: SYNC_VOCABULARY.resyncRequiredBadge,
      icon: SYNC_PRESENTATION_ICON.WARNING,
      tone: SYNC_PRESENTATION_TONE.WARNING,
      action: { label: SYNC_VOCABULARY.syncNow, kind: 'sync_now' },
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

/**
 * Map job progress phase codes to plain-language labels. Keeps the wide
 * `(phase: string): string` signature with unknown-phase passthrough — the
 * exported contract; callers narrow at their own seam.
 */
export const formatSyncJobPhase = (phase: string): string =>
  // The cast widens the key: unknown phases resolve to undefined at runtime.
  JOB_PHASE_PRESENTATION[phase as JobPhase]?.label ?? phase;

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

/** Build presentation inputs from a SyncStatusResponse + UI flags. */
export const syncPresentationInputFromStatus = (
  data: SyncStatusResponse | null | undefined,
  extras: Omit<
    SyncPresentationInput,
    | 'legacySyncHealth'
    | 'lastSyncedAt'
    | 'isStale'
    | 'pendingChanges'
    | 'failedOps'
    | 'conflictCount'
    | 'lastSyncResult'
  > = {},
): SyncPresentationInput => ({
  ...extras,
  legacySyncHealth: data?.sync_health ?? null,
  lastSyncedAt: data?.last_synced_at ?? null,
  isStale: data?.is_stale ?? false,
  lastSyncResult: data?.last_sync_result ?? null,
  pendingChanges: data?.pending_curation_operations,
  failedOps: data?.failed_curation_operations,
  conflictCount: data?.conflict_count,
});
