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
    STALL_TICK: JOB_MACHINE_STATE.offline,
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
  reconnectAttempts: 0,
});

const tableCells = ALL_STATUSES.flatMap((status) =>
  ALL_EVENT_TYPES.map((eventType) => ({
    status,
    eventType,
    expected: EXPECTED_STATUS[status][eventType],
  })),
);

const dashCells = tableCells.filter((cell) => cell.expected === null);

/** Payload pins for active (non-dash, non-idle) table cells. Idle cells use initialJobState. */
const assertActiveTransitionPayload = (
  state: JobMachineState,
  event: JobEvent,
  next: JobMachineState,
): void => {
  switch (event.type) {
    case JOB_EVENT.START:
      expect(next.jobId).toBe(event.jobId);
      expect(next.done).toBe(0);
      expect(next.total).toBe(0);
      expect(next.lastEventAt).toBe(event.at);
      expect(next.reconnectAttempts).toBe(0);
      expect(next.failedCount).toBe(0);
      expect(next.error).toBeNull();
      expect(next.resumeStatus).toBeNull();
      return;
    case JOB_EVENT.STREAM_OPEN:
      expect(next.lastEventAt).toBe(event.at);
      expect(next.done).toBe(state.done);
      expect(next.total).toBe(state.total);
      expect(next.jobId).toBe(state.jobId);
      return;
    case JOB_EVENT.PROGRESS:
      expect(next.done).toBe(event.done);
      expect(next.total).toBe(event.total);
      expect(next.lastEventAt).toBe(event.at);
      expect(next.jobId).toBe(state.jobId);
      expect(next.reconnectAttempts).toBe(0);
      return;
    case JOB_EVENT.STALL_TICK:
      expect(next.lastEventAt).toBe(event.now);
      expect(next.reconnectAttempts).toBe(state.reconnectAttempts + 1);
      expect(next.done).toBe(state.done);
      expect(next.total).toBe(state.total);
      expect(next.jobId).toBe(state.jobId);
      return;
    case JOB_EVENT.RECONNECTED:
      expect(next.lastEventAt).toBe(event.at);
      expect(next.done).toBe(state.done);
      expect(next.total).toBe(state.total);
      expect(next.jobId).toBe(state.jobId);
      return;
    case JOB_EVENT.OFFLINE:
      expect(next.lastEventAt).toBe(event.at);
      expect(next.resumeStatus).toBe(state.status);
      expect(next.done).toBe(state.done);
      expect(next.total).toBe(state.total);
      expect(next.jobId).toBe(state.jobId);
      return;
    case JOB_EVENT.ONLINE:
      expect(next.lastEventAt).toBe(event.at);
      expect(next.resumeStatus).toBeNull();
      expect(next.reconnectAttempts).toBe(0);
      expect(next.status).toBe(state.resumeStatus);
      expect(next.done).toBe(state.done);
      expect(next.total).toBe(state.total);
      return;
    case JOB_EVENT.COMPLETE:
      expect(next.lastEventAt).toBe(event.at);
      expect(next.resumeStatus).toBeNull();
      expect(next.done).toBe(state.done);
      expect(next.total).toBe(state.total);
      expect(next.jobId).toBe(state.jobId);
      return;
    case JOB_EVENT.COMPLETE_WITH_ERRORS:
      expect(next.failedCount).toBe(event.failedCount);
      expect(next.lastEventAt).toBe(event.at);
      expect(next.resumeStatus).toBeNull();
      expect(next.done).toBe(state.done);
      expect(next.total).toBe(state.total);
      return;
    case JOB_EVENT.FAIL:
      expect(next.error).toEqual(event.error);
      expect(next.resumeStatus).toBeNull();
      expect(next.done).toBe(state.done);
      expect(next.total).toBe(state.total);
      return;
    case JOB_EVENT.CANCEL:
    case JOB_EVENT.RESET:
      expect(next).toEqual(initialJobState);
      return;
    default: {
      const _exhaustive: never = event;
      throw new Error(`unhandled table event: ${JSON.stringify(_exhaustive)}`);
    }
  }
};

describe('jobReducer table (FEBT-1 L6a)', () => {
  it.each(tableCells)('$status + $eventType => $expected', ({ status, eventType, expected }) => {
    const state = fixtureFor(status);
    const event = SAMPLE_EVENTS[eventType];
    const next = jobReducer(state, event);
    if (expected === JOB_MACHINE_STATE.idle) {
      expect(next).toEqual(initialJobState);
      return;
    }
    expect(next.status).toBe(expected ?? status);
    if (expected !== null) {
      assertActiveTransitionPayload(state, event, next);
    }
  });

  it.each(dashCells)('dash cell $status + $eventType returns the same state object', ({ status, eventType }) => {
    const state = fixtureFor(status);
    expect(jobReducer(state, SAMPLE_EVENTS[eventType])).toBe(state);
  });

  it('CANCEL from running with non-zero payload equals initialJobState (FEBT1-W2C-11)', () => {
    const state: JobMachineState = {
      ...fixtureFor(JOB_MACHINE_STATE.running),
      done: 7,
      total: 20,
      reconnectAttempts: 2,
    };
    expect(jobReducer(state, { type: JOB_EVENT.CANCEL })).toEqual(initialJobState);
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

  it('STALL_TICK with now before lastEventAt neither fails nor advances the counter (FEBT1-W2C-12)', () => {
    const state: JobMachineState = {
      ...fixtureFor(JOB_MACHINE_STATE.running),
      reconnectAttempts: 2,
    };
    const rewound = AT - 1;
    const next = jobReducer(state, { type: JOB_EVENT.STALL_TICK, now: rewound });
    expect(next.status).toBe(JOB_MACHINE_STATE.running);
    expect(next.reconnectAttempts).toBe(2);
    expect(next.error).toBeNull();
    expect(next.lastEventAt).toBe(rewound);

    const stalled = jobReducer(next, {
      type: JOB_EVENT.STALL_TICK,
      now: rewound + JOB_MACHINE_STALL_THRESHOLD_MS,
    });
    expect(stalled.status).toBe(JOB_MACHINE_STATE.stalled);
    expect(stalled.reconnectAttempts).toBe(3);
  });

  it('STALL_TICK delta of MAX_TICK_DELTA_MS + 1 clamps lastEventAt without stalling (FEBT1-W2C-12)', () => {
    const state: JobMachineState = {
      ...fixtureFor(JOB_MACHINE_STATE.running),
      reconnectAttempts: 2,
    };
    const now = AT + JOB_MACHINE_MAX_TICK_DELTA_MS + 1;
    const next = jobReducer(state, { type: JOB_EVENT.STALL_TICK, now });
    expect(next.status).toBe(JOB_MACHINE_STATE.running);
    expect(next.reconnectAttempts).toBe(2);
    expect(next.error).toBeNull();
    expect(next.lastEventAt).toBe(now);
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

  it('PROGRESS from reconnectAttempts: 2 resets the counter to 0 (FEBT1-W2C-10)', () => {
    const state: JobMachineState = {
      ...fixtureFor(JOB_MACHINE_STATE.running),
      reconnectAttempts: 2,
    };
    const next = jobReducer(state, { type: JOB_EVENT.PROGRESS, done: 7, total: 20, at: 9_000 });
    expect(next.reconnectAttempts).toBe(0);
    expect(next.status).toBe(JOB_MACHINE_STATE.running);

    const stalled = jobReducer(next, {
      type: JOB_EVENT.STALL_TICK,
      now: 9_000 + JOB_MACHINE_STALL_THRESHOLD_MS,
    });
    expect(stalled.status).toBe(JOB_MACHINE_STATE.stalled);
    expect(stalled.reconnectAttempts).toBe(1);
  });

  it('PROGRESS refreshes lastEventAt to the event at timestamp (FEBT1-W2C-10)', () => {
    const state: JobMachineState = {
      ...fixtureFor(JOB_MACHINE_STATE.running),
      lastEventAt: AT,
    };
    const at = 77_000;
    const next = jobReducer(state, { type: JOB_EVENT.PROGRESS, done: 1, total: 2, at });
    expect(next.lastEventAt).toBe(at);
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
      expect(stalled.lastEventAt).toBe(t + 330_002);
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

  describe('M-03 reconnect ceiling', () => {
    it('stays stalled below the ceiling and fails when the ceiling is crossed', () => {
      let state = jobReducer(fixtureFor(JOB_MACHINE_STATE.running), {
        type: JOB_EVENT.STALL_TICK,
        now: AT + 30_000,
      });
      expect(state.status).toBe(JOB_MACHINE_STATE.stalled);

      state = jobReducer(state, { type: JOB_EVENT.STALL_TICK, now: AT + 60_000 });
      expect(state.status).toBe(JOB_MACHINE_STATE.stalled);

      state = jobReducer(state, { type: JOB_EVENT.STALL_TICK, now: AT + 90_000 });
      expect(state.status).toBe(JOB_MACHINE_STATE.stalled);

      state = jobReducer(state, { type: JOB_EVENT.STALL_TICK, now: AT + 120_000 });
      expect(state.status).toBe(JOB_MACHINE_STATE.failed);
      expect(state.error).not.toBeNull();
      expect(state.error?.message.toLowerCase()).toContain('reconnect');
    });

    it('ONLINE resets the reconnect counter so the next stall does not fail immediately', () => {
      let state = jobReducer(fixtureFor(JOB_MACHINE_STATE.running), {
        type: JOB_EVENT.STALL_TICK,
        now: AT + 30_000,
      });
      state = jobReducer(state, { type: JOB_EVENT.STALL_TICK, now: AT + 60_000 });
      state = jobReducer(state, { type: JOB_EVENT.STALL_TICK, now: AT + 90_000 });
      expect(state.status).toBe(JOB_MACHINE_STATE.stalled);

      const offline = jobReducer(state, offlineEvent(AT + 91_000));
      const online = jobReducer(offline, onlineEvent(AT + 92_000));
      const stalledAgain = jobReducer(online, { type: JOB_EVENT.STALL_TICK, now: AT + 122_000 });
      expect(stalledAgain.status).toBe(JOB_MACHINE_STATE.stalled);
      expect(stalledAgain.error).toBeNull();
    });
  });

  describe('M-04 pending stall and bounded offline wait', () => {
    it('STALL_TICK from pending stalls after 30s quiet', () => {
      const pending = fixtureFor(JOB_MACHINE_STATE.pending);
      const next = jobReducer(pending, { type: JOB_EVENT.STALL_TICK, now: AT + 30_000 });
      expect(next.status).toBe(JOB_MACHINE_STATE.stalled);
    });

    it('an offline pending job fails after the reconnect ceiling of quiet ticks', () => {
      const pending = fixtureFor(JOB_MACHINE_STATE.pending);
      let state = jobReducer(pending, offlineEvent(AT));
      expect(state.status).toBe(JOB_MACHINE_STATE.offline);

      state = jobReducer(state, { type: JOB_EVENT.STALL_TICK, now: AT + 30_000 });
      expect(state.status).toBe(JOB_MACHINE_STATE.offline);

      state = jobReducer(state, { type: JOB_EVENT.STALL_TICK, now: AT + 60_000 });
      expect(state.status).toBe(JOB_MACHINE_STATE.offline);

      state = jobReducer(state, { type: JOB_EVENT.STALL_TICK, now: AT + 90_000 });
      expect(state.status).toBe(JOB_MACHINE_STATE.offline);

      state = jobReducer(state, { type: JOB_EVENT.STALL_TICK, now: AT + 120_000 });
      expect(state.status).toBe(JOB_MACHINE_STATE.failed);
      expect(state.error).not.toBeNull();
    });
  });

  describe('M-05 clock discontinuity', () => {
    it('does not stall on a 6-hour jump in one tick', () => {
      const state = fixtureFor(JOB_MACHINE_STATE.running);
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
