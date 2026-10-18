import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { App } from '../App';
import { TEST_CONFIG } from './renderPortal';
import { clerkDouble } from './clerkDouble';

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
const ATTEMPT_ID = '22222222-2222-4222-8222-222222222222';
const INVITATION = 'raw-invitation-token-once';
const RAW_KEY = 'raw-key-fragment-value';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function signInVerified() {
  clerkDouble.setState({
    isLoaded: true,
    isSignedIn: true,
    userId: 'user_1',
    sessionId: 'sess_1',
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

function portalFetch() {
  return vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input).split('?')[0];
    if (path === '/portal/me') {
      return jsonResponse(200, {
        tenant_id: TENANT,
        issuer: 'https://clerk.altcontext.com',
        subject: 'user_1',
        email: 'ada@example.test',
      });
    }
    if (path === '/portal/keys') {
      return jsonResponse(200, {
        data: [],
        next_cursor: null,
        cursor: null,
        limit: 25,
        total: 0,
      });
    }
    return jsonResponse(404, { detail: 'missing fixture' });
  });
}

function RouterLocationProbe() {
  const { pathname, search, hash } = useLocation();
  return <output data-testid="router-location">{JSON.stringify({ pathname, search, hash })}</output>;
}

function renderPortalAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <RouterLocationProbe />
      <App config={TEST_CONFIG} fetchImpl={portalFetch() as unknown as typeof fetch} />
    </MemoryRouter>,
  );
}

async function expectLocation(pathname: string) {
  const location = screen.getByTestId('router-location');
  await waitFor(() => {
    expect(JSON.parse(location.textContent ?? '{}')).toEqual({ pathname, search: '', hash: '' });
  });
}

afterEach(() => {
  clerkDouble.reset();
});

describe('billing return URL cleanup [WEB-44]', () => {
  it.each(['/sign-in', '/sign-in/verify', '/sign-up', '/sign-up/verify'])(
    'preserves Clerk callback query and fragment data on %s',
    async (pathname) => {
      const search = '?__clerk_ticket=verification-ticket&__clerk_status=verified';
      const hash = '#verification-callback';
      renderPortalAt(`${pathname}${search}${hash}`);

      expect(
        await screen.findByRole('form', {
          name: pathname.startsWith('/sign-in') ? 'Secure account sign-in' : 'Secure account setup',
        }),
      ).toBeInTheDocument();
      await waitFor(() => {
        expect(JSON.parse(screen.getByTestId('router-location').textContent ?? '{}')).toEqual({
          pathname,
          search,
          hash,
        });
      });
    },
  );

  it('replaces billing return query and fragment values while preserving the route', async () => {
    signInVerified();
    renderPortalAt(`/billing/return?attempt_id=${ATTEMPT_ID}&invitation=${INVITATION}#raw_key=${RAW_KEY}`);

    expect(await screen.findByRole('heading', { name: /billing return/i })).toBeInTheDocument();
    await expectLocation('/billing/return');
  });

  it('replaces private-route query values while preserving the route', async () => {
    signInVerified();
    renderPortalAt(`/keys?invitation=${INVITATION}`);

    expect(await screen.findByRole('heading', { name: /api keys/i })).toBeInTheDocument();
    await expectLocation('/keys');
  });
});
