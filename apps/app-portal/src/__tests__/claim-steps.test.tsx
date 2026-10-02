import { render, screen, within } from '@testing-library/react';
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
    const enterInvitation = steps.getByRole('listitem', { name: 'Step 1 of 2: Enter invitation' });
    const confirmAccess = steps.getByRole('listitem', { name: 'Step 2 of 2: Confirm access' });

    await user.type(screen.getByLabelText(/invitation token/i), INVITATION);
    expect(enterInvitation).toHaveAttribute('aria-current', 'step');
    expect(confirmAccess).not.toHaveAttribute('aria-current', 'step');

    await user.click(screen.getByRole('button', { name: /^claim access$/i }));
    expect(enterInvitation).not.toHaveAttribute('aria-current', 'step');
    expect(confirmAccess).toHaveAttribute('aria-current', 'step');
  });
});
