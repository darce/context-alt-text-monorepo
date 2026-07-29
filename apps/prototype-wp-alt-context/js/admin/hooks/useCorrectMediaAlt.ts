import { type QueryClient, useMutation, useQueryClient } from '@tanstack/react-query';

import {
  correctDescriptionHistoryItem,
  resolveDescribeErrorCode,
  type DescriptionHistoryItem,
} from '../api/describeApi';
import { queryKeys } from '../api/queryKeys';
import type { WorkbenchMediaResponse } from '../api/workbenchMediaApi';

interface CorrectMediaAltVariables {
  mediaId: number;
  altText: string;
}

/** Server code for alt-written / human-edit-marker-failed (BR-40 partial). */
const DESCRIPTION_CORRECTION_PARTIAL = 'description_correction_partial';

/**
 * Patch cached workbench pages so the operator sees the alt that storage already
 * holds, without invalidateQueries (which would refetch the missing-status list
 * and unmount the row before the alert can be read — WBUX-5-BR-51).
 */
const reconcilePartialAltInMediaCache = (queryClient: QueryClient, mediaId: number, altText: string): void => {
  const workbenchQueries = queryClient.getQueriesData<WorkbenchMediaResponse>({
    queryKey: queryKeys.media.workbench(),
  });

  for (const [queryKey, data] of workbenchQueries) {
    if (!data?.items?.some((item) => item.id === mediaId)) {
      continue;
    }
    queryClient.setQueryData<WorkbenchMediaResponse>(queryKey, {
      ...data,
      items: data.items.map((item) => (item.id === mediaId ? { ...item, altText } : item)),
    });
  }
};

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
    // Partial success (alt written, human-edit marker failed): reconcile the
    // specific cached row in place. Gate on the stable error code — never on
    // message text. Do not invalidate: a refetch on missing-status lists drops
    // the row and destroys the role=alert the operator still needs [RLSE-04].
    onError: (error, variables) => {
      if (resolveDescribeErrorCode(error) !== DESCRIPTION_CORRECTION_PARTIAL) {
        return;
      }
      reconcilePartialAltInMediaCache(queryClient, variables.mediaId, variables.altText);
    },
  });
};
