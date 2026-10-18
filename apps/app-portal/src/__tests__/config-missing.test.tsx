import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { parsePortalConfig } from '../config';
import { clerkDouble } from './clerkDouble';
import { renderPortal, TEST_CONFIG } from './renderPortal';

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
  vi.useRealTimers();
});

describe('missing and disabled configuration [RLSE-04][FORM-09]', () => {
  it('parses a missing publishable key as unavailable config', () => {
    expect(
      parsePortalConfig({
        VITE_CLERK_PUBLISHABLE_KEY: '  ',
        VITE_CLERK_FAPI: 'https://clerk.altcontext.com',
        VITE_PORTAL_ENABLED: 'true',
      }),
    ).toEqual({
      publishableKey: null,
      fapiOrigin: 'https://clerk.altcontext.com',
      portalEnabled: true,
    });
  });

  it('shows a designed unavailable screen when the publishable key is missing', () => {
    renderPortal({
      config: { ...TEST_CONFIG, publishableKey: null },
    });

    expect(screen.getByRole('status')).toHaveTextContent(/account access is not configured/i);
    expect(screen.queryByRole('button', { name: /^sign in$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /create account/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('form', { name: /sign-in/i })).not.toBeInTheDocument();
  });

  it('shows a distinct degraded screen when the public portal flag is off', () => {
    renderPortal({
      config: { ...TEST_CONFIG, portalEnabled: false },
    });

    expect(screen.getByRole('status')).toHaveTextContent(/account access is turned off/i);
    expect(screen.queryByRole('button', { name: /^sign in$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /create account/i })).not.toBeInTheDocument();
  });

  it('disables sign-in and create-account until Clerk is ready [FORM-09][NAV-08]', () => {
    clerkDouble.state.isLoaded = false;
    clerkDouble.state.isSignedIn = false;
    renderPortal({ clerkLoadTimeoutMs: 8_000 });

    expect(screen.getByRole('status')).toHaveTextContent(/checking sign-in/i);
    expect(screen.getByRole('button', { name: /^sign in$/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /create account/i })).toBeDisabled();
  });

  it('shows a designed Clerk outage with retry after the bounded wait', async () => {
    clerkDouble.state.isLoaded = false;
    renderPortal({ clerkLoadTimeoutMs: 25 });

    expect(screen.getByRole('status')).toHaveTextContent(/checking sign-in/i);
    expect(await screen.findByRole('button', { name: /try again/i })).toBeEnabled();
    expect(screen.getByRole('status')).toHaveTextContent(/sign-in is temporarily unavailable/i);
    expect(screen.queryByRole('button', { name: /^sign in$/i })).not.toBeInTheDocument();
  });
});
