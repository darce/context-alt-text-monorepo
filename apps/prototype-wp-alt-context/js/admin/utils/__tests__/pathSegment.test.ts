import { describe, expect, it } from 'vitest';

import { idPathSegment, InvalidIdPathSegmentError } from '../pathSegment';

describe('idPathSegment', () => {
  it.each(['..', '../users', 'a/b', 'a?x=1', '%2e%2e', '', 'a\\b', 'a#b', 'a&b', 'a.b', 'a\n', 'a'.repeat(129)])(
    'rejects an unsafe ID: %j',
    (value) => {
      expect(() => idPathSegment(value)).toThrow(InvalidIdPathSegmentError);
    },
  );

  it.each(['cluster-1', '123e4567-e89b-12d3-a456-426614174000', 'c-same', 'x', 'A_0', 'a'.repeat(128)])(
    'accepts and encodes an allowed ID: %s',
    (value) => {
      expect(idPathSegment(value)).toBe(encodeURIComponent(value));
    },
  );
});
