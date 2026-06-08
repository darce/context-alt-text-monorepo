import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import type { JobStatusResponse } from '../../api/recognition/types/scan';
import type { RecognitionActivityItem, RecognitionHistorySource } from '../../hooks/recognitionJobHistoryUtils';

interface DashboardRecentActivitySectionProps {
  historySource: RecognitionHistorySource;
  recentActivity: RecognitionActivityItem[];
  jobStatuses: Record<string, string>;
  jobDetails: Record<string, JobStatusResponse>;
}

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
    return sprintf(__('Duration: %ds', 'alt-context'), seconds);
  }

  return sprintf(__('Duration: %dm %ss', 'alt-context'), minutes, String(seconds).padStart(2, '0'));
};

export const DashboardRecentActivitySection = ({
  historySource,
  recentActivity,
  jobStatuses,
  jobDetails,
}: DashboardRecentActivitySectionProps): React.JSX.Element => (
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
);
