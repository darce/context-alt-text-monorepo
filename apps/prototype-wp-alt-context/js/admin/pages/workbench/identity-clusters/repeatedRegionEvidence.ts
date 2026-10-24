import type { BoundingBox, DetectedIdentity } from '../../../api/recognition';
import { identityGroupKey } from './utils';

export interface RepeatedRegionObservation {
  identityId: string;
  mediaId: number;
  bbox: Readonly<BoundingBox>;
  groupKey: string;
  personId: string | null;
  clusterId: string | null;
}

export interface RepeatedRegion {
  regionKey: string;
  mediaId: number;
  bbox: Readonly<BoundingBox>;
  groupKeys: readonly string[];
  observations: readonly RepeatedRegionObservation[];
}

export interface RepeatedRegionPool {
  loadedObservationCount: number;
  eligibleObservationCount: number;
  abstainedIdentityIds: readonly string[];
}

export interface RepeatedRegionEvidence {
  regions: readonly RepeatedRegion[];
  byGroupKey: ReadonlyMap<string, readonly RepeatedRegion[]>;
  pool: RepeatedRegionPool;
}

export interface RepeatedRegionEvidenceView {
  groupKey: string;
  regions: readonly RepeatedRegion[];
  pool: RepeatedRegionPool;
  groupLabels: ReadonlyMap<string, string | null>;
}

type RetainedTuple = Omit<RepeatedRegionObservation, 'bbox'> & { bbox: Readonly<BoundingBox> | null };
const compareText = (left: string, right: string): number => (left < right ? -1 : left > right ? 1 : 0);

const retainedTuple = (identity: DetectedIdentity): RetainedTuple => {
  // Preserve the grouping contract's empty/falsy-person normalization verbatim.
  let personId: string | null = null;
  if (identity.person_id) {
    personId = identity.person_id;
  }
  return {
    identityId: identity.identity_id,
    mediaId: identity.media_id,
    groupKey: identityGroupKey(identity),
    personId,
    clusterId: identity.cluster_id ?? null,
    bbox:
      identity.bbox !== null && typeof identity.bbox === 'object'
        ? { x: identity.bbox.x, y: identity.bbox.y, width: identity.bbox.width, height: identity.bbox.height }
        : null,
  };
};

// Complete structural agreement, including hidden cluster refs and signed zero.
// A serialized signature would lose types/delimiters/NaN/-0; no copy may win.
const sameRetainedTuple = (left: RetainedTuple, right: RetainedTuple): boolean =>
  Object.is(left.identityId, right.identityId) &&
  Object.is(left.mediaId, right.mediaId) &&
  Object.is(left.groupKey, right.groupKey) &&
  Object.is(left.personId, right.personId) &&
  Object.is(left.clusterId, right.clusterId) &&
  (left.bbox === null || right.bbox === null
    ? left.bbox === right.bbox
    : Object.is(left.bbox.x, right.bbox.x) &&
      Object.is(left.bbox.y, right.bbox.y) &&
      Object.is(left.bbox.width, right.bbox.width) &&
      Object.is(left.bbox.height, right.bbox.height));

const isSupported = (tuple: RetainedTuple): tuple is RepeatedRegionObservation => {
  const box = tuple.bbox;
  return (
    Number.isInteger(tuple.mediaId) &&
    tuple.mediaId > 0 &&
    box !== null &&
    [box.x, box.y, box.width, box.height].every((n) => typeof n === 'number' && Number.isFinite(n)) &&
    box.x >= 0 &&
    box.y >= 0 &&
    box.width > 1 &&
    box.height > 1
  );
};

/** Exact loaded coordinates only; no person recognition, overlap threshold or mutations. */
export const buildRepeatedRegionEvidence = (identities: readonly DetectedIdentity[]): RepeatedRegionEvidence => {
  const copies = new Map<string, { tuple: RetainedTuple; disagrees: boolean }>();
  for (const identity of identities) {
    if (typeof identity.identity_id !== 'string' || !identity.identity_id.trim()) {
      continue;
    }
    const tuple = retainedTuple(identity);
    const existing = copies.get(tuple.identityId);
    if (existing) {
      existing.disagrees ||= !sameRetainedTuple(existing.tuple, tuple);
    } else {
      copies.set(tuple.identityId, { tuple, disagrees: false });
    }
  }

  const abstainedIdentityIds: string[] = [];
  const byRegion = new Map<string, RepeatedRegionObservation[]>();
  let eligibleObservationCount = 0;
  for (const [id, { tuple, disagrees }] of copies) {
    if (disagrees) {
      abstainedIdentityIds.push(id);
      continue;
    }
    if (!isSupported(tuple)) {
      continue;
    }
    eligibleObservationCount += 1;
    const { x, y, width, height } = tuple.bbox;
    // Only validated finite numbers enter this key. String(n) merges +/-0,
    // exactly as strict coordinate equality does between distinct records.
    const key = `${tuple.mediaId}|${x}|${y}|${width}|${height}`;
    const observations = byRegion.get(key) ?? [];
    observations.push(tuple);
    byRegion.set(key, observations);
  }

  const regions: RepeatedRegion[] = [];
  for (const [regionKey, observations] of byRegion) {
    const groupKeys = [...new Set(observations.map((o) => o.groupKey))].sort(compareText);
    if (groupKeys.length < 2) {
      continue;
    }
    observations.sort((a, b) => compareText(a.groupKey, b.groupKey) || compareText(a.identityId, b.identityId));
    const first = observations[0];
    if (first) {
      regions.push({ regionKey, mediaId: first.mediaId, bbox: first.bbox, groupKeys, observations });
    }
  }
  regions.sort(
    (a, b) =>
      a.mediaId - b.mediaId ||
      a.bbox.x - b.bbox.x ||
      a.bbox.y - b.bbox.y ||
      a.bbox.width - b.bbox.width ||
      a.bbox.height - b.bbox.height,
  );
  const byGroupKey = new Map<string, RepeatedRegion[]>();
  for (const region of regions) {
    for (const groupKey of region.groupKeys) {
      const entries = byGroupKey.get(groupKey) ?? [];
      entries.push(region);
      byGroupKey.set(groupKey, entries);
    }
  }
  return {
    regions,
    byGroupKey,
    pool: {
      loadedObservationCount: copies.size,
      eligibleObservationCount,
      abstainedIdentityIds: abstainedIdentityIds.sort(compareText),
    },
  };
};

export const repeatedRegionViewForGroup = (
  evidence: RepeatedRegionEvidence,
  groupKey: string,
  groupLabels: ReadonlyMap<string, string | null>,
): RepeatedRegionEvidenceView | undefined => {
  const regions = evidence.byGroupKey.get(groupKey);
  return regions?.length ? { groupKey, regions, pool: evidence.pool, groupLabels } : undefined;
};
