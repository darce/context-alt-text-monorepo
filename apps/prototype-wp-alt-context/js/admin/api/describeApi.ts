/**
 * Image Description API (E19-1 S12)
 *
 * Single-image describe: POST acx/v1/recognition/describe { media_id }. The WP
 * proxy forwards the backend `VisualFactsResponse` verbatim (17 core provenance
 * fields plus additive preview fields). A deferred/stub backend profile (florence_large, gpu_phi4) or a
 * missing [vlm] extra surfaces as a 503 whose FastAPI `detail` we extract for
 * the UI; a malformed upstream envelope is a WP_Error 502 (`message`).
 */

import { fetchRequiredApi } from '../utils/http';
import { getEndpoint, getConfig } from './config';
import { createRecognitionTimeoutSignal } from './recognition/requestTimeout';
import { parseWpErrorPayload, resolveWpErrorMessage } from './wpErrorMessage';

/** Canonical naming provenance statuses emitted for describe-run items (sr-007). */
export const NAMING_PROVENANCE_STATUS = {
  APPLIED: 'applied',
  DISABLED: 'disabled',
  SKIPPED_BUDGET: 'skipped_budget',
  NO_FACES: 'no_faces',
} as const;

/** Canonical naming realizer vocabulary emitted for applied names (sr-007). */
export const NAMING_REALIZER = {
  GROUNDED: 'grounded',
  POSITIONAL_FALLBACK: 'positional_fallback',
} as const;

export type NamingProvenanceStatus =
  (typeof NAMING_PROVENANCE_STATUS)[keyof typeof NAMING_PROVENANCE_STATUS];
export type NamingRealizer = (typeof NAMING_REALIZER)[keyof typeof NAMING_REALIZER];

/** C7 per-item naming provenance. Older run items may omit this field entirely. */
export interface NamingProvenance {
  status: NamingProvenanceStatus;
  realizer: NamingRealizer | null;
  names_applied: string[];
}

/** One identity name surfaced by the single-image named-caption preview. */
export interface InjectedName {
  name: string;
  cluster_id: string;
  roster_id: string | null;
  detection_confidence: number;
}

/** E19-4a skip reasons for the single-image named-caption preview. */
export type NamingProvenanceReason =
  | 'agreement_disabled'
  | 'db_unavailable'
  | 'image_unreadable'
  | 'no_confirmed_identities'
  | 'no_eligible_identities'
  | 'ambiguous_grounding'
  | 'merge_error';

/** E19-4a realization modes for the single-image named-caption preview. */
export type NamingProvenanceMode = 'grounded' | 'positional';

/** E19-4a single-image naming preview provenance. */
export interface NamedCaptionProvenance {
  injected_names: InjectedName[];
  naming_allowed: boolean;
  reason: NamingProvenanceReason | null;
  mode: NamingProvenanceMode | null;
}

export interface AttachmentFactProvenance {
  fact_id: string;
  fact_source: string;
  fact_label: string;
  decision: 'object' | 'caption' | 'dropped';
  altitude: 'object' | 'caption' | 'none';
  target_evidence: string | null;
  review_reason: string | null;
  visible: boolean;
}

export interface AttachmentProvenance {
  facts: AttachmentFactProvenance[];
}

export const DESCRIPTION_ADAPTER = {
  SEEDED: 'seeded',
  LOCAL_CPU: 'local_cpu',
  GPU: 'gpu',
  HOSTED_PROVIDER: 'hosted_provider',
} as const;

export type DescriptionAdapter = (typeof DESCRIPTION_ADAPTER)[keyof typeof DESCRIPTION_ADAPTER];

export const RETENTION_CLASS = {
  RETAIN_ALL: 'retain_all',
  DISPOSE_AFTER_ACK: 'dispose_after_ack',
  PURGE_ON_DEMAND: 'purge_on_demand',
} as const;

export type RetentionClass = (typeof RETENTION_CLASS)[keyof typeof RETENTION_CLASS];

export const PROVIDER_MODE = {
  NONE: 'none',
  LOCAL: 'local',
  HOSTED: 'hosted',
} as const;

export type ProviderMode = (typeof PROVIDER_MODE)[keyof typeof PROVIDER_MODE];

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
  adapter: DescriptionAdapter;
  model_id: string;
  model_version: string;
  prompt_or_task_version: string;
  visual_facts: VisualFacts;
  alt_text_draft: string;
  context_used: { sources: string[]; applied: boolean };
  provider_disclosure: { provider: ProviderMode; left_service_boundary: boolean };
  cached: boolean;
  duration_ms: number;
  retention_class: RetentionClass;
  tier: DescribeResultTier;
  result_generation: number;
  /** E19-4a additive preview fields, omitted by older adapters. */
  generic_draft?: string | null;
  named_draft?: string | null;
  naming_provenance?: NamedCaptionProvenance | null;
  /** E20-FUSION additive per-fact provenance, omitted when unavailable. */
  attachment_provenance?: AttachmentProvenance | null;
  /** ALTQ-1 additive long-form description, omitted by short-only adapters. */
  alt_text_long?: string | null;
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

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const hasOwn = (value: Record<string, unknown>, key: string): boolean =>
  Object.prototype.hasOwnProperty.call(value, key);

const firstContractKeyError = (
  value: Record<string, unknown>,
  expectedKeys: readonly string[],
  path: string,
): string | null => {
  const missingKey = expectedKeys.find((key) => !hasOwn(value, key));
  if (missingKey) {
    return `${path}.${missingKey}`;
  }

  const unexpectedKey = Object.keys(value).find((key) => !expectedKeys.includes(key));
  return unexpectedKey ? `${path}.${unexpectedKey}` : null;
};

const isStringArray = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every((item) => typeof item === 'string');

const isFiniteNumber = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);

const isInteger = (value: unknown): value is number =>
  isFiniteNumber(value) && Number.isInteger(value);

const DESCRIPTION_ADAPTERS = new Set(Object.values(DESCRIPTION_ADAPTER));
const PROVIDER_MODES = new Set(Object.values(PROVIDER_MODE));
const RETENTION_CLASSES = new Set(Object.values(RETENTION_CLASS));
const NAMING_PREVIEW_REASONS = new Set([
  'agreement_disabled',
  'db_unavailable',
  'image_unreadable',
  'no_confirmed_identities',
  'no_eligible_identities',
  'ambiguous_grounding',
  'merge_error',
]);
const NAMING_PREVIEW_MODES = new Set([NAMING_REALIZER.GROUNDED, 'positional']);
const ATTACHMENT_DECISIONS = new Set(['object', 'caption', 'dropped']);
const ATTACHMENT_ALTITUDES = new Set(['object', 'caption', 'none']);
const ALT_TEXT_WRITE_STATUSES = new Set([
  'written',
  'skipped_existing_alt',
  'skipped_empty_alt_text',
  'forced_overwrite',
  'provenance_healed',
  'partial',
  'failed',
]);
const ALT_TEXT_WRITE_PARTIAL_REASONS = new Set([
  'provenance_write_failed',
  'description_write_failed',
]);
const DESCRIPTION_WRITE_STATUSES = new Set([
  'written',
  'forced_overwrite',
  'skipped_no_long_text',
  'skipped_existing_description',
  'failed',
]);

const VISUAL_FACTS_RESPONSE_REQUIRED_KEYS = [
  'tenant_id',
  'media_id',
  'image_hash',
  'context_hash',
  'adapter',
  'model_id',
  'model_version',
  'prompt_or_task_version',
  'visual_facts',
  'alt_text_draft',
  'context_used',
  'provider_disclosure',
  'cached',
  'duration_ms',
  'retention_class',
  'tier',
  'result_generation',
] as const;

const VISUAL_FACTS_RESPONSE_OPTIONAL_KEYS = [
  'alt_text_long',
  'generic_draft',
  'named_draft',
  'naming_provenance',
  'attachment_provenance',
  'alt_text_write',
] as const;

const VISUAL_FACTS_RESPONSE_KEYS = [
  ...VISUAL_FACTS_RESPONSE_REQUIRED_KEYS,
  ...VISUAL_FACTS_RESPONSE_OPTIONAL_KEYS,
] as const;

const VISUAL_FACTS_KEYS = ['caption', 'objects', 'ocr_text'] as const;
const CONTEXT_USED_KEYS = ['sources', 'applied'] as const;
const PROVIDER_DISCLOSURE_KEYS = ['provider', 'left_service_boundary'] as const;
const NAMING_PREVIEW_KEYS = ['injected_names', 'naming_allowed', 'reason', 'mode'] as const;
const INJECTED_NAME_KEYS = ['name', 'cluster_id', 'roster_id', 'detection_confidence'] as const;
const ATTACHMENT_PROVENANCE_KEYS = ['facts'] as const;
const ATTACHMENT_FACT_KEYS = [
  'fact_id',
  'fact_source',
  'fact_label',
  'decision',
  'altitude',
  'target_evidence',
  'review_reason',
  'visible',
] as const;
const ALT_TEXT_WRITE_KEYS = ['status', 'existing_alt_present', 'reason', 'description_write'] as const;
const ALT_TEXT_WRITE_REQUIRED_KEYS = ['status', 'existing_alt_present'] as const;

const validateNamedCaptionProvenance = (value: unknown, path: string): string | null => {
  if (!isRecord(value)) {
    return path;
  }
  const keyError = firstContractKeyError(value, NAMING_PREVIEW_KEYS, path);
  if (keyError) {
    return keyError;
  }
  if (!Array.isArray(value.injected_names)) {
    return `${path}.injected_names`;
  }
  for (const [index, injectedName] of value.injected_names.entries()) {
    if (!isRecord(injectedName)) {
      return `${path}.injected_names[${index}]`;
    }
    const injectedNameKeyError = firstContractKeyError(
      injectedName,
      INJECTED_NAME_KEYS,
      `${path}.injected_names[${index}]`,
    );
    if (injectedNameKeyError) {
      return injectedNameKeyError;
    }
    if (typeof injectedName.name !== 'string') {
      return `${path}.injected_names[${index}].name`;
    }
    if (typeof injectedName.cluster_id !== 'string') {
      return `${path}.injected_names[${index}].cluster_id`;
    }
    if (injectedName.roster_id !== null && typeof injectedName.roster_id !== 'string') {
      return `${path}.injected_names[${index}].roster_id`;
    }
    if (!isFiniteNumber(injectedName.detection_confidence)) {
      return `${path}.injected_names[${index}].detection_confidence`;
    }
  }
  if (typeof value.naming_allowed !== 'boolean') {
    return `${path}.naming_allowed`;
  }
  if (
    value.reason !== null &&
    (typeof value.reason !== 'string' || !NAMING_PREVIEW_REASONS.has(value.reason))
  ) {
    return `${path}.reason`;
  }
  if (
    value.mode !== null &&
    (typeof value.mode !== 'string' || !NAMING_PREVIEW_MODES.has(value.mode))
  ) {
    return `${path}.mode`;
  }
  return null;
};

const validateAttachmentProvenance = (value: unknown, path: string): string | null => {
  if (!isRecord(value)) {
    return path;
  }
  const keyError = firstContractKeyError(value, ATTACHMENT_PROVENANCE_KEYS, path);
  if (keyError) {
    return keyError;
  }
  if (!Array.isArray(value.facts)) {
    return `${path}.facts`;
  }
  for (const [index, fact] of value.facts.entries()) {
    const factPath = `${path}.facts[${index}]`;
    if (!isRecord(fact)) {
      return factPath;
    }
    const factKeyError = firstContractKeyError(fact, ATTACHMENT_FACT_KEYS, factPath);
    if (factKeyError) {
      return factKeyError;
    }
    if (typeof fact.fact_id !== 'string') {
      return `${factPath}.fact_id`;
    }
    if (typeof fact.fact_source !== 'string') {
      return `${factPath}.fact_source`;
    }
    if (typeof fact.fact_label !== 'string') {
      return `${factPath}.fact_label`;
    }
    if (typeof fact.decision !== 'string' || !ATTACHMENT_DECISIONS.has(fact.decision)) {
      return `${factPath}.decision`;
    }
    if (typeof fact.altitude !== 'string' || !ATTACHMENT_ALTITUDES.has(fact.altitude)) {
      return `${factPath}.altitude`;
    }
    if (fact.target_evidence !== null && typeof fact.target_evidence !== 'string') {
      return `${factPath}.target_evidence`;
    }
    if (fact.review_reason !== null && typeof fact.review_reason !== 'string') {
      return `${factPath}.review_reason`;
    }
    if (typeof fact.visible !== 'boolean') {
      return `${factPath}.visible`;
    }
  }
  return null;
};

const validateAltTextWrite = (value: unknown, path: string): string | null => {
  if (!isRecord(value)) {
    return path;
  }
  const missingRequiredKey = ALT_TEXT_WRITE_REQUIRED_KEYS.find((key) => !hasOwn(value, key));
  if (missingRequiredKey) {
    return `${path}.${missingRequiredKey}`;
  }
  const unexpectedKey = Object.keys(value).find((key) => !ALT_TEXT_WRITE_KEYS.includes(key));
  if (unexpectedKey) {
    return `${path}.${unexpectedKey}`;
  }
  if (typeof value.status !== 'string' || !ALT_TEXT_WRITE_STATUSES.has(value.status)) {
    return `${path}.status`;
  }
  if (typeof value.existing_alt_present !== 'boolean') {
    return `${path}.existing_alt_present`;
  }
  if (
    hasOwn(value, 'reason') &&
    (typeof value.reason !== 'string' || !ALT_TEXT_WRITE_PARTIAL_REASONS.has(value.reason))
  ) {
    return `${path}.reason`;
  }
  if (
    hasOwn(value, 'description_write') &&
    (typeof value.description_write !== 'string' || !DESCRIPTION_WRITE_STATUSES.has(value.description_write))
  ) {
    return `${path}.description_write`;
  }
  return null;
};

const validateVisualFactsResponse = (payload: unknown): string | null => {
  if (!isRecord(payload)) {
    return 'response body';
  }
  const missingRequiredKey = VISUAL_FACTS_RESPONSE_REQUIRED_KEYS.find((key) => !hasOwn(payload, key));
  if (missingRequiredKey) {
    return `response.${missingRequiredKey}`;
  }
  const unexpectedTopLevelKey = Object.keys(payload).find(
    (key) => !VISUAL_FACTS_RESPONSE_KEYS.includes(key),
  );
  if (unexpectedTopLevelKey) {
    return `response.${unexpectedTopLevelKey}`;
  }

  for (const key of ['tenant_id', 'image_hash', 'context_hash', 'model_id', 'model_version', 'prompt_or_task_version'] as const) {
    if (typeof payload[key] !== 'string') {
      return `response.${key}`;
    }
  }
  if (!isInteger(payload.media_id)) {
    return 'response.media_id';
  }
  if (typeof payload.adapter !== 'string' || !DESCRIPTION_ADAPTERS.has(payload.adapter)) {
    return 'response.adapter';
  }
  if (!isRecord(payload.visual_facts)) {
    return 'response.visual_facts';
  }
  const visualFactsKeyError = firstContractKeyError(payload.visual_facts, VISUAL_FACTS_KEYS, 'response.visual_facts');
  if (visualFactsKeyError) {
    return visualFactsKeyError;
  }
  if (typeof payload.visual_facts.caption !== 'string') {
    return 'response.visual_facts.caption';
  }
  if (!isStringArray(payload.visual_facts.objects)) {
    return 'response.visual_facts.objects';
  }
  if (payload.visual_facts.ocr_text !== null && typeof payload.visual_facts.ocr_text !== 'string') {
    return 'response.visual_facts.ocr_text';
  }
  if (typeof payload.alt_text_draft !== 'string') {
    return 'response.alt_text_draft';
  }
  if (!isRecord(payload.context_used)) {
    return 'response.context_used';
  }
  const contextKeyError = firstContractKeyError(payload.context_used, CONTEXT_USED_KEYS, 'response.context_used');
  if (contextKeyError) {
    return contextKeyError;
  }
  if (!isStringArray(payload.context_used.sources)) {
    return 'response.context_used.sources';
  }
  if (typeof payload.context_used.applied !== 'boolean') {
    return 'response.context_used.applied';
  }
  if (!isRecord(payload.provider_disclosure)) {
    return 'response.provider_disclosure';
  }
  const providerKeyError = firstContractKeyError(
    payload.provider_disclosure,
    PROVIDER_DISCLOSURE_KEYS,
    'response.provider_disclosure',
  );
  if (providerKeyError) {
    return providerKeyError;
  }
  if (
    typeof payload.provider_disclosure.provider !== 'string' ||
    !PROVIDER_MODES.has(payload.provider_disclosure.provider)
  ) {
    return 'response.provider_disclosure.provider';
  }
  if (typeof payload.provider_disclosure.left_service_boundary !== 'boolean') {
    return 'response.provider_disclosure.left_service_boundary';
  }
  if (typeof payload.cached !== 'boolean') {
    return 'response.cached';
  }
  if (!isInteger(payload.duration_ms) || payload.duration_ms < 0) {
    return 'response.duration_ms';
  }
  if (typeof payload.retention_class !== 'string' || !RETENTION_CLASSES.has(payload.retention_class)) {
    return 'response.retention_class';
  }
  if (typeof payload.tier !== 'string' || !new Set(Object.values(DESCRIBE_RESULT_TIER)).has(payload.tier)) {
    return 'response.tier';
  }
  if (!isInteger(payload.result_generation) || payload.result_generation < 1) {
    return 'response.result_generation';
  }

  for (const key of ['alt_text_long', 'generic_draft', 'named_draft'] as const) {
    if (hasOwn(payload, key) && payload[key] !== null && typeof payload[key] !== 'string') {
      return `response.${key}`;
    }
  }
  if (hasOwn(payload, 'naming_provenance') && payload.naming_provenance !== null) {
    const namingError = validateNamedCaptionProvenance(payload.naming_provenance, 'response.naming_provenance');
    if (namingError) {
      return namingError;
    }
  }
  if (hasOwn(payload, 'attachment_provenance') && payload.attachment_provenance !== null) {
    const attachmentError = validateAttachmentProvenance(
      payload.attachment_provenance,
      'response.attachment_provenance',
    );
    if (attachmentError) {
      return attachmentError;
    }
  }
  if (hasOwn(payload, 'alt_text_write')) {
    const altTextWriteError = validateAltTextWrite(payload.alt_text_write, 'response.alt_text_write');
    if (altTextWriteError) {
      return altTextWriteError;
    }
  }
  return null;
};

/** Thrown when the describe response violates the backend envelope contract. */
export class MalformedVisualFactsResponseError extends Error {
  constructor(field: string) {
    super(`Describe response is missing or malformed: ${field}`);
    this.name = 'MalformedVisualFactsResponseError';
  }
}

const assertVisualFactsResponse: (payload: unknown) => asserts payload is VisualFactsResponse = (payload) => {
  const malformedField = validateVisualFactsResponse(payload);
  if (malformedField) {
    throw new MalformedVisualFactsResponseError(malformedField);
  }
};

/** Validate the wire payload before exposing it to describe result consumers. */
export const parseVisualFactsResponse = (payload: unknown): VisualFactsResponse => {
  assertVisualFactsResponse(payload);
  return payload;
};

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
  naming?: NamingProvenance;
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
 * Canonical GPU lifecycle states emitted by describe-run status responses.
 * `unknown` is a valid calm state (missing/stale snapshot), not an error.
 * Keep in lockstep with the description-service GPUState StrEnum (sr-007).
 */
export const GPU_STATE = {
  UNKNOWN: 'unknown',
  STOPPED: 'stopped',
  STARTING: 'starting',
  WARMING: 'warming',
  READY: 'ready',
  DEGRADED: 'degraded',
} as const;

export const isGpuState = (value: unknown): value is GpuState =>
  typeof value === 'string' && (Object.values(GPU_STATE) as string[]).includes(value);

export const isNamingProvenanceStatus = (value: unknown): value is NamingProvenanceStatus =>
  typeof value === 'string' &&
  (Object.values(NAMING_PROVENANCE_STATUS) as string[]).includes(value);

export const isNamingRealizer = (value: unknown): value is NamingRealizer =>
  typeof value === 'string' && (Object.values(NAMING_REALIZER) as string[]).includes(value);

/**
 * Validate the additive C7 field before it reaches presentation code. Invalid
 * naming metadata is treated like an older item with no naming field so the UI
 * never renders an untrusted status, realizer, or name.
 */
export const parseNamingProvenance = (value: unknown): NamingProvenance | undefined => {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return undefined;
  }

  const record = value as Record<string, unknown>;
  if (!isNamingProvenanceStatus(record.status)) {
    return undefined;
  }

  const realizer = record.realizer;
  if (realizer !== null && !isNamingRealizer(realizer)) {
    return undefined;
  }

  if (!Array.isArray(record.names_applied)) {
    return undefined;
  }
  const namesApplied = record.names_applied.filter(
    (name): name is string => typeof name === 'string',
  );
  if (namesApplied.length !== record.names_applied.length) {
    return undefined;
  }

  return {
    status: record.status,
    realizer,
    names_applied: namesApplied,
  };
};

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
export type GpuState = (typeof GPU_STATE)[keyof typeof GPU_STATE];

/** Canonical describe-run phase set, including GPU warmup as a RUNNING sub-phase. */
export const DESCRIBE_RUN_PHASE = {
  QUEUED: 'queued',
  WARMING: 'warming',
  DESCRIBING: 'describing',
  COMPLETE: 'complete',
  FAILED: 'failed',
  CANCELLED: 'cancelled',
} as const;

export type DescribeRunPhase = (typeof DESCRIBE_RUN_PHASE)[keyof typeof DESCRIBE_RUN_PHASE];

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
  // Untrusted wire value; consumers narrow it with isGpuState before presentation.
  gpu_state: unknown;
  // WBUX6-MRG-03: `recognition_enabled` is REQUIRED and non-nullable in
  // packages/shared-contracts/schemas/scene-describe-run.schema.json (which is
  // `additionalProperties: false`) and in the Python response model. This
  // interface omitted it, so the run's own record of whether identity fusion
  // was in play was invisible to every TS consumer -- and nothing failed.
  // Mirror the schema exactly rather than projecting a subset: a boundary type
  // that silently drops a contract field is the shape rg-005/rg-015 forbid, and
  // a divergence no test can see is not a decision, it is drift
  // (~/Development/heuristics-canon-research/lexicons/security.md:66, SEC-01
  // validate at every trust boundary).
  //
  // GATE: scene-describe-run.schema.json `required` must equal the keys of this
  // interface. See js/admin/api/__tests__/describeRunResponseContract.test.ts.
  recognition_enabled: boolean;
  /**
   * The server's own GENERATION budget (ACX_DESCRIPTION_TIMEOUT_SECONDS) as it
   * stood when the run was accepted, so a client waits on a disclosed bound
   * instead of a locally invented ceiling. It does NOT include GPU warm-up:
   * a cold run also pays ACX_GPU_WARMUP_TIMEOUT_SECONDS before generation
   * starts, and a client that treats this figure as the whole wait times a
   * healthy cold run out (see guidedPrototype/liveDescription.ts).
   *
   * Optional in scene-describe-run.schema.json (declared, but not in
   * `required`): null or absent for runs not created through
   * POST /scene/describe/run. Declared HERE rather than bolted on with a local
   * intersection at each call site, so a rename or type change in the schema
   * fails the contract test instead of silently falling through to a client
   * default (rg-005, rg-015).
   */
  deadline_seconds?: number | null;
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

  return parseVisualFactsResponse(
    await fetchRequiredApi<unknown>(getEndpoint('recognitionDescribe'), {
      method: 'POST',
      body,
      restNonce: getConfig().nonce,
      // Generous: florence_small is ~14s on the OCI A1, and the cold model load on
      // the first request can push the wall time higher.
      signal: createRecognitionTimeoutSignal(180_000),
    }),
  );
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
  ).then((response) => ({
    ...response,
    items: response.items.map((item) => {
      const provenance = item.provenance;
      if (
        !provenance ||
        typeof provenance !== 'object' ||
        !('naming' in provenance)
      ) {
        return item;
      }

      const naming = parseNamingProvenance(provenance.naming);
      if (naming === undefined) {
        const provenanceWithoutNaming = { ...provenance };
        delete provenanceWithoutNaming.naming;
        return { ...item, provenance: provenanceWithoutNaming };
      }

      return { ...item, provenance: { ...provenance, naming } };
    }),
  }));

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
