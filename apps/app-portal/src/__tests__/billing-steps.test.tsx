import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import type { PortalBillingClient } from '../api/portalBilling';
import { BillingScreen, hostedNavigation } from '../screens/BillingScreen';
import { clerkDouble } from './clerkDouble';
import { TEST_CONFIG } from './renderPortal';

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
const ATTEMPT_ID = '22222222-2222-4222-8222-222222222222';
const PLAN = 'starter_monthly';
const CHECKOUT_URL = 'https://pay.example.test/checkout/abc';
const ATTEMPT_STORAGE_KEY = `app-portal:billing-return-attempt:${TENANT_ID}`;

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
    if (String(input).split('?')[0] === '/portal/me') {
      return jsonResponse(200, {
        tenant_id: TENANT_ID,
        issuer: 'https://clerk.altcontext.com',
        subject: 'user_1',
        email: 'ada@example.test',
      });
    }
    if (String(input).split('?')[0] === '/portal/billing/checkout') {
      return jsonResponse(200, {
        attempt_id: ATTEMPT_ID,
        checkout_url: CHECKOUT_URL,
        status: 'pending',
        replayed: false,
      });
    }
    return jsonResponse(404, { detail: 'missing fixture' });
  });
}

function renderApp(path: string, billingEnabled = false) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App
        config={{ ...TEST_CONFIG, paymentsEnabled: billingEnabled, publicPlanCode: billingEnabled ? PLAN : null }}
        fetchImpl={portalFetch() as unknown as typeof fetch}
      />
    </MemoryRouter>,
  );
}

afterEach(() => {
  clerkDouble.reset();
  window.sessionStorage.clear();
  window.localStorage.clear();
  hostedNavigation.open = (url: string) => {
    window.location.assign(url);
  };
});

describe('billing checkout steps and return recovery [NAV-09][INT-13]', () => {
  it('restores the tenant-scoped attempt id on a fresh billing return and clears it after sign-out', async () => {
    signInVerified();
    window.sessionStorage.setItem(ATTEMPT_STORAGE_KEY, ATTEMPT_ID);

    renderApp('/billing/return');

    expect(await screen.findByText(ATTEMPT_ID)).toBeInTheDocument();

    act(() => {
      clerkDouble.setState({
        isSignedIn: false,
        userId: null,
        sessionId: null,
        user: null,
        getToken: async () => null,
      });
    });
    await waitFor(() => expect(window.sessionStorage.getItem(ATTEMPT_STORAGE_KEY)).toBeNull());
  });

  it('stores the attempt id before opening hosted checkout', async () => {
    const user = userEvent.setup();
    signInVerified();
    const storageAtOpen: string[] = [];
    const open = vi.fn((url: string) => {
      storageAtOpen.push(`${url}:${window.sessionStorage.getItem(ATTEMPT_STORAGE_KEY)}`);
    });
    hostedNavigation.open = open;

    renderApp('/billing', true);

    await user.click(await screen.findByRole('button', { name: /continue to checkout/i }));
    await user.click(screen.getByRole('button', { name: /confirm hosted checkout/i }));

    await waitFor(() => expect(open).toHaveBeenCalledTimes(1));
    expect(storageAtOpen).toEqual([`${CHECKOUT_URL}:${ATTEMPT_ID}`]);
  });

  it('shows the ordered checkout steps with the review step marked current in preview', async () => {
    const user = userEvent.setup();
    const client: PortalBillingClient = {
      checkout: vi.fn(async () => ({
        attempt_id: ATTEMPT_ID,
        checkout_url: null,
        status: 'pending',
        replayed: false,
      })),
      manage: vi.fn(async () => ({ portal_url: 'https://pay.example.test/portal' })),
    };

    render(
      <BillingScreen
        client={client}
        publicPlanCode={PLAN}
        paymentsEnabled
        onNavigateToReturn={vi.fn()}
        onNavigateToUsage={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: /continue to checkout/i }));

    expect(screen.getByRole('listitem', { current: 'step' })).toHaveTextContent('Step 1 of 2: review plan');
    expect(screen.getByText('Step 2 of 2: pay with the provider')).toBeInTheDocument();
  });

  it.each(['failed', 'expired', 'canceled', 'unknown'])('restores the plan summary after a pending checkout resolves %s', async (status) => {
    const user = userEvent.setup();
    let resolveCheckout!: (response: Awaited<ReturnType<PortalBillingClient['checkout']>>) => void;
    const pendingCheckout = new Promise<Awaited<ReturnType<PortalBillingClient['checkout']>>>((resolve) => {
      resolveCheckout = resolve;
    });
    const client: PortalBillingClient = {
      checkout: vi.fn(() => pendingCheckout),
      manage: vi.fn(async () => ({ portal_url: 'https://pay.example.test/portal' })),
    };

    render(
      <BillingScreen
        client={client}
        publicPlanCode={PLAN}
        paymentsEnabled
        onNavigateToReturn={vi.fn()}
        onNavigateToUsage={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: /continue to checkout/i }));
    await user.click(screen.getByRole('button', { name: /confirm hosted checkout/i }));

    expect(screen.getByRole('list', { name: 'Checkout steps' })).toBeInTheDocument();
    expect(screen.getByRole('listitem', { current: 'step' })).toHaveTextContent(
      'Step 2 of 2: pay with the provider',
    );

    await act(async () => {
      resolveCheckout({
        attempt_id: ATTEMPT_ID,
        checkout_url: null,
        status,
        replayed: false,
      });
    });

    expect(screen.queryByRole('list', { name: 'Checkout steps' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /continue to checkout/i })).toBeEnabled();
    expect(client.checkout).toHaveBeenCalledTimes(1);
  });

  it('restores the plan summary and clears retry intent on preview after a pending checkout rejects', async () => {
    const user = userEvent.setup();
    let rejectCheckout!: (error: Error) => void;
    const pendingCheckout = new Promise<Awaited<ReturnType<PortalBillingClient['checkout']>>>((_, reject) => {
      rejectCheckout = reject;
    });
    const client: PortalBillingClient = {
      checkout: vi.fn(() => pendingCheckout),
      manage: vi.fn(async () => ({ portal_url: 'https://pay.example.test/portal' })),
    };

    render(
      <BillingScreen
        client={client}
        publicPlanCode={PLAN}
        paymentsEnabled
        onNavigateToReturn={vi.fn()}
        onNavigateToUsage={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: /continue to checkout/i }));
    await user.click(screen.getByRole('button', { name: /confirm hosted checkout/i }));

    expect(screen.getByRole('list', { name: 'Checkout steps' })).toBeInTheDocument();
    expect(screen.getByRole('listitem', { current: 'step' })).toHaveTextContent(
      'Step 2 of 2: pay with the provider',
    );

    await act(async () => {
      rejectCheckout(Object.assign(new Error('checkout_unavailable'), {
        status: 503,
        code: 'checkout_unavailable',
      }));
    });

    expect(screen.queryByRole('list', { name: 'Checkout steps' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /continue to checkout/i })).toBeEnabled();
    expect(client.checkout).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: /try billing again/i })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /continue to checkout/i }));
    expect(screen.getByRole('button', { name: /confirm hosted checkout/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /try billing again/i })).not.toBeInTheDocument();
    expect(client.checkout).toHaveBeenCalledTimes(1);
  });
});
