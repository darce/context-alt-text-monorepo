import { useEffect, useRef, useState } from 'react';
import type {
  PortalKeyApiError,
  PortalKeyClient,
  PortalKeyIssueResponse,
  PortalKeyMetadataResponse,
  PortalKeyPageResponse,
} from '../api/portalKeys';
import { OneTimeSecretDialog } from '../components/OneTimeSecretDialog';
import { StatusMessage } from '../components/StatusMessage';

export type KeysScreenProps = {
  client: PortalKeyClient;
  sessionKey: string;
  onNavigateToUsage: () => void;
  onNavigateToBilling: () => void;
  onOpenWordPressGuidance: (keyId: string) => void;
};

type KeysMode = 'loading' | 'default' | 'empty' | 'error';
type SecretState = { rawKey: string | null; replayed: boolean; returnFocusId: string } | null;
type RevokeDialog = { phase: 'preview' | 'last_usable'; keyId: string } | null;
type IdempotencySlot = { fingerprint: string; key: string };

const LIFETIME_OPTIONS = [
  { value: 3600, label: '1 hour' },
  { value: 86400, label: '1 day' },
  { value: 2592000, label: '30 days' },
  { value: 7776000, label: '90 days' },
] as const;

function newIdempotencyKey(): string {
  return `${crypto.randomUUID()}${crypto.randomUUID()}`.replaceAll('-', '');
}

function readError(error: unknown): PortalKeyApiError {
  if (error && typeof error === 'object') {
    const candidate = error as Partial<PortalKeyApiError>;
    if (typeof candidate.status === 'number') {
      return {
        status: candidate.status,
        code: typeof candidate.code === 'string' ? candidate.code : null,
        detail: typeof candidate.detail === 'string' ? candidate.detail : null,
        attemptId: typeof candidate.attemptId === 'string' ? candidate.attemptId : null,
        retryAfterSeconds: typeof candidate.retryAfterSeconds === 'number' ? candidate.retryAfterSeconds : null,
      };
    }
  }
  return { status: 0, code: null, detail: null, attemptId: null, retryAfterSeconds: null };
}

function isUncertain(error: PortalKeyApiError): boolean {
  return error.status === 0 || error.status >= 500 || error.code === 'invalid_portal_key_response';
}

function keyErrorCopy(error: PortalKeyApiError): string {
  if (error.status === 404 || error.code === 'portal key not found') {
    return 'That API key is no longer available.';
  }
  if (error.code === 'idempotency key was reused with a different request') {
    return 'This retry does not match the original request. Start a new action.';
  }
  if (error.status === 422) {
    return 'This request is not valid. Check the details and try again.';
  }
  if (error.code === 'last_usable_key_confirmation_required') {
    return 'This is the last usable key. Revoking it would stop API access until a new key is created.';
  }
  if (error.code === 'tenant key limit reached') {
    return 'A usable API key already exists. Rotate or revoke it before creating another.';
  }
  if (error.code === 'portal key is already revoked') {
    return 'This API key is already revoked.';
  }
  if (error.code === 'portal key was already rotated') {
    return 'This API key was already rotated.';
  }
  if (error.status === 409) {
    return 'This API key cannot be changed in its current state.';
  }
  return 'API key management is temporarily unavailable. Try again.';
}

function isUsable(row: PortalKeyMetadataResponse, now: number): boolean {
  if (row.revoked_at) {
    return false;
  }
  if (!row.expires_at) {
    return true;
  }
  const expiresAt = Date.parse(row.expires_at);
  return Number.isFinite(expiresAt) && expiresAt > now;
}

function rowStatus(row: PortalKeyMetadataResponse, now: number): 'revoked' | 'expired' | 'usable' {
  if (row.revoked_at) {
    return 'revoked';
  }
  if (row.expires_at) {
    const expiresAt = Date.parse(row.expires_at);
    if (Number.isFinite(expiresAt) && expiresAt <= now) {
      return 'expired';
    }
  }
  return 'usable';
}

function currentUsableKey(rows: PortalKeyMetadataResponse[], now: number): PortalKeyMetadataResponse | null {
  const usable = rows.filter((row) => isUsable(row, now));
  if (usable.length === 0) {
    return null;
  }
  return usable.reduce((latest, row) => (row.created_at > latest.created_at ? row : latest));
}

function dialogFocusables(container: HTMLElement): HTMLElement[] {
  return Array.from(
    container.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  );
}

function handleDialogKeydown(event: KeyboardEvent, container: HTMLElement, onEscape: () => void): void {
  if (event.key === 'Escape') {
    event.preventDefault();
    onEscape();
    return;
  }
  if (event.key !== 'Tab') {
    return;
  }
  const nodes = dialogFocusables(container);
  const first = nodes[0];
  const last = nodes[nodes.length - 1];
  if (!first || !last) {
    event.preventDefault();
    return;
  }
  const active = document.activeElement;
  if (event.shiftKey) {
    if (active === first || !container.contains(active)) {
      event.preventDefault();
      last.focus();
    }
    return;
  }
  if (active === last || !container.contains(active)) {
    event.preventDefault();
    first.focus();
  }
}

function KeysScreenSession({
  client,
  onNavigateToUsage,
  onNavigateToBilling,
  onOpenWordPressGuidance,
}: KeysScreenProps) {
  const [mode, setMode] = useState<KeysMode>('loading');
  const [page, setPage] = useState<PortalKeyPageResponse | null>(null);
  const [status, setStatus] = useState('Checking API keys…');
  const [statusTone, setStatusTone] = useState<'info' | 'ok' | 'error'>('info');
  const [lifetimeSeconds, setLifetimeSeconds] = useState(2592000);
  const [secret, setSecret] = useState<SecretState>(null);
  const [revokeDialog, setRevokeDialog] = useState<RevokeDialog>(null);
  const [creating, setCreating] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [createBlocked, setCreateBlocked] = useState(false);
  const createInFlightRef = useRef(false);
  const rotateInFlightRef = useRef(false);
  const revokeInFlightRef = useRef(false);
  const revokeAttemptRef = useRef(0);
  const secretHeldRef = useRef(false);
  const restoreFocusIdRef = useRef<string | null>(null);
  const revokeDialogRef = useRef<HTMLDivElement>(null);
  const createIdempotencyRef = useRef<IdempotencySlot | null>(null);
  const rotateIdempotencyRef = useRef<IdempotencySlot | null>(null);
  const now = Date.now();
  const rows = page?.data ?? [];
  const primary = currentUsableKey(rows, now);
  const modalOpen = Boolean(secret) || Boolean(revokeDialog);
  const busy = mode === 'loading' || creating || rotating || revoking;
  const actionsLocked = busy || modalOpen;
  const createLocked = actionsLocked || createBlocked;

  function idempotencyFor(slot: { current: IdempotencySlot | null }, fingerprint: string): string {
    if (slot.current && slot.current.fingerprint === fingerprint) {
      return slot.current.key;
    }
    const key = newIdempotencyKey();
    slot.current = { fingerprint, key };
    return key;
  }

  async function loadKeys(cursor?: string, append = false) {
    if (!append) {
      setMode('loading');
      setPage(null);
      setStatus('Checking API keys…');
      setStatusTone('info');
    }
    try {
      const result = await client.list(cursor ? { cursor } : undefined);
      setPage((current) => {
        if (!append || !current) {
          return result;
        }
        const seen = new Set(current.data.map((row) => row.id));
        return {
          ...result,
          data: [...current.data, ...result.data.filter((row) => !seen.has(row.id))],
        };
      });
      setMode(result.data.length === 0 && !append ? 'empty' : 'default');
      setStatus(
        result.data.length === 0 && !append
          ? 'Create an API key to get started. Metadata only; raw secrets appear once after issue.'
          : 'Metadata only; raw secrets appear once after issue.',
      );
      setStatusTone('info');
      if (!append && !currentUsableKey(result.data, Date.now())) {
        setCreateBlocked(false);
      }
    } catch (error) {
      setMode('error');
      setStatus(keyErrorCopy(readError(error)));
      setStatusTone('error');
    }
  }

  useEffect(() => {
    void loadKeys();
  }, [client]);

  useEffect(() => {
    if (secret || revokeDialog) {
      return;
    }
    const id = restoreFocusIdRef.current;
    if (!id) {
      return;
    }
    restoreFocusIdRef.current = null;
    document.getElementById(id)?.focus();
  }, [secret, revokeDialog]);

  useEffect(() => {
    if (!revokeDialog) {
      return;
    }
    const keyId = revokeDialog.keyId;
    document.getElementById('keep-key')?.focus();
    function onKeyDown(event: KeyboardEvent) {
      const container = revokeDialogRef.current;
      if (!container) {
        return;
      }
      handleDialogKeydown(event, container, () => {
        if (revokeInFlightRef.current) {
          return;
        }
        restoreFocusIdRef.current = `revoke-key-${keyId}`;
        revokeAttemptRef.current += 1;
        setRevokeDialog(null);
      });
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [revokeDialog]);

  useEffect(() => {
    if (revoking) {
      revokeDialogRef.current?.focus();
    }
  }, [revoking]);

  async function handleCreate() {
    if (createInFlightRef.current || secretHeldRef.current || revokeDialog || createBlocked) {
      return;
    }
    const fingerprint = JSON.stringify({ lifetime_seconds: lifetimeSeconds });
    const idempotencyKey = idempotencyFor(createIdempotencyRef, fingerprint);
    createInFlightRef.current = true;
    setCreating(true);
    setStatus('Creating API key…');
    setStatusTone('info');
    try {
      const issued = await client.create({ lifetime_seconds: lifetimeSeconds }, idempotencyKey);
      createIdempotencyRef.current = null;
      if (secretHeldRef.current) {
        return;
      }
      secretHeldRef.current = true;
      setSecret({ rawKey: issued.raw_key, replayed: issued.replayed, returnFocusId: 'create-key' });
      await loadKeys();
    } catch (error) {
      const parsed = readError(error);
      if (parsed.code === 'tenant key limit reached') {
        setCreateBlocked(true);
      }
      setStatus(keyErrorCopy(parsed));
      setStatusTone('error');
    } finally {
      createInFlightRef.current = false;
      setCreating(false);
    }
  }

  async function handleRotate(row: PortalKeyMetadataResponse) {
    if (rotateInFlightRef.current || secretHeldRef.current || revokeDialog) {
      return;
    }
    const fingerprint = JSON.stringify({ id: row.id });
    const idempotencyKey = idempotencyFor(rotateIdempotencyRef, fingerprint);
    rotateInFlightRef.current = true;
    setRotating(true);
    setStatus('Rotating API key…');
    setStatusTone('info');
    try {
      const issued: PortalKeyIssueResponse = await client.rotate(row.id, {}, idempotencyKey);
      rotateIdempotencyRef.current = null;
      if (secretHeldRef.current) {
        return;
      }
      secretHeldRef.current = true;
      setSecret({ rawKey: issued.raw_key, replayed: issued.replayed, returnFocusId: `rotate-key-${row.id}` });
      await loadKeys();
    } catch (error) {
      setStatus(keyErrorCopy(readError(error)));
      setStatusTone('error');
    } finally {
      rotateInFlightRef.current = false;
      setRotating(false);
    }
  }

  async function confirmRevoke() {
    if (!revokeDialog || revokeInFlightRef.current) {
      return;
    }
    const keyId = revokeDialog.keyId;
    const payload = revokeDialog.phase === 'last_usable' ? { confirm_last_usable: true } : {};
    const attempt = ++revokeAttemptRef.current;
    revokeInFlightRef.current = true;
    setRevoking(true);
    try {
      await client.revoke(keyId, payload);
      if (attempt !== revokeAttemptRef.current) {
        return;
      }
      setRevokeDialog(null);
      await loadKeys();
    } catch (error) {
      if (attempt !== revokeAttemptRef.current) {
        return;
      }
      const parsed = readError(error);
      if (parsed.code === 'last_usable_key_confirmation_required') {
        setRevokeDialog({ phase: 'last_usable', keyId });
        setStatus(keyErrorCopy(parsed));
        setStatusTone('error');
        return;
      }
      setStatus(keyErrorCopy(parsed));
      setStatusTone('error');
      setRevokeDialog(null);
      if (isUncertain(parsed)) {
        await loadKeys();
      }
    } finally {
      if (attempt === revokeAttemptRef.current) {
        revokeInFlightRef.current = false;
        setRevoking(false);
      }
    }
  }

  function cancelRevoke() {
    if (revokeInFlightRef.current) {
      return;
    }
    const keyId = revokeDialog?.keyId;
    if (keyId) {
      restoreFocusIdRef.current = `revoke-key-${keyId}`;
    }
    revokeAttemptRef.current += 1;
    setRevokeDialog(null);
  }

  async function copyIssuedSecret(value: string) {
    const clipboard = navigator.clipboard;
    if (!clipboard?.writeText) {
      throw new Error('clipboard unavailable');
    }
    await clipboard.writeText(value);
  }

  const guidanceKeyId = primary?.id ?? rows[0]?.id;

  return (
    <main className="acx-portal" aria-busy={busy}>
      <div inert={modalOpen || undefined}>
        <header className="acx-portal-header">
          <div>
            <p className="acx-lede">AltContext</p>
            <h1>API keys</h1>
          </div>
          <div className="acx-portal-actions">
            <button type="button" className="acx-btn" onClick={onNavigateToUsage} disabled={actionsLocked}>
              Usage
            </button>
            <button type="button" className="acx-btn" onClick={onNavigateToBilling} disabled={actionsLocked}>
              Billing
            </button>
          </div>
        </header>
        <div className="acx-portal-actions">
          <label htmlFor="key-lifetime">Lifetime</label>
          <select
            id="key-lifetime"
            value={String(lifetimeSeconds)}
            disabled={actionsLocked}
            onChange={(event) => setLifetimeSeconds(Number(event.target.value))}
          >
            {LIFETIME_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <button
            id="create-key"
            type="button"
            className="acx-btn acx-btn-primary"
            onClick={() => void handleCreate()}
            disabled={createLocked}
          >
            Create API key
          </button>
          {createBlocked ? (
            <>
              <span className="acx-status acx-status-error">Tenant key limit reached.</span>
              <button
                type="button"
                className="acx-btn"
                onClick={() => void loadKeys()}
                disabled={actionsLocked}
              >
                Refresh keys
              </button>
            </>
          ) : null}
        </div>
        {mode === 'loading' && !page ? <p>Loading API key metadata…</p> : null}
        {rows.length > 0 ? (
          <ul>
            {rows.map((row) => {
              const state = rowStatus(row, now);
              const canRotate = primary?.id === row.id;
              return (
                <li key={row.id}>
                  <p>
                    {row.id} created {row.created_at}
                    {row.expires_at ? ` expires ${row.expires_at}` : ''}
                    {row.revoked_at ? ` revoked ${row.revoked_at}` : ''} status: {state}
                  </p>
                  {canRotate ? (
                    <button
                      id={`rotate-key-${row.id}`}
                      type="button"
                      className="acx-btn"
                      onClick={() => void handleRotate(row)}
                      disabled={actionsLocked}
                    >
                      Rotate key
                    </button>
                  ) : null}
                  {state !== 'revoked' ? (
                    <button
                      id={`revoke-key-${row.id}`}
                      type="button"
                      className="acx-btn"
                      onClick={() => setRevokeDialog({ phase: 'preview', keyId: row.id })}
                      disabled={actionsLocked}
                    >
                      Revoke key
                    </button>
                  ) : null}
                </li>
              );
            })}
          </ul>
        ) : null}
        {page?.next_cursor ? (
          <button
            type="button"
            className="acx-btn"
            onClick={() => void loadKeys(page.next_cursor ?? undefined, true)}
            disabled={actionsLocked}
          >
            Load more keys
          </button>
        ) : null}
        {guidanceKeyId ? (
          <button
            type="button"
            className="acx-btn"
            onClick={() => onOpenWordPressGuidance(guidanceKeyId)}
            disabled={actionsLocked}
          >
            WordPress Test Connection guidance
          </button>
        ) : null}
        {secret ? null : <StatusMessage tone={statusTone}>{status}</StatusMessage>}
        {mode === 'error' ? (
          <button
            type="button"
            className="acx-btn acx-btn-primary"
            onClick={() => void loadKeys()}
            disabled={actionsLocked}
          >
            Try again
          </button>
        ) : null}
      </div>
      {revokeDialog ? (
        <div
          ref={revokeDialogRef}
          role="dialog"
          aria-modal="true"
          aria-busy={revoking}
          aria-labelledby="revoke-key-title"
          tabIndex={-1}
          className="acx-portal"
        >
          <h2 id="revoke-key-title">{revokeDialog.phase === 'last_usable' ? 'Last usable key' : 'Revoke API key'}</h2>
          <p>
            {revokeDialog.phase === 'last_usable'
              ? 'Revoking the last usable key would stop API access until a new key is created. This cannot be undone.'
              : 'Revoke this API key? This cannot be undone.'}
          </p>
          {revoking ? <p aria-live="polite">Revoking API key…</p> : null}
          <div className="acx-portal-actions">
            <button
              id="keep-key"
              type="button"
              className="acx-btn"
              onClick={cancelRevoke}
              disabled={revoking}
            >
              Keep key
            </button>
            <button
              type="button"
              className="acx-btn acx-btn-primary"
              onClick={() => void confirmRevoke()}
              disabled={revoking}
            >
              {revoking ? 'Revoking…' : 'Confirm revoke'}
            </button>
          </div>
        </div>
      ) : null}
      {secret ? (
        <OneTimeSecretDialog
          rawKey={secret.rawKey}
          replayed={secret.replayed}
          onCopy={() => copyIssuedSecret(secret.rawKey ?? '')}
          onClose={() => {
            restoreFocusIdRef.current = secret.returnFocusId;
            secretHeldRef.current = false;
            setSecret(null);
          }}
          returnFocusId={secret.returnFocusId}
        />
      ) : null}
    </main>
  );
}

export function KeysScreen(props: KeysScreenProps) {
  return <KeysScreenSession key={props.sessionKey} {...props} />;
}
