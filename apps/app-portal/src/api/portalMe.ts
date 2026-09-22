export const PortalMeOutcome = {
  Ok: 'ok',
  Empty: 'empty',
  Unauthorized: 'unauthorized',
  EmailUnverified: 'email_unverified',
  NotAdmitted: 'not_admitted',
  Outage: 'outage',
  Aborted: 'aborted',
} as const;

export type PortalMeOutcome = (typeof PortalMeOutcome)[keyof typeof PortalMeOutcome];

export type PortalMeResult =
  | { outcome: typeof PortalMeOutcome.Ok; tenantId: string }
  | { outcome: Exclude<PortalMeOutcome, typeof PortalMeOutcome.Ok> };

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export const PORTAL_ME_PATH = '/portal/me';
export const PORTAL_ME_TIMEOUT_MS = 8_000;

type FetchPortalMeOptions = {
  getToken: () => Promise<string | null>;
  fetchImpl?: typeof fetch;
  signal?: AbortSignal;
  timeoutMs?: number;
};

function readDetailCode(body: unknown): string | null {
  if (!body || typeof body !== 'object') {
    return null;
  }
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === 'string') {
    return detail;
  }
  if (detail && typeof detail === 'object' && 'code' in detail) {
    const code = (detail as { code?: unknown }).code;
    return typeof code === 'string' ? code : null;
  }
  return null;
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function interpretSuccess(body: unknown): PortalMeResult {
  if (!body || typeof body !== 'object') {
    return { outcome: PortalMeOutcome.Outage };
  }
  const tenantId = (body as { tenant_id?: unknown }).tenant_id;
  if (typeof tenantId === 'string' && UUID_RE.test(tenantId)) {
    return { outcome: PortalMeOutcome.Ok, tenantId };
  }
  return { outcome: PortalMeOutcome.Outage };
}

function interpretError(status: number, body: unknown): PortalMeResult {
  if (status === 401) {
    return { outcome: PortalMeOutcome.Unauthorized };
  }
  if (status === 503) {
    return { outcome: PortalMeOutcome.Outage };
  }
  if (status === 403) {
    const code = readDetailCode(body);
    if (code === 'email_unverified') {
      return { outcome: PortalMeOutcome.EmailUnverified };
    }
    return { outcome: PortalMeOutcome.NotAdmitted };
  }
  return { outcome: PortalMeOutcome.Outage };
}

export async function fetchPortalMe({
  getToken,
  fetchImpl = fetch,
  signal,
  timeoutMs = PORTAL_ME_TIMEOUT_MS,
}: FetchPortalMeOptions): Promise<PortalMeResult> {
  if (signal?.aborted) {
    return { outcome: PortalMeOutcome.Aborted };
  }

  const controller = new AbortController();
  let timedOut = false;
  const timer = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const onAbort = () => controller.abort();
  if (signal) {
    if (signal.aborted) {
      controller.abort();
    } else {
      signal.addEventListener('abort', onAbort, { once: true });
    }
  }

  let settled = false;
  const aborted = new Promise<never>((_, reject) => {
    const fail = () => {
      if (!settled) {
        reject(new DOMException('The operation was aborted.', 'AbortError'));
      }
    };
    if (controller.signal.aborted) {
      fail();
      return;
    }
    controller.signal.addEventListener('abort', fail, { once: true });
  });

  const finish = (result: PortalMeResult): PortalMeResult => {
    settled = true;
    return result;
  };

  try {
    const token = await Promise.race([Promise.resolve().then(() => getToken()), aborted]);
    if (controller.signal.aborted) {
      return finish(
        signal?.aborted && !timedOut ? { outcome: PortalMeOutcome.Aborted } : { outcome: PortalMeOutcome.Outage },
      );
    }
    if (!token) {
      return finish({ outcome: PortalMeOutcome.Unauthorized });
    }

    const response = await Promise.race([
      fetchImpl(PORTAL_ME_PATH, {
        method: 'GET',
        cache: 'no-store',
        credentials: 'omit',
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal,
      }),
      aborted,
    ]);
    const body = await readJson(response);
    if (response.ok) {
      return finish(interpretSuccess(body));
    }
    return finish(interpretError(response.status, body));
  } catch {
    settled = true;
    if (signal?.aborted && !timedOut) {
      return { outcome: PortalMeOutcome.Aborted };
    }
    return { outcome: PortalMeOutcome.Outage };
  } finally {
    window.clearTimeout(timer);
    signal?.removeEventListener('abort', onAbort);
  }
}
