import { useEffect, useMemo } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { useMediaIdentities } from './useMediaIdentities';
import {
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
  const identitiesQuery = useMediaIdentities(mediaIds, enabled && mediaIds.length > 0);

  const itemsWithIdentities = useMemo(() => {
    const identitiesByMedia = identitiesQuery.data?.identities_by_media ?? {};
    return mediaQuery.data?.items.map((item) => ({
      ...item,
      identities: identitiesByMedia[String(item.id)] ?? [],
    }));
  }, [mediaQuery.data?.items, identitiesQuery.data]);

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

  return {
    ...mediaQuery,
    itemsWithIdentities,
    identitiesQuery,
  };
};

export type { WorkbenchMediaItem, WorkbenchMediaResponse };
