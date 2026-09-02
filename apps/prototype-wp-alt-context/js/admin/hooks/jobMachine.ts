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

export interface JobMachineState {
  readonly status: JobMachineStatus;
  readonly jobId: string | null;
  readonly done: number;
  readonly total: number;
  readonly lastEventAt: number | null;
  readonly failedCount: number;
  readonly error: { readonly message: string } | null;
  readonly resumeStatus: Exclude<JobMachineStatus, typeof JOB_MACHINE_STATE.offline> | null;
}

export const JOB_EVENT = {
  START: 'START',
  STREAM_OPEN: 'STREAM_OPEN',
  PROGRESS: 'PROGRESS',
  STALL_TICK: 'STALL_TICK',
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
  | { type: typeof JOB_EVENT.RECONNECTED; at: number }
  | { type: typeof JOB_EVENT.OFFLINE }
  | { type: typeof JOB_EVENT.ONLINE }
  | { type: typeof JOB_EVENT.COMPLETE; at: number }
  | { type: typeof JOB_EVENT.COMPLETE_WITH_ERRORS; failedCount: number; at: number }
  | { type: typeof JOB_EVENT.FAIL; error: { message: string } }
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
});

const stallIfQuiet = (state: JobMachineState, event: Extract<JobEvent, { type: 'STALL_TICK' }>): JobMachineState => {
  if (state.lastEventAt !== null && event.now - state.lastEventAt >= JOB_MACHINE_STALL_THRESHOLD_MS) {
    return { ...state, status: JOB_MACHINE_STATE.stalled };
  }
  return state;
};

const stay = (state: JobMachineState): JobMachineState => state;

const reconnect = (state: JobMachineState, event: Extract<JobEvent, { type: 'RECONNECTED' }>): JobMachineState => ({
  ...state,
  status: JOB_MACHINE_STATE.running,
  lastEventAt: event.at,
});

const goOffline = (state: JobMachineState): JobMachineState => {
  if (state.status === JOB_MACHINE_STATE.offline) {
    return state;
  }
  return {
    ...state,
    status: JOB_MACHINE_STATE.offline,
    resumeStatus: state.status,
  };
};

const goOnline = (state: JobMachineState): JobMachineState => {
  if (state.status !== JOB_MACHINE_STATE.offline || state.resumeStatus === null) {
    return state;
  }
  return {
    ...state,
    status: state.resumeStatus,
    resumeStatus: null,
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
  failedCount: event.failedCount,
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
    [JOB_EVENT.STALL_TICK]: stay,
    [JOB_EVENT.RECONNECTED]: reconnect,
    [JOB_EVENT.OFFLINE]: goOffline,
    [JOB_EVENT.COMPLETE]: complete,
    [JOB_EVENT.COMPLETE_WITH_ERRORS]: completeWithErrors,
    [JOB_EVENT.FAIL]: fail,
    [JOB_EVENT.CANCEL]: resetIdle,
    [JOB_EVENT.RESET]: resetIdle,
  },
  [JOB_MACHINE_STATE.offline]: {
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
