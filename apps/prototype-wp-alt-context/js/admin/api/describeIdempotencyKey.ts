/** Create one browser-side identity for a describe-run user action. */
export const createDescribeIdempotencyKey = (): string => {
  if (
    typeof globalThis.crypto !== 'undefined' &&
    typeof globalThis.crypto.randomUUID === 'function'
  ) {
    return globalThis.crypto.randomUUID();
  }

  return `describe-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
};
