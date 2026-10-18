import { useQuery } from '@tanstack/react-query';

import { fetchConflictDetail, type ConflictDetailResponse } from '../api/recognition';
import { queryKeys } from '../api/queryKeys';

export const useConflictDetail = (id: number | null) =>
  useQuery<ConflictDetailResponse>({
    queryKey: queryKeys.conflicts.detail(id),
    queryFn: () => {
      if (id === null) {
        throw new Error('Conflict ID is required.');
      }
      return fetchConflictDetail(id);
    },
    enabled: id !== null,
  });
