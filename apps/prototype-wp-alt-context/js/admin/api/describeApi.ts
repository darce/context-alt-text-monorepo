/**
 * Image Description API (E19-1 S12)
 *
 * Single-image describe: POST acx/v1/recognition/describe { media_id }. The WP
 * proxy forwards the backend `VisualFactsResponse` verbatim (15 provenance
 * fields). A deferred/stub backend profile (florence_large, gpu_phi4) or a
 * missing [vlm] extra surfaces as a 503 whose FastAPI `detail` we extract for
 * the UI; a malformed upstream envelope is a WP_Error 502 (`message`).
 */

import { fetchRequiredApi } from '../utils/http';
import { getEndpoint, getConfig } from './config';
import { createRecognitionTimeoutSignal } from './recognition/requestTimeout';

export interface VisualFacts {
  caption: string;
  objects: string[];
  ocr_text: string | null;
}

export interface VisualFactsResponse {
  tenant_id: string;
  media_id: number;
  image_hash: string;
  context_hash: string;
  adapter: string;
  model_id: string;
  model_version: string;
  prompt_or_task_version: string;
  visual_facts: VisualFacts;
  alt_text_draft: string;
  context_used: { sources: string[]; applied: boolean };
  provider_disclosure: { provider: string; left_service_boundary: boolean };
  cached: boolean;
  duration_ms: number;
  retention_class: string;
}

export type DescriptionCandidateReason = 'missing_alt' | 'has_alt_text' | 'unsupported_mime';

export interface DescriptionCandidateRow {
  media_id: number;
  filename: string;
  title: string;
  mime_type: string;
  current_alt_text: string;
  reason: DescriptionCandidateReason;
}

export interface DescriptionCandidatesResponse {
  candidates: DescriptionCandidateRow[];
  exclusions: DescriptionCandidateRow[];
  limit: number;
  offset: number;
  total_candidates: number;
  total_exclusions: number;
}

export interface DescriptionCandidatesParams {
  limit?: number;
  offset?: number;
}

export const describeMedia = async (mediaId: number): Promise<VisualFactsResponse> =>
  fetchRequiredApi<VisualFactsResponse>(getEndpoint('recognitionDescribe'), {
    method: 'POST',
    body: { media_id: mediaId },
    restNonce: getConfig().nonce,
    // Generous: florence_small is ~14s on the OCI A1, and the cold model load on
    // the first request can push the wall time higher.
    signal: createRecognitionTimeoutSignal(180_000),
  });

export const fetchDescriptionCandidates = async ({
  limit = 50,
  offset = 0,
}: DescriptionCandidatesParams = {}): Promise<DescriptionCandidatesResponse> => {
  const endpoint = new URL(getEndpoint('recognitionDescribeCandidates'));
  endpoint.searchParams.set('limit', String(limit));
  endpoint.searchParams.set('offset', String(offset));

  return fetchRequiredApi<DescriptionCandidatesResponse>(endpoint.toString(), {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
};

const parsePayload = (raw: string): Record<string, unknown> | null => {
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
 * Resolve a user-safe describe error message: the FastAPI `detail` (503 stub /
 * unavailable) or the WP_Error `message` (502 invalid envelope) when present,
 * otherwise the caller's localized fallback. Never returns raw proxy body text.
 *
 * Intentionally separate from recognition/scanApiError.ts (E19-1-REV-C-4): that
 * resolver special-cases `embedding_runtime_unavailable` and only reads `detail`;
 * describe instead needs the WP_Error `message` branch (502 invalid_description_
 * envelope) and a nested-`detail` branch. Kept as a small dedicated parser rather
 * than coupling describe to the scan-specific resolver.
 */
export const resolveDescribeErrorMessage = (error: unknown, fallback: string): string => {
  if (!(error instanceof Error)) {
    return fallback;
  }
  const payload = parsePayload(error.message);
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
