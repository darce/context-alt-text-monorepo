import { StatusMessage } from '../components/StatusMessage';

export function OutageScreen({ kind, onRetry }: { kind: 'clerk' | 'backend'; onRetry: () => void }) {
  const copy =
    kind === 'backend'
      ? 'Account access is temporarily unavailable. Try again.'
      : 'Sign-in is temporarily unavailable. Try again.';
  return (
    <main className="acx-portal">
      <header>
        <p className="acx-lede">AltContext</p>
        <h1>Account</h1>
      </header>
      <StatusMessage tone="error">{copy}</StatusMessage>
      <button type="button" className="acx-btn acx-btn-primary" onClick={onRetry}>
        Try again
      </button>
    </main>
  );
}
