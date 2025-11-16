import { useEffect, useState } from 'react';

import type { ClusterSummary } from '../../../api/recognitionApi';
import { fetchMediaMeta, type MediaMeta } from '../utils/mediaMeta';

export type MediaMap = Record<number, MediaMeta>;

export const useClusterMediaMap = (clusters: ClusterSummary[], additionalMediaIds: number[] = []): MediaMap => {
  const [mediaMap, setMediaMap] = useState<MediaMap>({});

  useEffect(() => {
    const mediaIds = new Set<number>();
    clusters.forEach((cluster) => {
      const identities = cluster.sample_identities ?? cluster.sample_faces ?? [];
      identities.forEach((identity: ClusterSummary['sample_identities'][number]) => mediaIds.add(identity.media_id));
      const representativeMedia =
        cluster.representative_identity?.media_id ?? cluster.representative_face?.media_id ?? null;
      if (representativeMedia) {
        mediaIds.add(representativeMedia);
      }
    });
    additionalMediaIds.forEach((id) => mediaIds.add(id));

    const missing = Array.from(mediaIds).filter((id) => !(id in mediaMap));
    if (missing.length === 0) {
      return;
    }

    let cancelled = false;
    (async () => {
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
    })();

    return () => {
      cancelled = true;
    };
  }, [clusters, additionalMediaIds, mediaMap]);

  return mediaMap;
};
