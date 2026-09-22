type PortalRequest = (path: string, init?: RequestInit) => Promise<Response>;

export type PortalCheckoutRequest = {
  plan_code: string;
  return_path?: string | null;
};

export type PortalCheckoutResponse = {
  attempt_id: string;
  checkout_url: string | null;
  status: string;
  replayed: boolean;
};

export type PortalManageRequest = { return_path?: string | null };

export type PortalManageResponse = { portal_url: string };

export type PortalBillingApiError = {
  status: number;
  code: string | null;
  detail: string | null;
  attemptId: string | null;
  retryAfterSeconds: number | null;
};

export type PortalBillingClient = {
  checkout(input: PortalCheckoutRequest, idempotencyKey: string): Promise<PortalCheckoutResponse>;
  manage(input?: PortalManageRequest): Promise<PortalManageResponse>;
};

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const IDEMPOTENCY_KEY_RE = /^[A-Za-z0-9._:-]{64,128}$/;
const CHECKOUT_PATH = '/portal/billing/checkout';
const MANAGE_PATH = '/portal/billing/manage';

function raiseBillingError(error: PortalBillingApiError): never {
  throw Object.assign(new Error(error.code ?? 'portal_billing_error'), error);
}

function retryAfterSeconds(response: Response): number | null {
  const raw = response.headers.get('Retry-After');
  if (raw == null || raw === '') {
    return null;
  }
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

function parseError(status: number, body: unknown, response: Response): PortalBillingApiError {
  let code: string | null = null;
  let attemptId: string | null = null;
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === 'string') {
      code = detail;
    } else if (detail && typeof detail === 'object') {
      const rec = detail as { code?: unknown; attempt_id?: unknown };
      if (typeof rec.code === 'string') {
        code = rec.code;
      }
      if (typeof rec.attempt_id === 'string' && UUID_RE.test(rec.attempt_id)) {
        attemptId = rec.attempt_id;
      }
    }
  }
  return {
    status,
    code,
    detail: null,
    attemptId,
    retryAfterSeconds: retryAfterSeconds(response),
  };
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

export function isSafeHttpsUrl(value: string): boolean {
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:') {
      return false;
    }
    if (!url.hostname) {
      return false;
    }
    if (url.username || url.password) {
      return false;
    }
    return true;
  } catch {
    return false;
  }
}

function parseCheckoutResponse(body: unknown): PortalCheckoutResponse | null {
  if (!body || typeof body !== 'object') {
    return null;
  }
  const rec = body as Record<string, unknown>;
  if (typeof rec.attempt_id !== 'string' || !UUID_RE.test(rec.attempt_id)) {
    return null;
  }
  if (typeof rec.status !== 'string' || rec.status.length === 0) {
    return null;
  }
  if (typeof rec.replayed !== 'boolean') {
    return null;
  }
  if (rec.checkout_url !== null && typeof rec.checkout_url !== 'string') {
    return null;
  }
  if (typeof rec.checkout_url === 'string' && !isSafeHttpsUrl(rec.checkout_url)) {
    return null;
  }
  return {
    attempt_id: rec.attempt_id,
    checkout_url: rec.checkout_url,
    status: rec.status,
    replayed: rec.replayed,
  };
}

function parseManageResponse(body: unknown): PortalManageResponse | null {
  if (!body || typeof body !== 'object') {
    return null;
  }
  const rec = body as Record<string, unknown>;
  if (typeof rec.portal_url !== 'string' || !isSafeHttpsUrl(rec.portal_url)) {
    return null;
  }
  return { portal_url: rec.portal_url };
}

function unavailable(code: string): PortalBillingApiError {
  return {
    status: 503,
    code,
    detail: null,
    attemptId: null,
    retryAfterSeconds: null,
  };
}

export function createPortalBillingClient(request: PortalRequest): PortalBillingClient {
  return {
    async checkout(input: PortalCheckoutRequest, idempotencyKey: string): Promise<PortalCheckoutResponse> {
      if (!IDEMPOTENCY_KEY_RE.test(idempotencyKey)) {
        raiseBillingError({
          status: 422,
          code: 'invalid_idempotency_key',
          detail: null,
          attemptId: null,
          retryAfterSeconds: null,
        });
      }
      const bodyPayload: PortalCheckoutRequest = { plan_code: input.plan_code };
      if (input.return_path != null) {
        bodyPayload.return_path = input.return_path;
      }
      let response: Response;
      try {
        response = await request(CHECKOUT_PATH, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Idempotency-Key': idempotencyKey,
          },
          body: JSON.stringify(bodyPayload),
        });
      } catch {
        raiseBillingError(unavailable('checkout_unavailable'));
      }
      const body = await readJson(response);
      if (response.status === 200) {
        const parsed = parseCheckoutResponse(body);
        if (parsed) {
          return parsed;
        }
        raiseBillingError({
          status: response.status,
          code: 'malformed_response',
          detail: null,
          attemptId: null,
          retryAfterSeconds: retryAfterSeconds(response),
        });
      }
      raiseBillingError(parseError(response.status, body, response));
    },

    async manage(input?: PortalManageRequest): Promise<PortalManageResponse> {
      const payload: PortalManageRequest = {};
      if (input?.return_path != null) {
        payload.return_path = input.return_path;
      }
      let response: Response;
      try {
        response = await request(MANAGE_PATH, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      } catch {
        raiseBillingError(unavailable('billing_portal_unavailable'));
      }
      const body = await readJson(response);
      if (response.status === 200) {
        const parsed = parseManageResponse(body);
        if (parsed) {
          return parsed;
        }
        raiseBillingError({
          status: response.status,
          code: 'malformed_response',
          detail: null,
          attemptId: null,
          retryAfterSeconds: retryAfterSeconds(response),
        });
      }
      raiseBillingError(parseError(response.status, body, response));
    },
  };
}
