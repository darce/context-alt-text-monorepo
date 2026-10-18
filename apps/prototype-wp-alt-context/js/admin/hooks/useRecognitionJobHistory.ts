import { useCallback, useEffect, useState } from 'react';
import type { JobStatusResponse } from '../api/recognition/types/scan';
import {
  buildFallbackActivity,
  fetchRecognitionStatusEntries,
  hydrateRecognitionHistory,
  MAX_JOB_HISTORY,
  persistHistory,
  type RecognitionActivityItem,
  type RecognitionHistorySource,
} from './recognitionJobHistoryUtils';

const buildDurableStatusMap = (items: RecognitionActivityItem[]): Record<string, string> => {
  const statuses: Record<string, string> = {};
  items.forEach((item) => {
    if (item.jobId) {
      statuses[item.jobId] = item.statusText;
    }
  });
  return statuses;
};

export const useRecognitionJobHistory = () => {
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobHistory, setJobHistory] = useState<string[]>([]);
  const [pollableJobIds, setPollableJobIds] = useState<string[]>([]);
  const [jobStatuses, setJobStatuses] = useState<Record<string, string>>({});
  const [jobDetails, setJobDetails] = useState<Record<string, JobStatusResponse>>({});
  const [recentActivity, setRecentActivity] = useState<RecognitionActivityItem[]>([]);
  const [historySource, setHistorySource] = useState<RecognitionHistorySource>('unavailable');

  const hydrateHistory = useCallback(async (): Promise<void> => {
    const next = await hydrateRecognitionHistory();
    setRecentActivity(next.recentActivity);
    setJobHistory(next.jobHistory);
    setPollableJobIds(next.pollableJobIds);
    setHistorySource(next.historySource);
    setJobStatuses(next.historySource === 'durable' ? buildDurableStatusMap(next.recentActivity) : {});
    if (next.historySource === 'durable' && next.pollableJobIds.length === 0) {
      setJobDetails({});
    }
    setJobId((current) => (current && next.pollableJobIds.includes(current) ? current : next.selectedJobId));
  }, []);

  useEffect(() => {
    void hydrateHistory();
  }, [hydrateHistory]);

  useEffect(() => {
    if (pollableJobIds.length === 0) {
      return;
    }

    let cancelled = false;

    const fetchStatuses = async (): Promise<void> => {
      const entries = await fetchRecognitionStatusEntries(pollableJobIds);

      if (cancelled) {
        return;
      }

      const staleIds = entries.filter((entry) => entry.notFound).map((entry) => entry.id);
      if (staleIds.length > 0) {
        const nextHistory = jobHistory.filter((id) => !staleIds.includes(id));
        const nextPollableJobIds = pollableJobIds.filter((id) => !staleIds.includes(id));
        setJobHistory(nextHistory);
        setPollableJobIds(nextPollableJobIds);
        setRecentActivity((prev) => prev.filter((item) => !item.jobId || !staleIds.includes(item.jobId)));
        if (historySource === 'browser_local_fallback') {
          persistHistory(nextHistory);
        }
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
        setJobId((current) => (current && staleIds.includes(current) ? (nextPollableJobIds[0] ?? null) : current));
        if (nextPollableJobIds.length === 0) {
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
  }, [historySource, jobHistory, pollableJobIds]);

  const rememberJob = useCallback(
    (nextJobId: string) => {
      setJobHistory((prev) => {
        const next = [nextJobId, ...prev.filter((id) => id !== nextJobId)].slice(0, MAX_JOB_HISTORY);
        persistHistory(next);
        setPollableJobIds(next);
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

  const selectJob = useCallback(
    (id: string) => {
      setJobId((current) => (pollableJobIds.includes(id) ? id : current));
    },
    [pollableJobIds],
  );

  const clearHistory = useCallback(() => {
    persistHistory([]);
    if (historySource !== 'browser_local_fallback') {
      return;
    }

    setJobHistory([]);
    setPollableJobIds([]);
    setJobStatuses({});
    setJobDetails({});
    setRecentActivity([]);
    setJobId(null);
  }, [historySource]);

  const forgetJob = useCallback(
    (staleJobId: string) => {
      setJobHistory((prev) => {
        const next = prev.filter((id) => id !== staleJobId);
        if (historySource === 'browser_local_fallback') {
          persistHistory(next);
          setRecentActivity(buildFallbackActivity(next));
        } else {
          setRecentActivity((previousActivity) =>
            previousActivity.filter((item) => !item.jobId || item.jobId !== staleJobId),
          );
        }
        return next;
      });
      setPollableJobIds((prev) => prev.filter((id) => id !== staleJobId));
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
