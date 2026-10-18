import { useRef } from 'react';

import type { JobProgress } from '../api/recognition/types/scan';
import { enforceMonotonicProgress } from './jobStateMachineRuntime';

interface MonotonicCache {
  runKey: string | null;
  snapshot: JobProgress | null;
}

/**
 * Clamps displayed progress so a later snapshot for the same run cannot
 * regress. The `runKey` identifies the active run (batch-run id, scan job id,
 * or cluster job id); when it changes the accumulator resets so a new run
 * does not inherit the prior run's floor.
 */
export const useMonotonicScanProgress = (
  rawProgress: JobProgress | null,
  runKey: string | null,
): JobProgress | null => {
  const cacheRef = useRef<MonotonicCache>({ runKey: null, snapshot: null });
  const cache = cacheRef.current;

  if (cache.runKey !== runKey) {
    cache.runKey = runKey;
    cache.snapshot = rawProgress;
    return rawProgress;
  }

  const next = enforceMonotonicProgress(cache.snapshot, rawProgress);
  cache.snapshot = next;
  return next;
};
