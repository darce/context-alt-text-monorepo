import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { StatusMessage } from '../components/StatusMessage';

export function SignInScreen({ children }: { children: ReactNode }) {
  return (
    <main className="acx-portal">
      <header>
        <h1>Sign in</h1>
        <p className="acx-lede">Secure account sign-in. AltContext does not collect a password on this page.</p>
      </header>
      {children}
      <nav className="acx-escape" aria-label="Sign in escape">
        <Link className="acx-link" to="/sign-up">
          Create account
        </Link>
        <Link className="acx-link" to="/">
          Back to account
        </Link>
      </nav>
      <StatusMessage tone="info">No active session</StatusMessage>
    </main>
  );
}
