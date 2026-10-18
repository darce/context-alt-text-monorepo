/**
 * Workbench error surface for query/mutation failures (UXP-NET-2).
 * Auth expiry is actionable and distinct from generic errors ([FORM-05]).
 */

import * as React from 'react';

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
  // REF-19: this component owns no copy. formatUserFacingError already maps
  // auth expiry to the session-expired string, so there is no auth branch to
  // duplicate here; `authExpired` drives affordances only (button, kind attr).
  const message = formatUserFacingError(error, fallback);

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
          {SPA_SESSION_EXPIRED_COPY.reloadPage}
        </button>
      ) : null}
    </div>
  );
};

UserFacingErrorNotice.displayName = 'UserFacingErrorNotice';
