import { __, sprintf } from '@wordpress/i18n';

import { classifyError, isAbortOrTimeoutName, toUserMessage } from '../../../utils/appError';
import { isAbortOrTimeout } from '../../../utils/retryPolicy';

export const CLUSTER_MUTATION_ERROR_COPY = {
  timeout: __('The server took too long to respond — try again', 'alt-context'),
  transport: __('Network error — check your connection', 'alt-context'),
  parse: __('Unexpected response from server', 'alt-context'),
  unknown: __('An unexpected error occurred. Please try again.', 'alt-context'),
  staleConflict: __('Label already exists. Use the dropdown to merge.', 'alt-context'),
  bindFailed: __('The group was created but the person was not bound.', 'alt-context'),
} as const;

export type ClusterMutationErrorKind =
  | 'stale_conflict'
  | 'timeout'
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

  if (classified._tag === 'auth_expired') {
    return {
      kind: 'auth_expired',
      message: toUserMessage(error, CLUSTER_MUTATION_ERROR_COPY.unknown),
      recovery: 'reload',
    };
  }

  if (classified._tag === 'abort') {
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
