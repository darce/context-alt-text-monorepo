import { describe, expect, it } from 'vitest';
import { createPortalKeyClient, type PortalKeyMetadataResponse, type PortalKeyPageResponse } from '../api/portalKeys';
import { createPortalUsageClient, type PortalUsageResponse } from '../api/portalUsage';

const TENANT_A = '11111111-1111-4111-8111-111111111111';
const KEY_A = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const KEY_B = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function metadata(overrides: Partial<PortalKeyMetadataResponse> = {}): PortalKeyMetadataResponse {
  return {
    id: KEY_A,
    tenant_id: TENANT_A,
    created_at: '2026-09-01T00:00:00Z',
    expires_at: '2026-12-01T00:00:00Z',
    revoked_at: null,
    rate_limit_tier: 'standard',
    lifetime_seconds: 3600,
    ...overrides,
  };
}

function page(
  rows: PortalKeyMetadataResponse[],
  overrides: Partial<PortalKeyPageResponse> = {},
): PortalKeyPageResponse {
  return {
    data: rows,
    next_cursor: null,
    cursor: null,
    limit: 25,
    total: rows.length,
    ...overrides,
  };
}

function usage(overrides: Partial<PortalUsageResponse> = {}): PortalUsageResponse {
  return {
    tenant_id: TENANT_A,
    used: 3,
    reserved: 1,
    remaining: 6,
    allowance: 10,
    period_start: '2026-09-01T00:00:00Z',
    period_end: '2026-10-01T00:00:00Z',
    period: { start: '2026-09-01T00:00:00Z', end: '2026-10-01T00:00:00Z' },
    as_of: '2026-09-22T12:00:00Z',
    status: 'beta_active',
    data_source: 'authoritative',
    ...overrides,
  };
}

describe('APP-1 keys API fix wave [DATA-03][HAI-01][GRPH-09]', () => {
  describe('RV03 revoke acknowledgement', () => {
    it('rejects a 200 revoke envelope with revoked:false', async () => {
      const client = createPortalKeyClient(async () =>
        jsonResponse(200, { id: KEY_A, tenant_id: TENANT_A, revoked: false }),
      );
      await expect(client.revoke(KEY_A, {})).rejects.toMatchObject({
        code: 'invalid_portal_key_response',
      });
    });

    it('rejects a 200 revoke envelope whose id does not match the requested key', async () => {
      const client = createPortalKeyClient(async () =>
        jsonResponse(200, { id: KEY_B, tenant_id: TENANT_A, revoked: true }),
      );
      await expect(client.revoke(KEY_A, {})).rejects.toMatchObject({
        code: 'invalid_portal_key_response',
      });
    });

    it('accepts a 200 revoke envelope with revoked:true and the requested id', async () => {
      const client = createPortalKeyClient(async () =>
        jsonResponse(200, { id: KEY_A, tenant_id: TENANT_A, revoked: true }),
      );
      await expect(client.revoke(KEY_A, {})).resolves.toEqual({
        id: KEY_A,
        tenant_id: TENANT_A,
        revoked: true,
      });
    });
  });

  describe('RV05 key datetime fields', () => {
    it('rejects list rows whose created_at is not a finite producer ISO datetime', async () => {
      const client = createPortalKeyClient(async () =>
        jsonResponse(200, page([metadata({ created_at: 'not-a-timestamp' })])),
      );
      await expect(client.list()).rejects.toMatchObject({ code: 'invalid_portal_key_response' });
    });

    it('rejects list rows whose expires_at is an arbitrary non-empty string', async () => {
      const client = createPortalKeyClient(async () => jsonResponse(200, page([metadata({ expires_at: 'soon' })])));
      await expect(client.list()).rejects.toMatchObject({ code: 'invalid_portal_key_response' });

      const rolledOverExpiry = createPortalKeyClient(async () =>
        jsonResponse(200, page([metadata({ expires_at: '2027-02-30T00:00:00Z' })])),
      );
      await expect(rolledOverExpiry.list()).rejects.toMatchObject({ code: 'invalid_portal_key_response' });
    });

    it('rejects list rows whose revoked_at is not a finite producer ISO datetime', async () => {
      const client = createPortalKeyClient(async () =>
        jsonResponse(200, page([metadata({ revoked_at: 'yesterday' })])),
      );
      await expect(client.list()).rejects.toMatchObject({ code: 'invalid_portal_key_response' });
    });

    it('accepts producer UTC ISO timestamps and preserves null expiry as unknown', async () => {
      const client = createPortalKeyClient(async () =>
        jsonResponse(
          200,
          page([
            metadata({
              created_at: '2026-09-20T12:00:00Z',
              expires_at: null,
              revoked_at: null,
            }),
          ]),
        ),
      );
      const result = await client.list();
      expect(result.data[0]?.created_at).toBe('2026-09-20T12:00:00Z');
      expect(result.data[0]?.expires_at).toBeNull();
      expect(result.data[0]?.revoked_at).toBeNull();
    });
  });

  describe('RV06 usage counts and datetimes', () => {
    it('rejects negative count integers in a 200 usage envelope', async () => {
      const negativeUsed = createPortalUsageClient(async () => jsonResponse(200, usage({ used: -1 })));
      await expect(negativeUsed.read()).rejects.toMatchObject({ code: 'invalid_portal_usage_response' });

      const negativeReserved = createPortalUsageClient(async () => jsonResponse(200, usage({ reserved: -2 })));
      await expect(negativeReserved.read()).rejects.toMatchObject({ code: 'invalid_portal_usage_response' });

      const negativeRemaining = createPortalUsageClient(async () => jsonResponse(200, usage({ remaining: -3 })));
      await expect(negativeRemaining.read()).rejects.toMatchObject({ code: 'invalid_portal_usage_response' });

      const negativeAllowance = createPortalUsageClient(async () => jsonResponse(200, usage({ allowance: -4 })));
      await expect(negativeAllowance.read()).rejects.toMatchObject({ code: 'invalid_portal_usage_response' });
    });

    it('rejects count integers outside JavaScript safe integer precision', async () => {
      const unsafeCount = Number.MAX_SAFE_INTEGER + 1;
      for (const override of [
        { used: unsafeCount },
        { reserved: unsafeCount },
        { remaining: unsafeCount },
        { allowance: unsafeCount },
      ]) {
        const client = createPortalUsageClient(async () => jsonResponse(200, usage(override)));
        await expect(client.read()).rejects.toMatchObject({ code: 'invalid_portal_usage_response' });
      }
    });

    it('preserves null counts as unknown and does not coerce them to zero', async () => {
      const client = createPortalUsageClient(async () =>
        jsonResponse(200, usage({ used: null, reserved: null, remaining: null, allowance: null })),
      );
      const result = await client.read();
      expect(result.used).toBeNull();
      expect(result.reserved).toBeNull();
      expect(result.remaining).toBeNull();
      expect(result.allowance).toBeNull();
    });

    it('rejects invalid period and as_of timestamps at top level and nested period', async () => {
      const badPeriodStart = createPortalUsageClient(async () =>
        jsonResponse(200, usage({ period_start: 'not-a-period' })),
      );
      await expect(badPeriodStart.read()).rejects.toMatchObject({ code: 'invalid_portal_usage_response' });

      const badNestedEnd = createPortalUsageClient(async () =>
        jsonResponse(200, usage({ period: { start: '2026-09-01T00:00:00Z', end: 'later' } })),
      );
      await expect(badNestedEnd.read()).rejects.toMatchObject({ code: 'invalid_portal_usage_response' });

      const badAsOf = createPortalUsageClient(async () => jsonResponse(200, usage({ as_of: 'observed-whenever' })));
      await expect(badAsOf.read()).rejects.toMatchObject({ code: 'invalid_portal_usage_response' });

      const rolledOverPeriodStart = createPortalUsageClient(async () =>
        jsonResponse(200, usage({ period_start: '2026-02-30T00:00:00Z' })),
      );
      await expect(rolledOverPeriodStart.read()).rejects.toMatchObject({ code: 'invalid_portal_usage_response' });

      const rolledOverNestedEnd = createPortalUsageClient(async () =>
        jsonResponse(
          200,
          usage({ period: { start: '2026-09-01T00:00:00Z', end: '2026-02-30T00:00:00Z' } }),
        ),
      );
      await expect(rolledOverNestedEnd.read()).rejects.toMatchObject({ code: 'invalid_portal_usage_response' });

      const rolledOverAsOf = createPortalUsageClient(async () =>
        jsonResponse(200, usage({ as_of: '2026-02-30T00:00:00Z' })),
      );
      await expect(rolledOverAsOf.read()).rejects.toMatchObject({ code: 'invalid_portal_usage_response' });
    });

    it('accepts producer UTC ISO period/as_of fields and null as_of as unknown', async () => {
      const client = createPortalUsageClient(async () =>
        jsonResponse(
          200,
          usage({
            period_start: '2026-09-20T12:00:00Z',
            period_end: '2026-10-20T12:00:00Z',
            period: { start: '2026-09-20T12:00:00Z', end: '2026-10-20T12:00:00Z' },
            as_of: null,
            used: 0,
            reserved: 0,
            remaining: 0,
            allowance: 0,
          }),
        ),
      );
      const result = await client.read();
      expect(result.period_start).toBe('2026-09-20T12:00:00Z');
      expect(result.period.end).toBe('2026-10-20T12:00:00Z');
      expect(result.as_of).toBeNull();
      expect(result.used).toBe(0);
    });
  });
});
