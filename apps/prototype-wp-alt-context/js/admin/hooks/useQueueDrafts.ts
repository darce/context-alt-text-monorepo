import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';

import {
  fetchDescribeRunItems,
  fetchDescriptionHistory,
  type DescriptionHistoryItem,
  type DescribeRunItem,
} from '../api/describeApi';
import { decodeHtmlEntities } from '../utils/decodeHtmlEntities';
import { describeRunItemsQueryKey } from './useDescribeRunApply';

export const QUEUE_DRAFT_SOURCE = {
  DESCRIBE_RUN: 'describe_run',
  DESCRIPTION_HISTORY: 'description_history',
} as const;

export type QueueDraftSource = (typeof QUEUE_DRAFT_SOURCE)[keyof typeof QUEUE_DRAFT_SOURCE];

/** Prefix shared with DescriptionHistoryPage so invalidation refreshes both. */
export const QUEUE_DRAFTS_HISTORY_QUERY_KEY = ['description-history'] as const;

export const QUEUE_DRAFTS_HISTORY_PAGE_SIZE = 50;
export const QUEUE_DRAFTS_HISTORY_MAX_PAGES = 20;

export interface QueueDraft {
  mediaId: number;
  draftText: string;
  existingAlt: boolean;
  runId: string | null;
  source: QueueDraftSource;
}

export interface UseQueueDraftsResult {
  draftsByMediaId: Record<number, QueueDraft>;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  historyTruncated: boolean;
}

type HistoryDraftScan = {
  draftsByMediaId: Record<number, QueueDraft>;
  historyTruncated: boolean;
};

const hasUsableDraft = (text: string | null | undefined): text is string =>
  typeof text === 'string' && text.trim() !== '';

const normalizeRunId = (runId: string | null | undefined): string | null =>
  typeof runId === 'string' && runId.trim() !== '' ? runId.trim() : null;

const sortedWantedMediaIds = (ids: ReadonlySet<number>): number[] =>
  [...ids].sort((left, right) => left - right);

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

  while (
    pagesFetched < QUEUE_DRAFTS_HISTORY_MAX_PAGES &&
    offset < total &&
    remaining.size > 0
  ) {
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
    remaining.size > 0 &&
    pagesFetched >= QUEUE_DRAFTS_HISTORY_MAX_PAGES &&
    !stoppedOnEmptyPage &&
    offset < total;

  return { draftsByMediaId, historyTruncated };
};

/**
 * Queue-side draft lookup. Reads existing describe-run items or description
 * history (no new routes) and keys usable drafts by media id. Never applies.
 */
export const useQueueDrafts = (mediaIds: readonly number[], runId?: string | null): UseQueueDraftsResult => {
  const normalizedRunId = normalizeRunId(runId);
  const wantedIds = useMemo(() => new Set(mediaIds.filter((id) => id > 0)), [mediaIds]);
  const sortedWantedIds = useMemo(() => sortedWantedMediaIds(wantedIds), [wantedIds]);
  const enabled = wantedIds.size > 0;

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

  const draftsByMediaId = useMemo(() => {
    const drafts: Record<number, QueueDraft> = {};
    if (normalizedRunId !== null) {
      for (const item of runQuery.data?.items ?? []) {
        if (!wantedIds.has(item.media_id)) {
          continue;
        }
        const draft = draftFromRunItem(item, normalizedRunId);
        if (draft) {
          drafts[item.media_id] = draft;
        }
      }
      return drafts;
    }
    return historyQuery.data?.draftsByMediaId ?? {};
  }, [historyQuery.data, normalizedRunId, runQuery.data, wantedIds]);

  const activeQuery = normalizedRunId !== null ? runQuery : historyQuery;
  const historyTruncated =
    normalizedRunId === null && (historyQuery.data?.historyTruncated ?? false);

  return {
    draftsByMediaId,
    isLoading: enabled && activeQuery.isLoading,
    isError: enabled && activeQuery.isError,
    error: enabled ? (activeQuery.error ?? null) : null,
    historyTruncated,
  };
};
