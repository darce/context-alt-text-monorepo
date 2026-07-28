import { useMutation, useQueryClient } from '@tanstack/react-query';

import {
  correctDescriptionHistoryItem,
  type DescriptionHistoryItem,
} from '../api/describeApi';
import { queryKeys } from '../api/queryKeys';

interface CorrectMediaAltVariables {
  mediaId: number;
  altText: string;
}

export const useCorrectMediaAlt = () => {
  const queryClient = useQueryClient();

  return useMutation<DescriptionHistoryItem, Error, CorrectMediaAltVariables>({
    mutationFn: ({ mediaId, altText }) => correctDescriptionHistoryItem(mediaId, altText),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.media.all });
    },
  });
};