import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { normalizeConfig, registerConfig, resetConfigCache, type ApiConfig } from '../config';
import {
  fetchTenantUsage,
  MalformedTenantUsageError,
  parseTenantUsage,
  readAccountUsageUrl,
  TENANT_USAGE_STATUS,
} from '../usageApi';
import { HTTPError } from '../../utils/http';
import { setLogSink, type LogRecord } from '../../utils/logger';

/** The frozen acx/v1/usage contract body, verbatim from the UXREC-1 brief. */
const goldenBody = (): Record<string, unknown> => ({
  tenant_id: '00000000-0000-4000-8000-000000000001',
  used: 120,
  reserved: 8,
  remaining: 372,
  allowance: 500,
  period_start: '2026-10-01T00:00:00Z',
  period_end: '2026-11-01T00:00:00Z',
  period: { start: '2026-10-01T00:00:00Z', end: '2026-11-01T00:00:00Z' },
  as_of: '2026-10-26T09:30:00Z',
  status: 'paid_active',
  data_source: 'authoritative',
});

const CONTRACT_KEYS = Object.keys(goldenBody());

const withPeriod = (period: unknown): Record<string, unknown> => ({ ...goldenBody(), period });

const without = (key: string): Record<string, unknown> =>
  Object.fromEntries(Object.entries(goldenBody()).filter(([candidate]) => candidate !== key));

const expectMalformed = (payload: unknown, field: string): void => {
  expect(() => parseTenantUsage(payload)).toThrow(MalformedTenantUsageError);
  expect(() => parseTenantUsage(payload)).toThrow(`malformed: ${field}`);
};

describe('parseTenantUsage', () => {
  it('accepts the golden body and returns every contract field unchanged', () => {
    expect(parseTenantUsage(goldenBody())).toEqual(goldenBody());
  });

  it('returns a fresh object rather than the unvalidated payload', () => {
    const payload = goldenBody();

    expect(parseTenantUsage(payload)).not.toBe(payload);
  });

  it('keeps null counts, as_of and status as null instead of inventing values', () => {
    const parsed = parseTenantUsage({
      ...goldenBody(),
      used: null,
      reserved: null,
      remaining: null,
      allowance: null,
      as_of: null,
      status: null,
    });

    expect(parsed).toMatchObject({
      used: null,
      reserved: null,
      remaining: null,
      allowance: null,
      as_of: null,
      status: null,
    });
  });

  it.each(Object.values(TENANT_USAGE_STATUS))('accepts status %s', (status) => {
    expect(parseTenantUsage({ ...goldenBody(), status }).status).toBe(status);
  });

  it.each(CONTRACT_KEYS)('rejects a body missing %s', (key) => {
    expectMalformed(without(key), key);
  });

  it('rejects an extra top-level key', () => {
    expectMalformed({ ...goldenBody(), balance: 372 }, 'balance');
  });

  it.each(['start', 'end'])('rejects a period missing %s', (key) => {
    const period = key === 'start' ? { end: '2026-11-01T00:00:00Z' } : { start: '2026-10-01T00:00:00Z' };
    expectMalformed(withPeriod(period), `period.${key}`);
  });

  it('rejects an extra period key', () => {
    expectMalformed(
      withPeriod({ start: '2026-10-01T00:00:00Z', end: '2026-11-01T00:00:00Z', timezone: 'UTC' }),
      'period.timezone',
    );
  });

  it.each([
    ['tenant_id', 42],
    ['used', '120'],
    ['reserved', true],
    ['remaining', '372'],
    ['allowance', {}],
    ['remaining', Number.NaN],
    ['remaining', -1],
    ['allowance', -500],
    ['remaining', 1.6],
    ['used', Number.POSITIVE_INFINITY],
    ['tenant_id', 'not-a-uuid'],
    ['period_start', 'October 1'],
    ['period_start', 'not-a-date'],
    ['period_end', 1_793_491_200],
    ['period_end', '2026-11-01'],
    ['as_of', 0],
    ['as_of', 'not-a-date'],
    ['as_of', '2026-02-30T00:00:00Z'],
    ['as_of', '2026-10-26T24:00:00Z'],
    ['as_of', '2026-10-26T09:30:00'],
    ['status', 'active'],
    ['status', 'PAID_ACTIVE'],
    ['data_source', null],
  ])('rejects a mistyped %s (%o)', (key, value) => {
    expectMalformed({ ...goldenBody(), [key]: value }, key);
  });

  it('accepts zero counts and offset date-times with fractional seconds', () => {
    const body = {
      ...goldenBody(),
      remaining: 0,
      reserved: 0,
      as_of: '2026-10-26T09:30:00.123456Z',
      period_end: '2026-11-01T02:00:00+02:00',
    };

    expect(parseTenantUsage(body)).toEqual(body);
  });

  it.each([null, [], 'not-an-object'])('rejects a non-object period (%o)', (period) => {
    expectMalformed(withPeriod(period), 'period');
  });

  it.each([
    ['start', '2026/10/01'],
    ['end', null],
  ])('rejects a mistyped period.%s', (key, value) => {
    expectMalformed(
      withPeriod({ start: '2026-10-01T00:00:00Z', end: '2026-11-01T00:00:00Z', [key]: value }),
      `period.${key}`,
    );
  });

  it.each([null, undefined, [], 'body', 372])('rejects a non-object body (%o)', (payload) => {
    expectMalformed(payload, 'response body');
  });
});

describe('fetchTenantUsage', () => {
  const ENDPOINT = 'https://example.test/wp-json/acx/v1/usage';
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    resetConfigCache();
    registerConfig({ nonce: 'abcdef1234', ajaxUrl: '/wp-admin/admin-ajax.php', endpoints: { usage: ENDPOINT } });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
    resetConfigCache();
  });

  it('GETs the published usage endpoint with the REST nonce and returns the parsed body', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify(goldenBody()), { status: 200 }));

    await expect(fetchTenantUsage()).resolves.toEqual(goldenBody());

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe(ENDPOINT);
    expect(init?.method).toBe('GET');
    expect(new Headers(init?.headers).get('X-WP-Nonce')).toBe('abcdef1234');
  });

  it('rejects a body that breaks the contract', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ ...goldenBody(), extra: 1 }), { status: 200 }));

    await expect(fetchTenantUsage()).rejects.toBeInstanceOf(MalformedTenantUsageError);
  });

  it('rejects a negative remaining before anything can render it', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ ...goldenBody(), remaining: -1 }), { status: 200 }));

    await expect(fetchTenantUsage()).rejects.toBeInstanceOf(MalformedTenantUsageError);
  });

  it.each([502, 503])('rejects a %i from the service as an HTTP error', async (status) => {
    fetchMock.mockResolvedValue(new Response('{"code":"usage_unavailable"}', { status }));

    await expect(fetchTenantUsage()).rejects.toBeInstanceOf(HTTPError);
  });
});

describe('accountUsageUrl config', () => {
  const BASE: ApiConfig = { nonce: 'abcdef1234', ajaxUrl: '/wp-admin/admin-ajax.php', endpoints: {} };
  let records: LogRecord[] = [];

  beforeEach(() => {
    records = [];
    resetConfigCache();
    setLogSink((record) => {
      records.push(record);
    });
  });

  afterEach(() => {
    setLogSink(null);
    resetConfigCache();
  });

  it('keeps an absolute https URL', () => {
    const url = 'https://app.altcontext.test/account/usage';

    expect(normalizeConfig({ ...BASE, accountUsageUrl: url }).accountUsageUrl).toBe(url);
    expect(records).toEqual([]);
  });

  it.each([undefined, '', '   '])('treats %o as no link, without a warning', (accountUsageUrl) => {
    expect(normalizeConfig({ ...BASE, accountUsageUrl }).accountUsageUrl).toBe('');
    expect(records).toEqual([]);
  });

  it.each(['javascript:alert(1)', 'account/usage'])(
    'drops a non-http(s) value (%s) with a warning',
    (accountUsageUrl) => {
      expect(normalizeConfig({ ...BASE, accountUsageUrl }).accountUsageUrl).toBe('');
      expect(records).toHaveLength(1);
      expect(records[0]?.level).toBe('warn');
      expect(records[0]?.fields.field).toBe('accountUsageUrl');
    },
  );

  it('reads no link when there is no bootstrap at all', () => {
    expect(readAccountUsageUrl()).toBe('');
  });
});
