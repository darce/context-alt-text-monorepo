type PortalRequest = (path: string, init?: RequestInit) => Promise<Response>;

export type PortalKeyMetadataResponse = {
  id: string;
  tenant_id: string;
  created_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  rate_limit_tier: string | null;
  lifetime_seconds: number | null;
};
export type PortalKeyIssueResponse = PortalKeyMetadataResponse & {
  raw_key: string | null;
  replayed: boolean;
};
export type PortalKeyPageResponse = {
  data: PortalKeyMetadataResponse[];
  next_cursor: string | null;
  cursor: string | null;
  limit: number;
  total: number;
};
export type CreateKeyRequest = {
  lifetime_seconds?: number | null;
  rate_limit_tier?: string | null;
};
export type RotateKeyRequest = { reason?: string };
export type RevokeKeyRequest = {
  reason?: string;
  confirm_last_usable?: boolean;
  emergency?: boolean;
};
export type RevokeKeyResponse = {
  id: string;
  tenant_id: string;
  revoked: boolean;
};
export type PortalKeyApiError = {
  status: number;
  code: string | null;
  detail: string | null;
  attemptId: string | null;
  retryAfterSeconds: number | null;
};
export type PortalKeyClient = {
  list(input?: { cursor?: string; limit?: number }): Promise<PortalKeyPageResponse>;
  create(input: CreateKeyRequest, idempotencyKey: string): Promise<PortalKeyIssueResponse>;
  rotate(id: string, input: RotateKeyRequest, idempotencyKey: string): Promise<PortalKeyIssueResponse>;
  revoke(id: string, input: RevokeKeyRequest): Promise<RevokeKeyResponse>;
};

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const ISO_DATE_TIME_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const DEFAULT_LIST_LIMIT = 25;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function parseUuid(value: unknown): string | null {
  return typeof value === 'string' && UUID_RE.test(value) ? value : null;
}

function parseIsoDateTime(value: unknown): string | null {
  if (typeof value !== 'string' || !ISO_DATE_TIME_RE.test(value)) {
    return null;
  }
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? value : null;
}

function parseNullableIsoDateTime(value: unknown): string | null | undefined {
  if (value === null) {
    return null;
  }
  const parsed = parseIsoDateTime(value);
  return parsed === null ? undefined : parsed;
}

function parseNullableString(value: unknown): string | null | undefined {
  if (value === null) {
    return null;
  }
  if (typeof value === 'string') {
    return value;
  }
  return undefined;
}

function parseNullableInt(value: unknown): number | null | undefined {
  if (value === null) {
    return null;
  }
  if (typeof value === 'boolean' || typeof value !== 'number' || !Number.isInteger(value) || value < 0) {
    return undefined;
  }
  return value;
}

function parseRequiredInt(value: unknown): number | null {
  if (typeof value === 'boolean' || typeof value !== 'number' || !Number.isInteger(value)) {
    return null;
  }
  return value;
}

function parseBoolean(value: unknown): boolean | null {
  return typeof value === 'boolean' ? value : null;
}

function parseRetryAfter(value: string | null): number | null {
  if (!value) {
    return null;
  }
  const seconds = Number(value);
  return Number.isInteger(seconds) && seconds >= 0 ? seconds : null;
}

function makeError(fields: PortalKeyApiError): Error & PortalKeyApiError {
  const error = new Error('portal_key_request_failed') as Error & PortalKeyApiError;
  error.status = fields.status;
  error.code = fields.code;
  error.detail = fields.detail;
  error.attemptId = fields.attemptId;
  error.retryAfterSeconds = fields.retryAfterSeconds;
  return error;
}

function invalidResponseError(status: number): Error & PortalKeyApiError {
  return makeError({
    status,
    code: 'invalid_portal_key_response',
    detail: null,
    attemptId: null,
    retryAfterSeconds: null,
  });
}

function parseErrorBody(body: unknown): Pick<PortalKeyApiError, 'code' | 'detail' | 'attemptId'> {
  if (!isRecord(body)) {
    return { code: null, detail: null, attemptId: null };
  }
  const attemptFromBody = typeof body.attempt_id === 'string' ? body.attempt_id : null;
  const detail = body.detail;
  if (typeof detail === 'string') {
    return { code: detail, detail, attemptId: attemptFromBody };
  }
  if (isRecord(detail)) {
    return {
      code: typeof detail.code === 'string' ? detail.code : null,
      detail: typeof detail.detail === 'string' ? detail.detail : null,
      attemptId: typeof detail.attempt_id === 'string' ? detail.attempt_id : attemptFromBody,
    };
  }
  return {
    code: typeof body.code === 'string' ? body.code : null,
    detail: null,
    attemptId: attemptFromBody,
  };
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

async function throwHttpError(response: Response): Promise<never> {
  const body = await readJson(response);
  const parsed = parseErrorBody(body);
  throw makeError({
    status: response.status,
    code: parsed.code,
    detail: parsed.detail,
    attemptId: parsed.attemptId,
    retryAfterSeconds: parseRetryAfter(response.headers.get('Retry-After')),
  });
}

function parseMetadata(value: unknown): PortalKeyMetadataResponse | null {
  if (!isRecord(value)) {
    return null;
  }
  const id = parseUuid(value.id);
  const tenantId = parseUuid(value.tenant_id);
  const createdAt = parseIsoDateTime(value.created_at);
  const expiresAt = parseNullableIsoDateTime(value.expires_at);
  const revokedAt = parseNullableIsoDateTime(value.revoked_at);
  const rateLimitTier = parseNullableString(value.rate_limit_tier);
  const lifetimeSeconds = parseNullableInt(value.lifetime_seconds);
  if (
    !id ||
    !tenantId ||
    !createdAt ||
    expiresAt === undefined ||
    revokedAt === undefined ||
    rateLimitTier === undefined ||
    lifetimeSeconds === undefined
  ) {
    return null;
  }
  return {
    id,
    tenant_id: tenantId,
    created_at: createdAt,
    expires_at: expiresAt,
    revoked_at: revokedAt,
    rate_limit_tier: rateLimitTier,
    lifetime_seconds: lifetimeSeconds,
  };
}

function parseIssue(value: unknown): PortalKeyIssueResponse | null {
  const metadata = parseMetadata(value);
  if (!metadata || !isRecord(value)) {
    return null;
  }
  const rawKey = parseNullableString(value.raw_key);
  const replayed = parseBoolean(value.replayed);
  if (rawKey === undefined || replayed === null) {
    return null;
  }
  return { ...metadata, raw_key: rawKey, replayed };
}

function parsePage(value: unknown): PortalKeyPageResponse | null {
  if (!isRecord(value) || !Array.isArray(value.data)) {
    return null;
  }
  const data: PortalKeyMetadataResponse[] = [];
  for (const row of value.data) {
    const metadata = parseMetadata(row);
    if (!metadata) {
      return null;
    }
    data.push(metadata);
  }
  const nextCursor = parseNullableString(value.next_cursor);
  const cursor = parseNullableString(value.cursor);
  const limit = parseRequiredInt(value.limit);
  const total = parseRequiredInt(value.total);
  if (nextCursor === undefined || cursor === undefined || limit === null || limit <= 0 || total === null || total < 0) {
    return null;
  }
  return { data, next_cursor: nextCursor, cursor, limit, total };
}

function parseRevoke(value: unknown, requestedId: string): RevokeKeyResponse | null {
  if (!isRecord(value)) {
    return null;
  }
  const id = parseUuid(value.id);
  const tenantId = parseUuid(value.tenant_id);
  const revoked = parseBoolean(value.revoked);
  if (!id || !tenantId || revoked !== true || id !== requestedId) {
    return null;
  }
  return { id, tenant_id: tenantId, revoked };
}

function compactBody(input: object): string {
  return JSON.stringify(input, (_key, inner) => (inner === undefined ? undefined : inner));
}

function listPath(input?: { cursor?: string; limit?: number }): string {
  const params = new URLSearchParams();
  if (input?.cursor) {
    params.set('cursor', input.cursor);
  }
  params.set('limit', String(input?.limit ?? DEFAULT_LIST_LIMIT));
  return `/portal/keys?${params.toString()}`;
}

export function createPortalKeyClient(request: PortalRequest): PortalKeyClient {
  return {
    async list(input) {
      const response = await request(listPath(input), { method: 'GET' });
      if (!response.ok) {
        await throwHttpError(response);
      }
      const parsed = parsePage(await readJson(response));
      if (!parsed) {
        throw invalidResponseError(response.status);
      }
      return parsed;
    },
    async create(input, idempotencyKey) {
      const response = await request('/portal/keys', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': idempotencyKey,
        },
        body: compactBody(input),
      });
      if (!response.ok) {
        await throwHttpError(response);
      }
      const parsed = parseIssue(await readJson(response));
      if (!parsed) {
        throw invalidResponseError(response.status);
      }
      return parsed;
    },
    async rotate(id, input, idempotencyKey) {
      const response = await request(`/portal/keys/${id}/rotate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': idempotencyKey,
        },
        body: compactBody(input),
      });
      if (!response.ok) {
        await throwHttpError(response);
      }
      const parsed = parseIssue(await readJson(response));
      if (!parsed) {
        throw invalidResponseError(response.status);
      }
      return parsed;
    },
    async revoke(id, input) {
      const response = await request(`/portal/keys/${id}/revoke`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: compactBody(input),
      });
      if (!response.ok) {
        await throwHttpError(response);
      }
      const parsed = parseRevoke(await readJson(response), id);
      if (!parsed) {
        throw invalidResponseError(response.status);
      }
      return parsed;
    },
  };
}
