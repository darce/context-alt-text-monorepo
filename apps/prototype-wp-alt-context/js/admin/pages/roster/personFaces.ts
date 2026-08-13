import type { RosterEntry } from '../../api/rosterApi';
import type { RosterEntryInstance } from '../../api/generated/roster-entry';

export interface PersonScrubFace {
  identityId: string;
  clusterId: string;
  clusterIndex: number;
  mediaId: number;
  mediaUrl: string | null;
  bbox: RosterEntryInstance['bbox'];
  similarity: number | null;
  similarityThreshold: number | null;
  isRepresentative: boolean;
}

export function collectPersonFaces(entry: RosterEntry): PersonScrubFace[] {
  const faces: PersonScrubFace[] = [];

  entry.clusters.forEach((cluster, clusterIndex) => {
    const representativeId = cluster.representative_identity?.identity_id ?? null;
    const seen = new Set<string>();

    const pushFace = (instance: RosterEntryInstance, isRepresentative: boolean): void => {
      if (seen.has(instance.identity_id)) {
        return;
      }
      seen.add(instance.identity_id);
      faces.push({
        identityId: instance.identity_id,
        clusterId: cluster.cluster_id,
        clusterIndex,
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
}

export function resolveVisibleFaceId(
  visibleIds: readonly string[],
  requestedId: string | null,
  previousId: string | null,
): string | null {
  if (requestedId && visibleIds.includes(requestedId)) {
    return requestedId;
  }
  if (previousId && visibleIds.includes(previousId)) {
    return previousId;
  }
  return visibleIds[0] ?? null;
}

export function assertSelectedFace(
  face: PersonScrubFace | null,
): asserts face is PersonScrubFace {
  if (face == null) {
    throw new Error('Expected a selected roster face');
  }
}
