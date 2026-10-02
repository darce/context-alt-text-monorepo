import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { PortalBillingApiError, PortalBillingClient, PortalCheckoutResponse } from '../api/portalBilling';
import { BillingScreen, hostedNavigation } from '../screens/BillingScreen';

const ATTEMPT_ID = '22222222-2222-4222-8222-222222222222';
const PLAN = 'starter_monthly';
const CHECKOUT_URL = 'https://pay.example.test/checkout/abc';

const PENDING_CHECKOUT: PortalCheckoutResponse = {
  attempt_id: ATTEMPT_ID,
  checkout_url: CHECKOUT_URL,
  status: 'pending',
  replayed: false,
};

const PROVIDER_REQUESTED_CHECKOUT: PortalCheckoutResponse = {
  attempt_id: ATTEMPT_ID,
  checkout_url: CHECKOUT_URL,
  status: 'provider_requested',
  replayed: false,
};

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

afterEach(() => {
  hostedNavigation.open = (url: string) => {
    window.location.assign(url);
  };
});

describe('APP1-CLAIMUI-RV02 checkout attempt_id handoff [NAV-11][RES-01][GRPH-09]', () => {
  it('hands off attempt_id before hostedNavigation.open on pending checkout', async () => {
    const user = userEvent.setup();
    const events: string[] = [];
    hostedNavigation.open = vi.fn((url: string) => {
      events.push(`hostedNavigation.open:${url}`);
    });
    const onNavigateToReturn = vi.fn((attemptId: string) => {
      events.push(`onNavigateToReturn:${attemptId}`);
    });
    const checkout = vi.fn(async () => PENDING_CHECKOUT);

    render(
      <BillingScreen
        client={{ checkout, manage: vi.fn() }}
        publicPlanCode={PLAN}
        paymentsEnabled
        onNavigateToReturn={onNavigateToReturn}
        onNavigateToUsage={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: /continue to checkout/i }));
    await user.click(screen.getByRole('button', { name: /confirm hosted checkout/i }));

    await waitFor(() => expect(hostedNavigation.open).toHaveBeenCalledWith(CHECKOUT_URL));
    expect(onNavigateToReturn).toHaveBeenCalledWith(ATTEMPT_ID);
    expect(events).toEqual([`onNavigateToReturn:${ATTEMPT_ID}`, `hostedNavigation.open:${CHECKOUT_URL}`]);
  });

  it('hands off attempt_id before hostedNavigation.open on provider_requested checkout', async () => {
    const user = userEvent.setup();
    const events: string[] = [];
    hostedNavigation.open = vi.fn((url: string) => {
      events.push(`hostedNavigation.open:${url}`);
    });
    const onNavigateToReturn = vi.fn((attemptId: string) => {
      events.push(`onNavigateToReturn:${attemptId}`);
    });

    render(
      <BillingScreen
        client={{ checkout: vi.fn(async () => PROVIDER_REQUESTED_CHECKOUT), manage: vi.fn() }}
        publicPlanCode={PLAN}
        paymentsEnabled
        onNavigateToReturn={onNavigateToReturn}
        onNavigateToUsage={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: /continue to checkout/i }));
    await user.click(screen.getByRole('button', { name: /confirm hosted checkout/i }));

    await waitFor(() => expect(hostedNavigation.open).toHaveBeenCalledWith(CHECKOUT_URL));
    expect(events).toEqual([`onNavigateToReturn:${ATTEMPT_ID}`, `hostedNavigation.open:${CHECKOUT_URL}`]);
  });
});

describe('APP1-CLAIMUI-RV03 preview retry reset [RES-01][RES-02][NAV-11]', () => {
  it('clears manage recovery intent when entering checkout preview', async () => {
    const user = userEvent.setup();
    const checkout = vi.fn(async () => PENDING_CHECKOUT);
    const manage = vi.fn(async () => {
      throw apiError({ status: 503, code: 'billing_portal_unavailable' });
    });
    hostedNavigation.open = vi.fn();

    render(
      <BillingScreen
        client={{ checkout, manage }}
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
    const retryButton = screen.getByRole('button', { name: /try billing again/i });
    expect(retryButton).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /continue to checkout/i }));
    expect(screen.getByRole('button', { name: /confirm hosted checkout/i })).toBeInTheDocument();
    expect(retryButton).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /try billing again/i })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /confirm hosted checkout/i }));
    await waitFor(() => expect(checkout).toHaveBeenCalledTimes(1));
    expect(manage).toHaveBeenCalledTimes(1);
  });

  it('clears checkout recovery intent when entering checkout preview', async () => {
    const user = userEvent.setup();
    const checkout = vi
      .fn<PortalBillingClient['checkout']>()
      .mockRejectedValueOnce(apiError({ status: 503, code: 'checkout_unavailable' }))
      .mockResolvedValueOnce(PENDING_CHECKOUT);
    hostedNavigation.open = vi.fn();

    render(
      <BillingScreen
        client={{ checkout, manage: vi.fn() }}
        publicPlanCode={PLAN}
        paymentsEnabled
        onNavigateToReturn={vi.fn()}
        onNavigateToUsage={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: /continue to checkout/i }));
    await user.click(screen.getByRole('button', { name: /confirm hosted checkout/i }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/checkout is temporarily unavailable/i));
    const retryButton = screen.getByRole('button', { name: /try billing again/i });
    expect(retryButton).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /continue to checkout/i }));
    expect(screen.getByRole('button', { name: /confirm hosted checkout/i })).toBeInTheDocument();
    expect(retryButton).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /try billing again/i })).not.toBeInTheDocument();
    expect(checkout).toHaveBeenCalledTimes(1);
  });
});
