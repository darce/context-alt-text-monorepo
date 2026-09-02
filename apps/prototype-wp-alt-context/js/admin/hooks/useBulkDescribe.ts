import { useEffect, useRef } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { __, sprintf } from '@wordpress/i18n';

import {
  cancelBulkDescribeRun,
  type DescribeRunResponse,
  resolveDescribeErrorDataField,
  submitBulkDescribeRun,
} from '../api/describeApi';
import { invalidateWorkbenchListPages } from '../api/queryKeys';
import { resolveWpErrorMessage } from '../api/wpErrorMessage';
import { useDescribeRunProgress, type DescribeRunProgress } from './useDescribeRunProgress';

export interface UseBulkDescribeResult {
  submit: ReturnType<typeof useMutation<DescribeRunResponse, Error, number[]>>;
  cancel: ReturnType<typeof useMutation<DescribeRunResponse, Error, string>>;
  /** run_id of the run this session started/cancelled, or null before submit. */
  runId: string | null;
  /** Live honest-progress state polled from the run status endpoint. */
  progress: DescribeRunProgress;
  /**
   * Operator-visible submit/cancel failure text. Resolved through
   * resolveWpErrorMessage; when a durable membership write fails after the
   * upstream run was accepted, surfaces the stranded run id without starting
   * a progress poll (BR-143 / [RLSE-04]).
   */
  errorMessage: string | null;
}

const SUBMIT_ERROR_FALLBACK = __('Could not start the describe run. Please try again.', 'alt-context');
const CANCEL_ERROR_FALLBACK = __('Could not cancel the describe run. Please try again.', 'alt-context');

/**
 * Build the operator-visible notice for a bulk-describe mutation failure.
 * Never sets polling state — callers must not treat a run_id found only in an
 * error payload as a successful submit ([RLSE-04]).
 *
 * Exported for unit tests.
 */
export const formatBulkDescribeErrorMessage = (
  error: unknown,
  fallback: string = SUBMIT_ERROR_FALLBACK,
): string => {
  const message = resolveWpErrorMessage(error, fallback);
  // Membership-store failure leaves the upstream run accepted and burning paid
  // compute; surface the id so the operator can find it, without polling as if
  // submit had succeeded (BR-143).
  const strandedRunId = resolveDescribeErrorDataField(error, 'run_id');
  if (strandedRunId !== null && strandedRunId !== '') {
    return sprintf(
      /* translators: %1$s is the resolved error message; %2$s is the upstream run id. */
      __(
        '%1$s The describe run %2$s is already running upstream but cannot be applied on this site. Note the run id and retry or contact support — do not start another run for the same items.',
        'alt-context',
      ),
      message,
      strandedRunId,
    );
  }
  return message;
};

export const useBulkDescribe = (): UseBulkDescribeResult => {
  const queryClient = useQueryClient();
  const submit = useMutation<DescribeRunResponse, Error, number[]>({
    mutationFn: (mediaIds) => submitBulkDescribeRun(mediaIds),
  });
  const cancel = useMutation<DescribeRunResponse, Error, string>({
    mutationFn: (runId) => cancelBulkDescribeRun(runId),
  });

  // Only a successful submit/cancel response owns runId — never an error body
  // that happens to carry data.run_id (BR-143 / [RLSE-04]).
  const runId = submit.data?.run_id ?? cancel.data?.run_id ?? null;
  const progress = useDescribeRunProgress(runId);
  const invalidatedWorkbenchRunIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (runId === null || !progress.isTerminal) {
      return;
    }
    if (invalidatedWorkbenchRunIdRef.current === runId) {
      return;
    }
    invalidatedWorkbenchRunIdRef.current = runId;
    invalidateWorkbenchListPages(queryClient);
  }, [runId, progress.isTerminal, queryClient]);

  const errorMessage = submit.error
    ? formatBulkDescribeErrorMessage(submit.error, SUBMIT_ERROR_FALLBACK)
    : cancel.error
      ? formatBulkDescribeErrorMessage(cancel.error, CANCEL_ERROR_FALLBACK)
      : null;

  return { submit, cancel, runId, progress, errorMessage };
};
