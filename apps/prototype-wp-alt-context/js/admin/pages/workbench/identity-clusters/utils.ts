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
 * Group identities by person, falling back to cluster ID.
 *
 * Identities without a cluster ID are grouped individually.
 *
 * @param identities - Array of detected identities
 * @returns Array of cluster groups
 */
export const groupIdentitiesByClusters = (identities: DetectedIdentity[]): ClusterGroup[] => {
  const groups = new Map<string, ClusterGroup>();
  // Tracks whether a group has already locked in a human label so a later
  // auto/empty label can never displace it (IDCHIP-1-GROUP-R-01).
  const hasHumanLabel = new Map<string, boolean>();

  identities.forEach((identity) => {
    const personId = identity.person_id || null;
    const clusterKey = personId !== null
      ? `person:${personId}`
      : identity.cluster_id != null
        ? `cluster:${identity.cluster_id}`
        : `identity:${identity.identity_id}`;

    if (!groups.has(clusterKey)) {
      groups.set(clusterKey, {
        key: clusterKey,
        clusterId: identity.cluster_id ?? null,
        personId,
        clusterIds: [],
        label: null,
        isAutoLabel: false,
        clusteringPending: Boolean(identity.clustering_pending),
        members: [],
        identityClusterIds: {},
      });
      hasHumanLabel.set(clusterKey, false);
    }

    // If any member is pending, mark the whole group as pending
    const group = groups.get(clusterKey)!;
    if (identity.cluster_id != null) {
      group.identityClusterIds![identity.identity_id] = identity.cluster_id;
      if (!group.clusterIds!.includes(identity.cluster_id)) {
        group.clusterIds!.push(identity.cluster_id);
      }
    }

    const trimmedLabel = identity.cluster_label?.trim() ?? '';
    const isHumanCandidate = trimmedLabel.length > 0 && !identity.is_auto_label;
    if (isHumanCandidate && !hasHumanLabel.get(clusterKey)) {
      group.label = identity.cluster_label;
      group.isAutoLabel = false;
      hasHumanLabel.set(clusterKey, true);
    } else if (!hasHumanLabel.get(clusterKey) && group.label === null && trimmedLabel.length > 0) {
      group.label = identity.cluster_label;
      group.isAutoLabel = Boolean(identity.is_auto_label);
    }

    if (identity.clustering_pending) {
      group.clusteringPending = true;
    }

    group.members.push(identity);
  });

  // A group formed from an unbound first member (clusterId null) but later
  // members that do carry a cluster id should still resolve to one of those
  // ids so display/auto-label gating (formatClusterLabel) applies (BR-01).
  groups.forEach((group) => {
    if (group.clusterId === null && group.clusterIds && group.clusterIds.length > 0) {
      group.clusterId = group.clusterIds[0];
    }
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
