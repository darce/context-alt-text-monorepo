import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import type { SyncHealth, SyncHealthResponse } from '../../api/recognition/types/sync';
import { getDashboardSyncHealthSummary } from '../workbench/degradedModeBannerLogic';
import { SCAN_CONFLICTS_HREF, SCAN_DEAD_LETTER_HREF } from '../workbench/workbenchOverlayLinks';

interface SyncStatusData {
  last_snapshot_version?: number | null;
}

interface DashboardSyncHealthSectionProps {
  isLoading: boolean;
  isError: boolean;
  syncStatus: SyncStatusData | null | undefined;
  effectiveSyncHealth: SyncHealth;
  syncHealthEnvelope: SyncHealthResponse | null | undefined;
  localClusterCount: number;
  showMirrorDivergenceBanner: boolean;
  pendingReplayCount: number;
  conflictCount: number;
  failedReplayCount: number;
  topologyPending: number;
  topologyFailed: number;
  topologyConflicts: number;
  lastConflictDate: string | null;
  lastFailureDate: string | null;
  resetPending: boolean;
  onResetMirror: () => void;
}

export const DashboardSyncHealthSection = ({
  isLoading,
  isError,
  syncStatus,
  effectiveSyncHealth,
  syncHealthEnvelope,
  localClusterCount,
  showMirrorDivergenceBanner,
  pendingReplayCount,
  conflictCount,
  failedReplayCount,
  topologyPending,
  topologyFailed,
  topologyConflicts,
  lastConflictDate,
  lastFailureDate,
  resetPending,
  onResetMirror,
}: DashboardSyncHealthSectionProps): React.JSX.Element => (
  <section className="acx-dashboard__panel">
    <h2>{__('Sync Health', 'alt-context')}</h2>
    {isLoading ? (
      <p>{__('Loading sync health…', 'alt-context')}</p>
    ) : isError || !syncStatus ? (
      <p>{__('Sync health is unavailable right now.', 'alt-context')}</p>
    ) : (
      <>
        {showMirrorDivergenceBanner ? (
          <div className="acx-dashboard__mirror-warning" role="status">
            <p>
              {sprintf(
                __(
                  'Mirror is out of sync with the backend — %1$d stale clusters, %2$d failed sync events.',
                  'alt-context',
                ),
                localClusterCount,
                failedReplayCount,
              )}
            </p>
            <button
              type="button"
              className="acx-button acx-button--secondary"
              disabled={resetPending}
              onClick={onResetMirror}
            >
              {resetPending ? __('Resetting…', 'alt-context') : __('Reset mirror', 'alt-context')}
            </button>
          </div>
        ) : null}
        <p>{getDashboardSyncHealthSummary(effectiveSyncHealth, syncHealthEnvelope)}</p>
        <div className="acx-dashboard__stats-grid">
          <div className="acx-dashboard__stat">
            <span className="acx-dashboard__stat-value">{pendingReplayCount}</span>
            <span className="acx-dashboard__stat-label">{__('Pending Replay', 'alt-context')}</span>
          </div>
          <div className="acx-dashboard__stat">
            <span className="acx-dashboard__stat-value">{conflictCount}</span>
            <span className="acx-dashboard__stat-label">{__('Conflicts', 'alt-context')}</span>
          </div>
          <div className="acx-dashboard__stat">
            <span className="acx-dashboard__stat-value">{failedReplayCount}</span>
            <span className="acx-dashboard__stat-label">{__('Failed Replay', 'alt-context')}</span>
          </div>
        </div>
        {topologyPending > 0 || topologyFailed > 0 || topologyConflicts > 0 ? (
          <p>
            {sprintf(
              __('Topology backlog: pending %1$d, failed %2$d, conflicts %3$d', 'alt-context'),
              topologyPending,
              topologyFailed,
              topologyConflicts,
            )}
          </p>
        ) : null}
        {conflictCount > 0 && lastConflictDate ? (
          <p>{sprintf(__('Last conflict: %s', 'alt-context'), lastConflictDate)}</p>
        ) : null}
        {failedReplayCount > 0 && lastFailureDate ? (
          <p>{sprintf(__('Last failure: %s', 'alt-context'), lastFailureDate)}</p>
        ) : null}
        <div className="acx-dashboard__actions">
          <a href="#/workbench?tab=scan" className="acx-dashboard__action-card">
            <h3>{__('Open Workbench', 'alt-context')}</h3>
            <p>{__('Inspect sync status, scans, and queued replay work.', 'alt-context')}</p>
          </a>
          {conflictCount > 0 ? (
            <a href={SCAN_CONFLICTS_HREF} className="acx-dashboard__action-card">
              <h3>{__('Open Conflict Inbox', 'alt-context')}</h3>
              <p>{__('Review and resolve recorded sync conflicts.', 'alt-context')}</p>
            </a>
          ) : null}
          {failedReplayCount > 0 ? (
            <a href={SCAN_DEAD_LETTER_HREF} className="acx-dashboard__action-card">
              <h3>{__('Open Dead-Letter Queue', 'alt-context')}</h3>
              <p>{__('Retry or discard failed replay operations.', 'alt-context')}</p>
            </a>
          ) : null}
        </div>
      </>
    )}
  </section>
);
