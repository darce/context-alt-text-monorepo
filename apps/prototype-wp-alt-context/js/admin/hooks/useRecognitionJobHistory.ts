import { useCallback, useEffect, useState } from 'react';
import { __ } from '@wordpress/i18n';

import { fetchScanStatus } from '../api/recognition';
import type { JobStatusResponse } from '../api/recognition/types/scan';

const JOB_HISTORY_KEY = 'acx-recognition-jobs';
const MAX_JOB_HISTORY = 5;

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

export const useRecognitionJobHistory = () => {
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobHistory, setJobHistory] = useState<string[]>([]);
  const [jobStatuses, setJobStatuses] = useState<Record<string, string>>({});
  const [jobDetails, setJobDetails] = useState<Record<string, JobStatusResponse>>({});

  useEffect(() => {
    const stored = readStoredHistory();
    if (stored.length > 0) {
      setJobHistory(stored);
      setJobId(stored[0]);
    }
  }, []);

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

  const rememberJob = useCallback((nextJobId: string) => {
    setJobHistory((prev) => {
      const next = [nextJobId, ...prev.filter((id) => id !== nextJobId)].slice(0, MAX_JOB_HISTORY);
      persistHistory(next);
      return next;
    });
    setJobId(nextJobId);
  }, []);

  const selectJob = useCallback((id: string) => {
    setJobId(id);
  }, []);

  const clearHistory = useCallback(() => {
    setJobHistory([]);
    setJobStatuses({});
    setJobDetails({});
    setJobId(null);
    persistHistory([]);
  }, []);

  const forgetJob = useCallback((staleJobId: string) => {
    setJobHistory((prev) => {
      const next = prev.filter((id) => id !== staleJobId);
      persistHistory(next);
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
  }, []);

  return {
    jobId,
    jobHistory,
    jobStatuses,
    jobDetails,
    rememberJob,
    selectJob,
    forgetJob,
    clearHistory,
  } as const;
};
