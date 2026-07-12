import React from 'react';
import { sprintf } from '@wordpress/i18n';

import { useSyncHealth } from '../../hooks/useSyncHealth';
import { useSyncStatus } from '../../hooks/useSyncStatus';
import { useSyncTrigger } from '../../hooks/useSyncTrigger';
import { useRetentionStatus } from '../../hooks/useRetentionStatus';
import type { PipelinePhase } from '../../hooks/jobStateMachineUtils';
import type { ProjectionSyncState } from '../../hooks/useJobStateMachineEffects';
import type { WorkbenchTab } from './WorkbenchContext';
import {
  SYNC_PRESENTATION_ICON,
  SYNC_PRESENTATION_TONE,
  SYNC_VOCABULARY,
  buildSyncPresentation,
  formatRetentionModeLabel,
  formatSyncModeLabel,
  syncPresentationIconGlyph,
  syncPresentationToneClass,
  type SyncPresentation,
} from './syncPresentation';
import { buildWorkbenchOverlayHref } from './workbenchOverlayLinks';

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

const normalizeCount = (value: number | null | undefined): number => {
  if (typeof value !== 'number' || Number.isNaN(value) || value <= 0) {
    return 0;
  }

  return Math.floor(value);
};

interface SyncStatusIndicatorProps {
  activeSection?: WorkbenchTab;
  pipelinePhase?: PipelinePhase;
  projectionState?: ProjectionSyncState;
  projectionError?: string | null;
  onRetryProjection?: () => void;
}

const SyncStatusStrip = ({
  presentation,
  onAction,
  meta,
}: {
  presentation: SyncPresentation;
  onAction?: () => void;
  meta?: React.ReactNode;
}): React.JSX.Element => {
  const toneClass = syncPresentationToneClass(presentation.tone);
  const glyph = syncPresentationIconGlyph(presentation.icon);
  const badgeOk = presentation.tone === SYNC_PRESENTATION_TONE.SUCCESS || presentation.badge === SYNC_VOCABULARY.healthyBadge;
  const actionIsButton =
    presentation.action &&
    (presentation.action.kind === 'retry' ||
      presentation.action.kind === 'sync_now' ||
      presentation.action.kind === 'retry_results');
  // Badge href already surfaces the navigation target — skip a duplicate action link.
  const showActionLink =
    presentation.action &&
    !actionIsButton &&
    Boolean(presentation.action.href) &&
    presentation.action.href !== presentation.badgeHref;

  return (
    <div
      className={`acx-sync-status${toneClass ? ` ${toneClass}` : ''}`}
      role="status"
      aria-live="polite"
      data-testid="acx-sync-status-strip"
      data-sync-status={presentation.status}
    >
      <span className="acx-sync-status__icon" aria-hidden="true">
        {presentation.icon === SYNC_PRESENTATION_ICON.SPINNER ? (
          <span className="acx-sync-status__spinner">{glyph}</span>
        ) : (
          glyph
        )}
      </span>
      <span className="acx-sync-status__label">{presentation.headline}</span>
      {presentation.badge ? (
        presentation.badgeHref ? (
          <a
            href={presentation.badgeHref}
            className={`acx-sync-status__badge acx-sync-status__link${badgeOk ? ' acx-sync-status__badge--ok' : ''}`}
          >
            {presentation.badge}
          </a>
        ) : (
          <span className={`acx-sync-status__badge${badgeOk ? ' acx-sync-status__badge--ok' : ''}`}>
            {presentation.badge}
          </span>
        )
      ) : null}
      {presentation.detail ? <span className="acx-sync-status__detail">{presentation.detail}</span> : null}
      {presentation.action && actionIsButton ? (
        <button type="button" className="button button-link" onClick={onAction} disabled={!onAction}>
          {presentation.action.label}
        </button>
      ) : null}
      {showActionLink && presentation.action?.href ? (
        <a href={presentation.action.href} className="acx-sync-status__link">
          {presentation.action.label}
        </a>
      ) : null}
      {meta}
    </div>
  );
};

export const SyncStatusIndicator = ({
  activeSection = 'scan',
  pipelinePhase,
  projectionState = 'idle',
  projectionError = null,
  onRetryProjection,
}: SyncStatusIndicatorProps): React.JSX.Element | null => {
  const { data, isError, isLoading } = useSyncStatus();
  const { data: syncHealthEnvelope } = useSyncHealth();
  const retentionStatus = useRetentionStatus();
  const syncTrigger = useSyncTrigger(data?.is_stale ?? false);

  // Preserve prior empty-while-loading behaviour (tests + layout stability).
  if (isLoading) {
    return null;
  }

  const presentation = buildSyncPresentation({
    isLoading: false,
    isError: isError || !data,
    legacySyncHealth: data?.sync_health ?? null,
    syncHealthEnvelope: syncHealthEnvelope ?? null,
    lastSyncedAt: data?.last_synced_at ?? null,
    isStale: data?.is_stale ?? false,
    triggerPending: syncTrigger.isPending,
    triggerSuccess: syncTrigger.isSuccess,
    triggerError: syncTrigger.isError,
    triggerSynced: syncTrigger.data?.synced ?? false,
    triggerReason: syncTrigger.data?.reason ?? null,
    triggerLastSyncedAt: syncTrigger.data?.last_synced_at ?? null,
    pipelinePhase: pipelinePhase ?? 'idle',
    resultsSyncState: projectionState,
    resultsError: projectionError,
    activeSection,
  });

  const pendingChanges = normalizeCount(data?.pending_curation_operations);
  const failedOps = normalizeCount(data?.failed_curation_operations);
  const conflictCount = normalizeCount(data?.conflict_count);
  const acknowledgedAt = formatTimestamp(data?.last_curation_acknowledged_at);
  const conflictAt = formatTimestamp(data?.last_curation_conflict_at);
  const failedAt = formatTimestamp(data?.last_curation_failed_at);
  const backlogPending = normalizeCount(data?.topology_commands?.pending);
  const backlogApplied = normalizeCount(data?.topology_commands?.applied);
  const backlogFailed = normalizeCount(data?.topology_commands?.failed);
  const backlogConflict = normalizeCount(data?.topology_commands?.conflict);
  const conflictHref = buildWorkbenchOverlayHref(activeSection, 'conflicts');
  const failuresHref = buildWorkbenchOverlayHref(activeSection, 'dead-letter');
  const retentionMode = retentionStatus.data?.available ? retentionStatus.data.policy?.retention_mode : null;
  const syncMode = data?.sync_mode ? formatSyncModeLabel(data.sync_mode) : null;

  const retentionDetails =
    retentionMode && retentionMode !== 'retain_all' ? (
      <div className="acx-sync-status__meta">
        <a href="#/retention" className="acx-sync-status__link">
          {formatRetentionModeLabel(retentionMode)}
        </a>
      </div>
    ) : null;

  const syncModeDetails = syncMode ? (
    <div className="acx-sync-status__meta">
      <span className="acx-sync-status__badge">{syncMode}</span>
    </div>
  ) : null;

  const changeDetails =
    pendingChanges > 0 || failedOps > 0 || conflictCount > 0 || acknowledgedAt || conflictAt || failedAt ? (
      <div className="acx-sync-status__meta">
        {pendingChanges > 0 ? (
          <span className="acx-sync-status__badge">
            {sprintf(SYNC_VOCABULARY.pendingChanges, pendingChanges)}
          </span>
        ) : null}
        {conflictCount > 0 ? (
          <a href={conflictHref} className="acx-sync-status__link">
            {sprintf(SYNC_VOCABULARY.conflictsCount, conflictCount)}
          </a>
        ) : null}
        {failedOps > 0 ? (
          <a href={failuresHref} className="acx-sync-status__link">
            {sprintf(SYNC_VOCABULARY.failedOps, failedOps)}
          </a>
        ) : null}
        {acknowledgedAt ? (
          <span className="acx-sync-status__label">
            {sprintf(SYNC_VOCABULARY.lastChangeConfirmed, acknowledgedAt)}
          </span>
        ) : null}
        {conflictAt ? (
          <span className="acx-sync-status__label">{sprintf(SYNC_VOCABULARY.lastConflict, conflictAt)}</span>
        ) : null}
        {failedAt ? (
          <span className="acx-sync-status__label">{sprintf(SYNC_VOCABULARY.lastFailure, failedAt)}</span>
        ) : null}
      </div>
    ) : null;

  const backlogDetails =
    backlogPending > 0 || backlogApplied > 0 || backlogFailed > 0 || backlogConflict > 0 ? (
      <div className="acx-sync-status__meta">
        <span className="acx-sync-status__label">
          {sprintf(
            SYNC_VOCABULARY.syncBacklog,
            backlogPending,
            backlogApplied,
            backlogFailed,
            backlogConflict,
          )}
        </span>
      </div>
    ) : null;

  const meta = (
    <>
      {syncModeDetails}
      {retentionDetails}
      {changeDetails}
      {backlogDetails}
    </>
  );

  const handleAction = (): void => {
    if (!presentation.action) {
      return;
    }
    if (presentation.action.kind === 'retry_results') {
      onRetryProjection?.();
      return;
    }
    if (presentation.action.kind === 'retry' || presentation.action.kind === 'sync_now') {
      syncTrigger.mutate();
    }
  };

  return <SyncStatusStrip presentation={presentation} onAction={handleAction} meta={meta} />;
};
