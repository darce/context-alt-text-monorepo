import { describe, expect, it } from 'vitest';

import {
  JOB_EVENT,
  JOB_MACHINE_MAX_TICK_DELTA_MS,
  JOB_MACHINE_RECONNECT_CEILING,
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
  [JOB_EVENT.RECONNECTING]: true,
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
  RECONNECTING: { type: JOB_EVENT.RECONNECTING, at: AT },
  RECONNECTED: { type: JOB_EVENT.RECONNECTED, at: AT },
  OFFLINE: { type: JOB_EVENT.OFFLINE, at: AT },
  ONLINE: { type: JOB_EVENT.ONLINE, at: AT },
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
    RECONNECTING: null,
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
    STALL_TICK: JOB_MACHINE_STATE.stalled,
    RECONNECTING: JOB_MACHINE_STATE.pending,
    RECONNECTED: JOB_MACHINE_STATE.running,
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
    RECONNECTING: JOB_MACHINE_STATE.running,
    RECONNECTED: JOB_MACHINE_STATE.running,
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
    RECONNECTING: JOB_MACHINE_STATE.stalled,
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
    RECONNECTING: JOB_MACHINE_STATE.offline,
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
    RECONNECTING: null,
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
    RECONNECTING: null,
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
    RECONNECTING: null,
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
  reconnectAttempts: 0,
  lastTickAt: null,
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
    expect(below).toEqual({ ...state, lastTickAt: AT + JOB_MACHINE_STALL_THRESHOLD_MS - 1 });

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
      const offline = jobReducer(state, { type: JOB_EVENT.OFFLINE, at: AT });
      expect(offline.status).toBe(JOB_MACHINE_STATE.offline);
      expect(offline.resumeStatus).toBe(status);

      const restored = jobReducer(offline, { type: JOB_EVENT.ONLINE, at: AT });
      expect(restored.status).toBe(status);
      expect(restored.resumeStatus).toBeNull();
    },
  );

  it.each(ALL_STATUSES.filter((status) => status !== JOB_MACHINE_STATE.offline))(
    'ONLINE in non-offline status %s is identity',
    (status) => {
      const state = fixtureFor(status);
      expect(jobReducer(state, { type: JOB_EVENT.ONLINE, at: AT })).toBe(state);
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
      reconnectAttempts: 0,
      lastTickAt: null,
    });
  });
});

const offlineEvent = (at: number): JobEvent => ({ type: JOB_EVENT.OFFLINE, at });
const onlineEvent = (at: number): JobEvent => ({ type: JOB_EVENT.ONLINE, at });

describe('FEBT-1 W1 fix lane (L6A-01, M-01..M-06)', () => {
  describe('L6A-01 offline/online timestamps', () => {
    it('does not stall one millisecond after a 5-minute offline window, then stalls 30s later', () => {
      const t = AT;
      const running = fixtureFor(JOB_MACHINE_STATE.running);
      const offline = jobReducer(running, offlineEvent(t));
      const online = jobReducer(offline, onlineEvent(t + 300_000));

      const immediate = jobReducer(online, { type: JOB_EVENT.STALL_TICK, now: t + 300_001 });
      expect(immediate.status).toBe(JOB_MACHINE_STATE.running);

      const later = jobReducer(immediate, { type: JOB_EVENT.STALL_TICK, now: t + 330_002 });
      expect(later.status).toBe(JOB_MACHINE_STATE.stalled);
    });
  });

  describe('M-01 handler writes', () => {
    it('START writes lastEventAt and clears resumeStatus', () => {
      const state = fixtureFor(JOB_MACHINE_STATE.idle);
      const next = jobReducer(state, { type: JOB_EVENT.START, jobId: 'job-9', at: 4_000 });
      expect(next.lastEventAt).toBe(4_000);
      expect(next.resumeStatus).toBeNull();
    });

    it('STREAM_OPEN writes lastEventAt', () => {
      const state = fixtureFor(JOB_MACHINE_STATE.pending);
      const next = jobReducer(state, { type: JOB_EVENT.STREAM_OPEN, at: 8_000 });
      expect(next.lastEventAt).toBe(8_000);
    });

    it('PROGRESS writes lastEventAt', () => {
      const state = fixtureFor(JOB_MACHINE_STATE.running);
      const next = jobReducer(state, { type: JOB_EVENT.PROGRESS, done: 7, total: 20, at: 9_000 });
      expect(next.lastEventAt).toBe(9_000);
    });

    it('RECONNECTED writes lastEventAt', () => {
      const state = fixtureFor(JOB_MACHINE_STATE.stalled);
      const next = jobReducer(state, { type: JOB_EVENT.RECONNECTED, at: 11_000 });
      expect(next.lastEventAt).toBe(11_000);
    });

    it('COMPLETE writes lastEventAt and clears resumeStatus', () => {
      const state = { ...fixtureFor(JOB_MACHINE_STATE.running), resumeStatus: JOB_MACHINE_STATE.running };
      const next = jobReducer(state, { type: JOB_EVENT.COMPLETE, at: 12_000 });
      expect(next.lastEventAt).toBe(12_000);
      expect(next.resumeStatus).toBeNull();
    });

    it('COMPLETE_WITH_ERRORS writes lastEventAt and clears resumeStatus', () => {
      const state = { ...fixtureFor(JOB_MACHINE_STATE.running), resumeStatus: JOB_MACHINE_STATE.running };
      const next = jobReducer(state, { type: JOB_EVENT.COMPLETE_WITH_ERRORS, failedCount: 2, at: 13_000 });
      expect(next.lastEventAt).toBe(13_000);
      expect(next.resumeStatus).toBeNull();
    });

    it('FAIL clears resumeStatus', () => {
      const state = { ...fixtureFor(JOB_MACHINE_STATE.running), resumeStatus: JOB_MACHINE_STATE.running };
      const next = jobReducer(state, { type: JOB_EVENT.FAIL, error: { message: 'nope' } });
      expect(next.resumeStatus).toBeNull();
    });

    it('OFFLINE writes lastEventAt from event.at and stores resumeStatus', () => {
      const state = fixtureFor(JOB_MACHINE_STATE.running);
      const next = jobReducer(state, offlineEvent(5_000));
      expect(next.lastEventAt).toBe(5_000);
      expect(next.resumeStatus).toBe(JOB_MACHINE_STATE.running);
    });

    it('ONLINE writes lastEventAt from event.at and clears resumeStatus', () => {
      const offline = jobReducer(fixtureFor(JOB_MACHINE_STATE.running), offlineEvent(5_000));
      const next = jobReducer(offline, onlineEvent(8_000));
      expect(next.lastEventAt).toBe(8_000);
      expect(next.resumeStatus).toBeNull();
    });

    it('RESET writes lastEventAt null and resumeStatus null', () => {
      const next = jobReducer(fixtureFor(JOB_MACHINE_STATE.running), { type: JOB_EVENT.RESET });
      expect(next.lastEventAt).toBeNull();
      expect(next.resumeStatus).toBeNull();
    });

    it('offline → online → stall writes lastEventAt and resumeStatus at each step', () => {
      const t = AT;
      const running = fixtureFor(JOB_MACHINE_STATE.running);

      const offline = jobReducer(running, offlineEvent(t));
      expect(offline.status).toBe(JOB_MACHINE_STATE.offline);
      expect(offline.resumeStatus).toBe(JOB_MACHINE_STATE.running);
      expect(offline.lastEventAt).toBe(t);

      const online = jobReducer(offline, onlineEvent(t + 300_000));
      expect(online.status).toBe(JOB_MACHINE_STATE.running);
      expect(online.resumeStatus).toBeNull();
      expect(online.lastEventAt).toBe(t + 300_000);

      const notYet = jobReducer(online, { type: JOB_EVENT.STALL_TICK, now: t + 300_001 });
      expect(notYet.status).toBe(JOB_MACHINE_STATE.running);
      expect(notYet.lastEventAt).toBe(t + 300_000);
      expect(notYet.resumeStatus).toBeNull();

      const stalled = jobReducer(notYet, { type: JOB_EVENT.STALL_TICK, now: t + 330_002 });
      expect(stalled.status).toBe(JOB_MACHINE_STATE.stalled);
      // A quiet tick observes; it does not re-timestamp. lastEventAt still points at the
      // last real event so quiet duration keeps growing.
      expect(stalled.lastEventAt).toBe(t + 300_000);
      expect(stalled.resumeStatus).toBeNull();
    });
  });

  describe('M-02 stall threshold pin', () => {
    it('pins JOB_MACHINE_STALL_THRESHOLD_MS to 30_000', () => {
      expect(JOB_MACHINE_STALL_THRESHOLD_MS).toBe(30_000);
    });

    it('pins JOB_MACHINE_RECONNECT_CEILING to 3 and MAX_TICK_DELTA_MS to 120_000', () => {
      expect(JOB_MACHINE_RECONNECT_CEILING).toBe(3);
      expect(JOB_MACHINE_MAX_TICK_DELTA_MS).toBe(120_000);
    });

    it('stalls after a literal 30_000 ms quiet interval and not after 29_999', () => {
      const state = fixtureFor(JOB_MACHINE_STATE.running);
      const below = jobReducer(state, { type: JOB_EVENT.STALL_TICK, now: AT + 29_999 });
      expect(below.status).toBe(JOB_MACHINE_STATE.running);

      const atThreshold = jobReducer(state, { type: JOB_EVENT.STALL_TICK, now: AT + 30_000 });
      expect(atThreshold.status).toBe(JOB_MACHINE_STATE.stalled);
    });
  });

  describe('M-03 reconnect ceiling counts real reconnects, never quiet time', () => {
    it('never fails from quiet ticks alone, however long the silence runs', () => {
      let state = jobReducer(fixtureFor(JOB_MACHINE_STATE.running), {
        type: JOB_EVENT.STALL_TICK,
        now: AT + 30_000,
      });
      expect(state.status).toBe(JOB_MACHINE_STATE.stalled);

      // 10 minutes of silence on an OPEN stream (burst-GPU warmup, one very large image).
      // Nothing reconnected, so nothing may be counted against the reconnect ceiling.
      for (let now = AT + 60_000; now <= AT + 600_000; now += 30_000) {
        state = jobReducer(state, { type: JOB_EVENT.STALL_TICK, now });
      }
      expect(state.status).toBe(JOB_MACHINE_STATE.stalled);
      expect(state.error).toBeNull();
      expect(state.reconnectAttempts).toBe(0);
      // lastEventAt is never re-stamped by a tick, so the quiet window is still measurable.
      expect(state.lastEventAt).toBe(AT);
    });

    it('counts one attempt per RECONNECTING and fails only when the ceiling is crossed', () => {
      let state = fixtureFor(JOB_MACHINE_STATE.stalled);
      for (let attempt = 1; attempt <= JOB_MACHINE_RECONNECT_CEILING; attempt += 1) {
        state = jobReducer(state, { type: JOB_EVENT.RECONNECTING, at: AT + attempt });
        expect(state.status).toBe(JOB_MACHINE_STATE.stalled);
        expect(state.reconnectAttempts).toBe(attempt);
      }

      state = jobReducer(state, { type: JOB_EVENT.RECONNECTING, at: AT + 99 });
      expect(state.status).toBe(JOB_MACHINE_STATE.failed);
      expect(state.error?.message.toLowerCase()).toContain('reconnect');
      // The message must state the attempts actually made, not the constant.
      expect(state.error?.message).toContain(String(JOB_MACHINE_RECONNECT_CEILING + 1));
    });

    it('a successful RECONNECTED clears the breaker so the next outage gets a full budget', () => {
      let state = fixtureFor(JOB_MACHINE_STATE.stalled);
      state = jobReducer(state, { type: JOB_EVENT.RECONNECTING, at: AT + 1 });
      state = jobReducer(state, { type: JOB_EVENT.RECONNECTING, at: AT + 2 });
      expect(state.reconnectAttempts).toBe(2);

      state = jobReducer(state, { type: JOB_EVENT.RECONNECTED, at: AT + 3 });
      expect(state.status).toBe(JOB_MACHINE_STATE.running);
      expect(state.reconnectAttempts).toBe(0);

      for (let attempt = 1; attempt <= JOB_MACHINE_RECONNECT_CEILING; attempt += 1) {
        state = jobReducer(state, { type: JOB_EVENT.RECONNECTING, at: AT + 10 + attempt });
      }
      expect(state.status).not.toBe(JOB_MACHINE_STATE.failed);
    });

    it('ONLINE resets the reconnect counter so the next outage gets a full budget', () => {
      let state = fixtureFor(JOB_MACHINE_STATE.running);
      state = jobReducer(state, { type: JOB_EVENT.RECONNECTING, at: AT + 1 });
      state = jobReducer(state, { type: JOB_EVENT.RECONNECTING, at: AT + 2 });
      expect(state.reconnectAttempts).toBe(2);

      const offline = jobReducer(state, offlineEvent(AT + 91_000));
      const online = jobReducer(offline, onlineEvent(AT + 92_000));
      expect(online.reconnectAttempts).toBe(0);
      expect(online.error).toBeNull();
    });

    it('[FEBT1-W2C-10] PROGRESS resets reconnectAttempts, proving the transport is healthy', () => {
      const stalledAfterRetries: JobMachineState = {
        ...fixtureFor(JOB_MACHINE_STATE.stalled),
        reconnectAttempts: 2,
      };

      const resumed = jobReducer(stalledAfterRetries, {
        type: JOB_EVENT.PROGRESS,
        done: 6,
        total: 10,
        at: AT + 5_000,
      });
      expect(resumed.status).toBe(JOB_MACHINE_STATE.running);
      expect(resumed.reconnectAttempts).toBe(0);

      // Without the reset, these two attempts would land on 3 and 4 and cross the ceiling.
      let after = jobReducer(resumed, { type: JOB_EVENT.RECONNECTING, at: AT + 6_000 });
      after = jobReducer(after, { type: JOB_EVENT.RECONNECTING, at: AT + 7_000 });
      expect(after.status).not.toBe(JOB_MACHINE_STATE.failed);
      expect(after.reconnectAttempts).toBe(2);
    });

    it('[FEBT1-W2C-10] START resets reconnectAttempts for the new job', () => {
      const dirty: JobMachineState = { ...fixtureFor(JOB_MACHINE_STATE.failed), reconnectAttempts: 3 };
      const next = jobReducer(dirty, { type: JOB_EVENT.START, jobId: 'job-fresh', at: AT });
      expect(next.reconnectAttempts).toBe(0);
    });
  });

  describe('M-04 pending stall and bounded offline wait', () => {
    it('STALL_TICK from pending stalls after 30s quiet', () => {
      const pending = fixtureFor(JOB_MACHINE_STATE.pending);
      const next = jobReducer(pending, { type: JOB_EVENT.STALL_TICK, now: AT + 30_000 });
      expect(next.status).toBe(JOB_MACHINE_STATE.stalled);
    });

    it('[FEBT1-GATE-02] an offline wait is never ended by quiet time', () => {
      const pending = fixtureFor(JOB_MACHINE_STATE.pending);
      let state = jobReducer(pending, offlineEvent(AT));
      expect(state.status).toBe(JOB_MACHINE_STATE.offline);

      for (let now = AT + 30_000; now <= AT + 600_000; now += 30_000) {
        state = jobReducer(state, { type: JOB_EVENT.STALL_TICK, now });
      }
      // Losing wifi must not fail a job that is still running server-side.
      expect(state.status).toBe(JOB_MACHINE_STATE.offline);
      expect(state.error).toBeNull();

      const online = jobReducer(state, onlineEvent(AT + 601_000));
      expect(online.status).toBe(JOB_MACHINE_STATE.pending);
    });

    it('[FEBT1-GATE-02] an offline wait IS bounded by real reconnect attempts', () => {
      let state = jobReducer(fixtureFor(JOB_MACHINE_STATE.pending), offlineEvent(AT));
      for (let attempt = 1; attempt <= JOB_MACHINE_RECONNECT_CEILING; attempt += 1) {
        state = jobReducer(state, { type: JOB_EVENT.RECONNECTING, at: AT + attempt });
        expect(state.status).toBe(JOB_MACHINE_STATE.offline);
      }
      state = jobReducer(state, { type: JOB_EVENT.RECONNECTING, at: AT + 50 });
      expect(state.status).toBe(JOB_MACHINE_STATE.failed);
      expect(state.error).not.toBeNull();
    });
  });

  describe('M-04b payload-level transitions (FEBT1-W2C-11)', () => {
    // The status-only table cannot see a CANCEL that leaks the previous job's payload:
    // a mutant returning { ...state, status: idle } keeps jobId/done/total/error.
    it.each(
      ALL_STATUSES.filter(
        (status) => EXPECTED_STATUS[status][JOB_EVENT.CANCEL] === JOB_MACHINE_STATE.idle,
      ),
    )('CANCEL from %s clears every payload field, not just the status', (status) => {
      const dirty: JobMachineState = {
        ...fixtureFor(status),
        reconnectAttempts: 2,
        failedCount: 4,
        error: { message: 'prior' },
      };
      expect(jobReducer(dirty, { type: JOB_EVENT.CANCEL })).toEqual(initialJobState);
    });

    it.each(
      ALL_STATUSES.filter(
        (status) => EXPECTED_STATUS[status][JOB_EVENT.RESET] === JOB_MACHINE_STATE.idle,
      ),
    )('RESET from %s clears every payload field, not just the status', (status) => {
      const dirty: JobMachineState = {
        ...fixtureFor(status),
        reconnectAttempts: 2,
        failedCount: 4,
        error: { message: 'prior' },
      };
      expect(jobReducer(dirty, { type: JOB_EVENT.RESET })).toEqual(initialJobState);
    });

    it('START from a dirty terminal state clears the previous run payload', () => {
      const dirty: JobMachineState = {
        ...fixtureFor(JOB_MACHINE_STATE.completedWithErrors),
        error: { message: 'prior' },
        reconnectAttempts: 3,
      };
      expect(jobReducer(dirty, { type: JOB_EVENT.START, jobId: 'job-next', at: AT })).toEqual({
        ...initialJobState,
        status: JOB_MACHINE_STATE.pending,
        jobId: 'job-next',
        lastEventAt: AT,
      });
    });

    it('COMPLETE_WITH_ERRORS without a wire count keeps the known count instead of inventing 0', () => {
      const state: JobMachineState = { ...fixtureFor(JOB_MACHINE_STATE.running), failedCount: 7 };
      const next = jobReducer(state, { type: JOB_EVENT.COMPLETE_WITH_ERRORS, at: AT });
      expect(next.status).toBe(JOB_MACHINE_STATE.completedWithErrors);
      expect(next.failedCount).toBe(7);
    });
  });

  describe('M-05 clock discontinuity', () => {
    it('[FEBT1-W2C-12] a clock rewind rebases instead of stalling or ticking backwards', () => {
      const state: JobMachineState = { ...fixtureFor(JOB_MACHINE_STATE.running), lastTickAt: AT };
      const rewound = jobReducer(state, { type: JOB_EVENT.STALL_TICK, now: AT - 1 });
      expect(rewound.status).toBe(JOB_MACHINE_STATE.running);
      expect(rewound.lastEventAt).toBe(AT - 1);

      const after = jobReducer(rewound, { type: JOB_EVENT.STALL_TICK, now: AT - 1 + 31_000 });
      expect(after.status).toBe(JOB_MACHINE_STATE.stalled);
    });

    it('[FEBT1-W2C-12] a large backwards jump also rebases rather than stalling', () => {
      const state: JobMachineState = { ...fixtureFor(JOB_MACHINE_STATE.running), lastTickAt: AT };
      const rewound = jobReducer(state, { type: JOB_EVENT.STALL_TICK, now: AT - 3_600_000 });
      expect(rewound.status).toBe(JOB_MACHINE_STATE.running);
      expect(rewound.lastEventAt).toBe(AT - 3_600_000);
    });

    it('does not stall on a 6-hour jump between two consecutive ticks', () => {
      // The ticker has already run once (lastTickAt), then the machine slept for 6h.
      const state: JobMachineState = { ...fixtureFor(JOB_MACHINE_STATE.running), lastTickAt: AT };
      const sixHours = AT + 6 * 60 * 60 * 1000;
      const jumped = jobReducer(state, { type: JOB_EVENT.STALL_TICK, now: sixHours });
      expect(jumped.status).toBe(JOB_MACHINE_STATE.running);

      const after = jobReducer(jumped, { type: JOB_EVENT.STALL_TICK, now: sixHours + 31_000 });
      expect(after.status).toBe(JOB_MACHINE_STATE.stalled);
    });

    it('two consecutive 31s-quiet ticks still stall', () => {
      const state = fixtureFor(JOB_MACHINE_STATE.running);
      const first = jobReducer(state, { type: JOB_EVENT.STALL_TICK, now: AT + 31_000 });
      expect(first.status).toBe(JOB_MACHINE_STATE.stalled);

      const second = jobReducer(first, { type: JOB_EVENT.STALL_TICK, now: AT + 62_000 });
      expect(second.status).toBe(JOB_MACHINE_STATE.stalled);
    });
  });

  describe('M-06 RESET pin', () => {
    it('RESET from idle is deep-equal to initialJobState', () => {
      const next = jobReducer(fixtureFor(JOB_MACHINE_STATE.idle), { type: JOB_EVENT.RESET });
      expect(next).toEqual(initialJobState);
    });
  });
});
