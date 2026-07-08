import { useMutation } from '@tanstack/react-query';

import {
  cancelBulkDescribeRun,
  type DescribeRunResponse,
  submitBulkDescribeRun,
} from '../api/describeApi';

export interface UseBulkDescribeResult {
  submit: ReturnType<typeof useMutation<DescribeRunResponse, Error, number[]>>;
  cancel: ReturnType<typeof useMutation<DescribeRunResponse, Error, string>>;
}

export const useBulkDescribe = (): UseBulkDescribeResult => {
  const submit = useMutation<DescribeRunResponse, Error, number[]>({
    mutationFn: (mediaIds) => submitBulkDescribeRun(mediaIds),
  });
  const cancel = useMutation<DescribeRunResponse, Error, string>({
    mutationFn: (runId) => cancelBulkDescribeRun(runId),
  });

  return { submit, cancel };
};
