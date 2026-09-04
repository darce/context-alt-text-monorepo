/**
 * Interactive budget for the cluster-labeling write paths.
 *
 * FEBT1G-H-08 established that a declared budget must be *enforced* by the caller: a
 * request that drops its AbortSignal must not be able to outlive the budget and hang the
 * UI until the global fetch timeout (RES-02 "every socket/pool/RPC/wait() needs a bounded
 * timeout", lexicons/engineering.md:113).
 *
 * FEBT1-LC-02 removes the stringly-typed half of that mechanism. The deadline no longer
 * signals "timed out" with an English string literal that a downstream substring match
 * has to re-parse; it rejects with `ClusterMutationTimeoutError`, the branded sentinel
 * owned by `clusterMutationUtils` (sr-007: one canonical definition, imported not
 * re-derived). That type is deliberately NOT abort-like: an abort-like value reaching a
 * mutation hook's `onError` is classified as a user cancel and suppresses the error
 * notice entirely, so the operator's write would time out in silence (AGT-10 degrade
 * loudly, lexicons/engineering.md:80).
 *
 * This module is the single owner of the labeling write deadline. The panel's former
 * local `withTimeout` is deleted — two independent deadlines on one write path make the
 * effective budget whichever is shorter and neither the documented one.
 */

import {
  createClusterMutationTimeoutError,
  isAbortError,
  isClusterMutationTimeoutError,
} from './clusterMutationUtils';

export const SAVE_TIMEOUT_MS = 3000;
/** The duplicate lookup gates the save, so it shares the save's interactive budget. */
export const DUPLICATE_LOOKUP_TIMEOUT_MS = 3000;

/**
 * Operations that run under an interactive budget (sr-007: one canonical set).
 * Stable machine tokens — diagnostic only, never user-facing copy.
 */
export const CLUSTER_LABELING_OPERATION = {
  SAVE: 'save',
  MERGE: 'merge',
  DUPLICATE_LOOKUP: 'duplicate_lookup',
} as const;

export type ClusterLabelingOperation =
  (typeof CLUSTER_LABELING_OPERATION)[keyof typeof CLUSTER_LABELING_OPERATION];

/**
 * Enforce an interactive budget end to end.
 *
 * The signal is passed so callers that honour it cancel the transport (FEBT1-LC-01: a
 * deadline that only abandons the caller still leaks the server-side write — RES-04,
 * lexicons/engineering.md:115), and the deadline is additionally enforced by a race so a
 * signal-deaf request still cannot hang the UI.
 */
export const withTimeout = async <T,>(
  request: (signal: AbortSignal) => Promise<T>,
  timeoutMs: number,
  operation: ClusterLabelingOperation,
): Promise<T> => {
  const controller = new AbortController();
  let timeoutId = 0;
  const deadline = new Promise<never>((_resolve, reject) => {
    timeoutId = window.setTimeout(() => {
      const timeoutError = createClusterMutationTimeoutError(operation);
      controller.abort(timeoutError);
      reject(timeoutError);
    }, timeoutMs);
  });
  const attempt = (async (): Promise<T> => {
    try {
      return await request(controller.signal);
    } catch (error) {
      if (isClusterMutationTimeoutError(error)) {
        throw error;
      }
      // No cancel affordance exists on this write path, so an abort surfacing here is
      // never a user cancel — it is our deadline, or the transport's own composed
      // timeout. Letting it through abort-like would make a mutation `onError` swallow it
      // and show nothing (AGT-10 degrade loudly, lexicons/engineering.md:80).
      if (isAbortError(error)) {
        throw createClusterMutationTimeoutError(operation);
      }
      throw error;
    }
  })();
  try {
    return await Promise.race([attempt, deadline]);
  } finally {
    window.clearTimeout(timeoutId);
  }
};
