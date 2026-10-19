import { useCallback, useEffect, useMemo } from 'react';
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  fetchDescribeRunItems,
  fetchDescribeRuns,
  fetchDescriptionHistory,
  type DescriptionHistoryItem,
  type DescribeRunItem,
} from '../api/describeApi';
import { decodeHtmlEntities } from '../utils/decodeHtmlEntities';
import { describeRunItemsQueryKey } from './useDescribeRunApply';
import { queryKeys } from '../api/queryKeys';
import type { SyncHealthResponse } from '../api/recognition';
import { invalidateDescriptionDrafts } from '../utils/invalidateDescriptionDrafts';

export const QUEUE_DRAFT_SOURCE = {
  DESCRIBE_RUN: 'describe_run',
  DESCRIPTION_HISTORY: 'description_history',
} as const;

export type QueueDraftSource = (typeof QUEUE_DRAFT_SOURCE)[keyof typeof QUEUE_DRAFT_SOURCE];

/** Shared prefix for saved history and per-image run history invalidation. */
export const QUEUE_DRAFTS_HISTORY_QUERY_KEY = ['description-history'] as const;

export const QUEUE_DRAFTS_HISTORY_PAGE_SIZE = 50;
export const QUEUE_DRAFTS_HISTORY_MAX_PAGES = 20;

export interface QueueDraft {
  mediaId: number;
  draftText: string;
  existingAlt: boolean;
  runId: string | null;
  source: QueueDraftSource;
  createdAt?: number;
  namingRefreshUnavailable?: boolean;
}

export interface UseQueueDraftsResult {
  draftsByMediaId: Record<number, QueueDraft>;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  historyTruncated: boolean;
  historyByMediaId: Record<number, QueueDraft[]>;
  hasOlderDescriptions: boolean;
  isLoadingOlder: boolean;
  loadOlderDescriptions: () => void;
  historyPartial: boolean;
}

interface HistoryDraftScan {
  draftsByMediaId: Record<number, QueueDraft>;
  historyTruncated: boolean;
}

const hasUsableDraft = (text: string | null | undefined): text is string =>
  typeof text === 'string' && text.trim() !== '';

const normalizeRunId = (runId: string | null | undefined): string | null =>
  typeof runId === 'string' && runId.trim() !== '' ? runId.trim() : null;

const sortedWantedMediaIds = (ids: ReadonlySet<number>): number[] => [...ids].sort((left, right) => left - right);

export const queueDraftsHistoryQueryKey = (wantedIds: readonly number[]) =>
  [...QUEUE_DRAFTS_HISTORY_QUERY_KEY, ...sortedWantedMediaIds(new Set(wantedIds))] as const;

const draftFromRunItem = (item: DescribeRunItem, runId: string): QueueDraft | null => {
  const draftText = item.alt_text_draft;
  if (!hasUsableDraft(draftText)) {
    return null;
  }
  return {
    mediaId: item.media_id,
    draftText,
    existingAlt: item.existing_alt,
    runId,
    source: QUEUE_DRAFT_SOURCE.DESCRIBE_RUN,
    ...(item.provenance?.naming_refresh?.status === 'unavailable' ? { namingRefreshUnavailable: true } : {}),
  };
};

const draftFromHistoryItem = (item: DescriptionHistoryItem): QueueDraft | null => {
  if (item.human_edit != null) {
    return null;
  }
  const generated = decodeHtmlEntities(item.generated_alt_text);
  const current = decodeHtmlEntities(item.current_alt_text);
  if (!hasUsableDraft(generated)) {
    return null;
  }
  if (generated.trim() === current.trim()) {
    return null;
  }
  return {
    mediaId: item.media_id,
    draftText: generated,
    existingAlt: current.trim() !== '',
    runId: null,
    source: QUEUE_DRAFT_SOURCE.DESCRIPTION_HISTORY,
  };
};

const scanHistoryDrafts = async (wantedIds: ReadonlySet<number>): Promise<HistoryDraftScan> => {
  const draftsByMediaId: Record<number, QueueDraft> = {};
  const remaining = new Set(wantedIds);
  let offset = 0;
  let pagesFetched = 0;
  let total = Number.POSITIVE_INFINITY;
  let stoppedOnEmptyPage = false;

  while (pagesFetched < QUEUE_DRAFTS_HISTORY_MAX_PAGES && offset < total && remaining.size > 0) {
    const page = await fetchDescriptionHistory({
      limit: QUEUE_DRAFTS_HISTORY_PAGE_SIZE,
      offset,
    });
    pagesFetched += 1;
    total = page.total;

    if (page.items.length === 0) {
      stoppedOnEmptyPage = true;
      break;
    }

    for (const item of page.items) {
      if (!remaining.has(item.media_id) || item.media_id in draftsByMediaId) {
        continue;
      }
      const draft = draftFromHistoryItem(item);
      if (draft) {
        draftsByMediaId[item.media_id] = draft;
        remaining.delete(item.media_id);
      }
    }

    offset += QUEUE_DRAFTS_HISTORY_PAGE_SIZE;
  }

  const historyTruncated =
    remaining.size > 0 && pagesFetched >= QUEUE_DRAFTS_HISTORY_MAX_PAGES && !stoppedOnEmptyPage && offset < total;

  return { draftsByMediaId, historyTruncated };
};

/**
 * Queue-side draft lookup. Reads existing describe-run items or description
 * history and keys usable drafts by media id. Never applies.
 */
export const useQueueDrafts = (mediaIds: readonly number[], runId?: string | null): UseQueueDraftsResult => {
  const queryClient = useQueryClient();
  const normalizedRunId = normalizeRunId(runId);
  const wantedIds = useMemo(() => new Set(mediaIds.filter((id) => id > 0)), [mediaIds]);
  const sortedWantedIds = useMemo(() => sortedWantedMediaIds(wantedIds), [wantedIds]);
  const enabled = wantedIds.size > 0;

  useEffect(() => {
    if (!enabled) {
      return;
    }
    // Observe the existing sync-health owner; do not add another poller.
    let previous = queryClient.getQueryData<SyncHealthResponse>(queryKeys.sync.health());
    return queryClient.getQueryCache().subscribe((event) => {
      const rawKey: unknown = event.query.queryKey;
      const key: readonly unknown[] = Array.isArray(rawKey) ? (rawKey as readonly unknown[]) : [];
      if (event.type !== 'updated' || key[0] !== 'sync' || key[1] !== 'health') {
        return;
      }
      const current = queryClient.getQueryData<SyncHealthResponse>(queryKeys.sync.health());
      const drained =
        previous?.outbox?.state === 'ok' &&
        previous.outbox.pending > 0 &&
        current?.outbox?.state === 'ok' &&
        current.outbox.pending === 0;
      const pulled = current?.last_pull?.ok && current.last_pull.at && previous?.last_pull?.at !== current.last_pull.at;
      previous = current;
      if (drained || pulled) {
        invalidateDescriptionDrafts(queryClient);
      }
    });
  }, [enabled, queryClient]);

  const readRun = useCallback(
    (id: string) =>
      queryClient.fetchQuery({
        queryKey: describeRunItemsQueryKey(id),
        queryFn: () => fetchDescribeRunItems(id),
      }),
    [queryClient],
  );

  // readRun is a cache transport callback; media/run IDs contain the data identity.
  // eslint-disable-next-line @tanstack/query/exhaustive-deps
  const runHistory = useInfiniteQuery({
    queryKey: [...QUEUE_DRAFTS_HISTORY_QUERY_KEY, 'runs', sortedWantedIds, normalizedRunId],
    initialPageParam: 0,
    queryFn: async ({ pageParam }) => {
      const page = await fetchDescribeRuns(sortedWantedIds, pageParam);
      const drafts: QueueDraft[] = [];
      let failures = 0;
      let firstError: unknown;
      let index = 0;
      // A page holds at most five runs. Two readers bound network/worker pressure.
      const results: QueueDraft[][] = page.items.map(() => []);
      const read = async (): Promise<void> => {
        while (index < page.items.length) {
          const position = index++;
          const record = page.items[position];
          try {
            const response = await readRun(record.run_id);
            for (const item of response.items) {
              if (!sortedWantedIds.includes(item.media_id) || !record.media_ids.includes(item.media_id)) {
                continue;
              }
              const draft = draftFromRunItem(item, record.run_id);
              if (draft) {
                results[position].push({ ...draft, createdAt: record.created_at });
              }
            }
          } catch (error) {
            failures += 1;
            firstError ??= error;
          }
        }
      };
      await Promise.all([read(), read()]);
      if (page.items.length > 0 && failures === page.items.length) {
        throw firstError;
      }
      for (const result of results) {
        drafts.push(...result);
      }
      return { drafts, nextOffset: page.next_offset, partial: failures > 0 };
    },
    getNextPageParam: (page) => page.nextOffset,
    enabled,
  });

  const runQuery = useQuery({
    queryKey: describeRunItemsQueryKey(normalizedRunId),
    queryFn: () => {
      if (normalizedRunId === null) {
        return Promise.reject(new Error('No describe run selected.'));
      }
      return fetchDescribeRunItems(normalizedRunId);
    },
    enabled: enabled && normalizedRunId !== null,
  });

  const historyQuery = useQuery({
    queryKey: queueDraftsHistoryQueryKey(sortedWantedIds),
    queryFn: () => scanHistoryDrafts(new Set(sortedWantedIds)),
    enabled: enabled && normalizedRunId === null,
  });

  const historyByMediaId = useMemo(() => {
    const history: Record<number, QueueDraft[]> = {};
    const add = (draft: QueueDraft): void => {
      const versions = (history[draft.mediaId] ??= []);
      if (!versions.some((item) => item.runId === draft.runId && item.draftText === draft.draftText)) {
        versions.push(draft);
      }
    };
    for (const page of runHistory.data?.pages ?? []) {
      for (const draft of page.drafts) {
        add(draft);
      }
    }
    if (normalizedRunId !== null) {
      for (const item of runQuery.data?.items ?? []) {
        if (!wantedIds.has(item.media_id)) {
          continue;
        }
        const draft = draftFromRunItem(item, normalizedRunId);
        if (draft) {
          add(draft);
        }
      }
    }
    for (const draft of Object.values(historyQuery.data?.draftsByMediaId ?? {})) {
      add(draft);
    }
    return history;
  }, [normalizedRunId, runQuery.data, wantedIds, runHistory.data, historyQuery.data]);

  const draftsByMediaId = useMemo(() => {
    const drafts: Record<number, QueueDraft> = {};
    for (const [mediaId, versions] of Object.entries(historyByMediaId)) {
      const draft = normalizedRunId === null ? versions[0] : versions.find((item) => item.runId === normalizedRunId);
      if (draft) {
        drafts[Number(mediaId)] = draft;
      }
    }
    return drafts;
  }, [historyByMediaId, normalizedRunId]);

  const activeQuery = normalizedRunId !== null ? runQuery : runHistory;
  const historyTruncated = normalizedRunId === null && (historyQuery.data?.historyTruncated ?? false);
  return {
    draftsByMediaId,
    historyByMediaId,
    isLoading: enabled && (activeQuery.isLoading || (normalizedRunId === null && historyQuery.isLoading)),
    isError:
      enabled && ((activeQuery.isError && !activeQuery.data) || (normalizedRunId === null && historyQuery.isError)),
    error: enabled ? (activeQuery.error ?? historyQuery.error ?? null) : null,
    historyTruncated,
    hasOlderDescriptions: runHistory.hasNextPage,
    isLoadingOlder: runHistory.isFetchingNextPage,
    loadOlderDescriptions: () => {
      void runHistory.fetchNextPage();
    },
    historyPartial: runHistory.isFetchNextPageError || (runHistory.data?.pages.some((page) => page.partial) ?? false),
  };
};
