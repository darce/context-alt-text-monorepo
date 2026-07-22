import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { AuthExpiredError } from '../../../utils/http';
import { SPA_SESSION_EXPIRED_COPY } from '../../../utils/userFacingError';
import { UserFacingErrorNotice } from '../UserFacingErrorNotice';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

describe('UserFacingErrorNotice (SPA auth-expired surface)', () => {
  it('AuthExpiredError → session-expired copy + reload, not generic [TEST-15]', () => {
    const error = new AuthExpiredError({ endpoint: '/acx/v1/x', status: 403 });
    render(<UserFacingErrorNotice error={error} fallback="Unable to load media details." />);

    expect(screen.getByTestId('acx-user-facing-error')).toHaveAttribute('data-error-kind', 'auth-expired');
    expect(screen.getByRole('alert')).toHaveTextContent(SPA_SESSION_EXPIRED_COPY.sessionExpired);
    expect(screen.queryByText('Unable to load media details.')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: SPA_SESSION_EXPIRED_COPY.reloadPage })).toBeInTheDocument();
  });

  it('generic error → fallback/message, not session-expired [TEST-15]', () => {
    render(<UserFacingErrorNotice error={new Error('boom')} fallback="Unable to load media details." />);

    expect(screen.getByTestId('acx-user-facing-error')).toHaveAttribute('data-error-kind', 'generic');
    expect(screen.getByRole('alert')).toHaveTextContent('boom');
    expect(screen.queryByText(SPA_SESSION_EXPIRED_COPY.sessionExpired)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: SPA_SESSION_EXPIRED_COPY.reloadPage })).not.toBeInTheDocument();
  });
});
