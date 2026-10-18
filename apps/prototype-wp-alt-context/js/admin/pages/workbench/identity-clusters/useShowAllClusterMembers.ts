/**
 * Client-side paging over the cluster-members envelope for show-all expansion.
 *
 * First page comes from React Query; subsequent pages append via sequential
 * `fetchClusterMembers` calls that respect limit/offset and never request
 * beyond `total` [RES-05]. The first-page `truncated` flag stays available for
 * the Slice-5 bulk disabled-while-truncated gate.
 *
 * Slice-5 gate contract:
 * - `truncated` is the FIRST-PAGE ENVELOPE flag — the server's statement that
 *   the cluster has more members than one page. It never flips when this hook
 *   finishes client-side expansion.
 * - `isFullyLoaded` is INSTANCE-LOCAL — it reflects this hook instance's
 *   expansion state only and resets on remount, cluster switch, or refetch.
 * - The Slice-5 bulk disabled-while-truncated gate must therefore consume the
 *   query-cache envelope (`membersResponse.truncated`), NOT this hook's
 *   `isFullyLoaded`, which is a per-instance UI affordance signal.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import {
  fetchClusterMembers,
  type ClusterIdentity,
  type ClusterMembersResponse,
} from '../../../api/recognition';
import { queryKeys } from '../../../api/queryKeys';

/**
 * S4-03 [rg-007]: slack added to the declared-total page count for the show-all
 * round-trip backstop, covering a snapshot that shifts (under-filled pages) under
 * us. The loop can never fan out beyond `ceil(total/limit) + EXPAND_PAGE_SLACK`.
 */
const EXPAND_PAGE_SLACK = 2;

export interface UseShowAllClusterMembersResult {
  members: ClusterIdentity[];
  /** First-page envelope; null while loading/error. */
  membersResponse: ClusterMembersResponse | undefined;
  isLoading: boolean;
  isError: boolean;
  /** Envelope truncated flag from the first page (Slice-5 bulk gate). */
  truncated: boolean;
  total: number;
  /** True once the client has loaded every member up to `total` (instance-local). */
  isFullyLoaded: boolean;
  isExpanding: boolean;
  expandError: string | null;
  showAll: () => Promise<void>;
  /** Re-run the first-page members query (UI-05 error-branch recovery). */
  refetch: () => void;
}

export const useShowAllClusterMembers = (clusterId: string): UseShowAllClusterMembersResult => {
  const [expandedMembers, setExpandedMembers] = useState<ClusterIdentity[] | null>(null);
  const [isExpanding, setIsExpanding] = useState(false);
  const [expandError, setExpandError] = useState<string | null>(null);
  // Bumped whenever the expansion baseline changes (cluster switch, refetch).
  // In-flight showAll loops capture the generation at start and discard their
  // results when it moves, so a stale closure never applies old-cluster pages.
  const generationRef = useRef(0);

  useEffect(() => {
    generationRef.current += 1;
    setExpandedMembers(null);
    setIsExpanding(false);
    setExpandError(null);
  }, [clusterId]);

  const {
    data: membersResponse,
    isLoading,
    isError,
    refetch: refetchMembers,
  } = useQuery({
    queryKey: queryKeys.clusters.memberList(clusterId),
    queryFn: () => fetchClusterMembers(clusterId),
    enabled: Boolean(clusterId),
    retry: false,
  });

  // Any refetch that changes the envelope identity (invalidation after a
  // mutation, background refetch) invalidates the expanded snapshot: drop back
  // to the honest first page — show-all can be clicked again.
  useEffect(() => {
    generationRef.current += 1;
    setExpandedMembers(null);
    setIsExpanding(false);
    // A-04: a new envelope snapshot invalidates any prior expansion error too —
    // otherwise a stale 'Unable to load…' banner lingers over the honest first page.
    setExpandError(null);
  }, [membersResponse]);

  const firstPageMembers = membersResponse?.members ?? [];
  const truncated = membersResponse?.truncated ?? false;
  const total = membersResponse?.total ?? 0;
  const members = expandedMembers ?? firstPageMembers;
  const isFullyLoaded = expandedMembers !== null || !truncated;

  const showAll = useCallback(async (): Promise<void> => {
    if (!membersResponse || !membersResponse.truncated || isExpanding) {
      return;
    }

    const generation = generationRef.current;
    setIsExpanding(true);
    setExpandError(null);

    try {
      const pageLimit = Math.max(1, membersResponse.limit);
      const total = membersResponse.total;
      // S4-03: explicit round-trip cap. `offset < total` already bounds a well-behaved
      // server, but this makes the ceiling explicit and contains a shifting/malformed
      // snapshot that under-fills pages so `offset` crawls toward `total`.
      const maxPages = Math.ceil(total / pageLimit) + EXPAND_PAGE_SLACK;

      // S4-02: dedup by identity_id. Offset paging over a mutating membership can
      // re-return an already-seen member (a row inserted before the window shifts it);
      // appending blindly would duplicate it. `offset` tracks the SERVER window position
      // (raw page length), independent of how many rows survive dedup.
      const seen = new Set<string>();
      const accumulated: ClusterIdentity[] = [];
      for (const member of membersResponse.members) {
        if (!seen.has(member.identity_id)) {
          seen.add(member.identity_id);
          accumulated.push(member);
        }
      }
      let offset = membersResponse.members.length;
      let pages = 0;

      while (accumulated.length < total && offset < total) {
        if (pages >= maxPages) {
          // Round-trip ceiling hit before convergence: the list changed under us.
          setExpandError('Unable to load all members — the list changed while loading.');
          return;
        }
        pages += 1;

        const remaining = total - offset;
        const pageSize = Math.min(pageLimit, remaining);
        if (pageSize <= 0) {
          break;
        }

        const page = await fetchClusterMembers(clusterId, {
          limit: pageSize,
          offset,
        });

        if (generationRef.current !== generation) {
          return;
        }

        if (page.members.length === 0) {
          // Empty page while accumulated < total: the snapshot shifted under
          // us. Surface the error and keep the honest first page + affordance
          // instead of stamping the run complete.
          setExpandError('Unable to load remaining members.');
          return;
        }

        let added = 0;
        for (const member of page.members) {
          if (!seen.has(member.identity_id)) {
            seen.add(member.identity_id);
            accumulated.push(member);
            added += 1;
          }
        }
        // Advance by the server window, not the deduped count [RES-05].
        offset += page.members.length;

        if (added === 0) {
          // The window returned only already-seen members — snapshot shifted; stop
          // honestly rather than looping to the page cap.
          setExpandError('Unable to load remaining members.');
          return;
        }
      }

      if (generationRef.current !== generation) {
        return;
      }
      // C-02: the loop can exit via `offset >= total` while dedup left fewer unique
      // members than `total` — overlapping windows under a mid-expand membership shift
      // (page re-returns an already-seen identity_id, so `offset` reaches `total` before
      // `accumulated` does). Surface the shortfall instead of stamping a partial set as
      // fully loaded, which would silently hide members the server still has.
      if (accumulated.length < total) {
        setExpandError('Unable to load all members — the list changed while loading.');
        return;
      }
      setExpandedMembers(accumulated.slice(0, total));
    } catch (error) {
      if (generationRef.current !== generation) {
        return;
      }
      const message = error instanceof Error ? error.message : 'Unable to load remaining members.';
      setExpandError(message);
    } finally {
      if (generationRef.current === generation) {
        setIsExpanding(false);
      }
    }
  }, [clusterId, isExpanding, membersResponse]);

  const refetch = useCallback((): void => {
    void refetchMembers();
  }, [refetchMembers]);

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
    refetch,
  };
};
