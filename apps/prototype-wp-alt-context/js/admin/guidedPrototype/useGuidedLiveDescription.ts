/**
 * Drives one bounded live describe run for the guided prototype.
 *
 * The reducer in `liveDescription.ts` owns every state transition; this hook
 * owns only the I/O and the clock. Keeping the split that way means the wait
 * bounds are testable without a network and the network is testable without
 * re-deriving the state machine.
 */
import { useCallback, useEffect, useMemo, useReducer, useRef } from 'react';

import {
  cancelBulkDescribeRun,
  DESCRIBE_RUN_PHASE,
  DESCRIBE_RUN_STATUS,
  fetchBulkDescribeRun,
  fetchDescribeRunItems,
  isDescribeRunTerminal,
  isGpuState,
  submitBulkDescribeRun,
} from '../api/describeApi';
import type { DescribeRunItemsResponse, DescribeRunResponse } from '../api/describeApi';
import { isFrozenPollFailure } from '../hooks/useDescribeRunProgress';
import {
  GUIDED_LIVE_STATUS,
  GUIDED_LIVE_WAIT_CEILING_SECONDS,
  guidedLiveNamingDisclosure,
  guidedLivePollDelayMs,
  guidedLiveRequestPayload,
  guidedLiveReducer,
  initialGuidedLiveState,
  isGuidedLiveWaiting,
} from './liveDescription';
import type {
  GuidedLiveGpuState,
  GuidedLiveNamingDisclosure,
  GuidedLivePhase,
  GuidedLiveState,
  GuidedLiveTier,
} from './liveDescription';
import { GUIDED_IDENTITY_STATUS } from './state';
import type { GuidedScenario } from './state';

/** Warm-GPU ceiling: the backend's own describe budget with no burst to pay for. */
export const GUIDED_LIVE_WARM_CEILING_SECONDS = 180;

const TICK_MS = 1000;

export interface GuidedLiveDescriptionClient {
  submit: (mediaId: number) => Promise<DescribeRunResponse>;
  poll: (runId: string) => Promise<DescribeRunResponse>;
  items: (runId: string) => Promise<DescribeRunItemsResponse>;
  cancel: (runId: string) => Promise<unknown>;
}

const defaultClient: GuidedLiveDescriptionClient = {
  // The payload builder is the single place that decides what leaves the
  // browser, so the route never sees anything the guided screen invented.
  submit: (mediaId) => submitBulkDescribeRun(guidedLiveRequestPayload(mediaId).media_ids),
  poll: fetchBulkDescribeRun,
  items: fetchDescribeRunItems,
  cancel: cancelBulkDescribeRun,
};

export type GuidedLiveBlockedReason = 'no_faces_decided' | 'no_media';

export interface UseGuidedLiveDescriptionOptions {
  scenario: GuidedScenario;
  /** The real attachment the live run describes; null when the demo has none configured. */
  mediaId: number | null;
  client?: GuidedLiveDescriptionClient;
}

export interface UseGuidedLiveDescriptionResult {
  state: GuidedLiveState;
  disclosure: GuidedLiveNamingDisclosure;
  blockedReason: GuidedLiveBlockedReason | null;
  canRequest: boolean;
  canCancel: boolean;
  request: () => void;
  cancel: () => void;
}

const gpuStateOf = (value: unknown): GuidedLiveGpuState => (isGpuState(value) ? value : 'unknown');

const ceilingSecondsFor = (gpu: GuidedLiveGpuState): number =>
  gpu === 'ready' ? GUIDED_LIVE_WARM_CEILING_SECONDS : GUIDED_LIVE_WAIT_CEILING_SECONDS;

/**
 * The run's own terminal statuses outrank `phase`. A run can settle
 * (`completed_with_errors`, `failed`, `cancelled`) while `phase` still reads as
 * a running sub-phase; without this the guided screen would poll a finished run
 * all the way to its client deadline and report a timeout that never happened.
 * `isDescribeRunTerminal` is the one shared owner of that question -- guessing
 * it locally is how the two surfaces drift.
 */
const terminalPhaseFor = (status: DescribeRunResponse['status']): GuidedLivePhase => {
  switch (status) {
    case DESCRIBE_RUN_STATUS.FAILED:
      return DESCRIBE_RUN_PHASE.FAILED;
    case DESCRIBE_RUN_STATUS.CANCELLED:
      return DESCRIBE_RUN_PHASE.CANCELLED;
    default:
      return DESCRIBE_RUN_PHASE.COMPLETE;
  }
};

const phaseOf = (run: DescribeRunResponse): GuidedLivePhase => {
  switch (run.phase) {
    case DESCRIBE_RUN_PHASE.COMPLETE:
    case DESCRIBE_RUN_PHASE.FAILED:
    case DESCRIBE_RUN_PHASE.CANCELLED:
      return run.phase;
    case DESCRIBE_RUN_PHASE.WARMING:
    case DESCRIBE_RUN_PHASE.DESCRIBING:
    case DESCRIBE_RUN_PHASE.QUEUED:
      return isDescribeRunTerminal(run.status) ? terminalPhaseFor(run.status) : run.phase;
    default:
      return DESCRIBE_RUN_PHASE.QUEUED;
  }
};

/**
 * Null means "this run produced nothing for the image on screen". Falling back
 * to `items[0]` would show a confident sentence about a different photograph,
 * which is worse than showing nothing at all.
 */
const draftOf = (
  items: DescribeRunItemsResponse,
  mediaId: number,
): { text: string | null; tier: GuidedLiveTier | null } | null => {
  const item = items.items.find((row) => row.media_id === mediaId);
  if (item === undefined) {
    return null;
  }
  return { text: item.alt_text_draft ?? null, tier: item.tier ?? null };
};

export const useGuidedLiveDescription = ({
  scenario,
  mediaId,
  client = defaultClient,
}: UseGuidedLiveDescriptionOptions): UseGuidedLiveDescriptionResult => {
  const [state, dispatch] = useReducer(guidedLiveReducer, undefined, initialGuidedLiveState);

  // A run generation fences every in-flight promise: a poll resolving after a
  // cancel or a new request must not write into the run that replaced it.
  const generationRef = useRef(0);
  const attemptRef = useRef(0);

  // "Decided" means every face has an answer -- confirmed OR marked
  // unidentified. Counting only confirmations let a learner who marked every
  // face unidentified stay blocked forever, and let a learner who answered one
  // of two faces start a run while the other was still open.
  const facesDecided = scenario.identities.every(
    (identity) => identity.status !== GUIDED_IDENTITY_STATUS.UNCONFIRMED,
  );
  const blockedReason: GuidedLiveBlockedReason | null = !facesDecided
    ? 'no_faces_decided'
    : mediaId === null
      ? 'no_media'
      : null;

  const waiting = isGuidedLiveWaiting(state.status);
  const runId = state.runId;

  // Re-opening a face while a run is in flight invalidates that run. The
  // reducer stops the screen; the burst it started keeps costing money until
  // the server hears about it, so fence the generation and cancel the run id.
  const waitingRef = useRef<{ waiting: boolean; runId: string | null }>({ waiting, runId });
  waitingRef.current = { waiting, runId };

  useEffect(() => {
    const decided = blockedReason === null;
    if (!decided && waitingRef.current.waiting) {
      generationRef.current += 1;
      const inFlight = waitingRef.current.runId;
      if (inFlight !== null) {
        void client.cancel(inFlight).catch(() => undefined);
      }
    }
    dispatch({ kind: 'faces_decided', decided });
  }, [blockedReason, client]);

  const request = useCallback(() => {
    if (blockedReason !== null || waiting || mediaId === null) {
      return;
    }
    const generation = generationRef.current + 1;
    generationRef.current = generation;
    attemptRef.current = 0;
    dispatch({ kind: 'requested', atMs: Date.now() });

    void client
      .submit(mediaId)
      .then((run) => {
        if (generationRef.current !== generation) {
          // The learner stopped waiting while the submit was in flight. The run
          // exists on the server now, so a burst it started keeps costing money
          // unless we cancel the run id we only just learned.
          void client.cancel(run.run_id).catch(() => undefined);
          return;
        }
        dispatch({
          kind: 'accepted',
          runId: run.run_id,
          deadlineSeconds: ceilingSecondsFor(gpuStateOf(run.gpu_state)),
          atMs: Date.now(),
        });
      })
      .catch(() => {
        if (generationRef.current === generation) {
          dispatch({ kind: 'failed', reason: 'submit_failed' });
        }
      });
  }, [blockedReason, client, mediaId, waiting]);

  const cancel = useCallback(() => {
    if (!waiting) {
      return;
    }
    generationRef.current += 1;
    // The screen stops either way. A cancel the server never heard still leaves
    // the learner with a stopped wait rather than a spinner nobody owns.
    dispatch({ kind: 'cancelled' });
    if (runId !== null) {
      void client.cancel(runId).catch(() => undefined);
    }
  }, [client, runId, waiting]);

  useEffect(() => {
    if (!waiting) {
      return undefined;
    }
    const interval = setInterval(() => dispatch({ kind: 'tick', atMs: Date.now() }), TICK_MS);
    return () => clearInterval(interval);
  }, [waiting]);

  // The poll chain reschedules itself. Keying a `setTimeout` on `state.elapsedMs`
  // instead meant the 1s tick tore the timer down and re-armed it every second,
  // so once the backoff passed 1000ms the poll never fired at all and the run
  // sat in QUEUED until the client deadline. Fake timers hid it; a browser would
  // not have. Deps hold only the identity of the run being polled.
  useEffect(() => {
    if (!waiting || runId === null || mediaId === null) {
      return undefined;
    }
    const generation = generationRef.current;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const live = (): boolean => !cancelled && generationRef.current === generation;

    const schedule = (): void => {
      timer = setTimeout(() => void poll(), guidedLivePollDelayMs(attemptRef.current));
    };

    const poll = async (): Promise<void> => {
      try {
        const run = await client.poll(runId);
        if (!live()) {
          return;
        }
        const phase = phaseOf(run);
        const gpu = gpuStateOf(run.gpu_state);

        if (phase !== DESCRIBE_RUN_PHASE.COMPLETE) {
          attemptRef.current += 1;
          // A submit-time warm pin can be wrong. If the run reports a colder GPU
          // than the pin assumed, give the wait back its cold budget.
          dispatch({ kind: 'deadline_raised', deadlineSeconds: ceilingSecondsFor(gpu) });
          dispatch({ kind: 'polled', phase, gpu, atMs: Date.now() });
          if (live()) {
            schedule();
          }
          return;
        }

        const draft = draftOf(await client.items(runId), mediaId);
        if (!live()) {
          return;
        }
        if (draft === null) {
          dispatch({ kind: 'polled', phase, gpu, atMs: Date.now(), reason: 'item_missing' });
          return;
        }
        dispatch({ kind: 'polled', phase, gpu, atMs: Date.now(), ...draft });
      } catch (error) {
        if (!live()) {
          return;
        }
        if (!isFrozenPollFailure(error)) {
          // A hard failure will not heal by waiting. Say so now rather than
          // spending the learner's whole deadline on a dead channel.
          dispatch({ kind: 'failed', reason: 'poll_failed' });
          return;
        }
        // Abort/timeout is transient: back off and retry inside the deadline the
        // tick already enforces.
        attemptRef.current += 1;
        dispatch({ kind: 'tick', atMs: Date.now() });
        schedule();
      }
    };

    schedule();
    return () => {
      cancelled = true;
      if (timer !== null) {
        clearTimeout(timer);
      }
    };
  }, [client, mediaId, runId, waiting]);

  const disclosure = useMemo(() => guidedLiveNamingDisclosure(scenario), [scenario]);

  return {
    state,
    disclosure,
    blockedReason,
    canRequest: blockedReason === null && state.status !== GUIDED_LIVE_STATUS.BLOCKED && !waiting,
    canCancel: waiting,
    request,
    cancel,
  };
};
