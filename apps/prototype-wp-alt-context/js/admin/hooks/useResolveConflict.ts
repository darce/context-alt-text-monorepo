import { useMutation, useQueryClient } from '@tanstack/react-query';

import { resolveConflict, type ResolveConflictRequest, type ResolveConflictResponse } from '../api/recognition';
import { queryKeys } from '../api/queryKeys';

interface ResolveConflictVariables {
  id: number;
  request: ResolveConflictRequest;
}

export const useResolveConflict = () => {
  const queryClient = useQueryClient();

  return useMutation<ResolveConflictResponse, Error, ResolveConflictVariables>({
    mutationFn: ({ id, request }) => resolveConflict(id, request),
    onSuccess: async (_data, variables) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.conflicts.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.outbox.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.sync.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.conflicts.detail(variables.id) }),
      ]);
    },
  });
};

