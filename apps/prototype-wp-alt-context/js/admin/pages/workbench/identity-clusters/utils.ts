/**
 * Utility functions for identity cluster operations.
 */

import type { DetectedIdentity } from '../../../api/recognition';
import { isHumanLabeledTarget } from './suggestionProjection';
import type { ClusterGroup } from './types';

/** Bucket key for identities with neither a person nor a cluster (GPUFLOW-2 C5). */
export const UNGROUPED_GROUP_KEY = 'ungrouped';

export const isUngroupedGroup = (group: ClusterGroup): boolean => group.key === UNGROUPED_GROUP_KEY;

/**
 * Identity ids for the single inline-suggestion batch.
 *
 * Unlabeled grouped clusters contribute their anchor (`members[0]`); ungrouped
 * residue contributes every member. Grouping changes presentation only (rg-002).
 */
export const unlabeledSuggestionBatchIds = (groups: readonly ClusterGroup[]): string[] => {
  const ids: string[] = [];
  for (const group of groups) {
    if (group.label) {
      continue;
    }
    if (isUngroupedGroup(group)) {
      for (const member of group.members) {
        if (member.identity_id) {
          ids.push(member.identity_id);
        }
      }
      continue;
    }
    const anchorId = group.members[0]?.identity_id;
    if (anchorId) {
      ids.push(anchorId);
    }
  }
  return ids;
};

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
 * Identities with neither a person nor a cluster collapse into one `ungrouped`
 * bucket (GPUFLOW-2 C5). They are not distinct people.
 *
 * @param identities - Array of detected identities
 * @returns Array of cluster groups, with ungrouped residue last when present
 */
export const groupIdentitiesByClusters = (identities: DetectedIdentity[]): ClusterGroup[] => {
  const groups = new Map<string, ClusterGroup>();
  // Tracks whether a group has already locked in a human label so a later
  // auto/empty label can never displace it (IDCHIP-1-GROUP-R-01).
  const hasHumanLabel = new Map<string, boolean>();

  identities.forEach((identity) => {
    const personId = identity.person_id || null;
    const clusterKey =
      personId !== null
        ? `person:${personId}`
        : identity.cluster_id != null
          ? `cluster:${identity.cluster_id}`
          : UNGROUPED_GROUP_KEY;

    if (!groups.has(clusterKey)) {
      groups.set(clusterKey, {
        key: clusterKey,
        clusterId: clusterKey === UNGROUPED_GROUP_KEY ? null : (identity.cluster_id ?? null),
        personId: clusterKey === UNGROUPED_GROUP_KEY ? null : personId,
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
    const group = groups.get(clusterKey);
    if (!group) {
      return;
    }
    if (identity.cluster_id != null) {
      group.identityClusterIds![identity.identity_id] = identity.cluster_id;
      if (!group.clusterIds!.includes(identity.cluster_id)) {
        group.clusterIds!.push(identity.cluster_id);
      }
    }

    if (clusterKey !== UNGROUPED_GROUP_KEY) {
      const trimmedLabel = identity.cluster_label?.trim() ?? '';
      const isHumanCandidate = !identity.is_auto_label && isHumanLabeledTarget(trimmedLabel);
      if (isHumanCandidate && !hasHumanLabel.get(clusterKey)) {
        group.label = identity.cluster_label;
        group.isAutoLabel = false;
        hasHumanLabel.set(clusterKey, true);
      } else if (!hasHumanLabel.get(clusterKey) && group.label === null && trimmedLabel.length > 0) {
        group.label = identity.cluster_label;
        group.isAutoLabel = Boolean(identity.is_auto_label);
      }
    }

    if (identity.clustering_pending) {
      group.clusteringPending = true;
    }

    group.members.push(identity);
  });

  // A group formed from an unbound first member (clusterId null) but later
  // members that do carry a cluster id should still resolve to one of those
  // ids so display/auto-label gating (formatClusterLabel) applies (BR-01).
  const ordered: ClusterGroup[] = [];
  let ungrouped: ClusterGroup | undefined;
  groups.forEach((group) => {
    if (group.clusterId === null && group.clusterIds && group.clusterIds.length > 0) {
      group.clusterId = group.clusterIds[0];
    }
    if (isUngroupedGroup(group)) {
      ungrouped = group;
      return;
    }
    ordered.push(group);
  });
  if (ungrouped) {
    ordered.push(ungrouped);
  }
  return ordered;
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
