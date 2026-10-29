import { fetchRequiredApi } from '../utils/http';
import { getConfig, getEndpoint } from './config';

/**
 * Tenant usage read (GET acx/v1/usage). Display-only: the service is the one
 * authority on the balance [DATA-14], and admission is decided server-side.
 */

/** Endpoint key published by Admin::localize_spa_config for acx/v1/usage. */
export const TENANT_USAGE_ENDPOINT_KEY = 'usage';

/** A balance read fails fast to "unavailable" instead of holding the 300 s HTTP backstop [RES-02]. */
export const TENANT_USAGE_TIMEOUT_MS = 15_000;

export const TENANT_USAGE_STATUS = {
  BETA_ACTIVE: 'beta_active',
  PAID_ACTIVE: 'paid_active',
  PAST_DUE: 'past_due',
  EXPIRED: 'expired',
  REVOKED: 'revoked',
} as const;

export type TenantUsageStatus = (typeof TENANT_USAGE_STATUS)[keyof typeof TENANT_USAGE_STATUS];

/** The `data_source` that marks counts as settled; any other value is still updating. */
export const TENANT_USAGE_AUTHORITATIVE_SOURCE = 'authoritative';

export interface TenantUsagePeriod {
  start: string;
  end: string;
}

export interface TenantUsage {
  tenant_id: string;
  used: number | null;
  reserved: number | null;
  remaining: number | null;
  allowance: number | null;
  period_start: string;
  period_end: string;
  period: TenantUsagePeriod;
  as_of: string | null;
  status: TenantUsageStatus | null;
  data_source: string;
}

export class MalformedTenantUsageError extends Error {
  readonly field: string;

  constructor(field: string) {
    super(`Tenant usage response is missing or malformed: ${field}`);
    this.name = 'MalformedTenantUsageError';
    this.field = field;
  }
}

const TENANT_USAGE_KEYS = [
  'tenant_id',
  'used',
  'reserved',
  'remaining',
  'allowance',
  'period_start',
  'period_end',
  'period',
  'as_of',
  'status',
  'data_source',
] as const;

const PERIOD_KEYS = ['start', 'end'] as const;

const ISO_DATE_TIME = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-](\d{2}):(\d{2}))$/;

/** The lower-case hyphenated form WordPress `wp_is_uuid` accepts on the proxy. */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

const daysInMonth = (year: number, month: number): number => {
  if (month === 2) {
    return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28;
  }
  return [4, 6, 9, 11].includes(month) ? 30 : 31;
};

/**
 * An explicit-offset ISO-8601 date-time with a real calendar date and time.
 * Date.parse alone accepts 2026-02-30 and 24:00; the PHP proxy
 * (is_usage_date_time) applies this same rule.
 */
const isDateTime = (text: string): boolean => {
  const match = ISO_DATE_TIME.exec(text);
  if (match === null) {
    return false;
  }
  // A "Z" offset leaves the offset groups unmatched (undefined).
  const parts = match.slice(1).map((part: string | undefined) => (part === undefined ? 0 : Number(part)));
  const [year, month, day, hour, minute, second, offsetHour, offsetMinute] = parts;
  return (
    year >= 1 &&
    month >= 1 &&
    month <= 12 &&
    day >= 1 &&
    day <= daysInMonth(year, month) &&
    hour <= 23 &&
    minute <= 59 &&
    second <= 59 &&
    offsetHour <= 23 &&
    offsetMinute <= 59
  );
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const rejectUnexpectedKeys = (record: Record<string, unknown>, keys: readonly string[], path: string): void => {
  const missing = keys.find((key) => !Object.hasOwn(record, key));
  if (missing !== undefined) {
    throw new MalformedTenantUsageError(`${path}${missing}`);
  }
  const extra = Object.keys(record).find((key) => !keys.includes(key));
  if (extra !== undefined) {
    throw new MalformedTenantUsageError(`${path}${extra}`);
  }
};

const readString = (value: unknown, field: string): string => {
  if (typeof value !== 'string') {
    throw new MalformedTenantUsageError(field);
  }
  return value;
};

const readUuid = (value: unknown, field: string): string => {
  const text = readString(value, field);
  if (!UUID.test(text)) {
    throw new MalformedTenantUsageError(field);
  }
  return text;
};

const readDateTime = (value: unknown, field: string): string => {
  const text = readString(value, field);
  if (!isDateTime(text)) {
    throw new MalformedTenantUsageError(field);
  }
  return text;
};

const readNullableDateTime = (value: unknown, field: string): string | null =>
  value === null ? null : readDateTime(value, field);

/**
 * Null stays null: an unknown count is never coerced to 0 [DATA-14]. A count
 * is otherwise a nonnegative integer; anything else fails closed before render.
 */
const readCount = (value: unknown, field: string): number | null => {
  if (value === null) {
    return null;
  }
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) {
    throw new MalformedTenantUsageError(field);
  }
  return value;
};

const readStatus = (value: unknown): TenantUsageStatus | null => {
  if (value === null) {
    return null;
  }
  const status = Object.values(TENANT_USAGE_STATUS).find((candidate) => candidate === value);
  if (status === undefined) {
    throw new MalformedTenantUsageError('status');
  }
  return status;
};

/**
 * Boundary validator for the frozen acx/v1/usage contract [sr-005]: every key
 * required, no extra keys, each value read and type-checked into a fresh object.
 */
export const parseTenantUsage = (payload: unknown): TenantUsage => {
  if (!isRecord(payload)) {
    throw new MalformedTenantUsageError('response body');
  }
  rejectUnexpectedKeys(payload, TENANT_USAGE_KEYS, '');
  const period = payload.period;
  if (!isRecord(period)) {
    throw new MalformedTenantUsageError('period');
  }
  rejectUnexpectedKeys(period, PERIOD_KEYS, 'period.');

  return {
    tenant_id: readUuid(payload.tenant_id, 'tenant_id'),
    used: readCount(payload.used, 'used'),
    reserved: readCount(payload.reserved, 'reserved'),
    remaining: readCount(payload.remaining, 'remaining'),
    allowance: readCount(payload.allowance, 'allowance'),
    period_start: readDateTime(payload.period_start, 'period_start'),
    period_end: readDateTime(payload.period_end, 'period_end'),
    period: {
      start: readDateTime(period.start, 'period.start'),
      end: readDateTime(period.end, 'period.end'),
    },
    as_of: readNullableDateTime(payload.as_of, 'as_of'),
    status: readStatus(payload.status),
    data_source: readString(payload.data_source, 'data_source'),
  };
};

export const fetchTenantUsage = async (signal?: AbortSignal): Promise<TenantUsage> =>
  parseTenantUsage(
    await fetchRequiredApi<unknown>(getEndpoint(TENANT_USAGE_ENDPOINT_KEY), {
      method: 'GET',
      restNonce: getConfig().nonce,
      signal,
      timeoutMs: TENANT_USAGE_TIMEOUT_MS,
    }),
  );

/**
 * Usage & billing account area link, or '' when there is none to show. No
 * bootstrap (isolated surfaces) also means no link rather than a thrown render.
 */
export const readAccountUsageUrl = (): string => {
  try {
    const url: unknown = getConfig().accountUsageUrl;
    return typeof url === 'string' ? url : '';
  } catch {
    return '';
  }
};
