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

  it('keeps non-auth errors on their existing paths [TEST-15]', () => {
    expect(formatUserFacingError(new Error('network down'), 'generic')).toBe('network down');
    expect(formatUserFacingError({}, 'fallback text')).toBe('fallback text');
    expect(getClusterMutationErrorMessage(new Error('Failed to fetch'), 'Sam')).toBe(
      'Network error. Please check your connection and try again.',
    );
    expect(getClusterMutationErrorMessage(new Error('plain failure'), 'Sam')).toBe('plain failure');
  });
});
