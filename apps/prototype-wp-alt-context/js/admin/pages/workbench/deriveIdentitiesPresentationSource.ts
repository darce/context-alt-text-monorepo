import { DATA_SOURCE, type DataSource } from '../../api/recognition/types';

/**
 * Presentation-only derivation for the media-row identity surface.
 *
 * Maps the client query-error path (no envelope) to UNAVAILABLE so
 * IdentityClusterList can keep a single dataSource-shaped input. Does not
 * invent envelope fields at the API layer (rg-015): only derives UI state when
 * React Query reports isError with no retained cache for the current key.
 *
 * State matrix:
 * 1. isError × no cached data → UNAVAILABLE (unavailable affordance)
 * 2. isError × same-key cached data → pass through cached data_source (labels stay)
 * 3. pending + placeholder → data from previous key; never coexists with isError
 * 4. success × empty map → genuine-empty branch via envelope data_source
 */
export const deriveIdentitiesPresentationSource = (
  isError: boolean,
  data: { data_source?: DataSource } | undefined,
): DataSource | undefined => {
  if (isError && data === undefined) {
    return DATA_SOURCE.UNAVAILABLE;
  }
  return data?.data_source;
};
