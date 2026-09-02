import { describe, expect, it, vi } from 'vitest';

import { classifyError } from '../../../../utils/appError';
import { getClusterMutationErrorMessage, isAbortError } from '../clusterMutationUtils';

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
    expect(getClusterMutationErrorMessage(classified, 'Ada')).toBe(
      'Save is taking too long. Please try again.',
    );
  });
});
