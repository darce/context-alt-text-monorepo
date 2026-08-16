/**
 * Shared WP_Error / FastAPI rejection body parser.
 *
 * fetchRequiredApi throws Error whose message embeds the JSON body after a
 * status prefix. Callers must only surface structured `detail` / nested
 * `detail` / WP_Error `message` — never raw proxy/HTTP body text.
 */

export const parseWpErrorPayload = (raw: string): Record<string, unknown> | null => {
  const start = raw.indexOf('{');
  if (start < 0) {
    return null;
  }
  try {
    const payload: unknown = JSON.parse(raw.slice(start));
    return payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : null;
  } catch {
    return null;
  }
};

/**
 * Resolve a user-safe error message: FastAPI `detail` (string or nested),
 * then WP_Error `message`, otherwise the caller's localized fallback.
 * Never returns raw proxy body text.
 */
export const resolveWpErrorMessage = (error: unknown, fallback: string): string => {
  if (!(error instanceof Error)) {
    return fallback;
  }
  const payload = parseWpErrorPayload(error.message);
  if (payload) {
    const detail = payload.detail;
    if (typeof detail === 'string' && detail.trim() !== '') {
      return detail;
    }
    if (detail && typeof detail === 'object') {
      const nested = (detail as { detail?: unknown }).detail;
      if (typeof nested === 'string' && nested.trim() !== '') {
        return nested;
      }
    }
    const message = payload.message;
    if (typeof message === 'string' && message.trim() !== '') {
      return message;
    }
  }
  return fallback;
};
