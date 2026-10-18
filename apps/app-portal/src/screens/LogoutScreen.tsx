import { StatusMessage } from '../components/StatusMessage';

export function LogoutScreen({ mode, onRetry }: { mode: 'loading' | 'error'; onRetry?: () => void }) {
  const copy =
    mode === 'loading'
      ? 'Signing out… Existing API keys are unchanged.'
      : 'Sign out failed. Your account data on this page is cleared. Try again.';
  return (
    <main className="acx-portal">
      <header>
        <p className="acx-lede">AltContext</p>
        <h1>Account</h1>
      </header>
      <StatusMessage tone={mode === 'error' ? 'error' : 'info'}>{copy}</StatusMessage>
      {mode === 'error' && onRetry ? (
        <button type="button" className="acx-btn acx-btn-primary" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </main>
  );
}
