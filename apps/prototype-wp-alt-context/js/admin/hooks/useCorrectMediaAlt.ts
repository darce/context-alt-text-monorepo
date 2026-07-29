import { type QueryClient, useMutation, useQueryClient } from '@tanstack/react-query';

import {
  correctDescriptionHistoryItem,
  DESCRIPTION_CORRECTION_CODE,
  resolveDescribeErrorCode,
  resolveDescribeErrorDataField,
  type DescriptionHistoryItem,
} from '../api/describeApi';
import { queryKeys } from '../api/queryKeys';
import type { WorkbenchMediaResponse } from '../api/workbenchMediaApi';
import { invalidateMediaStats } from './useMediaStats';

interface CorrectMediaAltVariables {
  mediaId: number;
  altText: string;
}

/**
 * Patch one media row's altText across every cached workbench page, without
 * touching total / totalPages / status. Envelope fields stay server truth
 * [rg-015]; the row stays mounted until a natural refetch (no list invalidate).
 *
 * Used by both full success (from DescriptionHistoryItem.current_alt_text) and
 * partial failure (from server-reported stored_alt_text). Sibling traffic must
 * never blow away an unread partial role=alert by refetching media.all [RLSE-05].
 */
const patchWorkbenchRowAlt = (queryClient: QueryClient, mediaId: number, altText: string): void => {
  const workbenchQueries = queryClient.getQueriesData<WorkbenchMediaResponse>({
    queryKey: queryKeys.media.workbench(),
  });

  for (const [queryKey, data] of workbenchQueries) {
    if (!data?.items) {
      continue;
    }
    const index = data.items.findIndex((item) => item.id === mediaId);
    if (index < 0) {
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
    // Targeted patch only — never invalidateQueries(media.all). That refetch
    // drops corrected (and partial) rows from missing-status pages and destroys
    // unread role=alert / in-progress draft state [RLSE-04][RLSE-05][BR-77].
    //
    // Refresh dashboard coverage counters only (perPage:1 missing probe). Those
    // keys are distinct from the rendered list page, so this cannot unmount a
    // sibling row. Failures / partials do not refresh — we only trust a full
    // write success to move the headline figure [RLSE-04][BR-101].
    //
    // Fire-and-forget: do not await anything here so isPending clears as soon as
    // the write lands (WBUX-5-S2C3A-BR-05).
    //
    // media.details / media.identities are not invalidated: WorkbenchMediaDetail
    // has no alt field, and identities are face-recognition projections. Alt
    // lives on the workbench list, which we patch from the server response.
    onSuccess: (data, variables) => {
      patchWorkbenchRowAlt(queryClient, variables.mediaId, data.current_alt_text);
      invalidateMediaStats(queryClient);
    },

    // Partial success (alt written, human-edit marker failed): reconcile the
    // specific cached row in place from server-reported stored_alt_text only.
    // If that field is absent, leave the cache alone — stale-but-real beats a
    // fabricated request-body guess ([rg-015]). Gate on the stable error code —
    // never on message text. Do not invalidate: a refetch on missing-status
    // lists drops the row and destroys the role=alert the operator still needs
    // [RLSE-04][RLSE-05].
    onError: (error, variables) => {
      if (resolveDescribeErrorCode(error) !== DESCRIPTION_CORRECTION_CODE.PARTIAL) {
        return;
      }
      // Null-only gate: empty string is a legitimate stored alt (sanitize_text_field
      // of a blank correction) and must still reconcile [TEST-15][rg-015].
      const storedAltText = resolveDescribeErrorDataField(error, 'stored_alt_text');
      if (storedAltText === null) {
        return;
      }
      patchWorkbenchRowAlt(queryClient, variables.mediaId, storedAltText);
    },
  });
};
