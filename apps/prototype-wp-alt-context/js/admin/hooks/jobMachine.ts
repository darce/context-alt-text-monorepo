/**
 * ONE status vocabulary for the job pipeline (sr-007, REF-26 "DRY is knowledge, not text").
 *
 * Before FEBT1-LA-05 this file owned `idle|pending|running|stalled|offline|completed|
 * completed_with_errors|failed` while useJobProgressStream owned
 * `pending|running|completed|completed_with_errors|failed|rejected|clustering` — two
 * `as const` maps for one fact, disjoint on four members. The union lives here; the
 * subsets below are *derived tuples*, not second vocabularies.
 *
 * Axes:
 *  - producer statuses (`WIRE_JOB_STATUSES`) come off the SSE wire and are the only
 *    source of a job-lifecycle claim (rg-015: a boundary adapter must not invent
 *    contract metadata);
 *  - `idle`, `stalled` and `offline` are client-observed transport states. They are real
 *    designed states (RLSE-04), not sentinels, and they are projected back onto a wire
 *    status for consumers by `projectWireStatus`.
 */
export const JOB_STATUS = {
  IDLE: 'idle',
  PENDING: 'pending',
  RUNNING: 'running',
  CLUSTERING: 'clustering',
  STALLED: 'stalled',
  OFFLINE: 'offline',
  COMPLETED: 'completed',
  COMPLETED_WITH_ERRORS: 'completed_with_errors',
  FAILED: 'failed',
  REJECTED: 'rejected',
} as const;

export type JobStatus = (typeof JOB_STATUS)[keyof typeof JOB_STATUS];

/**
 * Statuses the WP SSE producer can put on the wire. Mirrors
 * `class-job-progress-stream-service.php` (`$status` is forwarded verbatim and its
 * TERMINAL_JOB_STATUSES includes `rejected`).
 */
export const WIRE_JOB_STATUSES = [
  JOB_STATUS.PENDING,
  JOB_STATUS.RUNNING,
  JOB_STATUS.CLUSTERING,
  JOB_STATUS.COMPLETED,
  JOB_STATUS.COMPLETED_WITH_ERRORS,
  JOB_STATUS.FAILED,
  JOB_STATUS.REJECTED,
] as const satisfies readonly JobStatus[];

export type WireJobStatus = (typeof WIRE_JOB_STATUSES)[number];

/** Wire statuses that mean "still working": the ones a stall or an offline gap suspends. */
export const LIVE_JOB_STATUSES = [
  JOB_STATUS.PENDING,
  JOB_STATUS.RUNNING,
  JOB_STATUS.CLUSTERING,
] as const satisfies readonly WireJobStatus[];

export type LiveJobStatus = (typeof LIVE_JOB_STATUSES)[number];

/** Wire statuses after which nothing else arrives on the stream. */
export const TERMINAL_JOB_STATUSES = [
  JOB_STATUS.COMPLETED,
  JOB_STATUS.COMPLETED_WITH_ERRORS,
  JOB_STATUS.FAILED,
  JOB_STATUS.REJECTED,
] as const satisfies readonly WireJobStatus[];

export type TerminalJobStatus = (typeof TERMINAL_JOB_STATUSES)[number];

/**
 * Explicit validation of untrusted SSE boundary data (sr-005): the parse helpers hand back
 * whatever the wire carried in `status`, so an unknown or absent status must be rejected
 * here rather than falling through a default branch that means "success".
 */
export const isWireJobStatus = (value: unknown): value is WireJobStatus =>
  typeof value === 'string' && (WIRE_JOB_STATUSES as readonly string[]).includes(value);

export const isLiveJobStatus = (value: unknown): value is LiveJobStatus =>
  typeof value === 'string' && (LIVE_JOB_STATUSES as readonly string[]).includes(value);

export const isTerminalJobStatus = (status: JobStatus): status is TerminalJobStatus =>
  (TERMINAL_JOB_STATUSES as readonly string[]).includes(status);

/** The single stall clock for the whole tree (REF-21, FEBT-1-W1-M-08). */
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
  readonly status: JobStatus;
  readonly jobId: string | null;
  readonly done: number;
  readonly total: number;
  readonly lastEventAt: number | null;
  readonly failedCount: number;
  readonly error: { readonly message: string } | null;
  readonly resumeStatus: Exclude<JobStatus, typeof JOB_STATUS.OFFLINE> | null;
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
  REJECT: 'REJECT',
  CANCEL: 'CANCEL',
  RESET: 'RESET',
} as const;

export type JobEvent =
  | { type: typeof JOB_EVENT.START; jobId: string; at: number }
  | { type: typeof JOB_EVENT.STREAM_OPEN; at: number }
  // `status` is required: a progress frame carries the producer's lifecycle claim and the
  // machine adopts it verbatim instead of hard-coding `running` (rg-015).
  | { type: typeof JOB_EVENT.PROGRESS; status: LiveJobStatus; done: number; total: number; at: number }
  | { type: typeof JOB_EVENT.STALL_TICK; now: number }
  | { type: typeof JOB_EVENT.RECONNECTING; at: number }
  | { type: typeof JOB_EVENT.RECONNECTED; at: number }
  | { type: typeof JOB_EVENT.OFFLINE; at: number }
  | { type: typeof JOB_EVENT.ONLINE; at: number }
  | { type: typeof JOB_EVENT.COMPLETE; at: number }
  | { type: typeof JOB_EVENT.COMPLETE_WITH_ERRORS; failedCount?: number; at: number }
  | { type: typeof JOB_EVENT.FAIL; error: { message: string } | null }
  // `rejected` is a distinct designed terminal (RLSE-04): the producer never admitted the
  // job, which is operationally different from a job that ran and broke.
  | { type: typeof JOB_EVENT.REJECT; error: { message: string } | null }
  | { type: typeof JOB_EVENT.CANCEL }
  | { type: typeof JOB_EVENT.RESET };

export const initialJobState: JobMachineState = {
  status: JOB_STATUS.IDLE,
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

export const isTerminalJobState = (s: JobMachineState): boolean => isTerminalJobStatus(s.status);

const assertNever = (value: never): never => {
  throw new Error(`Unhandled job-machine value: ${JSON.stringify(value)}`);
};

/**
 * Projection of the machine onto the producer vocabulary consumers speak (FEBT1-LA-05).
 *
 * The machine is the single source of truth; this is the only place the transport-derived
 * states are mapped back. `stalled` is deliberately NOT leaked as a lifecycle status —
 * a quiet stream is a running job whose quiet window is reported separately through
 * `stalledForSeconds` (RLSE-04: stalled is a designed state, surfaced on its own channel,
 * not by overwriting the job's status).
 */
const WIRE_PROJECTION: Record<Exclude<JobStatus, typeof JOB_STATUS.OFFLINE>, WireJobStatus> = {
  [JOB_STATUS.IDLE]: JOB_STATUS.PENDING,
  [JOB_STATUS.PENDING]: JOB_STATUS.PENDING,
  [JOB_STATUS.RUNNING]: JOB_STATUS.RUNNING,
  [JOB_STATUS.CLUSTERING]: JOB_STATUS.CLUSTERING,
  [JOB_STATUS.STALLED]: JOB_STATUS.RUNNING,
  [JOB_STATUS.COMPLETED]: JOB_STATUS.COMPLETED,
  [JOB_STATUS.COMPLETED_WITH_ERRORS]: JOB_STATUS.COMPLETED_WITH_ERRORS,
  [JOB_STATUS.FAILED]: JOB_STATUS.FAILED,
  [JOB_STATUS.REJECTED]: JOB_STATUS.REJECTED,
};

export const projectWireStatus = (state: JobMachineState): WireJobStatus =>
  state.status === JOB_STATUS.OFFLINE
    ? WIRE_PROJECTION[state.resumeStatus ?? JOB_STATUS.IDLE]
    : WIRE_PROJECTION[state.status];

const startJob = (_state: JobMachineState, event: Extract<JobEvent, { type: 'START' }>): JobMachineState => ({
  status: JOB_STATUS.PENDING,
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

/**
 * Transport-open is a transport fact, not a lifecycle claim: it may clear the client's own
 * `stalled` observation but must not promote `pending` to `running` — only the producer's
 * wire status may do that (rg-015).
 */
const openStream = (state: JobMachineState, event: Extract<JobEvent, { type: 'STREAM_OPEN' }>): JobMachineState => ({
  ...state,
  status: state.status === JOB_STATUS.STALLED ? JOB_STATUS.RUNNING : state.status,
  lastEventAt: event.at,
});

const applyProgress = (state: JobMachineState, event: Extract<JobEvent, { type: 'PROGRESS' }>): JobMachineState => ({
  ...state,
  status: event.status,
  done: event.done,
  total: event.total,
  lastEventAt: event.at,
  reconnectAttempts: 0,
});

const failReconnectCeiling = (state: JobMachineState, attempts: number, at: number): JobMachineState => ({
  ...state,
  status: JOB_STATUS.FAILED,
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
 * the one-shot live -> stalled edge plus a clock-discontinuity rebase.
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

  if (quietMs < JOB_MACHINE_STALL_THRESHOLD_MS || state.status === JOB_STATUS.STALLED) {
    return state.lastTickAt === event.now ? state : { ...state, lastTickAt: event.now };
  }
  return { ...state, status: JOB_STATUS.STALLED, lastTickAt: event.now };
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

/**
 * The transport actually re-established: clear the breaker. Like STREAM_OPEN this clears the
 * client's `stalled` observation but never invents a lifecycle promotion (rg-015).
 */
const reconnect = (state: JobMachineState, event: Extract<JobEvent, { type: 'RECONNECTED' }>): JobMachineState => ({
  ...state,
  status: state.status === JOB_STATUS.STALLED ? JOB_STATUS.RUNNING : state.status,
  lastEventAt: event.at,
  resumeStatus: null,
  reconnectAttempts: 0,
});

const goOffline = (state: JobMachineState, event: Extract<JobEvent, { type: 'OFFLINE' }>): JobMachineState => {
  if (state.status === JOB_STATUS.OFFLINE) {
    return state;
  }
  return {
    ...state,
    status: JOB_STATUS.OFFLINE,
    resumeStatus: state.status,
    lastEventAt: event.at,
  };
};

const goOnline = (state: JobMachineState, event: Extract<JobEvent, { type: 'ONLINE' }>): JobMachineState => {
  if (state.status !== JOB_STATUS.OFFLINE || state.resumeStatus === null) {
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
  status: JOB_STATUS.COMPLETED,
  lastEventAt: event.at,
  resumeStatus: null,
});

const completeWithErrors = (
  state: JobMachineState,
  event: Extract<JobEvent, { type: 'COMPLETE_WITH_ERRORS' }>,
): JobMachineState => ({
  ...state,
  status: JOB_STATUS.COMPLETED_WITH_ERRORS,
  failedCount: event.failedCount ?? state.failedCount,
  lastEventAt: event.at,
  resumeStatus: null,
});

const fail = (state: JobMachineState, event: Extract<JobEvent, { type: 'FAIL' }>): JobMachineState => ({
  ...state,
  status: JOB_STATUS.FAILED,
  error: event.error,
  resumeStatus: null,
});

const reject = (state: JobMachineState, event: Extract<JobEvent, { type: 'REJECT' }>): JobMachineState => ({
  ...state,
  status: JOB_STATUS.REJECTED,
  error: event.error,
  resumeStatus: null,
});

const resetIdle = (): JobMachineState => initialJobState;

type JobEventHandler<E extends JobEvent['type']> = (
  state: JobMachineState,
  event: Extract<JobEvent, { type: E }>,
) => JobMachineState;

/** RESET is hoisted out of the table, so it is not a per-row handler key. */
type TableEventType = Exclude<JobEvent['type'], typeof JOB_EVENT.RESET>;

type TransitionHandlers = Partial<{
  readonly [E in TableEventType]: JobEventHandler<E>;
}>;

type TransitionTable = Record<JobStatus, TransitionHandlers>;

/**
 * FEBT-1-W1-M-07 / GRPH-28: `RESET` was copied onto all eight rows with an identical
 * unconditioned handler, so it is pulled up below into `jobReducer` and a state added later
 * cannot silently miss the edge. `CANCEL` and `OFFLINE` are deliberately left in the table:
 * their row membership differs (terminals refuse both, `offline` has no STALL_TICK), and
 * that difference is load-bearing, not copy-paste drift.
 */
const TRANSITIONS: TransitionTable = {
  [JOB_STATUS.IDLE]: {
    [JOB_EVENT.START]: startJob,
    [JOB_EVENT.OFFLINE]: goOffline,
  },
  [JOB_STATUS.PENDING]: {
    [JOB_EVENT.STREAM_OPEN]: openStream,
    [JOB_EVENT.PROGRESS]: applyProgress,
    [JOB_EVENT.STALL_TICK]: stallIfQuiet,
    [JOB_EVENT.RECONNECTING]: noteReconnectAttempt,
    [JOB_EVENT.RECONNECTED]: reconnect,
    [JOB_EVENT.OFFLINE]: goOffline,
    [JOB_EVENT.COMPLETE]: complete,
    [JOB_EVENT.COMPLETE_WITH_ERRORS]: completeWithErrors,
    [JOB_EVENT.FAIL]: fail,
    [JOB_EVENT.REJECT]: reject,
    [JOB_EVENT.CANCEL]: resetIdle,
  },
  [JOB_STATUS.RUNNING]: {
    [JOB_EVENT.PROGRESS]: applyProgress,
    [JOB_EVENT.STALL_TICK]: stallIfQuiet,
    [JOB_EVENT.RECONNECTING]: noteReconnectAttempt,
    [JOB_EVENT.RECONNECTED]: reconnect,
    [JOB_EVENT.OFFLINE]: goOffline,
    [JOB_EVENT.COMPLETE]: complete,
    [JOB_EVENT.COMPLETE_WITH_ERRORS]: completeWithErrors,
    [JOB_EVENT.FAIL]: fail,
    [JOB_EVENT.REJECT]: reject,
    [JOB_EVENT.CANCEL]: resetIdle,
  },
  // Clustering is the producer's second working phase; it accepts exactly what `running`
  // accepts so a clustering job cannot be quietly demoted to `running` by a reconnect.
  [JOB_STATUS.CLUSTERING]: {
    [JOB_EVENT.PROGRESS]: applyProgress,
    [JOB_EVENT.STALL_TICK]: stallIfQuiet,
    [JOB_EVENT.RECONNECTING]: noteReconnectAttempt,
    [JOB_EVENT.RECONNECTED]: reconnect,
    [JOB_EVENT.OFFLINE]: goOffline,
    [JOB_EVENT.COMPLETE]: complete,
    [JOB_EVENT.COMPLETE_WITH_ERRORS]: completeWithErrors,
    [JOB_EVENT.FAIL]: fail,
    [JOB_EVENT.REJECT]: reject,
    [JOB_EVENT.CANCEL]: resetIdle,
  },
  [JOB_STATUS.STALLED]: {
    [JOB_EVENT.STREAM_OPEN]: openStream,
    [JOB_EVENT.PROGRESS]: applyProgress,
    [JOB_EVENT.STALL_TICK]: stallIfQuiet,
    [JOB_EVENT.RECONNECTING]: noteReconnectAttempt,
    [JOB_EVENT.RECONNECTED]: reconnect,
    [JOB_EVENT.OFFLINE]: goOffline,
    [JOB_EVENT.COMPLETE]: complete,
    [JOB_EVENT.COMPLETE_WITH_ERRORS]: completeWithErrors,
    [JOB_EVENT.FAIL]: fail,
    [JOB_EVENT.REJECT]: reject,
    [JOB_EVENT.CANCEL]: resetIdle,
  },
  // Offline is a peer state with its own recovery edge (ONLINE), not a countdown to failure:
  // losing wifi must never fail a job that is still running server-side. STALL_TICK is
  // therefore deliberately absent — there is no quiet-time bound here. The only bound is
  // RECONNECTING, which counts real transport attempts.
  [JOB_STATUS.OFFLINE]: {
    [JOB_EVENT.RECONNECTING]: noteReconnectAttempt,
    [JOB_EVENT.ONLINE]: goOnline,
    [JOB_EVENT.FAIL]: fail,
    [JOB_EVENT.REJECT]: reject,
    [JOB_EVENT.CANCEL]: resetIdle,
  },
  [JOB_STATUS.COMPLETED]: {
    [JOB_EVENT.START]: startJob,
  },
  [JOB_STATUS.COMPLETED_WITH_ERRORS]: {
    [JOB_EVENT.START]: startJob,
  },
  [JOB_STATUS.FAILED]: {
    [JOB_EVENT.START]: startJob,
  },
  [JOB_STATUS.REJECTED]: {
    [JOB_EVENT.START]: startJob,
  },
};

export const jobReducer = (state: JobMachineState, event: JobEvent): JobMachineState => {
  switch (state.status) {
    case JOB_STATUS.IDLE:
    case JOB_STATUS.PENDING:
    case JOB_STATUS.RUNNING:
    case JOB_STATUS.CLUSTERING:
    case JOB_STATUS.STALLED:
    case JOB_STATUS.OFFLINE:
    case JOB_STATUS.COMPLETED:
    case JOB_STATUS.COMPLETED_WITH_ERRORS:
    case JOB_STATUS.FAILED:
    case JOB_STATUS.REJECTED:
      break;
    default:
      return assertNever(state.status);
  }

  // GRPH-28 pull-up: RESET is total and unconditioned across every state.
  if (event.type === JOB_EVENT.RESET) {
    return resetIdle();
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
    case JOB_EVENT.REJECT:
    case JOB_EVENT.CANCEL:
      return state;
    default:
      return assertNever(event);
  }
};
