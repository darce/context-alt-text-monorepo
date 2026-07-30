import { type QueryClient, useMutation, useQueryClient } from '@tanstack/react-query';

import {
  correctDescriptionHistoryItem,
  DESCRIPTION_CORRECTION_CODE,
  resolveDescribeErrorCode,
  resolveDescribeErrorDataField,
  type DescriptionHistoryItem,
} from '../api/describeApi';
import { queryKeys } from '../api/queryKeys';
import type { WorkbenchMediaItem, WorkbenchMediaResponse } from '../api/workbenchMediaApi';
import { invalidateMediaStats } from './useMediaStats';

interface CorrectMediaAltVariables {
  mediaId: number;
  altText: string;
  /**
   * When true, posts decorative:true with the correction so the server plants
   * the durable empty-alt marker. Omitted / false keeps the ordinary two-arg
   * wire body for Accept/Save and other callers [WBUX-5-S2C3C-BR-01][S7-BR-01].
   */
  decorative?: boolean;
}

/**
 * Derive workbench row status from the same two facts the list producer uses.
 *
 * Authoritative rule is class-api.php:338 —
 *   `'status' => ( $has_alt || $is_decorative ) ? 'complete' : 'missing'`
 * Empty alt with decorative marker is 'complete' on a real refetch; deriving
 * from alt alone would mis-classify decorative success as 'missing'
 * [rg-015][DATA-14][WBUX-5-BR-112].
 */
const statusFromServerFacts = (
  altText: string,
  decorative: boolean,
): WorkbenchMediaItem['status'] =>
  '' !== altText.trim() || decorative ? 'complete' : 'missing';

interface PatchWorkbenchRowAltOptions {
  /**
   * True when this write planted (or reaffirmed) the durable decorative marker.
   * PARTIAL failures must omit / pass false — the marker was not stored.
   */
  decorative?: boolean;
}

/**
 * Patch one media row's altText and status across every cached workbench page,
 * without touching total / totalPages. Envelope counts stay server truth
 * [rg-015]; the row stays mounted until a natural refetch (no list invalidate).
 *
 * status is derived via statusFromServerFacts (class-api.php:338) so a
 * successful correction no longer leaves status:'missing' forever on the
 * Status=missing workbench [WBUX-5-BR-112], including decorative marks.
 *
 * Used by both full success (from DescriptionHistoryItem.current_alt_text) and
 * partial failure (from server-reported stored_alt_text). Sibling traffic must
 * never blow away an unread partial role=alert by refetching media.all [RLSE-05].
 */
const patchWorkbenchRowAlt = (
  queryClient: QueryClient,
  mediaId: number,
  altText: string,
  options?: PatchWorkbenchRowAltOptions,
): void => {
  const workbenchQueries = queryClient.getQueriesData<WorkbenchMediaResponse>({
    queryKey: queryKeys.media.workbench(),
  });
  const decorative = options?.decorative === true;
  // class-api.php:346 emits null when !has_alt — never ''. Consumers
  // distinguish '' (blank paragraph / alt="") from null ("No alt text yet" /
  // title fallback). Normalize at the patch boundary [API-11][A11Y-04].
  const nextAlt = altText.trim() === '' ? null : altText;

  for (const [queryKey, data] of workbenchQueries) {
    if (!data?.items) {
      continue;
    }
    const index = data.items.findIndex((item) => item.id === mediaId);
    if (index < 0) {
      continue;
    }
    const status = statusFromServerFacts(altText, decorative);
    queryClient.setQueryData<WorkbenchMediaResponse>(queryKey, {
      ...data,
      items: data.items.map((item) =>
        item.id === mediaId ? { ...item, altText: nextAlt, status } : item,
      ),
    });
  }
};

export const useCorrectMediaAlt = () => {
  const queryClient = useQueryClient();

  return useMutation<DescriptionHistoryItem, Error, CorrectMediaAltVariables>({
    // Pass decorative only when true so two-arg callers keep an identical
    // correctDescriptionHistoryItem(mediaId, altText) call signature (tests pin
    // toHaveBeenCalledWith without a third arg).
    mutationFn: ({ mediaId, altText, decorative }) =>
      decorative === true
        ? correctDescriptionHistoryItem(mediaId, altText, { decorative: true })
        : correctDescriptionHistoryItem(mediaId, altText),
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
      // Thread decorative intent so status mirrors class-api.php:338 (has_alt
      // OR is_decorative). PARTIAL onError omits decorative — marker not stored.
      patchWorkbenchRowAlt(queryClient, variables.mediaId, data.current_alt_text, {
        decorative: variables.decorative === true,
      });
      invalidateMediaStats(queryClient);
    },

    // Partial success (alt written, human-edit / decorative marker failed):
    // reconcile the specific cached row in place from server-reported
    // stored_alt_text only. Marker was NOT stored, so do not pass decorative.
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
