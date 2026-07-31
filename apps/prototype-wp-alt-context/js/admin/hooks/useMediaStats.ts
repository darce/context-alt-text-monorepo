import { type QueryClient, useQuery } from '@tanstack/react-query';
import { fetchWorkbenchMedia } from '../api/workbenchMediaApi';
import { queryKeys } from '../api/queryKeys';

export interface MediaStats {
  total: number;
  missing: number;
  coverage: number;
}

/**
 * Shared probe shape for dashboard coverage counters. Single definition so
 * invalidation from useCorrectMediaAlt (and any future writer) cannot drift
 * from the keys useMediaStats actually observes.
 */
export const MEDIA_STATS_PROBE = {
  page: 1,
  perPage: 1,
} as const;

/** Total-media count probe — alt correction does not change this total. */
export const mediaStatsTotalQueryKey = queryKeys.media.workbenchPage({
  ...MEDIA_STATS_PROBE,
  status: 'all',
});

/** Missing-alt count probe — the figure that must refresh after a successful correction. */
export const mediaStatsMissingQueryKey = queryKeys.media.workbenchPage({
  ...MEDIA_STATS_PROBE,
  status: 'missing',
});

/**
 * Ask the server for a fresh missing-alt total after a successful alt write.
 *
 * Only the missing probe is invalidated: coverage = f(total, missing), and
 * correcting alt text never changes how many media exist. The total probe's
 * response is consumed solely for `.total` in useMediaStats — invalidating it
 * would cost a request and refresh nothing. Distinct from list pages
 * (perPage > 1), so this cannot unmount a workbench row [BR-77].
 */
export const invalidateMediaStats = (queryClient: QueryClient): void => {
  void queryClient.invalidateQueries({ queryKey: mediaStatsMissingQueryKey });
};

export const useMediaStats = () => {
  const totalMediaResult = useQuery({
    queryKey: mediaStatsTotalQueryKey,
    queryFn: () =>
      fetchWorkbenchMedia({
        ...MEDIA_STATS_PROBE,
        status: 'all',
      }),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });

  const missingAltResult = useQuery({
    queryKey: mediaStatsMissingQueryKey,
    queryFn: () =>
      fetchWorkbenchMedia({
        ...MEDIA_STATS_PROBE,
        status: 'missing',
      }),
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
