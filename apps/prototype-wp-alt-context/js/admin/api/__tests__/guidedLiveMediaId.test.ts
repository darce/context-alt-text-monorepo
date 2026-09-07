import { beforeEach, describe, expect, it } from 'vitest';

import { getGuidedLiveMediaId, normalizeConfig, registerConfig, resetConfigCache } from '../config';

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

  /**
   * Same predicate as the publisher. `Admin::get_guided_live_media_id` runs
   * `FILTER_VALIDATE_INT`, which reads only decimal digits and tolerates
   * surrounding whitespace. `Number()` disagreed on every row below: it read
   * hex and exponent notation as valid ids the PHP side had already refused,
   * so the two ends could disagree about whether the demo has a subject
   * (rg-005 schema/contract parity).
   */
  it.each(['0x1a', '1e10', '4211.0', '1_000', ' ', '+', '٤٢'])(
    'rejects %p, which FILTER_VALIDATE_INT also rejects',
    (value) => {
      expect(normalize(value)).toBeNull();
    },
  );

  it.each([' 4211', '4211 ', ' 4211 ', '+4211'])('accepts %p, which FILTER_VALIDATE_INT also accepts', (value) => {
    expect(normalize(value)).toBe(4211);
  });
});

/**
 * The guided prototype is the one admin screen that renders without the SPA
 * bootstrap (the entrance card, and component tests in isolation). A missing
 * bootstrap means there is no live run to offer — not a crash that takes the
 * lesson down with it.
 */
describe('reading the guided live media id without a bootstrap', () => {
  beforeEach(() => {
    resetConfigCache();
    delete window.AltContextAdmin;
  });

  it('reports no configured media when AltContextAdmin is absent', () => {
    expect(getGuidedLiveMediaId()).toBeNull();
  });

  it('reports the configured id once the bootstrap is registered', () => {
    registerConfig({ nonce: 'abc', ajaxUrl: '/ajax', endpoints: {}, guided_live_media_id: '4211' });

    expect(getGuidedLiveMediaId()).toBe(4211);
  });
});
