import { describe, expect, it } from 'vitest';

import {
  GPU_LAST_TRANSITION_REASON,
  GpuIntentAction,
  GpuIntentStatus,
  MalformedGpuStatusError,
  parseGpuStatusResponse,
} from '../gpuApi';

const statusResponse = (): Record<string, unknown> => ({
  gpu_state: {
    state: 'stopped',
    instance_id: null,
    written_at: 1_700_000_000,
    reason: null,
    since: null,
    intent: GpuIntentAction.AUTO,
    intent_expires_at: null,
    intent_status: GpuIntentStatus.NONE,
    honoured_nonce: null,
    lease_expires_at: null,
    instance_running_since: null,
    last_transition_reason: GPU_LAST_TRANSITION_REASON.UNKNOWN,
  },
  snapshot_age_seconds: 12,
  snapshot_fresh: true,
  intent: {
    schema_version: 1,
    action: GpuIntentAction.AUTO,
    requested_at: '2026-09-07T11:59:00Z',
    expires_at: '2026-09-07T12:01:00Z',
    ttl_seconds: 120,
    requested_by: 'operator@example.test',
    nonce: 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee',
  },
  load: {
    has_work: false,
    written_at: 1_700_000_004,
    fresh: true,
  },
  server_time: '2026-09-07T12:00:00Z',
});

const nestedRecord = (payload: Record<string, unknown>, key: string): Record<string, unknown> => {
  const value = payload[key];
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error(`${key} fixture must be an object`);
  }
  return value as Record<string, unknown>;
};

describe('parseGpuStatusResponse', () => {
  it('returns a complete schema-valid response without inventing metadata', () => {
    const payload = statusResponse();

    expect(parseGpuStatusResponse(payload)).toBe(payload);
  });

  it('rejects a response when a nested contract field is omitted', () => {
    const payload = statusResponse();
    delete nestedRecord(payload, 'gpu_state').intent_status;

    expect(() => parseGpuStatusResponse(payload)).toThrowError(new MalformedGpuStatusError('gpu_state.intent_status'));
  });

  it('rejects malformed nested metadata instead of passing it to the control card', () => {
    const payload = statusResponse();
    nestedRecord(payload, 'gpu_state').last_transition_reason = 'backend-invented';

    expect(() => parseGpuStatusResponse(payload)).toThrow(/gpu_state\.last_transition_reason/);
  });

  it('rejects invalid snapshot age and additional wire properties', () => {
    const negativeAge = statusResponse();
    negativeAge.snapshot_age_seconds = -1;
    expect(() => parseGpuStatusResponse(negativeAge)).toThrow(/snapshot_age_seconds/);

    const extraProperty = statusResponse();
    nestedRecord(extraProperty, 'load').unexpected = true;
    expect(() => parseGpuStatusResponse(extraProperty)).toThrow(/load\.unexpected/);
  });

  it('rejects malformed operator intent metadata', () => {
    const payload = statusResponse();
    const intent = nestedRecord(payload, 'intent');
    intent.ttl_seconds = 30;

    expect(() => parseGpuStatusResponse(payload)).toThrow(/intent\.ttl_seconds/);
  });

  it('rejects invalid date-time and UUID fields', () => {
    const invalidDate = statusResponse();
    invalidDate.server_time = 'not-a-date';
    expect(() => parseGpuStatusResponse(invalidDate)).toThrow(/server_time/);

    const invalidUuid = statusResponse();
    nestedRecord(invalidUuid, 'intent').nonce = 'not-a-uuid';
    expect(() => parseGpuStatusResponse(invalidUuid)).toThrow(/intent\.nonce/);
  });
});
