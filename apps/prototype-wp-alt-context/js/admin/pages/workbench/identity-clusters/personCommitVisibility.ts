/**
 * E21-5 Slice 3 — per-kind person-commit visibility (plan § action matrix).
 *
 * ASSIGNMENT: only when clusterId is non-null/non-empty.
 * MERGE: never.
 * NAME / CLUSTER: always (clusterId required on the item).
 */

import { NEXT_ACTION_KIND, type NextActionKind } from './reviewQueueDriver';

export const hasPersonCommitClusterId = (clusterId: string | null | undefined): boolean =>
  typeof clusterId === 'string' && clusterId.trim().length > 0;

/**
 * Whether the person-commit primary chrome renders for this queue kind + cluster.
 */
export const shouldShowPersonCommit = (
  kind: NextActionKind,
  clusterId: string | null | undefined,
): boolean => {
  switch (kind) {
    case NEXT_ACTION_KIND.MERGE:
    case NEXT_ACTION_KIND.NONE:
      return false;
    case NEXT_ACTION_KIND.ASSIGNMENT:
      return hasPersonCommitClusterId(clusterId);
    case NEXT_ACTION_KIND.NAME:
    case NEXT_ACTION_KIND.CLUSTER:
      return hasPersonCommitClusterId(clusterId);
    default:
      return false;
  }
};

/**
 * Person-commit is the chromatic primary for NAME/CLUSTER; on ASSIGNMENT it is
 * available alongside Accept/Reject when clusterId is present.
 */
export const isPersonCommitPrimaryKind = (kind: NextActionKind): boolean =>
  kind === NEXT_ACTION_KIND.NAME || kind === NEXT_ACTION_KIND.CLUSTER;
