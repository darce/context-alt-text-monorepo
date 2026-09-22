import type { ReactNode } from 'react';
import { StatusMessage } from '../components/StatusMessage';

export function OutageScreen({
  kind,
  onRetry,
  userMenu,
  onSignOut,
}: {
  kind: 'clerk' | 'backend';
  onRetry: () => void;
  userMenu?: ReactNode;
  onSignOut?: () => void;
}) {
  const copy =
    kind === 'backend'
      ? 'Account access is temporarily unavailable. Try again.'
      : 'Sign-in is temporarily unavailable. Try again.';
  const signedInChrome = userMenu != null && onSignOut != null;
  return (
    <main className="acx-portal">
      <header className={signedInChrome ? 'acx-portal-header' : undefined}>
        <div>
          <p className="acx-lede">AltContext</p>
          <h1>Account</h1>
        </div>
        {signedInChrome ? (
          <div className="acx-portal-actions">
            {userMenu}
            <button type="button" className="acx-btn" onClick={onSignOut}>
              Sign out
            </button>
          </div>
        ) : null}
      </header>
      <StatusMessage tone="error">{copy}</StatusMessage>
      <button type="button" className="acx-btn acx-btn-primary" onClick={onRetry}>
        Try again
      </button>
    </main>
  );
}
