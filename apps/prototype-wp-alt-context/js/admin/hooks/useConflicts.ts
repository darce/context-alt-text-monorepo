import { useQuery } from '@tanstack/react-query';

import { fetchConflicts, type ConflictListParams, type ConflictListResponse } from '../api/recognition';
import { queryKeys } from '../api/queryKeys';

export const useConflicts = (params: ConflictListParams = {}) =>
  useQuery<ConflictListResponse>({
    queryKey: queryKeys.conflicts.list(params),
    queryFn: () => fetchConflicts(params),
  });

