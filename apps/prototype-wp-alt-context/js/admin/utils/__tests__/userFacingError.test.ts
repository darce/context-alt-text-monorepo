import { describe, expect, it, vi } from 'vitest';

import { AuthExpiredError, HTTPError } from '../http';
import { formatUserFacingError, isAuthExpiredError, SPA_SESSION_EXPIRED_COPY } from '../userFacingError';
import {
  getClusterMutationErrorMessage,
  getClusterMutationUserError,
} from '../../pages/workbench/identity-clusters/clusterMutationUtils';

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
  });

  it('HTTPError from a cluster mutation never surfaces the endpoint URL or response body [FEBT1-W2A-04]', () => {
    const error = new HTTPError({
      status: 500,
      retryAfterSeconds: undefined,
      endpoint: '/acx/v1/recognition/clusters/c1',
      bodyPreview: '{"code":"boom","message":"stack trace body"}',
      message: 'Request to /acx/v1/recognition/clusters/c1 failed (500): {"code":"boom","message":"stack trace body"}',
    });
    const message = getClusterMutationErrorMessage(error, 'Sam');
    expect(message).not.toContain('/acx/v1/recognition/clusters/c1');
    expect(message).not.toContain('stack trace body');
    expect(message).not.toBe(error.message);
  });

  it('409 yields the stale-conflict message and reload affordance [FEBT1-W2A-04]', () => {
    const error = new HTTPError({
      status: 409,
      retryAfterSeconds: undefined,
      endpoint: '/acx/v1/recognition/clusters/c1',
      bodyPreview: '{"code":"cluster_version_conflict"}',
      message: 'Request to /acx/v1/recognition/clusters/c1 failed (409): {"code":"cluster_version_conflict"}',
    });
    const mapped = getClusterMutationUserError(error, 'Sam');
    expect(mapped.kind).toBe('stale_conflict');
    expect(mapped.message).toBe('Label already exists. Use the dropdown to merge.');
    expect(mapped.recovery).toBe('reload');
    expect(mapped.message).not.toContain(error.endpoint);
    expect(mapped.message).not.toContain(error.bodyPreview);
  });

  it('transport failure yields the ux-map transport copy [FEBT1-W2A-04]', () => {
    expect(getClusterMutationErrorMessage(new TypeError('Failed to fetch'), 'Sam')).toBe(
      'Network error — check your connection',
    );
  });

  it('maps timeout to retry copy and leaves abort on the caller fallback [FEBT1-W2A-05]', () => {
    expect(formatUserFacingError({ name: 'TimeoutError', message: 'timed out' }, 'generic')).toBe(
      'The server took too long to respond — try again',
    );
    expect(formatUserFacingError({ name: 'AbortError', message: 'aborted' }, 'generic')).toBe('generic');
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
