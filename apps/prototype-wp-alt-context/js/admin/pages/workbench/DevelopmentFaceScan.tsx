import { __, _n, sprintf } from '@wordpress/i18n';

interface DevelopmentFaceScanProps {
  available: boolean;
  targetUrl: string;
  selectedCount: number;
  blockedReason: string | null;
  pending: boolean;
  message: string;
  error: string;
  onScan: () => void;
  onCancel?: () => void;
}

/** A one-shot command, never a persistent mode for the Describe button. */
export const DevelopmentFaceScan = ({
  available,
  targetUrl,
  selectedCount,
  blockedReason,
  pending,
  message,
  error,
  onScan,
  onCancel,
}: DevelopmentFaceScanProps): React.JSX.Element | null => {
  if (!available) {
    return null;
  }
  const held = pending || blockedReason !== null;
  return (
    <div className="acx-media-selection__developer-tools">
      <details>
        <summary>{__('Developer tools', 'alt-context')}</summary>
        <p>{sprintf(__('Development API: %s', 'alt-context'), targetUrl)}</p>
        <p id="acx-face-only-preview">
          {sprintf(_n('%d selected image', '%d selected images', selectedCount, 'alt-context'), selectedCount)}
          {' · '}
          {__(
            'Runs the configured FIR pipeline on the remote development CPU and updates face results. No descriptions or GPU startup.',
            'alt-context',
          )}
        </p>
        <button
          type="button"
          className="button"
          aria-disabled={held || undefined}
          aria-describedby="acx-face-only-preview acx-face-only-reason"
          onClick={() => {
            if (!held) {
              onScan();
            }
          }}
        >
          {__('Run FIR pipeline (CPU)', 'alt-context')}
        </button>
        <p id="acx-face-only-reason">{pending ? __('Face scan in progress.', 'alt-context') : blockedReason}</p>
      </details>
      <p role="status" aria-live="polite">
        {message}
      </p>
      {onCancel && (
        <button type="button" className="button button-link" onClick={onCancel}>
          {__('Cancel face scan', 'alt-context')}
        </button>
      )}
      {error && <p role="alert">{error}</p>}
    </div>
  );
};
