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

  /**
   * The parity table above only listed rows where the two ends already agreed,
   * so it could not fail when they diverged. These are the rows a probe of the
   * real `filter_var` disagreed on: PHP refuses a leading-zero spelling, and
   * its whitespace tolerance is the ASCII set `" \t\n\r\v"` -- not
   * `String.prototype.trim`, which also strips U+000C, NBSP and the BOM. Each
   * one let JS report a configured subject the publisher had already refused.
   */
  it.each(['0001', '+0001', '\f4211', '\u00A04211', '\uFEFF4211'])(
    'rejects %j, which FILTER_VALIDATE_INT also rejects',
    (value) => {
      expect(normalize(value)).toBeNull();
    },
  );

  // U+000B is the one control character PHP's trim set does include, so
  // rejecting it here would invent a divergence rather than close one.
  it('accepts a vertical-tab-padded id, which FILTER_VALIDATE_INT also accepts', () => {
    expect(normalize('\v4211')).toBe(4211);
  });

  /**
   * The string branch bounds itself with `Number.isSafeInteger`; the number
   * branch did not, so the same id was accepted or refused depending only on
   * which JSON type it arrived as. Above 2^53 the value is not the id anymore.
   */
  it('rejects a number above the safe-integer range, where the value is no longer exact', () => {
    expect(normalize(2 ** 53)).toBeNull();
  });

  /**
   * JS has no integer/float distinction, so a whole-valued number is
   * indistinguishable from an int and is accepted. PHP refuses the float
   * outright (its allow-list takes string and int only). Pinned, not fixed:
   * the localized wire always carries a string, so this branch is reachable
   * only from a hand-built payload, and reading 4211.0 as 4211 is the honest
   * answer there.
   */
  it('accepts a whole-valued number, the one shape JS cannot tell from an int', () => {
    expect(normalize(4211.0)).toBe(4211);
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

describe('the guard that production actually runs through', () => {
  beforeEach(() => {
    resetConfigCache();
  });

  // wp_localize_script stringifies every scalar, so the id reaches the browser
  // as '4211', not 4211. The safe-integer bound was asserted only on the number
  // branch, which production never takes: deleting it from the string branch
  // left the whole suite green while '9007199254740993' silently became
  // 9007199254740992 -- a different attachment.
  it('refuses a stringified id past the safe-integer bound', () => {
    registerConfig({ nonce: 'n', ajaxUrl: '/a', endpoints: {}, guided_live_media_id: '9007199254740993' });
    expect(getGuidedLiveMediaId()).toBeNull();

    resetConfigCache();
    registerConfig({ nonce: 'n', ajaxUrl: '/a', endpoints: {}, guided_live_media_id: '9007199254740992' });
    expect(getGuidedLiveMediaId()).toBeNull();
  });

  it('accepts the largest stringified id it can represent exactly', () => {
    registerConfig({ nonce: 'n', ajaxUrl: '/a', endpoints: {}, guided_live_media_id: '9007199254740991' });
    expect(getGuidedLiveMediaId()).toBe(9007199254740991);
  });
});
