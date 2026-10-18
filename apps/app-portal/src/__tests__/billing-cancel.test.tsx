import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
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

const TENANT = '11111111-1111-4111-8111-111111111111';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function renderBillingPath(path: string) {
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
  const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
    const requestPath = String(input).split('?')[0];
    if (requestPath === '/portal/me') {
      return jsonResponse(200, {
        tenant_id: TENANT,
        issuer: 'https://clerk.altcontext.com',
        subject: 'user_1',
        email: 'ada@example.test',
      });
    }
    if (requestPath === '/portal/usage') {
      return jsonResponse(200, {
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
      });
    }
    return jsonResponse(404, { detail: 'missing fixture' });
  });
  renderPortal({
    path,
    config: { ...TEST_CONFIG, paymentsEnabled: true, publicPlanCode: 'starter_monthly' },
    fetchImpl: fetchImpl as unknown as typeof fetch,
  });
  return fetchImpl;
}

afterEach(() => {
  clerkDouble.reset();
});

describe('A1HRV1005-01 checkout cancellation [INT-13][VIZ-22][TEST-15]', () => {
  it('shows cancellation and returns to billing to try checkout again', async () => {
    const user = userEvent.setup();
    const fetchImpl = renderBillingPath('/billing/cancel');

    expect(await screen.findByText('Checkout was cancelled.')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Checkout was cancelled.');
    expect(screen.getByRole('status').querySelector('svg')).toBeInTheDocument();
    const retry = screen.getByRole('button', { name: 'Try checkout again' });
    expect(retry).toHaveClass('acx-btn-primary');
    await user.click(retry);

    expect(await screen.findByRole('button', { name: 'Continue to checkout' })).toBeEnabled();
    expect(screen.getByRole('heading', { name: 'Billing' })).toBeInTheDocument();
    expect(screen.queryByText('Checkout was cancelled.')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Try checkout again' })).not.toBeInTheDocument();
    expect(fetchImpl.mock.calls.some(([input]) => String(input).includes('/portal/billing'))).toBe(false);
  });

  it('offers usage as a secondary recovery route', async () => {
    const user = userEvent.setup();
    renderBillingPath('/billing/cancel');
    expect(await screen.findByText('Checkout was cancelled.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'View usage' }));
    expect(await screen.findByRole('heading', { name: 'Usage' })).toBeInTheDocument();
  });

  it('omits cancellation status and recovery on plain billing', async () => {
    renderBillingPath('/billing');
    expect(await screen.findByRole('button', { name: 'Continue to checkout' })).toBeEnabled();
    expect(screen.queryByText('Checkout was cancelled.')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Try checkout again' })).not.toBeInTheDocument();
  });

  it.each(['/billing/cancelled', '/billing/cancelx'])('does not treat %s as cancellation', async (path) => {
    const fetchImpl = renderBillingPath(path);
    await waitFor(() => expect(fetchImpl).toHaveBeenCalledWith('/portal/me', expect.anything()));
    expect(await screen.findByRole('heading', { name: /account/i })).toBeInTheDocument();
    expect(screen.queryByText('Checkout was cancelled.')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Try checkout again' })).not.toBeInTheDocument();
  });
});
