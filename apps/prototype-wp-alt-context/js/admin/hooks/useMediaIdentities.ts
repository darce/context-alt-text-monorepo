import { useQuery } from '@tanstack/react-query';

import { queryKeys } from '../api/queryKeys';
import { fetchMediaIdentities, type MediaIdentitiesResponse } from '../api/recognition';

export const useMediaIdentities = (mediaIds: number[], enabled = true) =>
  useQuery<MediaIdentitiesResponse>({
    queryKey: queryKeys.media.identitiesByIds(mediaIds),
    queryFn: () => fetchMediaIdentities(mediaIds),
    enabled: enabled && mediaIds.length > 0,
    staleTime: 15_000,
    placeholderData: (previousData) => previousData,
  });
