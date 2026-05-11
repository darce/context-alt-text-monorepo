import { useCallback, useEffect, useState } from 'react';
import type { JobStatusResponse } from '../api/recognition/types/scan';
import {
  buildFallbackActivity,
  fetchRecognitionStatusEntries,
  hydrateRecognitionHistory,
  persistHistory,
  type RecognitionActivityItem,
  type RecognitionHistorySource,
} from './recognitionJobHistoryUtils';

export const useRecognitionJobHistory = () => {
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobHistory, setJobHistory] = useState<string[]>([]);
  const [jobStatuses, setJobStatuses] = useState<Record<string, string>>({});
  const [jobDetails, setJobDetails] = useState<Record<string, JobStatusResponse>>({});
  const [recentActivity, setRecentActivity] = useState<RecognitionActivityItem[]>([]);
  const [historySource, setHistorySource] = useState<RecognitionHistorySource>('unavailable');

  const hydrateHistory = useCallback(async (): Promise<void> => {
    const next = await hydrateRecognitionHistory();
    setRecentActivity(next.recentActivity);
    setJobHistory(next.jobHistory);
    setHistorySource(next.historySource);
    setJobId((current) => (current && next.jobHistory.includes(current) ? current : next.selectedJobId));
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
      const entries = await fetchRecognitionStatusEntries(jobHistory);

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
