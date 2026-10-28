/**
 * Host UI locale (the `lang` WordPress prints on <html>) and the formatters that
 * read it [FORM-02][sr-012]. A missing, malformed or unsupported tag renders
 * neutral raw output, never the runtime's default locale: a German admin must
 * not see en-US separators because the browser happened to be English.
 */
export type HostLocale =
  | { kind: 'localized'; tag: string }
  | { kind: 'neutral-raw'; reason: 'missing' | 'invalid' | 'unsupported' | 'unavailable' };

type SupportedLocalesOf = (locales: string[]) => string[];

export const readHostUiLocale = (): string | null => {
  try {
    return typeof document === 'undefined' ? null : document.documentElement.lang || null;
  } catch {
    return null;
  }
};

// `supportedLocalesOf` is probed per formatter: a constructor handed an
// unsupported tag silently falls back to the runtime default instead of throwing.
const resolveHostLocale = (raw: string | null, supportedLocalesOf: SupportedLocalesOf | null): HostLocale => {
  if (!raw?.trim()) {
    return { kind: 'neutral-raw', reason: 'missing' };
  }
  if (supportedLocalesOf === null || typeof Intl.getCanonicalLocales !== 'function') {
    return { kind: 'neutral-raw', reason: 'unavailable' };
  }
  let tag: string | undefined;
  try {
    [tag] = Intl.getCanonicalLocales(raw.trim());
  } catch (error) {
    return { kind: 'neutral-raw', reason: error instanceof RangeError ? 'invalid' : 'unavailable' };
  }
  if (!tag) {
    return { kind: 'neutral-raw', reason: 'invalid' };
  }
  try {
    return supportedLocalesOf([tag]).includes(tag)
      ? { kind: 'localized', tag }
      : { kind: 'neutral-raw', reason: 'unsupported' };
  } catch {
    return { kind: 'neutral-raw', reason: 'unavailable' };
  }
};

const numberLocalesOf = (): SupportedLocalesOf | null =>
  typeof Intl === 'undefined' || typeof Intl.NumberFormat?.supportedLocalesOf !== 'function'
    ? null
    : (locales) => Intl.NumberFormat.supportedLocalesOf(locales, { localeMatcher: 'lookup' });

const dateLocalesOf = (): SupportedLocalesOf | null =>
  typeof Intl === 'undefined' || typeof Intl.DateTimeFormat?.supportedLocalesOf !== 'function'
    ? null
    : (locales) => Intl.DateTimeFormat.supportedLocalesOf(locales, { localeMatcher: 'lookup' });

export const resolveHostNumberLocale = (raw: string | null): HostLocale => resolveHostLocale(raw, numberLocalesOf());

export const resolveHostDateLocale = (raw: string | null): HostLocale => resolveHostLocale(raw, dateLocalesOf());

/** Whole-number count in the host locale; raw digits otherwise. */
export const formatHostCount = (count: number, uiLocale: string | null): string => {
  const locale = resolveHostNumberLocale(uiLocale);
  if (locale.kind === 'localized') {
    try {
      return new Intl.NumberFormat(locale.tag, { style: 'decimal', maximumFractionDigits: 0 }).format(count);
    } catch {
      // Deliberate neutral raw-numeric fallback; never the runtime default locale.
    }
  }
  return String(count);
};

/**
 * Calendar day of an ISO instant as month + day ("Nov 1") in the host locale;
 * the ISO date ("2026-11-01") otherwise. Read in UTC because billing periods
 * turn over at UTC midnight: local time would show a Nov 1 reset as Oct 31
 * west of Greenwich.
 */
export const formatHostCalendarDay = (isoInstant: string, uiLocale: string | null): string => {
  const instant = new Date(isoInstant);
  if (Number.isNaN(instant.getTime())) {
    return isoInstant;
  }
  const locale = resolveHostDateLocale(uiLocale);
  if (locale.kind === 'localized') {
    try {
      return new Intl.DateTimeFormat(locale.tag, { month: 'short', day: 'numeric', timeZone: 'UTC' }).format(instant);
    } catch {
      // Deliberate neutral raw fallback; never the runtime default locale.
    }
  }
  return instant.toISOString().slice(0, 10);
};
