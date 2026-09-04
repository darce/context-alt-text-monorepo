import { describe, expect, it, vi } from 'vitest';

import { classifyError } from '../../../../utils/appError';
import { AuthExpiredError, HTTPError } from '../../../../utils/http';
import { SPA_SESSION_EXPIRED_COPY } from '../../../../utils/sessionExpiredCopy';
import {
  ClusterMutationTimeoutError,
  createClusterMutationTimeoutError,
  getClusterMutationErrorMessage,
  isAbortError,
  isClusterMutationTimeoutError,
} from '../clusterMutationUtils';

const GENERIC = 'An unexpected error occurred. Please try again.';
const TIMEOUT = 'Save is taking too long. Please try again.';
const CONFLICT = 'Label already exists. Use the dropdown to merge.';
const NETWORK = 'Network error. Please check your connection and try again.';
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
  it('maps pre-classified abort AppError to the timeout copy', () => {
    const classified = classifyError(new DOMException('The operation was aborted.', 'AbortError'));
    expect(getClusterMutationErrorMessage(classified, 'Ada')).toBe(TIMEOUT);
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

describe('ClusterMutationTimeoutError (FEBT1-LC-02: typed timeout channel)', () => {
  it('classifies by brand, not by the wording of any message', () => {
    const timedOut = createClusterMutationTimeoutError('save');

    expect(isClusterMutationTimeoutError(timedOut)).toBe(true);
    expect(getClusterMutationErrorMessage(timedOut, 'Ada')).toBe(TIMEOUT);
    // The proof that the channel is typed: the message contains none of the
    // English tokens the old substring matcher keyed on, and it still maps.
    expect(timedOut.message.toLowerCase()).not.toContain('timed out');
    expect(timedOut.message.toLowerCase()).not.toContain('timeout');
    // …and the substring matcher, run directly on that message, finds nothing —
    // so the mapping above can only have come from the brand.
    expect(getClusterMutationErrorMessage(new Error(timedOut.message), 'Ada')).not.toBe(TIMEOUT);
  });

  it('never leaks its diagnostic token as user copy', () => {
    const timedOut = createClusterMutationTimeoutError('duplicate_lookup');
    expect(timedOut.operation).toBe('duplicate_lookup');
    expect(getClusterMutationErrorMessage(timedOut, 'Ada')).not.toContain('duplicate_lookup');
  });

  it('is distinguishable from a user cancel, which the hooks swallow silently', () => {
    const cancelled = new DOMException('The operation was aborted.', 'AbortError');
    expect(isClusterMutationTimeoutError(cancelled)).toBe(false);
    expect(isAbortError(createClusterMutationTimeoutError('save'))).toBe(false);
  });

  it('rejects non-timeout values', () => {
    expect(isClusterMutationTimeoutError(new Error('save request timed out'))).toBe(false);
    expect(isClusterMutationTimeoutError(null)).toBe(false);
    expect(isClusterMutationTimeoutError('cluster_mutation_timeout')).toBe(false);
    expect(isClusterMutationTimeoutError(httpError(504, 'gateway timeout'))).toBe(false);
  });

  it('is an Error subclass so existing error plumbing still carries it', () => {
    const timedOut = createClusterMutationTimeoutError('merge');
    expect(timedOut).toBeInstanceOf(Error);
    expect(timedOut).toBeInstanceOf(ClusterMutationTimeoutError);
    expect(timedOut.name).toBe('ClusterMutationTimeoutError');
  });

  it('still maps wire-originated timeout text, which is a separate channel', () => {
    // Server-reported condition (message-shape recognition) must keep working:
    // the typed sentinel replaces our own locally minted literal only.
    expect(getClusterMutationErrorMessage(httpError(504, 'upstream timed out'), 'Ada')).toBe(TIMEOUT);
  });
});
