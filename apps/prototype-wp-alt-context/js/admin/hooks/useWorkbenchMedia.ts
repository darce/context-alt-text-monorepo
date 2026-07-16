import { useEffect, useMemo } from 'react';
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

export const useWorkbenchMedia = ({ page, perPage, search, status = 'all', enabled }: Params) => {
  const queryClient = useQueryClient();

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
    if (!mediaQuery.isSuccess) {
      return;
    }
    const totalPages = mediaQuery.data?.totalPages ?? 1;
    const nextPage = page + 1;
    if (nextPage > totalPages) {
      return;
    }

    const nextKey = queryKeys.media.workbenchPage({ page: nextPage, perPage, search, status });
    void queryClient
      .fetchQuery<WorkbenchMediaResponse>({
        queryKey: nextKey,
        queryFn: () => fetchWorkbenchMedia({ page: nextPage, perPage, search, status }),
      })
      .catch(() => undefined);
  }, [mediaQuery.isSuccess, mediaQuery.data?.totalPages, page, perPage, search, status, queryClient]);

  // useQuery results are fresh tracked proxies every render; memoize on the
  // leaf fields consumers read so the hook's return identity is stable.
  const detailSurface = useMemo(
    () => ({
      data: detailQuery.data,
      isPending: detailQuery.isPending,
      isLoading: detailQuery.isLoading,
      isFetching: detailQuery.isFetching,
      isError: detailQuery.isError,
      refetch: detailQuery.refetch,
    }),
    [
      detailQuery.data,
      detailQuery.isPending,
      detailQuery.isLoading,
      detailQuery.isFetching,
      detailQuery.isError,
      detailQuery.refetch,
    ],
  );

  const identitiesSurface = useMemo(
    () => ({
      data: identitiesQuery.data,
      isLoading: identitiesQuery.isLoading,
      isError: identitiesQuery.isError,
      refetch: identitiesQuery.refetch,
    }),
    [identitiesQuery.data, identitiesQuery.isLoading, identitiesQuery.isError, identitiesQuery.refetch],
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
