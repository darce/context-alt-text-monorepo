import { useQuery } from '@tanstack/react-query';

import { fetchMediaIdentities, type MediaIdentitiesResponse } from '../api/recognitionApi';

export const useMediaIdentities = (mediaIds: number[], enabled = true) =>
  useQuery<MediaIdentitiesResponse>({
    queryKey: ['media-identities', mediaIds],
    queryFn: () => fetchMediaIdentities(mediaIds),
    enabled: enabled && mediaIds.length > 0,
    staleTime: 15_000,
    placeholderData: (previousData) => previousData,
  });
