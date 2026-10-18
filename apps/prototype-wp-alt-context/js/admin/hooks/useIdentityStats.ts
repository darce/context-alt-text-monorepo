import { useQuery } from '@tanstack/react-query';

import { queryKeys } from '../api/queryKeys';
import { fetchDashboardStats, type DashboardStats } from '../api/dashboardApi';

export const useIdentityStats = () =>
  useQuery<DashboardStats>({
    queryKey: queryKeys.dashboard.stats(),
    queryFn: fetchDashboardStats,
    staleTime: 30_000,
    refetchOnWindowFocus: true,
  });
