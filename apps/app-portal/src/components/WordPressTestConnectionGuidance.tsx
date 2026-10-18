import { useEffect, useRef } from 'react';

export type WordPressTestConnectionGuidanceProps = {
  onClose: () => void;
  onReturnToKeys: () => void;
};

export function WordPressTestConnectionGuidance({ onClose, onReturnToKeys }: WordPressTestConnectionGuidanceProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) {
      return;
    }

    headingRef.current?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== 'Tab') {
        return;
      }

      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => !element.hasAttribute('hidden') && element.getAttribute('aria-hidden') !== 'true');
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;

      if (!first || !last) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      if (event.shiftKey && (!dialog.contains(active) || active === first || !focusable.includes(active as HTMLElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (!dialog.contains(active) || active === last)) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []);

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby="wordpress-guidance-title"
      className="acx-portal"
      tabIndex={-1}
    >
      <h2 ref={headingRef} id="wordpress-guidance-title" tabIndex={-1}>
        WordPress Test Connection guidance
      </h2>
      <ol>
        <li>Copy the secret once.</li>
        <li>Paste it into the WordPress plugin&apos;s API-key field.</li>
        <li>Run the plugin&apos;s Test Connection control.</li>
        <li>Return here to inspect, rotate, or revoke the key.</li>
      </ol>
      <p>
        Never send the secret in a URL, screenshot, log, or support ticket. Exact plugin menu labels are unverified in
        this portal and are not claimed here.
      </p>
      <div className="acx-portal-actions">
        <button type="button" className="acx-btn acx-btn-primary" onClick={onReturnToKeys}>
          Back to API keys
        </button>
        <button type="button" className="acx-btn" onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  );
}
