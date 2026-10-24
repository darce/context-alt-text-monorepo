import { describe, expect, it } from 'vitest';

import { formatScanSubmissionError, resolveScanErrorMessage } from '../scanApiError';
import { HTTPError } from '../../../utils/errorTaxonomy';

describe('formatScanSubmissionError', () => {
  it('surfaces embedding runtime rejection detail verbatim', () => {
    const error = new Error(
      'Request to /wp-json/acx/v1/recognition/analyze failed (503): {"detail":{"reason":"embedding_runtime_unavailable","detail":"InsightFace model bundle missing"}}',
    );

    expect(formatScanSubmissionError(error)).toBe('InsightFace model bundle missing');
  });

  it('returns null for unrelated errors', () => {
    expect(formatScanSubmissionError(new Error('network down'))).toBeNull();
  });
});

describe('resolveScanErrorMessage', () => {
  const FALLBACK = 'Recognition job failed. Please try again.';

  it.each([402, 429])('explains HTTP %i without exposing the response body', (status) => {
    const error = new HTTPError({
      status,
      endpoint: '/recognition/analyze',
      bodyPreview: 'private body',
      retryAfterSeconds: undefined,
      message: 'private body',
    });
    const message = resolveScanErrorMessage(error, FALLBACK);
    expect(message).not.toBe(FALLBACK);
    expect(message).not.toContain('private body');
    expect(message).toMatch(status === 402 ? /allowance/i : /wait/i);
  });

  it('returns the structured rejection detail when present', () => {
    const error = new Error(
      'Request to /wp-json/acx/v1/recognition/analyze failed (503): {"detail":{"reason":"embedding_runtime_unavailable","detail":"InsightFace model bundle missing"}}',
    );

    expect(resolveScanErrorMessage(error, FALLBACK)).toBe('InsightFace model bundle missing');
  });

  it('returns the fallback instead of raw HTTP body text when unparseable', () => {
    const error = new Error(
      'Request to /wp-json/acx/v1/recognition/analyze failed (502): <html><body>502 Bad Gateway</body></html>',
    );

    const message = resolveScanErrorMessage(error, FALLBACK);

    expect(message).toBe(FALLBACK);
    expect(message).not.toContain('502');
    expect(message).not.toContain('Bad Gateway');
  });

  it('returns the fallback for non-Error inputs', () => {
    expect(resolveScanErrorMessage('boom', FALLBACK)).toBe(FALLBACK);
  });
});
