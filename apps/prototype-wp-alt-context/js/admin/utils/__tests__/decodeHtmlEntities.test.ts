import { describe, expect, it } from 'vitest';

import { decodeHtmlEntities } from '../decodeHtmlEntities';

/**
 * Faithful-enough stand-in for WordPress `sanitize_text_field` as used by the
 * description correction write path: bare `<` (no closing `>`) is entity-encoded
 * via the pre-kses path; ampersands and intentional entity text are NOT
 * re-encoded. Mirrors the in-tree stub at tests/stubs/wp.php.
 */
const simulateSanitizeTextField = (input: string): string => {
  let filtered = input;
  if (filtered.includes('<')) {
    // wp_pre_kses_less_than: encode segments that open with `<` and never close.
    filtered = filtered.replace(/<[^>]*?(?=<|$)/g, (segment) => {
      if (segment.includes('>')) {
        return segment;
      }
      return segment
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    });
    // strip_tags would remove real tags; bare-`<` prose has already been encoded.
  }
  filtered = filtered.replace(/[\r\n\t ]+/g, ' ').trim();
  return filtered;
};

const roundTrip = (stored: string): string =>
  simulateSanitizeTextField(decodeHtmlEntities(stored));

describe('decodeHtmlEntities', () => {
  it('returns empty and plain strings unchanged', () => {
    expect(decodeHtmlEntities('')).toBe('');
    expect(decodeHtmlEntities('Bridge at dusk')).toBe('Bridge at dusk');
    expect(decodeHtmlEntities('a & b')).toBe('a & b');
  });

  it('decodes the five named references WordPress escaping emits', () => {
    expect(decodeHtmlEntities('&amp;')).toBe('&');
    expect(decodeHtmlEntities('&lt;')).toBe('<');
    expect(decodeHtmlEntities('&gt;')).toBe('>');
    expect(decodeHtmlEntities('&quot;')).toBe('"');
    expect(decodeHtmlEntities('&#039;')).toBe("'");
  });

  it('decodes decimal and hex numeric character references', () => {
    expect(decodeHtmlEntities('&#60;')).toBe('<');
    expect(decodeHtmlEntities('&#x3c;')).toBe('<');
    expect(decodeHtmlEntities('&#x3C;')).toBe('<');
    expect(decodeHtmlEntities('&#38;')).toBe('&');
    expect(decodeHtmlEntities('&#x26;')).toBe('&');
  });

  it('decodes the comparison-operator storage form operators actually hit (BR-140)', () => {
    expect(decodeHtmlEntities('x &lt;= y')).toBe('x <= y');
    expect(decodeHtmlEntities('a &lt; b and c &gt; d')).toBe('a < b and c > d');
  });

  it('decodes &amp; only once so &amp;lt; becomes the literal text &lt; (not <)', () => {
    // Single-pass / amp-last: sequential replace that expands &amp; first then
    // rescans would turn this into `<`.
    expect(decodeHtmlEntities('x &amp;lt; y')).toBe('x &lt; y');
    expect(decodeHtmlEntities('&amp;amp;')).toBe('&amp;');
    expect(decodeHtmlEntities('&amp;quot;')).toBe('&quot;');
  });

  it('leaves unrecognised or incomplete references untouched', () => {
    expect(decodeHtmlEntities('&unknown;')).toBe('&unknown;');
    expect(decodeHtmlEntities('&lt')).toBe('&lt');
    expect(decodeHtmlEntities('&#;')).toBe('&#;');
    expect(decodeHtmlEntities('&#x;')).toBe('&#x;');
  });

  it('does not resolve Object.prototype keys via the named lookup (BR-152)', () => {
    // NAMED must be own-property-only. A plain object literal falls through to
    // Object.prototype, and String.replace coerces the function to source text.
    expect(decodeHtmlEntities('&constructor;')).toBe('&constructor;');
    expect(decodeHtmlEntities('&toString;')).toBe('&toString;');
    expect(decodeHtmlEntities('a &toString; b')).toBe('a &toString; b');
    expect(decodeHtmlEntities('&valueOf;')).toBe('&valueOf;');
    expect(decodeHtmlEntities('&hasOwnProperty;')).toBe('&hasOwnProperty;');
  });

  it('leaves NUL and surrogate numeric references undecoded (BR-153)', () => {
    // PHP html_entity_decode leaves both undecoded; String.fromCodePoint does
    // not throw on lone surrogates, so the range must be rejected explicitly.
    expect(decodeHtmlEntities('&#0;')).toBe('&#0;');
    expect(decodeHtmlEntities('&#55296;')).toBe('&#55296;'); // U+D800
    expect(decodeHtmlEntities('&#xD800;')).toBe('&#xD800;');
    expect(decodeHtmlEntities('&#xDFFF;')).toBe('&#xDFFF;');
  });

  it('round-trip happy path: stored x &lt;= y → display x <= y → save → x &lt;= y', () => {
    const stored = 'x &lt;= y';
    const displayed = decodeHtmlEntities(stored);
    expect(displayed).toBe('x <= y');
    // Operator saves unchanged; server re-runs sanitize_text_field.
    expect(simulateSanitizeTextField(displayed)).toBe(stored);
    expect(roundTrip(stored)).toBe(stored);
  });

  it('round-trip adversarial: stored x &amp;lt; y is NOT stable under sanitize_text_field', () => {
    // Brief intent: operator literally typed `&lt;` → stored as `x &amp;lt; y`
    // under a full entity-encode-on-write. Real correction writes use
    // sanitize_text_field, which only encodes bare `<` and does NOT re-encode
    // `&`. Decode-on-read therefore cannot form a stable loop for this case.
    const stored = 'x &amp;lt; y';
    const displayed = decodeHtmlEntities(stored);
    expect(displayed).toBe('x &lt; y');
    const resaved = simulateSanitizeTextField(displayed);
    // Actual server behaviour: resaved stays single-encoded, not double-encoded.
    expect(resaved).toBe('x &lt; y');
    expect(resaved).not.toBe(stored);
  });
});
