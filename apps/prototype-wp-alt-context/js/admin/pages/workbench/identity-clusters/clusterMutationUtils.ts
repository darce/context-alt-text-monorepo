import { __, sprintf } from '@wordpress/i18n';

import { classifyError, isAbortLikeName } from '../../../utils/appError';
import { formatUserFacingError, isAuthExpiredError } from '../../../utils/userFacingError';

export const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Abort-like: user cancel and AbortSignal.timeout. The name check is kept
 * alongside the tag so this stays true if the timeout tag is ever split out of
 * `abort` (FEBT1G-M-13): a cancelled request must never take the retry path.
 */
export const isAbortError = (err: unknown): boolean =>
  classifyError(err)._tag === 'abort' || isAbortLikeName(err);

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
  if (isAbortError(error)) {
    return timeoutMessage();
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
    case 'parse':
    case 'nonce_refresh':
    case 'auth_expired':
    case 'abort':
      return known ?? genericMessage();
    default:
      return assertUnreachableTag(classified);
  }
};
