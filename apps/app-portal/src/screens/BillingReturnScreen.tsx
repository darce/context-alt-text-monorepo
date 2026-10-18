import { useEffect } from 'react';
import type { PortalBillingClient } from '../api/portalBilling';
import { StatusMessage } from '../components/StatusMessage';

export type BillingReturnScreenProps = {
  client: PortalBillingClient;
  publicPlanCode: string | null;
  paymentsEnabled: boolean;
  attemptId: string | null;
  onNavigateToBilling: () => void;
  onNavigateToUsage: () => void;
};

export function BillingReturnScreen({
  client,
  publicPlanCode,
  paymentsEnabled,
  attemptId,
  onNavigateToBilling,
  onNavigateToUsage,
}: BillingReturnScreenProps) {
  useEffect(() => {
    void client;
  }, [client]);

  const pendingCopy = 'We received the return. Access changes only after backend confirmation. Pending reconciliation.';

  return (
    <main className="acx-portal">
      <header>
        <p className="acx-lede">Account</p>
        <h1>Billing return</h1>
      </header>
      {publicPlanCode ? <p>Plan: {publicPlanCode}</p> : null}
      {!paymentsEnabled ? <p>Payments are disabled.</p> : null}
      <StatusMessage tone="info">{pendingCopy}</StatusMessage>
      {attemptId ? (
        <p>
          Attempt <span>{attemptId}</span>
        </p>
      ) : null}
      <div className="acx-portal-actions">
        <button type="button" className="acx-btn acx-btn-primary" onClick={onNavigateToBilling}>
          Return to billing
        </button>
        <button type="button" className="acx-btn" onClick={onNavigateToUsage}>
          View usage
        </button>
      </div>
    </main>
  );
}
