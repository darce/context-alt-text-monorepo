import { describe, expect, it, vi } from 'vitest';

import { classifyError } from '../../../../utils/appError';
import { HTTPError } from '../../../../utils/http';
import {
  CLUSTER_MUTATION_ERROR_COPY,
  getClusterMutationErrorMessage,
  getClusterMutationUserError,
  isAbortError,
} from '../clusterMutationUtils';

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
