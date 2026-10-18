import { useEffect, useMemo, useRef } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { useMediaIdentities } from './useMediaIdentities';
import {
  fetchWorkbenchMediaDetail,
  type WorkbenchMediaDetailResponse,
  fetchWorkbenchMedia,
  type WorkbenchMediaItem as WorkbenchMediaItemSchema,
  type WorkbenchMediaResponse as WorkbenchMediaApiResponse,
  type WorkbenchMediaStatus,
} from '../api/workbenchMediaApi';
import { queryKeys } from '../api/queryKeys';
import { type DetectedIdentity } from '../api/recognition';

type WorkbenchMediaItem = WorkbenchMediaItemSchema & {
  identities?: DetectedIdentity[];
};

type WorkbenchMediaResponse = WorkbenchMediaApiResponse;

interface Params {
  page: number;
  perPage: number;
  search?: string;
  status?: WorkbenchMediaStatus;
  enabled: boolean;
}

/** Serialize the page-view key that owns a single next-page prefetch. */
const serializePageKey = (
  page: number,
  perPage: number,
  search: string | undefined,
  status: WorkbenchMediaStatus,
): string => JSON.stringify({ page, perPage, search: search ?? '', status });

export const useWorkbenchMedia = ({ page, perPage, search, status = 'all', enabled }: Params) => {
  const queryClient = useQueryClient();
  /**
   * Once-per-page-key prefetch latch: records the serialized next-page key after
   * issuing its one fetchQuery. Resets when the current page-view key changes.
   * Status-level settle is not enough (placeholderData keeps status 'success'
   * while isFetching); settle is fetch-level below.
   */
  const prefetchedNextKeyRef = useRef<string | null>(null);
  const pageViewKey = serializePageKey(page, perPage, search, status);
  const prevPageViewKeyRef = useRef(pageViewKey);
  if (prevPageViewKeyRef.current !== pageViewKey) {
    prevPageViewKeyRef.current = pageViewKey;
    prefetchedNextKeyRef.current = null;
  }

  const mediaQuery = useQuery<WorkbenchMediaResponse, Error>({
    queryKey: queryKeys.media.workbenchPage({ page, perPage, search, status }),
    queryFn: () => fetchWorkbenchMedia({ page, perPage, search, status }),
    placeholderData: (previousData) => previousData,
    enabled,
  });

  const mediaIds = mediaQuery.data?.items.map((item) => item.id) ?? [];
  const detailQuery = useQuery<WorkbenchMediaDetailResponse, Error>({
    queryKey: queryKeys.media.detailByIds(mediaIds),
    queryFn: () => fetchWorkbenchMediaDetail(mediaIds),
    placeholderData: (previousData) => previousData,
    enabled: enabled && mediaIds.length > 0,
  });
  const identitiesQuery = useMediaIdentities(mediaIds, enabled && mediaIds.length > 0);

  const itemsWithIdentities = useMemo(() => {
    const identitiesByMedia = identitiesQuery.data?.identities_by_media ?? {};
    const detailsByMedia = detailQuery.data?.detailsByMedia ?? {};
    return mediaQuery.data?.items.map((item) => ({
      ...item,
      ...detailsByMedia[String(item.id)],
      identities: identitiesByMedia[String(item.id)] ?? [],
    }));
  }, [detailQuery.data, mediaQuery.data?.items, identitiesQuery.data]);

  useEffect(() => {
    if (!enabled || !mediaQuery.isSuccess) {
      return;
    }
    // Fetch-level settle only: status 'success' is true under placeholderData
    // while the real stage-2 fetch is still in flight.
    if (detailQuery.isFetching || identitiesQuery.isFetching) {
      return;
    }
    // Empty mediaIds: stage-2 queries are disabled (isFetching false). Prefetch
    // is still allowed once page-1 media settled — no stage-2 competitor.
    const totalPages = mediaQuery.data?.totalPages ?? 1;
    const nextPage = page + 1;
    if (nextPage > totalPages) {
      return;
    }

    const nextKey = queryKeys.media.workbenchPage({ page: nextPage, perPage, search, status });
    const nextKeySerialized = serializePageKey(nextPage, perPage, search, status);
    if (prefetchedNextKeyRef.current === nextKeySerialized) {
      return;
    }
    prefetchedNextKeyRef.current = nextKeySerialized;

    void queryClient
      .fetchQuery<WorkbenchMediaResponse>({
        queryKey: nextKey,
        queryFn: () => fetchWorkbenchMedia({ page: nextPage, perPage, search, status }),
      })
      .catch(() => undefined);
  }, [
    enabled,
    mediaQuery.isSuccess,
    mediaQuery.data?.totalPages,
    detailQuery.isFetching,
    identitiesQuery.isFetching,
    page,
    perPage,
    search,
    status,
    queryClient,
  ]);

  // useQuery results are fresh tracked proxies every render; memoize on the
  // leaf fields consumers read so the hook's return identity is stable.
  const detailSurface = useMemo(
    () => ({
      data: detailQuery.data,
      isPending: detailQuery.isPending,
      isLoading: detailQuery.isLoading,
      isFetching: detailQuery.isFetching,
      isError: detailQuery.isError,
      error: detailQuery.error,
      refetch: detailQuery.refetch,
    }),
    [
      detailQuery.data,
      detailQuery.isPending,
      detailQuery.isLoading,
      detailQuery.isFetching,
      detailQuery.isError,
      detailQuery.error,
      detailQuery.refetch,
    ],
  );

  const identitiesSurface = useMemo(
    () => ({
      data: identitiesQuery.data,
      isLoading: identitiesQuery.isLoading,
      isError: identitiesQuery.isError,
      error: identitiesQuery.error,
      isPlaceholderData: identitiesQuery.isPlaceholderData,
      isFetching: identitiesQuery.isFetching,
      refetch: identitiesQuery.refetch,
    }),
    [
      identitiesQuery.data,
      identitiesQuery.isLoading,
      identitiesQuery.isError,
      identitiesQuery.error,
      identitiesQuery.isPlaceholderData,
      identitiesQuery.isFetching,
      identitiesQuery.refetch,
    ],
  );

  return useMemo(
    () => ({
      data: mediaQuery.data,
      isPending: mediaQuery.isPending,
      isFetching: mediaQuery.isFetching,
      isError: mediaQuery.isError,
      isSuccess: mediaQuery.isSuccess,
      refetch: mediaQuery.refetch,
      itemsWithIdentities,
      detailQuery: detailSurface,
      identitiesQuery: identitiesSurface,
    }),
    [
      mediaQuery.data,
      mediaQuery.isPending,
      mediaQuery.isFetching,
      mediaQuery.isError,
      mediaQuery.isSuccess,
      mediaQuery.refetch,
      itemsWithIdentities,
      detailSurface,
      identitiesSurface,
    ],
  );
};

export type { WorkbenchMediaItem, WorkbenchMediaResponse };
