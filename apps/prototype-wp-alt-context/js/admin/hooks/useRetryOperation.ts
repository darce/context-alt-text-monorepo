import { useMutation, useQueryClient } from '@tanstack/react-query';

import { retryFailedOperation, type OutboxMutationResponse } from '../api/recognition';
import { queryKeys } from '../api/queryKeys';

export const useRetryOperation = () => {
  const queryClient = useQueryClient();

  return useMutation<OutboxMutationResponse, Error, number>({
    mutationFn: (id) => retryFailedOperation(id),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.outbox.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.sync.all }),
      ]);
    },
  });
};

