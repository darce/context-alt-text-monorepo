import { useCallback, useEffect, useState } from 'react';
import { __ } from '@wordpress/i18n';

import { fetchScanStatus } from '../api/recognitionApi';

const JOB_HISTORY_KEY = 'acx-recognition-jobs';
const MAX_JOB_HISTORY = 5;

const readStoredHistory = (): string[] => {
  if (typeof window === 'undefined') {
    return [];
  }

  try {
    const stored = window.localStorage.getItem(JOB_HISTORY_KEY);
    const parsed = stored ? JSON.parse(stored) : [];
    return Array.isArray(parsed) ? parsed : [];
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

    (async () => {
      const entries = await Promise.all(
        jobHistory.map(async (id) => {
          try {
            const response = await fetchScanStatus(id);
            return [id, response.status] as const;
          } catch {
            return [id, __('Unknown', 'alt-context')] as const;
          }
        }),
      );

      if (cancelled) {
        return;
      }

      setJobStatuses((prev) => {
        const next = { ...prev };
        entries.forEach(([id, status]) => {
          next[id] = status;
        });
        return next;
      });
    })();

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
    setJobId(null);
    persistHistory([]);
  }, []);

  return {
    jobId,
    jobHistory,
    jobStatuses,
    rememberJob,
    selectJob,
    clearHistory,
  } as const;
};
