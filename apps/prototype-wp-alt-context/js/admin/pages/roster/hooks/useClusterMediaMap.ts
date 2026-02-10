import { useEffect, useState } from 'react';

import type { ClusterSummary } from '../../../api/recognition';
import { fetchMediaMeta, type MediaMeta } from '../../../api/mediaApi';

export type MediaMap = Record<number, MediaMeta>;

export const useClusterMediaMap = (clusters: ClusterSummary[], additionalMediaIds: number[] = []): MediaMap => {
  const [mediaMap, setMediaMap] = useState<MediaMap>({});

  useEffect(() => {
    const mediaIds = new Set<number>();
    clusters.forEach((cluster) => {
      cluster.sample_identities.forEach((identity) => mediaIds.add(identity.media_id));
      if (cluster.representative_identity?.media_id) {
        mediaIds.add(cluster.representative_identity.media_id);
      }
    });
    additionalMediaIds.forEach((id) => mediaIds.add(id));

    const missing = Array.from(mediaIds).filter((id) => !(id in mediaMap));
    if (missing.length === 0) {
      return;
    }

    let cancelled = false;
    const loadMeta = async (): Promise<void> => {
      const entries = await Promise.all(
        missing.map(async (id) => {
          const meta = await fetchMediaMeta(id);
          return [id, meta] as const;
        }),
      );
      if (cancelled) {
        return;
      }
      setMediaMap((prev) => {
        const next = { ...prev };
        entries.forEach(([id, meta]) => {
          next[id] = meta;
        });
        return next;
      });
    };

    void loadMeta();

    return () => {
      cancelled = true;
    };
  }, [clusters, additionalMediaIds, mediaMap]);

  return mediaMap;
};
