type PortalRequest = (path: string, init?: RequestInit) => Promise<Response>;

export type PortalUsagePeriodResponse = { start: string; end: string };
export type PortalUsageResponse = {
  tenant_id: string;
  used: number | null;
  reserved: number | null;
  remaining: number | null;
  allowance: number | null;
  period_start: string;
  period_end: string;
  period: PortalUsagePeriodResponse;
  as_of: string | null;
  status: 'beta_active' | 'paid_active' | 'past_due' | 'expired' | 'revoked' | null;
  data_source: string;
};
export type PortalUsageApiError = {
  status: number;
  code: string | null;
  detail: string | null;
  attemptId: string | null;
  retryAfterSeconds: number | null;
};
export type PortalUsageClient = { read(): Promise<PortalUsageResponse> };

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const ISO_DATE_TIME_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const USAGE_STATUSES = new Set(['beta_active', 'paid_active', 'past_due', 'expired', 'revoked']);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function parseUuid(value: unknown): string | null {
  return typeof value === 'string' && UUID_RE.test(value) ? value : null;
}

function parseRequiredString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
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

function parseNullableInt(value: unknown): number | null | undefined {
  if (value === null) {
    return null;
  }
  if (typeof value === 'boolean' || typeof value !== 'number' || !Number.isInteger(value) || value < 0) {
    return undefined;
  }
  return value;
}

function parseRetryAfter(value: string | null): number | null {
  if (!value) {
    return null;
  }
  const seconds = Number(value);
  return Number.isInteger(seconds) && seconds >= 0 ? seconds : null;
}

function makeError(fields: PortalUsageApiError): Error & PortalUsageApiError {
  const error = new Error('portal_usage_request_failed') as Error & PortalUsageApiError;
  error.status = fields.status;
  error.code = fields.code;
  error.detail = fields.detail;
  error.attemptId = fields.attemptId;
  error.retryAfterSeconds = fields.retryAfterSeconds;
  return error;
}

function parseErrorBody(body: unknown): Pick<PortalUsageApiError, 'code' | 'detail' | 'attemptId'> {
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
  return { code: typeof body.code === 'string' ? body.code : null, detail: null, attemptId: attemptFromBody };
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function parseStatus(value: unknown): PortalUsageResponse['status'] | undefined {
  if (value === null) {
    return null;
  }
  if (typeof value === 'string' && USAGE_STATUSES.has(value)) {
    return value as PortalUsageResponse['status'];
  }
  return undefined;
}

function parsePeriod(value: unknown): PortalUsagePeriodResponse | null {
  if (!isRecord(value)) {
    return null;
  }
  const start = parseIsoDateTime(value.start);
  const end = parseIsoDateTime(value.end);
  if (!start || !end) {
    return null;
  }
  return { start, end };
}

function parseUsage(value: unknown): PortalUsageResponse | null {
  if (!isRecord(value)) {
    return null;
  }
  const tenantId = parseUuid(value.tenant_id);
  const used = parseNullableInt(value.used);
  const reserved = parseNullableInt(value.reserved);
  const remaining = parseNullableInt(value.remaining);
  const allowance = parseNullableInt(value.allowance);
  const periodStart = parseIsoDateTime(value.period_start);
  const periodEnd = parseIsoDateTime(value.period_end);
  const period = parsePeriod(value.period);
  const asOf = parseNullableIsoDateTime(value.as_of);
  const status = parseStatus(value.status);
  const dataSource = parseRequiredString(value.data_source);
  if (
    !tenantId ||
    used === undefined ||
    reserved === undefined ||
    remaining === undefined ||
    allowance === undefined ||
    !periodStart ||
    !periodEnd ||
    !period ||
    asOf === undefined ||
    status === undefined ||
    !dataSource
  ) {
    return null;
  }
  return {
    tenant_id: tenantId,
    used,
    reserved,
    remaining,
    allowance,
    period_start: periodStart,
    period_end: periodEnd,
    period,
    as_of: asOf,
    status,
    data_source: dataSource,
  };
}

export function createPortalUsageClient(request: PortalRequest): PortalUsageClient {
  return {
    async read() {
      const response = await request('/portal/usage', { method: 'GET' });
      const body = await readJson(response);
      if (!response.ok) {
        const parsed = parseErrorBody(body);
        throw makeError({
          status: response.status,
          code: parsed.code,
          detail: parsed.detail,
          attemptId: parsed.attemptId,
          retryAfterSeconds: parseRetryAfter(response.headers.get('Retry-After')),
        });
      }
      const parsed = parseUsage(body);
      if (!parsed) {
        throw makeError({
          status: response.status,
          code: 'invalid_portal_usage_response',
          detail: null,
          attemptId: null,
          retryAfterSeconds: null,
        });
      }
      return parsed;
    },
  };
}
