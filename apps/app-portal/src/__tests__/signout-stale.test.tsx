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

const TENANT_ID = '22222222-2222-4222-8222-222222222222';

function signedInPerson() {
  clerkDouble.state.isLoaded = true;
  clerkDouble.state.isSignedIn = true;
  clerkDouble.state.userId = 'user_2';
  clerkDouble.state.user = {
    fullName: 'Grace Hopper',
    primaryEmailAddress: {
      emailAddress: 'grace@example.test',
      verification: { status: 'verified' },
    },
  };
}

afterEach(() => {
  clerkDouble.reset();
});

describe('sign-out, retry, and stale /portal/me [CARD-15][RLSE-04]', () => {
  it('clears tenant data immediately and ignores a late /portal/me response', async () => {
    signedInPerson();
    let finishMe: ((value: Response) => void) | undefined;
    clerkDouble.state.getToken = async () => 'session-jwt';
    const fetchImpl = vi.fn(
      async () =>
        new Promise<Response>((resolve) => {
          finishMe = resolve;
        }),
    );
    clerkDouble.state.signOut = async () => {
      clerkDouble.state.isSignedIn = false;
      clerkDouble.state.userId = null;
      clerkDouble.state.user = null;
    };

    const user = userEvent.setup();
    renderPortal({ fetchImpl: fetchImpl as unknown as typeof fetch });

    expect(screen.getByRole('status')).toHaveTextContent(/checking account/i);
    await user.click(screen.getByRole('button', { name: /sign out/i }));

    expect(screen.queryByText(TENANT_ID)).not.toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^sign in$/i })).toBeEnabled();
    });

    finishMe?.(
      new Response(
        JSON.stringify({
          tenant_id: TENANT_ID,
          issuer: 'https://clerk.altcontext.com',
          subject: 'user_2',
          email: 'grace@example.test',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^sign in$/i })).toBeInTheDocument();
    });
    expect(screen.queryByText(TENANT_ID)).not.toBeInTheDocument();
  });

  it('keeps account data cleared and offers retry when sign-out fails', async () => {
    signedInPerson();
    clerkDouble.state.getToken = async () => 'session-jwt';
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            tenant_id: TENANT_ID,
            issuer: 'https://clerk.altcontext.com',
            subject: 'user_2',
            email: 'grace@example.test',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
    );
    clerkDouble.state.signOut = vi.fn(async () => {
      throw new Error('network');
    });

    const user = userEvent.setup();
    renderPortal({ fetchImpl: fetchImpl as unknown as typeof fetch });

    await waitFor(() => {
      expect(screen.getByText(TENANT_ID)).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /sign out/i }));

    expect(screen.queryByText(TENANT_ID)).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(/sign out failed|could not sign out/i);
    expect(screen.getByRole('button', { name: /try again/i })).toBeEnabled();

    clerkDouble.state.signOut = async () => {
      clerkDouble.state.isSignedIn = false;
      clerkDouble.state.userId = null;
      clerkDouble.state.user = null;
    };
    await user.click(screen.getByRole('button', { name: /try again/i }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^sign in$/i })).toBeEnabled();
    });
    expect(screen.queryByText(TENANT_ID)).not.toBeInTheDocument();
  });
});
