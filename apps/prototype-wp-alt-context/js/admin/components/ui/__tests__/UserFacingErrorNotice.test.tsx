import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AuthExpiredError } from '../../../utils/http';
import { SPA_SESSION_EXPIRED_COPY } from '../../../utils/sessionExpiredCopy';
import { UserFacingErrorNotice } from '../UserFacingErrorNotice';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

describe('UserFacingErrorNotice (SPA auth-expired surface)', () => {
  const originalSessionExpired = SPA_SESSION_EXPIRED_COPY.sessionExpired;
  const originalReloadPage = SPA_SESSION_EXPIRED_COPY.reloadPage;

  afterEach(() => {
    const mutableCopy = SPA_SESSION_EXPIRED_COPY as {
      sessionExpired: string;
      reloadPage: string;
    };
    mutableCopy.sessionExpired = originalSessionExpired;
    mutableCopy.reloadPage = originalReloadPage;
  });

  it('notice text follows SPA_SESSION_EXPIRED_COPY — a one-word constant mutation must change the DOM [E-03][TEST-15]', () => {
    const mutableCopy = SPA_SESSION_EXPIRED_COPY as {
      sessionExpired: string;
      reloadPage: string;
    };
    mutableCopy.sessionExpired = 'Your session expired — reload the page and log in again.';
    mutableCopy.reloadPage = 'Reload now';

    const error = new AuthExpiredError({ endpoint: '/acx/v1/x', status: 403 });
    render(<UserFacingErrorNotice error={error} fallback="Unable to load media details." />);

    expect(screen.getByRole('alert')).toHaveTextContent(mutableCopy.sessionExpired);
    expect(screen.getByRole('button', { name: mutableCopy.reloadPage })).toBeInTheDocument();
    expect(screen.queryByText(originalSessionExpired)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: originalReloadPage })).not.toBeInTheDocument();
  });

  it('AuthExpiredError → session-expired copy + reload, not generic [TEST-15]', () => {
    const error = new AuthExpiredError({ endpoint: '/acx/v1/x', status: 403 });
    render(<UserFacingErrorNotice error={error} fallback="Unable to load media details." />);

    expect(screen.getByTestId('acx-user-facing-error')).toHaveAttribute('data-error-kind', 'auth-expired');
    expect(screen.getByRole('alert')).toHaveTextContent(SPA_SESSION_EXPIRED_COPY.sessionExpired);
    expect(screen.queryByText('Unable to load media details.')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: SPA_SESSION_EXPIRED_COPY.reloadPage })).toBeInTheDocument();
  });

  it('generic error → fallback/message, not session-expired [TEST-15]', () => {
    render(
      <UserFacingErrorNotice
        error={new Error('Request to /wp-json/acx/v1/secret failed (500): raw body')}
        fallback="Unable to load media details."
      />,
    );

    expect(screen.getByTestId('acx-user-facing-error')).toHaveAttribute('data-error-kind', 'generic');
    // Raw error internals (endpoint, body) must never reach the DOM (UXPNET2-BR-01).
    expect(screen.getByRole('alert')).toHaveTextContent('Unable to load media details.');
    expect(screen.getByRole('alert')).not.toHaveTextContent('/wp-json/acx/v1/secret');
    expect(screen.queryByText(SPA_SESSION_EXPIRED_COPY.sessionExpired)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: SPA_SESSION_EXPIRED_COPY.reloadPage })).not.toBeInTheDocument();
  });
});
