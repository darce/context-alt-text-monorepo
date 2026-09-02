import { __, sprintf } from '@wordpress/i18n';

import { classifyError } from '../../../utils/appError';
import { formatUserFacingError, isAuthExpiredError } from '../../../utils/userFacingError';

export const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export const isAbortError = (err: unknown): boolean => classifyError(err)._tag === 'abort';

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

export const getClusterMutationErrorMessage = (error: unknown, label: string): string => {
  if (isAbortError(error)) {
    return __('Save is taking too long. Please try again.', 'alt-context');
  }
  if (isAuthExpiredError(error)) {
    return formatUserFacingError(error, __('An unexpected error occurred. Please try again.', 'alt-context'));
  }
  if (error instanceof Error) {
    const normalized = error.message.toLowerCase();
    if (normalized.includes('timed out') || normalized.includes('timeout')) {
      return __('Save is taking too long. Please try again.', 'alt-context');
    }
    if (isProjectionNotReadyError(error.message)) {
      return getProjectionNotReadyMessage();
    }
    if (isInvalidTargetClusterError(error.message)) {
      return getInvalidTargetClusterMessage(label);
    }
    if (error.message.includes('409') || normalized.includes('conflict')) {
      return __('Label already exists. Use the dropdown to merge.', 'alt-context');
    }
    if (error.message.includes('NetworkError') || error.message.includes('Failed to fetch')) {
      return __('Network error. Please check your connection and try again.', 'alt-context');
    }
    return error.message;
  }

  return __('An unexpected error occurred. Please try again.', 'alt-context');
};
