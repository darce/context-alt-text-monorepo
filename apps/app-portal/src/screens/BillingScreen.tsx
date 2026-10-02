import { useEffect, useRef, useState } from 'react';
import type { PortalBillingApiError, PortalBillingClient } from '../api/portalBilling';
import { StatusMessage, type StatusTone } from '../components/StatusMessage';

export type BillingScreenProps = {
  client: PortalBillingClient;
  publicPlanCode: string | null;
  paymentsEnabled: boolean;
  cancellationNotice?: { onRetry: () => void };
  onNavigateToReturn: (attemptId: string) => void;
  onNavigateToUsage: () => void;
};

export const hostedNavigation = {
  open(url: string): void {
    window.location.assign(url);
  },
};

type BillingCopy = {
  message: string;
  tone: StatusTone;
  retry: boolean;
  attemptId: string | null;
};

function createCheckoutIdempotencyKey(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

function asBillingError(error: unknown): PortalBillingApiError {
  if (
    error &&
    typeof error === 'object' &&
    'status' in error &&
    typeof (error as { status: unknown }).status === 'number'
  ) {
    const rec = error as PortalBillingApiError;
    return {
      status: rec.status,
      code: typeof rec.code === 'string' ? rec.code : null,
      detail: null,
      attemptId: typeof rec.attemptId === 'string' ? rec.attemptId : null,
      retryAfterSeconds: typeof rec.retryAfterSeconds === 'number' ? rec.retryAfterSeconds : null,
    };
  }
  return {
    status: 503,
    code: 'checkout_unavailable',
    detail: null,
    attemptId: null,
    retryAfterSeconds: null,
  };
}

function billingCopy(error: PortalBillingApiError): BillingCopy {
  const attemptId = error.attemptId;
  switch (error.code) {
    case 'payments_disabled':
      return {
        message: 'Payments are disabled.',
        tone: 'error',
        retry: false,
        attemptId,
      };
    case 'csrf_origin_denied':
      return {
        message: 'This request could not be verified. Reload the page and try again.',
        tone: 'error',
        retry: true,
        attemptId,
      };
    case 'unknown_plan_code':
      return {
        message: 'This plan is not available.',
        tone: 'error',
        retry: false,
        attemptId,
      };
    case 'invalid_return_path':
      return {
        message: 'Billing return could not be prepared. Try again.',
        tone: 'error',
        retry: true,
        attemptId,
      };
    case 'invalid_idempotency_key':
      return {
        message: 'This billing request could not be sent. Try again.',
        tone: 'error',
        retry: true,
        attemptId,
      };
    case 'idempotency_key_reuse':
      return {
        message: 'This billing request does not match a previous attempt. Start a new checkout.',
        tone: 'error',
        retry: true,
        attemptId,
      };
    case 'checkout_ambiguous':
      return {
        message: attemptId
          ? `A checkout is still being confirmed. Do not start another payment. Attempt ${attemptId}.`
          : 'A checkout is still being confirmed. Do not start another payment.',
        tone: 'error',
        retry: true,
        attemptId,
      };
    case 'already_subscribed':
      return {
        message: 'This account already has an active subscription. Check usage for current access.',
        tone: 'info',
        retry: false,
        attemptId,
      };
    case 'invalid_checkout_request':
      return {
        message: 'This checkout request is not valid. Try again.',
        tone: 'error',
        retry: true,
        attemptId,
      };
    case 'billing_customer_missing':
      return {
        message: 'Billing customer details are not ready yet. Complete checkout first, or try again later.',
        tone: 'error',
        retry: false,
        attemptId,
      };
    case 'billing_portal_unavailable':
      return {
        message: 'The billing portal is temporarily unavailable. Try again.',
        tone: 'error',
        retry: true,
        attemptId,
      };
    case 'checkout_unavailable':
      return {
        message: 'Checkout is temporarily unavailable. Try again.',
        tone: 'error',
        retry: true,
        attemptId,
      };
    default:
      return {
        message: 'Billing is temporarily unavailable. Try again.',
        tone: 'error',
        retry: true,
        attemptId,
      };
  }
}

export function BillingScreen({
  client,
  publicPlanCode,
  paymentsEnabled,
  cancellationNotice,
  onNavigateToReturn,
  onNavigateToUsage,
}: BillingScreenProps) {
  const checkoutEnabled = paymentsEnabled && Boolean(publicPlanCode);
  const [preview, setPreview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [retryKind, setRetryKind] = useState<'checkout' | 'manage' | null>(null);
  const [status, setStatus] = useState<{ tone: StatusTone; message: string }>(() =>
    !paymentsEnabled
      ? { tone: 'info', message: 'Payments are disabled.' }
      : !publicPlanCode
        ? { tone: 'info', message: 'No billing plan is available.' }
        : { tone: 'ok', message: 'Ready' },
  );
  const epochRef = useRef(0);
  const inFlightRef = useRef(false);
  const completedRef = useRef(false);
  const idempotencyRef = useRef<{ planCode: string; key: string } | null>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const statusRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    epochRef.current += 1;
    inFlightRef.current = false;
    completedRef.current = false;
    setPreview(false);
    setBusy(false);
    setRetryKind(null);
    setStatus(
      !paymentsEnabled
        ? { tone: 'info', message: 'Payments are disabled.' }
        : !publicPlanCode
          ? { tone: 'info', message: 'No billing plan is available.' }
          : { tone: 'ok', message: 'Ready' },
    );
  }, [client, publicPlanCode, paymentsEnabled]);

  useEffect(() => {
    return () => {
      epochRef.current += 1;
    };
  }, []);

  const keyFor = (planCode: string): string => {
    if (idempotencyRef.current?.planCode === planCode) {
      return idempotencyRef.current.key;
    }
    const key = createCheckoutIdempotencyKey();
    idempotencyRef.current = { planCode, key };
    return key;
  };

  const rotateKey = (planCode: string): void => {
    idempotencyRef.current = { planCode, key: createCheckoutIdempotencyKey() };
  };

  const startCheckout = async () => {
    if (!checkoutEnabled || !publicPlanCode || inFlightRef.current || completedRef.current) {
      return;
    }
    const epoch = epochRef.current;
    inFlightRef.current = true;
    setPreview(false);
    setBusy(true);
    setRetryKind(null);
    setStatus({ tone: 'info', message: 'Starting hosted checkout…' });
    statusRef.current?.focus();
    try {
      const result = await client.checkout({ plan_code: publicPlanCode }, keyFor(publicPlanCode));
      if (epoch !== epochRef.current) {
        return;
      }
      if (result.status === 'pending' || result.status === 'provider_requested') {
        completedRef.current = true;
        onNavigateToReturn(result.attempt_id);
        if (result.checkout_url) {
          hostedNavigation.open(result.checkout_url);
        }
        setBusy(false);
        setStatus({
          tone: 'info',
          message: `Checkout pending. Access changes only after backend confirmation. Attempt ${result.attempt_id}.`,
        });
        return;
      }
      if (result.status === 'succeeded') {
        completedRef.current = true;
        inFlightRef.current = false;
        setBusy(false);
        setStatus({
          tone: 'info',
          message: 'Checkout already completed. Access changes only after backend confirmation.',
        });
        onNavigateToReturn(result.attempt_id);
        return;
      }
      // Only known terminal failures permit starting a new payment attempt.
      if (result.status !== 'failed' && result.status !== 'expired' && result.status !== 'canceled') {
        inFlightRef.current = false;
        setBusy(false);
        setRetryKind('checkout');
        setStatus({
          tone: 'error',
          message: `A checkout is still being confirmed. Do not start another payment. Attempt ${result.attempt_id}.`,
        });
        return;
      }
      rotateKey(publicPlanCode);
      inFlightRef.current = false;
      setBusy(false);
      setStatus({
        tone: 'error',
        message:
          result.status === 'expired' || result.status === 'canceled'
            ? 'That checkout ended without a charge. Start a new checkout when you are ready.'
            : 'Checkout did not complete. Start a new checkout when you are ready.',
      });
    } catch (error) {
      if (epoch !== epochRef.current) {
        return;
      }
      const parsed = asBillingError(error);
      if (parsed.code === 'idempotency_key_reuse' && publicPlanCode) {
        rotateKey(publicPlanCode);
      }
      const copy = billingCopy(parsed);
      inFlightRef.current = false;
      setBusy(false);
      setRetryKind(copy.retry ? 'checkout' : null);
      setStatus({ tone: copy.tone, message: copy.message });
      statusRef.current?.focus();
    }
  };

  const startManage = async () => {
    if (!checkoutEnabled || inFlightRef.current) {
      return;
    }
    const epoch = epochRef.current;
    inFlightRef.current = true;
    setBusy(true);
    setRetryKind(null);
    setStatus({ tone: 'info', message: 'Opening billing portal…' });
    try {
      const result = await client.manage();
      if (epoch !== epochRef.current) {
        return;
      }
      hostedNavigation.open(result.portal_url);
      inFlightRef.current = false;
      setBusy(false);
    } catch (error) {
      if (epoch !== epochRef.current) {
        return;
      }
      const copy = billingCopy(asBillingError(error));
      inFlightRef.current = false;
      setBusy(false);
      setRetryKind(copy.retry ? 'manage' : null);
      setStatus({ tone: copy.tone, message: copy.message });
      statusRef.current?.focus();
    }
  };

  const onContinue = () => {
    if (!checkoutEnabled || busy || completedRef.current) {
      return;
    }
    setPreview(true);
    setRetryKind(null);
    setStatus({
      tone: 'info',
      message: 'This opens an external payment page. Access changes only after backend confirmation.',
    });
    window.setTimeout(() => confirmRef.current?.focus(), 0);
  };

  if (cancellationNotice) {
    return (
      <main className="acx-portal">
        <header>
          <p className="acx-lede">Account</p>
          <h1>Billing</h1>
        </header>
        <StatusMessage tone="info">Checkout was cancelled.</StatusMessage>
        <div className="acx-portal-actions">
          <button type="button" className="acx-btn acx-btn-primary" onClick={cancellationNotice.onRetry}>
            Try checkout again
          </button>
          <button type="button" className="acx-btn" onClick={onNavigateToUsage}>
            View usage
          </button>
        </div>
      </main>
    );
  }

  return (
    <main className="acx-portal">
      <header>
        <p className="acx-lede">Account</p>
        <h1>Billing</h1>
      </header>
      {publicPlanCode ? <p>Plan: {publicPlanCode}</p> : <p>Plan: not configured</p>}
      <div ref={statusRef} tabIndex={-1}>
        <StatusMessage tone={status.tone}>{status.message}</StatusMessage>
      </div>
      <div className="acx-portal-actions">
        {preview ? (
          <button
            ref={confirmRef}
            type="button"
            className="acx-btn acx-btn-primary"
            disabled={busy || !checkoutEnabled}
            onClick={() => {
              void startCheckout();
            }}
          >
            Confirm hosted checkout
          </button>
        ) : (
          <button
            type="button"
            className="acx-btn acx-btn-primary"
            disabled={busy || !checkoutEnabled}
            onClick={onContinue}
          >
            Continue to checkout
          </button>
        )}
        <button
          type="button"
          className="acx-btn"
          disabled={busy || !checkoutEnabled}
          onClick={() => {
            void startManage();
          }}
        >
          Manage billing
        </button>
        {retryKind ? (
          <button
            type="button"
            className="acx-btn"
            disabled={busy}
            onClick={() => {
              if (retryKind === 'manage') {
                void startManage();
              } else {
                void startCheckout();
              }
            }}
          >
            Try billing again
          </button>
        ) : null}
        <button type="button" className="acx-btn" onClick={onNavigateToUsage}>
          View usage
        </button>
      </div>
    </main>
  );
}
