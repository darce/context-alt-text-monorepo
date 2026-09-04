export const JOB_MACHINE_STATE = {
  idle: 'idle',
  pending: 'pending',
  running: 'running',
  stalled: 'stalled',
  offline: 'offline',
  completed: 'completed',
  completedWithErrors: 'completed_with_errors',
  failed: 'failed',
} as const;

export type JobMachineStatus = (typeof JOB_MACHINE_STATE)[keyof typeof JOB_MACHINE_STATE];

export const JOB_MACHINE_STALL_THRESHOLD_MS = 30_000;

/**
 * Max *real* transport reconnect attempts before the job is declared failed (RES-06).
 * Counted only at RECONNECTING (a fresh EventSource is being opened) — never by quiet
 * time. A quiet stream is not a failed stream: silence has no upper bound that the client
 * can distinguish from slow server-side work, so only an explicit terminal frame or a
 * transport that repeatedly fails to re-establish may end a run.
 */
export const JOB_MACHINE_RECONNECT_CEILING = 3;

/**
 * Gap between two *consecutive stall ticks* above this is a clock discontinuity (sleep,
 * NTP step, frozen tab), not observed quiet time. The tick cadence is ~1s, so any gap this
 * large means the ticker itself was suspended and the wall-clock elapsed cannot be trusted
 * as evidence about the stream. Measured tick-to-tick, never event-to-tick: quiet time
 * between real events is legitimately unbounded.
 */
export const JOB_MACHINE_MAX_TICK_DELTA_MS = 120_000;

export interface JobMachineState {
  readonly status: JobMachineStatus;
  readonly jobId: string | null;
  readonly done: number;
  readonly total: number;
  readonly lastEventAt: number | null;
  readonly failedCount: number;
  readonly error: { readonly message: string } | null;
  readonly resumeStatus: Exclude<JobMachineStatus, typeof JOB_MACHINE_STATE.offline> | null;
  readonly reconnectAttempts: number;
  /** Timestamp of the previous STALL_TICK; used only to detect a suspended ticker. */
  readonly lastTickAt: number | null;
}

export const JOB_EVENT = {
  START: 'START',
  STREAM_OPEN: 'STREAM_OPEN',
  PROGRESS: 'PROGRESS',
  STALL_TICK: 'STALL_TICK',
  RECONNECTING: 'RECONNECTING',
  RECONNECTED: 'RECONNECTED',
  OFFLINE: 'OFFLINE',
  ONLINE: 'ONLINE',
  COMPLETE: 'COMPLETE',
  COMPLETE_WITH_ERRORS: 'COMPLETE_WITH_ERRORS',
  FAIL: 'FAIL',
  CANCEL: 'CANCEL',
  RESET: 'RESET',
} as const;

export type JobEvent =
  | { type: typeof JOB_EVENT.START; jobId: string; at: number }
  | { type: typeof JOB_EVENT.STREAM_OPEN; at: number }
  | { type: typeof JOB_EVENT.PROGRESS; done: number; total: number; at: number }
  | { type: typeof JOB_EVENT.STALL_TICK; now: number }
  | { type: typeof JOB_EVENT.RECONNECTING; at: number }
  | { type: typeof JOB_EVENT.RECONNECTED; at: number }
  | { type: typeof JOB_EVENT.OFFLINE; at: number }
  | { type: typeof JOB_EVENT.ONLINE; at: number }
  | { type: typeof JOB_EVENT.COMPLETE; at: number }
  | { type: typeof JOB_EVENT.COMPLETE_WITH_ERRORS; failedCount?: number; at: number }
  | { type: typeof JOB_EVENT.FAIL; error: { message: string } | null }
  | { type: typeof JOB_EVENT.CANCEL }
  | { type: typeof JOB_EVENT.RESET };

export const initialJobState: JobMachineState = {
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
};

const TERMINAL_STATUSES: ReadonlySet<JobMachineStatus> = new Set([
  JOB_MACHINE_STATE.completed,
  JOB_MACHINE_STATE.completedWithErrors,
  JOB_MACHINE_STATE.failed,
]);

export const isTerminalJobState = (s: JobMachineState): boolean => TERMINAL_STATUSES.has(s.status);

const assertNever = (value: never): never => {
  throw new Error(`Unhandled job-machine value: ${JSON.stringify(value)}`);
};

const startJob = (_state: JobMachineState, event: Extract<JobEvent, { type: 'START' }>): JobMachineState => ({
  status: JOB_MACHINE_STATE.pending,
  jobId: event.jobId,
  done: 0,
  total: 0,
  lastEventAt: event.at,
  failedCount: 0,
  error: null,
  resumeStatus: null,
  reconnectAttempts: 0,
  lastTickAt: null,
});

const openStream = (state: JobMachineState, event: Extract<JobEvent, { type: 'STREAM_OPEN' }>): JobMachineState => ({
  ...state,
  status: JOB_MACHINE_STATE.running,
  lastEventAt: event.at,
});

const applyProgress = (state: JobMachineState, event: Extract<JobEvent, { type: 'PROGRESS' }>): JobMachineState => ({
  ...state,
  status: JOB_MACHINE_STATE.running,
  done: event.done,
  total: event.total,
  lastEventAt: event.at,
  reconnectAttempts: 0,
});

const failReconnectCeiling = (state: JobMachineState, attempts: number, at: number): JobMachineState => ({
  ...state,
  status: JOB_MACHINE_STATE.failed,
  lastEventAt: at,
  reconnectAttempts: attempts,
  resumeStatus: null,
  error: {
    message: `Reconnect ceiling exceeded (${attempts} attempts)`,
  },
});

/**
 * A quiet stream is observed, never terminated. `lastEventAt` keeps pointing at the last
 * *real* event so quiet duration keeps growing and the UI can render "no news for Ns";
 * rewriting it per tick would erase the very quantity being measured. The only mutation is
 * the one-shot running -> stalled edge plus a clock-discontinuity rebase.
 */
const stallIfQuiet = (
  state: JobMachineState,
  event: Extract<JobEvent, { type: 'STALL_TICK' }>,
): JobMachineState => {
  if (state.lastEventAt === null) {
    return state;
  }

  // Sleep / NTP step / frozen tab: the ticker itself stopped, so the wall time it skipped
  // is not evidence about the stream. Rebase the quiet window and start observing again.
  const tickGap = state.lastTickAt === null ? 0 : event.now - state.lastTickAt;
  const quietMs = event.now - state.lastEventAt;
  if (tickGap < 0 || tickGap > JOB_MACHINE_MAX_TICK_DELTA_MS || quietMs < 0) {
    return { ...state, lastEventAt: event.now, lastTickAt: event.now };
  }

  if (quietMs < JOB_MACHINE_STALL_THRESHOLD_MS || state.status === JOB_MACHINE_STATE.stalled) {
    return state.lastTickAt === event.now ? state : { ...state, lastTickAt: event.now };
  }
  return { ...state, status: JOB_MACHINE_STATE.stalled, lastTickAt: event.now };
};

/** Quiet time since the last real event, or null when no event has arrived yet. */
export const quietMsFor = (state: JobMachineState, now: number): number | null =>
  state.lastEventAt === null ? null : Math.max(0, now - state.lastEventAt);

/**
 * A real reconnect attempt: a fresh transport is being opened. This is the only site that
 * advances the ceiling, so "Reconnect ceiling exceeded (N attempts)" is now true when emitted.
 */
const noteReconnectAttempt = (
  state: JobMachineState,
  event: Extract<JobEvent, { type: 'RECONNECTING' }>,
): JobMachineState => {
  const attempts = state.reconnectAttempts + 1;
  if (attempts > JOB_MACHINE_RECONNECT_CEILING) {
    return failReconnectCeiling(state, attempts, event.at);
  }
  return { ...state, reconnectAttempts: attempts };
};

/** The transport actually re-established: clear the breaker. */
const reconnect = (state: JobMachineState, event: Extract<JobEvent, { type: 'RECONNECTED' }>): JobMachineState => ({
  ...state,
  status: JOB_MACHINE_STATE.running,
  lastEventAt: event.at,
  resumeStatus: null,
  reconnectAttempts: 0,
});

const goOffline = (state: JobMachineState, event: Extract<JobEvent, { type: 'OFFLINE' }>): JobMachineState => {
  if (state.status === JOB_MACHINE_STATE.offline) {
    return state;
  }
  return {
    ...state,
    status: JOB_MACHINE_STATE.offline,
    resumeStatus: state.status,
    lastEventAt: event.at,
  };
};

const goOnline = (state: JobMachineState, event: Extract<JobEvent, { type: 'ONLINE' }>): JobMachineState => {
  if (state.status !== JOB_MACHINE_STATE.offline || state.resumeStatus === null) {
    return state;
  }
  return {
    ...state,
    status: state.resumeStatus,
    resumeStatus: null,
    lastEventAt: event.at,
    reconnectAttempts: 0,
  };
};

const complete = (state: JobMachineState, event: Extract<JobEvent, { type: 'COMPLETE' }>): JobMachineState => ({
  ...state,
  status: JOB_MACHINE_STATE.completed,
  lastEventAt: event.at,
  resumeStatus: null,
});

const completeWithErrors = (
  state: JobMachineState,
  event: Extract<JobEvent, { type: 'COMPLETE_WITH_ERRORS' }>,
): JobMachineState => ({
  ...state,
  status: JOB_MACHINE_STATE.completedWithErrors,
  failedCount: event.failedCount ?? state.failedCount,
  lastEventAt: event.at,
  resumeStatus: null,
});

const fail = (state: JobMachineState, event: Extract<JobEvent, { type: 'FAIL' }>): JobMachineState => ({
  ...state,
  status: JOB_MACHINE_STATE.failed,
  error: event.error,
  resumeStatus: null,
});

const resetIdle = (): JobMachineState => initialJobState;

type JobEventHandler<E extends JobEvent['type']> = (
  state: JobMachineState,
  event: Extract<JobEvent, { type: E }>,
) => JobMachineState;

type TransitionHandlers = Partial<{
  readonly [E in JobEvent['type']]: JobEventHandler<E>;
}>;

type TransitionTable = Record<JobMachineStatus, TransitionHandlers>;

const TRANSITIONS: TransitionTable = {
  [JOB_MACHINE_STATE.idle]: {
    [JOB_EVENT.START]: startJob,
    [JOB_EVENT.OFFLINE]: goOffline,
    [JOB_EVENT.RESET]: resetIdle,
  },
  [JOB_MACHINE_STATE.pending]: {
    [JOB_EVENT.STREAM_OPEN]: openStream,
    [JOB_EVENT.PROGRESS]: applyProgress,
    [JOB_EVENT.STALL_TICK]: stallIfQuiet,
    [JOB_EVENT.RECONNECTING]: noteReconnectAttempt,
    [JOB_EVENT.RECONNECTED]: reconnect,
    [JOB_EVENT.OFFLINE]: goOffline,
    [JOB_EVENT.COMPLETE]: complete,
    [JOB_EVENT.COMPLETE_WITH_ERRORS]: completeWithErrors,
    [JOB_EVENT.FAIL]: fail,
    [JOB_EVENT.CANCEL]: resetIdle,
    [JOB_EVENT.RESET]: resetIdle,
  },
  [JOB_MACHINE_STATE.running]: {
    [JOB_EVENT.PROGRESS]: applyProgress,
    [JOB_EVENT.STALL_TICK]: stallIfQuiet,
    [JOB_EVENT.RECONNECTING]: noteReconnectAttempt,
    [JOB_EVENT.RECONNECTED]: reconnect,
    [JOB_EVENT.OFFLINE]: goOffline,
    [JOB_EVENT.COMPLETE]: complete,
    [JOB_EVENT.COMPLETE_WITH_ERRORS]: completeWithErrors,
    [JOB_EVENT.FAIL]: fail,
    [JOB_EVENT.CANCEL]: resetIdle,
    [JOB_EVENT.RESET]: resetIdle,
  },
  [JOB_MACHINE_STATE.stalled]: {
    [JOB_EVENT.STREAM_OPEN]: openStream,
    [JOB_EVENT.PROGRESS]: applyProgress,
    [JOB_EVENT.STALL_TICK]: stallIfQuiet,
    [JOB_EVENT.RECONNECTING]: noteReconnectAttempt,
    [JOB_EVENT.RECONNECTED]: reconnect,
    [JOB_EVENT.OFFLINE]: goOffline,
    [JOB_EVENT.COMPLETE]: complete,
    [JOB_EVENT.COMPLETE_WITH_ERRORS]: completeWithErrors,
    [JOB_EVENT.FAIL]: fail,
    [JOB_EVENT.CANCEL]: resetIdle,
    [JOB_EVENT.RESET]: resetIdle,
  },
  // Offline is a peer state with its own recovery edge (ONLINE), not a countdown to failure:
  // losing wifi must never fail a job that is still running server-side. STALL_TICK is
  // therefore deliberately absent — there is no quiet-time bound here. The only bound is
  // RECONNECTING, which counts real transport attempts.
  [JOB_MACHINE_STATE.offline]: {
    [JOB_EVENT.RECONNECTING]: noteReconnectAttempt,
    [JOB_EVENT.ONLINE]: goOnline,
    [JOB_EVENT.FAIL]: fail,
    [JOB_EVENT.CANCEL]: resetIdle,
    [JOB_EVENT.RESET]: resetIdle,
  },
  [JOB_MACHINE_STATE.completed]: {
    [JOB_EVENT.START]: startJob,
    [JOB_EVENT.RESET]: resetIdle,
  },
  [JOB_MACHINE_STATE.completedWithErrors]: {
    [JOB_EVENT.START]: startJob,
    [JOB_EVENT.RESET]: resetIdle,
  },
  [JOB_MACHINE_STATE.failed]: {
    [JOB_EVENT.START]: startJob,
    [JOB_EVENT.RESET]: resetIdle,
  },
};

export const jobReducer = (state: JobMachineState, event: JobEvent): JobMachineState => {
  switch (state.status) {
    case JOB_MACHINE_STATE.idle:
    case JOB_MACHINE_STATE.pending:
    case JOB_MACHINE_STATE.running:
    case JOB_MACHINE_STATE.stalled:
    case JOB_MACHINE_STATE.offline:
    case JOB_MACHINE_STATE.completed:
    case JOB_MACHINE_STATE.completedWithErrors:
    case JOB_MACHINE_STATE.failed:
      break;
    default:
      return assertNever(state.status);
  }

  const handler = TRANSITIONS[state.status][event.type] as
    | ((current: JobMachineState, nextEvent: JobEvent) => JobMachineState)
    | undefined;
  if (handler) {
    return handler(state, event);
  }

  switch (event.type) {
    case JOB_EVENT.START:
    case JOB_EVENT.STREAM_OPEN:
    case JOB_EVENT.PROGRESS:
    case JOB_EVENT.STALL_TICK:
    case JOB_EVENT.RECONNECTING:
    case JOB_EVENT.RECONNECTED:
    case JOB_EVENT.OFFLINE:
    case JOB_EVENT.ONLINE:
    case JOB_EVENT.COMPLETE:
    case JOB_EVENT.COMPLETE_WITH_ERRORS:
    case JOB_EVENT.FAIL:
    case JOB_EVENT.CANCEL:
    case JOB_EVENT.RESET:
      return state;
    default:
      return assertNever(event);
  }
};
