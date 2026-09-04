import { __, sprintf } from '@wordpress/i18n';

import { classifyError, isAbortLikeName } from '../../../utils/appError';
import { formatUserFacingError, isAuthExpiredError } from '../../../utils/userFacingError';

export const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * FEBT1-LC-02 / sr-007: locally minted interactive-budget expiry travels as a typed
 * value, never as an English sentence classified by `.includes('timed out')`. A
 * stringly-typed control channel silently degrades to raw-message passthrough the
 * moment the literal is reworded or translated.
 *
 * The brand is a registry symbol so the predicate stays structural: it survives a
 * duplicated module instance (two copies of this file in one bundle) and does not
 * depend on `instanceof` prototype identity.
 */
const CLUSTER_MUTATION_TIMEOUT_BRAND = Symbol.for('acx.clusterMutationTimeout');

export class ClusterMutationTimeoutError extends Error {
  readonly [CLUSTER_MUTATION_TIMEOUT_BRAND] = true;

  /** Diagnostic only — never user-facing copy. */
  readonly operation: string;

  constructor(operation: string) {
    // Deliberately carries no English timeout token: if this message ever
    // matched `matchKnownCondition`, the substring matcher would silently rescue
    // a broken brand check and the typed channel would be untested (TEST-15).
    super(`cluster_mutation_budget_expired:${operation}`);
    this.name = 'ClusterMutationTimeoutError';
    this.operation = operation;
  }
}

/**
 * Mint the timeout signal for a client-side interactive budget (FEBT1G-H-08).
 * `operation` is a stable machine token (`'save'`, `'merge'`, `'duplicate_lookup'`),
 * not a sentence: it is for logs and tests, and never reaches the DOM.
 */
export const createClusterMutationTimeoutError = (operation: string): ClusterMutationTimeoutError =>
  new ClusterMutationTimeoutError(operation);

export const isClusterMutationTimeoutError = (error: unknown): boolean =>
  typeof error === 'object' &&
  error !== null &&
  (error as Record<symbol, unknown>)[CLUSTER_MUTATION_TIMEOUT_BRAND] === true;

/**
 * Abort-like: user cancel and AbortSignal.timeout. The name check is kept
 * alongside the tag so this stays true if the timeout tag is ever split out of
 * `abort` (FEBT1G-M-13): a cancelled request must never take the retry path.
 */
export const isAbortError = (err: unknown): boolean =>
  classifyError(err)._tag === 'abort' || isAbortLikeName(err);

/**
 * A *deliberate* cancel: the operator withdrew the request. Named for the policy
 * it answers ("what do I tell the operator happened?"), not for the error's
 * shape — `isAbortError` above is abort-*like* (it also answers true for a
 * `TimeoutError` name), so it cannot decide copy without telling a cancelling
 * operator the system is slow (DOM-03: one meaning per term per context).
 *
 * This is deliberately NOT `retryPolicy.isDeliberateAbort`. That predicate
 * answers a *retry* question; sharing one predicate across a retry policy and a
 * UI policy is what let FEBT1-W2A-05's narrowing regress the progress hook
 * across a module boundary. Same shape today, different reasons to change.
 */
export const isDeliberateCancelError = (error: unknown): boolean =>
  classifyError(error)._tag === 'abort';

export const isProjectionNotReadyError = (message: string): boolean => {
  const normalized = message.toLowerCase();
  return message.includes('projection_not_ready') || normalized.includes('local projection is not ready');
};

export const getProjectionNotReadyMessage = (): string =>
  __('Local sync is still catching up. Retry sync before editing labels.', 'alt-context');

export const isInvalidTargetClusterError = (message: string): boolean => {
  const normalized = message.toLowerCase();
  return (
    message.includes('invalid_target_cluster_id') || normalized.includes('source and target cluster ids must differ')
  );
};

export const getInvalidTargetClusterMessage = (label: string): string =>
  sprintf(__('That group is already named %s - nothing to merge.', 'alt-context'), label);

const HTTP_CONFLICT_STATUS = 409;

const timeoutMessage = (): string => __('Save is taking too long. Please try again.', 'alt-context');
/**
 * A cancel is the operator's own action, not a slow system: telling them "this
 * is taking too long" answers a question they did not ask and hides the one
 * they did (FORM-05 / A11Y-17 — what happened, and what to do next).
 *
 * It stops short of "nothing was saved". An abort fired after the request left
 * the browser has an UNKNOWN outcome, so asserting either success or failure
 * would be a claim the client cannot make (RLSE-05).
 */
const cancelledMessage = (): string =>
  __('Save cancelled. Check the label before trying again.', 'alt-context');
const conflictMessage = (): string => __('Label already exists. Use the dropdown to merge.', 'alt-context');
const networkMessage = (): string =>
  __('Network error. Please check your connection and try again.', 'alt-context');
const genericMessage = (): string => __('An unexpected error occurred. Please try again.', 'alt-context');

const assertUnreachableTag = (value: never): never => {
  throw new Error(`Unexpected AppError tag: ${String(value)}`);
};

/**
 * Message-shape recognition for server conditions the API reports as text
 * rather than as a distinct status. Matching on the message is fine; returning
 * it is not — see getClusterMutationErrorMessage.
 *
 * The 'timed out' arm here covers *wire-originated* text (a gateway body that
 * says so). It is not the control channel for our own interactive budget —
 * that is ClusterMutationTimeoutError (FEBT1-LC-02).
 */
const matchKnownCondition = (message: string, label: string): string | null => {
  const normalized = message.toLowerCase();
  if (normalized.includes('timed out') || normalized.includes('timeout')) {
    return timeoutMessage();
  }
  if (isProjectionNotReadyError(message)) {
    return getProjectionNotReadyMessage();
  }
  if (isInvalidTargetClusterError(message)) {
    return getInvalidTargetClusterMessage(label);
  }
  if (message.includes('409') || normalized.includes('conflict')) {
    return conflictMessage();
  }
  if (message.includes('NetworkError') || message.includes('Failed to fetch')) {
    return networkMessage();
  }
  return null;
};

/**
 * FEBT1-W2A-04: an HTTPError message embeds the response body preview, so the
 * verbatim message of any wire-originated error is not user-facing copy. Only
 * the `unknown` tag — locally minted Errors that never carry a wire body —
 * falls through to its own message.
 */
export const getClusterMutationErrorMessage = (error: unknown, label: string): string => {
  // Typed local-budget expiry first: it is a distinct condition from a user
  // cancel and must not depend on the wording of any message. This ordering is
  // load-bearing — checking isAbortError first would swallow the branded
  // sentinel the moment it grows an abort-like `name` (pinned by test).
  //
  // The mutation hooks swallow most cancels via isAbortError, but not all:
  // ClusterLabelingPanel.submitLabel and IdentityClusterItem.bindToRosterEntry
  // both route a rejected promise straight here, so the cancel copy is a state
  // the operator can actually reach (RLSE-04).
  if (isClusterMutationTimeoutError(error)) {
    return timeoutMessage();
  }
  if (isAbortError(error)) {
    // Abort-like covers two conditions, and they are not the same news for the
    // operator: a deliberate cancel is something they did, an elapsed deadline
    // is the system being slow. Both were previously told "taking too long".
    return isDeliberateCancelError(error) ? cancelledMessage() : timeoutMessage();
  }
  if (isAuthExpiredError(error)) {
    return formatUserFacingError(error, genericMessage());
  }

  const classified = classifyError(error);
  const known = matchKnownCondition(classified.message, label);

  switch (classified._tag) {
    case 'http':
      return known ?? (classified.status === HTTP_CONFLICT_STATUS ? conflictMessage() : genericMessage());
    case 'transport':
      return known ?? networkMessage();
    case 'unknown':
      return known ?? (error instanceof Error ? classified.message : genericMessage());
    case 'abort':
      // Not deletable dead code — a required arm (FEBT2-W2-ADJ-03). Every
      // abort-tagged value is already claimed by isAbortError above, so no
      // caller reaches this line today, but removing the arm makes `classified`
      // non-`never` at the default and fails the type check:
      //   clusterMutationUtils.ts(193,35): TS2345: Argument of type
      //   'AppErrorBase<"abort">' is not assignable to parameter of type 'never'.
      // It is deliberately NOT an assertion helper: this function is the copy
      // source for an error path, so throwing here would replace a degraded
      // message with no message at all (RLSE-05, lexicons/engineering.md:696).
      // It returns the cancel copy so the exhaustive switch cannot silently
      // re-acquire the timeout copy if the guard above is ever narrowed.
      return cancelledMessage();
    case 'timeout':
      // Tag-driven, not message-driven. A plain `{_tag:'timeout'}` value carries
      // no abort-like `name`, so it reaches here; deciding its copy from
      // matchKnownCondition would make it depend on the wording of a message
      // (the stringly-typed channel FEBT1-LC-02 removed) and drop to the generic
      // copy for any timeout whose text lacks an English timeout token.
      return timeoutMessage();
    case 'parse':
    case 'nonce_refresh':
    case 'auth_expired':
      return known ?? genericMessage();
    default:
      return assertUnreachableTag(classified);
  }
};
