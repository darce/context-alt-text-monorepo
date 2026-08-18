import { useQuery } from '@tanstack/react-query';

import { getConfig } from '../../../api/config';
import { queryKeys } from '../../../api/queryKeys';
import { fetchTopUnlabeledClusters } from '../../../api/recognition';

// Same key + limit as the workbench queue hook (useSuggestionReviewQueries) so both
// surfaces share one cache entry for the single needs-assignment predicate.
const TOP_UNLABELED_LIMIT = 20;

/**
 * Server-reported count of unnamed face groups waiting in the workbench review
 * queue. Returns null while loading or on error — callers must say the count is
 * unknown rather than invent one (rg-015: total comes from the envelope only).
 */
export const useTopUnlabeledTotal = (): number | null => {
  const tenantId = getConfig().tenant_id ?? '';
  const query = useQuery({
    queryKey: queryKeys.clusters.topUnlabeled(tenantId),
    queryFn: ({ signal }) => fetchTopUnlabeledClusters(tenantId, TOP_UNLABELED_LIMIT, signal),
    enabled: tenantId !== '',
    staleTime: 60000,
    retry: false,
  });
  const total = query.data?.total;
  return typeof total === 'number' ? total : null;
};
