import { type QueryClient, useMutation, useQueryClient } from '@tanstack/react-query';

import {
  correctDescriptionHistoryItem,
  DESCRIPTION_CORRECTION_CODE,
  resolveDescribeErrorCode,
  resolveDescribeErrorDataBooleanField,
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
   * Tri-state decorative flag [A-02][INT-09]:
   *   true  — plant durable empty-alt marker
   *   false — explicit un-mark (clear marker even with empty alt)
   *   undefined — omit from the wire; two-arg callers keep an identical
   *               correctDescriptionHistoryItem(mediaId, altText) call
   *               [WBUX-5-S2C3C-BR-01][S7-BR-01]
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
 *
 * `$decorative` must be server truth (success is_decorative / PARTIAL
 * is_decorative) — never a client re-derivation from request intent [A-03].
 */
const statusFromServerFacts = (
  altText: string,
  decorative: boolean,
): WorkbenchMediaItem['status'] =>
  '' !== altText.trim() || decorative ? 'complete' : 'missing';

/**
 * Patch one media row's altText, isDecorative, and status across every cached
 * workbench page, without touching total / totalPages. Envelope counts stay
 * server truth [rg-015]; the row stays mounted until a natural refetch (no list
 * invalidate).
 *
 * `isDecorative` is the server-owned marker value from the correction envelope
 * (DescriptionHistoryItem.is_decorative or PARTIAL data.is_decorative) — never
 * recomputed from request intent [A-03][rg-015]. status is derived via
 * statusFromServerFacts (class-api.php:338) so a successful correction no longer
 * leaves status:'missing' forever on the Status=missing workbench
 * [WBUX-5-BR-112], including decorative marks.
 *
 * Used by both full success (from DescriptionHistoryItem) and partial failure
 * (from server-reported stored_alt_text + is_decorative). Sibling traffic must
 * never blow away an unread partial role=alert by refetching media.all [RLSE-05].
 */
const patchWorkbenchRowAlt = (
  queryClient: QueryClient,
  mediaId: number,
  altText: string,
  isDecorative: boolean,
): void => {
  const workbenchQueries = queryClient.getQueriesData<WorkbenchMediaResponse>({
    queryKey: queryKeys.media.workbench(),
  });
  // class-api.php:346 emits null when !has_alt — never ''. Consumers
  // distinguish '' (blank paragraph / alt="") from null ("No alt text yet" /
  // title fallback). Normalize at the patch boundary [API-11][A11Y-04].
  const nextAlt = altText.trim() === '' ? null : altText;
  const status = statusFromServerFacts(altText, isDecorative);

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
      items: data.items.map((item) => {
        if (item.id !== mediaId) {
          return item;
        }
        return { ...item, altText: nextAlt, status, isDecorative };
      }),
    });
  }
};

export const useCorrectMediaAlt = () => {
  const queryClient = useQueryClient();

  return useMutation<DescriptionHistoryItem, Error, CorrectMediaAltVariables>({
    // Pass options whenever decorative is defined (true or false). Two-arg
    // callers (decorative undefined) keep a literal two-argument call — tests
    // pin toHaveBeenCalledWith(mediaId, altText) with no third arg [A-02].
    mutationFn: ({ mediaId, altText, decorative }) =>
      decorative !== undefined
        ? correctDescriptionHistoryItem(mediaId, altText, { decorative })
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
      // is_decorative is server storage truth from build_item — never re-derive
      // from variables.decorative [A-03][rg-015].
      patchWorkbenchRowAlt(
        queryClient,
        variables.mediaId,
        data.current_alt_text,
        data.is_decorative,
      );
      invalidateMediaStats(queryClient);
    },

    // Partial success (alt written, human-edit / decorative plant failed):
    // reconcile the specific cached row in place from server-reported
    // stored_alt_text + is_decorative. Do not invent decorative from request
    // intent [A-03][rg-015]. If either server field is absent, leave the cache
    // alone — stale-but-real beats a fabricated guess. Gate on the stable error
    // code — never on message text. Do not invalidate: a refetch on missing-status
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
      // Boolean null gate: absent is_decorative must not fall back to request
      // intent or a cached prior re-derivation [A-03][rg-015].
      const storedIsDecorative = resolveDescribeErrorDataBooleanField(error, 'is_decorative');
      if (storedIsDecorative === null) {
        return;
      }
      patchWorkbenchRowAlt(queryClient, variables.mediaId, storedAltText, storedIsDecorative);
    },
  });
};
