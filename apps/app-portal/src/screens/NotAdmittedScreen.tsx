import type { ReactNode } from 'react';
import { StatusMessage } from '../components/StatusMessage';

export function NotAdmittedScreen({
  reason,
  userMenu,
  onSignOut,
}: {
  reason: 'email_unverified' | 'not_admitted';
  userMenu: ReactNode;
  onSignOut: () => void;
}) {
  const copy =
    reason === 'email_unverified'
      ? 'Verify your email to continue. Account access is not ready yet.'
      : 'Your account is not ready for access yet.';
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
      <StatusMessage tone="error">{copy}</StatusMessage>
    </main>
  );
}
