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
import { useResetMirror } from '../hooks/useSyncTrigger';
import { useSyncHealth } from '../hooks/useSyncHealth';
import { useSyncStatus } from '../hooks/useSyncStatus';
import { hasSyncHealthWarnings, resolveEffectiveSyncHealth } from './workbench/degradedModeBannerLogic';
import { useRetentionStatus } from '../hooks/useRetentionStatus';
import { GuidanceCard } from './dashboard/GuidanceCard';
import { DashboardRecentActivitySection } from './dashboard/DashboardRecentActivitySection';
import { DashboardSyncHealthSection } from './dashboard/DashboardSyncHealthSection';
import { OrientationCard } from './dashboard/OrientationCard';
import { buildDashboardPriorityModel, type DashboardSectionId } from './dashboard/buildDashboardPriorityModel';
import {
  RETENTION_CARD_ACTION_BODY,
  RETENTION_CARD_ACTION_HEADING,
  RETENTION_CARD_ERROR_BODY,
  RETENTION_CARD_HEADING,
  RETENTION_CARD_LINK_HREF,
} from './dashboard/retentionCardCopy';
import { toWorkbench } from '../navigation/appLinks';

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
  return Number.isNaN(date.getTime()) ? null : date.toLocaleDateString();
};

export const DashboardPage = (): React.JSX.Element => {
  const { stats, isLoading: isStatsLoading } = useMediaStats();
  const {
    jobStatuses,
    jobDetails,
    recentActivity = [],
    historySource = 'unavailable',
  } = useRecognitionJobHistory();
  const { data: syncStatus, isLoading: isSyncStatusLoading, isError: isSyncStatusError } = useSyncStatus();
  const { data: syncHealthEnvelope } = useSyncHealth();
  const effectiveSyncHealth = resolveEffectiveSyncHealth(syncStatus?.sync_health ?? 'stale', syncHealthEnvelope);
  const syncHealthWarningsActive = syncHealthEnvelope ? hasSyncHealthWarnings(syncHealthEnvelope) : false;
  const resetMirror = useResetMirror();
  const { data: retentionStatus, isError: isRetentionError, isLoading: isRetentionLoading } =
    useRetentionStatus();
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
  const localClusterCount =
    normalizeCount(identityStats?.assigned_clusters_count) + normalizeCount(identityStats?.pending_clusters_count);
  const showMirrorDivergenceBanner = Boolean(syncStatus?.last_snapshot_version === 0 && localClusterCount > 0);
  const topologyPending = normalizeCount(syncStatus?.topology_commands?.pending);
  const topologyFailed = normalizeCount(syncStatus?.topology_commands?.failed);
  const topologyConflicts = normalizeCount(syncStatus?.topology_commands?.conflict);
  const lastConflictDate = formatDiagnosticDate(syncStatus?.last_curation_conflict_at);
  const lastFailureDate = formatDiagnosticDate(syncStatus?.last_curation_failed_at);
  // State matrix (UXP-4 S3 / A11Y-24): loading or available:false → no panel;
  // isError → remediation + #/retention; available + policy → summary.
  const retentionPolicy = retentionStatus?.available ? retentionStatus.policy : null;
  const showRetentionPanel =
    !isRetentionLoading && (isRetentionError || Boolean(retentionPolicy));
  const retentionModeLabel =
    retentionPolicy?.retention_mode === 'dispose_after_ack'
      ? __('Dispose after ack', 'alt-context')
      : retentionPolicy?.retention_mode === 'purge_on_demand'
        ? __('Purge on demand', 'alt-context')
        : __('Retain all', 'alt-context');

  const priorityModel = buildDashboardPriorityModel({
    isSyncStatusLoading,
    isSyncStatusError,
    effectiveSyncHealth,
    hasSyncHealthWarnings: syncHealthWarningsActive,
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

  const gridSections: Record<DashboardSectionId, React.JSX.Element> = {
    syncHealth: (
      <DashboardSyncHealthSection
        isLoading={isSyncStatusLoading}
        isError={isSyncStatusError}
        syncStatus={syncStatus}
        effectiveSyncHealth={effectiveSyncHealth}
        syncHealthEnvelope={syncHealthEnvelope}
        localClusterCount={localClusterCount}
        showMirrorDivergenceBanner={showMirrorDivergenceBanner}
        pendingReplayCount={pendingReplayCount}
        conflictCount={conflictCount}
        failedReplayCount={failedReplayCount}
        topologyPending={topologyPending}
        topologyFailed={topologyFailed}
        topologyConflicts={topologyConflicts}
        lastConflictDate={lastConflictDate}
        lastFailureDate={lastFailureDate}
        resetPending={resetMirror.isPending}
        onResetMirror={() => resetMirror.mutate()}
      />
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
                  title={__('Total unique people identified in your media library.', 'alt-context')}
                >
                  {__('People', 'alt-context')}
                </span>
              </div>
              <div className="acx-dashboard__stat">
                <span className="acx-dashboard__stat-value">{identityStats.assigned_clusters_count}</span>
                <span
                  className="acx-dashboard__stat-label"
                  title={__('Face groups that have been matched to a person.', 'alt-context')}
                >
                  {__('Assigned', 'alt-context')}
                </span>
              </div>
              <div className="acx-dashboard__stat acx-dashboard__stat--highlight">
                <span className="acx-dashboard__stat-value">{identityStats.pending_clusters_count}</span>
                <span
                  className="acx-dashboard__stat-label"
                  title={__('New face groups waiting for your review and labeling.', 'alt-context')}
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
        <div className="acx-dashboard__actions">
          <a href={toWorkbench({ status: 'missing' })} className="acx-button acx-button--primary">
            {__('Fix missing descriptions', 'alt-context')}
          </a>
        </div>
      </section>
    ),
    recentActivity: (
      <DashboardRecentActivitySection
        historySource={historySource}
        recentActivity={recentActivity}
        jobStatuses={jobStatuses}
        jobDetails={jobDetails}
      />
    ),
    retentionPosture: showRetentionPanel ? (
      <section className="acx-dashboard__panel">
        <h2>{RETENTION_CARD_HEADING}</h2>
        {isRetentionError || !retentionPolicy ? (
          <>
            <p>{RETENTION_CARD_ERROR_BODY}</p>
            <div className="acx-dashboard__actions">
              <a href={RETENTION_CARD_LINK_HREF} className="acx-dashboard__action-card">
                <h3>{RETENTION_CARD_ACTION_HEADING}</h3>
                <p>{RETENTION_CARD_ACTION_BODY}</p>
              </a>
            </div>
          </>
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
              <a href={RETENTION_CARD_LINK_HREF} className="acx-dashboard__action-card">
                <h3>{RETENTION_CARD_ACTION_HEADING}</h3>
                <p>{RETENTION_CARD_ACTION_BODY}</p>
              </a>
            </div>
          </>
        )}
      </section>
    ) : (
      // loading / available:false — absent from initial render (no focus/live-region work)
      <></>
    ),
  };

  return (
    <section className="acx-dashboard__shell" aria-labelledby="acx-dashboard-title">
      <header className="acx-dashboard__hero">
        <p className="acx-dashboard__eyebrow">{__('Alt Context', 'alt-context')}</p>
        <h1 id="acx-dashboard-title" className="acx-dashboard__title">
          {__('Alt Context Overview', 'alt-context')}
        </h1>
        <p className="acx-dashboard__subtitle">
          {__('It finds the people in your media library and writes alt text that names them.', 'alt-context')}
        </p>
      </header>

      <div className="acx-dashboard__grid">
        {priorityModel.gridSectionOrder.map((sectionId) => (
          <React.Fragment key={sectionId}>{gridSections[sectionId]}</React.Fragment>
        ))}
      </div>

      {priorityModel.orientationPosition === 'after_grid' && identityStats ? (
        <OrientationCard peopleCount={identityStats.people_count} />
      ) : null}
    </section>
  );
};
