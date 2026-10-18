import { useQuery } from '@tanstack/react-query';

import { fetchOutboxOperations, type OutboxListParams, type OutboxListResponse } from '../api/recognition';
import { queryKeys } from '../api/queryKeys';

export const useOutboxOperations = (params: OutboxListParams = {}) =>
  useQuery<OutboxListResponse>({
    queryKey: queryKeys.outbox.list(params),
    queryFn: () => fetchOutboxOperations(params),
  });
