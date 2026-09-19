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

/** Same key as DescriptionHistoryPage so queue and history share one cache. */
export const QUEUE_DRAFTS_HISTORY_QUERY_KEY = ['description-history'] as const;

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
}

const hasUsableDraft = (text: string | null | undefined): text is string =>
  typeof text === 'string' && text.trim() !== '';

const normalizeRunId = (runId: string | null | undefined): string | null =>
  typeof runId === 'string' && runId.trim() !== '' ? runId.trim() : null;

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

/**
 * Queue-side draft lookup. Reads existing describe-run items or description
 * history (no new routes) and keys usable drafts by media id. Never applies.
 */
export const useQueueDrafts = (mediaIds: readonly number[], runId?: string | null): UseQueueDraftsResult => {
  const normalizedRunId = normalizeRunId(runId);
  const wantedIds = useMemo(() => new Set(mediaIds.filter((id) => id > 0)), [mediaIds]);
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
    queryKey: QUEUE_DRAFTS_HISTORY_QUERY_KEY,
    queryFn: () => fetchDescriptionHistory({ limit: 50, offset: 0 }),
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
    for (const item of historyQuery.data?.items ?? []) {
      if (!wantedIds.has(item.media_id)) {
        continue;
      }
      const draft = draftFromHistoryItem(item);
      if (draft) {
        drafts[item.media_id] = draft;
      }
    }
    return drafts;
  }, [historyQuery.data, normalizedRunId, runQuery.data, wantedIds]);

  const activeQuery = normalizedRunId !== null ? runQuery : historyQuery;

  return {
    draftsByMediaId,
    isLoading: enabled && activeQuery.isLoading,
    isError: enabled && activeQuery.isError,
    error: enabled ? (activeQuery.error ?? null) : null,
  };
};
