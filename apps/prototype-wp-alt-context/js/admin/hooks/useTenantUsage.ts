import { useEffect, useRef } from 'react';
import { useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query';

import { queryKeys } from '../api/queryKeys';
import { fetchTenantUsage, type TenantUsage } from '../api/usageApi';
import { isCooldownSignal } from '../utils/retryPolicy';
import { useActiveDescribeRun } from './activeDescribeRun';

export const TENANT_USAGE_STALE_TIME_MS = 60_000;

/** A throttled (429 / 503-with-Retry-After) balance read, re-labelled so it stays local to the chip. */
export class TenantUsageUnavailableError extends Error {
  constructor(cause: unknown) {
    super('Tenant usage is temporarily unavailable.', { cause });
    this.name = 'TenantUsageUnavailableError';
  }
}

const fetchUsage = async ({ signal }: { signal: AbortSignal }): Promise<TenantUsage> => {
  try {
    return await fetchTenantUsage(signal);
  } catch (error) {
    // The app QueryCache arms the shared recognition cooldown on any throttle
    // signal, which pauses describe polling. A display-only read must never
    // hold Describe [rg-003], so its throttle stops here.
    if (isCooldownSignal(error)) {
      throw new TenantUsageUnavailableError(error);
    }
    throw error;
  }
};

/**
 * Read-only tenant balance. No retry: a failed read shows "Balance unavailable"
 * at once, and the next window focus or settled run reads again.
 */
export const useTenantUsage = (): UseQueryResult<TenantUsage, Error> => {
  const queryClient = useQueryClient();
  const { runId } = useActiveDescribeRun();
  const previousRunIdRef = useRef(runId);

  useEffect(() => {
    const previousRunId = previousRunIdRef.current;
    previousRunIdRef.current = runId;
    // useBulkDescribe clears the active run id when the run reaches a terminal
    // state; its spend has settled, so the cached balance is stale.
    if (previousRunId !== null && previousRunId !== runId) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.usage.tenant() });
    }
  }, [queryClient, runId]);

  return useQuery<TenantUsage, Error>({
    queryKey: queryKeys.usage.tenant(),
    queryFn: fetchUsage,
    staleTime: TENANT_USAGE_STALE_TIME_MS,
    refetchOnWindowFocus: true,
    retry: false,
  });
};
