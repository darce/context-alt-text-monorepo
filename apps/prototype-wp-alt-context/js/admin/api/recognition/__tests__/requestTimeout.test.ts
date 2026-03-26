import { afterEach, describe, expect, it, vi } from 'vitest';

import { createRecognitionTimeoutSignal } from '../requestTimeout';

describe('createRecognitionTimeoutSignal', () => {
  const originalAbortSignal = globalThis.AbortSignal;

  afterEach(() => {
    globalThis.AbortSignal = originalAbortSignal;
    vi.restoreAllMocks();
  });

  it('returns undefined when AbortSignal.timeout is unavailable', () => {
    globalThis.AbortSignal = {} as unknown as typeof AbortSignal;

    expect(createRecognitionTimeoutSignal(5_000)).toBeUndefined();
  });

  it('delegates to AbortSignal.timeout when available', () => {
    const signal = new AbortController().signal;
    const timeout = vi.fn<(timeoutMs: number) => AbortSignal>().mockReturnValue(signal);

    globalThis.AbortSignal = { timeout } as unknown as typeof AbortSignal;

    expect(createRecognitionTimeoutSignal(7_500)).toBe(signal);
    expect(timeout).toHaveBeenCalledWith(7_500);
  });
});
