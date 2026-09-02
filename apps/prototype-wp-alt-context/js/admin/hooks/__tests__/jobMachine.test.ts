import { describe, expect, it } from 'vitest';

import {
  JOB_EVENT,
  JOB_MACHINE_STALL_THRESHOLD_MS,
  JOB_MACHINE_STATE,
  initialJobState,
  isTerminalJobState,
  jobReducer,
  type JobEvent,
  type JobMachineState,
  type JobMachineStatus,
} from '../jobMachine';

const AT = 1_000;

const _all: Record<JobMachineStatus, true> = {
  [JOB_MACHINE_STATE.idle]: true,
  [JOB_MACHINE_STATE.pending]: true,
  [JOB_MACHINE_STATE.running]: true,
  [JOB_MACHINE_STATE.stalled]: true,
  [JOB_MACHINE_STATE.offline]: true,
  [JOB_MACHINE_STATE.completed]: true,
  [JOB_MACHINE_STATE.completedWithErrors]: true,
  [JOB_MACHINE_STATE.failed]: true,
};

const _events: Record<JobEvent['type'], true> = {
  [JOB_EVENT.START]: true,
  [JOB_EVENT.STREAM_OPEN]: true,
  [JOB_EVENT.PROGRESS]: true,
  [JOB_EVENT.STALL_TICK]: true,
  [JOB_EVENT.RECONNECTED]: true,
  [JOB_EVENT.OFFLINE]: true,
  [JOB_EVENT.ONLINE]: true,
  [JOB_EVENT.COMPLETE]: true,
  [JOB_EVENT.COMPLETE_WITH_ERRORS]: true,
  [JOB_EVENT.FAIL]: true,
  [JOB_EVENT.CANCEL]: true,
  [JOB_EVENT.RESET]: true,
};

const ALL_STATUSES = Object.keys(_all) as JobMachineStatus[];
const ALL_EVENT_TYPES = Object.keys(_events) as JobEvent['type'][];

const SAMPLE_EVENTS: { readonly [E in JobEvent['type']]: Extract<JobEvent, { type: E }> } = {
  START: { type: JOB_EVENT.START, jobId: 'job-2', at: AT },
  STREAM_OPEN: { type: JOB_EVENT.STREAM_OPEN, at: AT },
  PROGRESS: { type: JOB_EVENT.PROGRESS, done: 4, total: 12, at: AT },
  STALL_TICK: { type: JOB_EVENT.STALL_TICK, now: AT + JOB_MACHINE_STALL_THRESHOLD_MS },
  RECONNECTED: { type: JOB_EVENT.RECONNECTED, at: AT },
  OFFLINE: { type: JOB_EVENT.OFFLINE },
  ONLINE: { type: JOB_EVENT.ONLINE },
  COMPLETE: { type: JOB_EVENT.COMPLETE, at: AT },
  COMPLETE_WITH_ERRORS: { type: JOB_EVENT.COMPLETE_WITH_ERRORS, failedCount: 3, at: AT },
  FAIL: { type: JOB_EVENT.FAIL, error: { message: 'boom' } },
  CANCEL: { type: JOB_EVENT.CANCEL },
  RESET: { type: JOB_EVENT.RESET },
};

/** `null` means a doc-table dash (`—`): no-op identity. */
const EXPECTED_STATUS: Record<JobMachineStatus, Record<JobEvent['type'], JobMachineStatus | null>> = {
  [JOB_MACHINE_STATE.idle]: {
    START: JOB_MACHINE_STATE.pending,
    STREAM_OPEN: null,
    PROGRESS: null,
    STALL_TICK: null,
    RECONNECTED: null,
    OFFLINE: JOB_MACHINE_STATE.offline,
    ONLINE: null,
    COMPLETE: null,
    COMPLETE_WITH_ERRORS: null,
    FAIL: null,
    CANCEL: null,
    RESET: JOB_MACHINE_STATE.idle,
  },
  [JOB_MACHINE_STATE.pending]: {
    START: null,
    STREAM_OPEN: JOB_MACHINE_STATE.running,
    PROGRESS: JOB_MACHINE_STATE.running,
    STALL_TICK: null,
    RECONNECTED: null,
    OFFLINE: JOB_MACHINE_STATE.offline,
    ONLINE: null,
    COMPLETE: JOB_MACHINE_STATE.completed,
    COMPLETE_WITH_ERRORS: JOB_MACHINE_STATE.completedWithErrors,
    FAIL: JOB_MACHINE_STATE.failed,
    CANCEL: JOB_MACHINE_STATE.idle,
    RESET: JOB_MACHINE_STATE.idle,
  },
  [JOB_MACHINE_STATE.running]: {
    START: null,
    STREAM_OPEN: null,
    PROGRESS: JOB_MACHINE_STATE.running,
    STALL_TICK: JOB_MACHINE_STATE.stalled,
    RECONNECTED: null,
    OFFLINE: JOB_MACHINE_STATE.offline,
    ONLINE: null,
    COMPLETE: JOB_MACHINE_STATE.completed,
    COMPLETE_WITH_ERRORS: JOB_MACHINE_STATE.completedWithErrors,
    FAIL: JOB_MACHINE_STATE.failed,
    CANCEL: JOB_MACHINE_STATE.idle,
    RESET: JOB_MACHINE_STATE.idle,
  },
  [JOB_MACHINE_STATE.stalled]: {
    START: null,
    STREAM_OPEN: JOB_MACHINE_STATE.running,
    PROGRESS: JOB_MACHINE_STATE.running,
    STALL_TICK: JOB_MACHINE_STATE.stalled,
    RECONNECTED: JOB_MACHINE_STATE.running,
    OFFLINE: JOB_MACHINE_STATE.offline,
    ONLINE: null,
    COMPLETE: JOB_MACHINE_STATE.completed,
    COMPLETE_WITH_ERRORS: JOB_MACHINE_STATE.completedWithErrors,
    FAIL: JOB_MACHINE_STATE.failed,
    CANCEL: JOB_MACHINE_STATE.idle,
    RESET: JOB_MACHINE_STATE.idle,
  },
  [JOB_MACHINE_STATE.offline]: {
    START: null,
    STREAM_OPEN: null,
    PROGRESS: null,
    STALL_TICK: null,
    RECONNECTED: null,
    OFFLINE: null,
    // Fixture resumeStatus is `running`.
    ONLINE: JOB_MACHINE_STATE.running,
    COMPLETE: null,
    COMPLETE_WITH_ERRORS: null,
    FAIL: JOB_MACHINE_STATE.failed,
    CANCEL: JOB_MACHINE_STATE.idle,
    RESET: JOB_MACHINE_STATE.idle,
  },
  [JOB_MACHINE_STATE.completed]: {
    START: JOB_MACHINE_STATE.pending,
    STREAM_OPEN: null,
    PROGRESS: null,
    STALL_TICK: null,
    RECONNECTED: null,
    OFFLINE: null,
    ONLINE: null,
    COMPLETE: null,
    COMPLETE_WITH_ERRORS: null,
    FAIL: null,
    CANCEL: null,
    RESET: JOB_MACHINE_STATE.idle,
  },
  [JOB_MACHINE_STATE.completedWithErrors]: {
    START: JOB_MACHINE_STATE.pending,
    STREAM_OPEN: null,
    PROGRESS: null,
    STALL_TICK: null,
    RECONNECTED: null,
    OFFLINE: null,
    ONLINE: null,
    COMPLETE: null,
    COMPLETE_WITH_ERRORS: null,
    FAIL: null,
    CANCEL: null,
    RESET: JOB_MACHINE_STATE.idle,
  },
  [JOB_MACHINE_STATE.failed]: {
    START: JOB_MACHINE_STATE.pending,
    STREAM_OPEN: null,
    PROGRESS: null,
    STALL_TICK: null,
    RECONNECTED: null,
    OFFLINE: null,
    ONLINE: null,
    COMPLETE: null,
    COMPLETE_WITH_ERRORS: null,
    FAIL: null,
    CANCEL: null,
    RESET: JOB_MACHINE_STATE.idle,
  },
};

const fixtureFor = (status: JobMachineStatus): JobMachineState => ({
  status,
  jobId: 'job-1',
  done: 5,
  total: 10,
  lastEventAt: AT,
  failedCount: status === JOB_MACHINE_STATE.completedWithErrors ? 2 : 0,
  error: status === JOB_MACHINE_STATE.failed ? { message: 'prior' } : null,
  resumeStatus: status === JOB_MACHINE_STATE.offline ? JOB_MACHINE_STATE.running : null,
});

const tableCells = ALL_STATUSES.flatMap((status) =>
  ALL_EVENT_TYPES.map((eventType) => ({
    status,
    eventType,
    expected: EXPECTED_STATUS[status][eventType],
  })),
);

const dashCells = tableCells.filter((cell) => cell.expected === null);

describe('jobReducer table (FEBT-1 L6a)', () => {
  it.each(tableCells)('$status + $eventType => $expected', ({ status, eventType, expected }) => {
    const state = fixtureFor(status);
    const next = jobReducer(state, SAMPLE_EVENTS[eventType]);
    expect(next.status).toBe(expected ?? status);
  });

  it.each(dashCells)('dash cell $status + $eventType returns the same state object', ({ status, eventType }) => {
    const state = fixtureFor(status);
    expect(jobReducer(state, SAMPLE_EVENTS[eventType])).toBe(state);
  });
});

describe('jobReducer stall, progress, offline, terminal', () => {
  it('STALL_TICK below threshold is identity and at exactly the threshold stalls', () => {
    const state = fixtureFor(JOB_MACHINE_STATE.running);
    const below = jobReducer(state, { type: JOB_EVENT.STALL_TICK, now: AT + JOB_MACHINE_STALL_THRESHOLD_MS - 1 });
    expect(below).toBe(state);

    const atThreshold = jobReducer(state, { type: JOB_EVENT.STALL_TICK, now: AT + JOB_MACHINE_STALL_THRESHOLD_MS });
    expect(atThreshold).not.toBe(state);
    expect(atThreshold.status).toBe(JOB_MACHINE_STATE.stalled);

    const noLastEvent = { ...state, lastEventAt: null };
    expect(jobReducer(noLastEvent, { type: JOB_EVENT.STALL_TICK, now: AT + JOB_MACHINE_STALL_THRESHOLD_MS * 4 })).toBe(
      noLastEvent,
    );
  });

  it('PROGRESS updates done/total/lastEventAt and keeps status running', () => {
    const state = fixtureFor(JOB_MACHINE_STATE.running);
    const next = jobReducer(state, { type: JOB_EVENT.PROGRESS, done: 7, total: 20, at: 9_000 });
    expect(next).not.toBe(state);
    expect(next.status).toBe(JOB_MACHINE_STATE.running);
    expect(next.done).toBe(7);
    expect(next.total).toBe(20);
    expect(next.lastEventAt).toBe(9_000);
  });

  it.each([JOB_MACHINE_STATE.pending, JOB_MACHINE_STATE.running, JOB_MACHINE_STATE.stalled] as const)(
    'OFFLINE from %s stores resumeStatus and ONLINE restores it',
    (status) => {
      const state = fixtureFor(status);
      const offline = jobReducer(state, { type: JOB_EVENT.OFFLINE });
      expect(offline.status).toBe(JOB_MACHINE_STATE.offline);
      expect(offline.resumeStatus).toBe(status);

      const restored = jobReducer(offline, { type: JOB_EVENT.ONLINE });
      expect(restored.status).toBe(status);
      expect(restored.resumeStatus).toBeNull();
    },
  );

  it.each(ALL_STATUSES.filter((status) => status !== JOB_MACHINE_STATE.offline))(
    'ONLINE in non-offline status %s is identity',
    (status) => {
      const state = fixtureFor(status);
      expect(jobReducer(state, { type: JOB_EVENT.ONLINE })).toBe(state);
    },
  );

  it.each([
    JOB_MACHINE_STATE.completed,
    JOB_MACHINE_STATE.completedWithErrors,
    JOB_MACHINE_STATE.failed,
  ] as const)('START from terminal %s resets progress fields and sets jobId', (status) => {
    const state = fixtureFor(status);
    const next = jobReducer(state, { type: JOB_EVENT.START, jobId: 'fresh-job', at: 50 });
    expect(next.status).toBe(JOB_MACHINE_STATE.pending);
    expect(next.jobId).toBe('fresh-job');
    expect(next.done).toBe(0);
    expect(next.total).toBe(0);
    expect(next.failedCount).toBe(0);
    expect(next.error).toBeNull();
    expect(next.resumeStatus).toBeNull();
  });

  it('COMPLETE_WITH_ERRORS stores failedCount and FAIL stores error', () => {
    const pending = fixtureFor(JOB_MACHINE_STATE.pending);
    const withErrors = jobReducer(pending, {
      type: JOB_EVENT.COMPLETE_WITH_ERRORS,
      failedCount: 3,
      at: AT,
    });
    expect(withErrors.status).toBe(JOB_MACHINE_STATE.completedWithErrors);
    expect(withErrors.failedCount).toBe(3);

    const failed = jobReducer(pending, { type: JOB_EVENT.FAIL, error: { message: 'nope' } });
    expect(failed.status).toBe(JOB_MACHINE_STATE.failed);
    expect(failed.error).toEqual({ message: 'nope' });
  });
});

describe('isTerminalJobState', () => {
  it.each([
    [JOB_MACHINE_STATE.idle, false],
    [JOB_MACHINE_STATE.pending, false],
    [JOB_MACHINE_STATE.running, false],
    [JOB_MACHINE_STATE.stalled, false],
    [JOB_MACHINE_STATE.offline, false],
    [JOB_MACHINE_STATE.completed, true],
    [JOB_MACHINE_STATE.completedWithErrors, true],
    [JOB_MACHINE_STATE.failed, true],
  ] as const)('%s => %s', (status, expected) => {
    expect(isTerminalJobState(fixtureFor(status))).toBe(expected);
  });
});

describe('compile-time exhaustiveness tables', () => {
  it('covers every JobMachineStatus and JobEvent type exactly once', () => {
    expect(ALL_STATUSES).toEqual(Object.values(JOB_MACHINE_STATE));
    expect(ALL_EVENT_TYPES).toEqual(Object.values(JOB_EVENT));
  });
});

describe('initialJobState', () => {
  it('is idle with empty progress', () => {
    expect(initialJobState).toEqual({
      status: JOB_MACHINE_STATE.idle,
      jobId: null,
      done: 0,
      total: 0,
      lastEventAt: null,
      failedCount: 0,
      error: null,
      resumeStatus: null,
    });
  });
});
