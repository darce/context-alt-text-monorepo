const hasAbortSignalTimeout = (): boolean => typeof AbortSignal !== 'undefined' && 'timeout' in AbortSignal;

export const createRecognitionTimeoutSignal = (ms = 2_000): AbortSignal | undefined => {
  if (!hasAbortSignalTimeout()) {
    return undefined;
  }
  return (AbortSignal as unknown as { timeout: (timeoutMs: number) => AbortSignal }).timeout(ms);
};
