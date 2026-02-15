import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import { useSyncStatus } from '../../hooks/useSyncStatus';

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

  const formatted = formatTimestamp(data.last_synced_at);
  const label = formatted
    ? sprintf(__('Last sync: %s', 'alt-context'), formatted)
    : __('No sync recorded yet', 'alt-context');

  return (
    <div className={`acx-sync-status${data.is_stale ? ' acx-sync-status--warning' : ''}`}>
      <span className="acx-sync-status__label">{label}</span>
      {data.is_stale ? (
        <span className="acx-sync-status__badge">{__('Stale', 'alt-context')}</span>
      ) : (
        <span className="acx-sync-status__badge acx-sync-status__badge--ok">{__('Fresh', 'alt-context')}</span>
      )}
    </div>
  );
};
