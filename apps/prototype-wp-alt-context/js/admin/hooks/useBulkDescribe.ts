import { useMutation } from '@tanstack/react-query';

import {
  cancelBulkDescribeRun,
  type DescribeRunResponse,
  submitBulkDescribeRun,
} from '../api/describeApi';
import { useDescribeRunProgress, type DescribeRunProgress } from './useDescribeRunProgress';

export interface UseBulkDescribeResult {
  submit: ReturnType<typeof useMutation<DescribeRunResponse, Error, number[]>>;
  cancel: ReturnType<typeof useMutation<DescribeRunResponse, Error, string>>;
  /** run_id of the run this session started/cancelled, or null before submit. */
  runId: string | null;
  /** Live honest-progress state polled from the run status endpoint. */
  progress: DescribeRunProgress;
}

export const useBulkDescribe = (): UseBulkDescribeResult => {
  const submit = useMutation<DescribeRunResponse, Error, number[]>({
    mutationFn: (mediaIds) => submitBulkDescribeRun(mediaIds),
  });
  const cancel = useMutation<DescribeRunResponse, Error, string>({
    mutationFn: (runId) => cancelBulkDescribeRun(runId),
  });

  const runId = submit.data?.run_id ?? cancel.data?.run_id ?? null;
  const progress = useDescribeRunProgress(runId);

  return { submit, cancel, runId, progress };
};
