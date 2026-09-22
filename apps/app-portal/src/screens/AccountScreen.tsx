import type { ReactNode } from 'react';
import { StatusMessage } from '../components/StatusMessage';

export function AccountScreen({
  personName,
  tenantId,
  mode,
  userMenu,
  onSignOut,
  onRetry,
}: {
  personName: string | null;
  tenantId: string | null;
  mode: 'loading' | 'default' | 'empty' | 'error';
  userMenu: ReactNode;
  onSignOut: () => void;
  onRetry?: () => void;
}) {
  const status =
    mode === 'loading'
      ? 'Checking account…'
      : mode === 'empty'
        ? 'Account access is not linked yet.'
        : mode === 'error'
          ? 'Your sign-in session could not be verified.'
          : 'Session ready';
  return (
    <main className="acx-portal">
      <header className="acx-portal-header">
        <div>
          <p className="acx-lede">AltContext</p>
          <h1>Account</h1>
        </div>
        <div className="acx-portal-actions">
          {userMenu}
          <button type="button" className="acx-btn" onClick={onSignOut}>
            Sign out
          </button>
        </div>
      </header>
      <p className="acx-lede">{personName ? `You are signed in as ${personName}.` : 'You are signed in.'}</p>
      {tenantId ? (
        <p>
          Account access: <span>{tenantId}</span>
        </p>
      ) : (
        <p>Account access: Waiting for account</p>
      )}
      <StatusMessage tone={mode === 'error' ? 'error' : mode === 'default' ? 'ok' : 'info'}>{status}</StatusMessage>
      {mode === 'error' && onRetry ? (
        <button type="button" className="acx-btn acx-btn-primary" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </main>
  );
}
