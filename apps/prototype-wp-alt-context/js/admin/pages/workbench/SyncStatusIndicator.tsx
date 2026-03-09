import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import { useSyncStatus } from '../../hooks/useSyncStatus';
import { useSyncTrigger } from '../../hooks/useSyncTrigger';
import type { PipelinePhase } from '../../hooks/jobStateMachineUtils';
import type { ProjectionSyncState } from '../../hooks/useJobStateMachineEffects';

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
  pipelinePhase?: PipelinePhase;
  projectionState?: ProjectionSyncState;
  projectionError?: string | null;
  onRetryProjection?: () => void;
}

export const SyncStatusIndicator = ({
  pipelinePhase,
  projectionState = 'idle',
  projectionError = null,
  onRetryProjection,
}: SyncStatusIndicatorProps): React.JSX.Element | null => {
  const { data, isError, isLoading } = useSyncStatus();
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
  const conflictCount = normalizeCount(data.conflict_count);
  const acknowledgedAt = formatTimestamp(data.last_curation_acknowledged_at);
  const conflictAt = formatTimestamp(data.last_curation_conflict_at);

  const curationDetails =
    pendingCuration > 0 || conflictCount > 0 || acknowledgedAt || conflictAt ? (
      <div className="acx-sync-status__meta" aria-label={__('Curation sync details', 'alt-context')}>
        {pendingCuration > 0 ? (
          <span className="acx-sync-status__badge">
            {sprintf(__('Pending curation: %d', 'alt-context'), pendingCuration)}
          </span>
        ) : null}
        {conflictCount > 0 ? (
          <span className="acx-sync-status__badge acx-sync-status__badge--warning">
            {sprintf(__('Conflicts: %d', 'alt-context'), conflictCount)}
          </span>
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
      </div>
    ) : null;

  if (pipelinePhase === 'projecting') {
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
          {curationDetails}
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
        {curationDetails}
      </div>
    );
  }

  // Show syncing state while trigger is in progress and stale.
  if (data.is_stale && syncTrigger.isPending) {
    return (
      <div className="acx-sync-status acx-sync-status--syncing">
        <span className="acx-sync-status__label">{__('Syncing…', 'alt-context')}</span>
        <span className="acx-sync-status__badge">{__('In Progress', 'alt-context')}</span>
        {curationDetails}
      </div>
    );
  }

  // Sync succeeded but no clusters exist yet — show informational state.
  if (syncTrigger.isSuccess && syncTrigger.data?.synced && syncTrigger.data.reason === 'no_remote_data') {
    return (
      <div className="acx-sync-status acx-sync-status--info">
        <span className="acx-sync-status__label">{__('Service connected — no clusters yet', 'alt-context')}</span>
        {curationDetails}
      </div>
    );
  }

  // Show success notification after sync completes
  if (syncTrigger.isSuccess && syncTrigger.data?.synced) {
    const syncedAt = formatTimestamp(syncTrigger.data.last_synced_at);
    return (
      <div className="acx-sync-status acx-sync-status--success">
        <span className="acx-sync-status__label">
          {syncedAt ? sprintf(__('Sync completed: %s', 'alt-context'), syncedAt) : __('Sync completed', 'alt-context')}
        </span>
        <span className="acx-sync-status__badge acx-sync-status__badge--ok">{__('Fresh', 'alt-context')}</span>
        {curationDetails}
      </div>
    );
  }

  // Sync was attempted but the service is unreachable.
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
        {curationDetails}
      </div>
    );
  }

  const formatted = formatTimestamp(data.last_synced_at);
  const label = formatted
    ? sprintf(__('Last sync: %s', 'alt-context'), formatted)
    : __('No sync recorded yet', 'alt-context');

  return (
    <div className={`acx-sync-status${data.is_stale ? ' acx-sync-status--warning' : ''}`}>
      <span className="acx-sync-status__label">{label}</span>
      {data.is_stale ? (
        <>
          <span className="acx-sync-status__badge">{__('Stale', 'alt-context')}</span>
          <button
            type="button"
            className="button button-link"
            onClick={() => syncTrigger.mutate()}
            disabled={syncTrigger.isPending}
          >
            {__('Sync now', 'alt-context')}
          </button>
        </>
      ) : (
        <span className="acx-sync-status__badge acx-sync-status__badge--ok">{__('Fresh', 'alt-context')}</span>
      )}
      {curationDetails}
    </div>
  );
};
