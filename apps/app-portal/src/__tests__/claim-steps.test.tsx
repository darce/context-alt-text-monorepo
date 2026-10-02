import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { PortalClaimClient } from '../api/portalClaim';
import { ClaimScreen } from '../screens/ClaimScreen';

const INVITATION = 'raw-invitation-token-once';

describe('ClaimScreen progress indicator [NAV-09][TEST-15]', () => {
  it('marks invitation entry and confirmation as the current ordered step', async () => {
    const user = userEvent.setup();
    render(<ClaimScreen client={{ claim: vi.fn<PortalClaimClient['claim']>() }} onClaimed={vi.fn()} />);

    const steps = within(screen.getByRole('list', { name: 'Claim steps' }));
    const enterInvitation = steps.getByText('Step 1 of 2: Enter invitation').closest('li');
    const confirmAccess = steps.getByText('Step 2 of 2: Confirm access').closest('li');

    await user.type(screen.getByLabelText(/invitation token/i), INVITATION);
    expect(enterInvitation).toHaveAttribute('aria-current', 'step');
    expect(confirmAccess).not.toHaveAttribute('aria-current', 'step');

    await user.click(screen.getByRole('button', { name: /^claim access$/i }));
    expect(enterInvitation).not.toHaveAttribute('aria-current', 'step');
    expect(confirmAccess).toHaveAttribute('aria-current', 'step');
  });

  it('keeps confirmation current while the claim request is pending', async () => {
    const user = userEvent.setup();
    let rejectClaim!: (reason: unknown) => void;
    const pendingClaim = new Promise<Awaited<ReturnType<PortalClaimClient['claim']>>>((_, reject) => {
      rejectClaim = reject;
    });
    const claim = vi.fn<PortalClaimClient['claim']>().mockReturnValue(pendingClaim);
    render(<ClaimScreen client={{ claim }} onClaimed={vi.fn()} />);

    const steps = within(screen.getByRole('list', { name: 'Claim steps' }));
    const enterInvitation = steps.getByText('Step 1 of 2: Enter invitation').closest('li');
    const confirmAccess = steps.getByText('Step 2 of 2: Confirm access').closest('li');
    await user.type(screen.getByLabelText(/invitation token/i), INVITATION);
    await user.click(screen.getByRole('button', { name: /^claim access$/i }));
    await user.click(screen.getByRole('button', { name: /confirm claim access/i }));

    expect(claim).toHaveBeenCalledWith(INVITATION);
    expect(screen.getByRole('form', { name: 'Claim invitation' })).toHaveAttribute('aria-busy', 'true');
    expect(confirmAccess).toHaveAttribute('aria-current', 'step');
    expect(enterInvitation).not.toHaveAttribute('aria-current', 'step');

    await act(async () => {
      rejectClaim({ status: 503, code: 'portal_identity_unavailable' });
    });
    expect(screen.getByRole('form', { name: 'Claim invitation' })).toHaveAttribute('aria-busy', 'false');
    expect(enterInvitation).toHaveAttribute('aria-current', 'step');
    expect(confirmAccess).not.toHaveAttribute('aria-current', 'step');
  });
});
