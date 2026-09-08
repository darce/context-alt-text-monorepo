import { __, sprintf } from '@wordpress/i18n';

import { classifyError, isAbortOrTimeoutName, toUserMessage } from '../../../utils/appError';
import { isAbortOrTimeout } from '../../../utils/retryPolicy';

export const CLUSTER_MUTATION_ERROR_COPY = {
  timeout: __('The server took too long to respond — try again', 'alt-context'),
  /**
   * A cancel is the operator's own action, not a slow system: telling them "this
   * is taking too long" answers a question they did not ask and hides the one
   * they did (FORM-05 / A11Y-17 — what happened, and what to do next).
   *
   * It stops short of "nothing was saved". An abort fired after the request left
   * the browser has an UNKNOWN outcome, so asserting either success or failure
   * would be a claim the client cannot make (RLSE-05).
   */
  cancelled: __('Save cancelled. Check the label before trying again.', 'alt-context'),
  transport: __('Network error — check your connection', 'alt-context'),
  parse: __('Unexpected response from server', 'alt-context'),
  unknown: __('An unexpected error occurred. Please try again.', 'alt-context'),
  staleConflict: __('Label already exists. Use the dropdown to merge.', 'alt-context'),
  bindFailed: __('The group was created but the person was not bound.', 'alt-context'),
} as const;

export type ClusterMutationErrorKind =
  | 'stale_conflict'
  | 'timeout'
  | 'cancelled'
  | 'transport'
  | 'auth_expired'
  | 'parse'
  | 'http'
  | 'projection_not_ready'
  | 'invalid_target'
  | 'bind_failed'
  | 'unknown';

export type ClusterMutationRecovery = 'reload' | 'retry' | 'none';

export interface ClusterMutationUserError {
  readonly kind: ClusterMutationErrorKind;
  readonly message: string;
  readonly recovery: ClusterMutationRecovery;
}

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
    // Deliberately carries no English timeout token: a substring matcher must
    // never be able to silently rescue a broken brand check (TEST-15).
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
 * A *deliberate* cancel: the operator withdrew the request. Named for the policy
 * it answers ("what do I tell the operator happened?"), not for the error's
 * shape — `isAbortError` below is abort-*or-timeout* (it also answers true for a
 * `TimeoutError` name), so it cannot decide copy without telling a cancelling
 * operator the system is slow (DOM-03: one meaning per term per context).
 *
 * This is deliberately NOT `retryPolicy.isDeliberateAbort`. That predicate
 * answers a *retry* question; sharing one predicate across a retry policy and a
 * UI policy is what let FEBT1-W2A-05's narrowing regress the progress hook
 * across a module boundary. Same shape today, different reasons to change.
 */
export const isDeliberateCancelError = (error: unknown): boolean => classifyError(error)._tag === 'abort';

/**
 * Does this wire message describe a deadline the *server* hit? Matched on the
 * two spellings HTTP intermediaries actually emit ("timed out", "timeout"), and
 * used only to pick a copy constant — never to build the copy itself.
 */
const isWireTimeoutMessage = (message: string): boolean => {
  const normalized = message.toLowerCase();
  return normalized.includes('timed out') || normalized.includes('timeout');
};

/**
 * Abort-like: user cancel and AbortSignal.timeout. The shared retry-policy
 * predicate covers the `abort` and `timeout` tags; the name check is kept
 * alongside it for values that never reach a tag (FEBT1G-M-13): a cancelled
 * request must never take the retry path.
 */
export const isAbortError = (err: unknown): boolean => isAbortOrTimeout(err) || isAbortOrTimeoutName(err);

const readStringField = (value: unknown, key: string): string | null => {
  if (typeof value !== 'object' || value === null || !Object.hasOwn(value, key)) {
    return null;
  }
  const field = (value as Record<string, unknown>)[key];
  return typeof field === 'string' ? field : null;
};

const readBodyPreview = (error: unknown): string => {
  const classified = classifyError(error);
  return readStringField(classified.cause, 'bodyPreview') ?? readStringField(error, 'bodyPreview') ?? '';
};

const readWpErrorCode = (preview: string): string | null => {
  if (preview === '') {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(preview);
    return readStringField(parsed, 'code');
  } catch {
    return null;
  }
};

export const getClusterErrorCode = (error: unknown): string | null => readWpErrorCode(readBodyPreview(error));

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

export const getClusterMutationUserError = (error: unknown, label = 'that label'): ClusterMutationUserError => {
  const classified = classifyError(error);
  const code = getClusterErrorCode(error);
  const rawMessage = error instanceof Error ? error.message : '';

  // Typed local-budget expiry first: it is a distinct condition from a user
  // cancel and must not depend on the wording of any message. This ordering is
  // load-bearing — checking the abort predicates first would swallow the branded
  // sentinel the moment it grows an abort-like `name` (pinned by test).
  if (isClusterMutationTimeoutError(error)) {
    return {
      kind: 'timeout',
      message: CLUSTER_MUTATION_ERROR_COPY.timeout,
      recovery: 'retry',
    };
  }

  if (classified._tag === 'auth_expired') {
    return {
      kind: 'auth_expired',
      message: toUserMessage(error, CLUSTER_MUTATION_ERROR_COPY.unknown),
      recovery: 'reload',
    };
  }

  // Abort-like covers two conditions, and they are not the same news for the
  // operator: a deliberate cancel is something they did, an elapsed deadline is
  // the system being slow. Both were previously told "taking too long".
  if (classified._tag === 'abort') {
    return {
      kind: 'cancelled',
      message: CLUSTER_MUTATION_ERROR_COPY.cancelled,
      recovery: 'retry',
    };
  }

  // Tag-driven, not message-driven. A plain `{_tag:'timeout'}` value carries no
  // abort-like `name`, so deciding its copy from a substring match would make it
  // depend on the wording of a message (the stringly-typed channel FEBT1-LC-02
  // removed) and drop to the generic copy for any timeout whose text lacks an
  // English timeout token.
  if (classified._tag === 'timeout') {
    return {
      kind: 'timeout',
      message: toUserMessage(error, CLUSTER_MUTATION_ERROR_COPY.timeout),
      recovery: 'retry',
    };
  }

  if (classified._tag === 'transport' || classified._tag === 'nonce_refresh') {
    return {
      kind: 'transport',
      message: toUserMessage(error, CLUSTER_MUTATION_ERROR_COPY.transport),
      recovery: 'retry',
    };
  }

  if (classified._tag === 'parse') {
    return {
      kind: 'parse',
      message: toUserMessage(error, CLUSTER_MUTATION_ERROR_COPY.parse),
      recovery: 'retry',
    };
  }

  if (code === 'projection_not_ready' || (code === null && isProjectionNotReadyError(rawMessage))) {
    return {
      kind: 'projection_not_ready',
      message: getProjectionNotReadyMessage(),
      recovery: 'retry',
    };
  }

  if (code === 'invalid_target_cluster_id' || (code === null && isInvalidTargetClusterError(rawMessage))) {
    return {
      kind: 'invalid_target',
      message: getInvalidTargetClusterMessage(label),
      recovery: 'none',
    };
  }

  if (code === 'acx_cluster_created_bind_failed') {
    return {
      kind: 'bind_failed',
      message: CLUSTER_MUTATION_ERROR_COPY.bindFailed,
      recovery: 'retry',
    };
  }

  // FEBT2-LD2-NEW-05: a gateway/upstream deadline arrives as an ordinary 5xx —
  // the tag is 'http', not 'timeout'. Recognising the wire wording here is
  // *classification*, not copy: the operator still gets the single-owner
  // constant, never the response text (FEBT1-W2A-04).
  if (classified._tag === 'http' && isWireTimeoutMessage(rawMessage)) {
    return {
      kind: 'timeout',
      message: CLUSTER_MUTATION_ERROR_COPY.timeout,
      recovery: 'retry',
    };
  }

  if (classified._tag === 'http' && classified.status === 409) {
    return {
      kind: 'stale_conflict',
      message: CLUSTER_MUTATION_ERROR_COPY.staleConflict,
      recovery: 'reload',
    };
  }

  // FEBT1-W2A-04: an HTTPError message embeds the response body preview, so the
  // verbatim message of any wire-originated error is not user-facing copy. Only
  // the `unknown` tag — locally minted Errors that never carry a wire body —
  // falls through to its own message.
  if (classified._tag === 'unknown' && error instanceof Error) {
    return { kind: 'unknown', message: classified.message, recovery: 'retry' };
  }

  return {
    kind: classified._tag === 'http' ? 'http' : 'unknown',
    message: toUserMessage(error, CLUSTER_MUTATION_ERROR_COPY.unknown),
    recovery: 'retry',
  };
};

export const getClusterMutationErrorMessage = (error: unknown, label: string): string =>
  getClusterMutationUserError(error, label).message;
