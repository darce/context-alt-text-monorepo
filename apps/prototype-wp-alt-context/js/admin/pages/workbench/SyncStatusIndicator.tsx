import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import type { SyncHealth, WorkbenchOverlay } from '../../api/recognition';
import { useSyncHealth } from '../../hooks/useSyncHealth';
import { useSyncStatus } from '../../hooks/useSyncStatus';
import { isSyncOffline } from './degradedModeBannerLogic';
import { buildWorkbenchOverlayHref } from './workbenchOverlayLinks';
import { useSyncTrigger } from '../../hooks/useSyncTrigger';
import { useRetentionStatus } from '../../hooks/useRetentionStatus';
import type { PipelinePhase } from '../../hooks/jobStateMachineUtils';
import type { ProjectionSyncState } from '../../hooks/useJobStateMachineEffects';
import type { WorkbenchTab } from './WorkbenchContext';

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

const formatRetentionMode = (mode: string): string => {
  switch (mode) {
    case 'dispose_after_ack':
      return __('Retention: Dispose after ack', 'alt-context');
    case 'purge_on_demand':
      return __('Retention: Purge on demand', 'alt-context');
    default:
      return __('Retention: Retain all', 'alt-context');
  }
};

const formatSyncMode = (mode: 'delta' | 'full'): string =>
  mode === 'delta' ? __('Delta sync', 'alt-context') : __('Full sync', 'alt-context');

interface SyncStatusIndicatorProps {
  activeSection?: WorkbenchTab;
  pipelinePhase?: PipelinePhase;
  projectionState?: ProjectionSyncState;
  projectionError?: string | null;
  onRetryProjection?: () => void;
}

interface IdleStatePresentation {
  toneClassName: string;
  label: string;
  badge: string;
  badgeHref?: string;
  actionLabel?: string;
}

const buildIdleState = (
  syncHealth: SyncHealth,
  lastSyncedAt: string | null | undefined,
  activeSection: WorkbenchTab,
): IdleStatePresentation => {
  const formatted = formatTimestamp(lastSyncedAt);
  const lastSyncLabel = formatted
    ? sprintf(__('Last sync: %s', 'alt-context'), formatted)
    : __('No sync recorded yet', 'alt-context');

  switch (syncHealth) {
    case 'offline':
      return {
        toneClassName: 'acx-sync-status--warning',
        label: __('Waiting for service…', 'alt-context'),
        badge: __('Offline', 'alt-context'),
        actionLabel: __('Retry', 'alt-context'),
      };
    case 'failures':
      return {
        toneClassName: 'acx-sync-status--warning',
        label: __('Curation replay needs attention.', 'alt-context'),
        badge: __('Failures', 'alt-context'),
        badgeHref: buildWorkbenchOverlayHref(activeSection, 'dead-letter'),
      };
    case 'conflicts':
      return {
        toneClassName: 'acx-sync-status--warning',
        label: __('Conflict resolution is required before replay can catch up.', 'alt-context'),
        badge: __('Conflicts', 'alt-context'),
        badgeHref: buildWorkbenchOverlayHref(activeSection, 'conflicts'),
      };
    case 'queued':
      return {
        toneClassName: 'acx-sync-status--info',
        label: __('Local curation changes are queued for replay.', 'alt-context'),
        badge: __('Queued', 'alt-context'),
      };
    case 'stale':
      return {
        toneClassName: 'acx-sync-status--warning',
        label: lastSyncLabel,
        badge: __('Stale', 'alt-context'),
        actionLabel: __('Sync now', 'alt-context'),
      };
    case 'healthy':
    default:
      return {
        toneClassName: '',
        label: lastSyncLabel,
        badge: __('Fresh', 'alt-context'),
      };
  }
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

  if (isLoading) {
    return null;
  }

  if (isError || !data) {
    return (
      <div className="acx-sync-status acx-sync-status--warning">
        <span className="acx-sync-status__label">{__('Sync status unavailable', 'alt-context')}</span>
      </div>
    );
  }

  const pendingCuration = normalizeCount(data.pending_curation_operations);
  const failedCuration = normalizeCount(data.failed_curation_operations);
  const conflictCount = normalizeCount(data.conflict_count);
  const acknowledgedAt = formatTimestamp(data.last_curation_acknowledged_at);
  const conflictAt = formatTimestamp(data.last_curation_conflict_at);
  const failedAt = formatTimestamp(data.last_curation_failed_at);
  const topologyPending = normalizeCount(data.topology_commands?.pending);
  const topologyApplied = normalizeCount(data.topology_commands?.applied);
  const topologyFailed = normalizeCount(data.topology_commands?.failed);
  const topologyConflict = normalizeCount(data.topology_commands?.conflict);
  const conflictHref = buildWorkbenchOverlayHref(activeSection, 'conflicts');
  const deadLetterHref = buildWorkbenchOverlayHref(activeSection, 'dead-letter');
  const retentionMode = retentionStatus.data?.available ? retentionStatus.data.policy?.retention_mode : null;
  const syncMode = data.sync_mode ? formatSyncMode(data.sync_mode) : null;
  const retentionDetails =
    retentionMode && retentionMode !== 'retain_all' ? (
      <div className="acx-sync-status__meta" aria-label={__('Retention details', 'alt-context')}>
        <a href="#/retention" className="acx-sync-status__link">
          {formatRetentionMode(retentionMode)}
        </a>
      </div>
    ) : null;
  const syncModeDetails = syncMode ? (
    <div className="acx-sync-status__meta" aria-label={__('Sync mode details', 'alt-context')}>
      <span className="acx-sync-status__badge">{syncMode}</span>
    </div>
  ) : null;

  const curationDetails =
    pendingCuration > 0 || failedCuration > 0 || conflictCount > 0 || acknowledgedAt || conflictAt || failedAt ? (
      <div className="acx-sync-status__meta" aria-label={__('Curation sync details', 'alt-context')}>
        {pendingCuration > 0 ? (
          <span className="acx-sync-status__badge">
            {sprintf(__('Pending curation: %d', 'alt-context'), pendingCuration)}
          </span>
        ) : null}
        {conflictCount > 0 ? (
          <a href={conflictHref} className="acx-sync-status__link">
            {sprintf(__('Conflicts: %d', 'alt-context'), conflictCount)}
          </a>
        ) : null}
        {failedCuration > 0 ? (
          <a href={deadLetterHref} className="acx-sync-status__link">
            {sprintf(__('Failed replay: %d', 'alt-context'), failedCuration)}
          </a>
        ) : null}
        {acknowledgedAt ? (
          <span className="acx-sync-status__label">
            {sprintf(__('Last curation acknowledgement: %s', 'alt-context'), acknowledgedAt)}
          </span>
        ) : null}
        {conflictAt ? (
          <span className="acx-sync-status__label">
            {sprintf(__('Last curation conflict: %s', 'alt-context'), conflictAt)}
          </span>
        ) : null}
        {failedAt ? (
          <span className="acx-sync-status__label">
            {sprintf(__('Last curation failure: %s', 'alt-context'), failedAt)}
          </span>
        ) : null}
      </div>
    ) : null;

  const topologyDetails =
    topologyPending > 0 || topologyApplied > 0 || topologyFailed > 0 || topologyConflict > 0 ? (
      <div className="acx-sync-status__meta" aria-label={__('Topology command details', 'alt-context')}>
        <span className="acx-sync-status__label">
          {sprintf(
            __('Topology backlog: pending %1$d, applied %2$d, failed %3$d, conflicts %4$d', 'alt-context'),
            topologyPending,
            topologyApplied,
            topologyFailed,
            topologyConflict,
          )}
        </span>
      </div>
    ) : null;

  if (projectionState === 'error') {
    return (
      <div className="acx-sync-status acx-sync-status--syncing">
        <span className="acx-sync-status__label">{projectionError ?? __('Waiting for service…', 'alt-context')}</span>
        <button
          type="button"
          className="button button-link"
          onClick={() => onRetryProjection?.()}
          disabled={!onRetryProjection}
        >
          {__('Retry sync', 'alt-context')}
        </button>
        {syncModeDetails}
        {retentionDetails}
        {curationDetails}
        {topologyDetails}
      </div>
    );
  }

  if (pipelinePhase === 'projecting') {
    if (projectionState === 'ready') {
      return (
        <div className="acx-sync-status acx-sync-status--success">
          <span className="acx-sync-status__label">{__('Projected results ready for review.', 'alt-context')}</span>
          <span className="acx-sync-status__badge acx-sync-status__badge--ok">{__('Ready', 'alt-context')}</span>
          {syncModeDetails}
          {retentionDetails}
          {curationDetails}
          {topologyDetails}
        </div>
      );
    }

    return (
      <div className="acx-sync-status acx-sync-status--syncing">
        <span className="acx-sync-status__label">
          {projectionState === 'acknowledging'
            ? __('Acknowledging projected results…', 'alt-context')
            : __('Syncing results…', 'alt-context')}
        </span>
        <span className="acx-sync-status__badge">{__('In Progress', 'alt-context')}</span>
        {syncModeDetails}
        {retentionDetails}
        {curationDetails}
        {topologyDetails}
      </div>
    );
  }

  if (data.is_stale && syncTrigger.isPending) {
    return (
      <div className="acx-sync-status acx-sync-status--syncing">
        <span className="acx-sync-status__label">{__('Syncing…', 'alt-context')}</span>
        <span className="acx-sync-status__badge">{__('In Progress', 'alt-context')}</span>
        {syncModeDetails}
        {retentionDetails}
        {curationDetails}
        {topologyDetails}
      </div>
    );
  }

  if (syncTrigger.isSuccess && syncTrigger.data?.synced && syncTrigger.data.reason === 'no_remote_data') {
    return (
      <div className="acx-sync-status acx-sync-status--info">
        <span className="acx-sync-status__label">{__('Service connected — no clusters yet', 'alt-context')}</span>
        {syncModeDetails}
        {retentionDetails}
        {curationDetails}
        {topologyDetails}
      </div>
    );
  }

  if (syncTrigger.isSuccess && syncTrigger.data?.synced) {
    const syncedAt = formatTimestamp(syncTrigger.data.last_synced_at);
    return (
      <div className="acx-sync-status acx-sync-status--success">
        <span className="acx-sync-status__label">
          {syncedAt ? sprintf(__('Sync completed: %s', 'alt-context'), syncedAt) : __('Sync completed', 'alt-context')}
        </span>
        <span className="acx-sync-status__badge acx-sync-status__badge--ok">{__('Fresh', 'alt-context')}</span>
        {syncModeDetails}
        {retentionDetails}
        {curationDetails}
        {topologyDetails}
      </div>
    );
  }

  if (data.is_stale && ((syncTrigger.isSuccess && !syncTrigger.data?.synced) || syncTrigger.isError)) {
    return (
      <div className="acx-sync-status acx-sync-status--syncing">
        <span className="acx-sync-status__label">{__('Waiting for service…', 'alt-context')}</span>
        <button
          type="button"
          className="button button-link"
          onClick={() => syncTrigger.mutate()}
          disabled={syncTrigger.isPending}
        >
          {__('Retry', 'alt-context')}
        </button>
        {syncModeDetails}
        {retentionDetails}
        {curationDetails}
        {topologyDetails}
      </div>
    );
  }

  const effectiveSyncHealth = syncHealthEnvelope && isSyncOffline(syncHealthEnvelope) ? 'offline' : data.sync_health;
  const idleState = buildIdleState(effectiveSyncHealth, data.last_synced_at, activeSection);

  return (
    <div className={`acx-sync-status${idleState.toneClassName ? ` ${idleState.toneClassName}` : ''}`}>
      <span className="acx-sync-status__label">{idleState.label}</span>
      {idleState.badgeHref ? (
        <a
          href={idleState.badgeHref}
          className={`acx-sync-status__badge acx-sync-status__link${effectiveSyncHealth === 'healthy' ? ' acx-sync-status__badge--ok' : ''}`}
        >
          {idleState.badge}
        </a>
      ) : (
        <span
          className={`acx-sync-status__badge${effectiveSyncHealth === 'healthy' ? ' acx-sync-status__badge--ok' : ''}`}
        >
          {idleState.badge}
        </span>
      )}
      {syncModeDetails}
      {retentionDetails}
      {idleState.actionLabel ? (
        <button
          type="button"
          className="button button-link"
          onClick={() => syncTrigger.mutate()}
          disabled={syncTrigger.isPending}
        >
          {idleState.actionLabel}
        </button>
      ) : null}
      {curationDetails}
      {topologyDetails}
    </div>
  );
};
