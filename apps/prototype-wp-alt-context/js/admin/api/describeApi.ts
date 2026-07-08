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
  alt_text_write?: AltTextWriteResult;
}

export type AltTextWriteStatus = 'written' | 'skipped_existing_alt' | 'forced_overwrite';

export interface AltTextWriteResult {
  status: AltTextWriteStatus;
  existing_alt_present: boolean;
}

export interface DescribeMediaWriteOptions {
  writeAlt?: boolean;
  force?: boolean;
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

export interface DescriptionHistoryRunStatus {
  status?: string;
  updated_at?: string | null;
  [key: string]: unknown;
}

export interface DescriptionHistoryHumanEdit {
  alt_text: string;
  edited_at?: string | null;
  user_id?: number | null;
}

export interface DescriptionHistoryItem {
  media_id: number;
  title: string;
  mime_type: string;
  current_alt_text: string;
  generated_alt_text: string;
  provenance: VisualFactsResponse | Record<string, unknown> | null;
  human_edit: DescriptionHistoryHumanEdit | null;
  run_status: DescriptionHistoryRunStatus | null;
}

export interface DescriptionHistoryResponse {
  total: number;
  items: DescriptionHistoryItem[];
}

export interface DescriptionHistoryQuery {
  limit?: number;
  offset?: number;
}

/**
 * Canonical describe-run status set. Single source of truth for status
 * comparisons — do not scatter `=== 'completed'` string literals (sr-007).
 */
export const DESCRIBE_RUN_STATUS = {
  PENDING: 'pending',
  RUNNING: 'running',
  COMPLETED: 'completed',
  COMPLETED_WITH_ERRORS: 'completed_with_errors',
  FAILED: 'failed',
  CANCELLED: 'cancelled',
} as const;

export type DescribeRunStatus = (typeof DESCRIBE_RUN_STATUS)[keyof typeof DESCRIBE_RUN_STATUS];
export type DescribeRunPhase = 'queued' | 'describing' | 'complete' | 'failed' | 'cancelled';

const TERMINAL_DESCRIBE_RUN_STATUSES: ReadonlySet<DescribeRunStatus> = new Set([
  DESCRIBE_RUN_STATUS.COMPLETED,
  DESCRIBE_RUN_STATUS.COMPLETED_WITH_ERRORS,
  DESCRIBE_RUN_STATUS.FAILED,
  DESCRIBE_RUN_STATUS.CANCELLED,
]);

/** A run is terminal once it can no longer make progress (success, partial, failure, or cancel). */
export const isDescribeRunTerminal = (status: DescribeRunStatus): boolean =>
  TERMINAL_DESCRIBE_RUN_STATUSES.has(status);

export interface DescribeRunResponse {
  tenant_id: string;
  run_id: string;
  status: DescribeRunStatus;
  phase: DescribeRunPhase;
  completed: number;
  failed: number;
  skipped: number;
  total: number;
  cancel_requested: boolean;
  // Backend-owned honest ETA for the remaining items; null while it cannot yet be estimated.
  eta_seconds: number | null;
  gpu_state: null;
}

/** One describe-run item as the operator reviews it before write-back (INT-01d).
 * `existing_alt` is the WP-side post-meta fact (INT-01b) that buckets drafts safe
 * to auto-apply (false) from those that would clobber operator alt text (true). */
export interface DescribeRunItem {
  media_id: number;
  status: string;
  alt_text_draft: string | null;
  caption: string | null;
  provenance: VisualFactsResponse | Record<string, unknown> | null;
  existing_alt: boolean;
}

export interface DescribeRunItemsResponse {
  run_id: string;
  items: DescribeRunItem[];
}

/** Result buckets from a guarded bulk apply (INT-01c): media ids written, ids
 * skipped because they already had alt (no explicit overwrite), and ids skipped
 * because the describe produced no draft. */
export interface ApplyDescribeRunResponse {
  run_id: string;
  applied: number[];
  skipped_existing: number[];
  skipped_no_draft: number[];
  // Media ids skipped because they are not attachment posts (untrusted upstream
  // media_id guard) and ids whose alt-text write failed — both reported so the
  // History UI never over-reports `applied`.
  skipped_invalid: number[];
  failed: number[];
}

export const describeMedia = async (
  mediaId: number,
  options: DescribeMediaWriteOptions = {},
): Promise<VisualFactsResponse> => {
  const body: { media_id: number; write_alt?: boolean; force?: boolean } = { media_id: mediaId };
  if (options.writeAlt !== undefined) {
    body.write_alt = options.writeAlt;
  }
  if (options.force !== undefined) {
    body.force = options.force;
  }

  return fetchRequiredApi<VisualFactsResponse>(getEndpoint('recognitionDescribe'), {
    method: 'POST',
    body,
    restNonce: getConfig().nonce,
    // Generous: florence_small is ~14s on the OCI A1, and the cold model load on
    // the first request can push the wall time higher.
    signal: createRecognitionTimeoutSignal(180_000),
  });
};

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

export const fetchDescriptionHistory = async ({
  limit = 50,
  offset = 0,
}: DescriptionHistoryQuery = {}): Promise<DescriptionHistoryResponse> => {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });

  return fetchRequiredApi<DescriptionHistoryResponse>(`${getEndpoint('recognitionDescribeHistory')}?${params}`, {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
};

export const correctDescriptionHistoryItem = async (
  mediaId: number,
  altText: string,
): Promise<DescriptionHistoryItem> =>
  fetchRequiredApi<DescriptionHistoryItem>(
    `${getEndpoint('recognitionDescribeHistory')}/${encodeURIComponent(String(mediaId))}/correction`,
    {
      method: 'POST',
      body: { alt_text: altText },
      restNonce: getConfig().nonce,
    },
  );

export const submitBulkDescribeRun = async (mediaIds: number[]): Promise<DescribeRunResponse> =>
  fetchRequiredApi<DescribeRunResponse>(getEndpoint('recognitionDescribeRuns'), {
    method: 'POST',
    body: { media_ids: mediaIds },
    restNonce: getConfig().nonce,
    // WP loads attachment bytes and forwards a multipart body under the proxy's
    // 180s 'description' budget; the browser timeout must exceed it so a slow
    // bulk upload cannot abort client-side after the run was already created
    // (which would orphan an untracked run — CLI-01).
    signal: createRecognitionTimeoutSignal(185_000),
  });

export const fetchBulkDescribeRun = async (runId: string): Promise<DescribeRunResponse> =>
  fetchRequiredApi<DescribeRunResponse>(
    `${getEndpoint('recognitionDescribeRuns')}/${encodeURIComponent(runId)}`,
    {
      method: 'GET',
      restNonce: getConfig().nonce,
      // Status is a cheap read polled every ~2s; a short timeout keeps a slow
      // poll from hanging and lets the next interval retry (INT-04).
      signal: createRecognitionTimeoutSignal(10_000),
    },
  );

export const cancelBulkDescribeRun = async (runId: string): Promise<DescribeRunResponse> =>
  fetchRequiredApi<DescribeRunResponse>(
    `${getEndpoint('recognitionDescribeRuns')}/${encodeURIComponent(runId)}/cancel`,
    {
      method: 'POST',
      restNonce: getConfig().nonce,
      signal: createRecognitionTimeoutSignal(30_000),
    },
  );

/**
 * Read a completed run's per-item drafts (INT-01d). The WP proxy annotates each
 * item with `existing_alt` so the History run view can bucket drafts safe to
 * auto-apply from those that need an explicit overwrite. A cheap read like the
 * status poll — short timeout, retried by react-query on failure.
 */
export const fetchDescribeRunItems = async (runId: string): Promise<DescribeRunItemsResponse> =>
  fetchRequiredApi<DescribeRunItemsResponse>(
    `${getEndpoint('recognitionDescribeRuns')}/${encodeURIComponent(runId)}/items`,
    {
      method: 'GET',
      restNonce: getConfig().nonce,
      signal: createRecognitionTimeoutSignal(10_000),
    },
  );

/**
 * Apply a completed run's drafts to attachment alt text (INT-01d → INT-01c).
 * `overwriteMediaIds` is the operator's explicit per-item opt-in to clobber
 * existing alt; the default empty list never overwrites operator text. Writes
 * post meta WP-side, so a modest timeout above the read budget.
 */
export const applyDescribeRunDrafts = async (
  runId: string,
  overwriteMediaIds: number[] = [],
): Promise<ApplyDescribeRunResponse> =>
  fetchRequiredApi<ApplyDescribeRunResponse>(
    `${getEndpoint('recognitionDescribeRuns')}/${encodeURIComponent(runId)}/apply`,
    {
      method: 'POST',
      body: { overwrite_media_ids: overwriteMediaIds },
      restNonce: getConfig().nonce,
      signal: createRecognitionTimeoutSignal(30_000),
    },
  );

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
