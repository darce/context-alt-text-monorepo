import { useMutation, useQueryClient } from '@tanstack/react-query';

import { bulkRetryFailedOperations, type BulkRetryResponse } from '../api/recognition';
import { queryKeys } from '../api/queryKeys';

export const useBulkRetryOperations = () => {
  const queryClient = useQueryClient();

  return useMutation<BulkRetryResponse, Error, void>({
    mutationFn: () => bulkRetryFailedOperations(),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.outbox.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.sync.all }),
      ]);
    },
  });
};
