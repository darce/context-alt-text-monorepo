// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { GPU_STATE } from '../../admin/api/describeApi';
import { TestConnectionOutcome } from '../../admin/api/settingsApi';
import { renderBanner } from '../../admin/pages/settings/testConnectionBanner';
import { GPU_STATE_VOCABULARY, gpuStateNotice } from '../../admin/pages/workbench/gpuStatePresentation';
import {
  PUBLIC_DEMO_CLIENT_DEADLINE_CEILING_SECONDS,
  PUBLIC_DEMO_ERROR_CODE,
  parsePublicDemoEnvelope,
  pollRun,
  statusPresentation,
} from '../demo-describe.js';

const C1 = 'The first description after a quiet period starts the GPU and can take several minutes. After that, each image takes seconds.';
// PublicDemoDescribeController::public_envelope_response projects counters into progress.
const warming = {
  run_id: 'run-1', status: 'running', phase: 'warming',
  gpu_state: 'starting', progress: { done: 0, total: 1 },
};

afterEach(() => vi.useRealTimers());

describe('canonical cold-start wait parity', () => {
  it('pins public warming and the stopped admin notice to exact C1', () => {
    expect(GPU_STATE_VOCABULARY.coldStartWait).toBe(C1);
    expect(gpuStateNotice(GPU_STATE.STOPPED)).toBe(C1);
    expect(statusPresentation(parsePublicDemoEnvelope(warming))).toEqual({ state: 'warming', message: C1 });
  });

  it.each(['unknown', 'degraded', null, undefined])('keeps warming honest with advisory gpu_state=%s', (gpuState) => {
    const { gpu_state: _gpuState, ...withoutGpuState } = warming;
    const body = gpuState === undefined ? withoutGpuState : { ...warming, gpu_state: gpuState };
    expect(statusPresentation(parsePublicDemoEnvelope(body))).toEqual({ state: 'warming', message: C1 });
  });

  it.each([undefined, 0, -1])('does not turn Retry-After into readiness when warmup_eta_seconds=%s', (eta) => {
    // SettingsController::build_probe_payload emits these as separate fields.
    const result = renderBanner({
      outcome: TestConnectionOutcome.STARTING, status_code: 202,
      retry_after_seconds: 48, ...(eta === undefined ? {} : { warmup_eta_seconds: eta }),
    });
    expect(result.primary).toBe('ℹ Description service is starting.');
    expect(result.remediation).toBe(GPU_STATE_VOCABULARY.coldStartWait);
  });

  it('preserves a producer-supplied ETA while keeping the canonical explanation', () => {
    const result = renderBanner({
      outcome: TestConnectionOutcome.STARTING, status_code: 202,
      retry_after_seconds: 5, warmup_eta_seconds: 48,
    });
    expect(result.primary).toBe('ℹ Description service is starting — ready in ~48 s');
    expect(result.remediation).toBe(C1);
  });

  it.each([
    { tier: 'provisional_cpu', message: 'CPU fallback draft (not GPU final).' },
    { tier: null, message: 'Description available, processing tier unavailable.' },
    { tier: undefined, message: 'Description available, processing tier unavailable.' },
  ])('ends the wait as degraded for tier=$tier even with ready telemetry', ({ tier, message }) => {
    const body = parsePublicDemoEnvelope({
      run_id: 'run-1', status: 'completed', phase: 'complete', gpu_state: 'ready',
      progress: { done: 1, total: 1 }, description: 'A lakeside path.',
      ...(tier === undefined ? {} : { description_tier: tier }),
    });
    expect(statusPresentation(body)).toEqual({ state: 'degraded', message });
  });

  it('bounds continued warming at 120 seconds without claiming terminal backend failure', async () => {
    vi.useFakeTimers();
    const onUpdate = vi.fn();
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(async () => new Response(JSON.stringify({
      ...warming, gpu_state: 'degraded',
    }), { status: 200 }));
    let settled = false;
    const outcome = pollRun({ statusUrl: '/status/run-1', nonce: 'nonce', fetchImpl, onUpdate })
      .catch((error: unknown) => error)
      .finally(() => { settled = true; });

    expect(PUBLIC_DEMO_CLIENT_DEADLINE_CEILING_SECONDS).toBe(120);
    await vi.advanceTimersByTimeAsync(119_999);
    expect(settled).toBe(false);
    expect(onUpdate).toHaveBeenCalled();
    for (const [body] of onUpdate.mock.calls) {
      expect(statusPresentation(body)).toEqual({ state: 'warming', message: C1 });
    }
    await vi.advanceTimersByTimeAsync(1);
    expect(settled).toBe(true);
    expect(await outcome).toMatchObject({
      code: PUBLIC_DEMO_ERROR_CODE.POLL_TIMEOUT, terminal: false,
      message: 'This is taking longer than expected. The description may still finish: choose Describe again with the same image to check on it.',
    });
    const callsAtCeiling = fetchImpl.mock.calls.length;
    await vi.advanceTimersByTimeAsync(5_000);
    expect(fetchImpl).toHaveBeenCalledTimes(callsAtCeiling);
  });

  it.each([
    '../demo-describe.js',
    '../../admin/pages/workbench/gpuStatePresentation.ts',
    '../../admin/pages/settings/GpuControlCard.tsx',
    '../../admin/pages/settings/testConnectionBanner.ts',
  ])('rejects retired static estimates in %s', (relativePath) => {
    const source = readFileSync(new URL(relativePath, import.meta.url), 'utf8');
    expect(source).not.toMatch(/(~|about |≈)\s?2 min/);
    expect(source).not.toMatch(/few minutes/);
  });
});
