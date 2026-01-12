import type { ClusterSummary } from '../types/cluster';
import type { ClusterIdentity } from '../types/identity';
import type { ClusterGroup } from '../../../pages/workbench/identity-clusters/types';
import type { DetectedIdentity } from '../types/identity';

/**
 * @module clusterAdapter
 *
 * Transforms backend ClusterSummary types into frontend ClusterGroup types.
 *
 * **Usage**:
 * ```typescript
 * import { toClusterGroup } from '../api/recognition/adapters/clusterAdapter';
 *
 * const groups = clusters.map(toClusterGroup);
 * ```
 *
 * This adapter defines the type boundary between API responses and UI components.
 */

/**
 * Convert an API ClusterSummary to a UI ClusterGroup.
 */
export const toClusterGroup = (summary: ClusterSummary): ClusterGroup => {
  return {
    key: `cluster-${summary.id}`,
    clusterId: summary.id,
    label: summary.label,
    isAutoLabel: summary.is_auto_label ?? false,
    members: summary.sample_identities.map((identity) => toDetectedIdentity(identity, summary)),
  };
};

/**
 * Convert a ClusterIdentity (from summary) to a DetectedIdentity (for UI).
 */
export const toDetectedIdentity = (identity: ClusterIdentity, summary: ClusterSummary): DetectedIdentity => {
  return {
    identity_id: identity.identity_id,
    media_id: identity.media_id,
    // Context fields from the cluster
    cluster_id: summary.id,
    cluster_label: summary.label,
    is_auto_label: summary.is_auto_label ?? false,
    // Fields from ClusterIdentity
    bbox: identity.bbox,
    confidence: identity.confidence,
    similarity: identity.similarity,
    thumbnail_url: identity.thumbnail_url,
    media_url: identity.media_url,
    // Defaults for missing fields
    representative_id: null,
    is_pinned: false,
    detected_at: undefined,
    debug_metrics: null,
  };
};
