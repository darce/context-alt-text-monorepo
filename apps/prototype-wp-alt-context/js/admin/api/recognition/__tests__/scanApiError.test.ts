import { describe, expect, it } from 'vitest';

import { formatScanSubmissionError } from '../scanApiError';

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