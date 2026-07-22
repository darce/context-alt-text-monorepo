/**
 * Single-sourced SPA mapping from request failures to user-visible copy (UXP-NET-2).
 * Auth expiry is distinct from generic network/HTTP errors ([FORM-05]).
 */

import { AuthExpiredError } from './http';

export const SPA_SESSION_EXPIRED_COPY = {
  sessionExpired: 'Your session expired — reload the page and sign in again.',
  reloadPage: 'Reload page',
} as const;

export const isAuthExpiredError = (error: unknown): error is AuthExpiredError =>
  error instanceof AuthExpiredError;

/**
 * Map a thrown request error to user-visible text.
 * AuthExpiredError always yields the session-expired recovery message.
 */
export const formatUserFacingError = (error: unknown, fallback: string): string => {
  if (error instanceof AuthExpiredError) {
    return SPA_SESSION_EXPIRED_COPY.sessionExpired;
  }
  if (error instanceof Error && error.message.trim() !== '') {
    return error.message;
  }
  return fallback;
};
