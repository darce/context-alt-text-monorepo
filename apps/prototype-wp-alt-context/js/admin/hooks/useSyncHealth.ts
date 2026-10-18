import { useQuery } from '@tanstack/react-query';

import { fetchSyncHealth, type SyncHealthResponse } from '../api/recognition';
import { queryKeys } from '../api/queryKeys';

const SYNC_HEALTH_STALE_MS = 15_000;
const SYNC_HEALTH_REFETCH_MS = 15_000;

export const useSyncHealth = () =>
  useQuery<SyncHealthResponse>({
    queryKey: queryKeys.sync.health(),
    queryFn: () => fetchSyncHealth(),
    staleTime: SYNC_HEALTH_STALE_MS,
    refetchInterval: SYNC_HEALTH_REFETCH_MS,
    // A missed interval can remain paused after connectivity returns in RQ v5.
    // Always probe on reconnect so an open breaker can heal reactively.
    refetchOnReconnect: 'always',
  });
