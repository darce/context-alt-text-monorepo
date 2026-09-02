import { useMemo } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  applyDescribeRunDrafts,
  fetchDescribeRunItems,
  type ApplyDescribeRunResponse,
  type DescribeRunItem,
} from '../api/describeApi';
import { queryKeys } from '../api/queryKeys';
import { invalidateMediaStats } from './useMediaStats';

export interface DescribeRunApplyBuckets {
  /** Draft present, no existing alt — safe to apply via the primary bulk action. */
  withoutAlt: DescribeRunItem[];
  /** Draft present but the attachment already has alt — needs an explicit overwrite. */
  withExistingAlt: DescribeRunItem[];
  /** No usable draft (failed/skipped/blank) — informational only, never applied. */
  noDraft: DescribeRunItem[];
}

export interface UseDescribeRunApplyResult {
  itemsQuery: ReturnType<typeof useQuery<import('../api/describeApi').DescribeRunItemsResponse, Error>>;
  buckets: DescribeRunApplyBuckets;
  apply: ReturnType<typeof useMutation<ApplyDescribeRunResponse, Error, number[]>>;
}

const hasDraft = (item: DescribeRunItem): boolean =>
  typeof item.alt_text_draft === 'string' && item.alt_text_draft.trim() !== '';

export const describeRunItemsQueryKey = (runId: string | null) => ['describe-run-items', runId] as const;

/**
 * INT-01d: read a completed run's per-item drafts and drive the guarded
 * write-back. Buckets drafts into safe-to-apply (no existing alt), needs-overwrite
 * (existing alt), and no-draft so the History run view can offer one primary bulk
 * action plus explicit per-item overwrite. The apply mutation invalidates the
 * items query so the buckets refresh (existing_alt flips true) after a write.
 */
export const useDescribeRunApply = (runId: string | null): UseDescribeRunApplyResult => {
  const queryClient = useQueryClient();

  const itemsQuery = useQuery({
    queryKey: describeRunItemsQueryKey(runId),
    queryFn: () => {
      // `enabled` gates this to a non-null runId; narrow explicitly rather than
      // asserting so an empty run id can never reach the proxy.
      if (runId === null) {
        return Promise.reject(new Error('No describe run selected.'));
      }
      return fetchDescribeRunItems(runId);
    },
    enabled: runId !== null,
  });

  const buckets = useMemo<DescribeRunApplyBuckets>(() => {
    const items = itemsQuery.data?.items ?? [];
    const withoutAlt: DescribeRunItem[] = [];
    const withExistingAlt: DescribeRunItem[] = [];
    const noDraft: DescribeRunItem[] = [];
    for (const item of items) {
      if (!hasDraft(item)) {
        noDraft.push(item);
      } else if (item.existing_alt) {
        withExistingAlt.push(item);
      } else {
        withoutAlt.push(item);
      }
    }
    return { withoutAlt, withExistingAlt, noDraft };
  }, [itemsQuery.data]);

  const apply = useMutation<ApplyDescribeRunResponse, Error, number[]>({
    mutationFn: (overwriteMediaIds) => {
      if (runId === null) {
        // No run selected — surface an error state rather than hitting the API
        // with an empty run id (which would 404).
        return Promise.reject(new Error('No describe run selected.'));
      }
      return applyDescribeRunDrafts(runId, overwriteMediaIds);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: describeRunItemsQueryKey(runId) });
      // Applied drafts land on workbench rows; the items query only refreshes
      // the History run view, so the library list must refetch too (WBUX-6 G1).
      void queryClient.invalidateQueries({ queryKey: queryKeys.media.workbench() });
      // Bulk apply is the write most likely to move dashboard coverage. Ask the
      // server for a fresh missing-alt total — do not derive counts from response
      // buckets [rg-015]. onSuccess fires for full *and* partial applies: if any
      // alts landed, the counters are stale [BR-125][RLSE-04].
      invalidateMediaStats(queryClient);
    },
  });

  return { itemsQuery, buckets, apply };
};
