import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { PortalClaimApiError, PortalClaimClient } from '../api/portalClaim';
import { ClaimScreen } from '../screens/ClaimScreen';

const INVITATION = 'raw-invitation-token-once';

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

describe('APP1-CLAIMUI-RV01 terminal invitation token lifetime [DATA-03][RES-01][RLSE-04]', () => {
  it.each([
    {
      code: 'not_admitted',
      status: 403,
      copy: /not ready/i,
      retryVisible: true,
    },
    {
      code: 'invitation_consumed',
      status: 409,
      copy: /no longer available/i,
      retryVisible: false,
    },
    {
      code: 'invalid_claim_request',
      status: 422,
      copy: /valid invitation/i,
      retryVisible: true,
    },
  ] as const)(
    'clears the raw invitation before $code recovery and requires re-entry',
    async ({ code, status, copy, retryVisible }) => {
      const user = userEvent.setup();
      const claim = vi.fn(async () => {
        throw apiError({ status, code });
      });
      render(<ClaimScreen client={{ claim }} onClaimed={vi.fn()} />);
      await confirmClaim(user);
      await user.click(screen.getByRole('button', { name: /confirm claim access/i }));

      await waitFor(() => {
        expect(screen.getByRole('status')).toHaveTextContent(copy);
      });

      const field = screen.getByLabelText(/invitation token/i);
      expect(field).toHaveValue('');
      expect(screen.queryByText(INVITATION)).not.toBeInTheDocument();
      expect(window.localStorage.length).toBe(0);
      expect(window.sessionStorage.length).toBe(0);
      expect(claim).toHaveBeenCalledTimes(1);

      if (retryVisible) {
        expect(screen.getByRole('button', { name: /try claim again/i })).toBeDisabled();
      } else {
        expect(screen.queryByRole('button', { name: /try claim again/i })).not.toBeInTheDocument();
      }

      if (code === 'invalid_claim_request') {
        expect(field).toHaveFocus();
      }

      if (retryVisible) {
        await user.type(field, 'replacement-invitation-token');
        expect(screen.queryByRole('button', { name: /try claim again/i })).not.toBeInTheDocument();
        expect(claim).toHaveBeenCalledTimes(1);

        await user.click(screen.getByRole('button', { name: /^claim access$/i }));
        expect(screen.getByRole('status')).toHaveTextContent(/this invitation can be used only once/i);
        const confirm = screen.getByRole('button', { name: /confirm claim access/i });
        expect(confirm).toBeEnabled();
        expect(claim).toHaveBeenCalledTimes(1);

        await user.click(confirm);
        await waitFor(() => expect(claim).toHaveBeenCalledTimes(2));
        expect(claim).toHaveBeenLastCalledWith('replacement-invitation-token');
      }
    },
  );

  it('keeps the invitation only for bounded portal_identity_unavailable retry [RES-02][RES-05]', async () => {
    const user = userEvent.setup();
    const claim = vi.fn(async () => {
      throw apiError({ status: 503, code: 'portal_identity_unavailable' });
    });
    render(<ClaimScreen client={{ claim }} onClaimed={vi.fn()} />);
    await confirmClaim(user);
    await user.click(screen.getByRole('button', { name: /confirm claim access/i }));

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/temporarily unavailable/i);
    });

    expect(screen.getByLabelText(/invitation token/i)).toHaveValue(INVITATION);
    const retry = screen.getByRole('button', { name: /try claim again/i });
    expect(retry).toBeEnabled();
    await user.click(retry);
    await waitFor(() => expect(claim).toHaveBeenCalledTimes(2));
    expect(claim).toHaveBeenNthCalledWith(1, INVITATION);
    expect(claim).toHaveBeenNthCalledWith(2, INVITATION);
  });

  it('maps a transport throw to identity unavailable and still retains the invitation', async () => {
    const user = userEvent.setup();
    const claim = vi.fn<PortalClaimClient['claim']>(async () => {
      throw new Error('connection reset');
    });
    render(<ClaimScreen client={{ claim }} onClaimed={vi.fn()} />);
    await confirmClaim(user);
    await user.click(screen.getByRole('button', { name: /confirm claim access/i }));

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/temporarily unavailable/i);
    });
    expect(screen.getByLabelText(/invitation token/i)).toHaveValue(INVITATION);
    expect(screen.getByRole('button', { name: /try claim again/i })).toBeEnabled();
  });
});
