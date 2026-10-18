/**
 * Single-sourced SPA mapping from request failures to user-visible copy (UXP-NET-2).
 * Auth expiry is distinct from generic network/HTTP errors ([FORM-05]).
 */

import { classifyError, toUserMessage } from './appError';

export { SPA_SESSION_EXPIRED_COPY } from './sessionExpiredCopy';

export const isAuthExpiredError = (error: unknown): boolean => classifyError(error)._tag === 'auth_expired';

/**
 * Map a thrown request error to user-visible text.
 * AuthExpiredError always yields the session-expired recovery message.
 * Every other error yields the caller's safe fallback — raw error messages
 * carry endpoint URLs and response bodies and must never reach the DOM.
 */
export const formatUserFacingError = (error: unknown, fallback: string): string =>
  toUserMessage(error, fallback);
