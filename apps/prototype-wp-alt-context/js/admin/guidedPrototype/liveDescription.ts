/**
 * Bounded live-description run for the guided prototype.
 *
 * The guided flow already holds a complete, correct saved draft before this
 * module does anything. A live run is therefore always additive: every terminal
 * state here leaves that draft and the Apply button untouched, so a cold GPU
 * can never block the lesson.
 */
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

/** Cold-start ceiling: the GPU warm-up budget the backend advertises. */
export const GUIDED_LIVE_WAIT_CEILING_SECONDS = 510;
const POLL_BASE_MS = 500;
const POLL_CEILING_MS = 5000;

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

export type GuidedLivePhase = 'queued' | 'warming' | 'describing' | 'complete' | 'failed' | 'cancelled';
export type GuidedLiveGpuState = 'unknown' | 'stopped' | 'starting' | 'warming' | 'ready' | 'degraded';
export type GuidedLiveTier = 'provisional_cpu' | 'final_gpu';

export interface GuidedLiveState {
  status: GuidedLiveStatus;
  runId: string | null;
  /** Live description text. Non-null only in ready and degraded. */
  text: string | null;
  /** Machine reason for a non-success terminal state. */
  reason: string | null;
  startedAtMs: number | null;
  elapsedMs: number;
  deadlineMs: number;
}

export type GuidedLiveAction =
  | { kind: 'faces_decided'; decided: boolean }
  | { kind: 'requested'; atMs: number }
  | { kind: 'accepted'; runId: string; deadlineSeconds: number; atMs: number }
  | {
      kind: 'polled';
      phase: GuidedLivePhase;
      gpu: GuidedLiveGpuState;
      atMs: number;
      tier?: GuidedLiveTier | null;
      text?: string | null;
      reason?: string | null;
    }
  | { kind: 'tick'; atMs: number }
  | { kind: 'cancelled' }
  | { kind: 'failed'; reason: string };

export const initialGuidedLiveState = (): GuidedLiveState => ({
  status: GUIDED_LIVE_STATUS.BLOCKED,
  runId: null,
  text: null,
  reason: null,
  startedAtMs: null,
  elapsedMs: 0,
  deadlineMs: GUIDED_LIVE_WAIT_CEILING_SECONDS * 1000,
});

export const isGuidedLiveWaiting = (status: GuidedLiveStatus): boolean => WAITING_STATUSES.includes(status);

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

const terminal = (
  state: GuidedLiveState,
  status: GuidedLiveStatus,
  patch: Partial<GuidedLiveState> = {},
): GuidedLiveState => ({ ...state, text: null, ...patch, status });

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
    // success would hand the learner an empty box and no reason.
    return terminal(state, GUIDED_LIVE_STATUS.UNAVAILABLE, { reason: 'empty_description' });
  }

  const ranWithoutGpu = action.tier === 'provisional_cpu' || (action.tier == null && action.gpu === 'degraded');
  return {
    ...state,
    status: ranWithoutGpu ? GUIDED_LIVE_STATUS.DEGRADED : GUIDED_LIVE_STATUS.READY,
    text,
    reason: ranWithoutGpu ? 'cpu_fallback' : null,
  };
};

export const guidedLiveReducer = (state: GuidedLiveState, action: GuidedLiveAction): GuidedLiveState => {
  switch (action.kind) {
    case 'faces_decided': {
      if (!action.decided) {
        return isGuidedLiveWaiting(state.status) ? state : { ...state, status: GUIDED_LIVE_STATUS.BLOCKED };
      }
      return state.status === GUIDED_LIVE_STATUS.BLOCKED ? { ...state, status: GUIDED_LIVE_STATUS.IDLE } : state;
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
      return { ...state, runId: action.runId, deadlineMs: Math.max(0, capped) * 1000 };
    }

    case 'tick': {
      if (!isGuidedLiveWaiting(state.status) || state.startedAtMs === null) {
        return state;
      }
      const elapsedMs = action.atMs - state.startedAtMs;
      if (elapsedMs >= state.deadlineMs) {
        // The bound is the whole point: stop, say so, and never retry on our
        // own, because a burst run costs money and may still be finishing.
        return terminal({ ...state, elapsedMs }, GUIDED_LIVE_STATUS.TIMED_OUT, { reason: 'client_deadline' });
      }
      return { ...state, elapsedMs };
    }

    case 'polled': {
      if (!isGuidedLiveWaiting(state.status)) {
        return state;
      }
      const elapsedMs = state.startedAtMs === null ? state.elapsedMs : action.atMs - state.startedAtMs;
      const next = { ...state, elapsedMs };

      if (action.phase === 'complete') {
        return completion(next, action);
      }
      if (action.phase === 'failed') {
        return terminal(next, GUIDED_LIVE_STATUS.UNAVAILABLE, { reason: action.reason ?? 'run_failed' });
      }
      if (action.phase === 'cancelled') {
        return terminal(next, GUIDED_LIVE_STATUS.CANCELLED, { reason: action.reason ?? 'run_cancelled' });
      }

      const polledStatus =
        action.phase === 'warming'
          ? GUIDED_LIVE_STATUS.WARMING
          : action.phase === 'describing'
            ? GUIDED_LIVE_STATUS.DESCRIBING
            : GUIDED_LIVE_STATUS.QUEUED;

      return PHASE_RANK[polledStatus] > PHASE_RANK[next.status] ? { ...next, status: polledStatus } : next;
    }

    case 'cancelled': {
      if (!isGuidedLiveWaiting(state.status)) {
        return state;
      }
      return terminal(state, GUIDED_LIVE_STATUS.CANCELLED, { reason: 'stopped_by_operator' });
    }

    case 'failed': {
      if (!isGuidedLiveWaiting(state.status)) {
        return state;
      }
      return terminal(state, GUIDED_LIVE_STATUS.UNAVAILABLE, { reason: action.reason });
    }

    default:
      return state;
  }
};
