/**
 * Bounded live-description run for the guided prototype.
 *
 * The guided flow already holds a complete, correct saved draft before this
 * module does anything. A live run is therefore always additive: every terminal
 * state here leaves that draft and the Apply button untouched, so a cold GPU
 * can never block the lesson.
 */
import { DESCRIBE_RESULT_TIER, DESCRIBE_RUN_PHASE, GPU_STATE } from '../api/describeApi';
import type { DescribeResultTier, DescribeRunPhase, GpuState } from '../api/describeApi';

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
  CPU_TIER: 'cpu_tier',
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

/**
 * A cold live run has TWO budgets on the server and they do not overlap.
 *
 * Generation: `ACX_DESCRIPTION_TIMEOUT_SECONDS` (default 180). This is the leg
 * the service discloses as `deadline_seconds` -- and it is generation ONLY; it
 * does not include the time a scale-to-zero pod spends loading weights.
 *
 * Warm-up: `ACX_GPU_WARMUP_TIMEOUT_SECONDS` (default 510, see
 * `scene/config/settings.py` DEFAULT_GPU_WARMUP_TIMEOUT_SECONDS and
 * `.env.prod.example`). Paid only when the GPU is not already up.
 *
 * The WordPress proxy already states the total the same way -- see
 * `src/api/class-public-demo-describe-controller.php::public_deadline_seconds()`,
 * which returns `$warmup + $inference`. Treating the disclosed generation
 * budget as the whole wait timed a healthy cold run out at 3:15 while the pod
 * was still loading weights, so the two legs are named separately here and
 * summed in exactly one place.
 */
export const GUIDED_LIVE_WARM_CEILING_SECONDS = 180;

/** The warm-up leg, paid once, only when the GPU is not already `ready`. */
export const GUIDED_LIVE_GPU_WARMUP_CEILING_SECONDS = 510;

/** Cold-start ceiling: warm-up plus generation, the same total the proxy discloses. */
export const GUIDED_LIVE_WAIT_CEILING_SECONDS =
  GUIDED_LIVE_GPU_WARMUP_CEILING_SECONDS + GUIDED_LIVE_WARM_CEILING_SECONDS;

/**
 * A fresh window granted when the learner explicitly asks to keep waiting on a
 * run the server may still be finishing (INT-08 offer a side-effect-free way
 * out, INT-11 refine over restart). One generation budget: long enough for the
 * answer that was nearly there, short enough that the panel does not wait
 * forever on the learner's behalf.
 */
export const GUIDED_LIVE_KEEP_WAITING_SECONDS = GUIDED_LIVE_WARM_CEILING_SECONDS;

const POLL_BASE_MS = 500;
const POLL_CEILING_MS = 5000;

/**
 * Slack layered on top of the server's disclosed generation budget so the
 * client times out just after the server, never before it: one poll cadence
 * plus round-trip transport, not a guess at how late the server usually runs.
 */
export const GUIDED_LIVE_DEADLINE_SLACK_MS = 15_000;

/**
 * The lowest server generation budget this client is willing to believe.
 *
 * A misconfigured `ACX_DESCRIPTION_TIMEOUT_SECONDS=1`, or a number truncated in
 * a proxied body, would otherwise resolve to a 16-second deadline and declare a
 * healthy run timed out with no path back up. Together with
 * `GUIDED_LIVE_DEADLINE_CEILING_SECONDS`, this is a generation-shaped trust
 * band, independent of the local whole-wait ceiling and GPU state. Upstream
 * values are boundary data, so they are validated against that band rather
 * than merely type-narrowed (sr-005).
 */
export const GUIDED_LIVE_DEADLINE_FLOOR_SECONDS = 30;

/**
 * The highest server generation budget this client is willing to believe.
 *
 * The service derives `deadline_seconds` from its per-item envelope (the
 * adapter's generation timeout plus the 10-second naming budget) multiplied by
 * the run's unique item count. Guided requests currently contain one item, so
 * 900 seconds leaves ample room above the documented 240-second adapter timeout
 * and its naming envelope without turning arbitrary API data into an unbounded
 * wait. This is deliberately a generation budget: it does not include GPU
 * warm-up and is independent of the local wait ceiling and GPU state.
 */
export const GUIDED_LIVE_DEADLINE_CEILING_SECONDS = 900;

/**
 * Boundary check for `deadline_seconds`: untrusted API data, so it earns an
 * explicit predicate rather than an assertion helper (sr-005).
 *
 * Outside the generation-shaped band -- `null`, `undefined`, `0`, negative,
 * `NaN`, `Infinity`, a string, or a value below the floor or above the ceiling
 * -- means "the server did not disclose a usable budget" and the caller must
 * fall back to its own whole-wait ceiling. The local ceiling is intentionally
 * not an input: a valid server generation budget may be larger than that local
 * guess and must be allowed to replace it.
 */
export const isGuidedLiveDeadlineDisclosed = (value: unknown): value is number =>
  typeof value === 'number' &&
  Number.isFinite(value) &&
  value >= GUIDED_LIVE_DEADLINE_FLOOR_SECONDS &&
  value <= GUIDED_LIVE_DEADLINE_CEILING_SECONDS;

/**
 * The warm-up leg the disclosed budget does NOT cover. `ready` is the only
 * state in which the weights are already loaded; every other state (including
 * `unknown`) may still have to pay for a scale-to-zero start, and paying it
 * twice costs nothing while not paying it at all times a live run out.
 */
export const guidedLiveWarmupLegSeconds = (gpu: GpuState): number =>
  gpu === GPU_STATE.READY ? 0 : GUIDED_LIVE_GPU_WARMUP_CEILING_SECONDS;

/** The whole client-side wait for a run submitted against this GPU state. */
export const guidedLiveCeilingSecondsFor = (gpu: GpuState): number =>
  GUIDED_LIVE_WARM_CEILING_SECONDS + guidedLiveWarmupLegSeconds(gpu);

/**
 * The one place the server's disclosed budget is turned into a client
 * deadline.
 *
 * `deadline_seconds` is the server's GENERATION budget for the accepted run
 * and explicitly excludes GPU warm-up, so the warm-up leg is added back here
 * whenever the GPU is not already `ready`. `localCeilingMs` -- whatever the
 * warm/cold selection decided -- is used only when no usable budget was
 * disclosed. A valid disclosed budget is not clamped to that local guess: the
 * server's generation budget is authoritative, and may move the whole wait
 * past the old local ceiling.
 */
export const resolveGuidedLiveDeadlineMs = (
  localCeilingMs: number,
  deadlineSeconds: number | null | undefined,
  gpu: GpuState,
): number => {
  if (!isGuidedLiveDeadlineDisclosed(deadlineSeconds)) {
    return localCeilingMs;
  }
  const totalSeconds = deadlineSeconds + guidedLiveWarmupLegSeconds(gpu);
  return totalSeconds * 1000 + GUIDED_LIVE_DEADLINE_SLACK_MS;
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
  /**
   * The server's disclosed generation budget for THIS run, verbatim from the
   * wire, or null when nothing usable was disclosed.
   *
   * It lives in the state rather than in a hook ref because the deadline is a
   * function of the disclosure, the GPU warm-up leg, and the local fallback
   * ceiling. A poll can reveal a colder GPU than the submit assumed, so a ref
   * could only latch "a disclosure happened"; the reducer needs the number
   * itself to re-derive the deadline with the newly owed leg.
   */
  disclosedDeadlineSeconds: number | null;
  /**
   * The waiting status the run held when the client stopped waiting, so
   * "Keep waiting" resumes where the run actually was instead of claiming it
   * went back to queued.
   */
  resumeStatus: GuidedLiveStatus | null;
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
       * The GPU state the submit response reported. It decides whether the
       * warm-up leg is owed on top of the disclosed generation budget; absent
       * means `unknown`, which owes the leg.
       */
      gpu?: GuidedLiveGpuState;
      /**
       * The server's disclosed generation budget from the submit response
       * (wire field `deadline_seconds`). Kept verbatim in the state so a later
       * `deadline_raised` can re-derive the deadline if a colder GPU adds a
       * warm-up leg.
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
       * A poll carries the same `deadline_seconds` wire field as the submit
       * response. It is adopted only as a FIRST disclosure -- if the accept
       * already disclosed a budget, a poll disagreeing with it is a server bug,
       * not a resize, and is ignored. Adopting it can never shrink the wait:
       * `deadline_raised` only ever takes the larger of the two.
       */
      disclosedDeadlineSeconds?: number | null;
    }
  | {
      kind: 'deadline_raised';
      deadlineSeconds: number;
      /** GPU state from the poll that prompted the raise; absent means `unknown`. */
      gpu?: GuidedLiveGpuState;
    }
  | { kind: 'tick'; atMs: number }
  | { kind: 'wait_resumed'; atMs: number }
  | { kind: 'cancelled' }
  | { kind: 'failed'; reason: GuidedLiveReason };

export const initialGuidedLiveState = (
  blockedReason: GuidedLiveBlockedReason | null = null,
): GuidedLiveState => ({
  status: blockedReason === null ? GUIDED_LIVE_STATUS.IDLE : GUIDED_LIVE_STATUS.BLOCKED,
  blockedReason,
  runId: null,
  text: null,
  reason: null,
  startedAtMs: null,
  elapsedMs: 0,
  deadlineMs: GUIDED_LIVE_WAIT_CEILING_SECONDS * 1000,
  disclosedDeadlineSeconds: null,
  resumeStatus: null,
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
}

/** Static disclosure: live naming uses the server roster, never demo choices. */
export const GUIDED_LIVE_NAMING_DISCLOSURE: GuidedLiveNamingDisclosure = {
  namesTravelWithTheRequest: false,
  namingSource: 'roster',
};

const assertNever = (value: never): never => {
  throw new Error(`Unhandled guided live action: ${JSON.stringify(value)}`);
};

/**
 * Brief liveStatus vocabulary from the QM contract. Internal reducer statuses
 * stay more granular (queued/warming/describing, ready/degraded) so deadline
 * and tier tests keep their existing assertions; this is the mapping the
 * panel and parent read.
 */
export const GUIDED_LIVE_BRIEF_STATUS = {
  UNAVAILABLE: 'unavailable',
  IDLE: 'idle',
  PENDING: 'pending',
  SUCCEEDED: 'succeeded',
  FAILED: 'failed',
  TIMED_OUT: 'timed_out',
  STOPPED: 'stopped',
} as const;

export type GuidedLiveBriefStatus =
  (typeof GUIDED_LIVE_BRIEF_STATUS)[keyof typeof GUIDED_LIVE_BRIEF_STATUS];

export const guidedLiveBriefStatus = (state: GuidedLiveState): GuidedLiveBriefStatus => {
  switch (state.status) {
    case GUIDED_LIVE_STATUS.BLOCKED:
      return GUIDED_LIVE_BRIEF_STATUS.UNAVAILABLE;
    case GUIDED_LIVE_STATUS.IDLE:
      return GUIDED_LIVE_BRIEF_STATUS.IDLE;
    case GUIDED_LIVE_STATUS.QUEUED:
    case GUIDED_LIVE_STATUS.WARMING:
    case GUIDED_LIVE_STATUS.DESCRIBING:
      return GUIDED_LIVE_BRIEF_STATUS.PENDING;
    case GUIDED_LIVE_STATUS.READY:
    case GUIDED_LIVE_STATUS.DEGRADED:
      return GUIDED_LIVE_BRIEF_STATUS.SUCCEEDED;
    case GUIDED_LIVE_STATUS.TIMED_OUT:
      return GUIDED_LIVE_BRIEF_STATUS.TIMED_OUT;
    case GUIDED_LIVE_STATUS.CANCELLED:
      return GUIDED_LIVE_BRIEF_STATUS.STOPPED;
    case GUIDED_LIVE_STATUS.UNAVAILABLE:
      return GUIDED_LIVE_BRIEF_STATUS.FAILED;
    default:
      return assertNever(state.status);
  }
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
    // still be finishing. Remember where the run was, so the learner can resume
    // the same wait instead of being told to start over (INT-11).
    return terminal({ ...state, elapsedMs }, GUIDED_LIVE_STATUS.TIMED_OUT, {
      reason: GUIDED_LIVE_REASON.CLIENT_DEADLINE,
      resumeStatus: isGuidedLiveWaiting(state.status) ? state.status : state.resumeStatus,
    });
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
  disclosedDeadlineSeconds: null,
  resumeStatus: null,
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
    reason:
      action.tier === DESCRIBE_RESULT_TIER.PROVISIONAL_CPU
        ? GUIDED_LIVE_REASON.CPU_TIER
        : GUIDED_LIVE_REASON.TIER_UNREPORTED,
  };
};

export const guidedLiveReducer = (state: GuidedLiveState, action: GuidedLiveAction): GuidedLiveState => {
  switch (action.kind) {
    case 'gate_changed': {
      if (action.blockedReason !== null) {
        // Losing the media id invalidates any in-flight run. The hook cancels
        // the server side; the reducer stops the wait so a late poll cannot
        // land a sentence into an unavailable panel.
        return {
          ...state,
          status: GUIDED_LIVE_STATUS.BLOCKED,
          blockedReason: action.blockedReason,
          runId: null,
          text: null,
          reason: null,
          disclosedDeadlineSeconds: null,
          resumeStatus: null,
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
      // Kept verbatim, not folded into deadlineMs: the disclosure is generation
      // time, while a later poll may reveal that the run also owes a cold
      // warm-up leg. Keeping the raw number is what makes that later
      // re-derivation possible.
      const disclosedDeadlineSeconds = isGuidedLiveDeadlineDisclosed(action.disclosedDeadlineSeconds)
        ? action.disclosedDeadlineSeconds
        : null;
      const deadlineMs = resolveGuidedLiveDeadlineMs(
        localCeilingMs,
        disclosedDeadlineSeconds,
        action.gpu ?? GPU_STATE.UNKNOWN,
      );
      //
      // Record the run id before advancing the clock: a run the server has
      // just confirmed is precisely the one that still needs cancelling if
      // acceptance itself lands past the deadline.
      const accepted = { ...state, runId: action.runId, deadlineMs, disclosedDeadlineSeconds };
      return advanceClock(accepted, action.atMs);
    }

    case 'deadline_raised': {
      // A submit-time warm pin is a guess. If a later poll reveals the GPU is
      // colder than that, the wait must be allowed to grow back toward the
      // cold-start allowance -- but never to shrink under a learner mid-wait.
      //
      // Re-derived from the SAME disclosed budget rather than from the raw
      // ceiling: a valid disclosure is not clamped by `localCeilingMs`, so the
      // same disclosure and GPU state produce the same raised deadline even
      // when the local ceiling widens. `Math.max` preserves monotonicity if a
      // later observation would resolve lower. The ref that used to suppress
      // this action once anything had been disclosed made a legitimate
      // cold-GPU extension unreachable for the rest of the run.
      if (!isGuidedLiveWaiting(state.status)) {
        return state;
      }
      const capped = Math.min(action.deadlineSeconds, GUIDED_LIVE_WAIT_CEILING_SECONDS);
      const raisedMs = resolveGuidedLiveDeadlineMs(
        Math.max(0, capped) * 1000,
        state.disclosedDeadlineSeconds,
        action.gpu ?? GPU_STATE.UNKNOWN,
      );
      return { ...state, deadlineMs: Math.max(state.deadlineMs, raisedMs) };
    }

    case 'wait_resumed': {
      // The learner looked at a timed-out panel and said keep going. The run is
      // the server's, still possibly finishing, and the client is the only
      // thing that stopped -- so resume the same run rather than spending a
      // second burst on a restart (INT-08, INT-11).
      if (state.status !== GUIDED_LIVE_STATUS.TIMED_OUT || state.runId === null) {
        return state;
      }
      return {
        ...state,
        status: state.resumeStatus ?? GUIDED_LIVE_STATUS.QUEUED,
        reason: null,
        resumeStatus: null,
        // Exclude time spent on the timed-out screen. advanceClock measures
        // elapsed as atMs - startedAtMs, so leaving the original request time
        // in place would charge that pause against the fresh window and
        // immediately re-enter timed_out (INT-08, INT-11).
        startedAtMs: action.atMs - state.elapsedMs,
        deadlineMs: state.elapsedMs + GUIDED_LIVE_KEEP_WAITING_SECONDS * 1000,
      };
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
      // A poll is allowed to make a FIRST disclosure -- a submit that carried
      // no budget followed by polls that do should not leave the client on a
      // locally invented ceiling forever. It is not allowed to revise one: a
      // poll contradicting the accept is a server bug. Either way this only
      // records the number; `deadline_raised` is the sole path to a new
      // deadline and it never shrinks the wait.
      const polledDisclosure = isGuidedLiveDeadlineDisclosed(action.disclosedDeadlineSeconds)
        ? action.disclosedDeadlineSeconds
        : null;
      const seen =
        state.disclosedDeadlineSeconds === null && polledDisclosure !== null
          ? { ...state, disclosedDeadlineSeconds: polledDisclosure }
          : state;
      const next = advanceClock(seen, action.atMs);

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
