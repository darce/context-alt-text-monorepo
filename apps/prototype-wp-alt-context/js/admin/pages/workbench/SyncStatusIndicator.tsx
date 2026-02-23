import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import { useSyncStatus } from '../../hooks/useSyncStatus';
import { useSyncTrigger } from '../../hooks/useSyncTrigger';

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

export const SyncStatusIndicator = (): React.JSX.Element | null => {
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

  // Show syncing state while trigger is in progress and stale.
  if (data.is_stale && syncTrigger.isPending) {
    return (
      <div className="acx-sync-status acx-sync-status--syncing">
        <span className="acx-sync-status__label">{__('Syncing…', 'alt-context')}</span>
        <span className="acx-sync-status__badge">{__('In Progress', 'alt-context')}</span>
      </div>
    );
  }

  // Sync succeeded but no clusters exist yet — show informational state.
  if (syncTrigger.isSuccess && syncTrigger.data?.synced && syncTrigger.data.reason === 'no_remote_data') {
    return (
      <div className="acx-sync-status acx-sync-status--info">
        <span className="acx-sync-status__label">{__('Service connected — no clusters yet', 'alt-context')}</span>
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
    </div>
  );
};
