/**
 * Extract a user-visible scan rejection reason from WP proxy / recognition API errors.
 */

const EMBEDDING_RUNTIME_UNAVAILABLE = 'embedding_runtime_unavailable';

const parseDetailPayload = (rawBody: string): { reason?: string; detail?: string } | null => {
  const jsonStart = rawBody.indexOf('{');
  if (jsonStart < 0) {
    return null;
  }
  try {
    const payload: unknown = JSON.parse(rawBody.slice(jsonStart));
    if (!payload || typeof payload !== 'object') {
      return null;
    }
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === 'string') {
      return { detail };
    }
    if (detail && typeof detail === 'object') {
      const structured = detail as { reason?: unknown; detail?: unknown };
      return {
        reason: typeof structured.reason === 'string' ? structured.reason : undefined,
        detail: typeof structured.detail === 'string' ? structured.detail : undefined,
      };
    }
    return null;
  } catch {
    return null;
  }
};

export const formatScanSubmissionError = (error: unknown): string | null => {
  if (!(error instanceof Error)) {
    return null;
  }
  const parsed = parseDetailPayload(error.message);
  if (!parsed) {
    return null;
  }
  if (parsed.reason === EMBEDDING_RUNTIME_UNAVAILABLE && parsed.detail) {
    return parsed.detail;
  }
  if (parsed.detail) {
    return parsed.detail;
  }
  return null;
};