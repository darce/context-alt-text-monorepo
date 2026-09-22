import { useEffect, useState } from 'react';
import type { PortalUsageClient, PortalUsageResponse } from '../api/portalUsage';
import { StatusMessage } from '../components/StatusMessage';

export type UsageScreenProps = {
  client: PortalUsageClient;
  sessionKey: string;
  onNavigateToKeys: () => void;
  onNavigateToBilling: () => void;
};

type UsageMode = 'loading' | 'default' | 'empty' | 'error' | 'degraded';

function formatCount(value: number | null): string {
  return value === null ? 'unknown' : String(value);
}

function statusCopy(snapshot: PortalUsageResponse | null, mode: UsageMode): string {
  if (mode === 'loading') {
    return 'Checking usage…';
  }
  if (mode === 'error') {
    return 'Usage is temporarily unavailable. Try again.';
  }
  if (!snapshot) {
    return 'Checking usage…';
  }
  if (snapshot.status === 'expired') {
    return 'This entitlement is expired. Access is closed.';
  }
  if (snapshot.status === 'revoked') {
    return 'This entitlement is revoked. Access is closed.';
  }
  if (snapshot.status === 'past_due') {
    return 'This entitlement is past due. Remaining access follows backend grace only.';
  }
  if (snapshot.remaining === 0) {
    return 'Usage is at the backend-reported cap.';
  }
  if (
    snapshot.data_source === 'pending' ||
    snapshot.used === null ||
    snapshot.reserved === null ||
    snapshot.remaining === null ||
    snapshot.allowance === null
  ) {
    return 'Usage is not available yet. Some counts are unknown.';
  }
  return `Usage status: ${snapshot.status ?? 'unknown'}.`;
}

function UsageScreenSession({ client, onNavigateToKeys, onNavigateToBilling }: UsageScreenProps) {
  const [mode, setMode] = useState<UsageMode>('loading');
  const [snapshot, setSnapshot] = useState<PortalUsageResponse | null>(null);

  async function loadUsage() {
    setMode('loading');
    setSnapshot(null);
    try {
      const result = await client.read();
      setSnapshot(result);
      if (result.status === 'expired' || result.status === 'revoked' || result.remaining === 0) {
        setMode('degraded');
      } else if (
        result.data_source === 'pending' ||
        (result.used === null && result.remaining === null && result.allowance === null && result.reserved === null)
      ) {
        setMode('empty');
      } else {
        setMode('default');
      }
    } catch {
      setSnapshot(null);
      setMode('error');
    }
  }

  useEffect(() => {
    void loadUsage();
  }, [client]);

  useEffect(() => {
    if (mode === 'error') {
      document.getElementById('retry-usage')?.focus();
    }
  }, [mode]);

  const busy = mode === 'loading';
  const tone = mode === 'error' ? 'error' : mode === 'degraded' ? 'error' : mode === 'default' ? 'ok' : 'info';

  return (
    <main className="acx-portal" aria-busy={busy}>
      <header className="acx-portal-header">
        <div>
          <p className="acx-lede">AltContext</p>
          <h1>Usage</h1>
        </div>
        <div className="acx-portal-actions">
          <button type="button" className="acx-btn" onClick={onNavigateToKeys}>
            API keys
          </button>
          <button type="button" className="acx-btn" onClick={onNavigateToBilling}>
            Billing
          </button>
        </div>
      </header>
      {snapshot && mode !== 'loading' ? (
        <section>
          <p>
            Usage period: {snapshot.period_start} — {snapshot.period_end}
          </p>
          <p>Used: {formatCount(snapshot.used)}</p>
          <p>Reserved: {formatCount(snapshot.reserved)}</p>
          <p>Remaining: {formatCount(snapshot.remaining)}</p>
          <p>Allowance: {formatCount(snapshot.allowance)}</p>
          <p>Source: {snapshot.data_source}</p>
          <p>As of: {snapshot.as_of ?? 'unavailable'}</p>
        </section>
      ) : null}
      <StatusMessage tone={tone}>{statusCopy(snapshot, mode)}</StatusMessage>
      <button
        id="retry-usage"
        type="button"
        className="acx-btn acx-btn-primary"
        onClick={() => void loadUsage()}
        disabled={busy}
      >
        Try again
      </button>
    </main>
  );
}

export function UsageScreen(props: UsageScreenProps) {
  return <UsageScreenSession key={props.sessionKey} {...props} />;
}
