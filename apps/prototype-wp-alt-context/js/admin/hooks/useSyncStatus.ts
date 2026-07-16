import { useQuery } from '@tanstack/react-query';

import { fetchSyncStatus, type SyncStatusResponse } from '../api/recognition';
import { queryKeys } from '../api/queryKeys';
import { gateRefetchInterval } from '../utils/rateLimitCooldown';

export const useSyncStatus = () =>
  useQuery<SyncStatusResponse>({
    queryKey: queryKeys.sync.status(),
    queryFn: () => fetchSyncStatus(),
    staleTime: 60_000,
    refetchInterval: gateRefetchInterval(120_000),
  });
