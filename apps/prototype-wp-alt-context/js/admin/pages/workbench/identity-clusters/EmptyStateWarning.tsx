import React from 'react';
import { __ } from '@wordpress/i18n';

interface EmptyStateWarningProps {
  title?: string;
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
}

export const EmptyStateWarning = ({
  title = __('Results are temporarily unavailable.', 'alt-context'),
  message,
  onRetry,
  retryLabel = __('Retry', 'alt-context'),
}: EmptyStateWarningProps): React.JSX.Element => (
  <div className="acx-empty-state-warning" role="status" aria-live="polite">
    <span className="acx-empty-state-warning__icon" aria-hidden="true">
      !
    </span>
    <div className="acx-empty-state-warning__content">
      <p className="acx-empty-state-warning__title">{title}</p>
      <p className="acx-empty-state-warning__message">{message}</p>
    </div>
    {onRetry ? (
      <button type="button" className="button" onClick={onRetry}>
        {retryLabel}
      </button>
    ) : null}
  </div>
);
