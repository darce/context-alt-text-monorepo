import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { PortalClaimApiError, PortalClaimClient } from '../api/portalClaim';
import { ClaimScreen } from '../screens/ClaimScreen';

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

describe('ADVFIX-1 PMONEY-M-2 claim retry token binding', () => {
  it.each([
    { code: 'invalid_claim_request', status: 422 },
    { code: 'portal_identity_unavailable', status: 503 },
  ] as const)('requires preview and confirmation for a replacement after $code', async ({ code, status }) => {
    const user = userEvent.setup();
    const claim = vi.fn<PortalClaimClient['claim']>();
    claim.mockRejectedValueOnce(apiError({ status, code }));
    claim.mockRejectedValueOnce(apiError({ status: 403, code: 'not_admitted' }));
    render(<ClaimScreen client={{ claim }} onClaimed={vi.fn()} />);

    const field = screen.getByLabelText(/invitation token/i);
    await user.type(field, 'confirmed-invitation');
    await user.click(screen.getByRole('button', { name: /^claim access$/i }));
    await user.click(screen.getByRole('button', { name: /confirm claim access/i }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/valid invitation|temporarily unavailable/i));
    expect(claim).toHaveBeenCalledTimes(1);

    await user.clear(field);
    await user.type(field, 'replacement-invitation');

    expect(screen.queryByRole('button', { name: /try claim again/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^claim access$/i })).toBeEnabled();
    expect(claim).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: /^claim access$/i }));
    expect(screen.getByRole('button', { name: /confirm claim access/i })).toBeInTheDocument();
    expect(claim).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: /confirm claim access/i }));
    await waitFor(() => expect(claim).toHaveBeenCalledTimes(2));
    expect(claim).toHaveBeenNthCalledWith(1, 'confirmed-invitation');
    expect(claim).toHaveBeenNthCalledWith(2, 'replacement-invitation');
  });

  it('keeps direct retry available for the unchanged confirmed token', async () => {
    const user = userEvent.setup();
    const claim = vi.fn<PortalClaimClient['claim']>();
    claim.mockRejectedValueOnce(apiError({ status: 503, code: 'portal_identity_unavailable' }));
    claim.mockRejectedValueOnce(apiError({ status: 403, code: 'not_admitted' }));
    render(<ClaimScreen client={{ claim }} onClaimed={vi.fn()} />);

    const field = screen.getByLabelText(/invitation token/i);
    await user.type(field, 'confirmed-invitation');
    await user.click(screen.getByRole('button', { name: /^claim access$/i }));
    await user.click(screen.getByRole('button', { name: /confirm claim access/i }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/temporarily unavailable/i));

    await user.click(screen.getByRole('button', { name: /try claim again/i }));
    await waitFor(() => expect(claim).toHaveBeenCalledTimes(2));
    expect(claim).toHaveBeenNthCalledWith(1, 'confirmed-invitation');
    expect(claim).toHaveBeenNthCalledWith(2, 'confirmed-invitation');
  });
});
