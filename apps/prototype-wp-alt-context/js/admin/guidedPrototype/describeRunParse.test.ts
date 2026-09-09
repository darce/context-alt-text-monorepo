import { describe, expect, it } from 'vitest';

import { GPU_STATE, MalformedDescribeRunResponseError, parseDescribeRunResponse } from '../api/describeApi';

const validRun = {
  tenant_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
  run_id: 'run-1',
  status: 'running',
  phase: 'queued',
  completed: 0,
  failed: 0,
  skipped: 0,
  total: 1,
  cancel_requested: false,
  eta_seconds: null,
  gpu_state: GPU_STATE.STOPPED,
  recognition_enabled: true,
} as const;

describe('parseDescribeRunResponse', () => {
  it('accepts a schema-shaped envelope including a non-null gpu_state', () => {
    expect(parseDescribeRunResponse(validRun).run_id).toBe('run-1');
    expect(parseDescribeRunResponse(validRun).gpu_state).toBe(GPU_STATE.STOPPED);
  });

  it('rejects a missing or null run_id so pollers cannot treat undefined as live', () => {
    const missing = { ...validRun } as Record<string, unknown>;
    delete missing.run_id;
    expect(() => parseDescribeRunResponse(missing)).toThrow(MalformedDescribeRunResponseError);
    expect(() => parseDescribeRunResponse({ ...validRun, run_id: null })).toThrow(/response\.run_id/);
    expect(() => parseDescribeRunResponse({ ...validRun, run_id: '' })).toThrow(/response\.run_id/);
  });

  it('rejects a null or unknown gpu_state', () => {
    expect(() => parseDescribeRunResponse({ ...validRun, gpu_state: null })).toThrow(/response\.gpu_state/);
    expect(() => parseDescribeRunResponse({ ...validRun, gpu_state: 'cold' })).toThrow(/response\.gpu_state/);
  });
});
