import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render as renderBare, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { PropsWithChildren, ReactElement } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { registerConfig, resetConfigCache, type ApiConfig } from '../../../api/config';
import { TENANT_USAGE_STATUS, type TenantUsageStatus } from '../../../api/usageApi';
import type { DescribeRunProgress } from '../../../hooks/useDescribeRunProgress';
import { BulkDescribeCta } from '../MediaSelection';
import { RECOGNITION_POLICY } from '../mediaFooterCtaState';
import { USAGE_BALANCE_STATE, UsageBalanceChip } from '../UsageBalanceChip';

const USAGE_ENDPOINT = 'https://example.test/wp-json/acx/v1/usage';
const ACCOUNT_USAGE_URL = 'https://app.altcontext.test/account/usage';

const bootstrap = (overrides: Partial<ApiConfig> = {}): void => {
  registerConfig({
    nonce: 'abcdef1234',
    ajaxUrl: '/wp-admin/admin-ajax.php',
    endpoints: { usage: USAGE_ENDPOINT },
    accountUsageUrl: ACCOUNT_USAGE_URL,
    ...overrides,
  });
};

const usageBody = (overrides: Record<string, unknown> = {}): Record<string, unknown> => ({
  tenant_id: '00000000-0000-4000-8000-000000000001',
  used: 120,
  reserved: 8,
  remaining: 372,
  allowance: 500,
  period_start: '2026-10-01T00:00:00Z',
  period_end: '2026-11-01T00:00:00Z',
  period: { start: '2026-10-01T00:00:00Z', end: '2026-11-01T00:00:00Z' },
  as_of: '2026-10-26T09:30:00Z',
  status: 'paid_active',
  data_source: 'authoritative',
  ...overrides,
});

const fetchMock = vi.fn<typeof fetch>();
const respondWith = (body: unknown, status = 200): void => {
  fetchMock.mockImplementation(() => Promise.resolve(new Response(JSON.stringify(body), { status })));
};

const render = (ui: ReactElement) =>
  renderBare(ui, {
    wrapper: ({ children }: PropsWithChildren): ReactElement => (
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        {children}
      </QueryClientProvider>
    ),
  });

const chip = (): HTMLElement => screen.getByTestId('acx-usage-balance-chip');

const settledChip = async (state: string): Promise<HTMLElement> => {
  await waitFor(() => expect(chip()).toHaveAttribute('data-state', state));
  return chip();
};

/** Every state pairs its text with an icon: state is never carried by colour alone [sr-004]. */
const expectIcon = (node: HTMLElement): void => {
  const icon = node.querySelector('svg');
  expect(icon).not.toBeNull();
  expect(icon).toHaveAttribute('aria-hidden', 'true');
};

const usageLinks = (): HTMLElement[] => screen.queryAllByRole('link', { name: /Usage & billing/ });

beforeEach(() => {
  resetConfigCache();
  bootstrap();
  vi.stubGlobal('fetch', fetchMock);
  document.documentElement.lang = 'en-US';
});

afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
  resetConfigCache();
  document.documentElement.removeAttribute('lang');
});

describe('UsageBalanceChip states', () => {
  it('shows a checking state while the read is in flight', () => {
    fetchMock.mockImplementation(() => new Promise<Response>(() => undefined));

    render(<UsageBalanceChip />);

    expect(chip()).toHaveAttribute('data-state', USAGE_BALANCE_STATE.LOADING);
    expect(chip()).toHaveTextContent('Checking balance…');
    expectIcon(chip());
  });

  it('shows remaining of allowance and the reset day for an authoritative read', async () => {
    respondWith(usageBody());

    render(<UsageBalanceChip />);

    const node = await settledChip(USAGE_BALANCE_STATE.READY);
    expect(node).toHaveTextContent('372 of 500 credits left · resets Nov 1');
    expect(node).not.toHaveTextContent(/updating/);
    expectIcon(node);
    expect(fetchMock).toHaveBeenCalledWith(USAGE_ENDPOINT, expect.objectContaining({ method: 'GET' }));
  });

  it('uses the singular form when the allowance is one credit', async () => {
    respondWith(usageBody({ remaining: 1, allowance: 1 }));

    render(<UsageBalanceChip />);

    expect(await settledChip(USAGE_BALANCE_STATE.READY)).toHaveTextContent('1 of 1 credit left · resets Nov 1');
  });

  it('marks a non-authoritative read as updating, with the same numbers', async () => {
    respondWith(usageBody({ data_source: 'cache' }));

    render(<UsageBalanceChip />);

    const node = await settledChip(USAGE_BALANCE_STATE.UPDATING);
    expect(node).toHaveTextContent('372 of 500 credits left · resets Nov 1 · updating');
    expectIcon(node);
  });

  it.each([
    ['remaining', { remaining: null }],
    ['allowance', { allowance: null }],
  ])('shows "Balance unavailable" and no digits when %s is null', async (_field, overrides) => {
    respondWith(usageBody(overrides));

    render(<UsageBalanceChip />);

    const node = await settledChip(USAGE_BALANCE_STATE.UNAVAILABLE);
    expect(node).toHaveTextContent('Balance unavailable');
    expect(node.textContent).not.toMatch(/\d/);
    expectIcon(node);
  });

  it.each<[TenantUsageStatus, string]>([
    [TENANT_USAGE_STATUS.PAST_DUE, 'Payment past due'],
    [TENANT_USAGE_STATUS.EXPIRED, 'Plan expired'],
    [TENANT_USAGE_STATUS.REVOKED, 'Access revoked'],
  ])('shows a warning for status %s', async (status, text) => {
    respondWith(usageBody({ status }));

    render(<UsageBalanceChip />);

    const node = await settledChip(USAGE_BALANCE_STATE.ACCOUNT_HOLD);
    expect(node).toHaveTextContent(text);
    expect(node.textContent).not.toMatch(/\d/);
    expectIcon(node);
  });

  it.each([
    ['a network failure', () => fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))],
    ['a 502', () => respondWith({ code: 'bad_gateway' }, 502)],
    ['a 503', () => respondWith({ code: 'usage_unavailable' }, 503)],
    ['a malformed body', () => respondWith({ ...usageBody(), balance: 372 })],
  ])('shows "Balance unavailable" without a retry control after %s', async (_label, arrange) => {
    arrange();

    render(<UsageBalanceChip />);

    const node = await settledChip(USAGE_BALANCE_STATE.UNAVAILABLE);
    expect(node).toHaveTextContent('Balance unavailable');
    expect(node.textContent).not.toMatch(/\d/);
    expectIcon(node);
    expect(within(node).queryByRole('button')).toBeNull();
  });
});

describe('UsageBalanceChip announcements [A11Y-21]', () => {
  it.each([
    [
      'the balance',
      () => new Response(JSON.stringify(usageBody()), { status: 200 }),
      USAGE_BALANCE_STATE.READY,
      '372 of 500 credits left · resets Nov 1',
    ],
    [
      'an unavailable balance',
      () => new Response(JSON.stringify({ code: 'usage_unavailable' }), { status: 503 }),
      USAGE_BALANCE_STATE.UNAVAILABLE,
      'Balance unavailable',
    ],
    [
      'an account hold',
      () => new Response(JSON.stringify(usageBody({ status: TENANT_USAGE_STATUS.PAST_DUE })), { status: 200 }),
      USAGE_BALANCE_STATE.ACCOUNT_HOLD,
      'Payment past due',
    ],
  ])(
    'keeps one polite status region from first render and announces %s when the read settles',
    async (_label, response, state, text) => {
      let settle: (value: Response) => void = () => undefined;
      const pending = new Promise<Response>((resolve) => {
        settle = resolve;
      });
      fetchMock.mockImplementation(() => pending);

      render(<UsageBalanceChip />);

      const region = within(chip()).getByRole('status');
      expect(region).toHaveAttribute('aria-live', 'polite');
      expect(region).toHaveTextContent('Checking balance…');

      settle(response());
      await settledChip(state);

      // The same node stays mounted, so the change itself is what gets announced.
      expect(within(chip()).getByRole('status')).toBe(region);
      expect(region).toHaveTextContent(text);
      expect(within(region).queryByRole('link')).toBeNull();
      expect(within(chip()).getByRole('link', { name: /Usage & billing/ })).toBeInTheDocument();
    },
  );
});

describe('UsageBalanceChip host-locale formatting [FORM-02]', () => {
  it('formats counts and the reset day in the host locale', async () => {
    document.documentElement.lang = 'de-DE';
    respondWith(usageBody({ remaining: 1234, allowance: 5000 }));

    render(<UsageBalanceChip />);

    const node = await settledChip(USAGE_BALANCE_STATE.READY);
    expect(node).toHaveTextContent('1.234 of 5.000 credits left');
    expect(node.textContent).toContain(
      new Intl.DateTimeFormat('de-DE', { month: 'short', day: 'numeric', timeZone: 'UTC' }).format(
        new Date('2026-11-01T00:00:00Z'),
      ),
    );
  });

  it.each([
    ['missing', null],
    ['unsupported', 'zz-ZZ'],
    ['malformed', 'not a locale!'],
  ])('renders neutral raw output when the host locale is %s', async (_label, lang) => {
    if (lang === null) {
      document.documentElement.removeAttribute('lang');
    } else {
      document.documentElement.lang = lang;
    }
    respondWith(usageBody({ remaining: 1234, allowance: 5000 }));

    render(<UsageBalanceChip />);

    expect(await settledChip(USAGE_BALANCE_STATE.READY)).toHaveTextContent(
      '1234 of 5000 credits left · resets 2026-11-01',
    );
  });
});

describe('UsageBalanceChip Usage & billing link [NAV-05]', () => {
  it('links to the account area in a new tab, announcing that it opens one', async () => {
    respondWith(usageBody());

    render(<UsageBalanceChip />);
    await settledChip(USAGE_BALANCE_STATE.READY);

    const [link, ...others] = usageLinks();
    expect(others).toHaveLength(0);
    expect(link).toHaveAttribute('href', ACCOUNT_USAGE_URL);
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(link).toHaveAccessibleName('Usage & billing (opens in a new tab)');
    expect(within(link).getByText('(opens in a new tab)')).toHaveClass('screen-reader-text');
  });

  it('keeps the link when the balance is unavailable', async () => {
    respondWith({ code: 'usage_unavailable' }, 503);

    render(<UsageBalanceChip />);
    await settledChip(USAGE_BALANCE_STATE.UNAVAILABLE);

    expect(usageLinks()).toHaveLength(1);
  });

  it.each([
    ['empty', { accountUsageUrl: '' }],
    ['missing', { accountUsageUrl: undefined }],
  ])('renders no link when accountUsageUrl is %s', async (_label, overrides) => {
    resetConfigCache();
    bootstrap(overrides);
    respondWith(usageBody());

    render(<UsageBalanceChip />);
    await settledChip(USAGE_BALANCE_STATE.READY);

    expect(usageLinks()).toHaveLength(0);
    expect(screen.queryByRole('link')).toBeNull();
  });
});

describe('Describe footer with the balance chip', () => {
  const idleProgress: DescribeRunProgress = {
    run: null,
    status: null,
    progressFraction: null,
    etaSeconds: null,
    isTerminal: false,
    stalledForSeconds: null,
    isPolling: false,
    isFrozen: false,
    isError: false,
    error: null,
    retry: vi.fn(),
  };

  const renderFooter = (onSubmit = vi.fn()) =>
    render(
      <BulkDescribeCta
        selectedCount={2}
        isSubmitting={false}
        isCancelling={false}
        isRunning={false}
        runId={null}
        progress={idleProgress}
        isPanelVisible={false}
        errorMessage={null}
        isIdentifying={false}
        recognitionPolicy={RECOGNITION_POLICY.ON}
        onSubmit={onSubmit}
        onCancel={vi.fn()}
        onDismiss={vi.fn()}
        onRetryPolling={vi.fn()}
      />,
    );

  it.each([
    ['a 503', () => respondWith({ code: 'usage_unavailable' }, 503)],
    ['a network failure', () => fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))],
  ])('keeps Describe enabled when the usage read fails with %s [rg-003]', async (_label, arrange) => {
    arrange();
    const onSubmit = vi.fn();

    renderFooter(onSubmit);
    await settledChip(USAGE_BALANCE_STATE.UNAVAILABLE);

    const describeButton = screen.getByRole('button', { name: 'Describe 2 selected' });
    expect(describeButton).toBeEnabled();
    expect(describeButton).not.toHaveAttribute('aria-disabled');
    await userEvent.click(describeButton);
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('sits beside the unchanged estimate line with exactly one Usage & billing link', async () => {
    respondWith(usageBody());

    renderFooter();
    await settledChip(USAGE_BALANCE_STATE.READY);

    expect(
      screen.getByText(/Identifies people first \(AI\) · Estimated description cost: ~2 credits · Turn off in/),
    ).toBeInTheDocument();
    expect(usageLinks()).toHaveLength(1);
  });

  it('does not join the Describe button description', async () => {
    respondWith(usageBody());

    renderFooter();
    await settledChip(USAGE_BALANCE_STATE.READY);

    const describedIds = (
      screen.getByRole('button', { name: 'Describe 2 selected' }).getAttribute('aria-describedby') ?? ''
    ).split(/\s+/);
    expect(describedIds.some((id) => document.getElementById(id)?.contains(chip()))).toBe(false);
  });
});
