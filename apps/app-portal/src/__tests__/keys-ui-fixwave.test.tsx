import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type {
  PortalKeyClient,
  PortalKeyIssueResponse,
  PortalKeyMetadataResponse,
  PortalKeyPageResponse,
} from '../api/portalKeys';
import { OneTimeSecretDialog } from '../components/OneTimeSecretDialog';
import { KeysScreen } from '../screens/KeysScreen';

const TENANT_A = '11111111-1111-4111-8111-111111111111';
const KEY_A = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const KEY_B = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const SECRET_A = 'acx_live_secret_session_a_once';
const SECRET_B = 'acx_live_secret_session_b_once';

function metadata(overrides: Partial<PortalKeyMetadataResponse> = {}): PortalKeyMetadataResponse {
  return {
    id: KEY_A,
    tenant_id: TENANT_A,
    created_at: '2026-09-01T00:00:00Z',
    expires_at: '2026-12-01T00:00:00Z',
    revoked_at: null,
    rate_limit_tier: 'standard',
    lifetime_seconds: 3600,
    ...overrides,
  };
}

function page(
  rows: PortalKeyMetadataResponse[],
  overrides: Partial<PortalKeyPageResponse> = {},
): PortalKeyPageResponse {
  return {
    data: rows,
    next_cursor: null,
    cursor: null,
    limit: 25,
    total: rows.length,
    ...overrides,
  };
}

function issue(overrides: Partial<PortalKeyIssueResponse> = {}): PortalKeyIssueResponse {
  return {
    ...metadata(),
    raw_key: SECRET_A,
    replayed: false,
    ...overrides,
  };
}

function keyError(
  status: number,
  body: unknown,
): Error & {
  status: number;
  code: string | null;
  detail: string | null;
  attemptId: string | null;
  retryAfterSeconds: number | null;
} {
  const error = new Error('portal_key_request_failed') as Error & {
    status: number;
    code: string | null;
    detail: string | null;
    attemptId: string | null;
    retryAfterSeconds: number | null;
  };
  const record = body && typeof body === 'object' ? (body as Record<string, unknown>) : null;
  const detail = record?.detail;
  if (typeof detail === 'string') {
    error.code = detail;
    error.detail = detail;
  } else if (detail && typeof detail === 'object') {
    const nested = detail as Record<string, unknown>;
    error.code = typeof nested.code === 'string' ? nested.code : null;
    error.detail = typeof nested.detail === 'string' ? nested.detail : null;
  } else {
    error.code = null;
    error.detail = null;
  }
  error.status = status;
  error.attemptId = null;
  error.retryAfterSeconds = null;
  return error;
}

function mockClient(overrides: Partial<PortalKeyClient> = {}): PortalKeyClient {
  return {
    list: vi.fn(async () => page([])),
    create: vi.fn(async () => issue()),
    rotate: vi.fn(async () => issue({ id: KEY_B, raw_key: SECRET_B })),
    revoke: vi.fn(async () => ({ id: KEY_A, tenant_id: TENANT_A, revoked: true })),
    ...overrides,
  };
}

function renderKeys(client: PortalKeyClient) {
  return render(
    <KeysScreen
      client={client}
      sessionKey="sess-a"
      onNavigateToUsage={vi.fn()}
      onNavigateToBilling={vi.fn()}
      onOpenWordPressGuidance={vi.fn()}
    />,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('APP1-KEYS-RV01 exclusive one-time secret dialog [RLSE-04][NAV-11]', () => {
  it('disables background actions, traps focus, and never replaces an uncopied secret', async () => {
    const user = userEvent.setup();
    const list = vi
      .fn<PortalKeyClient['list']>()
      .mockResolvedValueOnce(page([]))
      .mockResolvedValue(page([metadata()]));
    const create = vi
      .fn<PortalKeyClient['create']>()
      .mockResolvedValueOnce(issue())
      .mockResolvedValueOnce(issue({ id: KEY_B, raw_key: SECRET_B }));
    const rotate = vi.fn<PortalKeyClient['rotate']>(async () => issue({ id: KEY_B, raw_key: SECRET_B }));
    renderKeys(mockClient({ list, create, rotate }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /create api key/i })).toBeEnabled();
    });
    await user.click(screen.getByRole('button', { name: /create api key/i }));
    const dialog = await screen.findByRole('dialog', { name: /copy this api secret once/i });
    expect(within(dialog).getByText(SECRET_A)).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: /copy secret/i })).toHaveFocus();

    const inertRoot = document.querySelector('[inert]');
    expect(inertRoot).not.toBeNull();
    expect(inertRoot).toContainElement(screen.getByRole('button', { name: /create api key/i }));
    expect(inertRoot).not.toContainElement(dialog);
    expect(screen.getByRole('button', { name: /create api key/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /rotate key/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /revoke key/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /^usage$/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /^billing$/i })).toBeDisabled();

    await user.tab();
    expect(within(dialog).getByRole('button', { name: /close secret/i })).toHaveFocus();
    await user.tab();
    expect(within(dialog).getByRole('button', { name: /copy secret/i })).toHaveFocus();
    await user.tab({ shift: true });
    expect(within(dialog).getByRole('button', { name: /close secret/i })).toHaveFocus();

    await user.click(screen.getByRole('button', { name: /create api key/i }));
    await user.click(screen.getByRole('button', { name: /rotate key/i }));
    expect(create).toHaveBeenCalledTimes(1);
    expect(rotate).not.toHaveBeenCalled();
    expect(screen.queryByText(SECRET_B)).not.toBeInTheDocument();
    expect(within(dialog).getByText(SECRET_A)).toBeInTheDocument();

    await user.keyboard('{Escape}');
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: /copy this api secret once/i })).not.toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /create api key/i })).toHaveFocus();
    expect(screen.getByRole('button', { name: /create api key/i })).toBeEnabled();
  });

  it('traps focus and restores it when the one-time secret dialog is used alone', async () => {
    const user = userEvent.setup();
    render(
      <div>
        <button id="create-key" type="button">
          Create API key
        </button>
        <button type="button">Outside</button>
        <OneTimeSecretDialog
          rawKey={SECRET_A}
          replayed={false}
          onCopy={async () => undefined}
          onClose={() => undefined}
          returnFocusId="create-key"
        />
      </div>,
    );
    const dialog = screen.getByRole('dialog', { name: /copy this api secret once/i });
    expect(within(dialog).getByRole('button', { name: /copy secret/i })).toHaveFocus();
    await user.tab();
    expect(within(dialog).getByRole('button', { name: /close secret/i })).toHaveFocus();
    await user.tab();
    expect(within(dialog).getByRole('button', { name: /copy secret/i })).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(screen.getByRole('button', { name: /create api key/i })).toHaveFocus();
  });
});

describe('APP1-KEYS-RV02 cancel-first revoke confirmation [NAV-11][CARD-15]', () => {
  it('focuses Keep key on preview, traps focus, Escape restores, and Enter does not confirm', async () => {
    const user = userEvent.setup();
    const revoke = vi.fn<PortalKeyClient['revoke']>();
    renderKeys(mockClient({ list: vi.fn(async () => page([metadata()])), revoke }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /revoke key/i })).toBeEnabled();
    });
    const revokeButton = screen.getByRole('button', { name: /revoke key/i });
    await user.click(revokeButton);

    const dialog = screen.getByRole('dialog', { name: /revoke api key/i });
    const keep = within(dialog).getByRole('button', { name: /keep key/i });
    const confirm = within(dialog).getByRole('button', { name: /confirm revoke/i });
    expect(keep).toHaveFocus();
    expect(document.querySelector('[inert]')).toContainElement(revokeButton);
    expect(document.querySelector('[inert]')).not.toContainElement(dialog);
    expect(screen.getByRole('button', { name: /create api key/i })).toBeDisabled();

    await user.tab();
    expect(confirm).toHaveFocus();
    await user.tab();
    expect(keep).toHaveFocus();
    await user.tab({ shift: true });
    expect(confirm).toHaveFocus();
    await user.tab({ shift: true });
    expect(keep).toHaveFocus();

    await user.keyboard('{Enter}');
    expect(revoke).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog', { name: /revoke api key/i })).not.toBeInTheDocument();
    expect(revokeButton).toHaveFocus();
  });

  it('keeps cancel-first focus on the last-usable phase and restores on Escape', async () => {
    const user = userEvent.setup();
    const revoke = vi.fn<PortalKeyClient['revoke']>(async () => {
      throw keyError(409, {
        detail: {
          code: 'last_usable_key_confirmation_required',
          detail: 'Revoking the last usable key would break API access until a new key is created.',
          confirmation_field: 'confirm_last_usable',
        },
      });
    });
    renderKeys(mockClient({ list: vi.fn(async () => page([metadata()])), revoke }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /revoke key/i })).toBeEnabled();
    });
    await user.click(screen.getByRole('button', { name: /revoke key/i }));
    await user.click(screen.getByRole('button', { name: /confirm revoke/i }));
    const dialog = await screen.findByRole('dialog', { name: /last usable key/i });
    expect(within(dialog).getByRole('button', { name: /keep key/i })).toHaveFocus();
    expect(screen.getByRole('status')).toHaveTextContent(/last usable key/i);
    expect(revoke).toHaveBeenCalledTimes(1);
    await user.keyboard('{Escape}');
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /revoke key/i })).toHaveFocus();
    expect(revoke).toHaveBeenCalledTimes(1);
  });
});

describe('APP1-KEYS-RV04 tenant key limit create latch [DATA-03][RES-01]', () => {
  it('latches Create after tenant key limit and clears it only after a successful refresh', async () => {
    const user = userEvent.setup();
    const list = vi
      .fn<PortalKeyClient['list']>()
      .mockResolvedValueOnce(page([metadata()]))
      .mockResolvedValueOnce(page([metadata({ revoked_at: '2026-09-22T00:00:00Z' })]));
    const create = vi
      .fn<PortalKeyClient['create']>()
      .mockRejectedValueOnce(keyError(409, { detail: 'tenant key limit reached' }))
      .mockResolvedValueOnce(issue({ id: KEY_B, raw_key: SECRET_B }));
    const revoke = vi.fn<PortalKeyClient['revoke']>(async () => ({
      id: KEY_A,
      tenant_id: TENANT_A,
      revoked: true,
    }));
    renderKeys(mockClient({ list, create, revoke }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /create api key/i })).toBeEnabled();
    });
    await user.click(screen.getByRole('button', { name: /create api key/i }));
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/usable api key already exists/i);
    });
    const createButton = screen.getByRole('button', { name: /create api key/i });
    expect(createButton).toBeDisabled();
    await user.click(createButton);
    expect(create).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: /revoke key/i }));
    await user.click(screen.getByRole('button', { name: /confirm revoke/i }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /create api key/i })).toBeEnabled();
    });
    await user.click(screen.getByRole('button', { name: /create api key/i }));
    await waitFor(() => {
      expect(screen.getByText(SECRET_B)).toBeInTheDocument();
    });
    expect(create).toHaveBeenCalledTimes(2);
  });

  it('latches Create when no usable key is visible on the loaded page', async () => {
    const user = userEvent.setup();
    const create = vi
      .fn<PortalKeyClient['create']>()
      .mockRejectedValueOnce(keyError(409, { detail: 'tenant key limit reached' }));
    renderKeys(
      mockClient({
        list: vi.fn(async () =>
          page([metadata({ revoked_at: '2026-09-22T00:00:00Z' })], { next_cursor: 'page-2' }),
        ),
        create,
      }),
    );

    const createButton = screen.getByRole('button', { name: /create api key/i });
    await waitFor(() => expect(createButton).toBeEnabled());
    await user.click(createButton);
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/usable api key already exists/i);
    });
    expect(createButton).toBeDisabled();
    await user.click(createButton);
    expect(create).toHaveBeenCalledTimes(1);
  });

  it('does not latch Create on a transient create failure', async () => {
    const user = userEvent.setup();
    const create = vi
      .fn<PortalKeyClient['create']>()
      .mockRejectedValueOnce(keyError(503, { detail: 'portal key service unavailable' }))
      .mockResolvedValueOnce(issue());
    renderKeys(mockClient({ list: vi.fn(async () => page([])), create }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /create api key/i })).toBeEnabled();
    });
    await user.click(screen.getByRole('button', { name: /create api key/i }));
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/temporarily unavailable/i);
    });
    expect(screen.getByRole('button', { name: /create api key/i })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: /create api key/i }));
    await waitFor(() => {
      expect(screen.getByText(SECRET_A)).toBeInTheDocument();
    });
    expect(create).toHaveBeenCalledTimes(2);
  });
});
