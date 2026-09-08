import { __ } from '@wordpress/i18n';

import { fetchRecentBatchRuns, fetchScanStatus } from '../api/recognition';
import type { JobStatusResponse, RecentBatchRunActivity } from '../api/recognition/types/scan';
import { isHttpStatus } from '../utils/appError';

const JOB_HISTORY_KEY = 'acx-recognition-jobs';
export const MAX_JOB_HISTORY = 5;

export type RecognitionHistorySource = 'durable' | 'browser_local_fallback' | 'unavailable';

export interface RecognitionActivityItem {
  id: string;
  jobId: string | null;
  runId: string | null;
  provenance: 'durable_batch_run' | 'browser_local_fallback';
  statusText: string;
}

export interface RecognitionStatusEntry {
  id: string;
  status: string;
  detail: JobStatusResponse | null;
  notFound: boolean;
}

const toStringArray = (value: unknown): string[] =>
  Array.isArray(value) && value.every((item) => typeof item === 'string') ? value : [];

export const readStoredHistory = (): string[] => {
  if (typeof window === 'undefined') {
    return [];
  }

  try {
    const stored = window.localStorage.getItem(JOB_HISTORY_KEY);
    const parsed: unknown = stored ? JSON.parse(stored) : [];
    return toStringArray(parsed);
  } catch {
    return [];
  }
};

export const persistHistory = (history: string[]): void => {
  if (typeof window === 'undefined') {
    return;
  }

  window.localStorage.setItem(JOB_HISTORY_KEY, JSON.stringify(history));
};

const buildDurableStatusText = (item: RecentBatchRunActivity): string => {
  if (item.latest_job_status) {
    return item.latest_job_status;
  }
  if (item.failed_total > 0 && item.accepted_total === 0) {
    return __('Submission failed', 'alt-context');
  }
  if (item.terminal_state) {
    return __('Completed', 'alt-context');
  }
  return __('Pending', 'alt-context');
};

export const buildDurableActivity = (items: RecentBatchRunActivity[]): RecognitionActivityItem[] =>
  items.map((item) => ({
    id: item.run_id,
    jobId: item.latest_job_id || null,
    runId: item.run_id,
    provenance: 'durable_batch_run',
    statusText: buildDurableStatusText(item),
  }));

export const buildFallbackActivity = (jobIds: string[]): RecognitionActivityItem[] =>
  jobIds.map((jobId) => ({
    id: jobId,
    jobId,
    runId: null,
    provenance: 'browser_local_fallback',
    statusText: __('Remembered in this browser only', 'alt-context'),
  }));

const getPollableDurableJobIds = (items: RecentBatchRunActivity[]): string[] =>
  items
    .filter((item) => !item.terminal_state)
    .map((item) => item.latest_job_id)
    .filter((value): value is string => typeof value === 'string' && value.length > 0);

export const hydrateRecognitionHistory = async (): Promise<{
  recentActivity: RecognitionActivityItem[];
  jobHistory: string[];
  pollableJobIds: string[];
  selectedJobId: string | null;
  historySource: RecognitionHistorySource;
}> => {
  const stored = readStoredHistory();

  try {
    const response = await fetchRecentBatchRuns(MAX_JOB_HISTORY);
    const durableActivity = buildDurableActivity(response.items);
    const durableJobHistory = durableActivity
      .map((item) => item.jobId)
      .filter((value): value is string => typeof value === 'string' && value.length > 0);

    if (durableActivity.length > 0) {
      const pollableJobIds = getPollableDurableJobIds(response.items);
      return {
        recentActivity: durableActivity,
        jobHistory: durableJobHistory,
        pollableJobIds,
        selectedJobId: pollableJobIds[0] ?? null,
        historySource: 'durable',
      };
    }

    if (stored.length > 0) {
      persistHistory([]);
    }

    return {
      recentActivity: [],
      jobHistory: [],
      pollableJobIds: [],
      selectedJobId: null,
      historySource: 'durable',
    };
  } catch {
    if (stored.length > 0) {
      return {
        recentActivity: buildFallbackActivity(stored),
        jobHistory: stored,
        pollableJobIds: stored,
        selectedJobId: stored[0] ?? null,
        historySource: 'browser_local_fallback',
      };
    }

    return {
      recentActivity: [],
      jobHistory: [],
      pollableJobIds: [],
      selectedJobId: null,
      historySource: 'unavailable',
    };
  }
};

export const fetchRecognitionStatusEntries = async (jobHistory: string[]): Promise<RecognitionStatusEntry[]> =>
  Promise.all(
    jobHistory.map(async (id) => {
      try {
        const response = await fetchScanStatus(id);
        return { id, status: response.status, detail: response, notFound: false };
      } catch (error) {
        return {
          id,
          status: __('Unknown', 'alt-context'),
          detail: null,
          notFound: isHttpStatus(error, 404),
        };
      }
    }),
  );
