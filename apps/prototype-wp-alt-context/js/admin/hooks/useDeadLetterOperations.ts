import { useQuery } from '@tanstack/react-query';

import { fetchFailedOutboxOperations, type FailedOutboxListParams, type OutboxListResponse } from '../api/recognition';
import { queryKeys } from '../api/queryKeys';

export const useDeadLetterOperations = (params: FailedOutboxListParams = {}) =>
  useQuery<OutboxListResponse>({
    queryKey: queryKeys.outbox.failedList(params),
    queryFn: () => fetchFailedOutboxOperations(params),
  });

