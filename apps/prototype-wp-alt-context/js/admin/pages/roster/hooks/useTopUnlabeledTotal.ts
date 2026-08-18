import { useQuery } from '@tanstack/react-query';

import { getConfig } from '../../../api/config';
import { queryKeys } from '../../../api/queryKeys';
import { fetchTopUnlabeledClusters } from '../../../api/recognition';
import { DATA_SOURCE } from '../../../api/recognition/types/dataSource';

// Same key + limit as the workbench queue hook (useSuggestionReviewQueries) so both
// surfaces share one cache entry for the single needs-assignment predicate.
const TOP_UNLABELED_LIMIT = 20;

const COUNTED_SOURCES = new Set<string>([DATA_SOURCE.LOCAL_PROJECTION, DATA_SOURCE.BACKEND_PROXY]);

/**
 * Server-reported count of unnamed face groups waiting in the workbench review
 * queue. Returns null while loading, on error, or when the envelope is a
 * designed-unknown source (unavailable / endpoint_error) — callers must say
 * the count is unknown rather than invent one (rg-015: total comes from the
 * envelope only, and only when data_source is a real projection).
 */
export const useTopUnlabeledTotal = (): number | null => {
  const tenantId = getConfig().tenant_id ?? '';
  const query = useQuery({
    queryKey: queryKeys.clusters.topUnlabeled(tenantId),
    queryFn: ({ signal }) => fetchTopUnlabeledClusters(tenantId, TOP_UNLABELED_LIMIT, signal),
    enabled: tenantId !== '',
    staleTime: 60000,
    refetchOnMount: 'always',
    retry: false,
  });
  const total = query.data?.total;
  if (typeof total !== 'number' || !COUNTED_SOURCES.has(query.data?.data_source ?? '')) {
    return null;
  }
  return total;
};
