/**
 * Utility functions for identity cluster operations.
 */

import type { DetectedIdentity } from '../../../api/recognition';
import { isHumanLabeledTarget } from './suggestionProjection';
import type { ClusterGroup } from './types';

/**
 * Format a cluster label for display.
 *
 * - If no cluster ID, returns the raw label as-is
 * - If a user-assigned label exists (not auto-shape), returns that
 * - Otherwise returns null; the caller owns unlabeled copy
 *
 * Display honesty: even when `isAutoLabel` is false/omitted, auto-shape labels
 * (`cluster-*`) must not render as confirmed person names (E21-15-BR-27).
 *
 * @param clusterId - The cluster UUID or null
 * @param rawLabel - The label from the API
 * @param isAutoLabel - Whether the label was auto-generated
 * @returns Human display label, or null when the caller should supply unlabeled copy
 */
export const formatClusterLabel = (
  clusterId: string | null,
  rawLabel: string | null,
  isAutoLabel: boolean,
): string | null => {
  if (!clusterId) {
    return rawLabel;
  }

  if (rawLabel && !isAutoLabel && isHumanLabeledTarget(rawLabel)) {
    return rawLabel;
  }

  return null;
};

/**
 * Group identities by their cluster ID.
 *
 * Identities without a cluster ID are grouped individually.
 *
 * @param identities - Array of detected identities
 * @returns Array of cluster groups
 */
export const groupIdentitiesByClusters = (identities: DetectedIdentity[]): ClusterGroup[] => {
  const groups = new Map<string, ClusterGroup>();

  identities.forEach((identity) => {
    const clusterKey = identity.cluster_id ?? `identity-${identity.identity_id}`;

    if (!groups.has(clusterKey)) {
      groups.set(clusterKey, {
        key: clusterKey,
        clusterId: identity.cluster_id ?? null,
        label: identity.cluster_label ?? null,
        isAutoLabel: Boolean(identity.is_auto_label),
        clusteringPending: Boolean(identity.clustering_pending),
        members: [],
      });
    }

    // If any member is pending, mark the whole group as pending
    const group = groups.get(clusterKey)!;
    if (identity.clustering_pending) {
      group.clusteringPending = true;
    }

    group.members.push(identity);
  });

  return Array.from(groups.values());
};

/**
 * Get the editable cluster ID from a cluster group.
 *
 * Falls back to the first member's cluster ID if the group doesn't have one.
 *
 * @param cluster - The cluster group
 * @returns Cluster ID that can be used for API operations, or null
 */
export const getEditableClusterId = (cluster: ClusterGroup): string | null => {
  if (cluster.clusterId) {
    return cluster.clusterId;
  }

  const memberWithCluster = cluster.members.find((member) => member.cluster_id);
  return memberWithCluster?.cluster_id ?? null;
};

export const filterEditableClusterMatch = <T extends { id: string }>(
  match: T | null,
  editableClusterId?: string | null,
): T | null => {
  if (!match || !editableClusterId) {
    return match;
  }

  return match.id === editableClusterId ? null : match;
};
