import { __, sprintf } from '@wordpress/i18n';

import type { RosterEntry } from '../../api/rosterApi';
import type { RosterEntryInstance } from '../../api/generated/roster-entry';

export interface PersonScrubFace {
  faceId: string;
  identityId: string;
  clusterId: string;
  clusterIndex: number;
  instanceOrdinal: number;
  mediaId: number;
  mediaUrl: string | null;
  bbox: RosterEntryInstance['bbox'];
  similarity: number | null;
  similarityThreshold: number | null;
  isRepresentative: boolean;
}

export const toPersonFaceId = (clusterId: string, identityId: string): string => `${clusterId}:${identityId}`;

export const identityIdFromFaceId = (faceId: string): string => {
  const separator = faceId.indexOf(':');
  if (separator <= 0 || separator === faceId.length - 1) {
    return faceId;
  }
  return faceId.slice(separator + 1);
};

export const collectPersonFaces = (entry: RosterEntry): PersonScrubFace[] => {
  const faces: PersonScrubFace[] = [];

  entry.clusters.forEach((cluster, clusterIndex) => {
    const representativeId = cluster.representative_identity?.identity_id ?? null;
    const seen = new Set<string>();
    let instanceOrdinal = 0;

    const pushFace = (instance: RosterEntryInstance, isRepresentative: boolean): void => {
      if (seen.has(instance.identity_id)) {
        return;
      }
      seen.add(instance.identity_id);
      instanceOrdinal += 1;
      faces.push({
        faceId: toPersonFaceId(cluster.cluster_id, instance.identity_id),
        identityId: instance.identity_id,
        clusterId: cluster.cluster_id,
        clusterIndex,
        instanceOrdinal,
        mediaId: instance.media_id,
        mediaUrl: instance.media_url,
        bbox: instance.bbox,
        similarity: instance.similarity,
        similarityThreshold: instance.similarity_threshold ?? null,
        isRepresentative,
      });
    };

    for (const instance of cluster.instances) {
      pushFace(instance, representativeId === instance.identity_id);
    }

    const representative = cluster.representative_identity;
    if (representative) {
      pushFace(representative, true);
    }
  });

  return faces;
};

export const resolveVisibleFaceId = (
  visibleIds: readonly string[],
  requestedId: string | null,
  previousId: string | null,
): string | null => {
  if (requestedId) {
    if (visibleIds.includes(requestedId)) {
      return requestedId;
    }
    if (!requestedId.includes(':')) {
      const firstIdentityMatch = visibleIds.find((id) => identityIdFromFaceId(id) === requestedId);
      if (firstIdentityMatch) {
        return firstIdentityMatch;
      }
    }
  }
  if (previousId && visibleIds.includes(previousId)) {
    return previousId;
  }
  return visibleIds[0] ?? null;
};

export const getSelectedFacePreviewLabel = (face: PersonScrubFace): string =>
  sprintf(
    __('Selected face from media %d in face group %d', 'alt-context'),
    face.mediaId,
    face.clusterIndex + 1,
  );

export const assertSelectedFace = (face: PersonScrubFace | null): asserts face is PersonScrubFace => {
  if (face == null) {
    throw new Error('Expected a selected roster face');
  }
};
