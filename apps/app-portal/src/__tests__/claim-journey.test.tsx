import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  createPortalClaimClient,
  type PortalClaimApiError,
  type PortalClaimClient,
  type PortalClaimResponse,
} from '../api/portalClaim';
import { ClaimScreen } from '../screens/ClaimScreen';

const TENANT_ID = '11111111-1111-4111-8111-111111111111';
const INVITATION = 'raw-invitation-token-once';

const FIRST_CLAIM: PortalClaimResponse = {
  tenant_id: TENANT_ID,
  issuer: 'https://clerk.altcontext.com',
  subject: 'user_1',
  email: 'ada@example.test',
  replayed: false,
};

const REPLAY_CLAIM: PortalClaimResponse = {
  ...FIRST_CLAIM,
  replayed: true,
};

function jsonResponse(status: number, body: unknown, headers?: HeadersInit): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}

function apiError(
  partial: Partial<PortalClaimApiError> & Pick<PortalClaimApiError, 'status' | 'code'>,
): PortalClaimApiError {
  return {
    detail: null,
    attemptId: null,
    retryAfterSeconds: null,
    ...partial,
  };
}

async function confirmClaim(user: ReturnType<typeof userEvent.setup>, token = INVITATION) {
  await user.type(screen.getByLabelText(/invitation token/i), token);
  await user.click(screen.getByRole('button', { name: /^claim access$/i }));
  expect(screen.getByRole('button', { name: /confirm claim access/i })).toBeInTheDocument();
}

afterEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe('createPortalClaimClient [HAI-01][DATA-03]', () => {
  it('POSTs invitation_token only and accepts 201 then 200 replay', async () => {
    const request = vi.fn(async (path: string, init?: RequestInit) => {
      expect(path).toBe('/portal/onboarding/claim');
      expect(init?.method).toBe('POST');
      const headers = new Headers(init?.headers);
      expect(headers.get('content-type')).toMatch(/application\/json/i);
      expect(headers.has('Origin')).toBe(false);
      expect(headers.has('X-Tenant-ID')).toBe(false);
      expect(headers.has('X-Tenant-Id')).toBe(false);
      expect(JSON.parse(String(init?.body))).toEqual({ invitation_token: INVITATION });
      return jsonResponse(201, FIRST_CLAIM);
    });

    const client = createPortalClaimClient(request);
    await expect(client.claim(INVITATION)).resolves.toEqual(FIRST_CLAIM);
    expect(request).toHaveBeenCalledTimes(1);

    request.mockImplementationOnce(async () => jsonResponse(200, REPLAY_CLAIM));
    await expect(client.claim(INVITATION)).resolves.toEqual(REPLAY_CLAIM);
  });

  it('maps typed claim errors and rejects malformed success JSON fail-closed', async () => {
    const client = createPortalClaimClient(async () => jsonResponse(403, { detail: { code: 'not_admitted' } }));
    await expect(client.claim(INVITATION)).rejects.toMatchObject({
      status: 403,
      code: 'not_admitted',
      detail: null,
    });

    const malformed = createPortalClaimClient(async () =>
      jsonResponse(201, {
        issuer: 'https://clerk.altcontext.com',
        subject: 'user_1',
        email: 'ada@example.test',
        replayed: false,
      }),
    );
    await expect(malformed.claim(INVITATION)).rejects.toMatchObject({
      status: 201,
      code: 'malformed_response',
    });
  });

  it('does not forge Origin and does not send a tenant selector', async () => {
    const request = vi.fn(async (_path: string, init?: RequestInit) => {
      const headers = new Headers(init?.headers);
      expect([...headers.keys()].some((key) => key.toLowerCase() === 'origin')).toBe(false);
      expect(String(init?.body)).not.toMatch(/tenant/i);
      return jsonResponse(201, FIRST_CLAIM);
    });
    await createPortalClaimClient(request).claim(INVITATION);
    expect(request).toHaveBeenCalledTimes(1);
  });
});

describe('ClaimScreen invitation claim [NAV-11][RLSE-04][HAI-01]', () => {
  it('requires preview confirmation before POST and calls onClaimed once on 201', async () => {
    const user = userEvent.setup();
    const claim = vi.fn(async (token: string) => {
      expect(token).toBe(INVITATION);
      return FIRST_CLAIM;
    });
    const onClaimed = vi.fn();
    render(<ClaimScreen client={{ claim }} onClaimed={onClaimed} />);

    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/tenant/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/email_verified/i)).not.toBeInTheDocument();

    await user.type(screen.getByLabelText(/invitation token/i), INVITATION);
    await user.click(screen.getByRole('button', { name: /^claim access$/i }));
    expect(claim).not.toHaveBeenCalled();
    expect(screen.getByRole('status')).toHaveTextContent(/once/i);

    await user.click(screen.getByRole('button', { name: /confirm claim access/i }));
    await waitFor(() => expect(onClaimed).toHaveBeenCalledTimes(1));
    expect(onClaimed).toHaveBeenCalledWith(FIRST_CLAIM);
    expect(claim).toHaveBeenCalledTimes(1);
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
    expect(screen.queryByText(INVITATION)).not.toBeInTheDocument();
  });

  it('treats 200 replayed as a valid claim and still calls onClaimed once', async () => {
    const user = userEvent.setup();
    const onClaimed = vi.fn();
    render(<ClaimScreen client={{ claim: vi.fn(async () => REPLAY_CLAIM) }} onClaimed={onClaimed} />);
    await confirmClaim(user);
    await user.click(screen.getByRole('button', { name: /confirm claim access/i }));
    await waitFor(() => expect(onClaimed).toHaveBeenCalledTimes(1));
    expect(onClaimed).toHaveBeenCalledWith(REPLAY_CLAIM);
  });

  it('keeps expired or unknown invitations non-enumerating', async () => {
    const user = userEvent.setup();
    const claim = vi.fn(async () => {
      throw apiError({ status: 403, code: 'not_admitted' });
    });
    render(<ClaimScreen client={{ claim }} onClaimed={vi.fn()} />);
    await confirmClaim(user);
    await user.click(screen.getByRole('button', { name: /confirm claim access/i }));

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/not ready/i);
    });
    expect(screen.getByRole('status')).not.toHaveTextContent(/expired/i);
    expect(screen.getByRole('status')).not.toHaveTextContent(/unknown/i);
    expect(screen.queryByText(INVITATION)).not.toBeInTheDocument();
  });

  it('maps email_unverified, consumed, bound, invalid, and 503 recovery copy', async () => {
    const user = userEvent.setup();
    const claim = vi.fn<PortalClaimClient['claim']>();
    const { rerender } = render(<ClaimScreen client={{ claim }} onClaimed={vi.fn()} />);

    const cases: Array<{ code: string; status: number; copy: RegExp; retry: boolean }> = [
      { code: 'email_unverified', status: 403, copy: /verify your email/i, retry: false },
      { code: 'invitation_consumed', status: 409, copy: /no longer available/i, retry: false },
      { code: 'identity_already_bound', status: 409, copy: /already linked/i, retry: false },
      { code: 'invalid_claim_request', status: 422, copy: /valid invitation/i, retry: true },
      { code: 'portal_identity_unavailable', status: 503, copy: /temporarily unavailable/i, retry: true },
    ];

    for (const example of cases) {
      claim.mockImplementationOnce(async () => {
        throw apiError({ status: example.status, code: example.code });
      });
      rerender(<ClaimScreen client={{ claim }} onClaimed={vi.fn()} />);
      await user.clear(screen.getByLabelText(/invitation token/i));
      await confirmClaim(user);
      await user.click(screen.getByRole('button', { name: /confirm claim access/i }));
      await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(example.copy));
      if (example.retry && example.status === 503) {
        expect(screen.getByRole('button', { name: /try claim again|try again/i })).toBeEnabled();
      }
      if (!example.retry && example.status === 409) {
        expect(screen.queryByRole('button', { name: /try claim again/i })).not.toBeInTheDocument();
      }
    }
  });

  it('clears the in-memory token on cancel and does not call onClaimed after unmount', async () => {
    const user = userEvent.setup();
    let finish!: (value: PortalClaimResponse) => void;
    const claim = vi.fn(
      () =>
        new Promise<PortalClaimResponse>((resolve) => {
          finish = resolve;
        }),
    );
    const onClaimed = vi.fn();
    const { unmount } = render(<ClaimScreen client={{ claim }} onClaimed={onClaimed} />);

    await confirmClaim(user);
    await user.click(screen.getByRole('button', { name: /^cancel$/i }));
    expect(screen.getByLabelText(/invitation token/i)).toHaveValue('');
    expect(claim).not.toHaveBeenCalled();

    await confirmClaim(user);
    await user.click(screen.getByRole('button', { name: /confirm claim access/i }));
    expect(screen.getByRole('form', { name: /claim invitation/i })).toHaveAttribute('aria-busy', 'true');

    unmount();
    await act(async () => {
      finish(FIRST_CLAIM);
    });
    expect(onClaimed).not.toHaveBeenCalled();

    let finishReplacement!: (value: PortalClaimResponse) => void;
    const firstClient = {
      claim: vi.fn(
        () =>
          new Promise<PortalClaimResponse>((resolve) => {
            finishReplacement = resolve;
          }),
      ),
    };
    const secondClient = { claim: vi.fn(async () => REPLAY_CLAIM) };
    const { rerender: rerenderClaim } = render(<ClaimScreen client={firstClient} onClaimed={onClaimed} />);
    await confirmClaim(user);
    await user.click(screen.getByRole('button', { name: /confirm claim access/i }));
    rerenderClaim(<ClaimScreen client={secondClient} onClaimed={onClaimed} />);
    await act(async () => {
      finishReplacement(FIRST_CLAIM);
    });
    expect(onClaimed).not.toHaveBeenCalled();
  });

  it('keeps token field focus after 422 and does not render raw exception bodies', async () => {
    const user = userEvent.setup();
    const claim = vi.fn(async () => {
      throw apiError({
        status: 422,
        code: 'invalid_claim_request',
        detail: 'super-secret-stack-trace',
      });
    });
    render(<ClaimScreen client={{ claim }} onClaimed={vi.fn()} />);
    await confirmClaim(user);
    await user.click(screen.getByRole('button', { name: /confirm claim access/i }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/valid invitation/i));
    expect(screen.getByLabelText(/invitation token/i)).toHaveFocus();
    expect(screen.queryByText(/super-secret-stack-trace/i)).not.toBeInTheDocument();
  });
});
