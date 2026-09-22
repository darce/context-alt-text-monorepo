import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { flushSync } from 'react-dom';
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

const TENANT_A = '11111111-1111-4111-8111-111111111111';
const TENANT_B = '22222222-2222-4222-8222-222222222222';
const USER_A = 'user_a';
const USER_B = 'user_b';

const personA = {
  fullName: 'Ada Lovelace',
  primaryEmailAddress: {
    emailAddress: 'ada@example.test',
    verification: { status: 'verified' as const },
  },
};

const personB = {
  fullName: 'Grace Hopper',
  primaryEmailAddress: {
    emailAddress: 'grace@example.test',
    verification: { status: 'verified' as const },
  },
};

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function meBody(tenantId: string, subject: string, email: string) {
  return {
    tenant_id: tenantId,
    issuer: 'https://clerk.altcontext.com',
    subject,
    email,
  };
}

function signInA() {
  clerkDouble.setState({
    isLoaded: true,
    isSignedIn: true,
    userId: USER_A,
    sessionId: 'sess_a',
    user: personA,
    getToken: async () => 'jwt-a',
  });
}

afterEach(() => {
  clerkDouble.reset();
});

describe('synchronous identity ownership [DATA-03][DDIA]', () => {
  it('never paints tenant A after person B becomes the active Clerk identity', async () => {
    signInA();
    let finishB: ((value: Response) => void) | undefined;
    const fetchImpl = vi.fn(async () => {
      if (clerkDouble.state.userId === USER_A) {
        return jsonResponse(200, meBody(TENANT_A, USER_A, 'ada@example.test'));
      }
      return new Promise<Response>((resolve) => {
        finishB = resolve;
      });
    });

    renderPortal({ fetchImpl: fetchImpl as unknown as typeof fetch });

    await waitFor(() => {
      expect(screen.getByText(TENANT_A)).toBeInTheDocument();
    });
    expect(screen.getByText(/signed in as ada lovelace/i)).toBeInTheDocument();

    flushSync(() => {
      clerkDouble.setState({
        userId: USER_B,
        sessionId: 'sess_b',
        user: personB,
        getToken: async () => 'jwt-b',
      });
    });

    expect(screen.queryByText(TENANT_A)).not.toBeInTheDocument();
    expect(screen.getByText(/signed in as grace hopper/i)).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(/checking account/i);

    await waitFor(() => {
      expect(finishB).toBeTypeOf('function');
    });
    finishB?.(jsonResponse(200, meBody(TENANT_B, USER_B, 'grace@example.test')));

    await waitFor(() => {
      expect(screen.getByText(TENANT_B)).toBeInTheDocument();
    });
    expect(screen.queryByText(TENANT_A)).not.toBeInTheDocument();
  });

  it('clears tenant A when only the Clerk session id is replaced', async () => {
    signInA();
    let finishReplacement: ((value: Response) => void) | undefined;
    let meCalls = 0;
    const fetchImpl = vi.fn(async () => {
      meCalls += 1;
      if (meCalls === 1) {
        return jsonResponse(200, meBody(TENANT_A, USER_A, 'ada@example.test'));
      }
      return new Promise<Response>((resolve) => {
        finishReplacement = resolve;
      });
    });

    renderPortal({ fetchImpl: fetchImpl as unknown as typeof fetch });
    await waitFor(() => {
      expect(screen.getByText(TENANT_A)).toBeInTheDocument();
    });

    flushSync(() => {
      clerkDouble.setState({ sessionId: 'sess_a_replaced' });
    });

    expect(screen.queryByText(TENANT_A)).not.toBeInTheDocument();
    expect(screen.getByText(/signed in as ada lovelace/i)).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(/checking account/i);

    await waitFor(() => {
      expect(finishReplacement).toBeTypeOf('function');
    });
    finishReplacement?.(jsonResponse(200, meBody(TENANT_B, USER_A, 'ada@example.test')));
    await waitFor(() => {
      expect(screen.getByText(TENANT_B)).toBeInTheDocument();
    });
    expect(screen.queryByText(TENANT_A)).not.toBeInTheDocument();
  });

  it('clears tenant A on a cross-tab storage identity event before the replacement fetch settles', async () => {
    signInA();
    let finishB: ((value: Response) => void) | undefined;
    const fetchImpl = vi.fn(async () => {
      if (clerkDouble.state.sessionId === 'sess_a') {
        return jsonResponse(200, meBody(TENANT_A, USER_A, 'ada@example.test'));
      }
      return new Promise<Response>((resolve) => {
        finishB = resolve;
      });
    });

    renderPortal({ fetchImpl: fetchImpl as unknown as typeof fetch });
    await waitFor(() => {
      expect(screen.getByText(TENANT_A)).toBeInTheDocument();
    });

    flushSync(() => {
      clerkDouble.setState({
        userId: USER_B,
        sessionId: 'sess_b',
        user: personB,
        getToken: async () => 'jwt-b',
      });
      window.dispatchEvent(
        new StorageEvent('storage', {
          key: 'clerk-db',
          newValue: 'sess_b',
          oldValue: 'sess_a',
        }),
      );
    });

    expect(screen.queryByText(TENANT_A)).not.toBeInTheDocument();
    expect(screen.getByText(/signed in as grace hopper/i)).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(/checking account/i);

    await waitFor(() => {
      expect(finishB).toBeTypeOf('function');
    });
    finishB?.(jsonResponse(200, meBody(TENANT_B, USER_B, 'grace@example.test')));
    await waitFor(() => {
      expect(screen.getByText(TENANT_B)).toBeInTheDocument();
    });
    expect(screen.queryByText(TENANT_A)).not.toBeInTheDocument();
  });
});

describe('sign-out/sign-in HTTP cache isolation [DATA-03][PERF-11]', () => {
  it('does not reuse a cached tenant A /portal/me body after B signs in', async () => {
    signInA();
    let cachedBody: string | null = null;
    const caches: Array<RequestCache | undefined> = [];
    const fetchImpl = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      caches.push(init?.cache);
      if (init?.cache !== 'no-store' && cachedBody) {
        return jsonResponse(200, JSON.parse(cachedBody) as unknown);
      }
      const body =
        clerkDouble.state.userId === USER_A
          ? meBody(TENANT_A, USER_A, 'ada@example.test')
          : meBody(TENANT_B, USER_B, 'grace@example.test');
      cachedBody = JSON.stringify(body);
      return jsonResponse(200, body);
    });
    clerkDouble.state.signOut = async () => {
      clerkDouble.setState({
        isSignedIn: false,
        userId: null,
        sessionId: null,
        user: null,
      });
    };

    const user = userEvent.setup();
    renderPortal({ fetchImpl: fetchImpl as unknown as typeof fetch });
    await waitFor(() => {
      expect(screen.getByText(TENANT_A)).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /sign out/i }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^sign in$/i })).toBeEnabled();
    });
    expect(screen.queryByText(TENANT_A)).not.toBeInTheDocument();

    flushSync(() => {
      clerkDouble.setState({
        isSignedIn: true,
        userId: USER_B,
        sessionId: 'sess_b',
        user: personB,
        getToken: async () => 'jwt-b',
      });
    });

    await waitFor(() => {
      expect(screen.getByText(TENANT_B)).toBeInTheDocument();
    });
    expect(screen.queryByText(TENANT_A)).not.toBeInTheDocument();
    expect(caches.length).toBeGreaterThanOrEqual(2);
    expect(caches.every((cache) => cache === 'no-store')).toBe(true);
  });
});
