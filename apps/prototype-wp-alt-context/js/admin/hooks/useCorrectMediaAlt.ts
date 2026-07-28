import { useMutation, useQueryClient } from '@tanstack/react-query';

import { correctDescriptionHistoryItem, type DescriptionHistoryItem } from '../api/describeApi';
import { queryKeys } from '../api/queryKeys';

interface CorrectMediaAltVariables {
  mediaId: number;
  altText: string;
}

export const useCorrectMediaAlt = () => {
  const queryClient = useQueryClient();

  return useMutation<DescriptionHistoryItem, Error, CorrectMediaAltVariables>({
    mutationFn: ({ mediaId, altText }) => correctDescriptionHistoryItem(mediaId, altText),
    // Fire-and-forget: awaiting invalidateQueries holds isPending until the whole
    // media tree refetches, which leaves the commit button on "Saving…" after the
    // write already landed and can unmount the row (missing-status list) before
    // the component's own onSuccess runs (WBUX-5-S2C3A-BR-05).
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.media.all });
    },
  });
};
