import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { flushSync } from 'react-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { parsePortalConfig } from '../config';
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
const ATTEMPT_ID = '22222222-2222-4222-8222-222222222222';
const INVITATION = 'raw-invitation-token-once';

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

function portalFetch(options: { me?: () => Response | Promise<Response>; claimAdmitted?: { current: boolean } } = {}) {
  return vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    const path = url.split('?')[0];
    if (path === '/portal/me') {
      if (options.me) {
        return options.me();
      }
      if (options.claimAdmitted?.current) {
        return jsonResponse(200, meBody());
      }
      return jsonResponse(200, meBody());
    }
    if (path === '/portal/keys') {
      return jsonResponse(200, keysPage());
    }
    if (path === '/portal/usage') {
      return jsonResponse(200, usageBody());
    }
    if (path === '/portal/onboarding/claim') {
      if (options.claimAdmitted) {
        options.claimAdmitted.current = true;
      }
      return jsonResponse(201, {
        tenant_id: TENANT,
        issuer: 'https://clerk.altcontext.com',
        subject: 'user_1',
        email: 'ada@example.test',
        replayed: false,
      });
    }
    if (path === '/portal/billing/checkout' || path === '/portal/billing/manage') {
      throw new Error(`billing call must be absent when payments are disabled: ${path}`);
    }
    return jsonResponse(404, { detail: 'missing fixture' });
  });
}

afterEach(() => {
  clerkDouble.reset();
});

describe('public payments config [HAI-01]', () => {
  it('defaults payments disabled and empty plan, enabling only explicit recognized true', () => {
    expect(
      parsePortalConfig({
        VITE_CLERK_PUBLISHABLE_KEY: 'pk_test',
        VITE_CLERK_FAPI: 'https://clerk.altcontext.com',
        VITE_PORTAL_ENABLED: 'true',
        VITE_PAYMENTS_ENABLED: '',
        VITE_PUBLIC_PLAN_CODE: '',
      }),
    ).toEqual({
      publishableKey: 'pk_test',
      fapiOrigin: 'https://clerk.altcontext.com',
      portalEnabled: true,
      paymentsEnabled: false,
      publicPlanCode: null,
    });

    expect(
      parsePortalConfig({
        VITE_CLERK_PUBLISHABLE_KEY: 'pk_test',
        VITE_CLERK_FAPI: 'https://clerk.altcontext.com',
        VITE_PORTAL_ENABLED: 'true',
        VITE_PAYMENTS_ENABLED: 'maybe',
        VITE_PUBLIC_PLAN_CODE: '  starter_monthly  ',
      }).paymentsEnabled,
    ).toBe(false);

    expect(
      parsePortalConfig({
        VITE_CLERK_PUBLISHABLE_KEY: 'pk_test',
        VITE_CLERK_FAPI: 'https://clerk.altcontext.com',
        VITE_PORTAL_ENABLED: 'true',
        VITE_PAYMENTS_ENABLED: 'TRUE',
        VITE_PUBLIC_PLAN_CODE: '  starter_monthly  ',
      }),
    ).toMatchObject({
      paymentsEnabled: true,
      publicPlanCode: 'starter_monthly',
    });
  });
});

describe('admitted shell navigation [NAV-08][NAV-11]', () => {
  it('wires keys, usage, billing, billing return, and WordPress guidance with sign-out', async () => {
    signInVerified();
    const fetchImpl = portalFetch();
    const user = userEvent.setup();
    renderPortal({ fetchImpl: fetchImpl as unknown as typeof fetch });

    await waitFor(() => {
      expect(screen.getByText(TENANT)).toBeInTheDocument();
    });
    expect(screen.getByRole('navigation', { name: /account/i })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /api keys/i }));
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /api keys/i })).toBeInTheDocument();
    });
    expect(screen.getByRole('main')).toHaveTextContent(KEY_ID);
    expect(screen.getByRole('button', { name: /sign out/i })).toBeEnabled();

    await user.click(screen.getByRole('button', { name: /wordpress test connection guidance/i }));
    expect(screen.getByRole('heading', { name: /wordpress test connection/i })).toBeInTheDocument();
    expect(screen.queryByText(/acx_live|raw_key/i)).not.toBeInTheDocument();
    expect(window.location.href).not.toMatch(/acx_live|raw_key|secret=/i);

    await user.click(screen.getByRole('button', { name: /back to api keys/i }));
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /api keys/i })).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /^usage$/i }));
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^usage$/i })).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /^billing$/i }));
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^billing$/i })).toBeInTheDocument();
    });
    expect(screen.getByRole('status')).toHaveTextContent(/payments are disabled/i);
    expect(screen.getByRole('button', { name: /continue to checkout/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /manage billing/i })).toBeDisabled();
  });

  it('keeps billing return pending and never grants entitlement or posts checkout [HAI-01]', async () => {
    signInVerified();
    const fetchImpl = portalFetch();
    renderPortal({
      path: '/billing/return?checkout=success',
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /billing return/i })).toBeInTheDocument();
    });
    expect(screen.getByRole('status')).toHaveTextContent(/pending reconciliation|backend confirmation/i);
    expect(screen.queryByText(/paid_active|you are now paid|subscription is active/i)).not.toBeInTheDocument();
    expect(fetchImpl.mock.calls.some((call) => String(call[0]).includes('/portal/billing'))).toBe(false);
  });
});

describe('claim admission boundary [HAI-01][DOM-03]', () => {
  it('lets a verified not-admitted identity claim and refetches /portal/me before admission', async () => {
    signInVerified();
    const admitted = { current: false };
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input).split('?')[0];
      if (path === '/portal/me') {
        if (admitted.current) {
          return jsonResponse(200, meBody());
        }
        return jsonResponse(403, { detail: 'portal access denied' });
      }
      if (path === '/portal/onboarding/claim') {
        return jsonResponse(201, {
          tenant_id: TENANT,
          issuer: 'https://clerk.altcontext.com',
          subject: 'user_1',
          email: 'ada@example.test',
          replayed: false,
        });
      }
      throw new Error(`unexpected path ${path}`);
    });
    const user = userEvent.setup();
    renderPortal({ fetchImpl: fetchImpl as unknown as typeof fetch });

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/not ready for access/i);
    });
    expect(screen.queryByText(TENANT)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /claim access/i }));
    expect(screen.getByLabelText(/invitation token/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sign out/i })).toBeEnabled();

    await user.type(screen.getByLabelText(/invitation token/i), INVITATION);
    await user.click(screen.getByRole('button', { name: /^claim access$/i }));
    await user.click(screen.getByRole('button', { name: /confirm claim access/i }));

    await waitFor(() => {
      expect(fetchImpl.mock.calls.some((call) => String(call[0]).includes('/portal/onboarding/claim'))).toBe(true);
      expect(
        fetchImpl.mock.calls.filter((call) => String(call[0]).split('?')[0] === '/portal/me').length,
      ).toBeGreaterThan(1);
    });
    expect(screen.queryByRole('heading', { name: /api keys/i })).not.toBeInTheDocument();
    expect(screen.queryByText(TENANT)).not.toBeInTheDocument();
    expect(window.location.href).not.toContain(INVITATION);
    expect(window.location.hash).not.toContain(INVITATION);
    admitted.current = true;
    expect(screen.queryByText(TENANT)).not.toBeInTheDocument();
  });

  it('admits only after a post-claim /portal/me tenant, never from the claim body [HAI-01]', async () => {
    signInVerified();
    const admitted = { current: false };
    const fetchImpl = portalFetch({ claimAdmitted: admitted });
    fetchImpl.mockImplementation(async (input: RequestInfo | URL) => {
      const path = String(input).split('?')[0];
      if (path === '/portal/me') {
        return admitted.current ? jsonResponse(200, meBody()) : jsonResponse(403, { detail: 'portal access denied' });
      }
      if (path === '/portal/onboarding/claim') {
        admitted.current = true;
        return jsonResponse(201, {
          tenant_id: TENANT,
          issuer: 'https://clerk.altcontext.com',
          subject: 'user_1',
          email: 'ada@example.test',
          replayed: false,
        });
      }
      if (path === '/portal/keys') {
        return jsonResponse(200, keysPage());
      }
      return jsonResponse(404, {});
    });
    const user = userEvent.setup();
    renderPortal({ path: '/claim', fetchImpl: fetchImpl as unknown as typeof fetch });

    await waitFor(() => {
      expect(screen.getByLabelText(/invitation token/i)).toBeInTheDocument();
    });
    await user.type(screen.getByLabelText(/invitation token/i), INVITATION);
    await user.click(screen.getByRole('button', { name: /^claim access$/i }));
    await user.click(screen.getByRole('button', { name: /confirm claim access/i }));

    await waitFor(() => {
      expect(screen.getByText(TENANT)).toBeInTheDocument();
    });
    expect(
      fetchImpl.mock.calls.filter((call) => String(call[0]).split('?')[0] === '/portal/me').length,
    ).toBeGreaterThan(1);
  });

  it('does not offer claim to an unverified identity', async () => {
    clerkDouble.setState({
      isLoaded: true,
      isSignedIn: true,
      userId: 'user_1',
      sessionId: 'sess_1',
      user: {
        fullName: 'Ada Lovelace',
        primaryEmailAddress: {
          emailAddress: 'ada@example.test',
          verification: { status: 'unverified' },
        },
      },
      getToken: async () => 'session-jwt',
    });
    renderPortal({
      path: '/claim',
      fetchImpl: vi.fn(async () =>
        jsonResponse(403, { detail: { code: 'email_unverified' } }),
      ) as unknown as typeof fetch,
    });

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/verify your email/i);
    });
    expect(screen.queryByLabelText(/invitation token/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /claim access/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sign out/i })).toBeEnabled();
  });
});

describe('private subtree ownership [DATA-03][CARD-15]', () => {
  it('clears keys metadata synchronously when the same user gets a new session', async () => {
    signInVerified('sess_a');
    const fetchImpl = portalFetch();
    renderPortal({ path: '/keys', fetchImpl: fetchImpl as unknown as typeof fetch });

    await waitFor(() => {
      expect(screen.getByRole('main')).toHaveTextContent(KEY_ID);
    });

    flushSync(() => {
      clerkDouble.setState({ sessionId: 'sess_a_replaced' });
    });

    expect(screen.getByRole('main')).not.toHaveTextContent(KEY_ID);
    expect(screen.getByRole('status')).toHaveTextContent(/checking account/i);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /sign out/i })).toBeEnabled();
    });
  });

  it('hides private modules immediately when sign-out fails [RLSE-04]', async () => {
    signInVerified();
    clerkDouble.state.signOut = vi.fn(async () => {
      throw new Error('network');
    });
    const fetchImpl = portalFetch();
    const user = userEvent.setup();
    renderPortal({ path: '/keys', fetchImpl: fetchImpl as unknown as typeof fetch });

    await waitFor(() => {
      expect(screen.getByRole('main')).toHaveTextContent(KEY_ID);
    });

    await user.click(screen.getByRole('button', { name: /sign out/i }));

    expect(screen.getByRole('main')).not.toHaveTextContent(KEY_ID);
    expect(screen.queryByRole('heading', { name: /api keys/i })).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(/sign out failed|could not sign out/i);
    expect(screen.getByRole('button', { name: /try again/i })).toBeEnabled();
  });
});

describe('opaque attempt id [HAI-01]', () => {
  it('does not put attempt, invite, or raw key material in search or hash', async () => {
    signInVerified();
    renderPortal({
      path: `/billing/return?attempt_id=${ATTEMPT_ID}&invitation=${INVITATION}`,
      fetchImpl: portalFetch() as unknown as typeof fetch,
    });

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /billing return/i })).toBeInTheDocument();
    });
    expect(screen.queryByText(INVITATION)).not.toBeInTheDocument();
    expect(screen.queryByText(ATTEMPT_ID)).not.toBeInTheDocument();
  });
});
