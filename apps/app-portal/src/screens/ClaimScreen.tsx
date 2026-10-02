import { useEffect, useRef, useState, type FormEvent } from 'react';
import type { PortalClaimApiError, PortalClaimClient, PortalClaimResponse } from '../api/portalClaim';
import { StatusMessage, type StatusTone } from '../components/StatusMessage';

export type ClaimScreenProps = {
  client: PortalClaimClient;
  onClaimed: (response: PortalClaimResponse) => void;
};

type ClaimCopy = {
  message: string;
  tone: StatusTone;
  retry: boolean;
  fieldFocus: boolean;
};

function asClaimError(error: unknown): PortalClaimApiError {
  if (
    error &&
    typeof error === 'object' &&
    'status' in error &&
    typeof (error as { status: unknown }).status === 'number'
  ) {
    const rec = error as PortalClaimApiError;
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
    code: 'portal_identity_unavailable',
    detail: null,
    attemptId: null,
    retryAfterSeconds: null,
  };
}

function retainInvitationForTransportRetry(error: PortalClaimApiError): boolean {
  return error.code === 'portal_identity_unavailable';
}

function claimCopy(error: PortalClaimApiError): ClaimCopy {
  switch (error.code) {
    case 'email_unverified':
      return {
        message: 'Verify your email to continue. Account access is not ready yet.',
        tone: 'error',
        retry: false,
        fieldFocus: false,
      };
    case 'not_admitted':
      return {
        message: 'Your account is not ready for access yet.',
        tone: 'error',
        retry: true,
        fieldFocus: false,
      };
    case 'invitation_consumed':
      return {
        message: 'This invitation is no longer available. Contact support if you need access.',
        tone: 'error',
        retry: false,
        fieldFocus: false,
      };
    case 'identity_already_bound':
      return {
        message: 'This account is already linked. Contact support if you need help.',
        tone: 'error',
        retry: false,
        fieldFocus: false,
      };
    case 'invalid_claim_request':
      return {
        message: 'Enter a valid invitation token.',
        tone: 'error',
        retry: true,
        fieldFocus: true,
      };
    case 'csrf_origin_denied':
    case 'tenant_header_forbidden':
      return {
        message: 'This request could not be verified. Reload the page and try again.',
        tone: 'error',
        retry: true,
        fieldFocus: false,
      };
    case 'invalid_portal_authorization':
      return {
        message: 'Your sign-in session could not be verified.',
        tone: 'error',
        retry: true,
        fieldFocus: false,
      };
    case 'portal_identity_unavailable':
      return {
        message: 'Account access is temporarily unavailable. Try again.',
        tone: 'error',
        retry: true,
        fieldFocus: false,
      };
    default:
      if (error.status === 401) {
        return {
          message: 'Your sign-in session could not be verified.',
          tone: 'error',
          retry: true,
          fieldFocus: false,
        };
      }
      if (error.status === 403) {
        return {
          message: 'Your account is not ready for access yet.',
          tone: 'error',
          retry: true,
          fieldFocus: false,
        };
      }
      if (error.status === 422) {
        return {
          message: 'Enter a valid invitation token.',
          tone: 'error',
          retry: true,
          fieldFocus: true,
        };
      }
      return {
        message: 'Account access is temporarily unavailable. Try again.',
        tone: 'error',
        retry: true,
        fieldFocus: false,
      };
  }
}

export function ClaimScreen({ client, onClaimed }: ClaimScreenProps) {
  const [token, setToken] = useState('');
  const [preview, setPreview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ tone: StatusTone; message: string }>({
    tone: 'ok',
    message: 'Ready to claim',
  });
  const [retry, setRetry] = useState(false);
  const epochRef = useRef(0);
  const tokenRef = useRef<HTMLInputElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const statusRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    epochRef.current += 1;
    setToken('');
    setPreview(false);
    setBusy(false);
    setRetry(false);
    setStatus({ tone: 'ok', message: 'Ready to claim' });
  }, [client]);

  useEffect(() => {
    return () => {
      epochRef.current += 1;
    };
  }, []);

  const submitClaim = async () => {
    const epoch = epochRef.current;
    setPreview(false);
    setBusy(true);
    setRetry(false);
    setStatus({ tone: 'info', message: 'Claiming access…' });
    statusRef.current?.focus();
    try {
      const response = await client.claim(token);
      if (epoch !== epochRef.current) {
        return;
      }
      setToken('');
      setBusy(false);
      setStatus({ tone: 'ok', message: response.replayed ? 'Invitation already claimed.' : 'Invitation claimed.' });
      onClaimed(response);
    } catch (error) {
      if (epoch !== epochRef.current) {
        return;
      }
      const parsed = asClaimError(error);
      const copy = claimCopy(parsed);
      if (!retainInvitationForTransportRetry(parsed)) {
        setToken('');
      }
      setBusy(false);
      setRetry(copy.retry);
      setStatus({ tone: copy.tone, message: copy.message });
      if (copy.fieldFocus) {
        tokenRef.current?.focus();
      } else {
        statusRef.current?.focus();
      }
    }
  };

  const onPreview = (event: FormEvent) => {
    event.preventDefault();
    if (busy || !token.trim()) {
      return;
    }
    setPreview(true);
    setStatus({
      tone: 'info',
      message: 'This invitation can be used only once. Confirm to claim access.',
    });
    window.setTimeout(() => confirmRef.current?.focus(), 0);
  };

  const onCancel = () => {
    if (busy) {
      return;
    }
    setToken('');
    setPreview(false);
    setRetry(false);
    setStatus({ tone: 'ok', message: 'Ready to claim' });
    tokenRef.current?.focus();
  };

  return (
    <main className="acx-portal">
      <header>
        <p className="acx-lede">AltContext onboarding</p>
        <h1>Claim your invited account</h1>
      </header>
      <ol
        aria-label="Claim steps"
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 'var(--acx-space-lg)',
          margin: 'var(--acx-space-md) 0',
          paddingInlineStart: '1.5rem',
          fontSize: 'var(--acx-text-sm)',
        }}
      >
        <li
          aria-current={preview ? undefined : 'step'}
          style={{
            color: preview ? 'var(--acx-color-text-secondary)' : 'var(--acx-color-accent)',
            fontWeight: preview ? 'var(--acx-font-weight-normal)' : 'var(--acx-font-weight-semibold)',
          }}
        >
          Step 1 of 2: Enter invitation
        </li>
        <li
          aria-current={preview ? 'step' : undefined}
          style={{
            color: preview ? 'var(--acx-color-accent)' : 'var(--acx-color-text-secondary)',
            fontWeight: preview ? 'var(--acx-font-weight-semibold)' : 'var(--acx-font-weight-normal)',
          }}
        >
          Step 2 of 2: Confirm access
        </li>
      </ol>
      <form
        aria-label="Claim invitation"
        aria-busy={busy}
        onSubmit={preview ? (event) => event.preventDefault() : onPreview}
      >
        <div>
          <label htmlFor="acx-invitation-token">Invitation token</label>
          <input
            id="acx-invitation-token"
            ref={tokenRef}
            type="text"
            autoComplete="off"
            spellCheck={false}
            value={token}
            readOnly={busy || preview}
            onChange={(event) => setToken(event.target.value)}
          />
        </div>
        <div ref={statusRef} tabIndex={-1}>
          <StatusMessage tone={status.tone}>{status.message}</StatusMessage>
        </div>
        <div className="acx-portal-actions">
          {preview ? (
            <button
              ref={confirmRef}
              type="button"
              className="acx-btn acx-btn-primary"
              disabled={busy}
              onClick={() => {
                void submitClaim();
              }}
            >
              Confirm claim access
            </button>
          ) : (
            <button type="submit" className="acx-btn acx-btn-primary" disabled={busy || !token.trim()}>
              Claim access
            </button>
          )}
          <button type="button" className="acx-btn" disabled={busy} onClick={onCancel}>
            Cancel
          </button>
          {retry ? (
            <button
              type="button"
              className="acx-btn"
              disabled={busy || !token.trim()}
              onClick={() => {
                void submitClaim();
              }}
            >
              Try claim again
            </button>
          ) : null}
        </div>
      </form>
    </main>
  );
}
