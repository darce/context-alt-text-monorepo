import { StatusMessage } from '../components/StatusMessage';

export function SignedOutScreen({
  ready,
  onSignIn,
  onSignUp,
}: {
  ready: boolean;
  onSignIn: () => void;
  onSignUp: () => void;
}) {
  return (
    <main className="acx-portal">
      <header>
        <p className="acx-lede">AltContext</p>
        <h1>Account</h1>
        <p className="acx-lede">Sign in to manage your account.</p>
      </header>
      <StatusMessage tone={ready ? 'ok' : 'info'}>{ready ? 'Ready to sign in' : 'Checking sign-in…'}</StatusMessage>
      <div className="acx-portal-actions">
        <button type="button" className="acx-btn acx-btn-primary" disabled={!ready} onClick={onSignIn}>
          Sign in
        </button>
        <button type="button" className="acx-btn" disabled={!ready} onClick={onSignUp}>
          Create account
        </button>
      </div>
    </main>
  );
}
