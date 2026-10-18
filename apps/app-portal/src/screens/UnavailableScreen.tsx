import { StatusMessage } from '../components/StatusMessage';

export function UnavailableScreen({ mode }: { mode: 'error' | 'degraded' }) {
  const copy =
    mode === 'degraded'
      ? 'Account access is turned off. Contact support. Sign in is disabled.'
      : 'Account access is not configured. Sign in and Create account are not available.';
  return (
    <main className="acx-portal">
      <header>
        <p className="acx-lede">AltContext</p>
        <h1>Account</h1>
      </header>
      <StatusMessage tone="error">{copy}</StatusMessage>
    </main>
  );
}
