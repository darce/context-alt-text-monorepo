/**
 * Canonical cluster-drawer modes [sr-007].
 * Derived only from real ClusterSummary fields — never invented topology.
 */
export const CLUSTER_DRAWER_STATES = {
  ASSIGNED: 'assigned',
  UNRESOLVED: 'unresolved',
  SINGLETON_PROPOSAL: 'singleton-proposal',
} as const;

export type ClusterDrawerState = (typeof CLUSTER_DRAWER_STATES)[keyof typeof CLUSTER_DRAWER_STATES];

export const getClusterPersonUuid = (cluster: { person_uuid?: string | null }): string | null => {
  const raw = cluster.person_uuid;
  if (typeof raw !== 'string') {
    return null;
  }
  const trimmed = raw.trim();
  return trimmed.length > 0 ? trimmed : null;
};

export const getClusterDrawerState = (cluster: {
  person_uuid?: string | null;
  identity_count: number;
}): ClusterDrawerState => {
  if (getClusterPersonUuid(cluster) !== null) {
    return CLUSTER_DRAWER_STATES.ASSIGNED;
  }
  if (cluster.identity_count === 1) {
    return CLUSTER_DRAWER_STATES.SINGLETON_PROPOSAL;
  }
  return CLUSTER_DRAWER_STATES.UNRESOLVED;
};
