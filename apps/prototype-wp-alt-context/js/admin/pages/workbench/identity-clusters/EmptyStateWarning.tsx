import React from 'react';
import { __ } from '@wordpress/i18n';

import { QueryRetryButton } from './queryRetry';

interface EmptyStateWarningProps {
  title?: string;
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
  retrying?: boolean;
}

export const EmptyStateWarning = ({
  title = __('Results are temporarily unavailable.', 'alt-context'),
  message,
  onRetry,
  retrying = false,
}: EmptyStateWarningProps): React.JSX.Element => {
  const describedById = React.useId();
  return (
    <div className="acx-empty-state-warning" role="status" aria-live="polite">
      <span className="acx-empty-state-warning__icon" aria-hidden="true">
        !
      </span>
      <div className="acx-empty-state-warning__content">
        <p id={describedById} className="acx-empty-state-warning__title">
          {title}
        </p>
        <p className="acx-empty-state-warning__message">{message}</p>
      </div>
      {onRetry ? (
        <QueryRetryButton describedBy={describedById} retrying={retrying} onClick={onRetry} className="button" />
      ) : null}
    </div>
  );
};
