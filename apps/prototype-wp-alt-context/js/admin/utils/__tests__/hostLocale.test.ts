import { describe, expect, it } from 'vitest';

import { formatHostCalendarDay, formatHostCount, resolveHostDateLocale, resolveHostNumberLocale } from '../hostLocale';

describe('host locale resolution', () => {
  it.each([
    [null, { kind: 'neutral-raw', reason: 'missing' }],
    ['  ', { kind: 'neutral-raw', reason: 'missing' }],
    ['not a locale!', { kind: 'neutral-raw', reason: 'invalid' }],
    ['zz-ZZ', { kind: 'neutral-raw', reason: 'unsupported' }],
    ['de-de', { kind: 'localized', tag: 'de-DE' }],
  ])('resolves %o', (raw, expected) => {
    expect(resolveHostNumberLocale(raw)).toEqual(expected);
    expect(resolveHostDateLocale(raw)).toEqual(expected);
  });
});

describe('formatHostCount', () => {
  it('groups digits in the host locale', () => {
    expect(formatHostCount(1234, 'de-DE')).toBe('1.234');
  });

  it.each([null, 'zz-ZZ', 'not a locale!'])('renders raw digits for %o', (locale) => {
    expect(formatHostCount(1234, locale)).toBe('1234');
  });
});

describe('formatHostCalendarDay', () => {
  it('formats the UTC calendar day in the host locale', () => {
    expect(formatHostCalendarDay('2026-11-01T00:00:00Z', 'en-US')).toBe('Nov 1');
  });

  it('reads the day in UTC, not local time', () => {
    expect(formatHostCalendarDay('2026-11-01T00:00:00Z', null)).toBe('2026-11-01');
    expect(formatHostCalendarDay('2026-10-31T23:30:00-05:00', null)).toBe('2026-11-01');
  });

  it.each([null, 'zz-ZZ'])('renders the ISO date for %o', (locale) => {
    expect(formatHostCalendarDay('2026-11-01T00:00:00Z', locale)).toBe('2026-11-01');
  });

  it('returns an unparseable value unchanged', () => {
    expect(formatHostCalendarDay('soon', 'en-US')).toBe('soon');
  });
});
