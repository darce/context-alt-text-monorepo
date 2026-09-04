import { describe, expect, it, vi } from 'vitest';

import { classifyError } from '../../../../utils/appError';
import { AuthExpiredError, HTTPError } from '../../../../utils/http';
import { SPA_SESSION_EXPIRED_COPY } from '../../../../utils/sessionExpiredCopy';
import {
  CLUSTER_MUTATION_ERROR_COPY,
  getClusterMutationErrorMessage,
  getClusterMutationUserError,
  isAbortError,
} from '../clusterMutationUtils';

const GENERIC = 'An unexpected error occurred. Please try again.';
// Canonical strings live in docs/ux-maps/febt-1-job-error-states.md and are
// re-exported as CLUSTER_MUTATION_ERROR_COPY; pin against that, not a literal copy.
const TIMEOUT = CLUSTER_MUTATION_ERROR_COPY.timeout;
const CONFLICT = 'Label already exists. Use the dropdown to merge.';
const NETWORK = CLUSTER_MUTATION_ERROR_COPY.transport;
const SECRET_BODY = 'stack-trace: /var/www/wp-content/plugins/secret.php line 42';

const httpError = (status: number, bodyPreview: string): HTTPError =>
  new HTTPError({
    status,
    retryAfterSeconds: undefined,
    endpoint: '/acx/v1/recognition/clusters/abc/merge',
    bodyPreview,
    // Mirrors http.ts: the body preview is embedded in the message.
    message: `Request to /acx/v1/recognition/clusters/abc/merge failed (${status}): ${bodyPreview}`,
  });

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (text: string, ...values: (string | number)[]) => {
    let index = 0;
    return text
      .replace(/%(\d+)\$[sd]/g, (_match, group: string) => String(values[Number(group) - 1] ?? ''))
      .replace(/%[sd]/g, () => String(values[index++] ?? ''));
  },
}));

describe('isAbortError', () => {
  it('treats DOMException AbortError as abort', () => {
    expect(isAbortError(new DOMException('The operation was aborted.', 'AbortError'))).toBe(true);
  });

  it('treats pre-classified abort AppError as abort [CARD-24]', () => {
    const classified = classifyError(new DOMException('The operation was aborted.', 'AbortError'));
    expect(classified._tag).toBe('abort');
    expect(isAbortError(classified)).toBe(true);
  });

  it('treats non-DOMException TimeoutError name as abort [CARD-24]', () => {
    const err = new Error('The operation timed out.');
    err.name = 'TimeoutError';
    expect(isAbortError(err)).toBe(true);
  });

  it('does not treat ordinary errors as abort', () => {
    expect(isAbortError(new Error('boom'))).toBe(false);
  });
});

describe('getClusterMutationErrorMessage abort', () => {
  it('maps pre-classified abort AppError to the ux-map timeout copy', () => {
    const classified = classifyError(new DOMException('The operation was aborted.', 'AbortError'));
    expect(getClusterMutationErrorMessage(classified, 'Ada')).toBe(CLUSTER_MUTATION_ERROR_COPY.timeout);
  });

  it('maps a TimeoutError name to the timeout copy [FEBT1G-M-08]', () => {
    const err = new Error('The operation timed out.');
    err.name = 'TimeoutError';
    expect(getClusterMutationErrorMessage(err, 'Ada')).toBe(TIMEOUT);
  });
});

describe('getClusterMutationErrorMessage never returns wire text [FEBT1-W2A-04]', () => {
  // Mutant killed: `return error.message` for an HTTPError renders the response
  // body — including any stack trace or WAF page — as user-facing copy.
  it.each([400, 422, 500, 502])('does not leak the %d response body', (status) => {
    const message = getClusterMutationErrorMessage(httpError(status, SECRET_BODY), 'Ada');
    expect(message).toBe(GENERIC);
    expect(message).not.toContain(SECRET_BODY);
    expect(message).not.toContain('failed (');
  });

  it('maps a 409 by status, not by scraping the message', () => {
    // Body carries no '409' and no 'conflict': only the status can classify it.
    expect(getClusterMutationErrorMessage(httpError(409, 'duplicate label'), 'Ada')).toBe(CONFLICT);
  });

  it('recognizes projection_not_ready inside an HTTP body', () => {
    expect(getClusterMutationErrorMessage(httpError(409, 'projection_not_ready'), 'Ada')).toBe(
      'Local sync is still catching up. Retry sync before editing labels.',
    );
  });

  it('recognizes invalid_target_cluster_id inside an HTTP body and names the label', () => {
    expect(getClusterMutationErrorMessage(httpError(400, 'invalid_target_cluster_id'), 'Ada')).toBe(
      'That group is already named Ada - nothing to merge.',
    );
  });

  it('maps a pre-classified http AppError like the raw HTTPError', () => {
    const classified = classifyError(httpError(500, SECRET_BODY));
    expect(getClusterMutationErrorMessage(classified, 'Ada')).toBe(GENERIC);
  });

  it('maps auth expiry to the session copy', () => {
    const authExpired = new AuthExpiredError({ endpoint: '/members', status: 403 });
    expect(getClusterMutationErrorMessage(authExpired, 'Ada')).toBe(
      SPA_SESSION_EXPIRED_COPY.sessionExpired,
    );
  });

  it('maps a transport TypeError to the network copy', () => {
    expect(getClusterMutationErrorMessage(new TypeError('Failed to fetch'), 'Ada')).toBe(NETWORK);
  });

  it('keeps locally minted Error messages, which carry no wire body', () => {
    expect(getClusterMutationErrorMessage(new Error('Cannot merge: no cluster ID'), 'Ada')).toBe(
      'Cannot merge: no cluster ID',
    );
  });

  it('falls back to generic copy for non-Error throws', () => {
    expect(getClusterMutationErrorMessage('boom', 'Ada')).toBe(GENERIC);
    expect(getClusterMutationErrorMessage(null, 'Ada')).toBe(GENERIC);
  });
});

describe('getClusterMutationUserError [FEBT1-W2A-04]', () => {
  it('maps HTTP 409 via status, never substring, with reload recovery', () => {
    const error = new HTTPError({
      status: 409,
      retryAfterSeconds: undefined,
      endpoint: '/acx/v1/recognition/clusters/c1',
      bodyPreview: '{"code":"cluster_version_conflict"}',
      message: 'Request to /acx/v1/recognition/clusters/c1 failed (409): stale',
    });
    const mapped = getClusterMutationUserError(error, 'Ada');
    expect(mapped.kind).toBe('stale_conflict');
    expect(mapped.recovery).toBe('reload');
    expect(mapped.message).toBe(CLUSTER_MUTATION_ERROR_COPY.staleConflict);
    expect(mapped.message).not.toContain(error.endpoint);
  });
});
