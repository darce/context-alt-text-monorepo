import { fetchRequiredApi } from '../utils/http';
import { getConfig, getEndpoint } from './config';
import { GPU_STATE, isGpuState, type GpuState } from './describeApi';

/** Wire actions accepted by the operator intent endpoint (C1). */
export const GpuIntentAction = {
  START: 'start',
  STOP: 'stop',
  AUTO: 'auto',
} as const;

export type GpuIntentAction = (typeof GpuIntentAction)[keyof typeof GpuIntentAction];

/** Lifecycle's acknowledgement for the most recent operator intent (C2). */
export const GpuIntentStatus = {
  NONE: 'none',
  PENDING: 'pending',
  HONOURED: 'honoured',
  BLOCKED_WORK_IN_FLIGHT: 'blocked_work_in_flight',
  EXPIRED: 'expired',
} as const;

export type GpuIntentStatus = (typeof GpuIntentStatus)[keyof typeof GpuIntentStatus];

// Uppercase aliases match the existing SPA vocabulary while the PascalCase names
// mirror the C2 contract names used by consumers.
export const GPU_INTENT_ACTION = GpuIntentAction;
export const GPU_INTENT_STATUS = GpuIntentStatus;

export const GPU_LAST_TRANSITION_REASON = {
  WORK: 'work',
  OPERATOR: 'operator',
  IDLE: 'idle',
  LEASE_CAP: 'lease_cap',
  START_FAILED: 'start_failed',
  UNKNOWN: 'unknown',
} as const;

export type GpuLastTransitionReason = (typeof GPU_LAST_TRANSITION_REASON)[keyof typeof GPU_LAST_TRANSITION_REASON];

export interface GpuStateSnapshot {
  state: GpuState;
  instance_id: string | null;
  written_at: number | null;
  reason: string | null;
  since: number | null;
  intent: GpuIntentAction;
  intent_expires_at: string | null;
  intent_status: GpuIntentStatus;
  honoured_nonce: string | null;
  lease_expires_at: string | null;
  instance_running_since: string | null;
  last_transition_reason: GpuLastTransitionReason;
}

export interface GpuOperatorIntent {
  schema_version: 1;
  action: GpuIntentAction;
  requested_at: string;
  expires_at: string;
  ttl_seconds: number;
  requested_by: string;
  nonce: string;
}

export interface GpuLoadSnapshot {
  has_work: boolean;
  written_at: number | null;
  fresh: boolean;
}

export interface GpuStatusResponse {
  gpu_state: GpuStateSnapshot;
  snapshot_age_seconds: number | null;
  snapshot_fresh: boolean;
  intent: GpuOperatorIntent | null;
  load: GpuLoadSnapshot;
  server_time: string;
}

export interface PostGpuIntentPayload {
  action: GpuIntentAction;
  ttl_seconds?: number;
}

export type { GpuState };

/**
 * Thrown when the GPU status wire payload does not satisfy the C2 contract.
 * The control card renders its error state instead of the operator seeing a
 * blank Settings page: a malformed subordinate payload must not take the host
 * screen down with it.
 */
export class MalformedGpuStatusError extends Error {
  constructor(field: string) {
    super(`GPU status response is missing or malformed: ${field}`);
    this.name = 'MalformedGpuStatusError';
  }
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const isIntentAction = (value: unknown): value is GpuIntentAction =>
  typeof value === 'string' && Object.values(GpuIntentAction).some((candidate) => candidate === value);

const isIntentStatus = (value: unknown): value is GpuIntentStatus =>
  typeof value === 'string' && Object.values(GpuIntentStatus).some((candidate) => candidate === value);

const isLastTransitionReason = (value: unknown): value is GpuLastTransitionReason =>
  typeof value === 'string' && Object.values(GPU_LAST_TRANSITION_REASON).some((candidate) => candidate === value);

const isNullableString = (value: unknown): value is string | null => value === null || typeof value === 'string';

const isNullableFiniteNumber = (value: unknown): value is number | null =>
  value === null || (typeof value === 'number' && Number.isFinite(value));

const isDateTime = (value: unknown): value is string => {
  if (typeof value !== 'string') {
    return false;
  }

  // The shared schema uses JSON Schema's date-time format. Keep the check
  // local to this boundary so malformed timestamps cannot reach formatters or
  // lifecycle comparisons as if they were trusted contract data.
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})$/.exec(value);
  if (!match) {
    return false;
  }

  const [, yearText, monthText, dayText, hourText, minuteText, secondText, offset] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const hour = Number(hourText);
  const minute = Number(minuteText);
  const second = Number(secondText);
  const offsetHours = offset === 'Z' ? 0 : Number(offset.slice(1, 3));
  const offsetMinutes = offset === 'Z' ? 0 : Number(offset.slice(4, 6));
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const daysInMonth = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1] ?? 0;

  return (
    month >= 1 &&
    month <= 12 &&
    day >= 1 &&
    day <= daysInMonth &&
    hour <= 23 &&
    minute <= 59 &&
    second <= 59 &&
    offsetHours <= 23 &&
    offsetMinutes <= 59
  );
};

const isUuid = (value: unknown): value is string =>
  typeof value === 'string' && /^(?:urn:uuid:)?[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(value);

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

// These key lists mirror the required properties and additionalProperties:false
// declarations in packages/shared-contracts/schemas/scene-gpu-status.schema.json.
// Checking exact keys here prevents a boundary adapter from silently projecting
// an unvalidated subset into the typed response consumed by the controls.
const GPU_STATUS_KEYS = [
  'gpu_state',
  'snapshot_age_seconds',
  'snapshot_fresh',
  'intent',
  'load',
  'server_time',
] as const;

const GPU_STATE_SNAPSHOT_KEYS = [
  'state',
  'instance_id',
  'written_at',
  'reason',
  'since',
  'intent',
  'intent_expires_at',
  'intent_status',
  'honoured_nonce',
  'lease_expires_at',
  'instance_running_since',
  'last_transition_reason',
] as const;

const GPU_INTENT_KEYS = [
  'schema_version',
  'action',
  'requested_at',
  'expires_at',
  'ttl_seconds',
  'requested_by',
  'nonce',
] as const;

const GPU_LOAD_KEYS = ['has_work', 'written_at', 'fresh'] as const;

const validateGpuStatusResponse = (payload: unknown): string | null => {
  if (!isRecord(payload)) {
    return 'response body';
  }

  const topLevelKeyError = firstContractKeyError(payload, GPU_STATUS_KEYS, 'response');
  if (topLevelKeyError) {
    return topLevelKeyError;
  }

  const gpuState = payload.gpu_state;
  if (!isRecord(gpuState)) {
    return 'gpu_state';
  }
  const gpuStateKeyError = firstContractKeyError(gpuState, GPU_STATE_SNAPSHOT_KEYS, 'gpu_state');
  if (gpuStateKeyError) {
    return gpuStateKeyError;
  }
  if (!isGpuState(gpuState.state)) {
    return 'gpu_state.state';
  }
  if (!isNullableString(gpuState.instance_id)) {
    return 'gpu_state.instance_id';
  }
  if (!isNullableFiniteNumber(gpuState.written_at)) {
    return 'gpu_state.written_at';
  }
  if (!isNullableString(gpuState.reason)) {
    return 'gpu_state.reason';
  }
  if (!isNullableFiniteNumber(gpuState.since)) {
    return 'gpu_state.since';
  }
  if (!isIntentAction(gpuState.intent)) {
    return 'gpu_state.intent';
  }
  if (gpuState.intent_expires_at !== null && !isDateTime(gpuState.intent_expires_at)) {
    return 'gpu_state.intent_expires_at';
  }
  if (!isIntentStatus(gpuState.intent_status)) {
    return 'gpu_state.intent_status';
  }
  if (!isNullableString(gpuState.honoured_nonce)) {
    return 'gpu_state.honoured_nonce';
  }
  if (gpuState.lease_expires_at !== null && !isDateTime(gpuState.lease_expires_at)) {
    return 'gpu_state.lease_expires_at';
  }
  if (gpuState.instance_running_since !== null && !isDateTime(gpuState.instance_running_since)) {
    return 'gpu_state.instance_running_since';
  }
  if (!isLastTransitionReason(gpuState.last_transition_reason)) {
    return 'gpu_state.last_transition_reason';
  }

  if (
    payload.snapshot_age_seconds !== null &&
    (!isNullableFiniteNumber(payload.snapshot_age_seconds) || payload.snapshot_age_seconds < 0)
  ) {
    return 'snapshot_age_seconds';
  }
  if (typeof payload.snapshot_fresh !== 'boolean') {
    return 'snapshot_fresh';
  }

  const intent = payload.intent;
  if (intent !== null) {
    if (!isRecord(intent)) {
      return 'intent';
    }
    const intentKeyError = firstContractKeyError(intent, GPU_INTENT_KEYS, 'intent');
    if (intentKeyError) {
      return intentKeyError;
    }
    if (intent.schema_version !== 1) {
      return 'intent.schema_version';
    }
    if (!isIntentAction(intent.action)) {
      return 'intent.action';
    }
    if (!isDateTime(intent.requested_at)) {
      return 'intent.requested_at';
    }
    if (!isDateTime(intent.expires_at)) {
      return 'intent.expires_at';
    }
    if (
      typeof intent.ttl_seconds !== 'number' ||
      !Number.isInteger(intent.ttl_seconds) ||
      intent.ttl_seconds < 60 ||
      intent.ttl_seconds > 7200
    ) {
      return 'intent.ttl_seconds';
    }
    if (typeof intent.requested_by !== 'string') {
      return 'intent.requested_by';
    }
    if (!isUuid(intent.nonce)) {
      return 'intent.nonce';
    }
  }

  const load = payload.load;
  if (!isRecord(load)) {
    return 'load';
  }
  const loadKeyError = firstContractKeyError(load, GPU_LOAD_KEYS, 'load');
  if (loadKeyError) {
    return loadKeyError;
  }
  if (typeof load.has_work !== 'boolean') {
    return 'load.has_work';
  }
  if (!isNullableFiniteNumber(load.written_at)) {
    return 'load.written_at';
  }
  if (typeof load.fresh !== 'boolean') {
    return 'load.fresh';
  }
  if (!isDateTime(payload.server_time)) {
    return 'server_time';
  }

  return null;
};

const assertGpuStatusResponse: (payload: unknown) => asserts payload is GpuStatusResponse = (payload) => {
  const malformedField = validateGpuStatusResponse(payload);
  if (malformedField) {
    throw new MalformedGpuStatusError(malformedField);
  }
};

/**
 * Validate the wire payload before any consumer dereferences it. `fetchRequiredApi`
 * only casts, so without this every field below is an unchecked assumption.
 */
export const parseGpuStatusResponse = (payload: unknown): GpuStatusResponse => {
  assertGpuStatusResponse(payload);
  return payload;
};

export const fetchGpuStatus = async (): Promise<GpuStatusResponse> =>
  parseGpuStatusResponse(
    await fetchRequiredApi<unknown>(getEndpoint('recognitionGpuStatus'), {
      method: 'GET',
      restNonce: getConfig().nonce,
    }),
  );

export const postGpuIntent = async (payload: PostGpuIntentPayload): Promise<GpuStatusResponse> =>
  parseGpuStatusResponse(
    await fetchRequiredApi<unknown>(getEndpoint('recognitionGpuIntent'), {
      method: 'POST',
      restNonce: getConfig().nonce,
      body: payload,
    }),
  );

// Keep the imported state object in this module's public surface for callers that
// only need the GPU control API, without inventing a second state vocabulary.
export { GPU_STATE };
