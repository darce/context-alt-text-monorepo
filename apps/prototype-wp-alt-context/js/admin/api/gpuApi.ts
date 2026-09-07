import { fetchRequiredApi } from '../utils/http';
import { getConfig, getEndpoint } from './config';
import { GPU_STATE, type GpuState } from './describeApi';

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

export const fetchGpuStatus = async (): Promise<GpuStatusResponse> =>
  fetchRequiredApi<GpuStatusResponse>(getEndpoint('recognitionGpuStatus'), {
    method: 'GET',
    restNonce: getConfig().nonce,
  });

export const postGpuIntent = async (payload: PostGpuIntentPayload): Promise<GpuStatusResponse> =>
  fetchRequiredApi<GpuStatusResponse>(getEndpoint('recognitionGpuIntent'), {
    method: 'POST',
    restNonce: getConfig().nonce,
    body: payload,
  });

// Keep the imported state object in this module's public surface for callers that
// only need the GPU control API, without inventing a second state vocabulary.
export { GPU_STATE };
