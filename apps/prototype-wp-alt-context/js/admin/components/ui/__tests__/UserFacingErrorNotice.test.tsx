import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AuthExpiredError } from '../../../utils/http';
import { SPA_SESSION_EXPIRED_COPY } from '../../../utils/sessionExpiredCopy';
import { UserFacingErrorNotice } from '../UserFacingErrorNotice';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

/**
 * The literals the plugin ships, pinned independently of the constant so a
 * one-word edit to sessionExpiredCopy.ts turns this file red (TEST-15/TEST-06).
 * These two lines are the only permitted second occurrence of the copy: a test
 * gate, not a production owner (REF-19).
 */
const SHIPPED_SESSION_EXPIRED = 'Your session expired — reload the page and sign in again.';
const SHIPPED_RELOAD_PAGE = 'Reload page';

describe('UserFacingErrorNotice (SPA auth-expired surface)', () => {
  const originalSessionExpired = SPA_SESSION_EXPIRED_COPY.sessionExpired;
  const originalReloadPage = SPA_SESSION_EXPIRED_COPY.reloadPage;

  const mutableCopy = (): { sessionExpired: string; reloadPage: string } =>
    SPA_SESSION_EXPIRED_COPY;

  afterEach(() => {
    mutableCopy().sessionExpired = originalSessionExpired;
    mutableCopy().reloadPage = originalReloadPage;
  });

  it('SPA_SESSION_EXPIRED_COPY holds exactly the shipped literals [E-03][TEST-15]', () => {
    expect(originalSessionExpired).toBe(SHIPPED_SESSION_EXPIRED);
    expect(originalReloadPage).toBe(SHIPPED_RELOAD_PAGE);
  });

  it('notice text follows SPA_SESSION_EXPIRED_COPY — a one-word constant mutation must change the DOM [E-03][TEST-15]', () => {
    mutableCopy().sessionExpired = 'Your session expired — reload the page and log in again.';
    mutableCopy().reloadPage = 'Reload now';

    const error = new AuthExpiredError({ endpoint: '/acx/v1/x', status: 403 });
    render(<UserFacingErrorNotice error={error} fallback="Unable to load media details." />);

    expect(screen.getByRole('alert')).toHaveTextContent(mutableCopy().sessionExpired);
    expect(screen.getByRole('button', { name: mutableCopy().reloadPage })).toBeInTheDocument();
    expect(screen.queryByText(SHIPPED_SESSION_EXPIRED)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: SHIPPED_RELOAD_PAGE })).not.toBeInTheDocument();
  });

  it('the component declares no session-expired copy of its own [E-03][REF-19]', async () => {
    const fs = await import('node:fs/promises');
    const path = await import('node:path');
    const src = await fs.readFile(
      path.join(process.cwd(), 'js/admin/components/ui/UserFacingErrorNotice.tsx'),
      'utf8',
    );

    // No second literal, and no __() re-wrap of the constant: __(SOME_CONST) is
    // invisible to gettext extraction, so wrapping here would move the string
    // that ships in the .pot file back into this file.
    expect(src).not.toContain('session expired');
    expect(src).not.toContain(SHIPPED_RELOAD_PAGE);
    expect(src).not.toMatch(/__\(/);
  });

  it('the owning copy leaf keeps both literals inside __() so gettext can extract them [E-03][REF-19]', async () => {
    const fs = await import('node:fs/promises');
    const path = await import('node:path');
    const src = await fs.readFile(path.join(process.cwd(), 'js/admin/utils/sessionExpiredCopy.ts'), 'utf8');

    expect(src).toContain(`__('${SHIPPED_SESSION_EXPIRED}', 'alt-context')`);
    expect(src).toContain(`__('${SHIPPED_RELOAD_PAGE}', 'alt-context')`);
  });

  it('AuthExpiredError → session-expired copy + reload, not generic [TEST-15]', () => {
    const error = new AuthExpiredError({ endpoint: '/acx/v1/x', status: 403 });
    render(<UserFacingErrorNotice error={error} fallback="Unable to load media details." />);

    expect(screen.getByTestId('acx-user-facing-error')).toHaveAttribute('data-error-kind', 'auth-expired');
    expect(screen.getByRole('alert')).toHaveTextContent(SHIPPED_SESSION_EXPIRED);
    expect(screen.queryByText('Unable to load media details.')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: SHIPPED_RELOAD_PAGE })).toBeInTheDocument();
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
    expect(screen.queryByText(SHIPPED_SESSION_EXPIRED)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: SHIPPED_RELOAD_PAGE })).not.toBeInTheDocument();
  });
});
