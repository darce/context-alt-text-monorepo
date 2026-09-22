import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
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

const TENANT_ID = '11111111-1111-4111-8111-111111111111';

function signedInPerson() {
  clerkDouble.state.isLoaded = true;
  clerkDouble.state.isSignedIn = true;
  clerkDouble.state.userId = 'user_1';
  clerkDouble.state.user = {
    fullName: 'Ada Lovelace',
    primaryEmailAddress: {
      emailAddress: 'ada@example.test',
      verification: { status: 'verified' },
    },
  };
  clerkDouble.state.getToken = async () => 'session-jwt';
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

afterEach(() => {
  clerkDouble.reset();
});

describe('backend authority for tenant display [CARD-12][DOM-03]', () => {
  it('shows tenant UUID only from GET /portal/me and never from email or org', async () => {
    signedInPerson();
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toBe('/portal/me');
      expect(init?.method ?? 'GET').toBe('GET');
      expect(init?.credentials).toBe('omit');
      expect(init?.headers).toEqual({ Authorization: 'Bearer session-jwt' });
      return jsonResponse(200, {
        tenant_id: TENANT_ID,
        issuer: 'https://clerk.altcontext.com',
        subject: 'user_1',
        email: 'ada@example.test',
      });
    });

    renderPortal({ fetchImpl: fetchImpl as unknown as typeof fetch });

    expect(screen.getByRole('status')).toHaveTextContent(/checking account/i);
    expect(screen.getByRole('button', { name: /open account menu/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sign out/i })).toBeEnabled();

    await waitFor(() => {
      expect(screen.getByText(TENANT_ID)).toBeInTheDocument();
    });
    expect(screen.getByText(/signed in as ada lovelace/i)).toBeInTheDocument();
    expect(screen.queryByText(/ada@example\.test workspace/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /organization/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/organization switcher/i)).not.toBeInTheDocument();
  });

  it('keeps the tenant strip empty when the server omits tenant_id', async () => {
    signedInPerson();
    const fetchImpl = vi.fn(async () =>
      jsonResponse(200, {
        issuer: 'https://clerk.altcontext.com',
        subject: 'user_1',
        email: 'ada@example.test',
      }),
    );

    renderPortal({ fetchImpl: fetchImpl as unknown as typeof fetch });

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/not linked yet|waiting for account/i);
    });
    expect(screen.queryByText(/ada@example\.test/)).not.toBeInTheDocument();
    expect(screen.queryByText(/lovelace/i)).not.toHaveTextContent(/tenant/i);
  });

  it('maps 401, email verification, 403 not admitted, and 503 outage explicitly', async () => {
    signedInPerson();
    const fetchImpl = vi.fn(async () => jsonResponse(401, { detail: 'invalid portal authorization' }));
    const first = renderPortal({ fetchImpl: fetchImpl as unknown as typeof fetch });
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/could not be verified|sign-in session/i);
    });
    first.unmount();

    signedInPerson();
    clerkDouble.state.user = {
      fullName: 'Ada Lovelace',
      primaryEmailAddress: {
        emailAddress: 'ada@example.test',
        verification: { status: 'unverified' },
      },
    };
    renderPortal({
      fetchImpl: vi.fn(async () =>
        jsonResponse(403, { detail: { code: 'email_unverified' } }),
      ) as unknown as typeof fetch,
    });
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/verify your email/i);
    });
    expect(screen.getByRole('button', { name: /sign out/i })).toBeEnabled();
    expect(screen.queryByText(TENANT_ID)).not.toBeInTheDocument();
  });

  it('shows not-admitted copy for backend 403 without enumerating tenant reasons', async () => {
    signedInPerson();
    renderPortal({
      fetchImpl: vi.fn(async () => jsonResponse(403, { detail: 'portal access denied' })) as unknown as typeof fetch,
    });

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/not ready for access/i);
    });
    expect(screen.queryByText(/tenant_not_eligible|claim_missing/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sign out/i })).toBeEnabled();
    expect(screen.getByRole('button', { name: /open account menu/i })).toBeInTheDocument();
  });

  it('retries a 503 identity outage without homemade login [RES-02]', async () => {
    signedInPerson();
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(503, { detail: 'portal authentication temporarily unavailable' }))
      .mockResolvedValueOnce(
        jsonResponse(200, {
          tenant_id: TENANT_ID,
          issuer: 'https://clerk.altcontext.com',
          subject: 'user_1',
          email: 'ada@example.test',
        }),
      );

    const user = userEvent.setup();
    renderPortal({ fetchImpl: fetchImpl as unknown as typeof fetch });

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/temporarily unavailable/i);
    });
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /try again/i }));

    await waitFor(() => {
      expect(screen.getByText(TENANT_ID)).toBeInTheDocument();
    });
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });
});
