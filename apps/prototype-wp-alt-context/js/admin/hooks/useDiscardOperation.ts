import { useMutation, useQueryClient } from '@tanstack/react-query';

import { discardFailedOperation, type OutboxMutationResponse } from '../api/recognition';
import { queryKeys } from '../api/queryKeys';

export const useDiscardOperation = () => {
  const queryClient = useQueryClient();

  return useMutation<OutboxMutationResponse, Error, number>({
    mutationFn: (id) => discardFailedOperation(id),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.outbox.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.sync.all }),
      ]);
    },
  });
};
