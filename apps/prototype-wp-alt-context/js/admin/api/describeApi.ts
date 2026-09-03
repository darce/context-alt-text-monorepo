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
import { parseWpErrorPayload, resolveWpErrorMessage } from './wpErrorMessage';

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

/**
 * REST `alt_text_write.status` members — keep in lockstep with PHP
 * `AltContext\Api\AltTextWriteStatus::REST_STATUSES` (sr-007 / BR-04).
 * CLI-only `dry_run` is not part of this REST payload type.
 * `provenance_healed` is success: force=false restamp when alt already matched.
 */
export type AltTextWriteStatus =
  | 'written'
  | 'skipped_existing_alt'
  | 'skipped_empty_alt_text'
  | 'forced_overwrite'
  | 'provenance_healed'
  | 'partial'
  | 'failed';

/**
 * REST `alt_text_write.reason` when status is `partial` (BR-08).
 * Distinguishes provenance-stamp failure (history gap, retry) from optional
 * long-description failure (history intact). Lockstep with PHP
 * `AltTextWriteStatus::PARTIAL_REASONS`.
 */
export type AltTextWritePartialReason =
  | 'provenance_write_failed'
  | 'description_write_failed';

/**
 * Nested `description_write` when `acx_alt_style` is `alt_plus_description`.
 * Lockstep with PHP `DescriptionWriteStatus::ALL`.
 */
export type DescriptionWriteStatus =
  | 'written'
  | 'forced_overwrite'
  | 'skipped_no_long_text'
  | 'skipped_existing_description'
  | 'failed';

export interface AltTextWriteResult {
  status: AltTextWriteStatus;
  existing_alt_present: boolean;
  /** Present when status is `partial` — distinguishes the two partial meanings. */
  reason?: AltTextWritePartialReason;
  /** Present only under alt_plus_description; omitted for alt_only. */
  description_write?: DescriptionWriteStatus;
}

export interface DescribeMediaWriteOptions {
  writeAlt?: boolean;
  force?: boolean;
}

export type DescriptionCandidateReason =
  | 'missing_alt'
  | 'has_alt_text'
  | 'unsupported_mime'
  | 'decorative';

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

/**
 * Recovery descriptor kinds on bulk-apply provenance envelopes.
 * Lockstep with PHP `AltTextWriteStatus::RECOVERY_KINDS` [sr-007] [R23-BR-20/21/22].
 */
export const RECOVERY_KIND = {
  NONE: 'none',
  SAME_RUN: 'same_run',
  RUN: 'run',
  SURFACE: 'surface',
  UNKNOWN: 'unknown',
} as const;

export type RecoveryKind = (typeof RECOVERY_KIND)[keyof typeof RECOVERY_KIND];

/**
 * Always-present recovery descriptor on bulk-applied provenance.
 * Replaces the deleted scalar `recovered_from_run_id` [R23-BR-20/21/22].
 */
export interface ProvenanceRecoveredFrom {
  /** Verbatim marker owner value when foreign recovery occurred; null otherwise. */
  origin: string | null;
  kind: RecoveryKind;
  /** Append-only origin chain, oldest first. */
  chain: string[];
}

/**
 * Stored provenance envelope on a history row (bulk apply / single / CLI writers).
 * Not the live VisualFactsResponse shape — recovery fields live here.
 */
export interface DescriptionHistoryProvenance {
  adapter?: string;
  model_id?: string;
  model_version?: string;
  prompt_or_task_version?: string;
  image_hash?: string;
  context_hash?: string;
  generated_at?: string;
  backend_result_id?: string;
  alt_text_draft?: string;
  source?: string;
  run_id?: string;
  applied_at?: string;
  recovered_from?: ProvenanceRecoveredFrom;
}

export interface DescriptionHistoryItem {
  media_id: number;
  title: string;
  mime_type: string;
  current_alt_text: string;
  generated_alt_text: string;
  provenance: DescriptionHistoryProvenance | VisualFactsResponse | null;
  human_edit: DescriptionHistoryHumanEdit | null;
  run_status: DescriptionHistoryRunStatus | null;
  /**
   * Server-owned decorative marker truth (acx_alt_decorative read-back as a
   * boolean). Present on correction success via build_item and on PARTIAL
   * error data — clients must not re-derive from request intent [A-03][rg-015].
   */
  is_decorative: boolean;
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

/** Canonical result tiers emitted for generated describe-run items (sr-007). */
export const DESCRIBE_RESULT_TIER = {
  PROVISIONAL_CPU: 'provisional_cpu',
  FINAL_GPU: 'final_gpu',
} as const;

/**
 * Canonical correction rejection codes from the history correction endpoint.
 * Gate on these via resolveDescribeErrorCode — never on localized message text
 * (sr-007, WBUX-5-BR-51).
 */
export const DESCRIPTION_CORRECTION_CODE = {
  PARTIAL: 'description_correction_partial',
  FAILED: 'description_correction_failed',
} as const;

export type DescriptionCorrectionCode =
  (typeof DESCRIPTION_CORRECTION_CODE)[keyof typeof DESCRIPTION_CORRECTION_CODE];

export type DescribeRunStatus = (typeof DESCRIBE_RUN_STATUS)[keyof typeof DESCRIBE_RUN_STATUS];
export type DescribeResultTier = (typeof DESCRIBE_RESULT_TIER)[keyof typeof DESCRIBE_RESULT_TIER];
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
  provenance: DescriptionHistoryProvenance | VisualFactsResponse | null;
  tier: DescribeResultTier | null;
  result_generation: number;
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
  // Alt text landed but provenance/history record did not — not fully applied;
  // operator should re-apply so the item appears in history. [RLSE-05]
  partial: number[];
  skipped_existing: number[];
  skipped_no_draft: number[];
  // Non-attachment / invalid targets only (untrusted upstream media_id guard).
  // Alt-write failures and unverified-marker outcomes land in `failed`, not here.
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

/**
 * Optional flags for history correction. Tri-state decorative [A-02][INT-09]:
 *   true  — mark decorative (empty alt + durable marker)
 *   false — explicit un-mark (clear marker even when alt is empty)
 *   undefined — omit from the body; server treats as unspecified (today's
 *               prior default-false behaviour for two-arg callers)
 * The server rejects decorative + non-empty alt with description_correction_failed (400).
 */
export interface DescriptionCorrectionOptions {
  decorative?: boolean;
}

export const correctDescriptionHistoryItem = async (
  mediaId: number,
  altText: string,
  options?: DescriptionCorrectionOptions,
): Promise<DescriptionHistoryItem> => {
  const body: { alt_text: string; decorative?: boolean } = { alt_text: altText };
  // Send whenever defined — including explicit false for un-mark [A-02].
  // undefined still omits the key so two-arg callers keep an identical body.
  if (options?.decorative !== undefined) {
    body.decorative = options.decorative;
  }
  return fetchRequiredApi<DescriptionHistoryItem>(
    `${getEndpoint('recognitionDescribeHistory')}/${encodeURIComponent(String(mediaId))}/correction`,
    {
      method: 'POST',
      body,
      restNonce: getConfig().nonce,
    },
  );
};

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

/**
 * Resolve a user-safe describe error message: the FastAPI `detail` (503 stub /
 * unavailable) or the WP_Error `message` (502 invalid envelope) when present,
 * otherwise the caller's localized fallback. Never returns raw proxy body text.
 *
 * Shared parse lives in wpErrorMessage.ts so settings and describe do not drift
 * ([REF-26]). Intentionally still separate from recognition/scanApiError.ts
 * (E19-1-REV-C-4): that resolver special-cases `embedding_runtime_unavailable`
 * and only reads `detail`.
 */
export const resolveDescribeErrorMessage = (error: unknown, fallback: string): string =>
  resolveWpErrorMessage(error, fallback);

/**
 * Resolve the WP_Error `code` from a describe/correction rejection when present.
 * Returns null when the error is not structured or carries no code — callers must
 * handle that honestly rather than inventing a sentinel ([rg-015]).
 *
 * Sibling of resolveDescribeErrorMessage: same parseWpErrorPayload, same deliberate
 * separation from recognition/scanApiError.ts. Code and message resolve
 * independently so a partial-correction path can gate on the stable code without
 * matching localized message text.
 */
export const resolveDescribeErrorCode = (error: unknown): string | null => {
  if (!(error instanceof Error)) {
    return null;
  }
  const payload = parseWpErrorPayload(error.message);
  if (!payload) {
    return null;
  }
  const code = payload.code;
  if (typeof code === 'string' && code.trim() !== '') {
    return code;
  }
  return null;
};

/**
 * Resolve a string field from the WP_Error `data` object when present.
 * Returns null when the error is unstructured, `data` is missing, or the named
 * field is absent / not a string — callers must not invent a value ([rg-015]).
 * Empty string is a legitimate stored value and is returned as-is.
 *
 * Sibling of resolveDescribeErrorCode: same parseWpErrorPayload, same tolerance for
 * unparseable messages. Used by partial-correction reconcile to read
 * `stored_alt_text` rather than guessing from the request payload.
 */
export const resolveDescribeErrorDataField = (error: unknown, field: string): string | null => {
  if (!(error instanceof Error)) {
    return null;
  }
  const payload = parseWpErrorPayload(error.message);
  if (!payload) {
    return null;
  }
  const data = payload.data;
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    return null;
  }
  const value = (data as Record<string, unknown>)[field];
  if (typeof value === 'string') {
    return value;
  }
  return null;
};

/**
 * Resolve a boolean field from the WP_Error `data` object when present.
 * Returns null when the error is unstructured, `data` is missing, or the named
 * field is absent / not a boolean — callers must not invent a value ([rg-015]).
 * Used by partial-correction reconcile to read `is_decorative` from server
 * truth rather than re-deriving from request intent [A-03].
 */
export const resolveDescribeErrorDataBooleanField = (
  error: unknown,
  field: string,
): boolean | null => {
  if (!(error instanceof Error)) {
    return null;
  }
  const payload = parseWpErrorPayload(error.message);
  if (!payload) {
    return null;
  }
  const data = payload.data;
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    return null;
  }
  const value = (data as Record<string, unknown>)[field];
  if (typeof value === 'boolean') {
    return value;
  }
  return null;
};
