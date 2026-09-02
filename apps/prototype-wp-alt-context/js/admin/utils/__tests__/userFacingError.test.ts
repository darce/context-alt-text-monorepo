import { describe, expect, it, vi } from 'vitest';

import { AuthExpiredError } from '../http';
import {
  formatUserFacingError,
  isAuthExpiredError,
  SPA_SESSION_EXPIRED_COPY,
} from '../userFacingError';
import { getClusterMutationErrorMessage } from '../../pages/workbench/identity-clusters/clusterMutationUtils';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (text: string, ...values: (string | number)[]) => {
    let index = 0;
    return text.replace(/%[sd]/g, () => String(values[index++] ?? ''));
  },
}));

describe('formatUserFacingError / getClusterMutationErrorMessage', () => {
  it('maps AuthExpiredError to session-expired copy (SPA single source) [TEST-15]', () => {
    const error = new AuthExpiredError({ endpoint: '/x', status: 401 });
    expect(isAuthExpiredError(error)).toBe(true);
    expect(formatUserFacingError(error, 'generic')).toBe(SPA_SESSION_EXPIRED_COPY.sessionExpired);
    expect(getClusterMutationErrorMessage(error, 'Sam')).toBe(SPA_SESSION_EXPIRED_COPY.sessionExpired);
  });

  it('never leaks raw error internals to the DOM — non-auth errors get the safe fallback [TEST-15]', () => {
    const leaky = new Error('Request to /wp-json/acx/v1/secret failed (500): stack trace body');
    expect(formatUserFacingError(leaky, 'generic')).toBe('generic');
    expect(formatUserFacingError(new Error('network down'), 'generic')).toBe('generic');
    expect(formatUserFacingError({}, 'fallback text')).toBe('fallback text');
    expect(getClusterMutationErrorMessage(new Error('Failed to fetch'), 'Sam')).toBe(
      'Network error. Please check your connection and try again.',
    );
    expect(getClusterMutationErrorMessage(new Error('plain failure'), 'Sam')).toBe('plain failure');
  });

  it('pre-classified auth_expired AppError uses session-expired copy (M16 / F5)', () => {
    const classified = {
      _tag: 'auth_expired' as const,
      endpoint: '/x',
      status: 401 as const,
      message: 'expired',
      cause: null,
    };
    expect(isAuthExpiredError(classified)).toBe(true);
    expect(formatUserFacingError(classified, 'generic')).toBe(SPA_SESSION_EXPIRED_COPY.sessionExpired);
  });
});
