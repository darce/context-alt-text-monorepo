import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import type { JobStatusResponse } from '../../api/recognition/types/scan';
import type { RecognitionActivityItem, RecognitionHistorySource } from '../../hooks/recognitionJobHistoryUtils';
import { toWorkbench } from '../../navigation/appLinks';
import { EmptyState, EmptyStateVariant } from '../../components/ui/EmptyState';

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

const formatRelativeTime = (iso: string | null | undefined, nowMs: number = Date.now()): string | null => {
  if (!iso) {
    return null;
  }

  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) {
    return null;
  }

  const deltaSeconds = Math.max(0, Math.round((nowMs - then) / 1000));
  if (deltaSeconds < 60) {
    return __('just now', 'alt-context');
  }

  const minutes = Math.floor(deltaSeconds / 60);
  if (minutes < 60) {
    return sprintf(__('%d minutes ago', 'alt-context'), minutes);
  }

  const hours = Math.floor(minutes / 60);
  if (hours < 48) {
    return sprintf(__('%d hours ago', 'alt-context'), hours);
  }

  const days = Math.floor(hours / 24);
  return sprintf(__('%d days ago', 'alt-context'), days);
};

const verbForStatus = (status: string | null | undefined, fallbackStatusText: string): string => {
  const candidate = (status ?? fallbackStatusText).trim();
  const normalized = candidate.toLowerCase();
  if (normalized.includes('completed') || normalized === 'complete') {
    return __('Scan finished', 'alt-context');
  }
  if (normalized.includes('fail')) {
    return __('Scan failed', 'alt-context');
  }
  if (normalized.includes('cancel')) {
    return __('Scan cancelled', 'alt-context');
  }
  if (normalized.includes('run') || normalized.includes('progress') || normalized.includes('pending')) {
    return __('Scan in progress', 'alt-context');
  }
  // Keep summary verb short/human. Do not echo long status copy, sentences, or IDs.
  if (
    !candidate ||
    candidate.length > 32 ||
    candidate.includes('.') ||
    /[0-9a-f]{8}-[0-9a-f]{4}/i.test(candidate)
  ) {
    return __('Recognition job', 'alt-context');
  }
  return candidate;
};

const countLabelFromJob = (jobDetail: JobStatusResponse | undefined): string | null => {
  if (!jobDetail?.progress) {
    return null;
  }

  const images =
    typeof jobDetail.progress.images_processed === 'number' && jobDetail.progress.images_processed > 0
      ? jobDetail.progress.images_processed
      : typeof jobDetail.progress.total === 'number' && jobDetail.progress.total > 0
        ? jobDetail.progress.total
        : typeof jobDetail.progress.completed === 'number' && jobDetail.progress.completed > 0
          ? jobDetail.progress.completed
          : null;

  if (images === null) {
    return null;
  }

  return sprintf(
    /* translators: %d: number of images processed in a recognition job */
    __('%d images', 'alt-context'),
    images,
  );
};

/** Human summary: verb + optional counts + optional relative time. Never includes raw IDs. */
export const buildActivitySummary = (
  item: RecognitionActivityItem,
  jobDetail: JobStatusResponse | undefined,
  statusLabel: string,
  nowMs: number = Date.now(),
): string => {
  const verb = verbForStatus(jobDetail?.status ?? statusLabel, item.statusText);
  const parts: string[] = [verb];

  const counts = countLabelFromJob(jobDetail);
  if (counts) {
    parts.push(counts);
  }

  const relative = formatRelativeTime(jobDetail?.finished_at ?? jobDetail?.started_at, nowMs);
  if (relative) {
    parts.push(relative);
  }

  return parts.join(' · ');
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
      <EmptyState
        variant={EmptyStateVariant.UNAVAILABLE}
        heading={__('Recent activity is unavailable', 'alt-context')}
        body={__('Previous scans could not be loaded. You can still start a new scan.', 'alt-context')}
        action={{ label: __('Run a scan', 'alt-context'), href: toWorkbench({ tab: 'scan' }) }}
        headingLevel={3}
        announceState={false}
      />
    ) : recentActivity.length === 0 ? (
      <EmptyState
        variant={EmptyStateVariant.EMPTY}
        heading={__('No recent scans yet', 'alt-context')}
        body={__('Run a scan to find faces in your media library.', 'alt-context')}
        action={{ label: __('Run a scan', 'alt-context'), href: toWorkbench({ tab: 'scan' }) }}
        headingLevel={3}
        announceState={false}
      />
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
          const summary = buildActivitySummary(item, jobDetail, statusLabel);

          return (
            <li key={item.id} className="acx-dashboard__activity-item">
              <span className="acx-dashboard__activity-summary">{summary}</span>
              <span className="acx-dashboard__activity-status">{statusLabel}</span>
              <span className="acx-dashboard__activity-status">
                {item.provenance === 'durable_batch_run'
                  ? __('Durable batch run', 'alt-context')
                  : __('Current browser memory', 'alt-context')}
              </span>
              {durationLabel ? <span className="acx-dashboard__activity-duration">{durationLabel}</span> : null}
              {item.jobId ? (
                <a href={toWorkbench({ advanced: true })} className="acx-link-button">
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
