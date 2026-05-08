import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

/**
 * Dashboard landing page for the Alt Context admin SPA.
 *
 * Displays a hero section with contextual copy so the React bundle
 * immediately communicates that it has mounted correctly inside wp-admin.
 */
import { useMediaStats } from '../hooks/useMediaStats';
import { useRecognitionJobHistory } from '../hooks/useRecognitionJobHistory';
import { useIdentityStats } from '../hooks/useIdentityStats';
import { useResetMirror } from '../hooks/useSyncTrigger';
import { useSyncStatus } from '../hooks/useSyncStatus';
import { useRetentionStatus } from '../hooks/useRetentionStatus';
import { GuidanceCard } from './dashboard/GuidanceCard';
import { OrientationCard } from './dashboard/OrientationCard';
import { buildDashboardPriorityModel, type DashboardSectionId } from './dashboard/buildDashboardPriorityModel';
import { rosterClustersUrl } from './workbench/Panels';

const normalizeCount = (value: number | null | undefined): number => {
  if (typeof value !== 'number' || Number.isNaN(value) || value <= 0) {
    return 0;
  }

  return Math.floor(value);
};

const formatDiagnosticDate = (value: string | null | undefined): string | null => {
  if (!value) {
    return null;
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }

  return date.toLocaleDateString();
};

export const DashboardPage = (): React.JSX.Element => {
  const { stats, isLoading: isStatsLoading } = useMediaStats();
  const {
    jobHistory,
    jobStatuses,
    jobDetails,
    recentActivity = [],
    historySource = 'unavailable',
  } = useRecognitionJobHistory();
  const { data: syncStatus, isLoading: isSyncStatusLoading, isError: isSyncStatusError } = useSyncStatus();
  const resetMirror = useResetMirror();
  const { data: retentionStatus } = useRetentionStatus();
  const {
    data: identityStats,
    isLoading: isIdentityLoading,
    isError: isIdentityError,
    refetch: refetchIdentity,
  } = useIdentityStats();

  const coveragePercent = Math.round(stats.coverage);
  const latestRecognitionJobId = recentActivity.find((item) => item.jobId)?.jobId ?? jobHistory[0] ?? null;
  const latestRecognitionJobStatus = latestRecognitionJobId ? jobStatuses[latestRecognitionJobId] : null;
  const pendingReplayCount = normalizeCount(syncStatus?.pending_curation_operations);
  const conflictCount = normalizeCount(syncStatus?.conflict_count);
  const failedReplayCount = normalizeCount(syncStatus?.failed_curation_operations);
  const localClusterCount =
    normalizeCount(identityStats?.assigned_clusters_count) + normalizeCount(identityStats?.pending_clusters_count);
  const showMirrorDivergenceBanner = Boolean(syncStatus?.last_snapshot_version === 0 && localClusterCount > 0);
  const topologyPending = normalizeCount(syncStatus?.topology_commands?.pending);
  const topologyFailed = normalizeCount(syncStatus?.topology_commands?.failed);
  const topologyConflicts = normalizeCount(syncStatus?.topology_commands?.conflict);
  const lastConflictDate = formatDiagnosticDate(syncStatus?.last_curation_conflict_at);
  const lastFailureDate = formatDiagnosticDate(syncStatus?.last_curation_failed_at);
  const retentionPolicy = retentionStatus?.available ? retentionStatus.policy : null;
  const retentionModeLabel =
    retentionPolicy?.retention_mode === 'dispose_after_ack'
      ? __('Dispose after ack', 'alt-context')
      : retentionPolicy?.retention_mode === 'purge_on_demand'
        ? __('Purge on demand', 'alt-context')
        : __('Retain all', 'alt-context');

  const priorityModel = buildDashboardPriorityModel({
    isSyncStatusLoading,
    isSyncStatusError,
    syncHealth: syncStatus?.sync_health ?? null,
    pendingReplayCount,
    conflictCount,
    failedReplayCount,
    topologyPending,
    topologyFailed,
    topologyConflicts,
    showMirrorDivergenceBanner,
    isIdentityLoading,
    isIdentityError,
    hasIdentityStats: Boolean(identityStats),
    pendingClustersCount: normalizeCount(identityStats?.pending_clusters_count),
    unassignedPersonsCount: normalizeCount(identityStats?.unassigned_persons_count),
  });

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

  const gridSections: Record<DashboardSectionId, React.JSX.Element> = {
    syncHealth: (
      <section className="acx-dashboard__panel">
        <h2>{__('Sync Health', 'alt-context')}</h2>
        {isSyncStatusLoading ? (
          <p>{__('Loading sync health…', 'alt-context')}</p>
        ) : isSyncStatusError || !syncStatus ? (
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
                  disabled={resetMirror.isPending}
                  onClick={() => resetMirror.mutate()}
                >
                  {resetMirror.isPending ? __('Resetting…', 'alt-context') : __('Reset mirror', 'alt-context')}
                </button>
              </div>
            ) : null}
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
    ),
    identityRecognition: (
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
    ),
    libraryCoverage: (
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
    ),
    recentActivity: (
      <section className="acx-dashboard__panel">
        <h2>{__('Recent Activity', 'alt-context')}</h2>
        {historySource === 'browser_local_fallback' ? (
          <p>{__('Showing jobs remembered in this browser only.', 'alt-context')}</p>
        ) : null}
        {historySource === 'unavailable' && recentActivity.length === 0 ? (
          <p>{__('Durable recent activity is unavailable right now.', 'alt-context')}</p>
        ) : recentActivity.length === 0 ? (
          <p>{__('No recent recognition jobs found.', 'alt-context')}</p>
        ) : (
          <ul className="acx-dashboard__activity-list">
            {recentActivity.map((item) => {
              const jobDetail = item.jobId ? jobDetails[item.jobId] : undefined;
              const statusLabel = jobDetail
                ? item.jobId
                  ? (jobStatuses[item.jobId] ?? __('Checking status…', 'alt-context'))
                  : item.statusText
                : item.statusText;
              const durationLabel = formatDuration(jobDetail?.started_at ?? '', jobDetail?.finished_at ?? null);

              return (
                <li key={item.id} className="acx-dashboard__activity-item">
                  <span className="acx-dashboard__activity-id">{item.jobId ?? item.runId ?? item.id}</span>
                  <span className="acx-dashboard__activity-status">{statusLabel}</span>
                  <span className="acx-dashboard__activity-status">
                    {item.provenance === 'durable_batch_run'
                      ? sprintf(__('Durable batch run: %s', 'alt-context'), item.runId ?? __('Unknown', 'alt-context'))
                      : __('Current browser memory', 'alt-context')}
                  </span>
                  {durationLabel ? <span className="acx-dashboard__activity-duration">{durationLabel}</span> : null}
                  {item.jobId ? (
                    <a href={`#/workbench?tab=confirm&jobId=${item.jobId}`} className="acx-link-button">
                      {__('View Results', 'alt-context')}
                    </a>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </section>
    ),
    retentionPosture: (
      <section className="acx-dashboard__panel">
        <h2>{__('Retention posture', 'alt-context')}</h2>
        {!retentionPolicy ? (
          <p>{__('Retention status is unavailable right now.', 'alt-context')}</p>
        ) : (
          <>
            <div className="acx-dashboard__stats-grid">
              <div className="acx-dashboard__stat">
                <span className="acx-dashboard__stat-value acx-dashboard__stat-value--compact">
                  {retentionModeLabel}
                </span>
                <span className="acx-dashboard__stat-label">{__('Current Mode', 'alt-context')}</span>
              </div>
              <div className="acx-dashboard__stat">
                <span className="acx-dashboard__stat-value acx-dashboard__stat-value--compact">
                  {retentionPolicy.last_export_at
                    ? new Date(retentionPolicy.last_export_at).toLocaleDateString()
                    : __('Never', 'alt-context')}
                </span>
                <span className="acx-dashboard__stat-label">{__('Last Export', 'alt-context')}</span>
              </div>
              <div className="acx-dashboard__stat">
                <span className="acx-dashboard__stat-value acx-dashboard__stat-value--compact">
                  {retentionPolicy.last_purge_at
                    ? new Date(retentionPolicy.last_purge_at).toLocaleDateString()
                    : __('Never', 'alt-context')}
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
    ),
    batchOperations: (
      <section className="acx-dashboard__panel">
        <h2>{__('Batch Operations', 'alt-context')}</h2>
        <p>
          {__(
            'Start new recognition batches from Dashboard, then jump back into scan, review, or roster cleanup from the same landing page.',
            'alt-context',
          )}
        </p>
        {latestRecognitionJobId ? (
          <>
            <p>
              {sprintf(__('Most recent batch job: %s', 'alt-context'), latestRecognitionJobId)}{' '}
              <a href={`#/workbench?tab=confirm&jobId=${latestRecognitionJobId}`} className="acx-link-button">
                {__('View latest results', 'alt-context')}
              </a>
            </p>
            {latestRecognitionJobStatus ? (
              <p>{sprintf(__('Latest batch status: %s', 'alt-context'), latestRecognitionJobStatus)}</p>
            ) : null}
          </>
        ) : (
          <p>
            {__('No recent recognition batches yet. Start from the analysis queue when you are ready.', 'alt-context')}
          </p>
        )}
        <div className="acx-dashboard__actions">
          <a href="#/workbench?tab=scan" className="acx-dashboard__action-card">
            <h3>{__('Analysis Queue', 'alt-context')}</h3>
            <p>{__('Select media and launch a new recognition batch.', 'alt-context')}</p>
          </a>
          <a href="#/workbench?tab=confirm" className="acx-dashboard__action-card">
            <h3>{__('Review Hub', 'alt-context')}</h3>
            <p>{__('Inspect recent jobs and cluster the latest results.', 'alt-context')}</p>
          </a>
          <a href={rosterClustersUrl()} className="acx-dashboard__action-card">
            <h3>{__('Managed Identities', 'alt-context')}</h3>
            <p>{__('View and merge identity clusters in the roster.', 'alt-context')}</p>
          </a>
        </div>
      </section>
    ),
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

      {priorityModel.orientationPosition === 'before_grid' ? <OrientationCard /> : null}

      <div className="acx-dashboard__grid">
        {priorityModel.gridSectionOrder.map((sectionId) => (
          <React.Fragment key={sectionId}>{gridSections[sectionId]}</React.Fragment>
        ))}
      </div>

      {priorityModel.orientationPosition === 'after_grid' ? <OrientationCard /> : null}
    </section>
  );
};
