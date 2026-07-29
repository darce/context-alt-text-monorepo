import { type QueryClient, useMutation, useQueryClient } from '@tanstack/react-query';

import {
  correctDescriptionHistoryItem,
  DESCRIPTION_CORRECTION_CODE,
  resolveDescribeErrorCode,
  resolveDescribeErrorDataField,
  type DescriptionHistoryItem,
} from '../api/describeApi';
import { queryKeys } from '../api/queryKeys';
import type { WorkbenchMediaItem, WorkbenchMediaResponse } from '../api/workbenchMediaApi';

interface CorrectMediaAltVariables {
  mediaId: number;
  altText: string;
}

/**
 * Snapshot of a workbench row that landed a partial correction (alt written,
 * human-edit marker failed). Kept so a later sibling success invalidate+refetch
 * of the missing-status list cannot silently unmount the row and its role=alert
 * [RLSE-04][RLSE-05]. Cleared only when this mediaId fully succeeds — never by
 * sibling traffic, cancel, or total failure.
 */
interface PinnedPartialRow {
  item: WorkbenchMediaItem;
  placements: { queryKey: readonly unknown[]; index: number }[];
}

const pinnedPartialRows = new Map<number, PinnedPartialRow>();
const guardedClients = new WeakSet<QueryClient>();

/** Test isolation for the module-level pin store. */
export const _resetPinnedPartialsForTests = (): void => {
  pinnedPartialRows.clear();
};

// Takes unknown: the cache event's queryKey is loosely typed at the query-core
// boundary, so narrow here rather than trusting the declared shape.
const isWorkbenchMediaQueryKey = (queryKey: unknown): boolean =>
  Array.isArray(queryKey) && queryKey[0] === 'media' && queryKey[1] === 'workbench';

/**
 * Re-insert any pinned partial rows that a workbench page refetch dropped.
 * Missing-status pages exclude items whose alt now exists, which is exactly
 * the partial case — those rows must stay mounted until the operator finishes
 * the correction (full success clears the pin).
 */
const remountPinnedPartialsIntoCache = (queryClient: QueryClient): void => {
  if (pinnedPartialRows.size === 0) {
    return;
  }

  for (const [mediaId, pin] of pinnedPartialRows) {
    for (const { queryKey, index } of pin.placements) {
      const data = queryClient.getQueryData<WorkbenchMediaResponse>(queryKey);
      if (!data?.items) {
        continue;
      }
      if (data.items.some((item) => item.id === mediaId)) {
        continue;
      }
      const insertAt = Math.min(Math.max(index, 0), data.items.length);
      const items = [...data.items];
      items.splice(insertAt, 0, pin.item);
      queryClient.setQueryData<WorkbenchMediaResponse>(queryKey, {
        ...data,
        items,
      });
    }
  }
};

/**
 * Subscribe once per QueryClient so any workbench cache write (invalidate
 * refetch, setQueryData, etc.) re-merges outstanding partial rows. Fire-and-
 * forget success invalidation must not block isPending (WBUX-5-S2C3A-BR-05),
 * so the remount runs from the cache update rather than awaiting invalidate.
 */
const ensurePartialPinGuard = (queryClient: QueryClient): void => {
  if (guardedClients.has(queryClient)) {
    return;
  }
  guardedClients.add(queryClient);
  queryClient.getQueryCache().subscribe((event) => {
    if (pinnedPartialRows.size === 0) {
      return;
    }
    if (event.type !== 'updated') {
      return;
    }
    if (!isWorkbenchMediaQueryKey(event.query.queryKey)) {
      return;
    }
    remountPinnedPartialsIntoCache(queryClient);
  });
};

/**
 * Patch cached workbench pages so the operator sees the alt that storage already
 * holds, without invalidateQueries (which would refetch the missing-status list
 * and unmount the row before the alert can be read — WBUX-5-BR-51).
 *
 * `altText` must be the server-reported stored value (`stored_alt_text`), never
 * the raw request payload — sanitize_text_field may have stripped markup/whitespace.
 *
 * Also pins the row so a later sibling success's media.all invalidation cannot
 * drop it from a missing-status refetch while the partial alert is still unread.
 */
const reconcileAndPinPartialAlt = (queryClient: QueryClient, mediaId: number, altText: string): void => {
  const workbenchQueries = queryClient.getQueriesData<WorkbenchMediaResponse>({
    queryKey: queryKeys.media.workbench(),
  });

  let snapshot: WorkbenchMediaItem | null = null;
  const placements: { queryKey: readonly unknown[]; index: number }[] = [];

  for (const [queryKey, data] of workbenchQueries) {
    if (!data?.items) {
      continue;
    }
    const index = data.items.findIndex((item) => item.id === mediaId);
    if (index < 0) {
      continue;
    }
    const updated: WorkbenchMediaItem = { ...data.items[index], altText };
    snapshot = updated;
    placements.push({ queryKey, index });
    queryClient.setQueryData<WorkbenchMediaResponse>(queryKey, {
      ...data,
      items: data.items.map((item) => (item.id === mediaId ? updated : item)),
    });
  }

  if (snapshot && placements.length > 0) {
    pinnedPartialRows.set(mediaId, { item: snapshot, placements });
  }
};

export const useCorrectMediaAlt = () => {
  const queryClient = useQueryClient();
  ensurePartialPinGuard(queryClient);

  return useMutation<DescriptionHistoryItem, Error, CorrectMediaAltVariables>({
    mutationFn: ({ mediaId, altText }) => correctDescriptionHistoryItem(mediaId, altText),
    // Fire-and-forget: awaiting invalidateQueries holds isPending until the whole
    // media tree refetches, which leaves the commit button on "Saving…" after the
    // write already landed and can unmount the row (missing-status list) before
    // the component's own onSuccess runs (WBUX-5-S2C3A-BR-05).
    //
    // Clear this mediaId's partial pin *before* invalidating so a full success
    // does not get re-mounted onto the missing list. Sibling successes leave
    // other pins alone — only this id is dismissed [RLSE-04].
    onSuccess: (_data, variables) => {
      pinnedPartialRows.delete(variables.mediaId);
      void queryClient.invalidateQueries({ queryKey: queryKeys.media.all });
    },
    // Partial success (alt written, human-edit marker failed): reconcile the
    // specific cached row in place from server-reported stored_alt_text only.
    // If that field is absent, leave the cache alone — stale-but-real beats a
    // fabricated request-body guess ([rg-015]). Gate on the stable error code —
    // never on message text. Do not invalidate: a refetch on missing-status
    // lists drops the row and destroys the role=alert the operator still needs
    // [RLSE-04][RLSE-05]. Pin the reconciled row so a *sibling* success's
    // invalidate cannot drop it either.
    onError: (error, variables) => {
      if (resolveDescribeErrorCode(error) !== DESCRIPTION_CORRECTION_CODE.PARTIAL) {
        return;
      }
      // Null-only gate: empty string is a legitimate stored alt (sanitize_text_field
      // of a blank correction) and must still reconcile [TEST-15][rg-015].
      const storedAltText = resolveDescribeErrorDataField(error, 'stored_alt_text');
      if (storedAltText === null) {
        return;
      }
      reconcileAndPinPartialAlt(queryClient, variables.mediaId, storedAltText);
    },
  });
};
