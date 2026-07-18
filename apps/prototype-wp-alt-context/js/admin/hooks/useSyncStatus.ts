import { useQuery } from '@tanstack/react-query';

import { fetchSyncStatus, type SyncStatusResponse } from '../api/recognition';
import { queryKeys } from '../api/queryKeys';

export const useSyncStatus = () =>
  useQuery<SyncStatusResponse>({
    queryKey: queryKeys.sync.status(),
    queryFn: () => fetchSyncStatus(),
    staleTime: 60_000,
    refetchInterval: 120_000,
  });
