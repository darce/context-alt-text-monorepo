import { screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchPortalMe, PortalMeOutcome, PORTAL_ME_PATH } from '../api/portalMe';
import { clerkDouble } from './clerkDouble';
import { renderPortal } from './renderPortal';

vi.mock('@clerk/react', async () => {
  const doubles = await import('./clerkDouble');
  return {
    ClerkProvider: doubles.ClerkProviderStub,
    SignIn: doubles.SignInStub,
    SignUp: doubles.SignUpStub,
    UserButton: doubles.UserButtonStub,
    useAuth: doubles.useAuthStub,
    useUser: doubles.useUserStub,
  };
});

const TENANT = '11111111-1111-4111-8111-111111111111';
const KEY_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function meBody(tenantId = TENANT) {
  return {
    tenant_id: tenantId,
    issuer: 'https://clerk.altcontext.com',
    subject: 'user_1',
    email: 'ada@example.test',
  };
}

function responseWithUrl(status: number, body: unknown, url: string): Response {
  const response = jsonResponse(status, body);
  Object.defineProperty(response, 'url', { configurable: true, value: url });
  return response;
}

function keysPage() {
  return {
    data: [
      {
        id: KEY_ID,
        tenant_id: TENANT,
        created_at: '2026-09-01T00:00:00Z',
        expires_at: '2026-12-01T00:00:00Z',
        revoked_at: null,
        rate_limit_tier: 'standard',
        lifetime_seconds: 3600,
      },
    ],
    next_cursor: null,
    cursor: null,
    limit: 25,
    total: 1,
  };
}

function usageBody() {
  return {
    tenant_id: TENANT,
    used: 1,
    reserved: 0,
    remaining: 9,
    allowance: 10,
    period_start: '2026-09-01T00:00:00Z',
    period_end: '2026-10-01T00:00:00Z',
    period: { start: '2026-09-01T00:00:00Z', end: '2026-10-01T00:00:00Z' },
    as_of: '2026-09-22T12:00:00Z',
    status: 'beta_active',
    data_source: 'authoritative',
  };
}

function signInVerified(sessionId = 'sess_1') {
  clerkDouble.setState({
    isLoaded: true,
    isSignedIn: true,
    userId: 'user_1',
    sessionId,
    user: {
      fullName: 'Ada Lovelace',
      primaryEmailAddress: {
        emailAddress: 'ada@example.test',
        verification: { status: 'verified' },
      },
    },
    getToken: async () => 'session-jwt',
  });
}

function portalFetch(me: () => Response | Promise<Response> = () => jsonResponse(200, meBody())) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input).split('?')[0];
    if (path === '/portal/me') {
      return me();
    }
    if (path === '/portal/keys') {
      return jsonResponse(200, keysPage());
    }
    if (path === '/portal/usage') {
      return jsonResponse(200, usageBody());
    }
    return jsonResponse(404, { detail: 'missing fixture' });
  });
}

afterEach(() => {
  clerkDouble.reset();
  vi.useRealTimers();
});

describe('APP1-INTEGRATION-RV01 /portal/me redirect and path containment [RES-01][DATA-03][RES-02]', () => {
  it('requests relative /portal/me with redirect error, no-store, and omitted credentials [RES-01]', async () => {
    const fetchImpl = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => jsonResponse(200, meBody()));
    const result = await fetchPortalMe({
      getToken: async () => 'session-jwt',
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    expect(result).toEqual({ outcome: PortalMeOutcome.Ok, tenantId: TENANT });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(fetchImpl).toHaveBeenCalledWith(
      PORTAL_ME_PATH,
      expect.objectContaining({
        method: 'GET',
        cache: 'no-store',
        credentials: 'omit',
        redirect: 'error',
      }),
    );
    const requested = fetchImpl.mock.calls[0]?.[0];
    expect(requested).toBe(PORTAL_ME_PATH);
    expect(String(requested)).not.toMatch(/^https?:/i);
  });

  it('fails closed when the transport throws because a redirect was refused [RES-01][RLSE-04]', async () => {
    const fetchImpl = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.redirect === 'error') {
        throw new TypeError('Failed to fetch');
      }
      return responseWithUrl(200, meBody(), 'https://evil.example/portal/me');
    });

    const result = await fetchPortalMe({
      getToken: async () => 'session-jwt',
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    expect(result).toEqual({ outcome: PortalMeOutcome.Outage });
    expect(result).not.toEqual(expect.objectContaining({ tenantId: TENANT }));
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('does not accept a UUID tenant from a redirected or foreign final URL [RES-01][DATA-03]', async () => {
    const foreign = await fetchPortalMe({
      getToken: async () => 'session-jwt',
      fetchImpl: vi.fn(async () =>
        responseWithUrl(200, meBody(), 'https://evil.example/portal/me'),
      ) as unknown as typeof fetch,
    });
    expect(foreign).toEqual({ outcome: PortalMeOutcome.Outage });

    const otherPortalPath = await fetchPortalMe({
      getToken: async () => 'session-jwt',
      fetchImpl: vi.fn(async () =>
        responseWithUrl(200, meBody(), 'https://app.altcontext.com/portal/keys'),
      ) as unknown as typeof fetch,
    });
    expect(otherPortalPath).toEqual({ outcome: PortalMeOutcome.Outage });
  });

  it('still accepts a same-origin /portal/me success URL [RES-01]', async () => {
    const result = await fetchPortalMe({
      getToken: async () => 'session-jwt',
      fetchImpl: vi.fn(async () =>
        responseWithUrl(200, meBody(), 'https://app.altcontext.com/portal/me'),
      ) as unknown as typeof fetch,
    });
    expect(result).toEqual({ outcome: PortalMeOutcome.Ok, tenantId: TENANT });
  });

  it('keeps the token deadline and never fetches after a hanging getToken [RES-02]', async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn();
    const pending = fetchPortalMe({
      getToken: () => new Promise<string | null>(() => undefined),
      fetchImpl: fetchImpl as unknown as typeof fetch,
      timeoutMs: 40,
    });

    await vi.advanceTimersByTimeAsync(40);
    await expect(pending).resolves.toEqual({ outcome: PortalMeOutcome.Outage });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('does not mount private modules when /portal/me is redirected [RES-01][HAI-01]', async () => {
    signInVerified();
    const fetchImpl = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (String(_input).split('?')[0] !== '/portal/me') {
        return jsonResponse(404, { detail: 'missing fixture' });
      }
      if (init?.redirect === 'error') {
        throw new TypeError('Failed to fetch');
      }
      return responseWithUrl(200, meBody(), 'https://evil.example/portal/me');
    });

    renderPortal({ path: '/keys', fetchImpl: fetchImpl as unknown as typeof fetch });

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/temporarily unavailable|try again/i);
    });
    expect(screen.queryByRole('heading', { name: /api keys/i })).not.toBeInTheDocument();
    expect(screen.queryByText(TENANT)).not.toBeInTheDocument();
  });
});

describe('APP1-INTEGRATION-RV03 private route segment boundaries [NAV-08][NAV-11][HAI-01]', () => {
  it.each([
    ['/keys-old', /api keys/i],
    ['/usage-preview', /^usage$/i],
    ['/billing-malformed', /^billing$/i],
    ['/billing/returnevil', /billing return/i],
  ] as const)('does not mount a real module for crafted %s', async (path, moduleHeading) => {
    signInVerified();
    renderPortal({ path, fetchImpl: portalFetch() as unknown as typeof fetch });

    await waitFor(() => {
      expect(screen.queryByText(/checking account/i)).not.toBeInTheDocument();
    });
    expect(screen.queryByRole('heading', { name: moduleHeading })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /^billing$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /billing return/i })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /^account$/i })).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: /account/i })).toBeInTheDocument();
    expect(screen.getByText(TENANT)).toBeInTheDocument();
  });

  it('does not mount the claim screen at /claim-anything [NAV-08][HAI-01]', async () => {
    signInVerified();
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).split('?')[0] === '/portal/me') {
        return jsonResponse(403, { detail: 'portal access denied' });
      }
      throw new Error(`unexpected path ${String(input)}`);
    });

    renderPortal({ path: '/claim-anything', fetchImpl: fetchImpl as unknown as typeof fetch });

    await waitFor(() => {
      expect(screen.queryByText(/checking account/i)).not.toBeInTheDocument();
    });
    expect(screen.queryByRole('heading', { name: /claim your invited account/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/invitation token/i)).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(/not ready for access/i);
    expect(screen.getByRole('button', { name: /claim access/i })).toBeEnabled();
  });

  it.each([
    ['/keys', /api keys/i],
    ['/keys/wordpress', /wordpress test connection/i],
    ['/usage', /^usage$/i],
    ['/billing', /^billing$/i],
    ['/billing/return', /billing return/i],
  ] as const)('still mounts canonical %s', async (path, heading) => {
    signInVerified();
    renderPortal({ path, fetchImpl: portalFetch() as unknown as typeof fetch });

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: heading })).toBeInTheDocument();
    });
  });

  it('still mounts canonical /claim for a verified not-admitted identity', async () => {
    signInVerified();
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).split('?')[0] === '/portal/me') {
        return jsonResponse(403, { detail: 'portal access denied' });
      }
      throw new Error(`unexpected path ${String(input)}`);
    });

    renderPortal({ path: '/claim', fetchImpl: fetchImpl as unknown as typeof fetch });

    await waitFor(() => {
      expect(screen.getByLabelText(/invitation token/i)).toBeInTheDocument();
    });
    expect(screen.getByRole('heading', { name: /claim your invited account/i })).toBeInTheDocument();
  });
});
