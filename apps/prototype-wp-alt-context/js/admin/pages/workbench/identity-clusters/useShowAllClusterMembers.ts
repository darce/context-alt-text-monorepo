/**
 * Client-side paging over the cluster-members envelope for show-all expansion.
 *
 * First page comes from React Query; subsequent pages append via sequential
 * `fetchClusterMembers` calls that respect limit/offset and never request
 * beyond `total` [RES-05]. The first-page `truncated` flag stays available for
 * the Slice-5 bulk disabled-while-truncated gate.
 */

import { useCallback, useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import {
  fetchClusterMembers,
  type ClusterIdentity,
  type ClusterMembersResponse,
} from '../../../api/recognition';
import { queryKeys } from '../../../api/queryKeys';

export interface UseShowAllClusterMembersResult {
  members: ClusterIdentity[];
  /** First-page envelope; null while loading/error. */
  membersResponse: ClusterMembersResponse | undefined;
  isLoading: boolean;
  isError: boolean;
  /** Envelope truncated flag from the first page (Slice-5 bulk gate). */
  truncated: boolean;
  total: number;
  /** True once the client has loaded every member up to `total`. */
  isFullyLoaded: boolean;
  isExpanding: boolean;
  expandError: string | null;
  showAll: () => Promise<void>;
}

export const useShowAllClusterMembers = (clusterId: string): UseShowAllClusterMembersResult => {
  const [expandedMembers, setExpandedMembers] = useState<ClusterIdentity[] | null>(null);
  const [isExpanding, setIsExpanding] = useState(false);
  const [expandError, setExpandError] = useState<string | null>(null);

  useEffect(() => {
    setExpandedMembers(null);
    setIsExpanding(false);
    setExpandError(null);
  }, [clusterId]);

  const {
    data: membersResponse,
    isLoading,
    isError,
  } = useQuery({
    queryKey: queryKeys.clusters.memberList(clusterId),
    queryFn: () => fetchClusterMembers(clusterId),
    enabled: Boolean(clusterId),
  });

  const firstPageMembers = membersResponse?.members ?? [];
  const truncated = membersResponse?.truncated ?? false;
  const total = membersResponse?.total ?? 0;
  const members = expandedMembers ?? firstPageMembers;
  const isFullyLoaded = expandedMembers !== null || !truncated;

  const showAll = useCallback(async (): Promise<void> => {
    if (!membersResponse || !membersResponse.truncated || isExpanding) {
      return;
    }

    setIsExpanding(true);
    setExpandError(null);

    try {
      const pageLimit = Math.max(1, membersResponse.limit);
      let accumulated = [...membersResponse.members];
      let offset = accumulated.length;

      while (offset < membersResponse.total) {
        const remaining = membersResponse.total - offset;
        const pageSize = Math.min(pageLimit, remaining);
        if (pageSize <= 0) {
          break;
        }

        const page = await fetchClusterMembers(clusterId, {
          limit: pageSize,
          offset,
        });

        if (page.members.length === 0) {
          break;
        }

        accumulated = [...accumulated, ...page.members];
        offset = accumulated.length;

        // Never walk past the declared total [RES-05].
        if (accumulated.length >= membersResponse.total) {
          break;
        }
      }

      setExpandedMembers(accumulated.slice(0, membersResponse.total));
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unable to load remaining members.';
      setExpandError(message);
    } finally {
      setIsExpanding(false);
    }
  }, [clusterId, isExpanding, membersResponse]);

  return {
    members,
    membersResponse,
    isLoading,
    isError,
    truncated,
    total,
    isFullyLoaded,
    isExpanding,
    expandError,
    showAll,
  };
};
