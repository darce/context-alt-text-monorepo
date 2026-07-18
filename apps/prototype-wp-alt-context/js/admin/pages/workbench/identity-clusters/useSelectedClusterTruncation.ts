/**
 * Slice-5 joint B3/B4 truncation gate (PR-35 / BR-43).
 *
 * Prefetches first-page members envelopes for each distinct selected TARGET
 * cluster and reads `truncated`/`total` from the QUERY-CACHE envelope
 * (`queryKeys.clusters.memberList`). Does NOT consume `useShowAllClusterMembers`
 * instance-local `isFullyLoaded` (see that hook's JSDoc contract).
 *
 * Selections without a cluster target are never truncation-gated.
 */

import { useMemo } from 'react';
import { useQueries } from '@tanstack/react-query';

import { fetchClusterMembers } from '../../../api/recognition';
import { queryKeys } from '../../../api/queryKeys';

export interface TruncationClusterInfo {
  clusterId: string;
  total: number;
  /** Members present on the first page (loaded count). */
  loaded: number;
  /** total − loaded when truncated; 0 when not truncated. */
  hiddenCount: number;
  truncated: boolean;
}

export interface UseSelectedClusterTruncationResult {
  /** Distinct target cluster ids being evaluated (empty → not gated). */
  targetClusterIds: readonly string[];
  /** True while any first-page envelope is still loading. */
  isLoading: boolean;
  /** Clusters whose first-page envelope reports truncated=true. */
  truncatedClusters: readonly TruncationClusterInfo[];
  /** True when any selected target cluster is truncated (gate active). */
  isTruncationGated: boolean;
  /** Sum of totals across truncated target clusters (confirm copy). */
  gatedTotal: number;
  /** Sum of hidden counts across truncated target clusters. */
  gatedHiddenCount: number;
}

const uniqueIds = (ids: readonly (string | null | undefined)[]): string[] => {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const id of ids) {
    if (!id || seen.has(id)) {
      continue;
    }
    seen.add(id);
    out.push(id);
  }
  return out;
};

/**
 * @param targetClusterIds — cluster ids from selected items that have a
 *   target cluster (assignment/name). Empty/null ids are ignored.
 */
export const useSelectedClusterTruncation = (
  targetClusterIds: readonly (string | null | undefined)[],
): UseSelectedClusterTruncationResult => {
  const ids = useMemo(() => uniqueIds(targetClusterIds), [targetClusterIds]);

  const queries = useQueries({
    queries: ids.map((clusterId) => ({
      queryKey: queryKeys.clusters.memberList(clusterId),
      queryFn: () => fetchClusterMembers(clusterId),
      enabled: Boolean(clusterId),
      // First page only — never request a full-members fetch here [RES-05].
      staleTime: 30_000,
    })),
  });

  const isLoading = ids.length > 0 && queries.some((q) => q.isLoading || q.isFetching);

  // Compute from query results each render — selection sets are small (no useMemo:
  // useQueries result is referentially unstable per @tanstack/query/no-unstable-deps).
  const truncatedClusters: TruncationClusterInfo[] = [];
  for (let i = 0; i < ids.length; i += 1) {
    const data = queries[i]?.data;
    if (!data?.truncated) {
      continue;
    }
    const loaded = data.members.length;
    const hiddenCount = Math.max(0, data.total - loaded);
    truncatedClusters.push({
      clusterId: ids[i],
      total: data.total,
      loaded,
      hiddenCount,
      truncated: true,
    });
  }

  const isTruncationGated = truncatedClusters.length > 0;
  const gatedTotal = truncatedClusters.reduce((sum, c) => sum + c.total, 0);
  const gatedHiddenCount = truncatedClusters.reduce((sum, c) => sum + c.hiddenCount, 0);

  return {
    targetClusterIds: ids,
    isLoading,
    truncatedClusters,
    isTruncationGated,
    gatedTotal,
    gatedHiddenCount,
  };
};
