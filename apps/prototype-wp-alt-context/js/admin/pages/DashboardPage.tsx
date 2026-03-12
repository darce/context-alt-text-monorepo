import React from 'react';
import { __ } from '@wordpress/i18n';

/**
 * Dashboard landing page for the Alt Context admin SPA.
 *
 * Displays a hero section with contextual copy so the React bundle
 * immediately communicates that it has mounted correctly inside wp-admin.
 */
import { useMediaStats } from '../hooks/useMediaStats';
import { useRecognitionJobHistory } from '../hooks/useRecognitionJobHistory';
import { useIdentityStats } from '../hooks/useIdentityStats';
import { useSyncStatus } from '../hooks/useSyncStatus';
import { useRetentionStatus } from '../hooks/useRetentionStatus';
import { rosterClustersUrl } from './workbench/Panels';
import { sprintf } from '@wordpress/i18n';
import { OrientationCard } from './dashboard/OrientationCard';
import { GuidanceCard } from './dashboard/GuidanceCard';

const normalizeCount = (value: number | null | undefined): number => {
  if (typeof value !== 'number' || Number.isNaN(value) || value <= 0) {
    return 0;
  }

  return Math.floor(value);
};

export const DashboardPage = (): React.JSX.Element => {
  const { stats, isLoading: isStatsLoading } = useMediaStats();
  const { jobHistory, jobStatuses, jobDetails } = useRecognitionJobHistory();
  const { data: syncStatus, isLoading: isSyncStatusLoading, isError: isSyncStatusError } = useSyncStatus();
  const { data: retentionStatus } = useRetentionStatus();
  const {
    data: identityStats,
    isLoading: isIdentityLoading,
    isError: isIdentityError,
    refetch: refetchIdentity,
  } = useIdentityStats();

  const coveragePercent = Math.round(stats.coverage);
  const pendingReplayCount = normalizeCount(syncStatus?.pending_curation_operations);
  const conflictCount = normalizeCount(syncStatus?.conflict_count);
  const failedReplayCount = normalizeCount(syncStatus?.failed_curation_operations);
  const topologyPending = normalizeCount(syncStatus?.topology_commands?.pending);
  const topologyFailed = normalizeCount(syncStatus?.topology_commands?.failed);
  const topologyConflicts = normalizeCount(syncStatus?.topology_commands?.conflict);
  const retentionPolicy = retentionStatus?.available ? retentionStatus.policy : null;
  const retentionModeLabel =
    retentionPolicy?.retention_mode === 'dispose_after_ack'
      ? __('Dispose after ack', 'alt-context')
      : retentionPolicy?.retention_mode === 'purge_on_demand'
        ? __('Purge on demand', 'alt-context')
        : __('Retain all', 'alt-context');
  const formatDuration = (startedAt: string, finishedAt: string | null): string | null => {
    if (!startedAt || !finishedAt) {
      return null;
    }
    const started = new Date(startedAt).getTime();
    const finished = new Date(finishedAt).getTime();
    if (!Number.isFinite(started) || !Number.isFinite(finished) || finished <= started) {
      return null;
    }
    const totalSeconds = Math.round((finished - started) / 1000);
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    if (minutes <= 0) {
      return sprintf(
        /* translators: %d: duration in seconds */
        __('Duration: %ds', 'alt-context'),
        seconds,
      );
    }
    const paddedSeconds = String(seconds).padStart(2, '0');
    return sprintf(
      /* translators: 1: duration minutes, 2: duration seconds */
      __('Duration: %dm %ss', 'alt-context'),
      minutes,
      paddedSeconds,
    );
  };

  return (
    <section className="acx-dashboard__shell" aria-labelledby="acx-dashboard-title">
      <header className="acx-dashboard__hero">
        <p className="acx-dashboard__eyebrow">{__('Alt Context', 'alt-context')}</p>
        <h1 id="acx-dashboard-title" className="acx-dashboard__title">
          {__('Alt Context Dashboard', 'alt-context')}
        </h1>
        <p className="acx-dashboard__subtitle">
          {__('Monitor your library coverage and manage identity recognition jobs.', 'alt-context')}
        </p>
      </header>

      <OrientationCard />

      <div className="acx-dashboard__grid">
        <section className="acx-dashboard__panel acx-dashboard__panel--stats">
          <h2>{__('Library Coverage', 'alt-context')}</h2>
          {isStatsLoading ? (
            <p>{__('Loading coverage insights…', 'alt-context')}</p>
          ) : (
            <div className="acx-dashboard__stats-grid">
              <div className="acx-dashboard__stat">
                <span className="acx-dashboard__stat-value">{stats.total}</span>
                <span className="acx-dashboard__stat-label">{__('Total Media', 'alt-context')}</span>
              </div>
              <div className="acx-dashboard__stat">
                <span className="acx-dashboard__stat-value">{stats.missing}</span>
                <span className="acx-dashboard__stat-label">{__('Missing Alt Text', 'alt-context')}</span>
              </div>
              <div className="acx-dashboard__stat acx-dashboard__stat--highlight">
                <span className="acx-dashboard__stat-value">{coveragePercent}%</span>
                <span className="acx-dashboard__stat-label">{__('Coverage', 'alt-context')}</span>
              </div>
            </div>
          )}
          <progress
            className="acx-dashboard__progress"
            value={coveragePercent}
            max={100}
            aria-label={__('Alt text coverage', 'alt-context')}
          />
        </section>

        <section className="acx-dashboard__panel">
          <h2>{__('Identity Recognition', 'alt-context')}</h2>
          {isIdentityLoading ? (
            <p>{__('Loading identity stats…', 'alt-context')}</p>
          ) : isIdentityError ? (
            <div className="acx-error-state">
              <p>{__('Unable to load identity stats.', 'alt-context')}</p>
              <button type="button" className="acx-button acx-button--secondary" onClick={() => void refetchIdentity()}>
                {__('Retry', 'alt-context')}
              </button>
            </div>
          ) : !identityStats ? (
            <p>{__('Unable to load identity stats.', 'alt-context')}</p>
          ) : (
            <>
              <div className="acx-dashboard__stats-grid">
                <div className="acx-dashboard__stat">
                  <span className="acx-dashboard__stat-value">{identityStats.people_count}</span>
                  <span
                    className="acx-dashboard__stat-label"
                    title={__('Total unique persons created in your roster.', 'alt-context')}
                  >
                    {__('People', 'alt-context')}
                  </span>
                </div>
                <div className="acx-dashboard__stat">
                  <span className="acx-dashboard__stat-value">{identityStats.assigned_clusters_count}</span>
                  <span
                    className="acx-dashboard__stat-label"
                    title={__('Clusters that have been matched to a person.', 'alt-context')}
                  >
                    {__('Assigned', 'alt-context')}
                  </span>
                </div>
                <div className="acx-dashboard__stat acx-dashboard__stat--highlight">
                  <span className="acx-dashboard__stat-value">{identityStats.pending_clusters_count}</span>
                  <span
                    className="acx-dashboard__stat-label"
                    title={__('New clusters waiting for your review and labeling.', 'alt-context')}
                  >
                    {__('Pending Review', 'alt-context')}
                  </span>
                </div>
                <div className="acx-dashboard__stat">
                  <span className="acx-dashboard__stat-value">{identityStats.media_with_faces_count}</span>
                  <span
                    className="acx-dashboard__stat-label"
                    title={__('Media items that have at least one detected face.', 'alt-context')}
                  >
                    {__('Media with faces', 'alt-context')}
                  </span>
                </div>
              </div>
              <div className="acx-dashboard__guidance">
                <GuidanceCard stats={identityStats} />
              </div>
            </>
          )}
        </section>

        <section className="acx-dashboard__panel">
          <h2>{__('Sync Health', 'alt-context')}</h2>
          {isSyncStatusLoading ? (
            <p>{__('Loading sync health…', 'alt-context')}</p>
          ) : isSyncStatusError || !syncStatus ? (
            <p>{__('Sync health is unavailable right now.', 'alt-context')}</p>
          ) : (
            <>
              <p>
                {syncStatus.sync_health === 'healthy'
                  ? __('Machine sync is healthy and curation replay is caught up.', 'alt-context')
                  : syncStatus.sync_health === 'queued'
                    ? __('Local curation changes are queued for replay.', 'alt-context')
                    : syncStatus.sync_health === 'conflicts'
                      ? __('Conflict resolution is blocking part of the replay queue.', 'alt-context')
                      : syncStatus.sync_health === 'failures'
                        ? __('Some replay operations failed and need operator attention.', 'alt-context')
                        : syncStatus.sync_health === 'offline'
                          ? __('The recognition backend is currently unreachable.', 'alt-context')
                          : __('Machine state is stale and should be refreshed.', 'alt-context')}
              </p>
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
              <div className="acx-dashboard__actions">
                <a href="#/workbench?tab=scan" className="acx-dashboard__action-card">
                  <h3>{__('Open Workbench', 'alt-context')}</h3>
                  <p>{__('Inspect sync status, scans, and queued replay work.', 'alt-context')}</p>
                </a>
                {conflictCount > 0 ? (
                  <a href="#/workbench?tab=scan&panel=conflicts" className="acx-dashboard__action-card">
                    <h3>{__('Open Conflict Inbox', 'alt-context')}</h3>
                    <p>{__('Review and resolve recorded sync conflicts.', 'alt-context')}</p>
                  </a>
                ) : null}
                {failedReplayCount > 0 ? (
                  <a href="#/workbench?tab=scan&panel=dead-letter" className="acx-dashboard__action-card">
                    <h3>{__('Open Dead-Letter Queue', 'alt-context')}</h3>
                    <p>{__('Retry or discard failed replay operations.', 'alt-context')}</p>
                  </a>
                ) : null}
              </div>
            </>
          )}
        </section>

        <section className="acx-dashboard__panel">
          <h2>{__('Retention posture', 'alt-context')}</h2>
          {!retentionPolicy ? (
            <p>{__('Retention status is unavailable right now.', 'alt-context')}</p>
          ) : (
            <>
              <div className="acx-dashboard__stats-grid">
                <div className="acx-dashboard__stat">
                  <span className="acx-dashboard__stat-value acx-dashboard__stat-value--compact">{retentionModeLabel}</span>
                  <span className="acx-dashboard__stat-label">{__('Current Mode', 'alt-context')}</span>
                </div>
                <div className="acx-dashboard__stat">
                  <span className="acx-dashboard__stat-value acx-dashboard__stat-value--compact">
                    {retentionPolicy.last_export_at ? new Date(retentionPolicy.last_export_at).toLocaleDateString() : __('Never', 'alt-context')}
                  </span>
                  <span className="acx-dashboard__stat-label">{__('Last Export', 'alt-context')}</span>
                </div>
                <div className="acx-dashboard__stat">
                  <span className="acx-dashboard__stat-value acx-dashboard__stat-value--compact">
                    {retentionPolicy.last_purge_at ? new Date(retentionPolicy.last_purge_at).toLocaleDateString() : __('Never', 'alt-context')}
                  </span>
                  <span className="acx-dashboard__stat-label">{__('Last Purge', 'alt-context')}</span>
                </div>
              </div>
              <div className="acx-dashboard__actions">
                <a href="#/retention" className="acx-dashboard__action-card">
                  <h3>{__('Open Retention Controls', 'alt-context')}</h3>
                  <p>{__('Review policy, run exports, and inspect recent audit events.', 'alt-context')}</p>
                </a>
              </div>
            </>
          )}
        </section>

        <section className="acx-dashboard__panel">
          <h2>{__('Quick Actions', 'alt-context')}</h2>
          <div className="acx-dashboard__actions">
            <a href="#/workbench?tab=scan" className="acx-dashboard__action-card">
              <h3>{__('Analysis Queue', 'alt-context')}</h3>
              <p>{__('Scan your library for faces and identities.', 'alt-context')}</p>
            </a>
            <a href="#/workbench?tab=confirm" className="acx-dashboard__action-card">
              <h3>{__('Review Hub', 'alt-context')}</h3>
              <p>{__('Cluster detected embeddings into known identities.', 'alt-context')}</p>
            </a>
            <a href={rosterClustersUrl()} className="acx-dashboard__action-card">
              <h3>{__('Managed Identities', 'alt-context')}</h3>
              <p>{__('View and merge identity clusters in the roster.', 'alt-context')}</p>
            </a>
          </div>
        </section>

        <section className="acx-dashboard__panel">
          <h2>{__('Recent Activity', 'alt-context')}</h2>
          {jobHistory.length === 0 ? (
            <p>{__('No recent recognition jobs found.', 'alt-context')}</p>
          ) : (
            <ul className="acx-dashboard__activity-list">
              {jobHistory.map((id) => {
                const jobDetail = jobDetails[id];
                const statusLabel = jobDetail
                  ? (jobStatuses[id] ?? __('Checking status…', 'alt-context'))
                  : __('Status unavailable. Refresh to retry.', 'alt-context');
                const durationLabel = formatDuration(jobDetail?.started_at ?? '', jobDetail?.finished_at ?? null);
                return (
                  <li key={id} className="acx-dashboard__activity-item">
                    <span className="acx-dashboard__activity-id">{id}</span>
                    <span className="acx-dashboard__activity-status">{statusLabel}</span>
                    {durationLabel && <span className="acx-dashboard__activity-duration">{durationLabel}</span>}
                    <a href={`#/workbench?tab=confirm&jobId=${id}`} className="acx-link-button">
                      {__('View Results', 'alt-context')}
                    </a>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>
    </section>
  );
};
