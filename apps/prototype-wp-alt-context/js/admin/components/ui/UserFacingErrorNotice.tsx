/**
 * Workbench error surface for query/mutation failures (UXP-NET-2).
 * Auth expiry is actionable and distinct from generic errors ([FORM-05]).
 */

import * as React from 'react';
import { __ } from '@wordpress/i18n';

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
  // Callers pass already-translated fallbacks; the session-expired constant is
  // translated here so the literal is extractable for the text domain.
  const message = authExpired
    ? __('Your session expired — reload the page and sign in again.', 'alt-context')
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
          {/* Literal (not a variable) so wp i18n string extraction sees it ([RLSE-04]). */}
          {__('Reload page', 'alt-context')}
        </button>
      ) : null}
    </div>
  );
};

UserFacingErrorNotice.displayName = 'UserFacingErrorNotice';
