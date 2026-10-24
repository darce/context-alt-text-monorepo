/**
 * Extract a user-visible scan rejection reason from WP proxy / recognition API errors.
 */

import { __ } from '@wordpress/i18n';
import { classifyError } from '../../utils/appError';

const EMBEDDING_RUNTIME_UNAVAILABLE = 'embedding_runtime_unavailable';

/** Run-wide refusals also reject later chunks; retry only on an explicit new action. */
export const shouldStopScanSubmission = (error: unknown): boolean => {
  const classified = classifyError(error);
  return (
    classified._tag === 'auth_expired' ||
    (classified._tag === 'http' && [401, 402, 403, 429].includes(classified.status))
  );
};

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

/**
 * Resolve a user-safe scan error message: the structured rejection detail when the
 * error carries one, otherwise the caller's localized fallback. Never returns raw
 * HTTP/proxy body text (E15-27-BR-11).
 */
export const resolveScanErrorMessage = (error: unknown, fallbackMessage: string): string => {
  const classified = classifyError(error);
  if (classified._tag === 'http' && classified.status === 402) {
    return __(
      'The account usage allowance is unavailable or insufficient for this scan. Check Usage & billing.',
      'alt-context',
    );
  }
  if (classified._tag === 'http' && classified.status === 429) {
    return __('Too many recognition requests. Wait before starting another scan.', 'alt-context');
  }
  return formatScanSubmissionError(error) ?? fallbackMessage;
};

/** User-safe copy for a `BatchAnalyzeResponse.refusal` that stopped a partly accepted scan. */
export const resolveScanRefusalMessage = (refusal: unknown): string =>
  resolveScanErrorMessage(refusal, __('Scanning stopped before all selected images were submitted.', 'alt-context'));
