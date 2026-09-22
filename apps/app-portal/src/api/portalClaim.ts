type PortalRequest = (path: string, init?: RequestInit) => Promise<Response>;

export type PortalClaimResponse = {
  tenant_id: string;
  issuer: string;
  subject: string;
  email: string | null;
  replayed: boolean;
};

export type PortalClaimApiError = {
  status: number;
  code: string | null;
  detail: string | null;
  attemptId: string | null;
  retryAfterSeconds: number | null;
};

export type PortalClaimClient = {
  claim(invitationToken: string): Promise<PortalClaimResponse>;
};

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const CLAIM_PATH = '/portal/onboarding/claim';

function raiseClaimError(error: PortalClaimApiError): never {
  throw Object.assign(new Error(error.code ?? 'portal_claim_error'), error);
}

function retryAfterSeconds(response: Response): number | null {
  const raw = response.headers.get('Retry-After');
  if (raw == null || raw === '') {
    return null;
  }
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

function parseError(status: number, body: unknown, response: Response): PortalClaimApiError {
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

function parseClaimResponse(body: unknown): PortalClaimResponse | null {
  if (!body || typeof body !== 'object') {
    return null;
  }
  const rec = body as Record<string, unknown>;
  if (typeof rec.tenant_id !== 'string' || !UUID_RE.test(rec.tenant_id)) {
    return null;
  }
  if (typeof rec.issuer !== 'string' || rec.issuer.length === 0) {
    return null;
  }
  if (typeof rec.subject !== 'string' || rec.subject.length === 0) {
    return null;
  }
  if (!('email' in rec) || (rec.email !== null && typeof rec.email !== 'string')) {
    return null;
  }
  if (typeof rec.replayed !== 'boolean') {
    return null;
  }
  return {
    tenant_id: rec.tenant_id,
    issuer: rec.issuer,
    subject: rec.subject,
    email: rec.email,
    replayed: rec.replayed,
  };
}

export function createPortalClaimClient(request: PortalRequest): PortalClaimClient {
  return {
    async claim(invitationToken: string): Promise<PortalClaimResponse> {
      let response: Response;
      try {
        response = await request(CLAIM_PATH, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ invitation_token: invitationToken }),
        });
      } catch {
        raiseClaimError({
          status: 503,
          code: 'portal_identity_unavailable',
          detail: null,
          attemptId: null,
          retryAfterSeconds: null,
        });
      }
      const body = await readJson(response);
      if (response.status === 200 || response.status === 201) {
        const parsed = parseClaimResponse(body);
        if (parsed) {
          return parsed;
        }
        raiseClaimError({
          status: response.status,
          code: 'malformed_response',
          detail: null,
          attemptId: null,
          retryAfterSeconds: retryAfterSeconds(response),
        });
      }
      raiseClaimError(parseError(response.status, body, response));
    },
  };
}
