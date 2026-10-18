import { useEffect, useRef, useState } from 'react';
import { StatusMessage } from './StatusMessage';

export type OneTimeSecretDialogProps = {
  rawKey: string | null;
  replayed: boolean;
  onCopy: () => Promise<void>;
  onClose: () => void;
  returnFocusId: string;
};

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

export function OneTimeSecretDialog({ rawKey, replayed, onCopy, onClose, returnFocusId }: OneTimeSecretDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const copyRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const recoverable = Boolean(rawKey) && !replayed;

  function handleClose() {
    onClose();
    document.getElementById(returnFocusId)?.focus();
  }

  useEffect(() => {
    if (recoverable) {
      copyRef.current?.focus();
    } else {
      closeRef.current?.focus();
    }
  }, [recoverable]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const container = dialogRef.current;
      if (!container) {
        return;
      }
      handleDialogKeydown(event, container, handleClose);
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose, returnFocusId]);

  async function handleCopy() {
    try {
      await onCopy();
      setCopyState('copied');
    } catch {
      setCopyState('failed');
    }
  }

  const status = !recoverable
    ? 'This secret is no longer available. It cannot be recovered from this page.'
    : copyState === 'copied'
      ? 'Copied'
      : copyState === 'failed'
        ? 'Copy failed. You can try copying again. The secret will not be requested from the server.'
        : 'Not copied';

  return (
    <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="one-time-secret-title" className="acx-portal">
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
