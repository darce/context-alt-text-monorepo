import { useEffect, useMemo } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { useMediaIdentities } from './useMediaIdentities';
import type { WorkbenchMediaItem as WorkbenchMediaItemSchema } from '../api/generated';
import { queryKeys } from '../api/queryKeys';
import { fetchMediaIdentities, type MediaIdentitiesResponse, type DetectedIdentity } from '../api/recognition';

type WorkbenchMediaItem = WorkbenchMediaItemSchema & {
  identities?: DetectedIdentity[];
};

interface WorkbenchMediaResponse {
  items: WorkbenchMediaItem[];
  total: number;
  totalPages: number;
}

interface Params {
  page: number;
  perPage: number;
  search?: string;
  enabled: boolean;
}

interface FetchParams {
  page: number;
  perPage: number;
  search?: string;
}

const isWorkbenchMediaResponse = (value: unknown): value is WorkbenchMediaResponse =>
  Boolean(
    value &&
      typeof value === 'object' &&
      Array.isArray((value as WorkbenchMediaResponse).items) &&
      typeof (value as WorkbenchMediaResponse).total === 'number' &&
      typeof (value as WorkbenchMediaResponse).totalPages === 'number',
  );

const fetchWorkbenchMedia = async ({ page, perPage, search }: FetchParams): Promise<WorkbenchMediaResponse> => {
  const config = window.AltContextAdmin;
  if (!config?.endpoints?.workbenchMedia) {
    throw new Error('Workbench media endpoint is not available.');
  }

  const requestUrl = new URL(config.endpoints.workbenchMedia, window.location.origin);
  requestUrl.searchParams.set('page', String(page));
  requestUrl.searchParams.set('per_page', String(perPage));
  requestUrl.searchParams.set('status', 'missing');

  if (search) {
    requestUrl.searchParams.set('search', search);
  }

  const response = await fetch(requestUrl.toString(), {
    headers: {
      'X-WP-Nonce': config.nonce,
      Accept: 'application/json',
    },
    credentials: 'same-origin',
  });

  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }

  const data: unknown = await response.json();
  if (!isWorkbenchMediaResponse(data)) {
    throw new Error('Workbench media response was malformed.');
  }

  return data;
};

export const useWorkbenchMedia = ({ page, perPage, search, enabled }: Params) => {
  const queryClient = useQueryClient();

  const mediaQuery = useQuery<WorkbenchMediaResponse, Error>({
    queryKey: queryKeys.media.workbenchPage({ page, perPage, search }),
    queryFn: () => fetchWorkbenchMedia({ page, perPage, search }),
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

    let canceled = false;
    const nextKey = queryKeys.media.workbenchPage({ page: nextPage, perPage, search });
    const prefetchNextPage = async (): Promise<void> => {
      const nextData = await queryClient.fetchQuery<WorkbenchMediaResponse>({
        queryKey: nextKey,
        queryFn: () => fetchWorkbenchMedia({ page: nextPage, perPage, search }),
      });

      if (canceled || !nextData) {
        return;
      }
      const nextMediaIds = nextData.items.map((item) => item.id);
      if (nextMediaIds.length === 0) {
        return;
      }
      await queryClient.prefetchQuery<MediaIdentitiesResponse>({
        queryKey: queryKeys.media.identitiesByIds(nextMediaIds),
        queryFn: () => fetchMediaIdentities(nextMediaIds),
      });
    };

    void prefetchNextPage().catch(() => undefined);

    return () => {
      canceled = true;
    };
  }, [mediaQuery.isSuccess, mediaQuery.data?.totalPages, page, perPage, search, queryClient]);

  return {
    ...mediaQuery,
    itemsWithIdentities,
    identitiesQuery,
  };
};

export type { WorkbenchMediaItem, WorkbenchMediaResponse };
