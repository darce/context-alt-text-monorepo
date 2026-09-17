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
import {
  clearActiveDescribeRunId,
  setActiveDescribeRunId,
  useActiveDescribeRun,
} from './activeDescribeRun';
import {
  DESCRIBE_OPERATION_CONTEXT_VERSION,
  DESCRIBE_OPERATION_KIND,
  putDescribeOperationContext,
} from './describeOperationStore';
import { useDescribeRunProgress, type DescribeRunProgress } from './useDescribeRunProgress';

export interface UseBulkDescribeResult {
  submit: ReturnType<typeof useMutation<DescribeRunResponse, Error, number[]>>;
  cancel: ReturnType<typeof useMutation<DescribeRunResponse, Error, string>>;
  /** run_id of the currently active run; null before submit and after terminal cleanup. */
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

const persistRunContext = (response: DescribeRunResponse): void => {
  putDescribeOperationContext({
    version: DESCRIBE_OPERATION_CONTEXT_VERSION,
    kind: DESCRIBE_OPERATION_KIND.RUN,
    id: response.run_id,
    startup_id: response.startup_id ?? null,
    started_at: Date.now(),
    request: { writeAlt: false, force: false },
  });
  setActiveDescribeRunId(response.run_id);
};

export const useBulkDescribe = (): UseBulkDescribeResult => {
  const queryClient = useQueryClient();
  const { runId: storedRunId } = useActiveDescribeRun();
  const submit = useMutation<DescribeRunResponse, Error, number[]>({
    mutationFn: (mediaIds) => submitBulkDescribeRun(mediaIds),
    onSuccess: persistRunContext,
  });
  const cancel = useMutation<DescribeRunResponse, Error, string>({
    mutationFn: (runId) => cancelBulkDescribeRun(runId),
  });

  // Store is the durable source (navigation/reload). Keep active and terminal
  // identities separate: the former controls whether a new submit is allowed,
  // while the latter keeps the finished response available for the terminal
  // summary after the active store entry is cleared.
  const activeRunIdRef = useRef<string | null>(null);
  const lastTerminalRunIdRef = useRef<string | null>(null);
  if (storedRunId !== activeRunIdRef.current) {
    // The store is the source of truth for whether a run is active. A terminal
    // summary may continue polling through lastTerminalRunIdRef, but it must
    // never keep the public active runId alive after the store is cleared.
    activeRunIdRef.current = storedRunId;
    if (storedRunId !== null) {
      lastTerminalRunIdRef.current = null;
    }
  }
  const runId = activeRunIdRef.current;
  const progressRunId = runId ?? lastTerminalRunIdRef.current;
  const progress = useDescribeRunProgress(progressRunId);
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

  useEffect(() => {
    if (runId !== null && progress.isTerminal) {
      lastTerminalRunIdRef.current = runId;
      clearActiveDescribeRunId(runId);
      activeRunIdRef.current = null;
    }
  }, [progress.isTerminal, runId]);

  const errorMessage = submit.error
    ? formatBulkDescribeErrorMessage(submit.error, SUBMIT_ERROR_FALLBACK)
    : cancel.error
      ? formatBulkDescribeErrorMessage(cancel.error, CANCEL_ERROR_FALLBACK)
      : null;

  return { submit, cancel, runId, progress, errorMessage };
};
