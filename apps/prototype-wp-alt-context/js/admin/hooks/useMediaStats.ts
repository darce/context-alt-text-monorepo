import { useQuery } from '@tanstack/react-query';
import { fetchWorkbenchMedia } from '../api/workbenchMediaApi';
import { queryKeys } from '../api/queryKeys';

export interface MediaStats {
  total: number;
  missing: number;
  coverage: number;
}

export const useMediaStats = () => {
  const totalMediaResult = useQuery({
    queryKey: queryKeys.media.workbenchPage({ page: 1, perPage: 1, status: 'all' }),
    queryFn: () => fetchWorkbenchMedia({ page: 1, perPage: 1, status: 'all' }),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });

  const missingAltResult = useQuery({
    queryKey: queryKeys.media.workbenchPage({ page: 1, perPage: 1, status: 'missing' }),
    queryFn: () => fetchWorkbenchMedia({ page: 1, perPage: 1, status: 'missing' }),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });

  const isLoading = totalMediaResult.isLoading || missingAltResult.isLoading;
  const isError = totalMediaResult.isError || missingAltResult.isError;

  const total = totalMediaResult.data?.total ?? 0;
  const missing = missingAltResult.data?.total ?? 0;
  const complete = Math.max(0, total - missing);
  const coverage = total > 0 ? (complete / total) * 100 : 0;

  return {
    stats: {
      total,
      missing,
      complete,
      coverage,
    },
    isLoading,
    isError,
    refetch: async () => {
      await Promise.all([totalMediaResult.refetch(), missingAltResult.refetch()]);
    },
  };
};
