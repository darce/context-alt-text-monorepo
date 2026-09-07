import { beforeEach, describe, expect, it } from 'vitest';

import { normalizeConfig, resetConfigCache } from '../config';

/**
 * The guided prototype's live run needs one real attachment. The id arrives
 * through wp_localize_script, which stringifies numbers, so the boundary has to
 * normalize rather than trust ([SEC-01] validate at every trust boundary). An
 * absent or nonsense id degrades that one capability instead of failing the
 * whole admin config load, matching the soft-fail policy the module already has.
 */
describe('guided live media id at the config boundary', () => {
  beforeEach(() => {
    resetConfigCache();
  });

  const normalize = (value: unknown) =>
    normalizeConfig({
      nonce: 'abc',
      ajaxUrl: '/ajax',
      endpoints: {},
      guided_live_media_id: value,
    }).guidedLiveMediaId;

  it('keeps a positive integer id', () => {
    expect(normalize(4211)).toBe(4211);
  });

  it('accepts the string wp_localize_script actually emits', () => {
    expect(normalize('4211')).toBe(4211);
  });

  it('reports no configured media when the field is absent', () => {
    expect(normalizeConfig({ nonce: 'abc', ajaxUrl: '/ajax', endpoints: {} }).guidedLiveMediaId).toBeNull();
  });

  it.each([0, '0', -3, '-3', 1.5, 'abc', '', null, true])('rejects %p, which is not an attachment id', (value) => {
    expect(normalize(value)).toBeNull();
  });
});
