import { describe, expect, expectTypeOf, it } from 'vitest';

import { GPU_STATE, type GpuState } from '../../../api/describeApi';
import type { ActivityWarmingObservation } from '../../../hooks/useActivityStatus';
import {
  WARMING_OBSERVATION_EVIDENCE,
  WARMING_OBSERVATION_STATUS,
  type WarmingObservationStatus,
} from '../../../utils/warmingDeadline';
import {
  descriptionWaitPresentation,
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
      'GPU unavailable. Existing results remain available; review each description’s compute tier.',
    );
  });

  it('returns notice copy for every canonical GPU state', () => {
    for (const state of Object.values(GPU_STATE)) {
      expect(gpuStateNotice(state, 3).length).toBeGreaterThan(0);
    }
  });
});

const UNAVAILABLE_HEADLINE = 'Description service status unavailable';
const NOT_CONFIRMED_HEADLINE = 'Description service status not confirmed yet';

const waitObservation = (
  status: WarmingObservationStatus,
  overrides: Partial<ActivityWarmingObservation> = {},
): ActivityWarmingObservation => ({
  status,
  evidence: WARMING_OBSERVATION_EVIDENCE.UNKNOWN,
  firstObservedAt: 1,
  deadlineAt: 2,
  ...overrides,
});

describe('descriptionWaitPresentation', () => {
  it.each([
    ['unobserved', undefined],
    ['unknown', waitObservation(WARMING_OBSERVATION_STATUS.UNKNOWN)],
    ['not warming', waitObservation(WARMING_OBSERVATION_STATUS.NOT_WARMING)],
    ['unknown without outage', waitObservation(WARMING_OBSERVATION_STATUS.UNKNOWN, { statusOutage: false })],
  ] as const)('keeps a %s status observation quiet instead of reporting an outage', (_label, observation) => {
    const wait = descriptionWaitPresentation(observation);
    expect(wait.headline).toBe(NOT_CONFIRMED_HEADLINE);
    expect(wait.headline).not.toBe(UNAVAILABLE_HEADLINE);
    expect(wait.detail).toBe(
      'This description run keeps waiting until the service reports its status. Check status or cancel the run.',
    );
  });

  it('reports status unavailable only for a confirmed status outage', () => {
    expect(
      descriptionWaitPresentation(waitObservation(WARMING_OBSERVATION_STATUS.UNKNOWN, { statusOutage: true })),
    ).toEqual({
      headline: UNAVAILABLE_HEADLINE,
      detail: 'Startup could not be confirmed. Check the run status or cancel this description run.',
    });
  });

  it.each([
    [WARMING_OBSERVATION_STATUS.WAITING, 'Waiting for description service…'],
    [WARMING_OBSERVATION_STATUS.OVERDUE, 'Description service is taking longer than expected'],
  ] as const)('keeps %s copy ahead of an outage verdict', (status, headline) => {
    expect(descriptionWaitPresentation(waitObservation(status, { statusOutage: true })).headline).toBe(headline);
  });
});
