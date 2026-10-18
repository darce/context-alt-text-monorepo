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

const TENANT = '11111111-1111-4111-8111-111111111111';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
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
      return jsonResponse(200, { data: [], next_cursor: null, cursor: null, limit: 25, total: 0 });
    }
    return jsonResponse(404, { detail: 'missing fixture' });
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

afterEach(() => {
  clerkDouble.reset();
});

describe('portal route focus [ARV1004-PSHELL-L-1]', () => {
  it('focuses the destination heading after keyboard navigation from Account to API keys', async () => {
    signInVerified();
    const user = userEvent.setup();
    renderPortal({ fetchImpl: portalFetch() as unknown as typeof fetch });

    await waitFor(() => expect(screen.getByText(TENANT)).toBeInTheDocument());
    const apiKeysButton = screen.getByRole('button', { name: /api keys/i });
    apiKeysButton.focus();
    expect(apiKeysButton).toHaveFocus();

    await user.keyboard('{Enter}');

    const heading = await screen.findByRole('heading', { name: /api keys/i });
    await waitFor(() => expect(heading).toHaveFocus());
  });
});
