export type PortalRequest = (path: string, init?: RequestInit) => Promise<Response>;

export type PortalRequestOwner = {
  userId: string;
  sessionId: string;
};

export type CreatePortalRequestOptions = {
  getToken: () => Promise<string | null>;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
  signal?: AbortSignal;
  owner: PortalRequestOwner;
  currentOwner: () => PortalRequestOwner | null;
};

const DEFAULT_TIMEOUT_MS = 8_000;
const PORTAL_PATH_RE = /^\/portal\/[A-Za-z0-9/_-]+$/;

function abortError(): DOMException {
  return new DOMException('The operation was aborted.', 'AbortError');
}

function ownersMatch(
  left: PortalRequestOwner | null | undefined,
  right: PortalRequestOwner | null | undefined,
): boolean {
  return Boolean(left && right && left.userId === right.userId && left.sessionId === right.sessionId);
}

export function resolvePortalPath(path: string): string | null {
  if (typeof path !== 'string' || path.length === 0) {
    return null;
  }
  if (!path.startsWith('/portal/')) {
    return null;
  }
  if (path.startsWith('//') || path.includes('://') || path.includes('\\')) {
    return null;
  }
  if (path.includes('..') || /%2e/i.test(path)) {
    return null;
  }
  let url: URL;
  try {
    url = new URL(path, 'https://app.altcontext.com');
  } catch {
    return null;
  }
  if (url.origin !== 'https://app.altcontext.com') {
    return null;
  }
  if (url.username || url.password) {
    return null;
  }
  if (url.protocol !== 'https:') {
    return null;
  }
  if (!PORTAL_PATH_RE.test(url.pathname)) {
    return null;
  }
  return `${url.pathname}${url.search}`;
}

function assertCurrentOwner(owner: PortalRequestOwner, currentOwner: () => PortalRequestOwner | null): void {
  if (!ownersMatch(owner, currentOwner())) {
    throw abortError();
  }
}

export function createPortalRequest(options: CreatePortalRequestOptions): PortalRequest {
  const fetchImpl = options.fetchImpl ?? fetch;
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;

  return async (path, init) => {
    const resolved = resolvePortalPath(path);
    if (!resolved) {
      throw new TypeError('portal request path is not allowed');
    }
    assertCurrentOwner(options.owner, options.currentOwner);
    if (options.signal?.aborted || init?.signal?.aborted) {
      throw abortError();
    }

    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    const onAbort = () => controller.abort();
    if (options.signal) {
      if (options.signal.aborted) {
        controller.abort();
      } else {
        options.signal.addEventListener('abort', onAbort, { once: true });
      }
    }
    if (init?.signal) {
      if (init.signal.aborted) {
        controller.abort();
      } else {
        init.signal.addEventListener('abort', onAbort, { once: true });
      }
    }

    const abortGate = new Promise<void>((resolve) => {
      if (controller.signal.aborted) {
        resolve();
        return;
      }
      controller.signal.addEventListener('abort', () => resolve(), { once: true });
    });

    try {
      assertCurrentOwner(options.owner, options.currentOwner);
      const tokenResult = await Promise.race([
        Promise.resolve()
          .then(() => options.getToken())
          .then((token) => ({ token })),
        abortGate.then(() => ({ aborted: true as const })),
      ]);
      if ('aborted' in tokenResult || controller.signal.aborted) {
        throw abortError();
      }
      assertCurrentOwner(options.owner, options.currentOwner);
      if (!tokenResult.token) {
        throw new Error('portal identity unavailable');
      }

      const headers = new Headers(init?.headers);
      headers.delete('Origin');
      headers.delete('Authorization');
      headers.set('Authorization', `Bearer ${tokenResult.token}`);

      const fetchResult = await Promise.race([
        fetchImpl(resolved, {
          ...init,
          headers,
          cache: 'no-store',
          credentials: 'omit',
          redirect: 'error',
          signal: controller.signal,
        }).then((response) => ({ response })),
        abortGate.then(() => ({ aborted: true as const })),
      ]);
      if ('aborted' in fetchResult || controller.signal.aborted) {
        throw abortError();
      }
      assertCurrentOwner(options.owner, options.currentOwner);
      if (options.signal?.aborted || init?.signal?.aborted) {
        throw abortError();
      }
      return fetchResult.response;
    } finally {
      window.clearTimeout(timer);
      options.signal?.removeEventListener('abort', onAbort);
      init?.signal?.removeEventListener('abort', onAbort);
    }
  };
}
