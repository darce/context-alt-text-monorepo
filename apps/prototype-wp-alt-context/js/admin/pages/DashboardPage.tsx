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
import { rosterClustersUrl } from './workbench/Panels';
import { sprintf } from '@wordpress/i18n';
import { OrientationCard } from './dashboard/OrientationCard';


export const DashboardPage = (): React.JSX.Element => {
  const { stats, isLoading: isStatsLoading } = useMediaStats();
  const { jobHistory, jobStatuses, jobDetails } = useRecognitionJobHistory();
  const { data: identityStats, isLoading: isIdentityLoading } = useIdentityStats();

  const coveragePercent = Math.round(stats.coverage);
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
          {isIdentityLoading || !identityStats ? (
            <p>{__('Loading identity stats…', 'alt-context')}</p>
          ) : (
            <>
              <div className="acx-dashboard__stats-grid">
                <div className="acx-dashboard__stat">
                  <span className="acx-dashboard__stat-value">{identityStats.people_count}</span>
                  <span className="acx-dashboard__stat-label" title={__('Total unique persons created in your roster.', 'alt-context')}>
                    {__('People', 'alt-context')}
                  </span>
                </div>
                <div className="acx-dashboard__stat">
                  <span className="acx-dashboard__stat-value">
                    {identityStats.assigned_clusters_count}
                  </span>
                  <span className="acx-dashboard__stat-label" title={__('Clusters that have been matched to a person.', 'alt-context')}>
                    {__('Assigned', 'alt-context')}
                  </span>
                </div>
                <div className="acx-dashboard__stat acx-dashboard__stat--highlight">
                  <span className="acx-dashboard__stat-value">
                    {identityStats.pending_clusters_count}
                  </span>
                  <span className="acx-dashboard__stat-label" title={__('New clusters waiting for your review and labeling.', 'alt-context')}>
                    {__('Pending Review', 'alt-context')}
                  </span>
                </div>

              </div>
              <div className="acx-dashboard__guidance">
                {identityStats.pending_clusters_count > 0 ? (
                  <>
                    <p>
                      {sprintf(
                        /* translators: %d: number of pending clusters */
                        __('%d faces are waiting for names.', 'alt-context'),
                        identityStats.pending_clusters_count
                      )}
                    </p>
                    <a href="#/workbench?tab=confirm" className="acx-link-button">
                      {__('Go to Workbench', 'alt-context')}
                    </a>
                  </>
                ) : identityStats.people_count === 0 ? (
                  <>
                    <p>{__('Start by scanning your media library for faces.', 'alt-context')}</p>
                    <a href="#/workbench?tab=scan" className="acx-link-button">
                      {__('Go to Scan tab', 'alt-context')}
                    </a>
                  </>
                ) : (
                  <p>{__('All caught up. New faces will appear here for review.', 'alt-context')}</p>
                )}
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
                const durationLabel = formatDuration(jobDetails[id]?.started_at ?? '', jobDetails[id]?.finished_at ?? null);
                return (
                  <li key={id} className="acx-dashboard__activity-item">
                    <span className="acx-dashboard__activity-id">{id}</span>
                    <span className="acx-dashboard__activity-status">
                      {jobStatuses[id] ?? __('Checking status…', 'alt-context')}
                    </span>
                    {durationLabel && (
                      <span className="acx-dashboard__activity-duration">{durationLabel}</span>
                    )}
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
