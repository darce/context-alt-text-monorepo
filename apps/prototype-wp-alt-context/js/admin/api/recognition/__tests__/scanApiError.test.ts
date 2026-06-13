import { describe, expect, it } from 'vitest';

import { formatScanSubmissionError, resolveScanErrorMessage } from '../scanApiError';

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
