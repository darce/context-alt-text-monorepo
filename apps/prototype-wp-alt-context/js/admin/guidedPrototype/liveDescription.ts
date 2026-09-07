/**
 * Bounded live-description run for the guided prototype.
 *
 * The guided flow already holds a complete, correct saved draft before this
 * module does anything. A live run is therefore always additive: every terminal
 * state here leaves that draft and the Apply button untouched, so a cold GPU
 * can never block the lesson.
 */
import { DESCRIBE_RESULT_TIER, DESCRIBE_RUN_PHASE } from '../api/describeApi';
import type { DescribeResultTier, DescribeRunPhase, DescribeRunResponse, GpuState } from '../api/describeApi';
import { confirmedPersonKeys, getGuidedPerson } from './state';
import type { GuidedScenario } from './state';

export const GUIDED_LIVE_STATUS = {
  IDLE: 'idle',
  BLOCKED: 'blocked',
  QUEUED: 'queued',
  WARMING: 'warming',
  DESCRIBING: 'describing',
  READY: 'ready',
  DEGRADED: 'degraded',
  TIMED_OUT: 'timed_out',
  UNAVAILABLE: 'unavailable',
  CANCELLED: 'cancelled',
} as const;

export type GuidedLiveStatus = (typeof GUIDED_LIVE_STATUS)[keyof typeof GUIDED_LIVE_STATUS];

/**
 * Why the gate is shut. It lives in the state rather than beside it because a
 * panel that reads "blocked" from one place and "why" from another can render
 * one without the other for a frame, which is exactly the dead-end disabled
 * control this screen set out to remove (sr-007).
 */
export const GUIDED_LIVE_BLOCKED_REASON = {
  NO_FACES_DECIDED: 'no_faces_decided',
  NO_MEDIA: 'no_media',
} as const;

export type GuidedLiveBlockedReason =
  (typeof GUIDED_LIVE_BLOCKED_REASON)[keyof typeof GUIDED_LIVE_BLOCKED_REASON];

/**
 * Every machine reason a run can end on. The panel turns these into sentences,
 * so a literal drifting in one module and not the other silently changes what
 * the learner is told without the type checker or a test noticing (sr-007).
 */
export const GUIDED_LIVE_REASON = {
  CPU_FALLBACK: 'cpu_fallback',
  TIER_UNREPORTED: 'tier_unreported',
  EMPTY_DESCRIPTION: 'empty_description',
  CLIENT_DEADLINE: 'client_deadline',
  RUN_FAILED: 'run_failed',
  RUN_CANCELLED: 'run_cancelled',
  STOPPED_BY_OPERATOR: 'stopped_by_operator',
  ITEM_MISSING: 'item_missing',
  SUBMIT_FAILED: 'submit_failed',
  POLL_FAILED: 'poll_failed',
  UNKNOWN_PHASE: 'unknown_phase',
} as const;

export type GuidedLiveReason = (typeof GUIDED_LIVE_REASON)[keyof typeof GUIDED_LIVE_REASON];

/** Cold-start ceiling: the GPU warm-up budget the backend advertises. */
export const GUIDED_LIVE_WAIT_CEILING_SECONDS = 510;
const POLL_BASE_MS = 500;
const POLL_CEILING_MS = 5000;

/**
 * Slack layered on top of the server's disclosed generation budget so the
 * client times out just after the server, never before it: one poll cadence
 * plus round-trip transport, not a guess at how late the server usually runs.
 */
export const GUIDED_LIVE_DEADLINE_SLACK_MS = 15_000;

/**
 * `deadline_seconds` is sibling-lane work landing on the wire contract this
 * module reads (submit response and every status poll). Extending
 * `DescribeRunResponse` itself lives in `../api/describeApi`, outside this
 * lane's owned paths, so it is carried here as a local intersection until the
 * coordinator hoists it onto the shared type.
 */
export type GuidedLiveDescribeRunResponse = DescribeRunResponse & {
  deadline_seconds?: number | null;
};

/**
 * Boundary check for `deadline_seconds`: it is untrusted API data, so it earns
 * an explicit predicate rather than an assertion helper (sr-005). Anything
 * that is not a finite positive number means "the server did not disclose a
 * budget" and must fall back to the client's own ceiling.
 *
 * Exported so the hook can decide, once at accept, whether a disclosed
 * deadline is in effect for this run -- the single source of truth for what
 * counts as a real disclosure, so the poll loop's "ignore it on polls" rule
 * (see the `polled` action) and this resolver never drift apart on the
 * definition of "disclosed".
 */
export const isGuidedLiveDeadlineDisclosed = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value > 0;

/**
 * The one place the server's disclosed budget is turned into a client
 * deadline. `localCeilingMs` is whatever the warm/cold selection already
 * decided (unchanged by this function); the disclosed budget can only pull
 * that ceiling in, never push it out, so an operator's generous local
 * patience bound is never extended by a server that discloses a longer one.
 * The same formula runs whether the local ceiling came from the warm or the
 * cold branch -- a disclosed budget is a statement about generation time, and
 * this function does not layer extra warm-up allowance on top of it even in
 * the cold case; the cold ceiling still wins as the outer cap when the
 * disclosed budget would exceed it.
 */
export const resolveGuidedLiveDeadlineMs = (
  localCeilingMs: number,
  deadlineSeconds: number | null | undefined,
): number => {
  if (!isGuidedLiveDeadlineDisclosed(deadlineSeconds)) {
    return localCeilingMs;
  }
  return Math.min(localCeilingMs, deadlineSeconds * 1000 + GUIDED_LIVE_DEADLINE_SLACK_MS);
};

const WAITING_STATUSES: readonly GuidedLiveStatus[] = [
  GUIDED_LIVE_STATUS.QUEUED,
  GUIDED_LIVE_STATUS.WARMING,
  GUIDED_LIVE_STATUS.DESCRIBING,
];

/** Rank orders the wait so an out-of-order poll cannot walk the screen backwards. */
const PHASE_RANK: Record<GuidedLiveStatus, number> = {
  [GUIDED_LIVE_STATUS.BLOCKED]: -1,
  [GUIDED_LIVE_STATUS.IDLE]: 0,
  [GUIDED_LIVE_STATUS.QUEUED]: 1,
  [GUIDED_LIVE_STATUS.WARMING]: 2,
  [GUIDED_LIVE_STATUS.DESCRIBING]: 3,
  [GUIDED_LIVE_STATUS.READY]: 4,
  [GUIDED_LIVE_STATUS.DEGRADED]: 4,
  [GUIDED_LIVE_STATUS.TIMED_OUT]: 4,
  [GUIDED_LIVE_STATUS.UNAVAILABLE]: 4,
  [GUIDED_LIVE_STATUS.CANCELLED]: 4,
};

// The guided screen reads the same wire contract as every other describe
// surface. Aliasing rather than restating keeps a backend phase or tier added
// in describeApi from silently type-checking as unreachable here (sr-007).
export type GuidedLivePhase = DescribeRunPhase;
export type GuidedLiveGpuState = GpuState;
export type GuidedLiveTier = DescribeResultTier;

export interface GuidedLiveState {
  status: GuidedLiveStatus;
  /** Non-null in exactly the blocked status; the panel needs no second source. */
  blockedReason: GuidedLiveBlockedReason | null;
  runId: string | null;
  /** Live description text. Non-null only in ready and degraded. */
  text: string | null;
  /**
   * Machine reason for a non-success terminal state: a member of
   * GUIDED_LIVE_REASON when this client decided, or whatever the service
   * reported verbatim when it did.
   */
  reason: string | null;
  startedAtMs: number | null;
  elapsedMs: number;
  deadlineMs: number;
}

export type GuidedLiveAction =
  | { kind: 'gate_changed'; blockedReason: GuidedLiveBlockedReason | null }
  | { kind: 'requested'; atMs: number }
  | {
      kind: 'accepted';
      runId: string;
      deadlineSeconds: number;
      atMs: number;
      /**
       * The server's disclosed generation budget from the submit response
       * (wire field `deadline_seconds`), taken once here and never re-derived
       * on a later poll. `null`/`undefined` means the server did not disclose
       * one; `resolveGuidedLiveDeadlineMs` decides what that is worth.
       */
      disclosedDeadlineSeconds?: number | null;
    }
  | {
      kind: 'polled';
      phase: GuidedLivePhase;
      gpu: GuidedLiveGpuState;
      atMs: number;
      tier?: GuidedLiveTier | null;
      text?: string | null;
      /** Passed through from the service, so not drawn from the closed set. */
      reason?: string | null;
      /**
       * A poll may carry its own `deadline_seconds` (same wire contract as the
       * submit response). The deadline is taken once, at accept, so this is
       * typed for wire fidelity but the reducer never reads it: a poll
       * disagreeing with the submit is a server bug, not a resize.
       */
      disclosedDeadlineSeconds?: number | null;
    }
  | { kind: 'deadline_raised'; deadlineSeconds: number }
  | { kind: 'tick'; atMs: number }
  | { kind: 'cancelled' }
  | { kind: 'failed'; reason: GuidedLiveReason };

export const initialGuidedLiveState = (
  blockedReason: GuidedLiveBlockedReason | null = GUIDED_LIVE_BLOCKED_REASON.NO_FACES_DECIDED,
): GuidedLiveState => ({
  status: blockedReason === null ? GUIDED_LIVE_STATUS.IDLE : GUIDED_LIVE_STATUS.BLOCKED,
  blockedReason,
  runId: null,
  text: null,
  reason: null,
  startedAtMs: null,
  elapsedMs: 0,
  deadlineMs: GUIDED_LIVE_WAIT_CEILING_SECONDS * 1000,
});

export const isGuidedLiveWaiting = (status: GuidedLiveStatus): boolean => WAITING_STATUSES.includes(status);

/**
 * Whether the server may still be spending GPU on this run.
 *
 * Timing out is a statement about the wait, not about the run: the screen stops
 * and the burst does not. Anything that ends the panel's ownership of a run --
 * unmount, a retry, the gate closing -- has to ask the same question, so it is
 * asked in one place.
 */
export const guidedLiveRunMayBeLive = (state: GuidedLiveState): boolean =>
  state.runId !== null &&
  (isGuidedLiveWaiting(state.status) || state.status === GUIDED_LIVE_STATUS.TIMED_OUT);

/**
 * Whether the panel still owns a run attempt.
 *
 * Wider than `guidedLiveRunMayBeLive` by exactly one window: the submit is on
 * the wire and the server has not handed back a run id yet. There is nothing
 * to cancel in that window, but the attempt is still this panel's, so anything
 * that ends the panel's ownership must fence the attempt -- otherwise the run
 * id lands after the fence and buys a burst nobody is watching.
 */
export const guidedLiveOwnsRunAttempt = (state: GuidedLiveState): boolean =>
  isGuidedLiveWaiting(state.status) || guidedLiveRunMayBeLive(state);

export const guidedLivePollDelayMs = (attempt: number): number =>
  Math.min(POLL_BASE_MS * 2 ** Math.max(0, attempt), POLL_CEILING_MS);

/**
 * The whole outbound payload. No describe route accepts caller-supplied person
 * names, so the guided screen's confirmations cannot and do not travel with it.
 */
export const guidedLiveRequestPayload = (mediaId: number): { media_ids: number[] } => ({ media_ids: [mediaId] });

export interface GuidedLiveNamingDisclosure {
  namesTravelWithTheRequest: false;
  namingSource: 'roster';
  confirmedHere: string[];
}

export const guidedLiveNamingDisclosure = (scenario: GuidedScenario): GuidedLiveNamingDisclosure => ({
  namesTravelWithTheRequest: false,
  namingSource: 'roster',
  confirmedHere: confirmedPersonKeys(scenario).map((key) => getGuidedPerson(scenario, key).name),
});

const assertNever = (value: never): never => {
  throw new Error(`Unhandled guided live action: ${JSON.stringify(value)}`);
};

const terminal = (
  state: GuidedLiveState,
  status: GuidedLiveStatus,
  patch: Partial<GuidedLiveState> = {},
): GuidedLiveState => ({ ...state, text: null, ...patch, status });

/**
 * The one place the promised wait is enforced. Every action that carries a
 * wall-clock reading goes through it, so the deadline binds the run rather than
 * only the timer that happens to notice first.
 */
const advanceClock = (state: GuidedLiveState, atMs: number): GuidedLiveState => {
  const elapsedMs = state.startedAtMs === null ? state.elapsedMs : atMs - state.startedAtMs;
  if (elapsedMs >= state.deadlineMs) {
    // Stop, say so, and never retry on our own: a burst run costs money and may
    // still be finishing.
    return terminal({ ...state, elapsedMs }, GUIDED_LIVE_STATUS.TIMED_OUT, { reason: GUIDED_LIVE_REASON.CLIENT_DEADLINE });
  }
  return { ...state, elapsedMs };
};

const startRun = (state: GuidedLiveState, atMs: number): GuidedLiveState => ({
  ...state,
  status: GUIDED_LIVE_STATUS.QUEUED,
  runId: null,
  text: null,
  reason: null,
  startedAtMs: atMs,
  elapsedMs: 0,
  deadlineMs: GUIDED_LIVE_WAIT_CEILING_SECONDS * 1000,
});

const completion = (state: GuidedLiveState, action: Extract<GuidedLiveAction, { kind: 'polled' }>): GuidedLiveState => {
  const text = (action.text ?? '').trim();
  if (text === '') {
    // A completed run with nothing to show is a failure. Reporting it as a
    // success would hand the learner an empty box and no reason. The caller may
    // name a more precise reason (e.g. the run returned no item for this image
    // at all, which is not the same as an empty draft).
    return terminal(state, GUIDED_LIVE_STATUS.UNAVAILABLE, { reason: action.reason ?? GUIDED_LIVE_REASON.EMPTY_DESCRIPTION });
  }

  // gpu_state is an advisory lifecycle snapshot that may be stale by the time
  // the item lands; describeApi says so outright. It is never proof of what
  // wrote the sentence. The item's own tier is that proof, so a completed run
  // that reports no tier is shown as unattributed rather than claimed for the
  // GPU ([HAI-12] never overstate the machine).
  if (action.tier === DESCRIBE_RESULT_TIER.FINAL_GPU) {
    return { ...state, status: GUIDED_LIVE_STATUS.READY, text, reason: null };
  }
  return {
    ...state,
    status: GUIDED_LIVE_STATUS.DEGRADED,
    text,
    reason: action.tier === DESCRIBE_RESULT_TIER.PROVISIONAL_CPU ? GUIDED_LIVE_REASON.CPU_FALLBACK : GUIDED_LIVE_REASON.TIER_UNREPORTED,
  };
};

export const guidedLiveReducer = (state: GuidedLiveState, action: GuidedLiveAction): GuidedLiveState => {
  switch (action.kind) {
    case 'gate_changed': {
      if (action.blockedReason !== null) {
        // Re-opening a face invalidates the sentence the last run produced: it
        // was written against an identity answer that no longer holds. Keeping
        // it on screen under blocked copy would show two contradictory truths
        // at once (S1-B-09).
        //
        // A run still in flight is invalidated for the same reason, so the gate
        // closing stops the wait rather than letting a poll land a sentence
        // into a blocked panel. The hook cancels the server side.
        return {
          ...state,
          status: GUIDED_LIVE_STATUS.BLOCKED,
          blockedReason: action.blockedReason,
          runId: null,
          text: null,
          reason: null,
        };
      }
      // status and blockedReason are separate fields, so a stale reason can ride
      // out of BLOCKED on any path that forgets to clear it. The panel reads
      // the reason with a fallback, so a stale one names the wrong obstacle.
      // Clearing it whenever the gate is open makes that unreachable by
      // construction rather than by everyone remembering.
      if (state.status === GUIDED_LIVE_STATUS.BLOCKED) {
        return { ...state, status: GUIDED_LIVE_STATUS.IDLE, blockedReason: null };
      }
      return state.blockedReason === null ? state : { ...state, blockedReason: null };
    }

    case 'requested': {
      // Commit before reveal: a live sentence must not arrive while a face
      // match is still unanswered.
      if (state.status === GUIDED_LIVE_STATUS.BLOCKED || isGuidedLiveWaiting(state.status)) {
        return state;
      }
      return startRun(state, action.atMs);
    }

    case 'accepted': {
      if (!isGuidedLiveWaiting(state.status)) {
        return state;
      }
      const capped = Math.min(action.deadlineSeconds, GUIDED_LIVE_WAIT_CEILING_SECONDS);
      // The server is the authority on how long its own work takes, so this
      // figure replaces the client's pre-acceptance placeholder outright --
      // including downward. What the learner must never see is that
      // placeholder presented as a promise and then revised; the panel
      // therefore advertises no ceiling until this action has negotiated one
      // (see GuidedLiveDescriptionPanel: waiting without a runId shows
      // elapsed only).
      const localCeilingMs = Math.max(0, capped) * 1000;
      // The server's disclosed generation budget (if any) can only pull that
      // ceiling in, taken once here -- never re-derived on a later poll.
      const deadlineMs = resolveGuidedLiveDeadlineMs(localCeilingMs, action.disclosedDeadlineSeconds);
      //
      // Record the run id before advancing the clock: a run the server has
      // just confirmed is precisely the one that still needs cancelling if
      // acceptance itself lands past the deadline.
      const accepted = { ...state, runId: action.runId, deadlineMs };
      return advanceClock(accepted, action.atMs);
    }

    case 'deadline_raised': {
      // A submit-time warm pin is a guess. If a later poll reveals the GPU is
      // colder than that, the wait must be allowed to grow back toward the
      // cold ceiling -- but never to shrink under a learner mid-wait.
      if (!isGuidedLiveWaiting(state.status)) {
        return state;
      }
      const capped = Math.min(action.deadlineSeconds, GUIDED_LIVE_WAIT_CEILING_SECONDS);
      return { ...state, deadlineMs: Math.max(state.deadlineMs, Math.max(0, capped) * 1000) };
    }

    case 'tick': {
      if (!isGuidedLiveWaiting(state.status) || state.startedAtMs === null) {
        return state;
      }
      return advanceClock(state, action.atMs);
    }

    case 'polled': {
      if (!isGuidedLiveWaiting(state.status)) {
        return state;
      }
      const next = advanceClock(state, action.atMs);

      if (action.phase === DESCRIBE_RUN_PHASE.COMPLETE) {
        // Deliberately ahead of the timeout check. The deadline is there to
        // bound an unbounded wait, not to throw away a sentence that is
        // already in the browser -- and the clock it is measured against
        // includes the items round trip that fetched this very payload, so
        // the late one is often the answer itself. Saying "the run may still
        // finish on its own" while holding its result is simply untrue.
        return completion(next, action);
      }

      if (next.status === GUIDED_LIVE_STATUS.TIMED_OUT) {
        // No answer in hand: the response is later than the wait it belongs
        // to. Reading it would hand the learner a result at 5:01 under a
        // promise that the wait ends at 5:00 -- a bound a run can outlive
        // between two ticks is no bound.
        return next;
      }
      if (action.phase === DESCRIBE_RUN_PHASE.FAILED) {
        return terminal(next, GUIDED_LIVE_STATUS.UNAVAILABLE, { reason: action.reason ?? GUIDED_LIVE_REASON.RUN_FAILED });
      }
      if (action.phase === DESCRIBE_RUN_PHASE.CANCELLED) {
        return terminal(next, GUIDED_LIVE_STATUS.CANCELLED, { reason: action.reason ?? GUIDED_LIVE_REASON.RUN_CANCELLED });
      }

      const polledStatus =
        action.phase === DESCRIBE_RUN_PHASE.WARMING
          ? GUIDED_LIVE_STATUS.WARMING
          : action.phase === DESCRIBE_RUN_PHASE.DESCRIBING
            ? GUIDED_LIVE_STATUS.DESCRIBING
            : GUIDED_LIVE_STATUS.QUEUED;

      return PHASE_RANK[polledStatus] > PHASE_RANK[next.status] ? { ...next, status: polledStatus } : next;
    }

    case 'cancelled': {
      if (!isGuidedLiveWaiting(state.status)) {
        return state;
      }
      return terminal(state, GUIDED_LIVE_STATUS.CANCELLED, { reason: GUIDED_LIVE_REASON.STOPPED_BY_OPERATOR });
    }

    case 'failed': {
      if (!isGuidedLiveWaiting(state.status)) {
        return state;
      }
      return terminal(state, GUIDED_LIVE_STATUS.UNAVAILABLE, { reason: action.reason });
    }

    default:
      // A new action must be handled here, not absorbed. sr-005: an assertion
      // helper for the branch that should be impossible.
      return assertNever(action);
  }
};
