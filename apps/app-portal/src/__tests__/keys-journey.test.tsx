import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  createPortalKeyClient,
  type PortalKeyClient,
  type PortalKeyIssueResponse,
  type PortalKeyMetadataResponse,
  type PortalKeyPageResponse,
  type RevokeKeyResponse,
} from '../api/portalKeys';
import { OneTimeSecretDialog } from '../components/OneTimeSecretDialog';
import { WordPressTestConnectionGuidance } from '../components/WordPressTestConnectionGuidance';
import { KeysScreen } from '../screens/KeysScreen';

const TENANT_A = '11111111-1111-4111-8111-111111111111';
const TENANT_B = '22222222-2222-4222-8222-222222222222';
const KEY_A = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const KEY_B = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const SECRET_A = 'acx_live_secret_session_a_once';
const SECRET_B = 'acx_live_secret_session_b_once';

type PortalRequest = (path: string, init?: RequestInit) => Promise<Response>;

function mockRequest(impl: PortalRequest) {
  return vi.fn<PortalRequest>(impl);
}

function jsonResponse(status: number, body: unknown, headers?: HeadersInit): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}

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

function renderKeys(
  client: PortalKeyClient,
  options: {
    sessionKey?: string;
    onNavigateToUsage?: () => void;
    onNavigateToBilling?: () => void;
    onOpenWordPressGuidance?: (keyId: string) => void;
  } = {},
) {
  return render(
    <KeysScreen
      client={client}
      sessionKey={options.sessionKey ?? 'sess-a'}
      onNavigateToUsage={options.onNavigateToUsage ?? vi.fn()}
      onNavigateToBilling={options.onNavigateToBilling ?? vi.fn()}
      onOpenWordPressGuidance={options.onOpenWordPressGuidance ?? vi.fn()}
    />,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('createPortalKeyClient [DATA-03][RES-01]', () => {
  it('encodes list cursor and limit and never selects a tenant', async () => {
    const request = mockRequest(async () =>
      jsonResponse(200, page([metadata()], { cursor: 'a/b+c', limit: 10, total: 1 })),
    );
    const client = createPortalKeyClient(request);
    const result = await client.list({ cursor: 'a/b+c', limit: 10 });

    expect(request).toHaveBeenCalledTimes(1);
    const [path, init] = request.mock.calls[0] ?? (['', undefined] as const);
    expect(String(path)).toBe('/portal/keys?cursor=a%2Fb%2Bc&limit=10');
    expect(init?.method ?? 'GET').toBe('GET');
    expect(JSON.stringify(init?.headers ?? {})).not.toMatch(/tenant/i);
    expect(String(path)).not.toMatch(/tenant/i);
    expect(result.data[0]?.id).toBe(KEY_A);
  });

  it('sends create body and Idempotency-Key, and treats replayed raw_key null as honest', async () => {
    const request = mockRequest(async () => jsonResponse(200, issue({ raw_key: null, replayed: true })));
    const client = createPortalKeyClient(request);
    const result = await client.create({ lifetime_seconds: 3600, rate_limit_tier: 'standard' }, 'idem-create-1');
    const [, init] = request.mock.calls[0] ?? (['', undefined] as const);
    expect(String(request.mock.calls[0]?.[0])).toBe('/portal/keys');
    expect(init?.method).toBe('POST');
    const headers = new Headers(init?.headers);
    expect(headers.get('Idempotency-Key')).toBe('idem-create-1');
    expect(headers.get('Content-Type')).toBe('application/json');
    expect(JSON.parse(String(init?.body))).toEqual({ lifetime_seconds: 3600, rate_limit_tier: 'standard' });
    expect(result.raw_key).toBeNull();
    expect(result.replayed).toBe(true);
  });

  it('posts rotate and revoke paths with UUID ids and omits emergency unless requested', async () => {
    const request = mockRequest(async (path: string) => {
      if (String(path).includes('/rotate')) {
        return jsonResponse(200, issue({ id: KEY_B, raw_key: SECRET_B, replayed: false }));
      }
      return jsonResponse(200, { id: KEY_A, tenant_id: TENANT_A, revoked: true } satisfies RevokeKeyResponse);
    });
    const client = createPortalKeyClient(request);
    await client.rotate(KEY_A, { reason: 'routine' }, 'idem-rotate-1');
    await client.revoke(KEY_A, { confirm_last_usable: true });
    expect(String(request.mock.calls[0]?.[0])).toBe(`/portal/keys/${KEY_A}/rotate`);
    expect(new Headers(request.mock.calls[0]?.[1]?.headers).get('Idempotency-Key')).toBe('idem-rotate-1');
    expect(JSON.parse(String(request.mock.calls[0]?.[1]?.body))).toEqual({ reason: 'routine' });
    expect(String(request.mock.calls[1]?.[0])).toBe(`/portal/keys/${KEY_A}/revoke`);
    expect(JSON.parse(String(request.mock.calls[1]?.[1]?.body))).toEqual({ confirm_last_usable: true });
    expect(JSON.parse(String(request.mock.calls[1]?.[1]?.body)).emergency).toBeUndefined();
  });

  it('fails closed on malformed list/issue/revoke envelopes [DATA-03]', async () => {
    const client = createPortalKeyClient(async () => jsonResponse(200, { data: [{ id: 'not-a-uuid' }] }));
    await expect(client.list()).rejects.toMatchObject({ code: 'invalid_portal_key_response' });

    const issueClient = createPortalKeyClient(async () => jsonResponse(200, { ...metadata(), raw_key: SECRET_A }));
    await expect(issueClient.create({}, 'idem')).rejects.toMatchObject({ code: 'invalid_portal_key_response' });

    const revokeClient = createPortalKeyClient(async () => jsonResponse(200, { id: KEY_A, tenant_id: TENANT_A }));
    await expect(revokeClient.revoke(KEY_A, {})).rejects.toMatchObject({ code: 'invalid_portal_key_response' });
  });

  it('maps status and error codes without exposing raw bodies', async () => {
    const request = mockRequest(async () =>
      jsonResponse(409, {
        detail: {
          code: 'last_usable_key_confirmation_required',
          detail: 'Revoking the last usable key would break API access until a new key is created.',
          confirmation_field: 'confirm_last_usable',
        },
      }),
    );
    const client = createPortalKeyClient(request);
    await expect(client.revoke(KEY_A, {})).rejects.toMatchObject({
      status: 409,
      code: 'last_usable_key_confirmation_required',
    });

    const notFound = createPortalKeyClient(async () => jsonResponse(404, { detail: 'portal key not found' }));
    await expect(notFound.rotate(KEY_A, {}, 'idem')).rejects.toMatchObject({
      status: 404,
      code: 'portal key not found',
    });

    const unavailable = createPortalKeyClient(async () =>
      jsonResponse(503, { detail: 'portal key service unavailable' }),
    );
    await expect(unavailable.list()).rejects.toMatchObject({ status: 503 });
  });
});

describe('KeysScreen list, create, rotate, and secret [NAV-11][CARD-15][RLSE-04]', () => {
  it('shows loading, empty, list, and error recovery without rendering raw exceptions', async () => {
    const user = userEvent.setup();
    const list = vi
      .fn()
      .mockRejectedValueOnce(keyError(503, { detail: 'portal key service unavailable' }))
      .mockResolvedValueOnce(page([]));
    renderKeys(mockClient({ list }));
    expect(screen.getByRole('status')).toHaveTextContent(/loading|checking/i);
    expect(screen.getByRole('main')).toHaveAttribute('aria-busy', 'true');
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/temporarily unavailable/i);
    });
    expect(screen.queryByText(/portal key service unavailable/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /try again/i }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /create api key/i })).toBeEnabled();
    });
    expect(screen.getByRole('status')).toHaveTextContent(/create/i);
  });

  it('creates with a finite lifetime, preserves idempotency on retry, and mints a new key when the request changes', async () => {
    const user = userEvent.setup();
    const create = vi
      .fn<PortalKeyClient['create']>()
      .mockRejectedValueOnce(keyError(503, { detail: 'portal key service unavailable' }))
      .mockResolvedValueOnce(issue())
      .mockResolvedValueOnce(issue({ id: KEY_B, raw_key: SECRET_B, lifetime_seconds: 86400 }));
    const client = mockClient({ list: vi.fn(async () => page([])), create });
    renderKeys(client);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /create api key/i })).toBeEnabled();
    });
    await user.selectOptions(screen.getByLabelText(/lifetime/i), '86400');
    await user.click(screen.getByRole('button', { name: /create api key/i }));
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/temporarily unavailable/i);
    });
    await user.click(screen.getByRole('button', { name: /create api key/i }));
    await waitFor(() => {
      expect(screen.getByText(SECRET_A)).toBeInTheDocument();
    });
    expect(create).toHaveBeenCalledTimes(2);
    const firstKey = create.mock.calls[0]?.[1];
    const secondKey = create.mock.calls[1]?.[1];
    expect(firstKey).toEqual(secondKey);
    expect(String(firstKey).length).toBeGreaterThanOrEqual(64);
    expect(create.mock.calls[0]?.[0]).toMatchObject({ lifetime_seconds: 86400 });

    await user.click(screen.getByRole('button', { name: /close secret/i }));
    await user.selectOptions(screen.getByLabelText(/lifetime/i), '3600');
    await user.click(screen.getByRole('button', { name: /create api key/i }));
    await waitFor(() => {
      expect(create).toHaveBeenCalledTimes(3);
    });
    expect(create.mock.calls[2]?.[1]).not.toEqual(firstKey);
    expect(create.mock.calls[2]?.[0]).toMatchObject({ lifetime_seconds: 3600 });
  });

  it('does not start a duplicate in-flight create', async () => {
    const user = userEvent.setup();
    let resolveCreate: ((value: PortalKeyIssueResponse) => void) | undefined;
    const create = vi.fn<PortalKeyClient['create']>(
      () =>
        new Promise<PortalKeyIssueResponse>((resolve) => {
          resolveCreate = resolve;
        }),
    );
    renderKeys(mockClient({ list: vi.fn(async () => page([])), create }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /create api key/i })).toBeEnabled();
    });
    await user.click(screen.getByRole('button', { name: /create api key/i }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /create api key/i })).toBeDisabled();
    });
    await user.click(screen.getByRole('button', { name: /create api key/i }));
    expect(create).toHaveBeenCalledTimes(1);
    resolveCreate?.(issue());
    await waitFor(() => {
      expect(screen.getByText(SECRET_A)).toBeInTheDocument();
    });
  });

  it('rotates only the current usable key and treats replayed raw_key null as unrecoverable', async () => {
    const user = userEvent.setup();
    const expired = metadata({
      id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
      expires_at: '2020-01-01T00:00:00Z',
      revoked_at: null,
      created_at: '2020-01-01T00:00:00Z',
    });
    const revoked = metadata({
      id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
      revoked_at: '2026-09-02T00:00:00Z',
      created_at: '2026-08-01T00:00:00Z',
    });
    const current = metadata({ id: KEY_B, created_at: '2026-09-20T00:00:00Z' });
    const rotate = vi.fn<PortalKeyClient['rotate']>(async () =>
      issue({ id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', raw_key: null, replayed: true }),
    );
    renderKeys(mockClient({ list: vi.fn(async () => page([expired, revoked, current])), rotate }));
    await waitFor(() => {
      expect(screen.getByText(/status: expired/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/status: revoked/i)).toBeInTheDocument();
    expect(screen.queryByText(/rotation history/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /rotate key/i })).toBeEnabled();
    expect(screen.getAllByRole('button', { name: /rotate key/i })).toHaveLength(1);
    await user.click(screen.getByRole('button', { name: /rotate key/i }));
    await waitFor(() => {
      expect(rotate).toHaveBeenCalledWith(KEY_B, expect.anything(), expect.any(String));
    });
    expect(screen.queryByText(/acx_live_secret/i)).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(/no longer available|cannot be recovered|not shown again/i);
    expect(screen.queryByRole('button', { name: /show secret/i })).not.toBeInTheDocument();
  });

  it('copies the one-time secret, announces copy failure with retry, and restores focus on close', async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockRejectedValueOnce(new Error('clipboard blocked')).mockResolvedValueOnce(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });
    renderKeys(mockClient({ list: vi.fn(async () => page([])), create: vi.fn(async () => issue()) }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /create api key/i })).toBeEnabled();
    });
    const createButton = screen.getByRole('button', { name: /create api key/i });
    await user.click(createButton);
    const dialog = await screen.findByRole('dialog', { name: /copy this api secret once/i });
    expect(within(dialog).getByText(SECRET_A)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: /copy secret/i }));
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/copy failed/i);
    });
    await user.click(within(dialog).getByRole('button', { name: /copy secret/i }));
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/copied/i);
    });
    expect(writeText).toHaveBeenCalledWith(SECRET_A);
    await user.click(within(dialog).getByRole('button', { name: /close secret/i }));
    await waitFor(() => {
      expect(screen.queryByText(SECRET_A)).not.toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /create api key/i })).toHaveFocus();
  });
});

describe('KeysScreen revoke warning and session isolation [CARD-15][HAI-01][DATA-03]', () => {
  it('warns on last usable key, never sends emergency, and cancel does not mutate', async () => {
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
    renderKeys(mockClient({ list: vi.fn(async () => page([metadata({ id: KEY_A })])), revoke }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /revoke key/i })).toBeEnabled();
    });
    await user.click(screen.getByRole('button', { name: /revoke key/i }));
    await user.click(screen.getByRole('button', { name: /confirm revoke/i }));
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/last usable key/i);
    });
    expect(revoke).toHaveBeenCalledTimes(1);
    expect(revoke.mock.calls[0]?.[1]).toEqual({});
    expect(screen.getByRole('button', { name: /keep key/i })).toHaveFocus();
    await user.click(screen.getByRole('button', { name: /keep key/i }));
    expect(revoke).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('button', { name: /confirm revoke/i })).not.toBeInTheDocument();
  });

  it('sends confirm_last_usable only after the last-key warning and refreshes after uncertain revoke', async () => {
    const user = userEvent.setup();
    const list = vi
      .fn()
      .mockResolvedValueOnce(page([metadata({ id: KEY_A })]))
      .mockResolvedValueOnce(page([metadata({ id: KEY_A })]))
      .mockResolvedValueOnce(page([metadata({ id: KEY_A, revoked_at: '2026-09-22T00:00:00Z' })]));
    const revoke = vi
      .fn<PortalKeyClient['revoke']>()
      .mockRejectedValueOnce(keyError(409, { detail: { code: 'last_usable_key_confirmation_required' } }))
      .mockRejectedValueOnce(keyError(503, { detail: 'portal key service unavailable' }))
      .mockResolvedValueOnce({ id: KEY_A, tenant_id: TENANT_A, revoked: true });
    renderKeys(mockClient({ list, revoke }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /revoke key/i })).toBeEnabled();
    });
    await user.click(screen.getByRole('button', { name: /revoke key/i }));
    await user.click(screen.getByRole('button', { name: /confirm revoke/i }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /confirm revoke/i })).toBeInTheDocument();
    });
    await user.click(screen.getByRole('button', { name: /confirm revoke/i }));
    await waitFor(() => {
      expect(list).toHaveBeenCalledTimes(2);
    });
    expect(revoke.mock.calls[1]?.[1]).toEqual({ confirm_last_usable: true });
    await user.click(screen.getByRole('button', { name: /revoke key/i }));
    await user.click(screen.getByRole('button', { name: /confirm revoke/i }));
    await waitFor(() => {
      expect(revoke).toHaveBeenCalledTimes(3);
    });
    expect(list.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it('never paints session A secret or metadata after a synchronous sessionKey change and ignores late A promises', async () => {
    let finishA: ((value: PortalKeyPageResponse) => void) | undefined;
    let finishSecret: ((value: PortalKeyIssueResponse) => void) | undefined;
    const clientA = mockClient({
      list: vi.fn(
        () =>
          new Promise<PortalKeyPageResponse>((resolve) => {
            finishA = resolve;
          }),
      ),
      rotate: vi.fn(
        () =>
          new Promise<PortalKeyIssueResponse>((resolve) => {
            finishSecret = resolve;
          }),
      ),
    });
    const clientB = mockClient({
      list: vi.fn(async () => page([metadata({ id: KEY_B, tenant_id: TENANT_B })])),
    });

    function Harness() {
      const [sessionKey, setSessionKey] = useState('sess-a');
      return (
        <div>
          <button type="button" onClick={() => setSessionKey('sess-b')}>
            switch-session
          </button>
          <KeysScreen
            client={sessionKey === 'sess-a' ? clientA : clientB}
            sessionKey={sessionKey}
            onNavigateToUsage={() => undefined}
            onNavigateToBilling={() => undefined}
            onOpenWordPressGuidance={() => undefined}
          />
        </div>
      );
    }

    const user = userEvent.setup();
    render(<Harness />);
    finishA?.(page([metadata({ id: KEY_A, tenant_id: TENANT_A })]));
    await waitFor(() => {
      expect(screen.getByText(new RegExp(KEY_A))).toBeInTheDocument();
    });
    await user.click(screen.getByRole('button', { name: /rotate key/i }));
    await waitFor(() => {
      expect(clientA.rotate).toHaveBeenCalled();
    });
    await user.click(screen.getByRole('button', { name: /switch-session/i }));
    expect(screen.queryByText(new RegExp(KEY_A))).not.toBeInTheDocument();
    expect(screen.queryByText(SECRET_A)).not.toBeInTheDocument();
    finishSecret?.(issue({ raw_key: SECRET_A }));
    await waitFor(() => {
      expect(screen.getByText(new RegExp(KEY_B))).toBeInTheDocument();
    });
    expect(screen.queryByText(SECRET_A)).not.toBeInTheDocument();
    expect(screen.queryByText(new RegExp(KEY_A))).not.toBeInTheDocument();
  });

  it('opens WordPress guidance without passing a secret', async () => {
    const user = userEvent.setup();
    const onOpenWordPressGuidance = vi.fn();
    renderKeys(mockClient({ list: vi.fn(async () => page([metadata()])) }), { onOpenWordPressGuidance });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /wordpress test connection guidance/i })).toBeEnabled();
    });
    await user.click(screen.getByRole('button', { name: /wordpress test connection guidance/i }));
    expect(onOpenWordPressGuidance).toHaveBeenCalledWith(KEY_A);
  });
});

describe('OneTimeSecretDialog and WordPress guidance [NAV-11][HAI-01]', () => {
  it('does not render a replayed or missing secret as recoverable', async () => {
    const onClose = vi.fn();
    render(
      <OneTimeSecretDialog
        rawKey={null}
        replayed={true}
        onCopy={async () => undefined}
        onClose={onClose}
        returnFocusId="create-key"
      />,
    );
    expect(screen.queryByText(/acx_/i)).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(/no longer available|cannot be recovered/i);
  });

  it('returns focus to the initiating control and keeps generic WordPress copy unverified', async () => {
    const user = userEvent.setup();
    const onReturnToKeys = vi.fn();
    const onClose = vi.fn();
    render(
      <div>
        <button id="create-key" type="button">
          Create API key
        </button>
        <OneTimeSecretDialog
          rawKey={SECRET_A}
          replayed={false}
          onCopy={async () => undefined}
          onClose={() => undefined}
          returnFocusId="create-key"
        />
        <WordPressTestConnectionGuidance onClose={onClose} onReturnToKeys={onReturnToKeys} />
      </div>,
    );
    await user.click(screen.getByRole('button', { name: /close secret/i }));
    expect(screen.getByRole('button', { name: /create api key/i })).toHaveFocus();
    expect(screen.getByRole('dialog', { name: /wordpress test connection/i })).toHaveTextContent(/api-key field/i);
    expect(screen.getByRole('dialog', { name: /wordpress test connection/i })).toHaveTextContent(/test connection/i);
    expect(screen.queryByText(/worked|connected successfully|verified plugin/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /back to api keys/i }));
    expect(onReturnToKeys).toHaveBeenCalledTimes(1);
  });
});
