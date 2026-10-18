import { describe, expect, it } from 'vitest';

import {
  deriveWarmingObservation,
  WARMING_OBSERVATION_EVIDENCE,
  WARMING_OBSERVATION_GRACE_MS,
  WARMING_OBSERVATION_LIMIT_MS,
  WARMING_OBSERVATION_STATUS,
} from '../warmingDeadline';

const storage = (): Storage => {
  const values = new Map<string, string>();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => {
      values.set(key, value);
    },
    removeItem: (key) => {
      values.delete(key);
    },
    clear: () => values.clear(),
    key: (index) => [...values.keys()][index] ?? null,
    get length() {
      return values.size;
    },
  } as Storage;
};

describe('deriveWarmingObservation', () => {
  const base = 1_700_000_000_000;
  const freshStopped = {
    state: 'stopped',
    snapshotFresh: true,
    intent: null,
    intentStatus: 'none',
  };

  it('bounds a warming run with fresh stopped/no-intent evidence', () => {
    const result = deriveWarmingObservation({
      runId: 'run-1',
      startupId: 'startup-1',
      isWarming: true,
      now: base,
      storage: storage(),
      gpuStatus: freshStopped,
    });

    expect(result.status).toBe(WARMING_OBSERVATION_STATUS.WAITING);
    expect(result.firstObservedAt).toBe(base);
    expect(result.deadlineAt).toBe(
      base + WARMING_OBSERVATION_LIMIT_MS + WARMING_OBSERVATION_GRACE_MS,
    );
    expect(result.evidence).toBe(WARMING_OBSERVATION_EVIDENCE.STOPPED);
  });

  it('keeps fresh stopped demand provisional while work is present without intent', () => {
    const result = deriveWarmingObservation({
      runId: 'run-demand',
      startupId: 'startup-demand',
      isWarming: true,
      now: base,
      storage: storage(),
      gpuStatus: { ...freshStopped, load: { has_work: true } },
    });

    expect(result.status).toBe(WARMING_OBSERVATION_STATUS.WAITING);
    expect(result.evidence).toBe(WARMING_OBSERVATION_EVIDENCE.STOPPED);
  });

  it('marks an explicit fresh start failure overdue without calling it terminal', () => {
    const result = deriveWarmingObservation({
      runId: 'run-start-failed',
      startupId: 'startup-start-failed',
      isWarming: true,
      now: base,
      storage: storage(),
      gpuStatus: {
        state: 'degraded',
        snapshotFresh: true,
        reason: 'start_failed',
        intent: null,
        intentStatus: 'none',
      },
    });

    expect(result.status).toBe(WARMING_OBSERVATION_STATUS.OVERDUE);
    expect(result.evidence).toBe(WARMING_OBSERVATION_EVIDENCE.START_FAILED);
  });

  it('waits for a valid pending start intent', () => {
    const result = deriveWarmingObservation({
      runId: 'run-pending',
      startupId: 'startup-pending',
      isWarming: true,
      now: base,
      storage: storage(),
      gpuStatus: {
        state: 'stopped',
        snapshotFresh: true,
        intent: 'start',
        intentStatus: 'pending',
      },
    });

    expect(result.status).toBe(WARMING_OBSERVATION_STATUS.WAITING);
    expect(result.evidence).toBe(WARMING_OBSERVATION_EVIDENCE.START_PENDING);
  });

  it.each([
    ['stale', { state: 'warming', snapshotFresh: false }],
    ['missing', undefined],
    ['malformed', { state: 'not-a-gpu-state', snapshotFresh: true }],
  ])('returns unknown for %s GPU evidence', (_label, gpuStatus) => {
    const result = deriveWarmingObservation({
      runId: `run-unknown-${_label}`,
      startupId: 'startup-unknown',
      isWarming: true,
      now: base,
      storage: storage(),
      gpuStatus,
    });

    expect(result.status).toBe(WARMING_OBSERVATION_STATUS.UNKNOWN);
    expect(result.evidence).toBe(WARMING_OBSERVATION_EVIDENCE.UNKNOWN);
  });

  it.each([
    ['malformed', { state: 'stopped', snapshotFresh: true, intent: 'active', intentStatus: 'none' }],
    [
      'expired',
      {
        state: 'stopped',
        snapshotFresh: true,
        intent: 'start',
        intentStatus: 'expired',
      },
    ],
  ])('returns unknown for a %s intent', (_label, gpuStatus) => {
    const result = deriveWarmingObservation({
      runId: `run-intent-${_label}`,
      startupId: 'startup-intent',
      isWarming: true,
      now: base,
      storage: storage(),
      gpuStatus,
    });

    expect(result.status).toBe(WARMING_OBSERVATION_STATUS.UNKNOWN);
  });

  it('changes to overdue exactly at the limit plus grace and not before', () => {
    const testStorage = storage();
    const input = {
      runId: 'run-boundary',
      startupId: 'startup-boundary',
      isWarming: true,
      storage: testStorage,
      gpuStatus: freshStopped,
    } as const;
    const bound = WARMING_OBSERVATION_LIMIT_MS + WARMING_OBSERVATION_GRACE_MS;

    expect(deriveWarmingObservation({ ...input, now: base }).status).toBe(
      WARMING_OBSERVATION_STATUS.WAITING,
    );
    expect(deriveWarmingObservation({ ...input, now: base + bound - 1 }).status).toBe(
      WARMING_OBSERVATION_STATUS.WAITING,
    );
    expect(deriveWarmingObservation({ ...input, now: base + bound }).status).toBe(
      WARMING_OBSERVATION_STATUS.OVERDUE,
    );
    expect(deriveWarmingObservation({ ...input, now: base + bound + 1 }).status).toBe(
      WARMING_OBSERVATION_STATUS.OVERDUE,
    );
  });

  it('shortens an existing bound with older phase-start evidence', () => {
    const testStorage = storage();
    const input = {
      runId: 'run-phase-start',
      startupId: 'startup-phase-start',
      isWarming: true,
      storage: testStorage,
      gpuStatus: freshStopped,
    } as const;
    const bound = WARMING_OBSERVATION_LIMIT_MS + WARMING_OBSERVATION_GRACE_MS;

    deriveWarmingObservation({ ...input, now: base });
    const shortened = deriveWarmingObservation({
      ...input,
      now: base + 1_000,
      phaseStartedAt: base - 5_000,
    });

    expect(shortened.firstObservedAt).toBe(base - 5_000);
    expect(shortened.deadlineAt).toBe(base - 5_000 + bound);
  });

  it('starts a separate bound for a new startup id', () => {
    const testStorage = storage();
    const first = deriveWarmingObservation({
      runId: 'run-startup-reset',
      startupId: 'startup-old',
      isWarming: true,
      now: base,
      storage: testStorage,
      gpuStatus: freshStopped,
    });
    const second = deriveWarmingObservation({
      runId: 'run-startup-reset',
      startupId: 'startup-new',
      isWarming: true,
      now: base + WARMING_OBSERVATION_LIMIT_MS,
      storage: testStorage,
      gpuStatus: freshStopped,
    });

    expect(first.firstObservedAt).toBe(base);
    expect(second.firstObservedAt).toBe(base + WARMING_OBSERVATION_LIMIT_MS);
    expect(second.status).toBe(WARMING_OBSERVATION_STATUS.WAITING);
  });

  it('clears the persisted bound when the run becomes terminal', () => {
    const testStorage = storage();
    const keyInput = {
      runId: 'run-terminal',
      startupId: 'startup-terminal',
      storage: testStorage,
      gpuStatus: freshStopped,
    } as const;

    deriveWarmingObservation({ ...keyInput, isWarming: true, now: base });
    const terminal = deriveWarmingObservation({
      ...keyInput,
      isWarming: false,
      isTerminal: true,
      now: base + 10,
    });
    const restartedObservation = deriveWarmingObservation({
      ...keyInput,
      isWarming: true,
      now: base + 20,
    });

    expect(terminal.status).toBe(WARMING_OBSERVATION_STATUS.NOT_WARMING);
    expect(restartedObservation.firstObservedAt).toBe(base + 20);
  });

  it('keeps the in-memory bound when storage get throws', () => {
    const testStorage: Storage = {
      ...storage(),
      getItem: () => {
        throw new Error('session storage unavailable');
      },
    } as Storage;
    const input = {
      runId: 'run-get-throws',
      startupId: 'startup-get-throws',
      isWarming: true,
      storage: testStorage,
      gpuStatus: freshStopped,
    } as const;

    const first = deriveWarmingObservation({ ...input, now: base });
    const second = deriveWarmingObservation({ ...input, now: base + 1_000 });

    expect(first.firstObservedAt).toBe(base);
    expect(second.firstObservedAt).toBe(base);
  });

  it('keeps the in-memory bound when storage set throws', () => {
    const testStorage: Storage = {
      ...storage(),
      setItem: () => {
        throw new Error('session storage quota exceeded');
      },
    } as Storage;
    const input = {
      runId: 'run-set-throws',
      startupId: 'startup-set-throws',
      isWarming: true,
      storage: testStorage,
      gpuStatus: freshStopped,
    } as const;

    const first = deriveWarmingObservation({ ...input, now: base });
    const second = deriveWarmingObservation({ ...input, now: base + 1_000 });

    expect(first.firstObservedAt).toBe(base);
    expect(second.firstObservedAt).toBe(base);
  });

  it('lets resumed progress win over an overdue warming display', () => {
    const testStorage = storage();
    const input = {
      runId: 'run-resumed',
      startupId: 'startup-resumed',
      isWarming: true,
      storage: testStorage,
      gpuStatus: freshStopped,
    } as const;
    const bound = WARMING_OBSERVATION_LIMIT_MS + WARMING_OBSERVATION_GRACE_MS;

    deriveWarmingObservation({ ...input, now: base });
    const result = deriveWarmingObservation({
      ...input,
      now: base + bound,
      resumedProgress: true,
    });

    expect(result.status).toBe(WARMING_OBSERVATION_STATUS.WAITING);
    expect(result.evidence).toBe(WARMING_OBSERVATION_EVIDENCE.PROGRESS);
  });
});
