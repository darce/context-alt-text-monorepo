import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

export function SignUpScreen({ children }: { children: ReactNode }) {
  return (
    <main className="acx-portal">
      <header>
        <h1>Create an account</h1>
        <p className="acx-lede">
          Set up your account to continue. Creating an account does not grant workspace access.
        </p>
      </header>
      {children}
      <nav className="acx-escape" aria-label="Create account escape">
        <Link className="acx-link" to="/sign-in">
          Sign in
        </Link>
        <Link className="acx-link" to="/">
          Back to account
        </Link>
      </nav>
    </main>
  );
}
