/**
 * Decode the HTML character references WordPress escaping can leave in stored
 * meta (alt text). Pure string transform — no DOM, no HTML parse, no sink.
 *
 * Handles the five named references WP emits (`&amp;` `&lt;` `&gt;` `&quot;`
 * `&#039;`) plus decimal (`&#NN;`) and hex (`&#xNN;`) numeric references.
 *
 * Single-pass: `&amp;lt;` becomes the literal text `&lt;`, never `<`.
 * A sequential replace that decoded `&amp;` first would double-decode.
 */

// Null-prototype map so lookup is own-property-only: bodies that match
// Object.prototype keys (constructor, toString, …) must stay literal.
const NAMED: Readonly<Record<string, string>> = Object.assign(
  Object.create(null) as Record<string, string>,
  {
    amp: '&',
    lt: '<',
    gt: '>',
    quot: '"',
    // HTML named form; WP itself writes the apostrophe as `&#039;`.
    apos: "'",
  },
);

/**
 * True when the code point must not be emitted as a decoded character.
 * Rejects NUL and the UTF-16 surrogate range; PHP html_entity_decode leaves
 * both undecoded.
 */
const isUnsafeCodePoint = (codePoint: number): boolean =>
  codePoint === 0 || (codePoint >= 0xd800 && codePoint <= 0xdfff);

/**
 * Decode a single character-reference body (without the leading `&` / trailing
 * `;`). Returns null when the body is not a recognised reference.
 */
const decodeReferenceBody = (body: string): string | null => {
  if (body.startsWith('#x') || body.startsWith('#X')) {
    const hex = body.slice(2);
    if (hex === '' || !/^[0-9a-fA-F]+$/.test(hex)) {
      return null;
    }
    const codePoint = Number.parseInt(hex, 16);
    if (
      !Number.isFinite(codePoint) ||
      codePoint < 0 ||
      codePoint > 0x10ffff ||
      isUnsafeCodePoint(codePoint)
    ) {
      return null;
    }
    try {
      return String.fromCodePoint(codePoint);
    } catch {
      return null;
    }
  }

  if (body.startsWith('#')) {
    const dec = body.slice(1);
    if (dec === '' || !/^\d+$/.test(dec)) {
      return null;
    }
    const codePoint = Number.parseInt(dec, 10);
    if (
      !Number.isFinite(codePoint) ||
      codePoint < 0 ||
      codePoint > 0x10ffff ||
      isUnsafeCodePoint(codePoint)
    ) {
      return null;
    }
    try {
      return String.fromCodePoint(codePoint);
    } catch {
      return null;
    }
  }

  // Own-property only: NAMED has a null prototype so inherited keys never match.
  return NAMED[body] ?? null;
};

/**
 * Decode HTML character references in a stored-meta string.
 * Values that contain no references are returned unchanged.
 */
export const decodeHtmlEntities = (value: string): string => {
  if (value === '' || !value.includes('&')) {
    return value;
  }

  // Single pass left-to-right. Each `&…;` is decoded at most once, so
  // `&amp;lt;` → `&lt;` and never further to `<`.
  return value.replace(/&(#(?:x[0-9a-fA-F]+|[0-9]+)|[a-zA-Z][a-zA-Z0-9]*);/g, (match, body: string) => {
    return decodeReferenceBody(body) ?? match;
  });
};
