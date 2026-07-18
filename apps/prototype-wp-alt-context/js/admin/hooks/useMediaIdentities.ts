import { useQuery } from '@tanstack/react-query';

import { queryKeys } from '../api/queryKeys';
import { fetchMediaIdentities, type MediaIdentitiesResponse } from '../api/recognition';
import { gateRefetchInterval } from '../utils/recognitionCooldown';

/**
 * Check if any identities are pending clustering assignment.
 * When faces are detected, they may not immediately have a cluster assigned
 * because clustering runs asynchronously. This helper determines if we should
 * poll for updates.
 */
const hasPendingClustering = (data: MediaIdentitiesResponse | undefined): boolean => {
  if (!data?.identities_by_media) {
    return false;
  }
  return Object.values(data.identities_by_media).some((identities) =>
    identities.some((identity) => identity.clustering_pending),
  );
};

export const useMediaIdentities = (mediaIds: number[], enabled = true) =>
  useQuery<MediaIdentitiesResponse>({
    queryKey: queryKeys.media.identitiesByIds(mediaIds),
    queryFn: () => fetchMediaIdentities(mediaIds),
    enabled: enabled && mediaIds.length > 0,
    // Deliberate exception to shared retry: conditional query already stops polling on error;
    // next scheduled poll (recognition cooldown in slice 2) is the retry. [RES-06]
    retry: false,
    staleTime: 15_000,
    placeholderData: (previousData) => previousData,
    // Auto-poll every 3 seconds when there are identities pending cluster assignment.
    // This provides automatic updates when clustering completes without manual refresh.
    refetchInterval: gateRefetchInterval((query) => {
      if (query.state.status === 'error') {
        return false;
      }
      return hasPendingClustering(query.state.data) ? 3000 : false;
    }),
  });
