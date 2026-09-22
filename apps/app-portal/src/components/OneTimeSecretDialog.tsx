import { useEffect, useRef, useState } from 'react';
import { StatusMessage } from './StatusMessage';

export type OneTimeSecretDialogProps = {
  rawKey: string | null;
  replayed: boolean;
  onCopy: () => Promise<void>;
  onClose: () => void;
  returnFocusId: string;
};

export function OneTimeSecretDialog({ rawKey, replayed, onCopy, onClose, returnFocusId }: OneTimeSecretDialogProps) {
  const copyRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const recoverable = Boolean(rawKey) && !replayed;

  useEffect(() => {
    if (recoverable) {
      copyRef.current?.focus();
    } else {
      closeRef.current?.focus();
    }
  }, [recoverable]);

  async function handleCopy() {
    try {
      await onCopy();
      setCopyState('copied');
    } catch {
      setCopyState('failed');
    }
  }

  function handleClose() {
    onClose();
    document.getElementById(returnFocusId)?.focus();
  }

  const status = !recoverable
    ? 'This secret is no longer available. It cannot be recovered from this page.'
    : copyState === 'copied'
      ? 'Copied'
      : copyState === 'failed'
        ? 'Copy failed. You can try copying again. The secret will not be requested from the server.'
        : 'Not copied';

  return (
    <div role="dialog" aria-modal="true" aria-labelledby="one-time-secret-title" className="acx-portal">
      <h2 id="one-time-secret-title">Copy this API secret once</h2>
      <p>This secret will not be shown again.</p>
      {recoverable ? <p>{rawKey}</p> : null}
      <StatusMessage tone={copyState === 'failed' || !recoverable ? 'error' : copyState === 'copied' ? 'ok' : 'info'}>
        {status}
      </StatusMessage>
      <div className="acx-portal-actions">
        {recoverable ? (
          <button ref={copyRef} type="button" className="acx-btn acx-btn-primary" onClick={() => void handleCopy()}>
            Copy secret
          </button>
        ) : null}
        <button ref={closeRef} type="button" className="acx-btn" onClick={handleClose}>
          Close secret
        </button>
      </div>
    </div>
  );
}
