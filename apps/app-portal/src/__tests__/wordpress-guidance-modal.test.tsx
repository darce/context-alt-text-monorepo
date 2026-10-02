import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { WordPressTestConnectionGuidance } from '../components/WordPressTestConnectionGuidance';
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

afterEach(() => {
  clerkDouble.reset();
});

describe('WordPress guidance modal [A11Y-11]', () => {
  it('calls onClose when Escape is pressed', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<WordPressTestConnectionGuidance onClose={onClose} onReturnToKeys={() => undefined} />);

    await user.keyboard('{Escape}');

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('focuses and contains keyboard navigation, closes with Escape, and inerts session controls', async () => {
    const user = userEvent.setup();
    signInVerified();
    renderPortal({ path: '/keys/wordpress', fetchImpl: portalFetch() as unknown as typeof fetch });

    const dialog = await screen.findByRole('dialog', { name: /wordpress test connection guidance/i });
    const heading = screen.getByRole('heading', { name: /wordpress test connection guidance/i });
    const backButton = screen.getByRole('button', { name: /back to api keys/i });
    const closeButton = screen.getByRole('button', { name: /^close$/i });
    await waitFor(() => expect(heading).toHaveFocus());

    const sessionEscape = document.querySelector('.acx-session-bar');
    expect(sessionEscape).not.toBeNull();
    expect(sessionEscape).toHaveAttribute('inert');

    closeButton.focus();
    await user.tab();
    expect(backButton).toHaveFocus();

    backButton.focus();
    await user.tab({ shift: true });
    expect(closeButton).toHaveFocus();

    await user.keyboard('{Escape}');
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: /wordpress test connection guidance/i })).not.toBeInTheDocument();
      expect(screen.getByRole('heading', { name: /api keys/i })).toBeInTheDocument();
    });
    expect(dialog).not.toBeInTheDocument();
  });
});
