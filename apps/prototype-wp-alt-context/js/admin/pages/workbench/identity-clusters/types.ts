/**
 * Types for Identity Cluster components.
 */

import type { DetectedIdentity, MergeClusterResponse } from '../../../api/recognition';

/**
 * A group of identities belonging to the same cluster.
 */
export interface ClusterGroup {
  /** Unique key for React rendering */
  key: string;
  /** Cluster ID (null for unclustered identities) */
  clusterId: string | null;
  /** User-assigned or auto-generated label */
  label: string | null;
  /** Whether the label was auto-generated */
  isAutoLabel: boolean;
  /** Identities in this cluster */
  members: DetectedIdentity[];
}

/**
 * State for the cluster edit form.
 */
export interface ClusterEditState {
  isEditing: boolean;
  labelInput: string;
  error: string | null;
  lastMerge: MergeClusterResponse | null;
}

/**
 * Actions for cluster edit state reducer.
 */
export type ClusterEditAction =
  | { type: 'START_EDIT'; initialLabel: string }
  | { type: 'CANCEL_EDIT' }
  | { type: 'SET_LABEL'; label: string }
  | { type: 'SET_ERROR'; error: string }
  | { type: 'CLEAR_ERROR' }
  | { type: 'SAVE_SUCCESS' }
  | { type: 'MERGE_SUCCESS'; mergeResult: MergeClusterResponse }
  | { type: 'REVERT_SUCCESS' };
