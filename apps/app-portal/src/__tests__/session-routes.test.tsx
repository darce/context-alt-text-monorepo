import { screen } from '@testing-library/react';
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

afterEach(() => {
  clerkDouble.reset();
});

describe('signed-out chrome and auth routes [NAV-08][NAV-07]', () => {
  it('enables Sign in and Create account when Clerk is ready and signed out', () => {
    renderPortal();

    expect(screen.getByRole('button', { name: /^sign in$/i })).toBeEnabled();
    expect(screen.getByRole('button', { name: /create account/i })).toBeEnabled();
    expect(screen.getByRole('status')).toHaveTextContent(/ready to sign in/i);
  });

  it('opens the Sign in route and keeps an escape back to account', async () => {
    const user = userEvent.setup();
    renderPortal();

    await user.click(screen.getByRole('button', { name: /^sign in$/i }));

    expect(screen.getByRole('form', { name: /secure account sign-in/i })).toBeInTheDocument();
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /back to account/i })).toHaveAttribute('href', '/');
    expect(screen.getByRole('link', { name: /create account/i })).toHaveAttribute('href', '/sign-up');
  });

  it('opens the Create account route without claiming a workspace is ready', async () => {
    const user = userEvent.setup();
    renderPortal();

    await user.click(screen.getByRole('button', { name: /create account/i }));

    expect(screen.getByRole('form', { name: /secure account setup/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /back to account/i })).toHaveAttribute('href', '/');
    expect(screen.getByRole('link', { name: /^sign in$/i })).toHaveAttribute('href', '/sign-in');
    expect(screen.queryByText(/workspace is ready/i)).not.toBeInTheDocument();
  });

  it('does not follow an open redirect from redirect_url [SEC]', async () => {
    const user = userEvent.setup();
    renderPortal({ path: '/sign-in?redirect_url=https://evil.example' });

    expect(screen.getByRole('form', { name: /secure account sign-in/i })).toBeInTheDocument();
    await user.click(screen.getByRole('link', { name: /back to account/i }));
    expect(screen.getByRole('button', { name: /^sign in$/i })).toBeInTheDocument();
    expect(window.location.href).not.toContain('evil.example');
  });
});
