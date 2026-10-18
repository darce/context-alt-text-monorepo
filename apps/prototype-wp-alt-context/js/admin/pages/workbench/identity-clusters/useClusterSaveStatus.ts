/**
 * Hook for tracking save status with a brief success state.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

export type SaveStatus = 'idle' | 'queued' | 'saved';

interface UseClusterSaveStatusOptions {
  delayMs?: number;
}

export const useClusterSaveStatus = ({ delayMs = 1200 }: UseClusterSaveStatusOptions = {}) => {
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const saveStatusTimerRef = useRef<number | null>(null);

  const clearSaveStatusTimer = useCallback(() => {
    if (saveStatusTimerRef.current === null) {
      return;
    }
    window.clearTimeout(saveStatusTimerRef.current);
    saveStatusTimerRef.current = null;
  }, []);

  const resetSaveStatus = useCallback(() => {
    clearSaveStatusTimer();
    setSaveStatus('idle');
  }, [clearSaveStatusTimer]);

  const queueSaveStatus = useCallback(() => {
    clearSaveStatusTimer();
    setSaveStatus('queued');
  }, [clearSaveStatusTimer]);

  const markSaveSuccess = useCallback(
    (onSuccess: () => void) => {
      clearSaveStatusTimer();
      setSaveStatus('saved');
      saveStatusTimerRef.current = window.setTimeout(() => {
        onSuccess();
        setSaveStatus('idle');
        saveStatusTimerRef.current = null;
      }, delayMs);
    },
    [clearSaveStatusTimer, delayMs],
  );

  useEffect(() => () => clearSaveStatusTimer(), [clearSaveStatusTimer]);

  return {
    saveStatus,
    resetSaveStatus,
    queueSaveStatus,
    markSaveSuccess,
  };
};
