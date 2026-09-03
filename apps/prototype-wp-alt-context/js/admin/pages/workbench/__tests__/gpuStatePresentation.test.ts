import { describe, expect, expectTypeOf, it } from 'vitest';

import { GPU_STATE, type GpuState } from '../../../api/describeApi';
import {
  GPU_STATE_PRESENTATION,
  gpuStateNotice,
  gpuStatePresentation,
  type GpuStatePresentation,
} from '../gpuStatePresentation';

const ALL_GPU_STATES = [
  GPU_STATE.UNKNOWN,
  GPU_STATE.STOPPED,
  GPU_STATE.STARTING,
  GPU_STATE.WARMING,
  GPU_STATE.READY,
  GPU_STATE.DEGRADED,
] as const satisfies readonly GpuState[];

const assertPresentationEntry: (
  entry: GpuStatePresentation | undefined,
  state: string,
) => asserts entry is GpuStatePresentation = (entry, state) => {
  if (entry === undefined) {
    throw new Error(`Missing GPU presentation entry for state: ${state}`);
  }
};

describe('gpuStatePresentation', () => {
  it('covers exactly the canonical GPU state vocabulary', () => {
    // The type assertion fails at compile time if GPU_STATE gains a member that
    // this test list omits; the key assertion also guards the runtime record.
    expectTypeOf<Exclude<GpuState, (typeof ALL_GPU_STATES)[number]>>().toEqualTypeOf<never>();
    expect(Object.keys(GPU_STATE_PRESENTATION).sort()).toEqual([...ALL_GPU_STATES].sort());

    for (const state of ALL_GPU_STATES) {
      const entry: GpuStatePresentation | undefined = GPU_STATE_PRESENTATION[state];
      assertPresentationEntry(entry, state);
      expect(entry.label.length).toBeGreaterThan(0);
      expect(entry.icon.length).toBeGreaterThan(0);
      expect(entry.tone.length).toBeGreaterThan(0);
      expect(typeof entry.terminal).toBe('boolean');
    }
  });

  it.each(ALL_GPU_STATES)('returns the canonical row for %s', (state) => {
    expect(gpuStatePresentation(state)).toBe(GPU_STATE_PRESENTATION[state]);
  });

  it('maps null and unknown to the same calm tier-not-reported presentation', () => {
    expect(gpuStatePresentation(null)).toBe(GPU_STATE_PRESENTATION.unknown);
    expect(gpuStatePresentation(null)).toEqual({
      label: 'not reported',
      icon: 'circle-help',
      tone: 'muted',
      terminal: false,
    });
  });

  it('marks only stable lifecycle states as terminal', () => {
    expect(GPU_STATE_PRESENTATION.stopped.terminal).toBe(true);
    expect(GPU_STATE_PRESENTATION.ready.terminal).toBe(true);
    expect(GPU_STATE_PRESENTATION.degraded.terminal).toBe(true);
    expect(GPU_STATE_PRESENTATION.starting.terminal).toBe(false);
    expect(GPU_STATE_PRESENTATION.warming.terminal).toBe(false);
  });

  it('owns the stopped and degraded consequence copy', () => {
    expect(gpuStateNotice(GPU_STATE.STOPPED, 0)).toBe('Will warm on start (~2 min)');
    expect(gpuStateNotice(GPU_STATE.DEGRADED, 3)).toBe(
      'GPU unavailable — kept 3 CPU drafts. Final descriptions will not upgrade.',
    );
  });

  it('returns notice copy for every canonical GPU state', () => {
    for (const state of Object.values(GPU_STATE)) {
      expect(gpuStateNotice(state, 3).length).toBeGreaterThan(0);
    }
  });
});
