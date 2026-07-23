import { describe, expect, it } from 'vitest';

import { DATA_SOURCE } from '../../../api/recognition/types';
import { deriveIdentitiesPresentationSource } from '../deriveIdentitiesPresentationSource';

/**
 * S3-T2 branch-copy matrix (presentation derivation) + matrix cells 1–4 predicates.
 * Leaf copy strings for empty branches are pinned on IdentityClusterList; this
 * unit pins the client-error → UNAVAILABLE mapping (never ENDPOINT_ERROR).
 */
describe('deriveIdentitiesPresentationSource (Slice 3)', () => {
  it('S3-T1/cell1: isError with no cached data maps to UNAVAILABLE', () => {
    expect(deriveIdentitiesPresentationSource(true, undefined)).toBe(DATA_SOURCE.UNAVAILABLE);
  });

  it('S3-T2: client error maps to UNAVAILABLE, never ENDPOINT_ERROR', () => {
    const derived = deriveIdentitiesPresentationSource(true, undefined);
    expect(derived).toBe(DATA_SOURCE.UNAVAILABLE);
    expect(derived).not.toBe(DATA_SOURCE.ENDPOINT_ERROR);
  });

  it('S3-T3/cell2: isError with same-key cached data keeps envelope data_source', () => {
    expect(
      deriveIdentitiesPresentationSource(true, { data_source: DATA_SOURCE.LOCAL_PROJECTION }),
    ).toBe(DATA_SOURCE.LOCAL_PROJECTION);
    expect(
      deriveIdentitiesPresentationSource(true, { data_source: DATA_SOURCE.BACKEND_PROXY }),
    ).toBe(DATA_SOURCE.BACKEND_PROXY);
  });

  it('cell4: success paths pass through envelope data_source (including empty maps)', () => {
    expect(
      deriveIdentitiesPresentationSource(false, { data_source: DATA_SOURCE.LOCAL_PROJECTION }),
    ).toBe(DATA_SOURCE.LOCAL_PROJECTION);
    expect(
      deriveIdentitiesPresentationSource(false, { data_source: DATA_SOURCE.BACKEND_PROXY }),
    ).toBe(DATA_SOURCE.BACKEND_PROXY);
    expect(
      deriveIdentitiesPresentationSource(false, { data_source: DATA_SOURCE.ENDPOINT_ERROR }),
    ).toBe(DATA_SOURCE.ENDPOINT_ERROR);
    expect(
      deriveIdentitiesPresentationSource(false, { data_source: DATA_SOURCE.UNAVAILABLE }),
    ).toBe(DATA_SOURCE.UNAVAILABLE);
    expect(deriveIdentitiesPresentationSource(false, undefined)).toBeUndefined();
  });
});
