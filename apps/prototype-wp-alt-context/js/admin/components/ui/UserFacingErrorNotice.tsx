/**
 * Workbench error surface for query/mutation failures (UXP-NET-2).
 * Auth expiry is actionable and distinct from generic errors ([FORM-05]).
 */

import * as React from 'react';
import { __ } from '@wordpress/i18n';

import { SPA_SESSION_EXPIRED_COPY } from '../../utils/sessionExpiredCopy';
import { formatUserFacingError, isAuthExpiredError } from '../../utils/userFacingError';

export interface UserFacingErrorNoticeProps {
  error: unknown;
  /** Generic fallback when error is not AuthExpiredError and has no message. */
  fallback: string;
  className?: string;
  /** A persistent parent live region can own announcement semantics. */
  announce?: boolean;
}

export const UserFacingErrorNotice: React.FC<UserFacingErrorNoticeProps> = ({
  error,
  fallback,
  className,
  announce = true,
}) => {
  const authExpired = isAuthExpiredError(error);
  // Single owner: SPA_SESSION_EXPIRED_COPY (REF-19 / E-03). __() wraps the
  // constant so runtime translation still applies without a second literal.
  const message = authExpired
    ? __(SPA_SESSION_EXPIRED_COPY.sessionExpired, 'alt-context')
    : formatUserFacingError(error, fallback);

  return (
    <div
      className={className}
      role={announce ? 'alert' : undefined}
      data-testid="acx-user-facing-error"
      data-error-kind={authExpired ? 'auth-expired' : 'generic'}
    >
      <span>{message}</span>
      {authExpired ? (
        <button type="button" onClick={() => window.location.reload()}>
          {__(SPA_SESSION_EXPIRED_COPY.reloadPage, 'alt-context')}
        </button>
      ) : null}
    </div>
  );
};

UserFacingErrorNotice.displayName = 'UserFacingErrorNotice';
