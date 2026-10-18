/**
 * Duplicate-name guard for ClusterLabelingPanel (extracted for FEBT1G-M-14).
 *
 * Owns one question: may this label be written, or must the operator resolve a collision
 * first? Local collision set first (cheap, possibly incomplete), then a submit-time remote
 * exact-match lookup that FAILS CLOSED (FEBT1G-H-05 / H-04) — a lookup that could not run
 * is not evidence that the name is free.
 *
 * The remote predicate here is deliberately NOT `clusterLabelLookup`'s: this guard uses raw
 * case-insensitive equality (BR-42), not `isHumanLabeledTarget`, so backend-labeled machine
 * shapes (e.g. cluster-auto-1) still arm it. Two rules that answer different questions —
 * "does anything collide" vs "is there a legal merge target" — must not be DRY-merged
 * (REF-10: don't merge code that will not change together).
 */

import React from 'react';

import { listRecognitionClusters } from '../../../api/recognition';
import {
  findCollisionsForLabel,
  namingOptionValue,
  uniqueClusterCollisionTarget,
  type NamingOption,
} from './buildNamingOptions';
import { CLUSTER_LABELING_OPERATION, DUPLICATE_LOOKUP_TIMEOUT_MS, withTimeout } from './clusterLabelingBudget';

export interface DuplicateGuardState {
  readonly label: string;
  readonly collisions: readonly NamingOption[];
  readonly mergeTarget: NamingOption | null;
}

/** Outcome of the submit-time duplicate evaluation (sr-007: one canonical status set). */
export const DUPLICATE_GUARD_OUTCOME = {
  /** No collision — the write may proceed. */
  PROCEED: 'proceed',
  /** A collision was found; the guard UI is now armed and the write must not run. */
  BLOCKED: 'blocked',
  /** The remote check could not run; fail closed and tell the operator. */
  LOOKUP_FAILED: 'lookup_failed',
} as const;

export type DuplicateGuardOutcome = (typeof DUPLICATE_GUARD_OUTCOME)[keyof typeof DUPLICATE_GUARD_OUTCOME];

/** Outcome of the submit-time remote duplicate lookup (sr-007). */
export const DUPLICATE_LOOKUP_STATUS = {
  NONE: 'none',
  DUPLICATE: 'duplicate',
  LOOKUP_FAILED: 'lookup_failed',
} as const;

export type RemoteDuplicateLookup =
  | { readonly status: typeof DUPLICATE_LOOKUP_STATUS.NONE }
  | { readonly status: typeof DUPLICATE_LOOKUP_STATUS.DUPLICATE; readonly guard: DuplicateGuardState }
  | { readonly status: typeof DUPLICATE_LOOKUP_STATUS.LOOKUP_FAILED };

export interface DuplicateGuardEvaluateOptions {
  readonly skipPersonOnlyGuard?: boolean;
  readonly skipDuplicateGuard?: boolean;
}

export interface ClusterLabelingDuplicateGuard {
  readonly duplicateGuard: DuplicateGuardState | null;
  readonly firstActionRef: React.MutableRefObject<HTMLButtonElement | null>;
  /** Arm the guard directly (combobox selection primes an explicit merge; INT-07). */
  readonly armGuard: (guard: DuplicateGuardState) => void;
  /** Clear the guard and the rename-anyway escape hatch. */
  readonly reset: () => void;
  /** Operator chose "rename anyway": clear the guard and let the next submit through. */
  readonly allowRenameAnyway: () => void;
  readonly evaluate: (trimmed: string, options?: DuplicateGuardEvaluateOptions) => Promise<DuplicateGuardOutcome>;
}

export const useClusterLabelingDuplicateGuard = ({
  clusterId,
  collisionsByLabel,
}: {
  clusterId: string;
  collisionsByLabel: ReadonlyMap<string, readonly NamingOption[]>;
}): ClusterLabelingDuplicateGuard => {
  const [duplicateGuard, setDuplicateGuard] = React.useState<DuplicateGuardState | null>(null);
  const allowRenameAnywayRef = React.useRef(false);
  const firstActionRef = React.useRef<HTMLButtonElement | null>(null);

  React.useEffect(() => {
    if (duplicateGuard) {
      firstActionRef.current?.focus();
    }
  }, [duplicateGuard]);

  const evaluateLocal = React.useCallback(
    (trimmed: string): DuplicateGuardState | null => {
      const collisions = findCollisionsForLabel(collisionsByLabel, trimmed, clusterId);
      if (collisions.length === 0) {
        return null;
      }
      return { label: trimmed, collisions, mergeTarget: uniqueClusterCollisionTarget(collisions) };
    },
    [collisionsByLabel, clusterId],
  );

  /**
   * When the local collision set is empty/pending (limit 20, disabled <2 chars), look up an
   * exact remote labeled match so free-text create cannot silent-dupe (FIX-8).
   */
  const evaluateRemote = React.useCallback(
    async (trimmed: string): Promise<RemoteDuplicateLookup> => {
      let results: Awaited<ReturnType<typeof listRecognitionClusters>>;
      try {
        results = await withTimeout(
          (signal) => listRecognitionClusters({ search: trimmed, limit: 10, labeled_only: true }, signal),
          DUPLICATE_LOOKUP_TIMEOUT_MS,
          CLUSTER_LABELING_OPERATION.DUPLICATE_LOOKUP,
        );
      } catch {
        // FEBT1G-H-05: a failed lookup is not evidence of "no duplicate". Fail closed —
        // this guard is the only protection when the local 20-item list is incomplete.
        return { status: DUPLICATE_LOOKUP_STATUS.LOOKUP_FAILED };
      }
      const normalized = trimmed.toLowerCase();
      const match = results.clusters.find(
        (cluster) =>
          cluster.id !== clusterId && typeof cluster.label === 'string' && cluster.label.toLowerCase() === normalized,
      );
      if (!match?.id || !match.label) {
        return { status: DUPLICATE_LOOKUP_STATUS.NONE };
      }
      const remoteOption: NamingOption = {
        value: namingOptionValue('cluster', match.id),
        label: match.label,
        source: 'cluster',
        identityCount: typeof match.identity_count === 'number' ? match.identity_count : undefined,
      };
      return {
        status: DUPLICATE_LOOKUP_STATUS.DUPLICATE,
        guard: { label: trimmed, collisions: [remoteOption], mergeTarget: remoteOption },
      };
    },
    [clusterId],
  );

  const evaluate = React.useCallback(
    async (trimmed: string, options?: DuplicateGuardEvaluateOptions): Promise<DuplicateGuardOutcome> => {
      if (!allowRenameAnywayRef.current && !options?.skipDuplicateGuard) {
        const localGuard = evaluateLocal(trimmed);
        const skipPersonOnly = Boolean(options?.skipPersonOnlyGuard && localGuard && !localGuard.mergeTarget);
        if (localGuard && !skipPersonOnly) {
          setDuplicateGuard(localGuard);
          return DUPLICATE_GUARD_OUTCOME.BLOCKED;
        }
        const remote = await evaluateRemote(trimmed);
        if (remote.status === DUPLICATE_LOOKUP_STATUS.LOOKUP_FAILED) {
          return DUPLICATE_GUARD_OUTCOME.LOOKUP_FAILED;
        }
        if (remote.status === DUPLICATE_LOOKUP_STATUS.DUPLICATE) {
          setDuplicateGuard(remote.guard);
          return DUPLICATE_GUARD_OUTCOME.BLOCKED;
        }
      }
      setDuplicateGuard(null);
      allowRenameAnywayRef.current = false;
      return DUPLICATE_GUARD_OUTCOME.PROCEED;
    },
    [evaluateLocal, evaluateRemote],
  );

  const armGuard = React.useCallback((guard: DuplicateGuardState) => {
    allowRenameAnywayRef.current = false;
    setDuplicateGuard(guard);
  }, []);

  const reset = React.useCallback(() => {
    allowRenameAnywayRef.current = false;
    setDuplicateGuard(null);
  }, []);

  const allowRenameAnyway = React.useCallback(() => {
    allowRenameAnywayRef.current = true;
    setDuplicateGuard(null);
  }, []);

  return { duplicateGuard, firstActionRef, armGuard, reset, allowRenameAnyway, evaluate };
};
