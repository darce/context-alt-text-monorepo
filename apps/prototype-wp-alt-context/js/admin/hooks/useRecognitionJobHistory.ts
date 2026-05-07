import { useCallback, useEffect, useState } from 'react';
import { __ } from '@wordpress/i18n';

import { fetchRecentBatchRuns, fetchScanStatus } from '../api/recognition';
import type { JobStatusResponse, RecentBatchRunActivity } from '../api/recognition/types/scan';

const JOB_HISTORY_KEY = 'acx-recognition-jobs';
const MAX_JOB_HISTORY = 5;

export type RecognitionHistorySource = 'durable' | 'browser_local_fallback' | 'unavailable';

export interface RecognitionActivityItem {
  id: string;
  jobId: string | null;
  runId: string | null;
  provenance: 'durable_batch_run' | 'browser_local_fallback';
  statusText: string;
}

const toStringArray = (value: unknown): string[] =>
  Array.isArray(value) && value.every((item) => typeof item === 'string') ? value : [];

const readStoredHistory = (): string[] => {
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

const persistHistory = (history: string[]): void => {
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

const buildDurableActivity = (items: RecentBatchRunActivity[]): RecognitionActivityItem[] =>
  items.map((item) => ({
    id: item.run_id,
    jobId: item.latest_job_id || null,
    runId: item.run_id,
    provenance: 'durable_batch_run',
    statusText: buildDurableStatusText(item),
  }));

const buildFallbackActivity = (jobIds: string[]): RecognitionActivityItem[] =>
  jobIds.map((jobId) => ({
    id: jobId,
    jobId,
    runId: null,
    provenance: 'browser_local_fallback',
    statusText: __('Remembered in this browser only', 'alt-context'),
  }));

export const useRecognitionJobHistory = () => {
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobHistory, setJobHistory] = useState<string[]>([]);
  const [jobStatuses, setJobStatuses] = useState<Record<string, string>>({});
  const [jobDetails, setJobDetails] = useState<Record<string, JobStatusResponse>>({});
  const [recentActivity, setRecentActivity] = useState<RecognitionActivityItem[]>([]);
  const [historySource, setHistorySource] = useState<RecognitionHistorySource>('unavailable');

  const hydrateHistory = useCallback(async (): Promise<void> => {
    const stored = readStoredHistory();

    try {
      const response = await fetchRecentBatchRuns(MAX_JOB_HISTORY);
      const durableActivity = buildDurableActivity(response.items);
      const durableJobHistory = durableActivity
        .map((item) => item.jobId)
        .filter((value): value is string => typeof value === 'string' && value.length > 0);

      if (durableActivity.length > 0) {
        setRecentActivity(durableActivity);
        setJobHistory(durableJobHistory);
        setJobId((current) =>
          current && durableJobHistory.includes(current) ? current : (durableJobHistory[0] ?? null),
        );
        setHistorySource('durable');
        return;
      }
    } catch {
      if (stored.length > 0) {
        setRecentActivity(buildFallbackActivity(stored));
        setJobHistory(stored);
        setJobId((current) => current ?? stored[0] ?? null);
        setHistorySource('browser_local_fallback');
        return;
      }

      setRecentActivity([]);
      setJobHistory([]);
      setJobId(null);
      setHistorySource('unavailable');
      return;
    }

    if (stored.length > 0) {
      setRecentActivity(buildFallbackActivity(stored));
      setJobHistory(stored);
      setJobId((current) => current ?? stored[0] ?? null);
      setHistorySource('browser_local_fallback');
      return;
    }

    setRecentActivity([]);
    setJobHistory([]);
    setJobId(null);
    setHistorySource('durable');
  }, []);

  useEffect(() => {
    void hydrateHistory();
  }, [hydrateHistory]);

  useEffect(() => {
    if (jobHistory.length === 0) {
      return;
    }

    let cancelled = false;

    const fetchStatuses = async (): Promise<void> => {
      const entries = await Promise.all(
        jobHistory.map(async (id) => {
          try {
            const response = await fetchScanStatus(id);
            return { id, status: response.status, detail: response, notFound: false } as const;
          } catch (error) {
            const message = error instanceof Error ? error.message : '';
            const notFound = message.includes('(404)');
            return { id, status: __('Unknown', 'alt-context'), detail: null, notFound } as const;
          }
        }),
      );

      if (cancelled) {
        return;
      }

      const staleIds = entries.filter((entry) => entry.notFound).map((entry) => entry.id);
      if (staleIds.length > 0) {
        const nextHistory = jobHistory.filter((id) => !staleIds.includes(id));
        setJobHistory(nextHistory);
        persistHistory(nextHistory);
        setJobStatuses((prev) => {
          const next = { ...prev };
          staleIds.forEach((id) => {
            delete next[id];
          });
          return next;
        });
        setJobDetails((prev) => {
          const next = { ...prev };
          staleIds.forEach((id) => {
            delete next[id];
          });
          return next;
        });
        setJobId((current) => (current && staleIds.includes(current) ? (nextHistory[0] ?? null) : current));
        if (nextHistory.length === 0) {
          return;
        }
      }

      setJobStatuses((prev) => {
        const next = { ...prev };
        entries.forEach((entry) => {
          if (staleIds.includes(entry.id)) {
            return;
          }
          next[entry.id] = entry.status;
        });
        return next;
      });
      setJobDetails((prev) => {
        const next = { ...prev };
        entries.forEach((entry) => {
          if (staleIds.includes(entry.id) || entry.notFound || !entry.detail) {
            return;
          }
          next[entry.id] = entry.detail;
        });
        return next;
      });
    };

    void fetchStatuses();

    return () => {
      cancelled = true;
    };
  }, [jobHistory]);

  const rememberJob = useCallback(
    (nextJobId: string) => {
      setJobHistory((prev) => {
        const next = [nextJobId, ...prev.filter((id) => id !== nextJobId)].slice(0, MAX_JOB_HISTORY);
        persistHistory(next);
        if (historySource !== 'durable') {
          setRecentActivity(buildFallbackActivity(next));
        }
        return next;
      });
      setJobId(nextJobId);
      void hydrateHistory();
    },
    [historySource, hydrateHistory],
  );

  const selectJob = useCallback((id: string) => {
    setJobId(id);
  }, []);

  const clearHistory = useCallback(() => {
    persistHistory([]);
    if (historySource !== 'browser_local_fallback') {
      return;
    }

    setJobHistory([]);
    setJobStatuses({});
    setJobDetails({});
    setRecentActivity([]);
    setJobId(null);
  }, [historySource]);

  const forgetJob = useCallback(
    (staleJobId: string) => {
      if (historySource !== 'browser_local_fallback') {
        return;
      }

      setJobHistory((prev) => {
        const next = prev.filter((id) => id !== staleJobId);
        persistHistory(next);
        setRecentActivity(buildFallbackActivity(next));
        return next;
      });
      setJobStatuses((prev) => {
        const next = { ...prev };
        delete next[staleJobId];
        return next;
      });
      setJobDetails((prev) => {
        const next = { ...prev };
        delete next[staleJobId];
        return next;
      });
      setJobId((current) => (current === staleJobId ? null : current));
    },
    [historySource],
  );

  return {
    jobId,
    jobHistory,
    jobStatuses,
    jobDetails,
    recentActivity,
    historySource,
    rememberJob,
    selectJob,
    forgetJob,
    clearHistory,
  } as const;
};
