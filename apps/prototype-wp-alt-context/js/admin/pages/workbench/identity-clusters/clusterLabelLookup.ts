/**
 * Remote exact-label lookup for the duplicate guard (FEBT1G-H-04).
 *
 * The lookup gates a WRITE, so it must fail CLOSED. The previous shape returned
 * `ClusterLabelMatch | null` and mapped both "no matching cluster" and every non-abort
 * request failure onto the same `null`; the save flow reads `null` as permission to
 * create or rename, so a transient lookup failure silently bypassed duplicate protection
 * (REF-01 "callee returns X-or-null the caller branch-checks → return an outcome enum";
 * REF-33 "null means absent *or* error *or* unknown → eliminate multi-meaning null flags").
 *
 * Note the asymmetry with `useLiveReviewTarget`'s probe, which correctly fails OPEN:
 * closing an operator's review pane on a transient probe failure is itself destructive.
 * Same `null`, opposite correct default — which is exactly why the outcome must be
 * explicit rather than encoded in a shared sentinel.
 */

import { __ } from '@wordpress/i18n';

import { listRecognitionClusters, type ClusterSummary } from '../../../api/recognition';
import { classifyError } from '../../../utils/appError';
import { createLogger, redactEndpoint, withRequestId } from '../../../utils/logger';
import { isAbortError } from './clusterMutationUtils';
import { isHumanLabeledTarget } from './suggestionProjection';
import type { ClusterLabelMatch } from './useClusterMatchAction';

const log = createLogger('identityClusters.clusterLabelLookup');

/** Outcome of a remote exact-label lookup (sr-007: one canonical status set). */
export const CLUSTER_LABEL_LOOKUP_STATUS = {
  /** The lookup ran and no other cluster carries this label. */
  NONE: 'none',
  /** The lookup ran and found a conflicting cluster. */
  MATCH: 'match',
  /** The caller cancelled; not evidence either way. */
  ABORTED: 'aborted',
  /** The lookup could not run. NOT evidence that the label is free. */
  LOOKUP_FAILED: 'lookup_failed',
} as const;

export type ClusterLabelLookupStatus =
  (typeof CLUSTER_LABEL_LOOKUP_STATUS)[keyof typeof CLUSTER_LABEL_LOOKUP_STATUS];

export type ClusterLabelLookup =
  | { readonly status: typeof CLUSTER_LABEL_LOOKUP_STATUS.NONE }
  | { readonly status: typeof CLUSTER_LABEL_LOOKUP_STATUS.MATCH; readonly match: ClusterLabelMatch }
  | { readonly status: typeof CLUSTER_LABEL_LOOKUP_STATUS.ABORTED }
  | { readonly status: typeof CLUSTER_LABEL_LOOKUP_STATUS.LOOKUP_FAILED; readonly cause: unknown };

/**
 * Thrown by the `ClusterLabelMatch | null` adapter when the lookup could not run.
 * Legacy callers that branch on `null` therefore fail closed by default: the throw
 * propagates to their catch instead of being read as "no duplicate".
 */
export class ClusterLabelLookupError extends Error {
  public readonly lookupCause: unknown;

  public constructor(lookupCause: unknown) {
    super(getClusterLabelLookupFailedMessage());
    this.name = 'ClusterLabelLookupError';
    this.lookupCause = lookupCause;
  }
}

export const getClusterLabelLookupFailedMessage = (): string =>
  __('Could not check whether that name is already in use. Please try again.', 'alt-context');

/**
 * BR-17: auto `cluster-*` labels are never merge/assign targets, so they are not
 * duplicate-guard matches for this lookup either.
 */
export const resolveClusterLabelMatch = (
  clusters: readonly ClusterSummary[],
  { label, editableClusterId }: { label: string; editableClusterId?: string | null },
): ClusterLabelMatch | null => {
  const normalizedLabel = label.toLowerCase().trim();
  const match = clusters.find(
    (cluster) =>
      cluster.id !== editableClusterId &&
      typeof cluster.label === 'string' &&
      cluster.label.toLowerCase() === normalizedLabel &&
      isHumanLabeledTarget(cluster.label),
  );
  if (!match?.id || !match.label) {
    return null;
  }
  return {
    id: match.id,
    label: match.label,
    identityCount: typeof match.identity_count === 'number' ? match.identity_count : undefined,
  };
};

export interface ClusterLabelLookupRequest {
  readonly label: string;
  readonly editableClusterId?: string | null;
  readonly signal?: AbortSignal;
}

export const lookupClusterByLabel = async ({
  label,
  editableClusterId,
  signal,
}: ClusterLabelLookupRequest): Promise<ClusterLabelLookup> => {
  if (!label.toLowerCase().trim()) {
    return { status: CLUSTER_LABEL_LOOKUP_STATUS.NONE };
  }

  let results: Awaited<ReturnType<typeof listRecognitionClusters>>;
  try {
    results = await listRecognitionClusters({ search: label, limit: 10, labeled_only: true }, signal);
  } catch (err) {
    if (isAbortError(err)) {
      return { status: CLUSTER_LABEL_LOOKUP_STATUS.ABORTED };
    }
    // AGT-10 / REF-37: degrade loudly — the failure is reported to the caller *and* logged.
    // FEBT1-W2B-01: one lookup run is one unit of work, so it opens its own
    // correlation id here. The module-scope logger mints none (rg-015).
    const classified = classifyError(err);
    withRequestId(log).warn('Failed to find cluster by label', {
      tag: classified._tag,
      ...('status' in classified ? { status: classified.status } : {}),
      ...('endpoint' in classified ? { endpoint: redactEndpoint(classified.endpoint) } : {}),
    });
    return { status: CLUSTER_LABEL_LOOKUP_STATUS.LOOKUP_FAILED, cause: err };
  }

  const match = resolveClusterLabelMatch(results.clusters, { label, editableClusterId });
  return match ? { status: CLUSTER_LABEL_LOOKUP_STATUS.MATCH, match } : { status: CLUSTER_LABEL_LOOKUP_STATUS.NONE };
};

/**
 * Adapter for callers that still consume `ClusterLabelMatch | null`. `null` now means
 * exactly one thing — "the lookup ran and found nothing" — and a lookup that could not
 * run throws instead.
 */
export const unwrapClusterLabelLookup = (lookup: ClusterLabelLookup): ClusterLabelMatch | null => {
  switch (lookup.status) {
    case CLUSTER_LABEL_LOOKUP_STATUS.MATCH:
      return lookup.match;
    case CLUSTER_LABEL_LOOKUP_STATUS.NONE:
      return null;
    // Caller-initiated cancellation: every call site gates on `signal.aborted`
    // immediately after the await, so the result is discarded either way.
    case CLUSTER_LABEL_LOOKUP_STATUS.ABORTED:
      return null;
    case CLUSTER_LABEL_LOOKUP_STATUS.LOOKUP_FAILED:
      throw new ClusterLabelLookupError(lookup.cause);
    default: {
      const exhaustive: never = lookup;
      throw new Error(`Unexpected cluster label lookup status: ${JSON.stringify(exhaustive)}`);
    }
  }
};
