import { describe, expect, it } from 'vitest';

import {
  normalizeRepresentativeMediaId,
  normalizeTopUnlabeledRepresentative,
} from '../normalizeTopUnlabeledRepresentative';

const ATTACHMENT_URL = 'https://example.test/unlabeled-attachment.jpg';

describe('normalizeTopUnlabeledRepresentative', () => {
  it('passes a real attachment_url through normalizeOptionalUrl', () => {
    const mapped = normalizeTopUnlabeledRepresentative({
      id: 'rep-1',
      attachment_url: ATTACHMENT_URL,
    });

    expect(mapped).toHaveProperty('attachment_url', ATTACHMENT_URL);
    expect(mapped.attachment_url).toBe(ATTACHMENT_URL);
  });

  it('normalizes missing, empty, and whitespace-only attachment_url values to null', () => {
    const omitted = normalizeTopUnlabeledRepresentative({ id: 'rep-omitted' });
    const fromNull = normalizeTopUnlabeledRepresentative({
      id: 'rep-null',
      attachment_url: null,
    });
    const fromUndefined = normalizeTopUnlabeledRepresentative({
      id: 'rep-undefined',
      attachment_url: undefined,
    });
    const fromEmpty = normalizeTopUnlabeledRepresentative({
      id: 'rep-empty',
      attachment_url: '',
    });
    const fromWhitespace = normalizeTopUnlabeledRepresentative({
      id: 'rep-whitespace',
      attachment_url: '   \t  ',
    });

    expect(omitted).toHaveProperty('attachment_url', null);
    expect(fromNull).toHaveProperty('attachment_url', null);
    expect(fromUndefined).toHaveProperty('attachment_url', null);
    expect(fromEmpty).toHaveProperty('attachment_url', null);
    expect(fromWhitespace).toHaveProperty('attachment_url', null);
    expect(omitted.attachment_url).toBeNull();
    expect(fromNull.attachment_url).toBeNull();
    expect(fromUndefined.attachment_url).toBeNull();
    expect(fromEmpty.attachment_url).toBeNull();
    expect(fromWhitespace.attachment_url).toBeNull();
  });

  it('maps media_id through normalizeRepresentativeMediaId and is_user_selected to is_pinned', () => {
    const mapped = normalizeTopUnlabeledRepresentative({
      id: 'rep-2',
      media_id: '42',
      is_user_selected: true,
    });

    expect(mapped.media_id).toBe(42);
    expect(mapped.is_pinned).toBe(true);
  });
});

describe('normalizeRepresentativeMediaId', () => {
  it('parses digit strings and keeps null for missing or non-digit values', () => {
    expect(normalizeRepresentativeMediaId('7')).toBe(7);
    expect(normalizeRepresentativeMediaId('0')).toBe(0);
    expect(normalizeRepresentativeMediaId(null)).toBeNull();
    expect(normalizeRepresentativeMediaId(undefined)).toBeNull();
    expect(normalizeRepresentativeMediaId('')).toBeNull();
    expect(normalizeRepresentativeMediaId('12.5')).toBeNull();
    expect(normalizeRepresentativeMediaId('abc')).toBeNull();
    expect(normalizeRepresentativeMediaId(42)).toBeNull();
  });
});
