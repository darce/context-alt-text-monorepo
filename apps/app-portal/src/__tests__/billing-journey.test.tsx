import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  createPortalBillingClient,
  type PortalBillingApiError,
  type PortalBillingClient,
  type PortalCheckoutResponse,
  type PortalManageResponse,
} from '../api/portalBilling';
import { BillingScreen, hostedNavigation } from '../screens/BillingScreen';
import { BillingReturnScreen } from '../screens/BillingReturnScreen';

const ATTEMPT_ID = '22222222-2222-4222-8222-222222222222';
const PLAN = 'starter_monthly';
const CHECKOUT_URL = 'https://pay.example.test/checkout/abc';
const PORTAL_URL = 'https://pay.example.test/portal/abc';

const PENDING_CHECKOUT: PortalCheckoutResponse = {
  attempt_id: ATTEMPT_ID,
  checkout_url: CHECKOUT_URL,
  status: 'pending',
  replayed: false,
};

const SUCCEEDED_CHECKOUT: PortalCheckoutResponse = {
  attempt_id: ATTEMPT_ID,
  checkout_url: null,
  status: 'succeeded',
  replayed: true,
};

function jsonResponse(status: number, body: unknown, headers?: HeadersInit): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}

function apiError(
  partial: Partial<PortalBillingApiError> & Pick<PortalBillingApiError, 'status' | 'code'>,
): PortalBillingApiError {
  return {
    detail: null,
    attemptId: null,
    retryAfterSeconds: null,
    ...partial,
  };
}

async function confirmCheckout(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: /continue to checkout|open hosted checkout/i }));
  expect(screen.getByRole('button', { name: /confirm hosted checkout|confirm checkout/i })).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: /confirm hosted checkout|confirm checkout/i }));
}

afterEach(() => {
  hostedNavigation.open = (url: string) => {
    window.location.assign(url);
  };
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe('createPortalBillingClient [RES-01][DATA-03][HAI-01]', () => {
  it('sends a 64-128 character Idempotency-Key and parses checkout/manage JSON', async () => {
    const key = 'a'.repeat(64);
    const request = vi.fn(async (path: string, init?: RequestInit) => {
      if (path === '/portal/billing/checkout') {
        expect(init?.method).toBe('POST');
        const headers = new Headers(init?.headers);
        expect(headers.get('Idempotency-Key')).toBe(key);
        expect(headers.has('Origin')).toBe(false);
        expect(JSON.parse(String(init?.body))).toEqual({ plan_code: PLAN });
        return jsonResponse(200, PENDING_CHECKOUT);
      }
      expect(path).toBe('/portal/billing/manage');
      return jsonResponse(200, { portal_url: PORTAL_URL });
    });
    const client = createPortalBillingClient(request);
    await expect(client.checkout({ plan_code: PLAN }, key)).resolves.toEqual(PENDING_CHECKOUT);
    await expect(client.manage()).resolves.toEqual({ portal_url: PORTAL_URL });
  });

  it('rejects UUID-length keys, unsafe URLs, and malformed payloads fail-closed', async () => {
    const request = vi.fn(async () => jsonResponse(200, PENDING_CHECKOUT));
    const client = createPortalBillingClient(request);
    await expect(client.checkout({ plan_code: PLAN }, '123e4567-e89b-12d3-a456-426614174000')).rejects.toMatchObject({
      status: 422,
      code: 'invalid_idempotency_key',
    });
    expect(request).not.toHaveBeenCalled();

    const unsafe = createPortalBillingClient(async () =>
      jsonResponse(200, { ...PENDING_CHECKOUT, checkout_url: 'javascript:alert(1)' }),
    );
    await expect(unsafe.checkout({ plan_code: PLAN }, 'b'.repeat(64))).rejects.toMatchObject({
      code: 'malformed_response',
    });

    const httpUrl = createPortalBillingClient(async () =>
      jsonResponse(200, { ...PENDING_CHECKOUT, checkout_url: 'http://pay.example.test/c' }),
    );
    await expect(httpUrl.checkout({ plan_code: PLAN }, 'c'.repeat(64))).rejects.toMatchObject({
      code: 'malformed_response',
    });

    const dataUrl = createPortalBillingClient(async () => jsonResponse(200, { portal_url: 'data:text/html,hi' }));
    await expect(dataUrl.manage()).rejects.toMatchObject({ code: 'malformed_response' });
  });

  it('preserves checkout_ambiguous attempt_id and Retry-After without inventing a poll route', async () => {
    const client = createPortalBillingClient(async () =>
      jsonResponse(503, { detail: { code: 'checkout_ambiguous', attempt_id: ATTEMPT_ID } }, { 'Retry-After': '1' }),
    );
    await expect(client.checkout({ plan_code: PLAN }, 'd'.repeat(64))).rejects.toMatchObject({
      status: 503,
      code: 'checkout_ambiguous',
      attemptId: ATTEMPT_ID,
      retryAfterSeconds: 1,
    });
  });
});

describe('BillingScreen checkout and manage [RLSE-04][NAV-11][CARD-15]', () => {
  it('does not request checkout or manage when payments are off or plan is absent', async () => {
    const user = userEvent.setup();
    const checkout = vi.fn();
    const manage = vi.fn();
    const client = { checkout, manage };

    const { rerender } = render(
      <BillingScreen
        client={client}
        publicPlanCode={PLAN}
        paymentsEnabled={false}
        onNavigateToReturn={vi.fn()}
        onNavigateToUsage={vi.fn()}
      />,
    );
    expect(screen.getByRole('status')).toHaveTextContent(/payments are disabled/i);
    expect(screen.getByRole('button', { name: /continue to checkout|open hosted checkout/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /manage billing/i })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: /continue to checkout|open hosted checkout/i }));
    await user.click(screen.getByRole('button', { name: /manage billing/i }));
    expect(checkout).not.toHaveBeenCalled();
    expect(manage).not.toHaveBeenCalled();

    rerender(
      <BillingScreen
        client={client}
        publicPlanCode={null}
        paymentsEnabled
        onNavigateToReturn={vi.fn()}
        onNavigateToUsage={vi.fn()}
      />,
    );
    expect(screen.getByRole('status')).toHaveTextContent(/no billing plan/i);
    expect(checkout).not.toHaveBeenCalled();
    expect(manage).not.toHaveBeenCalled();
    expect(screen.queryByText(/\$|usd|price|allowance/i)).not.toBeInTheDocument();
  });

  it('reuses a 64-hex idempotency key on retry and mints a new key when the plan changes', async () => {
    const user = userEvent.setup();
    const keys: string[] = [];
    const checkout = vi.fn(async (_input: { plan_code: string }, key: string) => {
      keys.push(key);
      throw apiError({ status: 503, code: 'checkout_unavailable' });
    });
    const client = { checkout, manage: vi.fn() };
    const { rerender } = render(
      <BillingScreen
        client={client}
        publicPlanCode={PLAN}
        paymentsEnabled
        onNavigateToReturn={vi.fn()}
        onNavigateToUsage={vi.fn()}
      />,
    );

    await confirmCheckout(user);
    await waitFor(() => expect(checkout).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole('button', { name: /try billing again|try again/i }));
    await waitFor(() => expect(checkout).toHaveBeenCalledTimes(2));

    expect(keys[0]).toMatch(/^[0-9a-f]{64}$/);
    expect(keys[0]?.length).toBe(64);
    expect(keys[0]).toBe(keys[1]);
    expect(keys[0]).not.toHaveLength(36);

    rerender(
      <BillingScreen
        client={client}
        publicPlanCode="pro_monthly"
        paymentsEnabled
        onNavigateToReturn={vi.fn()}
        onNavigateToUsage={vi.fn()}
      />,
    );
    await confirmCheckout(user);
    await waitFor(() => expect(checkout).toHaveBeenCalledTimes(3));
    expect(keys[2]).toMatch(/^[0-9a-f]{64}$/);
    expect(keys[2]).not.toBe(keys[0]);
    expect(checkout.mock.calls[0]?.[0]).toEqual({ plan_code: PLAN });
    expect(checkout.mock.calls[2]?.[0]).toEqual({ plan_code: 'pro_monthly' });
  });

  it('does not duplicate create, preserves ambiguous attempts, and never grants paid from a URL', async () => {
    const user = userEvent.setup();
    hostedNavigation.open = vi.fn();
    const checkout = vi.fn(async () => PENDING_CHECKOUT);
    const onNavigateToReturn = vi.fn();
    render(
      <BillingScreen
        client={{ checkout, manage: vi.fn() }}
        publicPlanCode={PLAN}
        paymentsEnabled
        onNavigateToReturn={onNavigateToReturn}
        onNavigateToUsage={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: /continue to checkout|open hosted checkout/i }));
    const confirm = screen.getByRole('button', { name: /confirm hosted checkout|confirm checkout/i });
    await user.click(confirm);
    await user.click(confirm);
    await waitFor(() => expect(checkout).toHaveBeenCalledTimes(1));
    expect(hostedNavigation.open).toHaveBeenCalledWith(CHECKOUT_URL);
    expect(onNavigateToReturn).toHaveBeenCalledWith(ATTEMPT_ID);
    expect(screen.queryByText(/paid_active|payment granted|you are paid/i)).not.toBeInTheDocument();
  });

  it('shows typed ambiguity and does not start a second checkout automatically', async () => {
    const user = userEvent.setup();
    const checkout = vi.fn(async () => {
      throw apiError({
        status: 409,
        code: 'checkout_ambiguous',
        attemptId: ATTEMPT_ID,
      });
    });
    render(
      <BillingScreen
        client={{ checkout, manage: vi.fn() }}
        publicPlanCode={PLAN}
        paymentsEnabled
        onNavigateToReturn={vi.fn()}
        onNavigateToUsage={vi.fn()}
      />,
    );
    await confirmCheckout(user);
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/still being confirmed/i));
    expect(screen.getByRole('status')).toHaveTextContent(ATTEMPT_ID);
    expect(checkout).toHaveBeenCalledTimes(1);
  });

  it('does not treat succeeded null checkout_url as a payment grant', async () => {
    const user = userEvent.setup();
    hostedNavigation.open = vi.fn();
    const onNavigateToReturn = vi.fn();
    render(
      <BillingScreen
        client={{ checkout: vi.fn(async () => SUCCEEDED_CHECKOUT), manage: vi.fn() }}
        publicPlanCode={PLAN}
        paymentsEnabled
        onNavigateToReturn={onNavigateToReturn}
        onNavigateToUsage={vi.fn()}
      />,
    );
    await confirmCheckout(user);
    await waitFor(() => expect(onNavigateToReturn).toHaveBeenCalledWith(ATTEMPT_ID));
    expect(hostedNavigation.open).not.toHaveBeenCalled();
    expect(screen.getByRole('status')).toHaveTextContent(/backend confirmation/i);
    expect(screen.queryByText(/paid access granted/i)).not.toBeInTheDocument();
  });

  it('recovers missing customer and provider outage on manage without constructing a vendor URL', async () => {
    const user = userEvent.setup();
    hostedNavigation.open = vi.fn();
    const manage = vi.fn<PortalBillingClient['manage']>(async () => {
      throw apiError({ status: 409, code: 'billing_customer_missing' });
    });
    const { rerender } = render(
      <BillingScreen
        client={{ checkout: vi.fn(), manage }}
        publicPlanCode={PLAN}
        paymentsEnabled
        onNavigateToReturn={vi.fn()}
        onNavigateToUsage={vi.fn()}
      />,
    );
    await user.click(screen.getByRole('button', { name: /manage billing/i }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/customer .*not ready|not ready yet/i));
    expect(hostedNavigation.open).not.toHaveBeenCalled();

    manage.mockImplementationOnce(async () => {
      throw apiError({ status: 503, code: 'billing_portal_unavailable' });
    });
    rerender(
      <BillingScreen
        client={{ checkout: vi.fn(), manage }}
        publicPlanCode={PLAN}
        paymentsEnabled
        onNavigateToReturn={vi.fn()}
        onNavigateToUsage={vi.fn()}
      />,
    );
    await user.click(screen.getByRole('button', { name: /manage billing/i }));
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent(/billing portal is temporarily unavailable/i),
    );

    manage.mockImplementationOnce(async (): Promise<PortalManageResponse> => ({ portal_url: PORTAL_URL }));
    rerender(
      <BillingScreen
        client={{ checkout: vi.fn(), manage }}
        publicPlanCode={PLAN}
        paymentsEnabled
        onNavigateToReturn={vi.fn()}
        onNavigateToUsage={vi.fn()}
      />,
    );
    await user.click(screen.getByRole('button', { name: /manage billing/i }));
    await waitFor(() => expect(hostedNavigation.open).toHaveBeenCalledWith(PORTAL_URL));
  });
});

describe('BillingReturnScreen untrusted return [HAI-01][NAV-11]', () => {
  it('never grants paid from a return signal and does not POST checkout on load', async () => {
    const user = userEvent.setup();
    const checkout = vi.fn();
    const manage = vi.fn();
    const onNavigateToBilling = vi.fn();
    const onNavigateToUsage = vi.fn();
    window.history.replaceState({}, '', '/billing/return?checkout=success');

    render(
      <BillingReturnScreen
        client={{ checkout, manage }}
        publicPlanCode={PLAN}
        paymentsEnabled
        attemptId={ATTEMPT_ID}
        onNavigateToBilling={onNavigateToBilling}
        onNavigateToUsage={onNavigateToUsage}
      />,
    );

    expect(checkout).not.toHaveBeenCalled();
    expect(manage).not.toHaveBeenCalled();
    expect(screen.getByRole('status')).toHaveTextContent(/backend confirmation/i);
    expect(screen.getByRole('status')).toHaveTextContent(/pending reconciliation/i);
    expect(screen.queryByText(/paid_active|you are now paid|subscription is active/i)).not.toBeInTheDocument();
    expect(screen.getByText(ATTEMPT_ID)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /return to billing/i }));
    expect(onNavigateToBilling).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole('button', { name: /view usage|open usage/i }));
    expect(onNavigateToUsage).toHaveBeenCalledTimes(1);
  });
});
