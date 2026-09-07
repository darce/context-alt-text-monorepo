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

export type GpuLastTransitionReason =
  | 'work'
  | 'operator'
  | 'idle'
  | 'lease_cap'
  | 'start_failed'
  | 'unknown';

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
  typeof value === 'object' && value !== null;

const isIntentAction = (value: unknown): value is GpuIntentAction =>
  Object.values(GpuIntentAction).includes(value as GpuIntentAction);

/**
 * Validate the wire payload before any consumer dereferences it. `fetchRequiredApi`
 * only casts, so without this every field below is an unchecked assumption.
 */
export const parseGpuStatusResponse = (payload: unknown): GpuStatusResponse => {
  if (!isRecord(payload)) {
    throw new MalformedGpuStatusError('response body');
  }
  const gpuState = payload.gpu_state;
  if (!isRecord(gpuState)) {
    throw new MalformedGpuStatusError('gpu_state');
  }
  if (!isGpuState(gpuState.state)) {
    throw new MalformedGpuStatusError('gpu_state.state');
  }
  if (!isIntentAction(gpuState.intent)) {
    throw new MalformedGpuStatusError('gpu_state.intent');
  }
  const load = payload.load;
  if (!isRecord(load) || typeof load.has_work !== 'boolean') {
    throw new MalformedGpuStatusError('load.has_work');
  }
  if (typeof payload.snapshot_fresh !== 'boolean') {
    throw new MalformedGpuStatusError('snapshot_fresh');
  }
  if (typeof payload.server_time !== 'string') {
    throw new MalformedGpuStatusError('server_time');
  }
  return payload as unknown as GpuStatusResponse;
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
